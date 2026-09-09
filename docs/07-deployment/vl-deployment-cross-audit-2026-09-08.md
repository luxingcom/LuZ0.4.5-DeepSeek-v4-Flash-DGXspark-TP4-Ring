# VL 部署方案交叉审核报告（Code Reviewer Cody）

**审核对象**：[`G1R7VL-BASELINE-DELIVERY-20260908.md`](../01-research-reports/G1R7VL-BASELINE-DELIVERY-20260908.md)（基准文档）所述 VL 切换方案与遗留问题处置
**审核方式**：只读 SSH 实测（node01/node02/node03/node04 四机逐台核验），零修改
**审核日期**：2026-09-08
**审核人**：Cody · 代码审查师（EngineeringAssuranceTeam）

> **关联报告**：
> - **姊妹篇**：[服务器治理面审计](vl-governance-audit-2026-09-08.md)（治理面专项审计，与本报告 P0 清单相互印证）。本报告 P0-1~P0-4 阻塞项与两报告 P0/P1 动作项已随切换窗口落实，执行回执见[切换执行审计](../06-verification/vl-switch-execution-audit-2026-09-08.md)（八项全 PASS）。
> - **验收上下文**：[上线六门验收](../06-verification/vl-acceptance-sixgates-2026-09-08.md) · [FINAL-METRICS-VL](../03-final-metrics/FINAL-METRICS-VL-2026-09-09.md)
> - **根因排查链**：[服务器取证](../01-research-reports/vl-server-side-forensics-2026-09-09.md) · [投机头调研](../01-research-reports/spec-head-research-2026-09-09.md)

---

## 0. 总体结论

**结论：Request Changes（有条件放行）——切换方案主体成立，但有 2 个 P0 阻塞项必须在切换窗口内同步处理，否则切换当天即会出现「自愈链用错模型名 400 / daily-smoke 误报」与「8003 网关完全拒绝 VL 模型名」两类故障。**

- 切换核心链路（脚本 md5、镜像就位、回退基线、guard 治理链）全部实测通过，runbook 主体可执行。
- 交接文档 §4 步骤 2 的 md5 矛盾点已定谳（见 §2），**不影响执行，但 runbook 文本须按 §2 修正**。
- R1 的 8001 代理长文本路由**未实现**（与文档自述一致，非阻塞但需明确排期）；R2-R5 复核确认非阻塞。

---

## 1. 审核项判定表

| # | 审核项 | 判定 | 关键证据（摘要，全文见 §3） |
|---|--------|------|------------------------------|
| 1a | runbook 步骤 1（脚本就位） | **PASS** | 四机 `.vl-final` 就位；head md5=`b0b3561a…`（node01），worker md5=`936963ee…`（node02/node03/node04 三份一致） |
| 1b | md5 矛盾点（§4 的 1a8c5090/0ee0fde5 vs §3 的 b0b3561a/936963ee） | **定谳：两者都对，但 §4 表述误导** | `tail -n +6`（去掉 5 行 VL-FINAL 注释头后）md5 恰为 `1a8c5090595f…`（head）/`0ee0fde5ee49…`（worker）。见 §2 |
| 1c | 回退基线 `.bak-window-20260907` | **PASS** | 四机就位；head live(`cf165e09`) == bak 逐字节一致；worker live(`31d60685`) == bak 逐字节一致 |
| 1d | F1 缓存卷非空 | **PASS（带 1 个说明项）** | flashinfer-cache-f1 四机非空（52-54 文件，含 `sparse_mla_sm120.so` + `sampling.so`，mtime 09-08 08:45-08:48 = boot2 暖缓存）。**tilelang-cache-f1 四机为空目录（0 文件）**——VL 形态下 tilelang 不再编译（TK512 已退役），空属预期，但 runbook §4 前置条件 2 的表述应修正 |
| 2 | 镜像就位 | **PASS** | registry digest `sha256:<BAKE_IMAGE_DIGEST>` 实测一致（curl registry API 直接确认）；node02/node03/node04 image ID = `<BAKE_IMAGE_DIGEST>`；node01 显示 `<BAKE_IMAGE_DIGEST>`（containerd snapshotter 显示差异，文档 §8 已有 RootFS 同源审计背书，且 manifest digest 四机一致） |
| 3 | R1-R5 处置 | **CONCERN** | R1：8001 代理 `concurrency_proxy_v2.py` **无任何模型名/token 长度路由逻辑**（grep "model" 零命中业务逻辑），长文本路由未实现——与文档自述一致，属运维待办，非切换阻塞。R2-R5 复核文档描述属实，非阻塞 |
| 4 | 治理链兼容性 | **FAIL（P0 ×1 + P1 ×1）** | guard→restart→systemd→monitor→live 脚本链路**自动跟随 VL**（PASS 部分）；但 `monitor_tp4_head_v043.sh:69` 预热请求硬编码 `deepseek-v4-flash-0731`（P0）；`daily_smoke.py:9` 同样硬编码且每日 09:33 自动触发（P0）；`healthcheck_hardened.sh:128` 默认值 0731 但支持 `SERVED_MODEL_NAME` env 注入，而 `vllm.env` 只有 `VLLM_API_KEY` 未注入（P1，有 BUSY 保护兜底） |
| 5 | 8003 网关面 | **FAIL（P0 ×1）** | `~/responses_gateway/main.py` MODEL_ALIAS 严格白名单（unknown→404），只认 `local-v4-flash`/`deepseek-v4-flash`/`deepseek-v4-flash-0731`。VL 上线后调用方若用 `deepseek-v4-flash-vision-exp` 会被 404 拒绝。embeddings 路径走 EMBED_URL(<NODE_IP>:8022) 独立转发，**确认不受影响** |

