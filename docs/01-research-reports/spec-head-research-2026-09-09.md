# DSpark MTP 投机解码头社区/官方资料调研报告

日期：2026-09-09 ｜ 调研人：vl-spec-research ｜ 性质：纯网络调研（只读，未触碰任何服务器）
背景问题：VL 版 dspark 接受率 0.572 vs 旧文本版 k=7 的 0.652（相对 -12.2%），深位衰减快（第 5 位 0.23 vs 0.47），退化集中在 coding/JSON；怀疑视觉版训练稀释了 draft 头对代码/JSON 分布的拟合。
引擎：自研 fork vLLM 0.26.1.dev0+gd3d3b2cca（0.28 体系），DSpark MTP k=6 probabilistic，flashinfer_b12x，TP4 GB10（SM121）。

标注约定：**[官方实锤]** = DeepSeek/vLLM 官方仓库、模型卡或已合并 PR；**[社区实测]** = 论坛/博客复现数据；**[社区传闻]** = 未经复现的转述。

---

## 0. TL;DR

1. **没有任何针对 VL 的第三方 draft 头权重**（官方或社区均未找到）。官方 DeepSeek-V4-Flash-Vision-Exp（2026-09-01 发布，MIT）内嵌 DSpark 头，未发现修订版或社区微调版 VL 头。
2. **换头不是主路，k 截短有直接证据**：同硬件（4×DGX Spark TP=4）社区实测 k 6→3 净赚（深位接受率 5.4%/1.7%）；vLLM 已合并 DSpark 专用自适应验证 PR #47808（v0.27.2rc0），但 **SM100-only 限制未证实覆盖 GB10/SM121**。
3. **VL 退化存在三个已知"工程根因"候选**，先排查再归因训练稀释：vLLM issue #51009（0.26.1rc1 DSpark 接受率 position 0 后塌陷）、PR #49133（draft 继承 target 量化配置）、FlyCockpit 教训（VL 包装层挡住 draft 依赖的辅助隐状态流，接受率 1-15%→透传修复后 50-64%）。
4. **重校准 draft 头可行且有官方工具链**：NeMo Automodel 有 deepseek_v4_flash DSpark draft 训练 recipe（含 target 再生成工具）；DeepSpec（官方）支持 DSpark 训练但官方目标仅 Qwen3/Gemma，适配 V4-VL 成本高（target cache TB 级~更大）。

---

## 1. 候选清单表

### A. 现成投机头权重文件（调研问题 1）

| 名称 | 来源 | 是什么 | 预期收益证据 | fork 0.28+TP4 集成风险 | 推荐度 |
|---|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4-Flash-Vision-Exp 内嵌 DSpark 头 | huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp | **[官方实锤]** VL 官方权重自带 draft 头：dspark_target_layer_ids=[40,41,42]、dspark_block_size=5、num_nextn_predict_layers=3、markov_rank=256 | DSpark 论文（arXiv 2607.051472）：线上 vs MTP-1 +60~85% 单用户提速 | 我们已在用同源权重；未发现 revision 更新或修订 checkpoint。核对一次 HEAD hash 即可 | 基准（无替代品） |
| ycui7/DeepSeek-V4-Flash-MTP | huggingface.co/ycui7/DeepSeek-V4-Flash-MTP | **[社区实测]** 从 0731 checkpoint 抽出的独立 MTP 头（单层，1575 tensors），供 `method=deepseek_mtp` 用，k≤2 | 仅为无 DSpark 支持引擎的替代；接受率/收益无独立数据 | 非 DSpark 路线，且基于 0731 文本版而非 VL；等于降级到 k=2 MTP | 低 |
| canada-quant / LordNeel / Rarri 等 MTP 量化修复版 | 见报告 §4 链接 | **[社区实测]** 解决 transformers 静默丢弃 mtp.* 的量化修复 checkpoint（MTP 头保持 BF16） | Rarri NVFP4：DSpark 接受 49.4%（官方 50.8% 基线），bf16 头 accept_len 4.09 vs FP8 头 3.51 | 均为文本 0731 底座，无 VL、无 SM121 验证；但"**draft 头保持 BF16**"结论对我们适用 | 低（借结论不借权重） |
| AQ-MedAI/DeepSeek-V4-Flash-0731-eagle3 | huggingface.co/AQ-MedAI/DeepSeek-V4-Flash-0731-eagle3 | **[社区传闻→有初步数据]** 社区训练的 EAGLE3 头（0.7B，0.5M 样本 open-perfectblend+中文，自述 preliminary） | HumanEval accept_len 3.16、Math500 3.20（vs 自家 DSpark 口径未对齐） | **SGLang 专用**（sglang 0.5.16+PR #33344）；vLLM 不可用；文本 0731 目标，不覆盖 VL | 低-中 |

