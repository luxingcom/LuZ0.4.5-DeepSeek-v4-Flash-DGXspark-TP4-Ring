# W9-R3 · 计算链路全面审计：生产 LuZ0.3.1 vs 0.28 定版形态 · 逐项对照 + MTP 全解释假设裁决 + rex10 执行序

**作者**：archi7（系统架构师，engineering-w9r3-perf）｜**日期**：2026-08-29｜**任务**：Task #12（team-lead 派单）
**方法**：纯本地。本地档案（kernel-path-audit / diff-matrix / W6/W7/W8 终局 / w9-port-assessment / w9-mtp-community-scan / w9-known-issues-crosscheck / w9_mtp_run.sh 实脚本）+ WebFetch 上游两仓（LuZ0.3.1 全套 FINAL-METRICS / README / 05-kernels-patches 清单；MiaAI ENVS.md 全表）。未触碰集群；一切集群真值归 rex10 实测。
**被审计对象锚点**：生产 DE c1=108.84（B1BASE_20260818 rows_v2.csv 三轮 109.81/105.06/108.84，bench_v2 系 harness）vs 0.28 定版 DE c1=34.52（rex8-S4b/S5，同 harness 族，team-lead 派单口径）。

---

## 0. TL;DR（五句话裁决）

1. **"MTP 全解释"假设大概率不成立，但需一次实验定谳而非纸上翻案**：34.52×3≈103.6 的闭环把三个未审计因子（MoE 路径 W4A8 vs W4A4、KV 4bit vs 8bit、linear-face 是否脱靶）全部记为零，过于乐观。FINAL-METRICS G1 同窗硬证显示 MoE 量化路径在 decode 侧并非零差（W4A4 在 C1 快于 W4A16 3.1%，且差距随并发放大至 +17.9%）；社区同栈记录 b12x vs deepgemm decode 差至 2x（不同代内核，须下修）。
2. **本次审计最大的新增发现：0.28 定版启动脚本（w9_mtp_run.sh）没有 `--linear-backend torch`** → auto 序首位 `FlashInferFp8DeepGEMMDynamicBlockScaled` 截胡，而生产 dense/shared/attention 投影面走 cuBLASLt 链（kernel-path-audit B2/D1 明证：torch 在序列末位，必须显式）。当前 34.52 可能在**所有 FP8 block 投影层**上与生产不同库、不同核——这是零成本可查、flag 级可修的第一嫌疑。
3. **attention backend 之争是伪命题**：kernel-path-audit B3 源码实证——cc12 上显式 `FLASHINFER_MLA_SPARSE_DSV4` 与默认选择落到**同一个类**（DeepseekV4FlashInferSM120Attention）。显式启用纯属防静默漂移的 defensive flag（±0 性能），但建议加，因为 D5 教训是"选择器会静默换后端"。两边 FlashInfer（0.6.16 / 0.6.16.post3）在无 MTP decode（topk=128）路径上内核对称，无差距来源。
4. **真正的结构性差距（0.28 无原生入口）：KV nvfp4_ds_mla（4bit）vs fp8_ds_mla（8bit）**——生产 decode 注意力读 KV 带宽减半；短上下文 DE c1 幅度有限（估 <5-10%），长上下文 DE 是硬差距，且 SM12x 白名单（D5）判 patch 级不可行动。其余 fork 资产（plugin_a1 / W4A4-on-MXFP4 / shared wrapper 池化）维持"不搬运、原生替代"裁决不变。
5. **裁决实验 = rex10 主线本来就要做的 MTP S1 复测**，只需预先定好判读带：DE c1（MTP 接入后）≥95 → "全解释"基本成立（残差 ≤12%，追赶路线=MTP 主线+微调）；78–95 → MoE/graph/KV 残差 12–28% 坐实，按 §4 执行序逐项回收；<78 → 先查 accept-rate（prose 类任务 accept 可低至 0.40）与 issue141/64 行哨兵，再谈路径残差。

---

## 1. 测量口径预警（先立尺子再比数字）

在逐项对照前必须声明三处口径事实，否则任何"差距归因"都会失真：