---

## 2. md5 矛盾点定谳（专项）

**现象**：交接文档 §3 说定稿脚本 md5 为 head=`b0b3561ae8f4b95a399ac349b819f4c7` / worker=`936963ee49aad295459cba45a02baa06`，§4 步骤 2 却说拷贝后验收 md5 应为 head=`1a8c5090` / worker=`0ee0fde5`。

**实测定谳**（node01 head、node02 worker 实测）：

```
$ md5sum start_tp4_head_v043.sh.vl-final
b0b3561ae8f4b95a399ac349b819f4c7          ← §3 的值，整文件 md5
$ tail -n +6 start_tp4_head_v043.sh.vl-final | md5sum
1a8c5090595f643f3f7446160c4fab30          ← §4 的值（前 8 位吻合），去掉前 5 行注释头后的 md5

$ md5sum start_tp4_worker_v043.sh.vl-final
936963ee49aad295459cba45a02baa06          ← §3 的值
$ tail -n +6 start_tp4_worker_v043.sh.vl-final | md5sum
0ee0fde5ee495e83f018f34c3188a414          ← §4 的值（前 8 位吻合）
```

**结论**：两对 md5 描述的是**同一文件的两种口径**——§3 是整文件（含 5 行 VL-FINAL 注释块），§4 是剥离注释头后的正文。`cp` 是整文件拷贝，拷贝后整文件 md5 **不会变成 §4 的值**。

**推测成因**：`.vl-final` 定稿流程可能是「正文先写、md5 先记」再加注释头，§4 沿用了加头前的旧 md5 快照，未随定稿更新。

**影响与修正**：
- 不影响实际部署正确性（文件内容本身正确，与 .bak 基线 diff 恰为文档所述 6 处差异 + 5 行注释头）。
- **runbook §4 步骤 2 的验收值必须改**：拷贝后应验收 `md5sum` 整文件 = `b0b3561a…`（head）/ `936963ee…`（worker×3 互相一致）。若运维照文档写 `1a8c5090` 去校验，会误判「拷贝出错」并可能无谓中止切换窗口。**这是 P0 级文档修正**（错误指令会直接卡死窗口执行）。

---

## 3. 各审核项详细证据

### 3.1 审核项 1：runbook 逐行核对

**脚本就位（PASS）**：
```
node01: b0b3561ae8f4b95a399ac349b819f4c7  start_tp4_head_v043.sh.vl-final（worker 版不存在，符合 head/worker 分置）
node02/node03/node04: 936963ee49aad295459cba45a02baa06  start_tp4_worker_v043.sh.vl-final（三份一致）
```