### B. 社区优化版投机头 / 训练校准工具链（调研问题 2）

| 名称 | 来源 | 是什么 | 预期收益证据 | 集成风险 | 推荐度 |
|---|---|---|---|---|---|
| NVIDIA NeMo Automodel DSpark recipes | github.com/NVIDIA-NeMo/Automodel → examples/speculative | **[官方实锤]** 含 `deepseek_v4_flash_dspark_precompute.yaml`（precompute_dspark_dist 缓存 target 输出训 draft）与 `components/speculative/regenerate.py`（用 target 模型重生成 assistant 答案，对齐分布） | EAGLE/DSpark 训练通用方法论：**draft 必须拟合 target 自身分布**，off-distribution 数据直接拉低接受率 | 需自备 code/JSON 语料 + VL target 服务做再生成；DSv4 draft 训练在 GB10 外硬件做（Spark 128G 不够训） | **中高**（唯一明确支持 DSv4 draft 训练的现成 recipe） |
| deepseek-ai/DeepSpec | github.com/deepseek-ai/DeepSpec | **[官方实锤]** DeepSeek 官方 draft 训练全栈（DSpark/DFlash/EAGLE3；数据准备→训练→9 benchmark 评估，含 HumanEval/MBPP/LiveCodeBench） | README 明言："domain-specific 用途应重训 draft，尤其 target 跑 thinking 模式时"；官方 Qwen3/Gemma 12 个 checkpoint 矩阵 | **官方 target 仅 Qwen3/Gemma，无 DeepSeek V4**；适配 V4-VL 需自改 config + target cache 成本巨大（Qwen3-4B 默认即 38TB） | 中（方法论权威，落地成本高） |
| Baseten EAGLE-3 训练指南 | baseten.co/blog/how-to-train-custom-eagle-3-heads | **[社区实测方法论]** task-specific 头 ~100k 样本即可；"用 target 重生成输出"是 golden rule；T=1 比 T=0 损失 15-25% 提速 | 1.5-2.5× 生产实测（Qwen3-4B） | 方法论参考，无现成产物 | 中（方法论） |
| FlyCockpit/DeepSeek-V4-Vision-2x-DGX-Sparks | github.com/FlyCockpit/DeepSeek-V4-Vision-2x-DGX-Sparks | **[社区实测]** VL 包装模型 vLLM 插件；曾因包装层挡住 draft 依赖的辅助隐状态流致 DSpark 接受率 1-15%，透传修复后恢复 50-64% | 与我们症状同构（VL 链路伤接受率）的已修案例 | 非我们要集成的对象，是**根因排查模板** | 中（诊断价值） |

### C. k 值动态/静态截短（调研问题 3）

