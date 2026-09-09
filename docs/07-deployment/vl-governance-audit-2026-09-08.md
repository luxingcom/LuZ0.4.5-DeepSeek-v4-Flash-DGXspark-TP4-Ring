# VL 切换「服务器治理面」审计报告

**审计人**：Rex（SRE 工程师，sre-engineer-2）｜ **日期**：2026-09-08 ｜ **性质**：只读取证（未修改任何服务器文件）
**对象**：V5b（LuZ…Ring-V5b）→ VL（LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring，served 名 `deepseek-v4-flash-vision-exp`，k=6）生产切换的服务器治理面
**取证环境**：4× DGX Spark（node01 head / node02·node03·node04 worker），经 `ssh node01` + 跳板 ssh 到各 worker；当前现役 V5b 容器 healthy 运行中（`/v1/models` 确认 served=deepseek-v4-flash-0731）。

> **关联报告**：
> - **姊妹篇**：[部署方案交叉审核](vl-deployment-cross-audit-2026-09-08.md)（切换前 Review，与本报告 P0 清单相互印证：healthcheck 探针注入断点 / warmup 硬编码 / daily-smoke / 8003 网关映射）。两报告的 P0/P1 动作项已随切换窗口落实，执行回执见[切换执行审计](../06-verification/vl-switch-execution-audit-2026-09-08.md)（八项全 PASS）。
> - **验收上下文**：[上线六门验收](../06-verification/vl-acceptance-sixgates-2026-09-08.md) · [FINAL-METRICS-VL](../03-final-metrics/FINAL-METRICS-VL-2026-09-09.md)
> - **根因排查链**：[服务器取证](../01-research-reports/vl-server-side-forensics-2026-09-09.md) · [投机头调研](../01-research-reports/spec-head-research-2026-09-09.md)

---

## 0. 总判定

| # | 审核项 | 判定 | 一句话结论 |
|---|---|---|---|
| 1 | 持久化面（enable 状态 + env md5 + masked） | **PASS** | 四机 8 个关键单元 enable+active，w6_env.txt 四机 md5 一致 b4ae0340，vllm028-* 四机 masked |
| 2 | 自愈链对 VL 的适配 | **CONCERN** | 容器重建路径版本无关（PASS），但 **2 处模型名硬编码**（healthcheck 活性探针 + monitor warmup 请求）在 VL 形态下会失效/半失效，需切换前落实 |
| 3 | 日志/取证面 | **PASS** | logdump 四机 enabled+active，轮转策略 200MB×3 份有效，磁盘余量 2.2T 充裕 |
| 4 | 守卫链（guard v3） | **PASS（含 1 个观察项）** | 双名 stop 容错确认；40×30s=20min 对 VL 首启 5-8min 裕量足（实测 boot2 6min）；D2 120s fail-fast 版本无关仍适用 |
| 5 | 缓存卷治理 | **PASS** | -f1 独立卷四机就绪（15M，含 boot2 暖缓存 .so，mtime 09-08 08:45）；生产卷无混用；vllm-cache autotune 共享卷角色明确 |
| 6 | 回退推演 | **PASS（结论可信）** | 回退=反向 cp+guard 重启，实测同路径 6min；最大风险点=healthcheck 探针与 smoke 双处模型名，回退后自愈链即恢复原状 |

**总评**：治理面就绪度 **可放行**，但有 **2 个 P0 动作**（healthcheck 活性探针模型名注入、warmup 请求模型名）需在切换窗口内同步落实，否则 VL 形态下「推理活性探针」与「CUDA 图预热」两道防线将静默失效。

---

## 1. 审核项 1：持久化面 — PASS

### 1.1 单元 enable/active 状态（实测 2026-09-08 ~09:5x UTC）

**node01（head）**：