**回退基线（PASS）**：
```
node01: live head  = cf165e09… = .bak-window-20260907（diff 逐字节一致）
     live worker(31d60685，本机历史残留) = worker bak 一致
node02/node03/node04: live worker = 31d60685dd9a5f84d5303f55c7d559ab = .bak-window-20260907（逐字节一致）
```
live 与回退基线完全一致 → 回退链 `cp .bak → guard` 可用，且回退后 served-model-name 回到 `deepseek-v4-flash-0731`。

**`.vl-final` vs `.bak` 差异核对（PASS）**：diff 输出恰为 5 行注释头 + 文档所述 6 处差异（镜像 tag、skip-ops env、权重挂载 `dsv4-vision-exp`、双 `-f1` 缓存卷、served 名 `deepseek-v4-flash-vision-exp`、k=7→6），**零意外差异项**。

**F1 缓存卷（PASS + 1 说明项）**：
```
四机 flashinfer-cache-f1：15M / 52-54 文件 / 0.6.18/121a/cached_ops/ 下
  sparse_mla_sm120.so (925152B, 09-08 08:45) + sampling.so (2136096B, 09-08 08:48)
  → boot2 暖缓存实证，与文档 §8 审计结论吻合
四机 tilelang-cache-f1：空目录（0 文件）
```
说明项：tilelang-cache-f1 为空在 TK512 退役后属预期（VL 形态不再触发 tilelang JIT），但 runbook 前置条件 2 写「tilelang-cache-f1 存在且非空」，与实测不符，应修正为「flashinfer-cache-f1 非空（tilelang-cache-f1 为空属预期，TK512 已退役）」，避免运维按文档检查时误判。**P2 文档修正**。

### 3.2 审核项 2：镜像就位（PASS）

```
registry API 实测（curl HEAD manifest）:
  LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring
  → Docker-Content-Digest: sha256:<BAKE_IMAGE_DIGEST>  ✅ 与文档一致

四机 docker images --no-trunc --digests:
  manifest digest 四机全部 = sha256:<BAKE_IMAGE_DIGEST>（一致）✅
  image ID：node02/node03/node04 = <BAKE_IMAGE_DIGEST>；node01 = <BAKE_IMAGE_DIGEST>（containerd snapshotter 显示差异）
```
node01 的 image ID 显示差异与文档 §8 镜像审计结论一致（RootFS 层序列 md5 已证同源），manifest digest 四机一致已构成充分判据。**通过**。

> 注：为脱敏计，本节 registry manifest digest 与本地 imageID 两类 sha256 指纹统一以 `<BAKE_IMAGE_DIGEST>` 占位——二者为**不同**指纹值（manifest digest 为分发口径，本地 imageID 为节点本地口径），"显示差异"指 node01 的本地 imageID 口径与其余三机不同。

### 3.3 审核项 3：残余风险 R1-R5（CONCERN）

**R1（#4973 IMA >12K 纯文本）——8001 路由未实现，确认属实**：
- `concurrency_proxy_v2.py` 全文 grep "model" 无任何业务路由逻辑（仅流式转发、并发准入、TTFT 预算）。
- 该代理是**单后端全量转发**（0.0.0.0:8001→127.0.0.1:8002），同一时刻只服务一个引擎，**当前架构下物理上无法做「VL/V5b 按内容分流」**——切到 VL 后 V5b 已停，没有可路由的文本线后端。
- **处置建议**：R1 缓解在「单引擎生产」形态下退化为**客户端使用约束**（>12K 纯文本请求暂缓/降级），8001 层路由属于「双引擎并存」的后续工程（需上层路由或多实例），**不应作为本次切换的阻塞项**，但应：① 在交接文档 R1 行明确「单引擎期缓解 = 调用方约束 + Gate4 哨兵监控」；② 将双活路由列入后续排期（对应 D4 待办，P2）。判定：**非阻塞，CONCERN 保留**。

**R2-R5**：文档描述与实测/逻辑复核相符（k=6 位置 4-6 低接受率有 per-position 数据背书；R3/R4/R5 均为「形态决策已锁定」类残留），**均非阻塞**。PASS。

### 3.4 审核项 4：治理链兼容性（FAIL —— 2 个 P0 + 1 个 P1）