| # | 口径事实 | 出处 | 含义 |
|---|---|---|---|
| 1 | **108.84 是 bench_v2 系（本地 harness）DE coding c1 三轮中位**（109.81/105.06/108.84），非 LuZ 官方 benchmark 包口径。LuZ 官方 decode-only C1 = 73.9（中位）/136.5（best）——同栈不同尺差达 ±45% | W7 报告 §7；LuZ FINAL-METRICS §2.4 | 34.52 与 108.84 同 harness 族可比（14.99→34.52 与 108.84 均同族），**结论可用**；但任何跨 harness 对比（如官方 73.9）不得用于裁决 |
| 2 | **生产形态有漂移**：util live=0.78（W8 inspect）vs README/FINAL-METRICS 0.82；batched-tokens 4096（采纳时）→8192（08-26 加固）；108.84 采于 08-18，此后生产经历过 8192 切换与 NCCL 加固 | W8 报告 §2.4；FINAL-METRICS §1；w9-port-assessment 诚实账#8 | 108.84 与"当前生产形态"之间隔了两次变更，其可复现性本身标"待集群实测"（PR@4K 3060 同理：3060 实为 FINAL-METRICS §2.2 C6 样本之一，单流 4K=2950.5） |
| 3 | **2.5x graph 因子是 W7 纸面估计，0.28 侧实测回收比 = 34.52/14.99 = 2.30x** | W7 §3.2；W8 §4 | 若 2.30x 是 graph 因子真值，则"MTP×3"分母被高估 8%，闭环的 -4.8% 余量并不存在而是恰好用尽——进一步削弱"全解释" |

---

## 2. 第一部分：逐项对照表（生产每一环 vs 0.28 现状）

图例：**判**=性能影响方向与幅度估计（标注证据强度：▲本地实测 / △上游同构数据 / ○纸面推断）；**行动**=0.28 侧可行动性（env / flag / patch / 不可用 四级）。

### C1 · MoE 量化路径与内核（最大结构差）

| 维度 | 生产 LuZ0.3.1（0.26 fork） | 0.28 定版 |
|---|---|---|
| 量化组合 | **W4A4 full**：`VLLM_MOE_W4A4=2`（+`MIN_M=3072` 切换阈值 + `CG=1` w4a4 专属 cudagraph），plugin_a1 生产插件，b12x 系融合核（dispatch+2×GEMM+SwiGLU+reduce 单核） | **W4A8**：deep_gemm `DeepGemmFP4Experts`（kMxfp4Static × kFp8Dynamic128Sym），`m_grouped_fp8_fp4_gemm_nt_contiguous` + fused silu/swiglu clamp quant；激活需 FP8-128block 动态量化；**DE 小 M 需 contiguous grouped 布局按 block_m 对齐填充，无小 M 专用核切换** |
| 入口 | `VLLM_MOE_W4A4=2`（fork env） | `--moe-backend deep_gemm`（w9_mtp_run.sh 已显式，D2 锁到位） |

- **判**：方向=生产占优。证据链：① G1 同窗对照（▲△）：W4A4 decode C1 快 3.1%、C12 慢 17.9%——证明 MoE 量化路径选择在 decode 是可测量变量，不是零；② 社区同栈记录（△，不同代内核下修使用）：tonyd2wild "VLLM_USE_B12X_MOE=1 是全部速度差异，=0 掉 DEEPGEMM_MXFP4 decode 减半"——b12x 系 vs deepgemm 系 decode 历史差距最大到过 2x；③ 小 M 填充开销（▲kernel-path-audit DE 表）是 0.28 独有的确定性劣化项。**综合估计：decode 侧 MoE 环节差 10–30%（e2e 换算 MoE 占 decode 时 ~40-55%，即 e2e 4–15%），下限按 G1 -3.1% 修正为"未必到 15-25% 上界"。**
- **行动**：0.28 上 MXFP4 权重**无 W4A4 原生入口**（mxfp4 oracle 映射表无 flashinfer_cutlass/b12x 键，误配 ValueError——D4/重构铲除，判"不可用"）。原生等价对照臂只能走 **nvfp4 权重 + `--moe-backend flashinfer_b12x`**（W4A4，镜像内 b12x 符号四项探测全 True，首启 JIT 预算 ≥10min）。对照实验设计见 §3.2/§4。

### C2 · Linear 投影面（dense / shared expert / attention QKV 投影）——⭐ 本报告最大新增发现

