# 隐患排查 — RoCE GID index3 全零致 NCCL 建链必败（对端断电残留）（2026-09-03）

> 督导复盘（2026-09-03）：03 号节点两次硬断电后，01 号节点 rank0 反复"拉起即崩"，初判为 400K 长 prefill 高压 / NCCL 通讯问题，最终定位为 **RoCE GID 表空洞**——对端断电引发的网络层暗伤，非引擎 bug。

**工作流**：事故响应（根因分析 + 自愈链隐患排查固话）
**参与成员**：Rex（SRE）· 督导复盘确认

---

## 📌 TL;DR

- **根因链条**：对端硬断电 → 本机直连 RoCE 口链路反复 down/up → **NetworkManager 在链路抖动时撤掉该口静态 IP，链路恢复后不自动加回**（connection 显示 activated、netplan 配置完好，但地址未应用）→ 该口 **IB GID index3 变全零** → **NCCL 建链必败**。
- **rank0 报错实锤**：`ibv_modify_qp failed with 61 No data available, on dev rocep1s0f0:1, curr state INIT→RTR, local GID ::`——local GID 为空是决定性信号。
- **影响**：15:30 之后的所有拉起循环（healthcheck 触发重建、worker systemd 反复重启）全部死在 NCCL 建链同一处——rank0 每次初始化到建链即崩，容器却表现为反复退出，极易误判为引擎/显存/负载问题。
- **修复**：`nmcli device reapply` 不够（NM 记账不刷新），**必须 disconnect + connect 硬复位**该口 → IP 回来、GID 恢复 → 自愈链自然拉起成功。
- **严重度**：🟠 高（网络层暗伤，可复发，且极易误诊）

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 故障现象 | rank0 反复拉起即崩；`ibv_modify_qp errno 61`；local GID `::` |
| 根因 | 对端断电 → NM 撤静态 IP 不自动回 → **RoCE GID index3 全零** |
| 判定关键 | 全集群审计仅 01 两个口有此暗伤，02/03/04 八口 GID 全部正常 |
| 修复动作 | `nmcli device disconnect + connect` 硬复位（reapply 无效） |
| 固化手段 | `gid_preflight.sh` 预检（检查 + 自动复位）+ 集成进自愈链重建流程 |
| 复发风险 | 🔴 高——对端每次硬断电都可能触发此症状 |
| 诊断口诀 | rank0 日志 `ibv_modify_qp errno 61` = **先查 GID**，勿误判为 NCCL/驱动问题 |

---

## 1. 根因链条（证据链）

```
03 号机 14:52 / 15:24 两次硬断电
  → 01 上与 03 直连的两个 CX-7 口链路反复 down/up
    → NetworkManager 在链路抖动时撤掉这两个口的静态 IP
      （connection 显示 activated、netplan 配置完好，但地址没应用——NM 应用态与配置脱节）
        → 口的 RoCE GID 表 index3 变全零
          → NCCL 建链必败（rank0: local GID ::）
```

- **rank0 报错（决定性证据）**：
  ```
  RuntimeError: Worker failed ... NCCL unhandled system error
  Call to ibv_modify_qp failed with 61 No data available,
  on dev rocep1s0f0:1, curr state INIT→RTR, local GID ::          ← GID 为空
  remote GID ::ffff:<RING_SUBNET>.2
  ```
- **波及范围**：15:30 后的拉起循环（healthcheck 15:31 触发重建、worker systemd 反复重启：02/03/04 各 4 次、01 两次）全部死在同一处——02/03/04 容器一直 healthy 干等，rank0 每次初始化到 NCCL 建链就崩。
- **次要因素（非主因）**：①03/04 重启时间差导致 rendezvous 凑不齐；②03 在 15:04 有一次 NVRM 显存分配失败（换代初始化的已知内存边界特性）。

## 2. 排查路径（为什么会误判）

1. 现象层：引擎 4 连崩（137/OOM crash_dump ×3）→ 一度指向 **400K 长 prefill 高压**（与 C1 崩溃模式相似）
2. 自愈层：自愈链 4 次拉起全部失败 → 判定"自愈失败"
3. 容器层：`docker logs` 见 `Engine core initialization failed` + `ibv_modify_qp errno 61`
4. **转折点**：检查 RoCE GID 表 → 01 的 `rocep1s0f0` GID index3 全零（其他三机 idx3 均有效）
5. 复核：接口 down/up 无法重建 GID 布局（驱动注册固有布局）；`nmcli reapply` 不刷新 NM 记账
6. 修复：`nmcli device disconnect + connect` 硬复位 → IP 回来、GID 恢复（`::ffff:<RING_SUBNET>.1 / <RING_SUBNET>.2`）、绑定口 ping 通 → 15:48 systemd 自然拉起 → 15:54 health=200，四机 healthy 稳定至今