**链路跟随性（PASS 部分）**：
```
w9r4_restart_guard.sh → bash w9r4_window_restart.sh
  → systemctl start/stop vllm-tp4-head / vllm-tp4-worker（四机）
  → vllm-tp4-head.service: ExecStart=~/w6-kit/monitor_tp4_head_v043.sh
  → monitor_tp4_head_v043.sh:26: NO_WAIT=1 bash ~/w6-kit/start_tp4_head_v043.sh
  → monitor_tp4_worker_v043.sh:37: bash ~/w6-kit/start_tp4_worker_v043.sh
```
整条链**全部引用 live 脚本名（start_tp4_*_v043.sh），零镜像 tag/模型名硬编码于启动路径** → `cp .vl-final → live` 后 guard 重启即自动跑 VL。guard flock 互斥、D2 fail-fast（TCPStore 120s）机制完好。

**硬编码问题（FAIL 部分）**：

| 文件 | 行 | 问题 | 影响 |
|------|-----|------|------|
| `~/w6-kit/monitor_tp4_head_v043.sh` | 69 | 预热请求 body 硬编码 `"model":"deepseek-v4-flash-0731"` | VL 启动后 monitor 预热请求 → vLLM 返回 404 model not found → `curl -sf` 失败 → WARMUP_RC 记录失败。**不致命**（代码对预热失败仅记日志，`docker wait` 仍正常），但预热功能失效 + 日志噪音；若后续有人把预热改成失败即退出会变致命 |
| `~/w6-kit/daily_smoke.py` | 9 | body 硬编码 `"model": "deepseek-v4-flash-0731"`，打 `127.0.0.1:8001` | daily-smoke.timer **每日 09:33 自动触发**，VL 上线后次日起每日误报模型不存在 |
| `<INSTALL_DIR>/scripts/healthcheck_hardened.sh` | 128 | `SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-deepseek-v4-flash-0731}"`，探针打 8001 | 默认值错误；`vllm-healthcheck.service` 的 EnvironmentFile `<INSTALL_DIR>/secrets/vllm.env` **只含 VLLM_API_KEY，未注入 SERVED_MODEL_NAME** → 探针将用错模型名。有 BUSY 兜底：探针失败但 8002 /health 存活 → 判 BUSY 不重建；连续 2 次全不可达才重建。**风险**：若引擎真卡死时探针本来就该报障，模型名错误会让探针永远走「请求失败」分支而不是「超时」分支——4xx 失败同样计入 FAIL 路径，但 8002 存活兜底使其多数情况停在观测级。综合判 P1（自愈链降级而非失能） |
| `<INSTALL_DIR>/scripts/check_vllm_script.sh` | 99 | 检查依赖文件 `<INSTALL_DIR>/models/deepseek-v4-flash-0731/config.json` | 该文件是 V5b 权重路径，VL 下线 0731 权重仍在本机（未删除）→ 检查仍通过。**当前无调用方**（grep systemd/cron 零命中）→ 无实际影响，P2 备注 |
| 其余（crash_dump.sh / vllm_logdump.sh / healthcheck-rebuild.sh / monitor_tp4_worker_v043.sh / watchdog_hardened.sh） | — | grep `0731|V5b|vision-exp` 零命中 | 模型名无关，**无需改动** ✅ |

### 3.5 审核项 5：8003 网关面（FAIL —— 1 个 P0）

文件：node02 `~/responses_gateway/main.py`（v2.0-slim，systemd --user `responses-gateway`，端口 8003）

**路由表实测**：
```python
SERVED_MODEL = os.environ.get("SERVED_MODEL", "deepseek-v4-flash-0731")
PUBLIC_MODEL = os.environ.get("PUBLIC_MODEL", "local-v4-flash")
LEGACY_MODEL = os.environ.get("LEGACY_MODEL", "deepseek-v4-flash")
MODEL_ALIAS = { PUBLIC_MODEL: SERVED_MODEL, LEGACY_MODEL: SERVED_MODEL, SERVED_MODEL: SERVED_MODEL }
```
runtime env（systemd --user unit）确认 `SERVED_MODEL=deepseek-v4-flash-0731`。

