# G1r5 全量重测报告（LuZ-0.4.4-G1r5, 2026-09-02）

> 督导指令：服务团队已完成 G1R4/G1R5 小版本升级（交接文档 `w9-evidence/w9r4/W9-R9-G1R4-G1R5-LANDING.md`），开展全量重测。
> 口径：uuid-prefix 冷算三轮中位（bench_v2 md5 714936f9）；重启一律走 guard。
> 对照（仅参考带，不作回归门——内核代际+cutlass+tvm-ffi 三项全换）。

---

## 1. TL;DR

| 项 | 结论 |
|---|---|
| 现役断言 | ✅ LuZ-0.4.4-G1r5（digest 353697b2）+ cB 参数 + env 五项 |
| DE C1 | 99.72 t/s（中位；G1r3 98.69 +1.0%；2400 等效 ≈103.9 入对照带 103-113） |
| PR@4K | C1=2671 / C2=2061 / C4=900 / C8=541（2400 等效 +2.1%/+2.6% vs G1r3 cB） |
| GSM8K 全量 | **0.9363**（1235/1319，marker 0.9378，err=0）→ ✅ ≥0.930 门 |
| PR131K | 中断（cD 优先，沿用昨晚扩展轮参考：C1≈2387/C2≈1237/C4≈887-898） |
| cD(2048+8192) | ⛔ 引擎 MoE max_num_tokens 硬上限 4608，bat=8192 不可行（G1r6 范围） |
| 热安全 | ✅ 2300MHz 制满载峰值 83-91°C，无过温（<MGMT_OCTET> 单点尖峰） |

## 2. 交接变更摘要（G1r4/G1r5）

- **G1r4**（digest 66ef61b6）：移除陈旧 AOT 包（flashinfer-jit-cache/cubin 0.6.15/0.6.14）→ 现场 JIT（0.6.18 csrc）；cutlass-dsl 4.6.2；tvm-ffi 0.1.9→0.1.11（0.1.12 起破坏 tilelang，逐版本二分定谳）；envs.py 注册 N1；FLASHINFER_CUDA_ARCH_LIST=12.1a。
- **G1r5**（digest 353697b2）：`_FLASHINFER_DSV4_DECODE_TOPKS` 恢复 192——DSpark draft 层（SWA 128+k7→192）不再垫宽 512，原生 192 直入内核。
- **内核真身**：新 JIT `sparse_mla_sm120.so` 实例化 H×K 全 25 档（含 192/256），编译目标原生 sm_121a（旧 AOT 为 sm_120 族 cubin）。
- 回退路径：192 有问题→G1r4；整体→G1r3（4.5.2 稳态）；cutlass→G1r3。

## 3. 现役断言（重测前核对）

- 镜像 digest：sha256:353697b2… ✅（与交接文档一致）
- 参数：thr=2048/bat=4096/116g/0.80/max-num-seqs 12/600K/MTP7/FP8_DS_MLA ✅
- env：VLLM_MOE_W4A4=2 / VLLM_MOE_W4A4_CG=1 / VLLM_B12X_SHARED_WRAPPER=1 / VLLM_USE_BREAKABLE_CUDAGRAPH=1 / FLASHINFER_CUDA_ARCH_LIST=12.1a ✅
- 四机容器 healthy（Up 7h）、health=200 ✅、gb10-clock-cap active（2300MHz）✅
- ⚠️ 发现：concurrency-proxy（8001）inactive + MAX_CONCURRENCY=6 未改（G1r4 批次"proxy 12"未落地）；基准直连 8002 不受影响

## 4. 全量重测结果

### 4.1 DE C1（对照带 103-113）

| 轮 | decode_tps | ttft_s | ok |
|---|---|---|---|
| r1 | 99.72 | 0.7431 | 1 |
| r2 | 97.93 | 0.7342 | 1 |
| r3 | 99.86 | 0.7456 | 1 |
| **中位** | **99.72** | 0.7431 | — |

- vs G1r3（2400MHz 制）：98.69 → **+1.0%**
- vs 对照带 103-113：-3.2%（名义）；**2300MHz 时钟折算（/0.96）≈103.9 → 进入对照带**
- 解读：192 原生内核收益（~+5%）被时钟降频（~-4%）抵消后剩 +1%

### 4.2 PR@4K uuid 冷算（对照 G1r3 cB 参数、2400MHz 制）

| 格 | G1r5 中位（2300 制） | G1r3 cB 中位（2400 制） | 差值 | 2400 等效 | 等效差值 |
|---|---|---|---|---|---|
| C1 | 2671.20 | 2724.98 | **-1.97%** | ≈2782 | **+2.1%** |
| C2 | 2061.28 | （无同口径） | — | — | — |
| C4 | 900.46 | 914.08 | **-1.54%** | ≈938 | **+2.6%** |
| C8 | 540.79 | 549.05 | **-1.50%** | ≈563 | **+2.6%** |