| 单元 | is-enabled | is-active |
|---|---|---|
| vllm-tp4-head.service | enabled | active |
| vllm-healthcheck.timer（即交接所指 "timer"） | enabled | active（每 60s 触发） |
| concurrency-proxy-v2.service | enabled | active |
| gb10-clock-cap.service | enabled | active |
| vllm-logdump.service | enabled | active |

> 交接资料中 "head/timer" 的实际单元名是 `vllm-tp4-head.service` + `vllm-healthcheck.timer`（timer 拉起 `vllm-healthcheck.service` oneshot，ExecStart=healthcheck-rebuild.sh --role head --cooldown 1800）。不存在名为 "head.service" / "timer.service" 的单元，属交接措辞简称，非缺口。

**node02/node03/node04（worker，三机一致）**：

| 单元 | is-enabled | is-active |
|---|---|---|
| vllm-tp4-worker.service | enabled | active |
| gb10-clock-cap.service | enabled | active |

> vllm-healthcheck.timer **仅在 node01**（head）部署（node02 实测 not-found）。这是设计使然：探针只打 head 的 8001/8002，worker 无对外 HTTP。若运维期望 worker 也有主动重建，属增量需求非本次切换阻塞项。

### 1.2 w6_env.txt 四机 md5

```
node01: b4ae0340cd55e04d289d2be43ff09a05  <HOME_DIR>/w6-kit/w6_env.txt
node02: b4ae0340cd55e04d289d2be43ff09a05  （同）
node03: b4ae0340cd55e04d289d2be43ff09a05  （同）
node04: b4ae0340cd55e04d289d2be43ff09a05  （同）
```
四机一致，与交接声称的 `b4ae0340` 前缀吻合，且 w6_env.txt 为版本无关环境文件 → 切 VL 无需动它。✅

### 1.3 旧单元 masked

```
node01: vllm028-tp4-head.service    masked
node02: vllm028-tp4-worker.service  masked
node03: vllm028-tp4-worker.service  masked
node04: vllm028-tp4-worker.service  masked
```
四机旧单元全部 masked（09-07 已做，本次复核确认仍有效）。masked 单元无法被任何依赖链误拉起。✅

---

## 2. 审核项 2：自愈链对 VL 的适配 — CONCERN

### 2.1 容器重建路径（PASS，版本无关）

自愈链核心路径逐环核验：

1. **healthcheck-rebuild.sh**（v1.0-p2，<INSTALL_DIR>/scripts/，仅 node01 有 timer 驱动）：
   - 调 `healthcheck_hardened.sh --role head --timeout 30 --grace-sec 900` 只读探针；
   - 探针失败 → 先查 `curl 127.0.0.1:8002/health`（**版本无关端点**）：存活=繁忙不重建；
   - 8002 不可达连续 2 次（60s 间隔）→ GID 预检 + `docker rm -f tp4-rank**`；
   - **重建不直接调 start 脚本**，而是 rm 容器 → monitor 的 `docker wait` 返回 → exit 1 → systemd Restart → monitor 调 **当前 live 的 start_tp4_*_v043.sh** 重建。
   - ✅ 切 VL 后 live=start_tp4_head_v043.sh（.vl-final 覆盖），自愈重建自动就是 VL。脚本内 grep **无任何镜像 tag / V5b / Ring-V5b 硬编码**。
2. **monitor_tp4_head_v043.sh**（~/w6-kit/，vllm-tp4-head.service 的 ExecStart）：
   - 容器名 `vllm-tp4-rank0`（VL 脚本同样用此名，vl-final 第 42 行确认）→ 名字匹配，无阻断；
   - 重建调用 `NO_WAIT=1 bash <HOME_DIR>/w6-kit/start_tp4_head_v043.sh`（live 脚本，无 tag 硬编码）；
   - D3 rank 就绪门禁：TCPStore :26000 + 4 rank 接入（60s 无进展 fail）→ 版本无关；
   - **GID 预检**（W9R15）：VL 同样走 NCCL/RoCE，需要。✅
