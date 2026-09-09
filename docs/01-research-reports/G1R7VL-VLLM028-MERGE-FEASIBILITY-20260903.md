# vLLM 0.28 合入可行性调查结论（2026-09-03）

前置：服务器异常重启后恢复；本轮全部轻量操作（web 调研 + 镜像内 grep，无构建无重启）。本地 fork 定制面盘点 + 上游事实链（vLLM releases/PR API、flashinfer #4781、eugr #363/#370、vllm-gb10 versions.env、recipes 页交叉核实）。

---

## 结论（一句话）

**有条件合入，但"合 0.28"本身是个错位的目标**：我们最想要的 Vision-Exp 支持（#54566）只进了 main/0.29，不在 0.28.0；0.28.0 真正能拿到的是 adaptive verification（#47808）、自适应预算（#51725）、量化 Markov 头（#50424）和 b12x MoE 上游化（#52016/#52018）。**建议双轨起步（0.26 生产不动 + 0.28 试验栈验证），等 0.29.0 后做一次全量 rebase；不做向 0.26 的 backport**。

## 1. 关键事实（含一个目标反转）

| 事实 | 出处 |
|---|---|
| v0.28.0 = 2026-08-26 发布；0.28.1 无正式版；nightly = 0.28.1rc1.devNNN（有官方 aarch64 wheel） | GitHub releases + PyPI + wheels.vllm.ai |
| **#54566（Vision-Exp）merged 2026-09-02，晚于 0.28.0 八天 → 只在 main/0.29**；官方 recipes 明写 "requires 0.29.0+"，且官方验证平台是 GB200 非 GB10 | PR #54566 + recipes.vllm.ai |
| 0.28.0 含：#47808 adaptive verification、#51725 自适应 spec 预算、#50424 量化 Markov 头、b12x FP4 MoE（#52018）与 dense linear（#52016）、SM12x XQA decode（#49718）、GB10 MoE FP8 调优（#52502） | v0.28.0 release notes |
| b12x attention（#52017）09-01 才合 → 0.29；eugr 的 b12x 实际跑的是 local-inference-lab fork（"接近 0.28.x"，含未上游的 DS4F 稳定性修复，#356 乱码/#358 acceptance 塌缩仍 open） | flashinfer #4223、eugr #363/#370 |
| flashinfer-cubin 断供（#4781）有 4 条解：flashinfer.ai/whl 装匹配 cubin / 卸载走 JIT / `flashinfer install-cubin-wheel` CLI / vLLM main 的双 pin 模式 | flashinfer #4781（官方 08-28 确认为 PyPI 10GB 限制所致） |
| **GB10 上 0.28.0 的存在性证明：vllm-gb10 仓库 = v0.28.0 + FlashInfer 0.6.16.post3 源码构建 + NCCL 2.31.2 源码 + torch2.13/triton3.7/CUDA13.2/12.1a，全 SHA pin，CI 绿** | timothystewart6/vllm-gb10 versions.env |
| pin 矩阵：0.28.0 ↔ flashinfer 0.6.16.post3；main/0.29 ↔ 0.6.17/0.6.18 | v0.27.0 notes + vllm-gb10 + #54566 测试矩阵 |

## 2. 我们 fork 的定制面（本地盘点，2026-09-03）

- deepseek_v4 模型树 **39 个 py 文件**（nvidia/amd/xpu 三平台 + 自定义 cutedsl ops）——与 #47808/#54566 的改动文件**正面重叠**（两 PR 都直接改三平台文件+qwen3_dspark+sparse_mla）。
- **两套 speculator 实现**：fork 自有 dspark/dflash 栈（G1r5-9 内部优化，含 WKV_ONLY、draft_logits fp32、wkv_only 双载等）vs 上游 dspark（#46995）——rebase 时必须二选一或合并。
- **5 个自编译 C++ 扩展**（persistent_topk 门控等）+ 手改 flashinfer 0.6.18 JIT（TK512）——需对新栈（torch2.13/triton3.7/flashinfer0.6.16+）重编重验。
- 深度 tokenizer 定制（tokenizers/deepseek_v4*.py，toolfix1 血统）——#54566 恰好也改 deepseek_v4_encoding（+35/-3）。
- 11 个专属 env、b12x 接入点（config/kernel.py）、NCCL ringonly LD_PRELOAD、autotune 烘焙。

## 3. 三条路工程量（判定）