| 名称 | 来源 | 是什么 | 预期收益证据 | 集成风险 | 推荐度 |
|---|---|---|---|---|---|
| 静态截短 k=6→4（或 3）+ 按任务路由 | 零代码，改 speculative-config | 改 `num_speculative_tokens` 即可；`rejection_sample_method: block` 等配置键 vLLM 主线已存在 | **[社区实测]** voktolom 4×DGX Spark TP=4（forum 381911/44）：深位 4-5 接受率 5.4%/1.7%，k=3 净赢（step 便宜 ~10%）；forum 381911/87：block-k k=4 使 JSON +15%、code +3%、prose -8%；deepwiki runbook：0731 checkpoint k 实际锁 5（>5 拒启/崩溃） | 极低；prose 损失需接受或按任务分路由（我们 prose 本就持平/负收益） | **高（第一步就做）** |
| vLLM PR #47808 `enable_adaptive_verification` | github.com/vllm-project/vllm/pull/47808（已并入 main，v0.27.2rc0，2026-08-12；博客 vllm.ai/blog/2026-08-14-dspark-adaptive-verification） | **[官方实锤]** DSpark confidence head 按步决定验证多少草稿 token（top-B 全局调度），单配置覆盖并发 1-256 Pareto 前沿 | 官方 8×B300 TP=8 实测：k=7 块内第 1 位 >70%、第 7 位 <10%，自适应全程贴 Pareto 前沿 | **SM100 专用 FULL varlen graph**；非 SM100 两说：回退 PIECEWISE（alphasignal）或启动直接拒绝（PR 正文中文版）；无 eager/LoRA/PP/logprobs；要求 k ≥ dspark_block_size(5)。GB10/SM121 未经官方验证 | **高（中期首选，需先验证 SM121 可跑）** |
| vLLM PR #26504 `eagle_dynamic` DynamicProposer | github.com/vllm-project/vllm/pull/26504 | **[社区]** open/未合并 PR：按请求监控历史接受率动态调 k（`--acceptance-rate-threshold 0.3`），EAGLE 实现 | PR 内 E2E 日志显示 k 随请求质量自适应升降 | 未合并需 cherry-pick；仅 EAGLE 实现，移植到 DSpark proposer 要自写 | 中 |
| vLLM PR #44336 `enable_adaptive_k` | www.github.gg/vllm-project/vllm/pulls/44336 | **[社区]** open PR：per-position EMA 接受率 + goodput 成本模型选 K；防振荡（10 步 EMA、冷却、迟滞） | RTX 4050 实测与最优固定 K 持平（75.9 vs 75.2 tok/s），正确惩罚过度投机 | 未合并；draft_model 路线验证，DSpark 需适配 | 中 |
| llama.cpp `--spec-draft-conf-min P` | rohitraj.tech/notes/deepseek-dspark-speculative-decoding-llamacpp-2026 | **[社区实测]** 已落地的"按置信度截断草稿块"先例：首个预测接受率 <P 的位置处截断 | llama.cpp PR 实测口径：accept_rate×block_size 才是真收益（MTP 2×0.65=1.30 vs DSpark 5×0.46=2.32） | 非 vLLM；但证明算法可行，可作为我们自研 per-position 截短的参照 | 中（参照系） |

### D. fork 兼容性已知 issue/PR（调研问题 4）

| 编号 | 来源 | 内容 | 与我们的相关性 |
|---|---|---|---|
| vLLM issue #50720（open） | theainews.cc/articles/2026-08-11-deepseek-v4-flash-rtx-pro6000/ | **[社区实测]** SM120/SM121 上 0.26.0/0.26.1rc1/main 硬开 DSpark 启动/预热崩溃；根因 FlashInfer SM120 稀疏 MLA 解码 kernel 只实例化 topk∈{128,512,1024}，`dspark_markov_rank=256` 命中不了分发表 | **我们 fork 正是 0.26.1 体系 + GB10(SM121)**。FlashInfer 修复 PR #4380（补 top-k 192/256）2026-08-08 合并、v0.6.16.post4 首发；vLLM v0.27.0 仍钉 0.6.16.post3（#50892）→ 官方 wheel 不含修复，需手动升 flashinfer |
| vLLM issue #51009 | 同上转述 | **[社区实测]** 0.26.1rc1 上 DSpark 接受率在 position 0 之后塌陷 | **与我们的深位衰减症状相似度极高，必须先核对是否同一根因**——若是，则"训练稀释"假设不成立 |
| vLLM PR #49133 | forums.developer.nvidia.com/t/deepseek-v4-flash-0731-dspark-1m-nvfp4-kv-2x-dgx-spark/378824 | **[社区实测]** DSpark draft 的 model_config 会继承 target 的量化配置（NVFP4/MXFP4 混淆），draft 专家走错 kernel → 接受率崩到每位置 0.44%-3.2% | fork 若未含此修复，VL+量化组合下 draft 路径可能同样被污染；论坛帖给出 draft-only 量化元数据归一化 patch 与 fail-closed 守卫代码 |
| vLLM PR #48304 / #51538 / #51593 / #51254 | 同上 | #48304 MTP 层 compress_ratio（DSpark 必需，未合并）；#51538 DSV4 稀疏 MLA 三模式端到端（未合并）；#51593 MTP 批量排空后挂起；#51254 SWA 索引宽度绕过补丁（已关闭被 #4380 取代） | cherry-pick 清单候选；#48304 标注为 DSpark 正确运行必需 |
| luxingcom/LuZ0.4.5 fork 文档 | github.com/luxingcom/LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring/blob/master/docs/03-final-metrics/FINAL-METRICS-2026-09-02.md | **[社区实测]** 4 节点 TP4 方案的最终指标矩阵（coding C1 102 t/s、json 106、prose 49 等，2026-09-02） | fork 本体只有指标文档，**未检索到该 fork 内关于 draft 头替换或接受率退化的 issue/讨论**（见 §3 空白） |

### E. 投机采样配置经验（调研问题 5）