3. **monitor_tp4_worker_v043.sh**（node02/node03/node04）：无镜像/模型名引用；head 健康探测走 8001 /ping（版本无关）；fail 判据 TCPStore 120s 不可达（D2 同款）。✅

**结论：容器重建链 100% 版本无关，切 VL 后自愈重建的就是 VL 容器。**

### 2.2 健康探测端点：/health 还是 /v1/models？

**探针分两层，判定不同：**

| 层 | 脚本 | 端点 | 模型名敏感？ |
|---|---|---|---|
| 基础层 | healthcheck-rebuild.sh 步骤 2.6 | `8002/health` | **否**（版本无关）✅ |
| 基础层 | healthcheck_hardened.sh 2a | `8001/health`（经代理转发到 8002） | **否** ✅ |
| **活性层** | healthcheck_hardened.sh 2b | `8001/v1/completions`（**POST 带 model 字段**） | **是** ⚠️ |

healthcheck_hardened.sh 第 126-128 行：

```bash
# QA-fix H1: 原硬编码 model "deepseek-v4-flash-0731" → 模型改名后探针 400。
# 改由 SERVED_MODEL_NAME env 注入 (缺省用当前生产名)
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-deepseek-v4-flash-0731}"
```

**QA-fix H1 的注入机制存在断点**：healthcheck-rebuild.sh 本身不导出 SERVED_MODEL_NAME；vllm-healthcheck.service 只 `EnvironmentFile=<INSTALL_DIR>/secrets/vllm.env`。实测 `sudo grep SERVED_MODEL_NAME <INSTALL_DIR>/secrets/vllm.env` = **0 行**。

→ **后果推演（关键）**：VL 切换后，活性探针 POST `{"model":"deepseek-v4-flash-0731",...}`，后端 served 名为 `deepseek-v4-flash-vision-exp`，vLLM 返回 404/400 → 探针恒 FAIL=1。但**不会误杀**：
- healthcheck-rebuild 2.6 检测 8002/health 存活（VL 正常时必 200）→ 判 BUSY 不重建 ✅（自愈链退化为「只看基础层」，活性层盲区重新打开=NCCL 死而 /health 活的卡死场景不再被探测）；
- 若 VL 真卡死（/health 也挂），failcnt×2 → 重建照常触发 ✅。

即：**不误杀，但活性探防线静默失效**——这正是 2026-08-25 事故后加的「闭合卡死仍 healthy 盲区」能力在 VL 形态下空转。**P0 动作**（见 §7）。

### 2.3 monitor warmup 请求模型名（第二处硬编码）

monitor_tp4_head_v043.sh 第 69 行（W9R11 CUDA 图预热）：

```bash
-d '{"model":"deepseek-v4-flash-0731","prompt":"warmup-cuda-graph","max_tokens":16,...}'
```

→ VL 形态下预热请求 400，`WARMUP_RC` 非 200，脚本仅 echo 记录、不 fail，**不阻断自愈链**；但长上下文首次 JIT 的预热防线失效。若 -f1 暖缓存被清空（交接 §4 提到 +5-10min JIT），首请求卡顿风险回到 W9R11 之前。**P0/P1 动作**。

### 2.4 grep 硬编码总表（自愈链三脚本）

| 脚本 | 命中 | 影响 |
|---|---|---|
| healthcheck-rebuild.sh | 无 | 无 |
| healthcheck_hardened.sh:128 | `deepseek-v4-flash-0731`（默认值） | 活性探针失效（见 2.2） |
| monitor_tp4_head_v043.sh:69 | `deepseek-v4-flash-0731`（warmup 请求体） | 预热失效（见 2.3） |
| monitor_tp4_worker_v043.sh（node02） | 无 | 无 |
| 三个脚本中的 V5b / Ring-V5b / 镜像 tag | **零命中** | 重建链不受影响 |

### 2.5 附带发现：daily-smoke（治理面外围，同病）

