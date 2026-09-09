# G1R7-VL 视觉切换性能损失调查报告（非开窗只读调查）

日期：2026-09-02 ｜ 调查人：ZCode ｜ 性质：**纯只读**（零重启、零镜像变更、零配置触碰）
对象：W2 视觉形态（`…-Ring-VL-baked4`，vision-exp 权重，k=6）相对 W1 文本形态（0731 权重，k=7）的 decode 单流吞吐损失 -27.7%（90.6 → 65.5 tok/s）

---

## 0. 结论摘要（TL;DR）

1. **损失完全可分解、无异常泄漏**：吞吐比 0.723 = 接受长度比 0.867（4.5→3.9）× 步时比 0.835（49.7→59.5ms），数学闭合。不存在"看不见的第三方开销"。
2. **根因主项 = draft 链从 1 层变 3 层**（vision-exp 权重架构自带 `n_mtp_layers=3`，0731 只有 1 层）。这是**官方架构强制**：参考实现 `forward_spec` 必须全链跑 3 层 MTP，不可截断。+9.8ms 步时增量按 ~4.9ms/层（小 batch MoE，launch/memory-bound）估算与此吻合，但层数成本是估计值，目标侧残差不能排除（需 E1 实验关闭）。
3. **根因次项 = 接受长度 -13%**：k 从 7 降到 6（fork 硬校验 k≥block_size(5) 且 k%n_predict(3)==0，6 是最小合法值；k=7 只在 0731 的 n_predict=1 下合法）压低了每步上限，叠加 vision 权重的 draft 质量差异。
4. **全网无参照系**：上游 vLLM main 对 DSv4 vision **零支持**（不存在任何 PR）；官方 recipe 仅在 **GB200 NVL4** 验证过，且其接受长度 2.99 tok/fwd **低于**我们的 3.9-5.3；社区 SM120 文本数字（调优后 30-35 tok/s）远低于我们 fork 的 90.6 基线。**我们是 vision-on-GB10 的第一个公开级实现，-28% 是对我们自己的文本基线，不是对任何可达到的 vision 水位。**
5. **恢复路径明确**：最有希望的单变量是 **k=9**（回收接受长度上限，draft 前向仍是一次并行 forward，仅顺序采样循环 +3 次迭代）；官方的 k=3+adaptive_verification 配方**在 fork 上不存在**（已实证 grep 零命中），不可照抄。

---

## 1. 调查期间生产状态实证

- 调查进行中（本日）生产团队**已执行停机切换**：四机容器换回非视觉基线 `…-TP4-Ring-baked`（0731 权重，`served-model-name deepseek-v4-flash-0731`，k=7，mmlen 600000），即用户安排的文本基线测试臂已在跑。
- 视觉形态资产完整保留、可一键回切：镜像 `…-Ring-VL-baked4`（digest <BASE_IMAGE_DIGEST>）四机在库；脚本变体 `start_tp4_{head,worker}_v043.sh.w2-20260902`（R5 指 baked4 + W2 serve 参数）。回切 = R5 指回 + guard 重启，无重建成本。

## 2. 归因数学（测量闭合）

| 量 | W1（0731, k=7） | W2（vision-exp, k=6） | 比 |
|---|---|---|---|
| decode 单流 | 90.6 tok/s | 65.5 tok/s | **0.723** |
| 平均接受长度 | 4.5 | 3.9 | 0.867 |
| 步时 | 49.7 ms | 59.5 ms | 0.835（+9.8ms） |

校验：4.5/0.0497 = 90.5 ✓；3.9/0.0595 = 65.5 ✓；0.867 × 0.835 = 0.724 ✓。两因子完全解释损失，无残差泄漏。

**+9.8ms 的分解（当前最优估计）**：
- draft 侧：+2 个 draft MoE 层（1→3 层链）。draft 前向是小 batch MoE（每请求 6-8 token 穿全层），launch/memory-bound，估算 ~4.9ms/层 → +9.8ms 与观测吻合。**但每层成本是推算值**：若实际更低（如 3ms/层），则存在最多 ~4-10ms 的目标侧残差，候选来源 = 图像上下文的稀疏索引宽度翻倍（SWA 段 128→512，即我们 F2 修复补的 TK=512 路径）+ 该 kernel 仅 FP8 ComputeMode 单实例、成熟度低于文本 TK=128 路径。**纯文本请求的解码理论上不受索引宽度影响**（SWA 恒 128），故 65.5 探针（纯文本）中目标侧残差预期较小——此判断正是 E1 实验要验证的。