| 主题 | 证据 | 要点 |
|---|---|---|
| greedy vs probabilistic draft 采样 | **[社区实测]** Rarri/DeepSeek-V4-Flash-0731-NVFP4 模型卡（2026-08-03 更新）：probabilistic 经 NVFP4 路径会"garble output"，greedy 在目标 T=0/0.7/1.0 全部干净；官方 vLLM recipe（aiwiki 转述 + PR #47808 复现命令）用 `"draft_sample_method":"probabilistic"` 的同时 #47808 官方博客亦有用例 | 注意矛盾点：官方 PR #47808 用 probabilistic，Rarri 与 llama.cpp 教程推荐 greedy。**greedy 草稿非严格无损**（改变草稿分布），Rarri 称实测干净但需自测。我们现配 k=6 probabilistic——A/B greedy 值得一试，但必须评估输出分布偏移 |
| draft 头精度 | **[社区实测]** Rarri：bf16 draft 头 accept_len 4.09 vs FP8 draft 头 3.51（-14%） | 排查我们 draft 头是否被量化路径降精度（关联 #49133） |
| target 温度 | **[社区实测]** Baseten：T=1 vs T=0 提速损失 15-25%，属正常衰减非 bug | 对齐预期，不作为退化解释 |
| thinking 模式 | **[社区实测]** classmethod（dev.classmethod.jp/en/articles/dgx-spark-2node-deepseek-v4-flash-dspark/）：thinking ON→OFF，per-token 接受率 24.2%→40.4%；DSpark 论文 §1：math/code 天然高接受，reasoning trace 难草拟 | 若生产混合 thinking 流量，会结构性压低整体接受率——需按 thinking 切分我们的 0.572 复核口径 |

---

## 2. 建议行动（按优先级）

1. **立即（零代码，1 天级）**：静态 k 截短 6→4 起步（甚至 3），观测 tok/step 与分任务吞吐。证据最硬：同硬件社区实测 + vLLM 官方 DSpark checkpoint 的 block_size 本就为 5。code/JSON 与 prose 可按网关路由到不同 k 的双实例（381911/87 的 block-k 数据支持：JSON +15%、prose -8%）。
2. **立即（根因排查，先于"训练稀释"结论）**：逐一核对三个已知工程坑——(a) issue #51009 的 position-0-后塌陷是否复现于我们 fork；(b) draft 量化路径是否继承 target 量化配置（#49133 模式）+ draft 头是否 bf16；(c) VL 视觉包装层是否透传 draft 所需辅助隐状态（FlyCockpit 案例）。任一命中则"换头/重训"假设作废。
3. **中期（1-2 周）**：在四机上验证 PR #47808 `enable_adaptive_verification` 于 SM121 的可用性（PIECEWISE 回退是否可跑、性能剩几成）；若被启动拒绝，参照 #26504/#44336 自研 per-position 置信截短（llama.cpp `--spec-draft-conf-min` 为先例），阈值可用我们的 p4/p5 数据（<0.35/0.25）。
4. **备选（重校准 draft 头，若根因确属训练稀释）**：用 NeMo Automodel 的 DSv4 DSpark recipe + regenerate.py，以 code/JSON 为主的重生成语料微调 VL draft 头（~100k 样本量级，参照 Baseten 方法论）；DeepSpec 适配 V4-VL 成本更高，不推荐首选。注意 GB10 上训练不可行，需外部硬件。
5. **同步小动作**：A/B `draft_sample_method: greedy`（注意非严格无损，需质量门）；升级 flashinfer wheel 至 ≥0.6.16.post4（#4380 修复，vLLM 官方发布未含）。

---

## 3. 「没有找到」清单（检索空白，同样是结论）

检索时间：2026-09-08/09；工具：WebSearch（多轮）+ 交叉引用。以下均**未检索到**：