| 维度 | 生产 | 0.28 现状 |
|---|---|---|
| FP8 block face 内核 | fork 链 cuBLASLt 13.6.1.10（BlockWiseTorch 等价物；r2/r3 验收事实互证） | **w9_mtp_run.sh 未传 `--linear-backend`** → auto 序 `_POSSIBLE_FP8_BLOCK_KERNELS[CUDA]` 首位 **FlashInferFp8DeepGEMMDynamicBlockScaled** 截胡（BlockWiseTorch 在末位） |
| 涉及张量 | wq_a / fused_wqa_wkv / wq_b / wo_a / wo_b / **shared experts gate_up/down** / indexer / compressor | 同左（全部走 block face） |

- **判**：方向=不确定但**当前 0.28 侧状态未取证**。两种可能：① auto 选中的 FlashInferFp8DeepGEMM 恰好更快（新核、动态块缩放）→ 34.52 已含此项增益；② 小 M decode 下 FlashInfer deepgemm 劣于 cuBLASLt（小批量 GEMM 库差常见 10-30%）→ 34.52 被压低而生产无此税。**当前无任何一侧日志/实测能裁决——这是"剩余差距未审计部分"里成本最低、嫌疑最大的未取证项**（○，但机制部分 ▲ 源码级确凿）。
- **行动**：**flag 级，双臂即可裁决**。①零成本先查：启动日志 `grep "Selected .*LinearKernel for"` 必须逐层看清实际命中（kernel-path-audit PW3 原生要求，当前定版形态从未对过账）；②对照臂 `--linear-backend torch` vs 缺省 auto，DE c1 各一轮。预期收益：若命中方向为 torch 占优，decode 小 M GEMM 差 10-30% 完全可能。

### C3 · 共享专家处理

| 生产 | 0.28 |
|---|---|
| `VLLM_B12X_SHARED_WRAPPER=1` 池补丁：跨层 wrapper 去重 + 权重池化省 22.8GiB（45.32 vs 68.15）；计算走 b12x 系融合路径；P0 拆账实测 shared experts = 6.98µs/token（占投影池 32.2%） | shared expert = 普通 FP8-block linear，走 C2 同一 face 决议（auto→FlashInferFp8DeepGEMM；显式→cuBLASLt） |

- **判**：**池化（22.8GiB）是内存项不是计算项**，对 DE c1 速度无直接贡献（对 KV 容量有间接贡献）；计算面上生产与 0.28 的差异**归并进 C2**（同 face 同核）。生产 P0 拆账显示 shared 投影在 decode 带占 1.99ms/step（M=8）——是 decode 时长的实质组成，C2 的库差会按比例传导到这里。○（归并 C2）。
- **行动**：无独立动作，随 C2。B12X_SHARED_WRAPPER 本身判"不移植"（挂载点被 #44941/#51078 重构铲除，w9-port-assessment §2.1 已裁，维持不变）。

### C4 · Attention backend（含"是否该显式启用"的正面回答）

| 生产 | 0.28 现状 |
|---|---|
| FI 0.6.16（bind-mount + JIT 缓存）+ fork 隐式选 B12X 系稀疏 MLA（env 驱动） | FI 0.6.16.post3；**未显式** `--attention-backend`；模型类 `_select_dsv4_attn_cls`：cc.major==12 且无显式配置 → `DeepseekV4FlashInferSM120Attention`（默认即 SM120 稀疏 MLA） |

- **正面回答"是否该开"**：源码实证（▲kernel-path-audit B3）——cc12 上显式 `FLASHINFER_MLA_SPARSE_DSV4` → **同一个类**。所以这不是性能开关，是**防静默漂移的 defensive flag**：D5 教训 = "选择器在组合不满足时会静默遍历下一候选"；显式化让任何漂移变成启动期 ValueError。**建议加（零成本、零风险），但不要期待 DE 增益（±0）。**
- **内核对称性**（▲）：无 MTP decode 的 topk=128 在 0.6.16/0.6.16.post3 的 dispatch 矩阵（128/512/1024）内 → **无 MTP 状态下两边 attention decode 内核同源，差距不来自这里**；topk=192 缺失只是 MTP blocker（w9-r2 已裁，rex10 S1 主线）。
- **行动**：flag 级（加 `--attention-backend FLASHINFER_MLA_SPARSE_DSV4`，与 kernel-path-audit C2 定稿模板对齐）。