| 路 | 工程量 | 判定 |
|---|---|---|
| a1 全量 rebase 到 0.28.x（实际应取 0.29 或 0.28.0+定点 cherry-pick #52017/#54566） | **4-8 人周**：39 文件树三方合并、两套 speculator 取舍、5 扩展重编、b12x 迁移到上游 #52016/#52018、env/autotune 对齐、ringonly 复验 | 一次付清拿全部，但 GB10 上多轮编译回归；且**只到 0.28 拿不到 vision** |
| a2 只 backport 四 PR 到 0.26 | **3-6 人周**：#50424≈零、#51725 小；但 #47808 依赖 varlen decode graph+AttentionCGSupport+MRV2 目录（0.27/0.28 基建），#54566 依赖 #47808+tokenizer 定制区+csrc 编译——**想要的两个恰是把 0.27-0.29 基建拖进 0.26 的两个** | ❌ 不做：比重摸上游贵 + 长期分叉债 |
| a3 双轨（0.26 生产不动 + 0.28 试验栈） | **1-2 人周起步**：直接复用 vllm-gb10 镜像（0.28.0 全 pin 可复现）与 eugr lil-fork 两条现成路线 | ✅ 风险最低，先用数据回答"上游 0.28 在我们 TP4 生产形态下到底什么水平" |

**已验证组合的边界**（必须诚实）：vllm-gb10 只验证了 0.28.0 基础栈在 GB10 单机/双机可跑；**"0.28 + DSV4 + DSpark + b12x + TP4 四机"的全功能组合没有任何公开验证**；eugr lil-fork 有 #356/#358 两个 open 稳定性问题；#47808 的 varlen graph 在 SM121 的 DSV4 backend 未被上游验证（PR 只写 SM100 report ALWAYS）；另有 SM12x sparse MLA `eidx must be contiguous` bug（#54566 评论，0731 也触发）与我们直接相关。

## 4. 建议路径与前置条件（按序）

1. **现在（无窗）**：固化为 0.29 目标；跟踪三件事——0.29.0 发布节奏、eugr #356/#358 修复去向（lil fork 的 DS4F 稳定性修复是否上游化）、SM12x eidx contiguity bug。
2. **试验栈（轻量窗）**：用 vllm-gb10 镜像在集群空闲期跑 DSV4-0731+DSpark 冒烟（cubin 走 flashinfer.ai/whl），测上游 0.28 的 spec 行为 vs 我们 fork——这一步只花一次轻量窗，产出 rebase 决策的核心数据。
3. **b12x 对比（同试验栈）**：上游 #52016/#52018 vs fork 自有 flashinfer_b12x 的 MoE 性能/精度对拍——决定 rebase 后 MoE 后端走哪条。
4. **rebase 决策门**：以上三项全绿 + 0.29.0 发布 → 立项 a1（基线 0.29.0），按 fork 资产迁移映射表执行（39 文件树→三方合并、5 扩展→csrc 矩阵、11 env→上游等价物核对、ringonly→NCCL 2.31 复验、autotune→#49315 机制）。
5. **回滚保证**：0.26/baked5 生产镜像冻结；GSM8K 逐位 + 工具编码用例作每阶段验收门（沿用 W1 门纪律）。

## 5. 与当前优化路线的关系

- baked5（C1+C2+SKIP 修复）与 0.28 无耦合，按既定 runbook 执行不受影响。
- #50424（量化 Markov 头）虽在 0.28.0，但按 a3/a1 路线它会随 rebase 自然到来，不值得为它单独 backport。
- #4802（flashinfer sparse MLA 重构）合入后 TK512 手改退役——该事项与 rebase 并行不悖。

---

# 附录：0.29 版本现状调查（2026-09-03 追加，目标固化为 0.29+ 后的复核）

## A1. 重大反转：#54566（vision）不在 0.29.0 里

- `releases/v0.29.0` 分支 08-31 cut，早于 #54566（09-02 合 main）与 #52017（09-01）；**两侧 registry.py 比对确认：release 分支无 DeepseekV4ForConditionalGeneration 条目**。官方 recipes 的 "requires 0.29.0+" 徽章与分支现实矛盾。
- 0.29.0 时点估计：tag ≈ 09-05~07、publish ≈ 09-07~09（rc1=09-02、rc2=09-03，节奏对齐前两轮）。**但对 GB10+vision 目标是"白等"**：vision/b12x-attn 都要等 0.30 周期（约 10 月上旬）。
- 结论修正：上一轮"等 0.29.0 后 rebase"改为 **"目标固化为 main 血统（≥0.30 周期），锚定三个上游件：#4802/#41834/#54631"**。

## A2. nightly/main 预览镜像的"已满足 vs 硬缺口"

已满足：官方 nightly aarch64 wheel 在产（0.28.1rc1.dev352=main，含 vision+b12x attn）；main pin 明确（flashinfer 0.6.18@flashinfer.ai/whl + torch 2.13.0，与我们 flashinfer 0.6.18 一致）；官方 pinned vision 镜像含 arm64-cu130 变体（Docker Hub 09-01）；Defilan 完整实测组合可对照。