- **VL/Vision 版 draft 头的任何第三方权重**：HF 搜索 "DeepSeek-V4-Flash-Vision MTP/draft/eagle" 仅命中官方 Vision-Exp 与文本版头的迁移物（ycui7、mlx-community、canada-quant、LordNeel、Rarri），无一针对 VL 底座，无一针对代码/JSON 分布校准。
- **官方对 Vision-Exp checkpoint 的修订/更新 draft 头**：Vision-Exp 2026-09-01 单次发布，未发现 revision 记录或官方公告修订 draft 头。
- **luxingcom/LuZ0.4.5 fork 内**关于 dspark 接受率退化、draft 头替换的 issue/PR/讨论（该仓库可见内容以指标文档为主）。
- **DeepSpec/NeMo 对 DeepSeek V4-VL 目标的官方支持声明**：DeepSpec 官方 target 仅 Qwen3/Gemma；NeMo 有 DSv4-Flash（文本）recipe，未见 VL 变体。
- **vLLM 主线对 DSpark 动态 k 的已合并实现**（#47808 是动态"验证预算"而非动态"起草步数"；#26504/#44336 均未合并）。
- **AQ-MedAI EAGLE3 头在 vLLM 上的任何适配**（仅 SGLang）。
- Reddit r/LocalLLaMA 专项帖：未检索到 VL 版接受率退化的独立报告（检索关键词：DeepSeek V4 vision speculative acceptance、DSpark VL degeneration）。

---

## 4. 主要来源 URL 备查

- 官方 VL 权重与配置：huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp（2026-09-01，MIT；配置转述见 explainx.ai/blog/deepseek-v4-flash-vision-305b-open-model-2026 与 aiwiki.ai/wiki/deepseek_v4_flash）
- DSpark 论文/DeepSpec：github.com/deepseek-ai/DeepSpec（DSpark_paper.pdf，arXiv 2607.051472；发布 2026-06-27）
- PR #47808：github.com/vllm-project/vllm/pull/47808（并入 v0.27.2rc0，2026-08-12；官方博客 vllm.ai/blog/2026-08-14-dspark-adaptive-verification）
- 动态 k：PR #26504、PR #44336（均 open）；llama.cpp conf-min：rohitraj.tech/notes/deepseek-dspark-speculative-decoding-llamacpp-2026
- SM121/FlashInfer 链：theainews.cc/articles/2026-08-11-deepseek-v4-flash-rtx-pro6000/（issue #50720、#51009、PR #4380/#48304/#51538/#51593/#50892）
- draft 量化继承：forums.developer.nvidia.com/t/deepseek-v4-flash-0731-dspark-1m-nvfp4-kv-2x-dgx-spark/378824（PR #49133 模式 + patch 代码）
- 4×Spark TP=4 k 截短实测：forums.developer.nvidia.com/t/deepseek-v4-flash-vision-exp-is-released-as-open-weights/381911/44 与 /87（block-k 数据）
- VL 包装层伤接受率案例：github.com/FlyCockpit/DeepSeek-V4-Vision-2x-DGX-Sparks（NeuralTalk 转述 + forum /379212）
- NeMo Automodel DSpark recipes：github.com/NVIDIA-NeMo/Automodel examples/speculative（precompute_dspark_dist、regenerate.py）
- EAGLE3 社区头：huggingface.co/AQ-MedAI/DeepSeek-V4-Flash-0731-eagle3
- 采样/头精度经验：huggingface.co/Rarri/DeepSeek-V4-Flash-0731-NVFP4（2026-08-03）；baseten.co EAGLE3 指南；dev.classmethod.jp/en/articles/dgx-spark-2node-deepseek-v4-flash-dspark/
- fork 指标：github.com/luxingcom/LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring docs/03-final-metrics/FINAL-METRICS-2026-09-02.md

---

## 5. 工程根因核验（2026-09-09 追加，代码级，只读）

### 5.0 核验材料口径（先读，决定证据边界）

- **luxingcom/LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring 不是 vLLM 源码 fork**：GitHub API `fork:false`，全仓仅 259KB（运维归档：文档 + 补丁生成器 + 启动/bench 脚本）；commit `d3d3b2cca` **不在该仓库**（API 422 "No commit found"）。引擎源码只存在于 registry 镜像内（LuZ0.4.5-baked / **-VL（<BAKE_IMAGE_DIGEST>, 35.7GB）**），且归档自查记载"**-VL 镜像内容未知、未核验**"（checkpoint-luz045-autotune-baked-2026-09-02.md）。
- 因此"fork 代码级核验"的实际边界 = ①归档内补丁生成器（内嵌全部 old/new 锚点串，可信度高）②上游 vLLM issue/PR API 原文 ③HF checkpoint config.json。**镜像内部状态只能给服务器侧验证清单，无法从 GitHub 确认——下述各项均诚实标注证据等级。**
- 归档基线为 **0731 文本版**（`--served-model-name deepseek-v4-flash-0731`，`--speculative-config '{"method":"dspark","num_speculative_tokens":7,"draft_sample_method":"probabilistic"}'`，start_tp4_head_v043.sh v044-r1）；VL 生产（k=6）的启动脚本不在归档中。
- 引擎基座确证（CHANGES-2026-09-02）：`vLLM 0.26.1.dev0+gd3d3b2cca（fork 基座，FlashInfer 0.6.18 + B12X MXFP4）`，`TORCH_CUDA_ARCH_LIST=12.1a`（w6_env.txt）。