`daily-smoke.timer`（enabled，每日 09:30）→ `~/w6-kit/daily_smoke.py` 第 9 行硬编码 `"model": "deepseek-v4-flash-0731"`。VL 切换后日级 smoke 恒 FAIL（alert-only，无自动动作，但告警通道每天报一次假阳性）。**P1 动作**。

---

## 3. 审核项 3：日志/取证面 — PASS

| 项 | 实测 | 判定 |
|---|---|---|
| vllm-logdump.service 四机状态 | node01/node02/node03/node04 全部 enabled+active | ✅ 常开确认 |
| 归档路径 | `<INSTALL_DIR>/backup/vllm-logdump/`（LOGDUMP_DIR env，systemd 单元固定） | ✅ |
| 当前体积 | node01: 42M（含 vllm028 时代 26M 遗留档）；node02/node03/node04: 14-15M | ✅ 轻量 |
| 轮转策略 | 单文件 200MB（LOGDUMP_ROTATE_MB）→ mv+gzip，保留最近 3 份（LOGDUMP_KEEP_OLD），v1.1-p0-forensics 实现于脚本 maybe_rotate() | ✅ 有界增长：单容器上限 ≈200M×4（live+3 gzip 档） |
| 采集模式 | 5s 扫描 `^vllm-tp4-rank[0-9]+$`，跨代追加同一文件；**容器名模式版本无关**（VL 仍叫 vllm-tp4-rank0） | ✅ VL 无需改 |
| crash_dump.sh | ExecStopPost 挂 vllm-tp4-head.service；DUMP_BASE=<INSTALL_DIR>/backup/crash-dumps；实测 09-08 早已有 4 个 crash 目录（08:25/08:40/08:42/08:59，19M）→ 切换窗口的 boot 周期已被完整留证 | ✅ 链路活 |
| 磁盘 | /（nvme0n1p2 3.6T）已用 37%，余 2.2T | ✅ |

**VL 上线后日志量预估**：VL 首启多出 dspark FULL 图捕获（10 图）+ `[NCCL][V5] cap-snap` 周期行 + SpecDecoding metrics 周期打印（V5b 也有）。logdump daemon 跟随的是 docker logs 流，日志速率与 V5b 同量级（boot2 实测当日 vllm-tp4-rank0.log ≈7.8M/数小时）。轮转阈值 200MB 足够，无需调整。**唯一注意**：VL 验证窗如果频繁重启（每代 head 容器重写同一 log 文件），档数会接近 3 份上限后自动清理旧档——切换窗口内如需完整留证，先手工 `cp` 一份当日 log。

---

## 4. 审核项 4：守卫链（guard v3）逐行审计 — PASS（1 观察项）

### 4.1 w9r4_restart_guard.sh（flock wrapper）

- `exec 9>/var/lock/w9r4-restart.lock`（失败回退 /tmp）+ `flock -w 1200`（等锁 20min 超时 exit 3）；
- trap EXIT 释放锁；内层 `bash w9r4_window_restart.sh "$@"`。
- **判定**：逻辑简单无版本相关内容；与 systemd 自愈链的互斥靠 monitor_v043 的「guard 互斥」（容器存在即 docker wait 跟随，不并发拉起）+ 本 flock（人际/脚本层防叠跑）。双层防叠跑在 09-08 三次实战（boot1/boot2/restore）中均未冲突。✅

### 4.2 w9r4_window_restart.sh（guard v3）逐项

