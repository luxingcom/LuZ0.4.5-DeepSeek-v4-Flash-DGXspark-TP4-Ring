# G1R7-VL 第十轮调查 — 社区视觉版本解决方案复查（2026-09-07）

范围：距上轮四源调查（09-03/04）的增量。两线并行 agent（vLLM 仓库线 + flashinfer/DeepSeek官方/社区线），全部 web 只读 + 本地源码/config 审计，零服务器触碰（符合 09-03 崩溃后的内存纪律）。

生产背景不变：4×DGX Spark GB10 TP4，fork v0.26.1.dev + flashinfer 0.6.18 + TK512 手补丁，vision-exp 权重 k=6，decode 65.5 tok/s（0731 基线 90.6，-27.7%）。

---

## 0. 摘要（先读这个）

1. **头号锚点 flashinfer #4802 已于 09-03 合入 main（merge `453aa7c`）**——SM12x sparse-MLA 缺口（五缺口之二）在 main 上关闭，含 TK=512 vision prefill arms（我们手补丁的正式版）、#4732 SM121 prefill-hang 修复、calibrated-cpb 解析模型、prefill gather L2 warming。GB10 实测：2×GB10 131K 新鲜长上下文 decode +26.2%（42.7→53.9 tok/s），TTFT −3.2%，acceptance 轻微回落（78.4→76.2%）。**不在任何正式 wheel 里**（09-05 发布的 v0.6.18.post1 只含 #4931 ragged-prefill 去 D2H 同步），要吃到必须从 main ≥`453aa7c` 自建或等 0.6.19。
2. **同拓扑社区基准落地（NVIDIA 论坛 voktolom 09-05，4×DGX Spark TP4 + fp8_ds_mla，1M 窗口）**：k=3 下 prose/code/JSON = 63.7/77.6/92.1 tok/s。**我们的 65.5 已达/超同拓扑 prose 天花板**——-27.7% 的主体是 vision-exp checkpoint 自身 Markov draft head 的接受形态（其结论原话："the remaining Vision gap stems from the checkpoint's own Markov draft head"），不是部署缺陷。恢复杠杆转向 step-time/kernel 路径（flashinfer main）与负载结构（block-k 仅利 JSON/code）。
3. **k 加深的预期要下调**：voktolom k=3→k=5 per-position acceptance 87/69/51/40/31%，prose 更深 draft 是净负；社区默认停在 k=3。我们的窗2 k=9 测试保留但重定目标——只对 code/JSON 混合负载有意义，prose 大概率负收益。
4. **两条新 issue 本地核验/挂账**：#55581（spec-decode 头数比不整除静默丢全部 CUDA graph）——**核验不适用**（W2 哨兵 PIECEWISE 16/16 + FULL 11/11 + dspark 捕获全过）；#55636（GB10 DSv4 sparse-MLA warmup 越界，崩溃+静默错 KV slot 双模式）——与我们 W2 boot 记录（0 异常行）不符，列观察项。
5. **HF discussion #10 的 "image rulebook 路由失效" 嫌疑已本地审计排除**：checkpoint 72633 键无任何 rulebook 类张量，唯一视觉路由机制 bias_vl×46（43 目标层+3 MTP）在我们 fork 中加载且**激活**（config `vision_n_layers=32` → `image_sentinel_lo=129257`，embedding 侧与 router 侧同一 ID 范围判断，`fused_topk_bias_router.py:134-138` 对图像行用 `scores+bias_vl` 重选专家）。
6. vLLM 0.29.0 **仍未发布**（截至 09-07 只到 08-26 的 0.28.0）；vision 仍只在 main。#41834 原地踏步（needs-rebase、零批准），但 Hefulalala 09-03 报告**不带 #41834 代码跑 main/SM120 零 eidx 错误**——eidx 缺口可能没有先前评估的那么硬，rebase 前需实测复核。#54631 大改：vision 权重流式加载部分被作者用 TP2 DGX Spark A/B 证伪并移除（09-04），只剩 DSpark `n_predict` 取 `dspark_block_size(5)` 修复。

---

## 1. flashinfer #4802 合入详情（本周最大变化）

