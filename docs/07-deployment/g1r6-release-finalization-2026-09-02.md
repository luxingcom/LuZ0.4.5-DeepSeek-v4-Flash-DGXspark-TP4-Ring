# G1R6 正式定版报告 — LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring（2026-09-02）

> 督导指令：①活性探针 GPU 利用率旁证准确性太低，关闭；②G1R6 可正式定版，版本号 `LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring`。

**工作流**：版本发布 / 变更收口
**参与成员**：Rex（SRE）· Cody（Code Review）· Docu（Tech Writer）协同产出

---

## 📌 TL;DR

- **定版**：G1R6 正式定版为 `LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring`（= G1r6 digest **sha256:<BAKE_IMAGE_DIGEST>**）；registry 正式 tag 已打并 push（manifest sha256:93564c4c），四机生产启动脚本 R5 已更新为正式 tag，md5 四机一致。
- **活性探针关闭**：W9R11 引入的 GPU 利用率旁证（`nvidia-smi utilization≥50% → BUSY 不判失败`）准确性低，已按督导指令移除——hardened 恢复 `FAIL=1` 直接判定，rebuild 恢复纯 failcnt 判定；其余超时守卫（日志活性 300s / health-cmd 30s / TimeoutStopSec=300 / monitor CUDA 图预热 / 8002 存活 / failcnt 2 / 冷却窗）全部保留。
- **附带修复**：healthcheck-rebuild.sh 重建容器名四机统一 `vllm028-tp4-rank`（02/03/04 原为 `vllm-tp4-rank`，`docker rm -f` 匹配不到容器 → 自愈重建失效隐患，已修复）。
- **验证**：四机脚本 md5 一致（hardened=94869b4d / rebuild=650a91ca）、bash -n 通过、GPU_UTIL 零残留、<MGMT_OCTET> head 只读试跑 healthy（宽限 skip）。
- 严重度：🔴 0 / 🟠 0 / 🟡 1（功能关闭）/ 🟢 0

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（可定版） |
| 正式版本号 | **LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring** |
| 版本来源 | LuZ-0.4.4-G1r6（digest sha256:<BAKE_IMAGE_DIGEST>） |
| registry tag | `REGISTRY_HOST:5000/vllm/vllm-openai:LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring`（manifest sha256:93564c4c4760…43be3） |
| 生产形态 | G1r6 + cB 参数 + TILE_CAP=0 + autotune 固化（B1 关闭，G1r7 候选） |
| 阻塞项数量 | 0 |
| 关键行动项 | 3 条（见行动清单） |
| 建议下一步 | 观察 2400MHz 满载温度；下次重建验证正式 tag 拉取链路 |

---

## 1. 活性探针 GPU 利用率旁证关闭（W9R12）

### 1.1 背景与判定

- **W9R11（今日早间）**：为防 C4+400K 长上下文 prefill 下探针排队超时误杀，在自愈链加入 GPU 利用率旁证（`nvidia-smi utilization≥50% = 繁忙(BUSY)非卡死`）。
- **督导反馈**：nvidia-smi utilization 为瞬时采样值，长上下文 prefill 期间波动大、50% 阈值缺乏依据，准确性太低 → **关闭**。

### 1.2 变更明细（四机同步，.bak 留档）

| # | 文件 | 变更 | 留档 |
|---|---|---|---|
| 1 | `healthcheck_hardened.sh` | 移除活性探针 GPU 旁证块（原 8 行）→ 恢复 `FAIL=1` 直接判定；探针失败一律交重建判定 | `.bak-pre-gpu-busy-close-20260902` |
| 2 | `healthcheck-rebuild.sh` | 移除 8002 不可达时 GPU 旁证块（原 9 行）→ 恢复纯 failcnt（连续 2 次失败才重建） | `.bak-pre-gpu-busy-close-20260902` |
| 3 | `healthcheck-rebuild.sh` | 重建容器名 `vllm-tp4-rank` → `vllm028-tp4-rank`（02/03/04 原匹配不到容器，<MGMT_OCTET> 已正确；一并统一） | 同上 |

### 1.3 校验证据

- 四机 md5 一致：`healthcheck_hardened.sh=94869b4d0959bb07c49edfcb6166eadc`、`healthcheck-rebuild.sh=650a91ca96cc5b9589d767f34b1caae2`
- `bash -n` 四机通过；`GPU_UTIL` 引用零残留
- <MGMT_OCTET> head 只读试跑：`ok 容器运行中` + `ok 冷启动宽限中 (uptime 691s < 900s)` + EXIT=0（宽限 skip，判定链路正常）
- 权限 `-rwxr-xr-x <USER>` 四机一致

### 1.4 保留的既有超时守卫（C4+400K 防护不退化）

| 守卫 | 机制 |
|---|---|
| 日志活性 300s | 宽限已过且就绪标记未现时，引擎日志近 300s 有推进 = 初始化中不干预 |
| 8002 HTTP 存活判定 | 探针失败但 8002 /health 存活 = 繁忙不重建（P2，2026-08-26） |
| failcnt 2 | 8002 不可达连续 2 次失败才重建（防单次抖动） |
| 冷却窗口 1800s | 防重启风暴 |
| health-cmd `-m 30` / `--health-timeout 35s` | head 容器健康检查超时窗放宽 |
| `TimeoutStopSec=300` | 停机时防 90s 默认超时 SIGKILL |
| monitor CUDA 图首运行预热 | health=200 后发 warmup 请求触发全链 JIT/CUDA 图编译 |