| # | 疑虑点 | 逐行核验结果 | 判定 |
|---|---|---|---|
| a | **stop 双名单元对 masked 状态的容错** | 第 42 行：`sudo -S systemctl stop vllm-tp4-worker vllm028-tp4-worker 2>/dev/null`——vllm028 已 masked，systemctl stop 对 masked 单元返回非零但 `2>/dev/null` 吞掉 stderr、命令列表以 `;` 串联继续执行；随后 `docker rm -f $(docker ps -aq --filter name=tp4-rank)` 兜底清容器。head 侧第 47 行同构。**masked 报错不阻断链**。09-08 三次实战日志（boot1/boot2/restore）均无中断。 | ✅ |
| b | **health 等待 40×30s=20min vs VL 首启 5-8min 裕量** | 实测 boot2（VL 定稿形态、-f1 暖缓存）：start head 08:42:44 → READY 12x30s，即 ~6min 到 health=200（含 capture+autotune），链总耗时 08:42:29→08:48:36=6min07s。**20min 预算 / 6min 实耗 ≈ 3.3 倍裕量**。最坏情形推演：-f1 卷被清空 → +5-10min JIT → 首启 11-16min，仍在 20min 内（此时裕量收窄至 1.25-1.8 倍，可接受但建议保留暖缓存）。**restore（切回 V5b）实测 11x30s≈5.5min，回退更快。** | ✅（观察项：勿清 -f1 卷，否则裕量收窄） |
| c | **D2 TCPStore fail-fast 120s 对 VL 适用性** | TCPStore 是 vLLM 分布式初始化原语（Ray-less 直连 MASTER:26000），与模型形态/镜像内容无关。VL 脚本 MASTER_PORT=26000 与 V5b 相同（vl-final 第 54 行 `-e MASTER_PORT=26000`，monitor_v043 也等 :26000）。实测 boot2 `TCPStore up 5x5s`（25s）。fail-fast 防分裂集群逻辑在 VL 下语义不变。 | ✅ |
| d | 单元/容器名双代兼容 | UNIT_HEAD 固定新名 `vllm-tp4-head`（教训注释：勿用 grep 探测选名）；容器名 filter `name=tp4-rank` 同时命中新旧两代。VL 脚本容器名 `vllm-tp4-rank0` 命中。 | ✅ |
| e | 退出路径 | D2 失败→停 head 单元保持四机静止+tail 日志 exit 2；health 失败→tail rank0 日志 exit 1。均有人工介入口。 | ✅ |
| f | sudo 密码明文 `PW='<PASSWORD>'` 内嵌 | 历史已知项（脚本内 sudo -S 管道）。属安全债，非本次切换功能风险。 | 观察（P2） |

### 4.3 一个隐藏交互（重要，切换窗口须知）

guard 链 stop 单元用 `systemctl stop` → systemd 停 monitor → **ExecStopPost=crash_dump.sh vllm-tp4-rank0**（vllm-tp4-head.service 定义）→ 每次受控重启都会产生一个 crash-dump 目录。09-08 已见 4 个（08:25-08:59 正是 boot1/boot2/restore 三次重启+1）。**这是设计行为（留证优先），不是故障**；切换 VL 时又会新增 ≥1 个 crash 目录，值班看到不要误报。同时 crash_dump 落盘在持久分区，19M/次，无容量压力。

---

## 5. 审核项 5：缓存卷治理 — PASS

### 5.1 -f1 独立卷挂载（vl-final 核实）

node01 head（start_tp4_head_v043.sh.vl-final 第 59-60 行）与 node02/node03/node04 worker（第 40-41 行）均确认：

```bash
-v <HOME_DIR>/flashinfer-cache-f1:/root/.cache/flashinfer:rw
-v <HOME_DIR>/tilelang-cache-f1:/root/.cache/tilelang:rw
```
与交接 §3 一致。✅

### 5.2 四机 -f1 卷现状（boot2 暖缓存实证）

| 节点 | flashinfer-cache-f1 | tilelang-cache-f1 | f1 内关键 .so |
|---|---|---|---|
| node01 | 15M，mtime 09-08 08:42-08:45 | 4.0K（空目录） | sparse_mla_sm120.so（mtime 08:45:58，boot2 窗口）+ b12x_moe_sm121a_cute_dsl 6.8M + sampling 5.4M |
| node02 | 15M，mtime 08:43 | 4.0K（空） | 同左 |
| node03 | 15M，mtime 08:43 | 4.0K（空） | 同左 |
| node04 | 15M，mtime 08:43 | 4.0K（空） | 同左 |