### C5 · KV cache 量化（结构性差距，0.28 不可行动）

| 生产 | 0.28 现状 |
|---|---|
| **nvfp4_ds_mla**（4bit KV，fork kernel2 MLA KV linear；KV tokens 5.73M） | **fp8_ds_mla**（8bit）；SM12x 白名单仅 {fp8, fp8_e4m3, fp8_ds_mla}，nvfp4 系**整体不可达**（D5：enum 有、消费方无） |

- **判**：方向=生产占优（decode 注意力是 KV 读带宽受限，4bit KV 字节减半）。幅度分层：DE coding 短上下文（c1 任务 ~512-8K ctx）KV 读量小，估 **e2e <5-10%**；长上下文 DE（生产 400K decode ≈99.6 t/s 场景）为硬差距且 0.28 侧连能力都不存在。另有 block 布局疑点（diff-matrix §6：0.28 原生 block 几何与 fork 可能不等价）——并入此项记档。○（方向确定，幅度未实测）。
- **行动**：**patch 级以上，判"不可用"**（需 SM12x 消费方内核 + issue22 族修复回移，超出旁路）。诚实记为永久 gap，不进 rex10 执行序。

### C6 · CUDA graph（形态差 + 因子账）

| 生产 | 0.28 现状 |
|---|---|
| **FULL** capture 十六档 1..96（`--max-cudagraph-capture-size 96` + 显式 sizes） | **FULL_AND_PIECEWISE**（compilation-config；eager 已移除） |

- **判**：① factor 账（▲）：eager 移除实测回收 2.30x（14.99→34.52），vs W7 纸面 2.5x——回收比略低于预估，本身给"其他残差存在"留了口子；② 形态账（○）：PIECEWISE 在 attention 处分段，段外节点保留 eager launch → decode 小 M（1–12 行）对 launch 开销敏感，FULL vs PIECEWISE 残差通常在个位数百分比；生产是 FULL，严格对齐存在理论残差。③ 风险（▲）：0.28 侧 FULL 模式在 dspark/新 runner 上有 capture 失败回退 eager 的已知风险面（D8），试 FULL 臂必须挂 capture 失败哨兵。
- **行动**：flag 级试臂（`--compilation-config '{"cudagraph_mode":"FULL"}'` vs 现状），预捕获金丝雀验证 capture 成功再进 DE（防静默回退 eager 污染对照）。

### C7 · 调度器与批次参数

| 生产 | 0.28 现状 |
|---|---|
| batched-tokens 8192（08-26 加固后）/ threshold 4096 / max-num-seqs 12 / scheduling-policy priority / **--enable-flashinfer-autotune**（diff-matrix E15 列生产配置） | 8192 / 4096 / 12 已对齐（w9_mtp_run.sh）；**priority 未设、flashinfer-autotune 未设、async-scheduling 未设** |

- **判**：① autotune 缺失（○）：autotune 按 shape 调优内核选择，decode 小 M 是其主要收益区，方向=生产占优、幅度未知（且 MTP 接入后 autotune 与 #51538 门禁交互需先过 S1-S3）；② priority 对 c1 单流零影响、对混合负载有意义；③ async-scheduling 生产未用（inspect 无此项），**不应作为"生产对齐"项**，社区配方（tonyd2wild）虽含它但那是不同栈——判为"0.28 侧独立试臂项"而非对齐项，优先级低。
- **行动**：全部 flag/env 级。autotune 建议在 MTP 通（S1-S3 后）再开（先单变量隔离）；priority 一行补齐（零风险）；async-scheduling 独立臂观察。

### C8 · o_proj 硬连路径

| 生产 | 0.28 |
|---|---|
| fork wo_b 融合投影（B12X_WO_PROJECTION=1 系） | `_o_proj` **硬编码** `deep_gemm_fp8_o_proj`（+fused_inv_rope_fp8_quant），不受 --linear-backend 影响（▲B3） |

- **判**：两边都是 deep_gemm 系融合投影，等价带（○）。无独立动作；日志哨兵=无 `_missing` 栈（PW4 原有项）。

### C9 · FlashInfer / 底座版本

| 生产 | 0.28 |
|---|---|
| FI 0.6.16（手动 bind-mount）+ 0.26 fork（torch/cu 13.0 系） | FI **0.6.16.post3**（镜像内建）+ torch 2.13.0+cu130 + transformers 5.15.1 |