- 注：G1r3 cB 的 C1 r1=317 为异常轮（稳健中位剔除）；G1r5 C1 r1=2460 首轮冷态偏低
- 解读：名义 -2%（时钟降频所致）；同频折算后 **192 原生内核约 +2% 正收益**

### 4.3 GSM8K 全量 1319 题（≥0.930 门）

- segA（114 题）：accuracy_content = 0.9386（107/114）、marker 0.9474、err=0、elapsed <MGMT_OCTET>s
- segB（1205 题）：（合并入全量）
- **全量 merged：accuracy_content = 0.9363（1235/1319）、marker 0.9378（1237/1319）、err=0**
- **gate_pass_0p930_content = true ✅（≥0.930 门通过）**，marker 亦通过
- 对比：历史锚 0.9492（上游）、spot200 0.955（G1r3）；全量 0.9363 达标

### 4.4 PR131K C2/C4

- **中断说明**：督导指令补测 cD（thr=2048/bat=8192）优先，131K 阶段未执行（全量脚本在 GSM8K 完成后停止）
- 参考数据（昨晚扩展轮，G1r3 cB、2400MHz 制）：PR131K C1≈2387 / C2≈1237 / C4≈887-898

### 4.5 cD（threshold=2048 + batched=8192）补测 — ⛔ 引擎硬上限否决

| 项 | 结论 |
|---|---|
| 执行 | guard 重启后 EngineCore 初始化失败 |
| 错误 | `num_tokens (8192) exceeds max_num_tokens (4608)` |
| 根因 | G1r5 引擎 MoE `max_num_tokens` **硬上限 4608**（=4096+512）：flashinfer 0.6.18 b12x W4A4 + CUDA graph 静态 buffer 容量（抛出点 `flashinfer/fused_moe/cute_dsl/b12x_moe.py:540` + `_sparse_mla_sm120.py:717`；容量来自 `moe_config.max_num_tokens`，vLLM 侧 flashinfer_b12x_moe.py:112） |
| 含义 | **bat≥4608 在 G1r5 不可行**（三组合实验含 cC=8192 只能在 LuZ0.3.1 跑的同因）；需引擎层改动（G1r6 范围） |
| 处置 | 四机 v043 恢复 cB（bat=4096，`.bak-bat4096-cB-20260902` 留档）→ guard 重启 rc=0 → 生产全链路恢复（health=200 / 自愈链 timer / 8001 proxy 均恢复 active） |

## 5. 关键观察

- **decode TPOT / draft 层延迟**（192 原生 vs 512 垫宽）：DE C1 99.72 t/s（G1r3 98.69 +1.0%）——192 原生内核收益 ~+5% 被时钟降频 ~-4% 抵消后剩 +1%
- **2300MHz 时钟制**：G1r5 全程 2300（gb10-clock-cap 昨日生效），历史基线 2400 制 → 时钟差 ~4%；同频折算后 192 原生内核约 **+2% 正收益**
- **异常轮/冷态**：首轮 uuid 冷算偏低属已知模式（稳健中位/剔除 >30% 偏差）
- **引擎 MoE 硬上限**：G1r5 max_num_tokens=4608（CUDA graph 静态容量），bat=8192 不可行

## 6. 温度与热安全（2300MHz 制）

- 满载峰值：<MGMT_OCTET>/<MGMT_OCTET> 83-85°C、<MGMT_OCTET> 87°C、<MGMT_OCTET> 91°C（单点尖峰，回落正常）
- 2300 cap 全程生效（满载时钟恒 2275-2288 MHz，无 boost 失控）
- 距过温断电阈值有裕量；GSM8K 单并发负载轻（67-75°C）

## 7. 结论与 G1r5 判定

| 项 | 判定 |
|---|---|
| G1r5 基本可用 | ✅ 全量重测核心必测项全部通过（DE/PR4K/GSM8K） |
| cD(2048+8192) | ⛔ 不可行（引擎 max_num_tokens 4608 硬上限，G1r6 范围） |
| 生产 | ✅ 已恢复 cB 参数 + guard 重启 + 自愈链/proxy 全链路恢复 |
| 遗留 | proxy MAX_CONCURRENCY=6 未改 12（G1r4 批次未落地） |

## 8. 遗留项

- proxy 12 未落地（inactive + MAX_CONCURRENCY=6）——G1r4 批次待办
- 192 档 autotune 键未落盘（走 heuristic，量级 <1%）
- FLASHINFER_DISABLE_VERSION_CHECK=1 惰性残留
- **cD 结论**：bat≥4608 需引擎层解除 MoE max_num_tokens 上限（G1r6 范围）

---
*报告定稿：2026-09-02（全量重测完成 + cD 否决 + 生产恢复）*