> 关闭 GPU 旁证后，长上下文 busy 的防误杀主要由「日志活性 + 8002 存活判定 + failcnt 2 + 冷却窗」承担——8002 存活判定在 prefill busy 场景下依然有效（HTTP 层队列未满时 8002 可响应），配合 CUDA 图预热消解首运行编译卡死，防护链完整。

## 2. G1R6 正式定版

### 2.1 版本溯源

- **试验名**：`LuZ-0.4.4-G1r6` → **正式名**：`LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring`
- 同一镜像（digest sha256:<BAKE_IMAGE_DIGEST>），正式 tag 为别名，无二进制差异
- 生产形态（督导裁决，已生效）：G1r6 + cB（thr=2048/bat=4096/116g/0.80/max-num-seqs 12）+ **TILE_CAP=0** + **autotune 手动固化**（B1 bf16 关闭，G1r7 候选）
- 关键性能锚点（autotune 固化后，2400MHz 制）：PR4K C1=2727（+2.1% vs G1r5）/ C4=906（+0.7%）；GSM8K 全量 W3=0.9318（B1 门 0.9356 未过，基础门 0.930 过）→ B1 默认关闭

### 2.2 定版动作（已执行）

| # | 动作 | 状态 |
|---|---|---|
| 1 | <MGMT_OCTET> registry 打正式 tag：`LuZ-0.4.4-G1r6` → `LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring` 并 push（manifest <BAKE_IMAGE_DIGEST>） | ✅ |
| 2 | registry API 验证正式 tag 存在（与 G1r6 并列） | ✅ |
| 3 | 四机 `start_tp4_head_v043.sh`（<MGMT_OCTET>）/ `start_tp4_worker_v043.sh`（四机）R5 镜像引用 → 正式 tag；`.bak-g1r6-tag-20260902` 留档 | ✅ |
| 4 | 四机 start 脚本 md5 一致：head=974817b2（<MGMT_OCTET>）/ worker=60b2104e（四机） | ✅ |
| 5 | 四机运行容器镜像核对：rank0-3 全部 `LuZ-0.4.4-G1r6`（<BAKE_IMAGE_DIGEST>） | ✅ |

### 2.3 当前生产状态

- 四机容器运行中（<MGMT_OCTET> head 容器 uptime 11min，宽限期内，服务正常）
- 2400MHz 生效（gb10-clock-cap，2385-2392 MHz）
- 自愈链：healthcheck timer + monitor + rebuild + 预热段 全部就位
- 下次容器重建将从 registry 按正式 tag 拉取（digest 相同，零行为差异）

## 3. 变更文件清单（本窗口）

| 文件（四机） | 变更 | md5 |
|---|---|---|
| `<INSTALL_DIR>/scripts/healthcheck_hardened.sh` | 移除 GPU 旁证 | 94869b4d |
| `<INSTALL_DIR>/scripts/healthcheck-rebuild.sh` | 移除 GPU 旁证 + 容器名统一 | 650a91ca |
| `/home/<USER>/w6-kit/start_tp4_head_v043.sh` | R5 → 正式 tag（<MGMT_OCTET>） | 974817b2 |
| `/home/<USER>/w6-kit/start_tp4_worker_v043.sh` | R5 → 正式 tag（四机） | 60b2104e |

留档：`healthcheck*.sh.bak-pre-gpu-busy-close-20260902`、`start_tp4_*.sh.bak-g1r6-tag-20260902`

## ✅ 行动清单

| # | 行动 | 负责 | 紧急度 | 预期完成 |
|---|------|------|--------|---------|
| 1 | 观察 2400MHz 满载温度（93°C 告警阈值保持）；扩展轮 C6/PR400K 与温度联动评估 | SRE | P1 | 下一扩展轮前 |
| 2 | 下次容器重建时验证正式 tag 拉取链路 + monitor 预热段执行（`[warmup] 预热请求完成 http=200`） | SRE | P2 | 下次重建 |
| 3 | proxy MAX_CONCURRENCY=6 → 12（G1r4 批次遗留，待 G1r7 窗口） | SRE | P2 | G1r7 |
| 4 | G1r6 定版信息同步至生产替换记录与交付索引 | Docu | P3 | 本日 |

## ⚠️ 待完善 / 已知局限

- GPU 旁证关闭后，极长 prefill（C6+ / PR400K 档）下 8002 若也被阻塞且引擎日志恰无推进，理论上仍可能触发 failcnt 重建——该场景由 CUDA 图预热 + 宽限 900s + failcnt 2 缓冲，风险可控；后续可用 C6/PR400K 实测覆盖
- healthcheck_hardened.sh 版本号（v1.0-prod-harden）未随 W9R12 递增（块内注释已标注变更，避免影响 --help 解析）
- 2400MHz 满载温度余量有限（2300 制峰值 83-91°C → 2400 制预计 88-96°C），热治理未根治

---

## 📚 数据来源 & 证据链

- diff 证据：<MGMT_OCTET> `healthcheck_hardened.sh.bak-pre-gpu-busy-20260902` vs 当前 —— 唯一差异即 GPU 旁证段（8 行 / 9 行），关闭 = 精确还原旁证前判定
- 试跑日志：`[healthcheck-hard][head] ok 容器运行中` / `ok 冷启动宽限中 (uptime 691s)` / EXIT=0
- registry API：`tags/list` 返回 `['LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring', 'LuZ-0.4.4-G1r6']`
- 四机运行容器：`vllm028-tp4-rank0/1/3/2 = LuZ-0.4.4-G1r6`
- 上游：`g1r6-experiment-benchmark-2026-09-02.md`（三窗口 + autotune 固化 + B1 降级）、`timeout-guard-cudagraph-warmup-2026-09-02.md`

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