- 合入：09-03，merge commit `453aa7c`，branch `sm120-sparse-mla-decode-consolidated`；批准 saltyminty(09-02)/bkryu(09-03)。
- 内容超上轮认知：零 token decode 修复（取代 #4461）、decode kernel 行stride 索引、cpb autotune 换成标定解析模型、prefill gather 的 L2 warming（09-02 commit）、合入 main 时带进 #4732 的 SM121 prefill-hang 修复。
- CI：合并时 27/40 banner / GitLab 15/17，失败两项为 RTX PRO 6000 ECC 硬件抖动（与 09-03 状态一致，非代码问题）。
- 验证：madalin-dogaru（2×GB10 TP2，DSV4-Flash-Vision-Exp，131K 新鲜 prompt）decode +26.2%（42.7→53.9）、TTFT −3.2%、acceptance 78.4→76.2%；Hefulalala 生产 TP4 H=16 用 dual-cache CM arms topk=512 的 backport（即我们 TK512 手补丁等价物）。
- 残留：#4973（09-04 开，未 triage）报告 SM120 长文本 topk-512 路径 IMA——维护者定位为过期分支 `803c466`，修复在 main；issue 本身仍开，**迁 main 后仍需盯**。

**对我们的含义**：TK512 手补丁可在 flashinfer-main 重建后退役；calibrated-cpb + L2 warming 是 49.7→59.5ms step-time 问题的直接候选杠杆；重建需重走我们 baked2 时代的三层 GPU 验证（JIT 编译过/dispatch 过/零 KV→零输出数值对）+ span 原子性 + accept 形态门。

## 2. vLLM 侧增量

| 项 | 状态（09-07） | 增量说明 |
|---|---|---|
| 0.29.0 | **未发布** | releases 页仍止于 0.28.0(08-26)；vision 仍 main-only |
| #41834（eidx/SM12x 大 PR） | open/needs-rebase/零批准 | 无 rebase 无审查进展；**Hefulalala 信号：main 跑 SM120 无 #41834 代码零 eidx 错误** |
| #54631 | open，09-04 重写 | 视觉流式加载部分被 TP2 A/B 证伪移除；剩 DSpark n_predict=5（dspark_block_size）+ 回归测试 |
| #52291（多节点 autotune 死锁） | open，零动态 | workaround 仍是 `VLLM_FLASHINFER_AUTOTUNE_DISTRIBUTED_SYNC=0` |
| #52292（opt-out PR） | open/needs-rebase | **09-06 vbooka1 实地确认：DSV4+DSpark 2×RTX PRO 6000 修好死锁**（0.28.0+FI 0.6.18.post1） |
| #54618（新，08-31 开，活跃至 09-06） | open | **第二种死锁模式：暖 autotune 缓存部分 rank 命中跳过 all-reduce 同步**——我们的 baked 镜像内置暖 autotune 缓存，重启路径正中此雷，挂账 |
| #55636（09-07 新） | open | 2×Spark TP2 DSv4 sparse-MLA CUDA-graph warmup 索引不存在 block-table 行：崩溃+静默错 KV slot 双模式，无 workaround |
| #55405（09-04 新） | open | SM12x NVFP4 kernel 优先级 bug（CuteDSL W4A16 遮蔽 W4A4），GB10 prefill ~-31%；仅 main，我们 FP8 路径不受影响，rebase 清单记账 |
| #55581（09-06 新） | open | spec-decode 头数比不整除→静默丢全部 CUDA graph；**本地核验不适用**（W2 哨兵 16/16+11/11+dspark 捕获全过） |
| #54566 后续 | — | #55107(Rocm 开 vision)、#55042+下游 port；Defilan 09-02 GB10 数字：prefill 2079、decode 25.3（k=3→39.1）；`enable_adaptive_verification` 被 indexer 后端拒绝 |
| #54815（09-02 已合入 main） | merged | RoPE/YaRN 作用于 SWA 层的正确性修复——**可能是 eugr #356 类长上下文乱码的根因**；我们 mmlen 65536+SWA128，backport 候选（span 门 3085tok 已过，30K+ needle 区未验） |

**main 上可 cherry-pick 的已合入 perf/修复 commits**（均在我们的問題空间，小而聚焦）：#55180（SM12.x FP8 权重超 L2 时 CTA raster swizzle，09-07）、#55234（optimized Python 下 DSpark cache-group 能力恢复，09-04）、#55341（CUDA graph 捕获前 kernel warmup，09-04）、#55299（DSv4 prefill sparse index workspace 的 -1 哨兵，09-05）、#54110（低 SMEM GPU persistent top-k 回退，09-05）、#55455（adaptive verification 推迟到 kernel warmup 后，09-06）。

**官方 recipes 页无更新**（止于 09-01）：仍 GB200 NVL4 TP4+EP、fp8 KV、block 256、DSpark k=3；参考 acceptance 2.99 mean/66.3% overall，"image tokens don't hurt acceptance"——我们的 3.9 高于此，佐证瓶颈不在接受侧。