### 5.1 核验项 1：#51009 —— 结论：**非 bug，无修复可包含（更正前报告）**［证据等级：issue 原文实锤］

- vllm-project/vllm issue **#51009**《DSpark acceptance collapses after position 0 on DeepSeek-V4-Flash-0731 (0.26.1rc1)》：**closed（2026-08-11，completed），没有修复 PR/commit**。维护者 benchislett（DSpark 作者）定性为 **benchmark 伪影**："you're sending random tokens to benchmark. 'Random tokens' dataset is going to break specdec."（issuecomment-5208238257，2026-08-06）。
- 关键佐证（hassellof，issuecomment-5209077385）：随机 prompt 上 DSpark 接受 4.4-4.7/5（位置 0 退化性地可预测），真实 prose ~2.1、真实 agentic 3.4-4.0——"位置 0 之后塌陷"恰是随机 token 负载的伪影特征，非 kernel regression。
- **对 fork 的适用性：不适用（不存在需要包含的修复）**。前报告 §D 将其引为"0.26.1rc1 接受率塌陷 bug（open）"系转述自 theainews 的不准确表述，**予以更正**。
- ⚠️ **但引出对我栈 bench 口径的实质疑点**：我们的 bench_v2.py（DE 模式）prompt = **512 token 随机十六进制 filler + 末尾真实任务模板**（`SeededPromptStream.next_prompt()`：`filler + "\n\n[任务]" + TASK_TEMPLATES[task]`），PR 模式 = 纯随机 token。这与 #51009 的伪影触发条件（随机输入主体）**部分同构**。我们测得的 0.572/0.652 与 p4/p5 深位衰减，可能被随机 filler 部分放大/扭曲。**建议：加测一臂纯真实 workload（MT-Bench 类或真实代码会话）做 per-pos 交叉校准，再决定"训练稀释"假设的置信度。**

### 5.2 核验项 2：#49133 模式 —— 结论：**高风险命中候选**［证据等级：PR API 实锤 + 归档补丁面证伪］

- PR **#49133**《DSpark: build draft under its own model/quant config (NVFP4 target corrupts MXFP4 draft experts)》（h-guo18，2026-07-20 开）：**state=closed 且 merged=false——上游未合并**（PR API：`"merged":false,"merged_at":null`）。即主线 0.27/0.28 均不含该修复，任何 fork 只能靠手工移植获得。
- 根因两层（PR 原文）：①`SpeculativeConfig.hf_config_override` 先把 draft model_type 改写导致 `DeepseekV4FP8Config.override_quantization_method` 不匹配，draft `quantization` 冻结在 "fp8"；②`load_dspark_model` 在 target 的 vllm_config 下构建 draft，复用 target 的 quant_config 实例 → FP4/NVFP4 target 下 draft 的 MXFP4 专家被建成 `ModelOptNvFp4FusedMoE`，**ue8m0 scales 形状恰好兼容、静默加载成功、算出垃圾**。Flash target AL 3.554→2.572（-28%），Pro 崩至 AL=1.0。
- **归档补丁面证伪**：V5b 五补丁（A1 model.py SKIP_MTP_COPY / A2 rope.py / A3 cache_utils.py / B1 qwen3_dspark.py+dspark.py Markov replicate / B2 dspark.py topk hook）+ autotune cache + tool-call-encoding——**无任何 draft 量化归一化内容**。归档可见范围内无修复；-VL 镜像未知。
- **我们形态的命中面**：Vision-Exp config.json 实证（HF raw，2026-09-09 抓取）：`expert_dtype:"fp4"` + `quantization_config:{fp8,e4m3,ue8m0,128×128}` 的混合量化 checkpoint，draft 层 mtp.0-2 内嵌——与 #49133 触发形态（hybrid 量化 + dspark model-type rewrite；NVIDIA forum 378824 同形态实测接受率崩至每位置 0.44-3.2%）**同构**。
- **诊断指纹（#49133 原文）**：FP8 target 时 draft 构建日志打印 `Using 'FLASHINFER_TRTLLM_MXFP4_MXFP8' Mxfp4 MoE backend`；FP4/NVFP4 target 时该行**消失**。→ 服务器侧一条 grep 即可初判（见 §5.6-1/2）。
- 注意：我们 VL 退化幅度 -12%（0.572 vs 0.652），远轻于 PR 中的 AL=1.0 崩溃——若命中，可能是错配程度较轻的变体（部分层/混合专家子集），**不能因幅度轻而排除**；反之若 grep 命中指纹正常，则该假设降权，注意力转向 5.1 口径问题与训练稀释。