- `/v1/chat/completions` 与 `/v1/responses`：**严格白名单**（`if model not in MODEL_ALIAS: return 404`）→ VL 模型名 `deepseek-v4-flash-vision-exp` 会被 404 拒绝。**必须改**。
- `/v1/models`：只列 PUBLIC/LEGACY/SERVED 三个名 → VL 名不在列表，客户端按 models 列表发现模型的会看不到 VL。
- **embeddings 路径确认不受影响**：`/v1/embeddings` 直接转发 `EMBED_URL=http://<NODE_IP>:8022`（Qwen3-Embedding 独立服务），与 8001/VL 无耦合 ✅。
- 注意：8003 → `VLLM_URL=http://<NODE_IP>:8001` → 单引擎。VL 上线后 8003 的 chat 流量全部落到 VL 引擎，**旧的 `local-v4-flash` 名将被映射到 `deepseek-v4-flash-0731` 并被 vLLM 404**——即不做任何改动的话，8003 的 chat/completions **整体不可用**（不只是 VL 新名字加不进来的问题）。这升级了问题严重性：**8003 改动是切换的硬前置**。

---

## 4. 切换前必须解决的阻塞项清单

### P0（切换窗口内必须完成，否则当天故障）

| # | 阻塞项 | 位置 | 具体动作 | 故障场景（若不做） |
|---|--------|------|----------|---------------------|
| P0-1 | runbook §4 步骤 2 md5 验收值错误 | 交接文档 | 将验收值改为整文件 md5：head=`b0b3561ae8f4b95a399ac349b819f4c7`、worker=`936963ee49aad295459cba45a02baa06`（或注明两种口径），并同步修正前置条件 2 的 tilelang 表述 | 运维照文档校验 `1a8c5090` 不中 → 误判拷贝失败 → 窗口中止或手工核对浪费停机时间 |
| P0-2 | 8003 网关模型映射不含 VL | node02 `~/responses_gateway/main.py` + `responses-gateway` user unit | 见 §5 行级建议；改完 `systemctl --user restart responses-gateway` 并用 `curl 8003/v1/models` + 一条 chat 探针验收 | VL 上线瞬间 8003 chat/completions **整体 404**（旧名映射的 0731 已下线，新名不在白名单）——所有经 8003 的 WorkBuddy 流量中断 |
| P0-3 | monitor head 预热模型名硬编码 | node01 `~/w6-kit/monitor_tp4_head_v043.sh:69` | 将第 69 行 `"model":"deepseek-v4-flash-0731"` 改为 `"model":"deepseek-v4-flash-vision-exp"`（建议改为从 `grep -o 'served-model-name [a-z0-9-]*' ~/w6-kit/start_tp4_head_v043.sh` 动态提取，或最低限度先静态替换；改前按 D5 纪律 `.bak` 留档） | 每次 guard 重启后预热请求 404，预热失效（长上下文首请求变慢，正是 W9R11 预热要解决的问题回归）+ 日志噪音误导值班 |
| P0-4 | daily_smoke 模型名硬编码 | node01 `~/w6-kit/daily_smoke.py:9` | 改为 `deepseek-v4-flash-vision-exp`（或 env 化）；建议先 `systemctl stop daily-smoke.timer` 待改完再启用 | 次日 09:33 起每日 smoke 误报，污染告警通道 |

### P1（切换后 24h 内完成）

| # | 项 | 位置 | 动作 |
|---|-----|------|------|
| P1-1 | healthcheck 探针模型名 | `<INSTALL_DIR>/secrets/vllm.env`（追加一行）| 追加 `SERVED_MODEL_NAME=deepseek-v4-flash-vision-exp`——`healthcheck_hardened.sh` 已支持该 env（QA-fix H1），**无需改脚本**，只补 env 注入；BUSY 兜底使其非 P0 |
| P1-2 | R1 长纯文本路由 | 8001 代理 / 调用方 | 单引擎期以「调用方约束 + Gate4 哨兵」为缓解并写入值班手册；双活路由列入 D4 后续工程排期 |

### P2（顺手/排期）

| # | 项 | 动作 |
|---|-----|------|
| P2-1 | runbook 前置条件 2 tilelang-cache-f1 表述 | 修正为「flashinfer-cache-f1 非空；tilelang-cache-f1 为空属预期（TK512 退役）」 |
| P2-2 | `check_vllm_script.sh:99` 依赖文件检查 | 无现役调用方；若恢复使用需同步 dsv4-vision-exp 路径，建议加注释标注 |
| P2-3 | 8001/8003 双活路由（R1 根治 + VL/文本并存） | 对应待办 D4，另行排期 |
| P2-4 | `<INSTALL_DIR>/scripts/` 下大量历史 .bak 与 bench 脚本含旧模型名 | 无现役调用（monitor/crash/logdump/healthcheck 现役文件已核清），仅归档噪音，可在整理窗口清理 |