- **判**：FI 两侧同代（.16 系），**无 MTP decode 路径内核对称**（▲，见 C4）；.post3 与 .16 的 patch 差异对已命中核无可测影响（○）。注意：PR #51538 作者 rig 用 torch 2.13.0+**cu132**，我 0.28 r3 为 cu130——同族不同 patch，记入诚实账（MTP S1 装 0.6.18 nightly 时须匹配 cu130）。fork 的 torch 小版本差异无法本地判定 → 待集群实测（无法本地判定项）。
- **行动**：S1 升级 flashinfer 时 `pip install --no-deps` + `FLASHINFER_DISABLE_VERSION_CHECK=1`（w9-r2 §四既定），cu130 匹配核对加入。

### C10 · dspark MTP 周边旋钮

| 生产 | 0.28 |
|---|---|
| 0.26 fork：`VLLM_DSPARK_LOCAL_ARGMAX=1` 等 fork env | 0.28 原生：#49793 local-argmax 融合已内置（自动）、#47808 confidence 调度、#51725 自适应预算 |

- **判**：语义原生等价（▲diff-matrix S2 行），**旧 env 在 0.28 被静默忽略，不得沿用**。MTP 本体接入属 rex10 S1 主线，本报告不重复设计，只提供 §3 判读带。
- **行动**：无（勿设旧 env）。

### C11 · NCCL / 通信栈

- 生产与 0.28 已同构：ringonly md5 2be94172 在位、pin 库、conf 双层、env 十项（W7/W8 铁证）；W8 终局 = 零变更。大消息回退已被 W8 A 臂证伪（W7 读数为环境污染）。**通信侧无未决差距项**——唯一挂账是 spin-wait #79（0.28 未含修复，w9-r2 §3.2r 已给容器层 patch 方案，判 P1 灰度后试，不与本表主线混投）。
- **行动**：无新增；spin-wait 维持 w9-port-assessment 既定排程。

### C12 · MoE 激活量化开销（并入 C1 的机理注记）

- 0.28 W4A8 路径每 expert 前需激活 FP8-128block 动态量化 + contiguous 重排（DeepGemmFP4 的 fused quant 在 kernel 内，但 contiguous 分组的 pad/mask 逻辑在小 M 下占比升高）；生产 W4A4 是 BF16 hidden 直进核内 FP4 量化（无独立量化 pass）。此开销已含在 C1 的 10-30% 带内，不单列行动项。

---

## 3. 第二部分（汇总）+ 重点破题：34.52×3=103.6≈108.84 的"MTP 全解释"是否成立

### 3.1 差异项总表与预期收益排序

| 排序 | 项 | 方向 | 幅度估计（DE c1 无 MTP 基线 34.52 上） | 证据强度 | 可行动性 | 预期 DE 增益 |
|---|---|---|---|---|---|---|
| 1 | **C2 linear-face 脱靶嫌疑** | 未知（两侧皆可能） | 命中则 10-30%（环内） | 机制▲/方向○ | **flag**（零成本双臂） | 0～+30%（conditional，最大未取证项） |
| 2 | **MTP S1 接入**（rex10 主线） | 生产占优 | ~3x（acceptance 依赖） | ▲ | 已在主线 | ×2.6-3.0 |
| 3 | C1 MoE W4A8 vs W4A4 | 生产占优 | 环内 10-30% → e2e 4-15% | △○ | **不可用**（MXFP4 无入口）/对照臂走 nvfp4+b12x | 0～+15%（需换权重，非定版形态） |
| 4 | C6 FULL vs FULL_AND_PIECEWISE | 生产占优（小 M launch 残差） | e2e 3-8% | ○ | flag 试臂 | 0～+8% |
| 5 | C5 KV 4bit vs 8bit | 生产占优 | 短 ctx e2e <5-10%；长 ctx 大且无解 | ○ | **不可用**（patch+） | 0（记 gap） |
| 6 | C7 autotune | 生产占优 | 未知，decode 小 M 收益区 | ○ | flag（MTP 通后再开） | 0～+5% |
| 7 | C4 attention 显式化 | ±0（同类） | 0 | ▲ | flag（defensive） | 0（防漂移） |
| 8 | C7 priority / async-scheduling | ±0～小 | c1 单流 ≈0 | ○ | flag | ≈0（c1 口径） |
| 9 | C11 spin-wait #79 | 生产已修我未修 | 方向性（TP4 幅度未实测） | △ | 容器 patch（既定排程） | TPOT 方差项非吞吐项 |
| — | C3 shared wrapper / C8 o_proj / C10 dspark 旋钮 / C11 NCCL | 等价带 | ≈0 | ▲ | 不动作 | 0 |