### 5.3 核验项 3：FlyCockpit 模式 —— 结论：**无法从 GitHub 确认**（-VL 镜像内无 wrapper 源码暴露）［证据等级：归档负面证据］

- 归档全树（API tree 逐文件核对）**无任何 vision wrapper / multimodal 包装源码或补丁**；-VL 镜像由修复团队独立部署，归档明确未覆盖。
- 参照判据（FlyCockpit 已修案例）：包装类若不透传 `**kwargs`、不暴露 `lm_head`、不转发 draft 依赖的辅助隐状态流 → DSpark 接受率 1-15%；透传后恢复 50-64%。官方路线（vLLM PR #54566 / pinned image）无独立 wrapper，理论上不受此影响——但 fork 实际用哪条路线只能服务器确认。
- 服务器侧判据见 §5.6-4/5。

### 5.4 附带项 4：thinking 口径核查 —— 结论：**bench 未控制 thinking，口径疑点成立**［证据等级：bench_v2.py raw 实锤］

- bench_v2.py（45KB raw 核验）请求体**仅含** `model/messages/max_tokens/temperature/stream/stream_options/ignore_eos`，`TEMPERATURE=0.6`——**无 thinking / reasoning_effort / chat_template_kwargs 任何字段**。thinking 状态完全取决于 chat template 默认值。
- 引擎侧已配 `--reasoning-parser deepseek_v4`（思考内容会分离进 `reasoning_content` 字段）；工具链 `--tool-call-parser deepseek_v4` 在位。
- classmethod 口径（0731 实测）：thinking ON→OFF 使 per-token 接受率 **24.2%→40.4%**（+67%）；VL 请求需显式 `chat_template_kwargs:{"thinking":false}`，否则答案落进未闭合 think 块。
- **风险**：若 VL chat template 默认 thinking 状态与 0731 不同，则 0.572 vs 0.652 的对比被口径污染。这是当前成本最低、优先级最高的排查项（§5.6-6）。
- 附：G1r6 曾有 "B1（bf16 draft logits）" 实验，GSM8K 0.9318<0.9356 门 → 默认关闭（CHANGES-2026-09-02）——服务器侧顺带确认现役 draft logits 精度状态（Rarri 数据：bf16 头 4.09 vs FP8 头 3.51 accept length）。

### 5.5 附带项 5：k 截短实施门槛 —— 结论：**纯配置零代码，一处改动点**［证据等级：启动脚本 raw 实锤 + config 实锤］

- 改动点：`start_tp4_head_v043.sh`（v044-r1）serve 命令行 `--speculative-config '{"method":"dspark","num_speculative_tokens":7,"draft_sample_method":"probabilistic"}'`；worker 脚本（start_tp4_worker_v043.sh）同步；env 层（w6_env.txt）无 spec 相关项，不涉及。**VL 生产对应脚本不在归档，服务器上按同名字符串定位即可。**
- block_size 差异：**Vision-Exp `dspark_block_size=5`**（HF config.json 实证；另 `num_nextn_predict_layers=3`、`dspark_markov_rank=256`、`dspark_target_layer_ids=[40,41,42]`）——与 0731 系（5）相同，**截短基准点无差异**。k=6≥5 合法；k=4 低于 block_size，#47808 惯例要求 k≥block_size，但社区同 checkpoint 实测 k=3 可运行且净赢（voktolom，4×Spark TP=4，Vision-Exp，forum 381911/44）→ k=4 大概率可行，staging 一验即可。
- cudagraph 容量：现配 `--max-cudagraph-capture-size 96` = max-num-seqs 12 × (k7+1)；k=4 需 12×5=60 ≤ 96，**容量无忧**；十六档 capture sizes 已覆盖。
- 红线不冲突：`--max-num-batched-tokens 4096`（红线勿动）与 k 无耦合。

### 5.6 服务器侧验证清单（交 SSH 成员执行；全部只读，按优先级排序）