**接受长度 -13% 的分解**：
- k=7→6：每步 token 上限 8→7，机械性压低 ~1/8；
- vision 权重 draft 质量：3 层 Markov 链是新训练目标（图文混合），位置接受率 0.92/0.77/0.70 形态健康但整体略低于 0731。

## 3. 计算流逐段剖析（源码级）

**draft 路径**（`vllm/v1/worker/gpu/spec_decode/dspark/speculator.py`，镜像内只读取证）：
- `_generate_draft` = **一次**并行 backbone 前向（num_reqs × n_spec token 穿全部 `num_dspark_layers` 层）+ `_sample_sequential` 顺序 Markov 采样循环（`for i in range(n_spec)`，k=6 即 6 次迭代，每次一次 `gumbel_sample`）。
- 层数由权重 config 决定：`num_dspark_layers = n_mtp_layers or 3`。0731=1 层（DSpark 102 params），vision-exp=3 层（105 params；97→102→105 与三代权重自洽）。
- **3 层不可截断**：官方参考 `model.py::forward_spec` 同样全链跑 MTP 层（各层隐状态供目标验证用），README 自述"可读参考实现而非生产服务引擎"。截断 = 改变验证语义，不可行。
- `use_fp64_gumbel` 默认 `False`（`config/model.py:239`，镜像内实证）→ **fp64 gumbel 候选排除**，现网 draft 采样已是 fp32。
- k 上调的边际成本：draft 前向 token 宽度 6→9→12（launch-bound，次线性增长）+ 采样循环 +3/+6 次迭代 + 验证 batch 变宽。**k=9 成本增量小、接受上限 +3**，是收益/成本比最好的方向。

**目标侧路径**：文本 token 的 MoE 路由两形态一致（`num_hash_layers=3` 两套权重相同）；`bias_vl` 是 kernel 内 elementwise，非路由变更；KV/注意力配置除稀疏索引宽度（仅图像行生效）外相同。FULL 11/11 + dspark 10/11→10/10 图捕获两形态均完整（**cudagraph 覆盖差异已排除**）。

## 4. 已排除项清单

| 候选 | 排除证据 |
|---|---|
| cudagraph 捕获集缺失 | 两形态 FULL 11/11 + dspark 10/10 完整（更正早期 12/12 记忆错误，logdump 复核） |
| 环境变量丢失/异常 | 仅 3 条良性 `Unknown:`（DISABLE_CUSTOM_ALL_REDUCE / MOE_DYNAMIC_TILE_CAP / TOPO_SAME_NODE_MAP），均为未消费提示 |
| MoE 路由路径变化 | num_hash_layers=3 两权重一致；文本 token 路径逐源码比对一致 |
| fp64 gumbel 采样开销 | `use_fp64_gumbel` 默认 False（本日镜像内实证） |
| processor/请求模板开销 | 仅影响 TTFT，不影响稳态 decode 步时 |
| tokenizer/编码差异 | W1 已验证逐 token 等价（含 GSM8K 答案 bit 级一致） |

## 5. 官方支持调查

- **官方 vLLM recipe**（已全文抓取）：推荐 `k=3` + `enable_adaptive_verification: true`；"block width 5, only depth 3 publicly tested"；**唯一有公开 vision 运行记录的硬件是 GB200 NVL4（TP4+EP）**；要求 pinned 镜像 `vllm/vllm-openai:deepseekv4-flash-vision`。
- GB200 参考水位：接受长度 2.99 tok/fwd（66.3%；位置 83.9/66.5/50.7）。**我们 k=6 的 3.9-5.3（0.92/0.77/0.70）全面高于它**——draft 质量不是我们的短板。
- **fork 能力边界实证（本日新增）**：`enable_adaptive_verification` 在 fork 全树 grep 零命中 → 官方 k=3+adaptive 配方**无法在我们栈上复现**；k 合法域 = {6, 9, 12}（k≥5 且 k%3==0）。
- 权重内置推理参考（`/opt/_PH_INSTALL_/models/dsv4-vision-exp/inference/`）：`n_mtp_layers=3`、`dspark_block_size=5`、`target_layer_ids=[40,41,42]`、`markov_rank=256`；`forward_spec` 全链循环 = 3 层链的架构必然。