### 3.2 反证法：若"MoE 路径有 15-25% 劣势"，108.84 从哪来？

派单反证框架的严格化：

- **假设 A（全解释）**：非 MTP 因子残差 = 0。检验：108.84 ÷ 3 ÷ 34.52 = 1.050 → 要求 graph 因子恰好 3.0/2.30×1.05 —— 需要"MTP 恰 3.00x **且** 0.28 graph 形态与生产 graph 等值 **且** MoE/KV/linear 全部零差"三个条件同时成立。
- **假设 B（残差存在）**：若 MoE e2e 劣势 15%（环内 30%+小 M pad）+ KV 5% + graph 形态 5%，则 MTP 接入后预测 = 34.52 × 3 ÷ 1.15 ÷ 1.05 ÷ 1.05 ≈ **81.8**，比 108.84 缺 25% —— 缺口不会消失，只会从"接入前"挪到"接入后"。
- **削弱假设 A 的三个独立证据**：① C2 linear-face 当前未取证（auto 截胡 vs 生产 cuBLASLt）——"全解释"把一个未知量当成了零；② 2.30x 实测回收 vs 2.5x 估计（§1-3）已消耗掉闭环的表观余量；③ G1 同窗证明 MoE 量化路径是 decode 可测量变量（C1 -3.1%），"量化路径零差"没有先例支持。
- **支持假设 A 的证据也如实列出**：PR@4K 0.28 反超生产 +15%（prefill 通路无残差，残差只可能在 decode 特有路径：graph 形态/M padding/KV 带宽/linear 小 M）；W5 时代 TTFT/prefill_tps 与 B1 同数量级。
- **裁决实验（判定性的，且是 rex10 必做项）**：MTP S1（flashinfer 0.6.18）后 DE c1 复测，判读带：
  - **≥95 tok/s** → 假设 A 基本成立（残差 ≤12%），追赶路线收敛为 MTP 主线 + §4 第 3/4 顺位微调；
  - **78–95** → 假设 B 坐实（残差 12–28%），按 §4 顺序逐项回收，预期落 95-108 带；
  - **<78** → 先查 accept-rate 分任务口径（prose accept 可低至 0.40，▲smoke 实测 0.3995）与 issue141 64 行 / running≥9 哨兵、APC+graph 质量哨兵（#115 族），排除"非路径性劣化"后再谈残差。
- **MoE 路径独立对照臂（回答派单②的正确姿势）**：0.28 上 `--moe-backend flashinfer_cutlass` 对 MXFP4 权重**不成立**（mxfp4 oracle 映射表无此键，ValueError 硬失败——修正派单中的对照臂设想）。合法对照设计二选一：
  - **臂 X（推荐，同权重）**：deep_gemm（现状）vs `--moe-backend marlin`（W4A16 负对照）。预期 marlin 更慢——只能证明方向敏感性，不能给出 W4A4 等价增益；
  - **臂 Y（真 W4A4 等价，需换权重）**：0731-nvfp4 权重 + `--moe-backend flashinfer_b12x`（+`--linear-backend b12x`）vs MXFP4+deep_gemm，同轮 DE c1。这是"生产 W4A4 在 0.28 的原生等价形态"唯一可达路径。前置：nvfp4 权重 96 shard sha256 全量校验（PW5 未销案）+ b12x 冷启 JIT 预算 ≥10min + D3/D5/D9 三查日志。**若臂 Y 显著快于臂 X 且能复制，"0.28 定版形态应切 nvfp4 权重"将成为独立决策项**——影响面大，需 team-lead 单独裁决。

### 3.3 结论

"全解释"假设**未经证明且先验偏低**（三个未审计因子中至少 C2 是真实的未知量）；但它**也不需要被纸上推翻**——它的证伪/证实成本已经被 MTP S1 主线吸收。工程上正确姿势：把 §3.2 判读带写给 rex10 预先钉死，接入后对带入座，避免"接入后看到 ~100 就宣布闭环"的确认偏误（103.6 恰在判读带下沿，若 acceptance 略低会伪装成闭环）。