## 3. 同拓扑社区基准与定位校准（voktolom，NVIDIA 论坛 #381911 post #106，09-05）

4×DGX Spark TP4、fp8_ds_mla KV、1M 窗口——与我们完全同拓扑：

| 指标 | k=3 基线 | k=5 | 结论 |
|---|---|---|---|
| tok/s（prose/code/JSON） | 63.7 / 77.6 / 92.1 | — | **我们 65.5 = prose 天花板水平** |
| acceptance（prose/code/JSON） | 0.51 / 0.72 / 0.98 | — | 视觉模型 prose 接受天然低 |
| per-position acceptance | 87/71/56% | 87/69/51/40/31% | 加深 draft 边际递减为负 |
| block-k patch | — | — | JSON +15%/code +3%/**prose −8%** |
| rope-swa-fix（=#54815 backport） | — | — | 速度中性，30K/128K 4/4 needle 正确 |

校准结论：
- **-27.7% 的定性改变**：对照同拓扑社区数据，65.5 不再是"待修复的回归"，而是 vision-exp checkpoint draft-head 接受形态在同硬件的典型值。0731 的 90.6 来自文本 checkpoint 的接受画像（其 JSON 类负载可达 92.1）。**剩余恢复空间 = step-time/kernel（flashinfer main 的 +26% 长上下文 decode 数据点）+ 负载结构（block-k、k 按负载分档）**，而非"修一个 bug"。
- **窗2 k=9 重定目标**：社区数据明确 deeper-k 伤 prose；k=9 仅在 code/JSON 占比的负载上有望净正。测试保留，判读标准改为分负载报告。
- 我们 fork 的 k 合法域（≥5 且 3|k → 6/9/12）与上游 #54631 修的 n_predict=5 语义一致，无需动作。

## 4. 其余新线索

- **flashinfer #4955**（09-04 开，活跃至 09-07）：SM120/121 原生 NVFP4 sparse MLA（E2M1+E4M3、384B/token paged ABI、单发射流式 prefill+split-K decode），decode 1.31×/E2E 1.09×（RTX PRO 5000）；opt-in `kv_cache_format="nvfp4"`。未合（P1 对齐/P2 分配审查中）。**合入后是我们最大单杠杆**，与社区 `nvfp4_ds_mla` KV recipe 呼应（BPAM 2×Spark k=5+Patch4 "wins ~33%"）。
- **flashinfer #4990**（09-06）：SM12x grouped MoE `fused_moe_120` 在多专家下 1 CTA/SM latency-bound——把我们"MoE decode 带宽受限"的判断落成上游记录。
- **#55264**（09-04 开）：SM120 sparse-MLA decode 按捕获桶精修 cpb warmup（dsv4 桶最高 1.07×/1.35× kernel 时间）；未批准，且 CodeRabbit 标注**无 GPDirect RDMA 的多节点 NCCL 启动挂起风险**——我们 TP4 over RoCE 相关，只观察不合入。
- **GLANCE 论文**（arXiv 2609.00355，08-31）：首个"vision 不是开销"的免损失 one-pass 块级 VLM drafter（对目标已融合 VL 状态做块扩散，2.93× vs AR、接受块长 2.7× EAGLE-3）；无 vLLM 集成，长期方向观察项——正中"Markov head 视觉 gap"的学术解法位。
- **DeepSeek 官方**：GitHub org 仅 deepseek-harness(09-04，无关)；HF 模型卡无修订；官方 pinned 镜像 `deepseekv4-flash-vision-arm64-cu130` 自 09-01 未再推（digest `8568b4bbc821`）；无新工程博客。**全无新动作。**
- **eugr/MiaAI**：#356/#358 零动态零上游化；MiaAI 栈仍是 0731 文本+Qwen3-VL sidecar（非原生 vision）；社区新动态=humanrouter GX10 recipe(09-05)/BlivionIaG SGLang vision recipe(09-07)。
- **#4931**（已进 0.6.18.post1）：`trtllm_ragged_attention_deepseek` 每次调用去掉一次 D2H 同步（`skip_all_rows_active_check`，默认关）——TTFT 小杠杆，flashinfer main 重建时顺带获得。

## 5. 五缺口表更新（09-03 版 → 09-07 版）

| # | 缺口 | 09-03 | 09-07 |
|---|---|---|---|
| 1 | SM12x eidx 连续性（#41834） | 未修 | 上游无进展；**但 main 可能已不触发（Hefulalala 信号）→ 从"硬缺口"降为"rebase 前实测复核项"** |
| 2 | flashinfer SM12x vision prefill arms（#4802） | approved 未合 | **main 上关闭（`453aa7c`）；正式 wheel 未含，需 main 自建或等 0.6.19** |
| 3 | 多节点 autotune 死锁（#52291/#52292） | open | 仍 open；#52292 补丁获 DSV4+DSpark 实地验证；**新增第二种暖缓存模式 #54618（正中我们 baked 暖缓存重启路径）** |
| 4 | vision 流式加载修复（#54631） | open | 作者 A/B 证伪并移除该半——**从缺口表除名**；剩余半=n_predict 修复（与我们 fork 无冲突） |
| 5 | eugr #356/#358 上游化 | 未上游 | 仍未上游；**邻近根因候选 #54815 已在 main**（RoPE/YaRN SWA 正确性）——backport 我们 fork 可覆盖 #356 类风险 |
| +6 | （新）#55636 GB10 warmup 越界 | — | open 无 workaround，崩溃+静默错位双模式；观察项，与我们 W2 boot 记录不符 |

## 6. 对现行计划的影响（无窗口，纯记账）

1. **runbook 新增窗4候选"F1：flashinfer main 重建 A/B"**（优先级提到 k=9 之前或并行）：FROM 生产镜像 + 替换 flashinfer JIT 源为 main `453aa7c`；门=三层 GPU 验证（沿 baked2 方法）+ TK512 手补丁退役确认 + span 原子性 + accept 形态 + decode/TTFT A/B。预期来自 +26.2%（2×GB10 长上下文新鲜 prompt）数据点，但我们 k=6/短上下文 regime 需实测。**叠 #54618 风险检查：重启时确认 autotune 分布式同步路径**。
2. **窗2 k=9 判读标准改为分负载**（prose vs code/JSON 分开报告）；若 prose 显著负而 code/JSON 正，k 档位决策交生产负载构成。
3. **E1 不变**（e1b→e1a spec-off Δ≥6ms=权重侧）——voktolom 数据不改变其实验价值：它校准的是"该恢复多少"，E1 定的是"差距在权重侧还是部署侧"。
4. **版本目标微调（不改血统结论）**：锚点 #4802 已落 main → 等价物=flashinfer ≥0.6.19 出轮或 main 自建；rebase 立项门更新为：eidx 在目标 commit 上实测复核（可能免费）+ #54631 剩余 + #52292/#54618 至少其一合入。0.29.0 仍未发布，"白等"结论维持。
5. **#54815 backport 评估**加入低优先队列（正确性项，非 perf；触发条件=生产出现长上下文(>30K)质量报告时提前）。
6. 生产零变更：baked5/脚本/权重均不动。

## 7. 追踪清单 v2（周更）

- flashinfer：0.6.19 出轮（含 #4802 与否）；#4955（NVFP4 KV）合入；#4973 triage；#55264；#4990；#4749/#4993
- vLLM：0.29.0 发布确认（预期仍无 vision）；#41834 或拆片（#53425/#53521/#53522）动态；#54631 合入；#52292/#54618；#55636；#55405；#55180 等 cherry-pick 候选落地评估（待 F1 窗）
- 官方/社区：pinned 镜像重推；recipes 页更新；HF discussion #10 后续（k=5/Patch4 数字复验）；GLANCE 类工作 vLLM 集成信号
- 我们侧待办：F1 窗（flashinfer main A/B）排期；k=9 分负载判读标准同步进 SMALLSCALE 报告；#54815 backport 触发条件记录

## 8. 来源

vLLM: #54566/#41834/#54631/#52291/#52292/#54618/#52451/#55636/#55405/#55581/#55459/#54815/#55180/#55234/#55341/#55299/#54110/#55455/#55264；releases 页；recipes.vllm.ai（deepseek-ai/DeepSeek-V4-Flash-Vision-Exp）
flashinfer: #4802(`453aa7c`)/#4850/#4931/#4973/#4955/#4993/#4990/#4749；releases（v0.6.18.post1, 09-05, `8bc3b57`）
社区: NVIDIA forums #381911 post#106（voktolom 09-05）/ #370309 / #374742；HF deepseek-ai/DeepSeek-V4-Flash-Vision-Exp discussion #10（BPAM/alaistair）；eugr/spark-vllm-docker #356/#358；MiaAI-Lab repo；arXiv 2609.00355（GLANCE）
本地审计: work/vllm 源码树（mm_preprocess.py/vl_model.py/model.py:570-571/fused_topk_bias_router.py:134-138/dsv4_topk.py:126）；Vision-Exp config.json（vision_n_layers=32）；model.safetensors.index.json（72633 键，rulebook 类=0，bias_vl×46）；W2 报告 boot 哨兵