## 6. 社区调查

- **HF 讨论 #28**（deepseek-ai/DeepSeek-V4-Flash，"Running models with vLLM on the RTX Pro 6000 - SM120"，已抓取）：SM120 文本版社区水位 = 朴素 5 tok/s → 调优（CUDA graph + 正确 env）30-35 tok/s；SGLang+EAGLE（2 draft）40-50；2×RTX Pro 6000 + MTP k=1 ~100 tok/s。已知问题簇：DeepGEMM 不支持 SM120（PR#318 待合）、sparse MLA 需 fallback、W8A8/MoE 报 "Performance might be sub-optimal"、长上下文 decode 掉至 3-5 tok/s（correctness-first patch）。**结论：stock SM120 栈远低于我们 fork 的 90.6 基线；社区不存在任何 vision 数字。**
- **NVIDIA 论坛 #381911**（"DeepSeek V4 Flash Vision Exp is released as open weights"，已抓取）：上游 vLLM main 对 V4 vision **零支持**（`DeepseekV4ForCausalLM` 映射无任何 vision/multimodal 引用，搜索 issues/PR 无任何 dsv4-vision PR）；Aiden 镜像 = 文本可用无 vision processor；eugr 仓库 = 仅 0731 文本；唯一 "vision" 方案是非官方 LoRA+外挂 vision tower 拼接。社区共识："Day 0-1 way too rough，约一个月后格局才明朗"。
- **vLLM issue #47266 + 我们 F2 同族**：SM12x sparse-MLA kernel 支持面缺口是**系统性现状**（不是我们移植引入的 bug）——F2（dual prefill 无 TK=512 实例）即此家族在 vision 负载下的具体表现，我们已用 JIT 源码补丁（baked2）先行修复。
- **综合**：vision-on-GB10 无任何外部参照；恢复方案的唯一标尺是我们自己的 0731 文本基线 + 官方 GB200 形态因子。

## 7. 分层恢复方案

**L0 配置级**（仅改 serve 参数，单窗单变量，无镜像变更）：
1. **k sweep 6/9/12（k=9 优先）**：接受上限 +3，draft 前向近似免费（launch-bound），采样循环 +3 迭代。位置接受率 0.70 的第三位之后仍有肉（对比 0731 的 4.5@k=7）。预期回收吞吐 +8~15%。
2. `--max-num-batched-tokens 4096→8192`：清 boot 警告（"at least 4036"），给图像 prompt 的 chunked prefill 留头寸（TTFT 项，13.3s 单图冷启动可受益）。
3. `draft_sample_method` 保持 probabilistic（greedy 会在长生成漂移，无证据支持换）。

**L1 代码级**（镜像层变更，不动架构）：
1. draft 小 batch MoE 专优化：6-8 token 穿全层 MoE 是 launch-bound，候选 = draft 专用精简 dispatch（跳过 EP 握手开销）、层间 fusion。需 profiler 数据支撑（E4）。
2. TK=512 dual prefill kernel 扩实例：当前仅 FP8 ComputeMode 一档；按 0731 TK=128 的模板族（PBSX×NH 全档）补齐 + autotune 深化（现 30 configs 含 vision 6 个新形状）。
3. 跟踪上游 SM12x 家族修复（#47266、DeepGEMM #318）择机回合。

**L2 结构级**：
1. **双服务路由**：文本流量 → 0731 非视觉服务（90.6），图像流量 → vision 服务。单集群显存不能同时双开——需第二组资源或按负载分窗；若业务图像占比低，这是唯一能"零损失保文本"的结构。
2. 上游等待项：官方 pinned vision 镜像扩展到 GB10 / vision PR 进 main（NVIDIA 论坛共识 ~1 个月明朗化）；PR#54566 移植是我们的 in-house 优势，持续维护。