---

## 5. 8003 网关具体改动建议（文件/行级）

文件：`node02:~/responses_gateway/main.py`（17903 字节，v2.0-slim；改前按惯例 `cp main.py main.py.bak-vl-20260908`）

**方案 A（推荐，最小改动 + 保留回退语义）**——利用现成的 env 机制，`main.py` 一行都不用改：

`systemctl --user edit responses-gateway`（或直接改 `~/.config/systemd/user/responses-gateway.service`）：
```ini
Environment=SERVED_MODEL=deepseek-v4-flash-vision-exp
# 保留旧名兼容：local-v4-flash 与 legacy 都映射到 VL（单引擎期唯一后端）
```
生效逻辑：`MODEL_ALIAS` 由 env 构造（L111-115），`local-v4-flash` / `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 全部 → VL served 名；`/v1/models` 列表自动更新（L201-215）。
代价：显式传 `deepseek-v4-flash-0731` 的存量调用方将 404——需先 grep 8003 的 gateway.log 确认是否有调用方在用裸 served 名（本次审计未查流量日志，**留给切换执行者一步确认**：`grep -o '"model":"[^"]*"' ~/responses_gateway/gateway.log | sort | uniq -c`）。

**方案 B（加双名映射）**——若需同时接受 VL 名与 0731 名，改 `main.py` L111-115：
```python
VL_MODEL = os.environ.get("VL_MODEL", "deepseek-v4-flash-vision-exp")
MODEL_ALIAS = {
    PUBLIC_MODEL: VL_MODEL,
    LEGACY_MODEL: VL_MODEL,
    VL_MODEL: VL_MODEL,
    # 回退期兼容（V5b 重新上线时把映射指回 0731 即可）
    SERVED_MODEL: VL_MODEL,
}
```
注意：单引擎期两个名字只能都指向当前引擎；真正按名分流需等双活路由（P2-3）。

**验收命令**（改后必跑）：
```
systemctl --user restart responses-gateway
curl -s http://127.0.0.1:8003/health
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8003/v1/models   # 应含 vision-exp
curl -s -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"local-v4-flash","messages":[{"role":"user","content":"ping"}],"max_tokens":4}' \
  http://127.0.0.1:8003/v1/chat/completions                                    # 应 200 有内容
# embeddings 不受影响验证：
curl -s -H "Authorization: Bearer $API_KEY" -d '{"model":"...","input":"x"}' http://127.0.0.1:8003/v1/embeddings
```

**回退联动**：V5b 回退（`cp .bak → guard`）时 8003 的 env/映射必须同步改回 `deepseek-v4-flash-0731`，建议把这一步写进 runbook 回退链（文档 §4 回退链当前只写了脚本 cp + guard，**缺 8003 联动与 monitor/daily_smoke 联动——已并入 P0-2/P0-3 的修改建议中，回退时反向执行**）。

---

## 6. 做得好的地方

- 定稿脚本与生产基线的 diff 恰为宣称的 6 处差异 + 注释头，零意外项——「最小差异集」纪律执行到位。
- 治理链设计干净：guard→restart→systemd→monitor→live 脚本，启动路径零模型名/tag 硬编码，`cp` 即切换，这是本次切换主体可放行的根基。
- `healthcheck_hardened.sh` 的 QA-fix H1（SERVED_MODEL_NAME env 化）说明团队已有「模型名可变」意识，本次只需补 env 注入即可闭环。
- D2 fail-fast（TCPStore 超时拒起 workers）与 BUSY/不可达双路径重建判定，把历史上两类真实事故的教训固化进了代码。
- F1 独立缓存卷（防 stale .so）+ boot2 暖缓存实证（.so mtime 与窗口吻合），部署侧 JIT 风险已收敛。

## 7. 结论

**Request Changes**：核心切换链路 PASS 可执行；P0-1（文档 md5 修正）、P0-2（8003 映射）、P0-3（monitor 预热名）、P0-4（daily_smoke 名）四项在切换窗口内完成后方可执行切换，P1 两项 24h 内跟进。