> **教训**：NCCL 建链失败 ≠ NCCL/驱动问题。`ibv_modify_qp errno 61` + `local GID ::` 是 RoCE GID 空洞的**独有指纹**，必须最先排除。

## 3. 隐患排查固话（已落地）

### 3.1 新增预检脚本 `gid_preflight.sh`

部署于四机 `/opt/_PH_INSTALL_/scripts/gid_preflight.sh`，功能：

| 模式 | 行为 |
|------|------|
| `bash gid_preflight.sh` | 只读检查本机全部 `rocep*` 口 `gids/3` 是否全零 |
| `bash gid_preflight.sh --fix` | 检查 + 对空 GID 口执行 `nmcli disconnect/connect` 硬复位并重查 |
| `bash gid_preflight.sh --all` | 四机（186-189）巡检，只读 |
| `bash gid_preflight.sh --all --fix` | 四机巡检 + 修复 |

退出码：`0` = 全部口 GID 有效（或已修复）；`1` = 仍有异常。

### 3.2 自愈链集成（重建/拉起容器前必检）

| 脚本 | 插入点 | 作用 |
|------|--------|------|
| `healthcheck-rebuild.sh` | `docker rm` 触发重建前 | 空 GID 先复位再重建，避免重建死循环 |
| `monitor_tp4_head_v043.sh` | `start_tp4_head_v043.sh` 前 | rank0 拉起前确保本机口 GID 健康 |
| `monitor_tp4_worker_v043.sh` | `start_tp4_worker_v043.sh` 前 | 每台 worker 拉起前自查 |

- 预检为 `--fix` 模式：发现空 GID 自动 `nmcli` 复位后再拉起；复位后仍异常则告警并继续（可能非 GID 根因）
- 配套：`/etc/sudoers.d/99-gid-preflight` 授予 `<USER>` **仅 nmcli** 的 NOPASSWD（最小权限，`visudo -c` 校验通过），使自愈链可无交互自动修复
- 幂等：脚本已含 `gid_preflight` 标记，重复执行不重复插入

### 3.3 落地验证

- 四机 8 个 RoCE 口 `gids/3` 巡检：**全部 [OK]**（IPv4-mapped 有效 GID）
- 修复前 01 两个口 index3 全零（`0000:...:0000`）→ 修复后 `::ffff:<RING_SUBNET>.1 / <RING_SUBNET>.2`
- 三个自愈脚本 `bash -n` 语法通过，集成点确认在拉起/重建动作之前

## 4. 诊断口诀与预防清单

### 诊断口诀
> **rank0 日志出现 `ibv_modify_qp errno 61`（`local GID ::`）＝ 先查 GID，不要误判为 NCCL/驱动问题。**

```bash
# 一键四机巡检（任一节点执行）
bash /opt/_PH_INSTALL_/scripts/gid_preflight.sh --all
# 发现空 GID 时自动复位
bash /opt/_PH_INSTALL_/scripts/gid_preflight.sh --all --fix
```

### 可复发坑与预防

| 触发条件 | 症状 | 预防 |
|----------|------|------|
| 对端节点硬断电 | 本机直连口 GID index3 全零 | 自愈链已内置预检（§3.2），拉起前自动复位 |
| NM 应用态与配置脱节 | connection activated 但地址未应用 | 预检直接读 `/sys/class/infiniband/*/ports/1/gids/3`，不依赖 NM 状态 |
| 集群反复拉起失败 | rank0 每次初始化到 NCCL 建链即崩 | 先跑 `gid_preflight.sh --all` 排除 GID 后再查引擎 |

---

## 附录：涉及文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `gid_preflight.sh` | 四机 `/opt/_PH_INSTALL_/scripts/` | 新增预检脚本（含根因注释 + 诊断口诀） |
| `healthcheck-rebuild.sh` | 四机 `/opt/_PH_INSTALL_/scripts/` | 已集成预检（docker rm 前） |
| `monitor_tp4_head_v043.sh` | 01 `/home/<USER>/w6-kit/` | 已集成预检（start 前） |
| `monitor_tp4_worker_v043.sh` | 四机 `/home/<USER>/w6-kit/` | 已集成预检（start 前） |
| `/etc/sudoers.d/99-gid-preflight` | 四机 | NOPASSWD nmcli（最小权限） |