## 8. 停机窗实验清单（配合生产文本基线排期，每项单变量一窗）

| # | 实验 | 操作 | 判定 |
|---|---|---|---|
| E1 | 目标侧隔离 | vision-exp + **spec off** vs 0731 + spec off，纯文本 decode 探针 | 步时相等 → +9.8ms 全在 draft 侧（3 层链定案）；vision 更慢 → 目标侧残差存在（稀疏宽度/kernel），L1-2 提级 |
| E2 | k sweep | vision-exp，k ∈ {9, 12}（k=6 已有 65.5） | accept/步时曲线，选最优 k；验证 k=9 采样循环成本假设 |
| E3 | k 单变量 | **0731 + k=6**（0731 n_predict=1 任意 k 合法） | 隔离 k=7→6 的机械效应 vs 权重/链效应；与 90.6（k=7）、65.5（vision k=6）构成 2×2 分解 |
| E4 | draft 剖析 | vision-exp k=6 + torch profiler 抓 draft 前向/采样分段 | 每层 MoE 实测成本（检验 4.9ms 估计）、采样循环占比 → 决定 L1-1 是否立项 |

优先级：**E1 > E3 > E2 > E4**（E1/E3 是归因收口，E2 是回收收益，E4 支撑代码级立项）。

## 9. 交接事项（ops/生产）

1. 生产文本基线臂已由 ops 启动（Ring-baked，k=7）——其 decode 单流数字应复现 ~90.6 tok/s，作为 E 系列的对照锚点。
2. 8001 调用方：vision 服务停用期间模型名回到 `deepseek-v4-flash-0731`；vision 回切时再切 `deepseek-v4-flash-vision-exp`。
3. window_restart TCPStore 超时仍起 worker 的缺陷已两次记录，仍待修。
4. logdump 按纪律保持关闭（W2 取证完成后即关）。

## 10. 调查过程资产

- 本报告：`~/w6-kit/G1R7VL-PERF-INVESTIGATION-20260902.md`
- 上游报告：`G1R7VL-W1-REPORT-20260902.md`、`G1R7VL-VLBAKED-20260902.md`、`G1R7VL-W2-REPORT-20260902.md`
- 原始数据：`~/w6-logs/G1R7VL_W1/`、`~/w6-logs/G1R7VL_W2/`（GSM8K raw + decode 探针）
- 源码取证（只读）：镜像内 `speculator.py`/`dspark.py`/`config/model.py`；权重参考 `dsv4-vision-exp/inference/`
- 外部证据：官方 recipe（WebFetch 全文）、HF #28（webReader 全文）、NVIDIA 论坛 #381911（WebFetch 全文）

---

# 11. 第二轮深挖（同日追加）：GitHub 社区 + 代码级计算流 + 优化定案

用户指令：k=9 待窗测试；确认主差异是 dspark 追加 draft 链；GitHub 社区深挖；无窗条件下代码/计算流层优化调查。产物：`~/w6-kit/g1r7-build/perf-inv/DRAFT-OPT-SPECS-20260902.md`（补丁规格全文）+ k9 脚本变体四机就绪。

## 11.1 代码级计算流解剖（镜像内只读，全部源码实证）

draft 每 step 成本清单（k=6 单请求）：combine(main_proj ~0.2ms) + ctx-KV(~0.3ms，fork 已有 WKV_ONLY 优化默认开) + **3 层前向 ~5-6ms**（MoE 专家读 ~415MB/层是带宽主项：6 tok × topk6 → ~33 唯一专家 × 12.6MB；GB10 ~273GB/s）+ **采样 ~1-1.5ms**。

**通信面（此前未知的重点）**：每 draft step = **13 次跨机小消息通信**——6× allreduce（3 层 × [o_proj wo_b + shared expert down_proj]）+ **7× all-gather 串行**（1 次 base logits + k 次 Markov bias，后者因 Markov 链逐位串行，`logits_processor.py:93` 实证）。CX7 quad-ring 小消息 60-150µs/次 → 通信独占 ~0.8-1.9ms。