- **是 boot2 暖缓存**：四机 f1 的 sparse_mla_sm120.so mtime=09-08 08:42-08:45（boot2 启动 08:42:44 之后），与交接 §8「-f1 缓存四节点就绪且 boot2 暖缓存」吻合。✅
- tilelang-cache-f1 为空属预期：VL 定稿形态走 flashinfer 453aa7c 原生 prefill（TK512 退役、tilelang 不再触发编译），空卷无害。
- autotune json：f1 卷内 `121a/autotune/sparse_mla_sm120_cpb.json` 存在（skip-ops 下通用调优跳过但 cpb 标定缓存仍在）。

### 5.3 生产两卷在 VL 形态下的角色

| 卷 | V5b 角色 | VL 形态角色 |
|---|---|---|
| `~/flashinfer-cache`（27M，旧 0.6.18） | flashinfer JIT 缓存 | **闲置**（VL 挂 -f1 不挂它）；保留供回退 V5b 即时使用。审计确认无污染（f1/生产卷内容独立，md5 前缀目录结构均各自完整）。 |
| `~/vllm-cache`（W9R14 autotune） | autotune-g1r6 策略缓存 | **VL 共享同一卷**（vl-final 第 62 行 `-v ~/vllm-cache:/root/.cache/vllm`，worker 同）。autotune_configs.json（9232B，mtime 09-08 09:04=restore 时刻 V5b 写入）MoE 策略对 VL 仍有效（b12x MoE 后端不变）；boot2 日志「Loaded 36 configs」实证。注意：**两版本交替会互相覆写 autotune_configs.json**——每次切换后首启都会重标定，属预期非缺陷。 |

**风险提示（P2）**：VL 与 V5b 交替期间 vllm-cache 的 autotune json 会被两个形态轮流改写。若某天需要冻结某一形态的最优标定，需引入 per-形态 autotune 目录；当前无性能故障迹象，不阻塞。

---

## 6. 审核项 6：回退推演（桌面推演，未动手）

### 6.1 V5b → VL 切换序列（含验证点）

| 步 | 操作 | 验证点 | 预计耗时 |
|---|---|---|---|
| S0 | 前置确认（已由本审计完成）：四机 vl-final 脚本 md5（head b0b3561a…；worker 三机一致 936963ee…）、VL 镜像 <BAKE_IMAGE_DIGEST> 四机就位、-f1 暖缓存四机就位 | md5 表核对 | 0（已完成） |
| S1 | `cp .vl-final → live` 四机 | `md5sum` live=vl-final；head=cf165e09→b0b3561a，worker=31d60685→936963ee；**三 worker 互相一致** | 1min |
| S2 | `bash ~/w6-kit/w9r4_restart_guard.sh` | 日志出现 stop workers→stop head→start head→TCPStore up（≤120s，D2 门）→start workers→wait health | — |
| S3 | 等 `[READY] health=200` | boot2 实测 ~6min（暖缓存）；预算上限 20min | 5-8min |
| S4 | 验收门（健康→GSM8K→视觉五门→needle→并发→投机指标） | 按 runbook §4 门表 | 15-25min |
| S5 | `curl 8002/v1/models` 确认 id=deepseek-v4-flash-vision-exp | 单命令 | <1min |
| S6 | 告知调用方换模型名（8001 代理全量转发，无需改） | — | 协调项 |

**切换总停机窗口：约 8-12min（S1-S3），与 runbook 声称一致；含验收 25-35min。**

### 6.2 VL → 回退 V5b 序列