```bash
# 1.【#49133 指纹·一条定生死】draft 构建日志的 Mxfp4 backend 行：
#    出现 → 大概率未命中 #49133；缺失 → 命中候选，进第 2 步
docker logs $(docker ps --format '{{.Names}}' | grep tp4-rank | head -1) 2>&1 \
  | grep -i "Mxfp4 MoE backend\|MXFP4_MXFP8\|ModelOptNvFp4"

# 2.【#49133 代码面】fork 是否已自带两半修复：
#    utils.py 若用 target vllm_config 构建 draft（无独立 get_quantization_config）→ 命中
docker exec <vl-container> sh -c "grep -n 'hf_config_override\|deepseek_v4_fp8' \
  /usr/local/lib/python3*/dist-packages/vllm/config/speculative.py | head -20; \
  grep -n 'get_quantization_config\|draft_model_config\|vllm_config' \
  /usr/local/lib/python3*/dist-packages/vllm/v1/worker/gpu/spec_decode/dspark/utils.py | head -20"

# 3.【draft 专家 quant method 直证】
docker exec <vl-container> sh -c "grep -rn 'routed_experts\|quant_method' /var/log/vllm/*.log | grep -i 'draft\|dspark\|mtp' | head"

# 4.【FlyCockpit 模式·wrapper 存在性】
docker exec <vl-container> sh -c "grep -rln 'VisionForCausalLM\|VisionModel' \
  /usr/local/lib/python3*/dist-packages/vllm/model_executor/models/ --include=*.py | head; \
  grep -n 'architectures\|DeepseekV4' /models/config.json | head -5"

# 5.【FlyCockpit 模式·透传判据】（若第 4 步发现包装类 <WrapperFile>）
docker exec <vl-container> sh -c "grep -n 'def forward\|\\*\\*kwargs\|lm_head\|hidden_state' \
  <WrapperFile> | head -30"

# 6.【thinking 口径·三连】
#  6a. 模板默认值：
docker exec <vl-container> sh -c "grep -o 'thinking[^,}]*' /models/tokenizer_config.json | head -5"
#  6b. 探针对照：同 prompt 发两次 /v1/chat/completions，一次带
#      "chat_template_kwargs": {"thinking": false}；前后各取 /metrics 快照，
#      对比 vllm:spec_decode_num_accepted_tokens_per_pos_total{position=0..k} 差分
curl -s http://127.0.0.1:8002/metrics | grep spec_decode_num_accepted_tokens_per_pos
#  6c. 现网 bench 产物抽查 reasoning_content 是否非空（决定 0.572 口径归属）
# 7.【bench 口径交叉校准】跑一臂纯真实 workload（MT-Bench 80 题）取 per-pos 接受率，
#    与 DE 随机 filler 臂对比——衰减形态差异即 bench 伪影贡献度
# 8.【draft logits 精度现状】确认 G1r6 "bf16 draft logits" 实验现役为默认关
docker exec <vl-container> sh -c "grep -rn 'bf16\|bfloat16' \
  /usr/local/lib/python3*/dist-packages/vllm/v1/worker/gpu/spec_decode/dspark/*.py | head"
```

### 5.7 更正记录（对前版报告）

| 原表述 | 更正为 | 依据 |
|---|---|---|
| §D "issue #51009（open）：0.26.1rc1 接受率 position 0 后塌陷" | **closed 无修复，定性 benchmark 伪影（random-token）** | issue #51009 评论原文（issuecomment-5208238257/5209077385） |
| §D "#51009 与我们深位衰减症状相似度极高，必须先核对" | 改判：**我们 bench 的随机 filler 输入与伪影条件部分同构**，需真实负载交叉校准后再归因 | 同上 + bench_v2.py 代码核验 |
| "fork 0.26.1rc1 体系" | 精确为 **0.26.1.dev0+gd3d3b2cca fork 基座（FlashInfer 0.6.18 + B12X MXFP4）**；FlashInfer topk=192 缺口已被 0.6.18 覆盖（start 脚本"已修复雷点②"） | CHANGES-2026-09-02 + start_tp4_head_v043.sh |
| —（新增） | luxingcom 仓库为运维归档非源码 fork，d3d3b2cca 不在其中；-VL 镜像内容归档未覆盖 | GitHub API repo/commit/tree 原文 |
| —（新增） | 归档 w6_env.txt 发布版未见 CHANGES-09-07 所述 `VLLM_DSPARK_MARKOV_REPL=0` 护栏行，疑发布副本与服务器版不同步（服务器侧顺带核对） | w6_env.txt raw vs CHANGES-2026-09-07 |

（报告完）