**两个定案**：
- `num_speculative_steps = num_speculative_tokens`（speculator.py:78）——k=9 仍是**一次** 9-token 宽并行前向，不是多次；
- `use_fp64_gumbel` 默认 False + DSpark 全流程在 FULL CUDA graph 内（图 10/10）——无 eager 惩罚（#47266 的 SM120 陷阱与我们无关）。

## 11.2 接受率曲线的反转发现（logdump 实测）

W2（vision k=6）位置率 `0.86-0.92/0.71-0.77/0.52-0.70/0.32-0.39/0.22-0.26/0.07-0.13` **逐位高于** W1（0731 k=7）的 `0.74/0.58/0.41/0.35/0.24/0.15/0.12`——**vision 3 层 draft 单位质量优于 0731 单层**，接受长度 4.5→3.9 主要是 k=7→6 机械截断而非 draft 退化。3 层链"买到了"更好的 draft，代价是层数×带宽的步时。

**k=9 重估（下调预期）**：尾部外推位 7-9 仅 +0.2 accept（+5%），成本 = draft 宽 6→9（专家读 +~35%）+ verify 7→10（目标 MoE 读 +15-20%）+ 采样 +3 串行迭代 → step +5-7ms（+9-11%）→ **单流预期净负 3-6%**。k9 变体（`.w2k9-20260902` 四机就绪）仍按批准实测，用于证伪/证实该曲线模型；若净负则 k=6 确认为合法域下界即最优。

## 11.3 GitHub 社区深挖要点（20 项来源，全文见 DRAFT-OPT-SPECS 附录）

- **PR#54566 评论（2×DGX Spark GB10）**：vision k=3=39.1 vs k=6=30.7 tok/s（no-spec 25.3）——"acceptance 不随 k 增长"。但其 draft 水位弱（k=3 已收 2.6-2.8/3）；我们的位置率更高、尾部仍有产出，k=6 对我们仍可能最优（k=3 在 fork 校验下也非法，且我们曲线外推净负 ~10%）。
- **上游 `dspark_draft_topk`**（官方 config，要求 draft TP1）= 我们 C2 补丁的官方等价物——方向正确性背书；**`speculative_draft_tensor_parallel_size`** fork 有 flag 但 DSpark 实现零引用（draft 层共享目标 TP4 分片），工程上不可行且理论收益平手，放弃。
- **Kimi K3 官方博客**：DSpark block-diffusion 骨干 draft 成本平坦 vs **MTP 链式每层串行**——从架构原理互证我们的归因（+2 层 = 实打实串行成本）。
- **eugr 社区 0rand 法则**：每 1 个 MTP token 配 ≥6k batched_tokens（他用 8k-10k）→ 支持 `max_num_batched_tokens 4096→8192` 独立臂。
- **issue #49002**：DSpark+结构化输出在 tool-call 边界 5-12s 停顿——⚠️ 生产开了 auto-tool-choice，**移交 ops 监控**此症状。
- vLLM meetup 口径 draft propose 开销 ~20%：我们 draft 侧 17-25%，同量级，无异常。

## 11.4 代码级优化定案（待开窗烘焙 baked5）

| # | 优化 | 类型 | 预期 | 风险 |
|---|---|---|---|---|
| C1 | Markov 转移头复制化（w2 66MB/rank 复制，bias 本地算，消 k 次串行 all-gather） | env 门控补丁 `VLLM_DSPARK_MARKOV_REPL` | -0.4~0.9ms/step（+1~1.5%） | 低（四 rank 同输入同权重 → 逐位一致） |
| C2 | draft 专家 topk 封顶（`n_activated_experts` 运行时覆盖，候选 4/5） | env 门控补丁 `VLLM_DSPARK_DRAFT_TOPK` | MoE 专家读 -33%（topk4），step -1.5~2ms | accept 或降；目标验证兜底正确性，A/B 净增益判据 |
| C4 | TK512 dual prefill 扩档（TTFT 侧） | kernel 补丁 | 图像 prefill 提速 | 独立于 decode |
| ~~C3~~ | draft 注意力复制（消 6 allreduce） | — | ~0.2-0.4ms | 工程量大，排后 |