| 步 | 操作 | 验证点 | 预计耗时 |
|---|---|---|---|
| R1 | 四机 `cp .bak-window-20260907 → live`（head cf165e09 / worker 31d60685，**当前 live 即这两个 md5，等于复制回现值**） | md5 核对 | 1min |
| R2 | `bash w9r4_restart_guard.sh` | 同 S2 | — |
| R3 | 等 health=200 | **restore 实测 09-08 08:58:59→09:04:55 = 5min56s（11x30s）**——V5b 回退是已验证路径 | 5-7min |
| R4 | `curl 8002/v1/models` id=deepseek-v4-flash-0731 + GSM8K 三题 | — | 2min |
| R5 | （若 VL 期间动过 healthcheck/daily_smoke 模型名——见 P0/P1 清单）回退需同步把模型名改回 0731 或恢复 SERVED_MODEL_NAME 注入 | grep 复核 | 2min |

**回退总耗时：约 8-10min（R1-R4）。** VL 专属残留物=零（脚本级 cp 覆盖；-f1 卷与 f1 镜像留存不碍事；vllm-cache autotune json 会被 V5b 重标定自动覆盖）。

### 6.3 推演结论：最易出问题的步骤

1. **S1 脚本分发不同步（最高风险，历史教训）**：三 worker 忘 cp 或 cp 错变体（w6-kit 里还躺着 .b7pw7/.b7full7sa/.b7f1full7/.b7f1pw7 多个过程变体，**文件名仅差后缀**）。缓解：S1 后必须跑四机 md5 对照表（本报告 §5/§6.1 已给出全部基准值），这是切换窗口唯一强制门。
2. **S3 若 -f1 暖缓存意外失效**（如有人清理 home 目录）：首启 +5-10min JIT，S3 可能到 11-16min，接近但仍未破 20min 预算；若破预算 guard exit 1，处置=重跑 guard（第二轮 JIT 已落缓存，必然快）。缓解：切换前 `du -sh ~/flashinfer-cache-f1` 四机确认 ≥10M。
3. **S4 验收门 R1（Gate4/13.6K 纯文本 IMA）失败**：已知残余风险 R1，回退即可；同时留证（crash_dump 已自动、`dmesg -T | grep Xid`）。
4. **回退 R5 忘改回模型名**：若按 P0 清单用「SERVED_MODEL_NAME 环境变量注入」方案则回退零动作（变量随版本切）；若用「直接改脚本硬编码」方案则回退必须反向改回，**推荐前者**（见 §7 P0-1 两方案）。

---

## 7. 切换前治理动作清单

### P0（切换窗口内必须完成，否则防线静默失效）

| # | 动作 | 理由 | 落实方式（推荐方案 A） |
|---|---|---|---|
| P0-1 | **修复 healthcheck_hardened.sh 活性探针模型名注入断点** | SERVED_MODEL_NAME 缺省 0731，vllm.env 实测无该变量 → VL 下活性探针恒 400，NCCL-卡死盲区重开 | **方案 A（推荐，零脚本改动）**：`<INSTALL_DIR>/secrets/vllm.env` 增加一行 `SERVED_MODEL_NAME=deepseek-v4-flash-vision-exp`，回退 V5b 时改回 0731。**方案 B**：改脚本缺省值并 .bak 留档（回退要再改回）。方案 A 使变量成为「当前生产形态声明」，与 EnvironmentFile 机制天然配套。 |
| P0-2 | **monitor_tp4_head_v043.sh 第 69 行 warmup 请求模型名改版本无关** | VL 下 warmup 400，CUDA 图/JIT 预热防线失效 | 最小改法：请求体 model 从 env 读 `${SERVED_MODEL_NAME:-deepseek-v4-flash-0731}`，且该 env 需在 vllm-tp4-head.service 的 EnvironmentFile（同 vllm.env）——即 P0-1 方案 A 落地后此脚本只需一行改（+ .bak 留档 + REFERENCE.md 更新，脚本头规约）。注意 monitor 是 systemd User=<USER> 直跑，EnvironmentFile 是否生效需在 unit 加 `EnvironmentFile=` 或在 monitor 头部 source vllm.env——建议 unit 加 EnvironmentFile 最干净。 |
| P0-3 | 切换 S1 后的四机 md5 对照（含三 worker 互查） | 历史分裂集群事故根因 | 用 §6.1 基准值：head live=b0b3561a…，worker live=936963ee…（×3 一致） |