---

## 4. 第三部分：可行动项执行序（给 rex10）

> 纪律：单变量、每臂 DE c1 同 harness 三轮取中位、基线臂 = 当前定版形态（34.52 带内复现一轮开场）。grep 类哨兵不占窗口。

| # | 动作 | 具体命令/参数 | 预期 DE c1 增益 | 单变量验证法 | 前置/哨兵 |
|---|---|---|---|---|---|
| 0 | **linear-face 取证（零成本，最先做）** | 现栈启动日志：`grep "Selected .*LinearKernel for"` 与 `grep "was requested, but no"` | —（纯取证） | 记录每 face 实际命中核（FlashInferFp8DeepGEMM vs BlockWiseTorch） | 若已命中 BlockWiseTorch → 本表第 1 项直接销案 |
| 1 | **linear-face 对照臂** | 臂 A=缺省 auto；臂 B=加 `--linear-backend torch`（FP8 block face→cuBLASLt）；其余全同 | 0～+30%（conditional） | 两臂 DE c1 各三轮；同时 `VLLM_DISABLED_KERNELS=MarlinFP8ScaledMMLinearKernel` 两臂同设防截胡漂移 | 启动日志逐层命中留痕；慢臂保留数据不回滚 |
| 2 | **MTP S1 + 判读带入座**（主线） | `pip install --no-deps flashinfer-python==0.6.18.dev20260811`（核对 cu130 匹配）+ `FLASHINFER_DISABLE_VERSION_CHECK=1`；S0 四问取证（192 内核 / #51538 门禁 / TRITON 注册）照 w9-r2 §四执行 | ×2.6-3.0 | 接入后 DE c1 对照 §3.2 三判读带（≥95 / 78-95 / <78），对带入座出结论 | running≥9 哨兵（issue141）、c>1 accept 哨兵、#115 质量哨兵（GSM8K-20） |
| 3 | **cudagraph FULL 试臂** | `--compilation-config '{"cudagraph_mode":"FULL"}'` vs 现状 FULL_AND_PIECEWISE（MTP 通后做，capture 形状族含 draft） | 0～+8% | 两臂 DE c1；启动期金丝雀确认 capture 成功（`grep -i "capture.*fail\|fall back to eager"` 应为空） | capture 失败即弃臂，不追 |
| 4 | **MoE 路径臂 Y**（team-lead 裁决后） | nvfp4 权重 + `--moe-backend flashinfer_b12x --linear-backend b12x` vs 定版 MXFP4+deep_gemm | 信息项（决定是否切权重形态） | 同轮 DE c1 + PR@4K；三查日志（D3/D5/D9）留痕 | PW5 sha256 校验；JIT 预热 ≥10min；**切权重形态属重大决策，不在本窗执行序内** |
| 5 | **autotune 臂**（MTP 通后） | 加 `--enable-flashinfer-autotune` | 0～+5% | DE c1 两臂；观察冷启时长变化 | 与 #51538 门禁交互先过；冷启预算 +N min |
| 6 | **defensive 参数补齐**（可与任一臂同行，不构成变量） | `--attention-backend FLASHINFER_MLA_SPARSE_DSV4` + `--scheduling-policy priority` | ≈0（防漂移） | 无需单臂；启动日志确认无静默 fallback | — |
| 7 | spin-wait #79（既定排程，S8 灰度后） | w9-r2 §3.2r 方案 A（sed busy_loop_s 1→0.002） | TPOT 方差项 | A/B 各 ≥3 轮取中位：TPOT、AR stall 频次、SM 功耗曲线 | 禁与 concurrency_proxy/预捕获同窗混投 |

**不执行清单（防止无效动作）**：❌ `--moe-backend flashinfer_cutlass`（MXFP4 权重必 ValueError）；❌ nvfp4_ds_mla / nvfp4 KV（白名单不可达）；❌ 沿用 fork env（VLLM_MOE_W4A4 / B12X_SHARED_WRAPPER / DSPARK_LOCAL_ARGMAX——0.28 静默忽略）；❌ 移除 `--moe-backend deep_gemm` 显式锁（D2 防坠 MARLIN）；❌ SpeculativeConfig.attention_backend 覆写（社区无效先例，w9-r2 §c）。