**硬缺口（全部集中 GB10/SM121，均未修/未合）**：
1. SM12x sparse MLA `eidx must be contiguous`：main 未修，DSV4 decode 本身坏，唯一规避=叠未合的 #41834（288 commits，needs-rebase）
2. flashinfer 0.6.18 stock 无 SM12x vision prefill dispatch arms：#4802 approved 未合（CI 15/17，失败为 ECC），#4850 已关闭让位——须自编 flashinfer 分支
3. #52291 GB10 多节点 autotune 死锁：open，workaround=-35% 吞吐或 per-rank tuning（我们 TP4 四机正中此雷）
4. #54631 vision 权重流式加载+DSpark block width 修复：open 待审
5. eugr #356（长上下文乱码）/#358（acceptance 塌缩，根因=MiaAI fork 的 stale draft KV slot 补丁）：都不在 main

**判定：镜像"能构建"，但 GB10 上"原样可用"不成立——需自叠 4-5 层补丁（=重走 Defilan/tonyd2wild 的路）。条件不齐备。**

## A3. 修正后的固化目标与执行框架

- **版本目标**：main 血统 ≥0.30 周期（vision 进正式版的最早窗口）；不追 0.29.0（无 vision）、不追 nightly 原样（GB10 硬缺口未齐）。
- **三个合入锚点（rebase 立项门）**：flashinfer #4802 合入 → SM12x sparse MLA 栈可用；vLLM #41834（或其拆分片）合入 → eidx bug 根治；#54631 合入 → vision 加载修复。三者齐 → main/0.30 在 GB10 接近开箱可用。
- **双轨维持**：生产 0.26/baked5 照旧（runbook 不变）；上游预览栈以官方 pinned `deepseekv4-flash-vision-arm64-cu130` 镜像为锚（含 Defilan 组合做参照），只在集群空闲窗做只读验证，不承载生产。
- **我们栈 overlay 兼容面（本地已核）**：torch 2.11→2.13 代差=fork 5 个 C++ 扩展需重编；ringonly NCCL LD_PRELOAD 跨版本符号兼容未验（rebase 前置项）；flashinfer 0.6.18 与 main pin 一致（唯一已对齐项）。

## A4. 追踪清单（每周一次即可）

flashinfer #4802 合入状态；vLLM #41834/#54631/#52292/#52451；eugr #356/#358 修复上游化；0.29.0 发布确认（预期不含 vision）；0.30 周期开启信号；MiaAI Keys-concurrency patch 去向。

## A5. 增补（2026-09-07 第十轮复查）：#4802 已合入，锚点/门槛更新

- **锚点 1（flashinfer #4802）已于 09-03 合入 main**（merge `453aa7c`），含 TK=512 vision prefill arms、#4732 SM121 prefill-hang 修复、calibrated-cpb、L2 warming；GB10 实测 decode +26.2%（2×GB10 131K 新鲜 prompt）。**不在 v0.6.18.post1（09-05）**——正式获取途径=等 0.6.19 出轮或 main ≥`453aa7c` 自建（生产 A/B 候选窗"F1"，详见第十轮报告 §6）。
- **锚点 2（#41834/eidx）降级为"rebase 前实测复核项"**：上游零进展，但社区在 SM120 无 #41834 代码跑 main 零 eidx 错误（Hefulalala 09-03）——缺口可能已不触发，复核成本一次启动观察。
- **锚点 3（#54631）瘦身**：vision 权重流式加载半被作者 TP2 A/B 证伪移除（09-04）；剩 n_predict=5 修复，与我们 fork 无冲突。
- **多节点死锁族扩容**：#52292 获 DSV4+DSpark 实地验证；新增 #54618（暖 autotune 缓存不同步，正中我们 baked 暖缓存重启路径）——rebase 立项门改为 #52292/#54618 至少其一合入。
- **新增观察**：#55636（GB10 warmup 越界，open 无 workaround）；#55405（SM12x NVFP4 优先级 bug，main-only，我们 FP8 路径不受影响）；flashinfer #4955（NVFP4 sparse MLA，decode 1.31×）合入后为最大单杠杆。
- **0.29.0 截至 09-07 仍未发布**（releases 止于 0.28.0/08-26），"白等"结论维持；版本目标"main 血统 ≥0.30"不变，门槛构成按上更新。
- 同拓扑社区基准（voktolom 4×Spark TP4：k=3 prose 63.7 tok/s）表明我们 65.5 已达 prose 天花板——-27.7% 主体为 checkpoint draft-head 接受形态，恢复杠杆=flashinfer main（step-time）+k 按负载分档，详见 [G1R7VL-COMMUNITY-RERESURVEY-20260907.md](./G1R7VL-COMMUNITY-RERESURVEY-20260907.md)。