窗口建议（待排期）：窗 A 三臂 = k=9 实测 → k=6+C1 → k=6+C1+C2(4)，每臂 decode 探针 + GSM8K10 哨兵 + accept 分布；`batched_tokens 8192` 与 E1（spec-off 目标侧隔离）为独立臂。

## 12. 归因重大修正（2026-09-02 第四轮核查）："0731 单层 draft" 不成立，两形态均为 3 层

**证据链（全部只读实证，可复核）**：
1. 两份 checkpoint 的 index 均含完整 `mtp.0/1/2` 三级权重（0731 与 vision 结构相同，head 栈同样只在 mtp.2）。
2. `n_mtp_layers` 全 vllm 树仅在 dspark.py:70 出现（三平台变体同款 `getattr(...) or 3`），**无任何注入点**；两份 config.json 均无此键 → 两形态都默认加载 3 层 draft。
3. W1 时代镜像（-VL v2, 6637e26f）与现行镜像同款代码行（docker run grep 复核）。
4. 参数计数 102 vs 105 的差**精确等于** vision 独有的 `mtp.{0,1,2}.ffn.gate.bias_vl`（0731 零个 bias_vl 张量）。
5. `num_nextn_predict_layers`（0731=1 / vision=3）只影响 k 整除校验（n_predict），不影响层数。

**推论**：
- 第 2 节归因中"+9.8ms ≈ 2 个额外 draft MoE 层"**作废**——draft 结构两形态相同，且 k=7→6 使 W2 的 draft 反而略便宜（宽度-1、采样迭代-1）。
- +9.8ms 的领先候选假设变为：**vision-exp 权重的路由展平 → 每步唯一专家数增多 → 专家权读增大（目标侧+draft 侧，带宽受限步时的直接放大器）**。量级核：目标 43 层，若每层唯一专家 +3~5 个 → +1.6~2.7GB 读 ≈ +6~10ms ✓ 量级吻合。
- **E1（双权重 spec-off 对照）从"重要"升格为"决定性"**；新增 E5：在 draft/目标侧记录每步 topk_ids 唯一专家计数的轻量插桩（或由 E1 差值反推）。
- 若 E1 证实目标侧专家展平：目标 topk **不可封顶**（目标定义真值，正确性红线），配置层无解 → 双服务路由（0731 承接文本流量）的价值上升；C2（draft 侧封顶）依然合法且正好攻击 draft 侧的展平成本。
- C1（通信面）与 C2 的设计不受影响——它们削减的成本在两形态中都真实存在。

原第 2/11 节的归因叙述保留作过程记录，以本节为准。

## 11.5 第三轮深挖（同日）：三方向设计定稿

用户圈定 C2/C3+C5/C1 三方向后逐一定稿，全文 `g1r7-build/perf-inv/DRAFT-OPT-DEEPDIVE-20260902.md`。要点修正：
- **通信面是 19 次/step 不是 13**——新发现 `markov_w1`（VocabParallelEmbedding）每次迭代 allreduce（vocab_parallel_embedding.py:491），Markov 循环每迭代 2 次通信共 12 次串行。
- **C1 升级 w1+w2 双复制**：数值中性（allreduce 单命中求和 = 本地查表；行分片 gather = 全量 matmul 行），+132MB/rank，消 12 次串行通信，+2~4%，baked5 首选。
- **C2 靶点修正**：flashinfer_b12x 走 FusedMoE 路径，topk 真实消费点 = `router.top_k`（每步现读）+ `moe_config.experts_per_token`（构造期烤入）——需三处联动覆盖（含 `_set_moe_config` 后门）。盈亏线：topk4 容忍 accept 降 <2.8%，偏紧，A/B 定夺。
- **C3/C5 确认可行但收益最小**（<1%）：wq_a/wkv fork 已 disable_tp（有先例），分片只剩 wo_a/wo_b 一对；FFN allreduce 是 MoE 分片固有不可消。
- **组合天花板 +4~6%**（65.5 → ~69-74 tok/s），其余为 3 层链 MoE 读的架构内损失，只能靠 L2 结构级（双服务路由）或官方后续优化。