### P1（切换后 24h 内完成）

| # | 动作 | 理由 |
|---|---|---|
| P1-1 | daily_smoke.py 第 9 行模型名改为 env 可注入（`SMOKE_MODEL` 缺省 0731），并在 systemd unit 或 vllm.env 注入 vision-exp | 否则 VL 期间每日 09:30 假阳性告警，狼来了效应 |
| P1-2 | 切换完成后主动观察一轮 healthcheck-rebuild 输出（journalctl -u vllm-healthcheck.service -n 50）确认活性探针返回 ok（P0-1 落实的验证） | 防注入写错名（如拼错 vision-exp） |
| P1-3 | guard 链日志从 /tmp/w3-*.log 迁移规范落 ~/w6-logs/（交接 §8.1 已建议，本次审计确认 /tmp 下已有 3 份易失日志） | /tmp 重启即失，取证连续性 |

### P2（后续优化窗）

| # | 动作 | 理由 |
|---|---|---|
| P2-1 | w9r4_window_restart.sh / w9r4 相关脚本中明文 sudo 密码改 sudoers NOPASSWD 精确授权 | 安全债 |
| P2-2 | vllm-cache autotune per-形态目录隔离（vl 与 v5b 各自 autotune-g1r6 子目录） | 消除两形态交替重标定开销（当前无性能故障，非紧急） |
| P2-3 | worker 侧是否部署 healthcheck timer 的策略讨论（当前仅 head 有主动重建，worker 依赖 monitor docker wait + D3 门禁） | 设计决策，非缺口 |

---

## 8. 审计方法与证据索引（全部只读命令）

- 单元状态：`systemctl is-enabled/is-active` × 四机 × 8 单元；`systemctl list-unit-files | grep vllm`
- 脚本全文：healthcheck-rebuild.sh、healthcheck_hardened.sh、monitor_tp4_head_v043.sh（node01）、monitor_tp4_worker_v043.sh（node02）、w9r4_restart_guard.sh、w9r4_window_restart.sh、vllm_logdump.sh、daily_smoke.py、concurrency_proxy_v2 单元 env、vllm-{healthcheck,logdump,tp4-head,tp4-worker,daily-smoke} 单元定义
- 硬编码扫描：grep `V5b|deepseek-v4-flash-0731|Ring-V5b|vllm028` 于自愈链三脚本（命中见 §2.4）
- md5：w6_env.txt 四机、start 脚本 vl-final/live/.bak 四机全对照
- 缓存卷：du/stat/find（f1 卷 .so 清单与 mtime）、vllm-cache autotune json
- 日志：/tmp/w3-boot1/boot2/restore.log（guard 实战时间线）、crash-dumps 目录 ls、vllm-logdump du + 轮转参数（systemd env）
- 环境注入验证：sudo grep SERVED_MODEL_NAME <INSTALL_DIR>/secrets/vllm.env（0 行）、VLLM_API_KEY（1 行）
- 现役状态：docker ps（V5b 容器 healthy）、curl 8002/v1/models（id=deepseek-v4-flash-0731）

**与既有交叉审计的关系**：交接资料 §8 记录了三个只读子代理审计（镜像/配置/文档），本报告是第四项——服务器治理面（持久化/自愈/日志/守卫/缓存卷/回退），发现项（SERVED_MODEL_NAME 注入断点、warmup 硬编码、daily-smoke 硬编码）均为治理面新发现，不在前三项范围内。