---

## 5. 第四部分：诚实账（无法本地判定处）

| # | 事项 | 状态 |
|---|---|---|
| 1 | 0.28 定版栈 linear-face 实际命中核（C2 截胡与否） | **待集群实测**（rex10 第 0 项 grep，1 分钟销案）——本报告第 1 嫌疑的定谳点 |
| 2 | 108.84 在当前生产形态（8192 切换+NCCL 加固后）的可复现性 | 待集群实测（生产侧 DE c1 复测一轮即可锚定；PR@4K=3060 出处同判） |
| 3 | MoE 环内差距幅度（C1 的 10-30% 带是三角推断：G1 对照+社区同栈+pad 机理） | 待集群实测（臂 Y 或臂 X；臂 Y 依赖 team-lead 裁决） |
| 4 | FULL vs FULL_AND_PIECEWISE decode 残差幅度 | 待集群实测（第 3 臂） |
| 5 | KV 4bit 短上下文幅度（<5-10% 是机理推断） | 待集群实测（无法在 0.28 侧测——KV 面不可达，只能靠臂间差分倒推） |
| 6 | autotune 增益 | 待集群实测 |
| 7 | 0.26 fork torch 小版本 / 0.28 cu130 与 #51538 rig cu132 的行为差 | 无法本地判定，记档；S1 装 nightly 时以 cu130 匹配为准 |
| 8 | "34.52"原始留证未在本地档案中检得（ rex8-S4b/S5 报告未同步到本地目录；`34.52` 字符串本地零命中） | 依 team-lead 派单口径入账；建议 rex8 留证归档后回填本报告 §1 口径表 |
| 9 | 本报告全部为纸面审计，未触碰集群 | 声明；一切真值归 rex10 |

---

## 6. 证据索引

| 来源 | 关键内容 |
|---|---|
| 本地 kernel-path-audit-2026-08-27 | B1 MoE 分派（W4A8 定型/mxfp4 oracle 键集）/B2 linear 序列与 torch 末位/B3 attention 类选择与 KV 白名单/B5 DE 周期表（小 M pad）/D1-D12 静默降级/C2 启动定稿模板 |
| 本地 diff-matrix-2026-08-27 | E7 priority/M3 MIN_M/S2 local-argmax 原生/G1 graph 形态/§6 KV block 几何疑点 |
| 本地 W7/W8-FINAL | 108.84 出处（B1BASE rows_v2.csv）/14.99/PR 反超 +15%/2.5x 因子估计/生产 inspect 全参（FULL 十六档、无 enforce-eager、8192、util 0.78）/W8 通信零变更 |
| 本地 w9-port-assessment / w9-mtp-community-scan / w9-known-issues | b12x 不移植裁决/tonyd2wild "B12X_MOE=1 即全部速度差"/spin-wait 方案/issue141 哨兵/#115 质量哨兵/MTP S0-S7 执行清单 |
| 本地 w9_mtp_run.sh（实脚本逐行） | 0.28 定版实参：无 --linear-backend、无 --attention-backend、无 priority、无 autotune、moe=deep_gemm、enforce-eager（S4b 谱系已移除）、FULL_AND_PIECEWISE（S5 谱系） |
| LuZ0.3.1 FINAL-METRICS（WebFetch） | G1 W4A4 vs W4A16 同窗 decode 对照（C1 -3.1%→C12 +17.9%）/P0 拆账（shared 6.98µs 占 32.2%）/官方 C1 73.9\|136.5/生产形态漂移三处（util/batched/KV tokens 5.73M） |
| LuZ0.3.1 README + 05-kernels-patches 清单（WebFetch） | 生产形态基线行/plugin_a1-kernel2-routeB 资产定位/57 篇内核报告主题图（本审计只采清单级，未逐篇展开） |
| MiaAI ENVS.md（WebFetch） | Lane B 的 VLLM_DSPARK_* 全族（0.28 侧不适用佐证）/spin-wait/JIT cache/flight recorder 现值/无 W4A4 变量存在（"⚠️ 文档中不存在任何 W4A4 变量"——W4A4 确系 LuZ fork 私有语义的旁证） |

*报告完。口径纪律：不确定标待验、推断注明推断、集群真值归 rex10。*
