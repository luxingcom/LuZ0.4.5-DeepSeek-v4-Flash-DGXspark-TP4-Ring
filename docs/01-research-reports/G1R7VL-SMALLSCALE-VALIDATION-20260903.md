# G1R7-VL 优化路线图小规模验证测试分析（无窗条件下）

日期：2026-09-03 ｜ 模式：**非开窗**——离线（CPU throwaway 容器，零集群影响）+ 现网有限探针
前置：四轮归因调查 + MTP 公开资料调查（DEEPDIVE 第 7/8 节）；本报告做**逐项可验证性判定**与**组合分析**，为正式测试提供 runbook。

## 0. 无窗条件下的验证边界

| 类别 | 手段 | 能验证 | 不能验证 |
|---|---|---|---|
| 离线权重级 | throwaway 容器读真实 checkpoint（torch CPU） | C1 数值中性、C2 路由尾部质量、E1-pretest 路由展平 | 运行时行为/吞吞吐 |
| 代码静态核验 | 镜像内源码逐行 | C2 覆盖点完整性、SKIP_MTP_COPY 条件、C1 加载路径 | 编译/运行期交互 |
| 现网有限探针 | 1 条流式请求 + 容器 metrics | 健康锚点、负载下位置率 | 干净单流基线（W1 已具） |
| **仅运行时** | 需 restart 窗 | — | E1、k=9、baked5 三臂、图捕获、autotune、accept 实测 |

结论先行：**C1 与 SKIP_MTP_COPY 修复达到"可放心进 baked5"的离线证据强度；C2 被离线数据判为高风险（不建议主推）；C6a/C6b 得到离线数据强背书（33% 尾部质量浪费）；E1-pretest 削弱了"目标侧路由展平"这一领先假设的权重级支持（E1 仍决定性）。**

## 1. 逐项验证结果

### 1.1 C1 Markov 头双复制化 —— ✅ 位级中性在真实权重上证明

离线脚本（real vision weights, torch CPU）：
- `mtp.2.markov_head.markov_w1.weight` / `.markov_w2.weight` 均为 **[129280, 256] bf16**（V=129280=r，无逐 rank 分片前的全量形态），加载路径（dspark.py head_prefixes → 每 rank 全量）静态核验通过。
- **行分片 matmul == 全量 matmul（torch.equal 位级相等）：True**——TP path 的 gather 语义与复制路径逐位一致，数值中性论断成立。
- 补充政策：TP 路径 `logits_processor` 以 fp32 累积输出（boot 日志 draft_logits=float32 佐证）→ **复制版 bias() 必须 cast fp32**（bf16 直算会漂移 accept 画像），已写入补丁规格。

**判定：无残留技术风险，唯一注意点是 fp32 cast 政策。进入 baked5。**

### 1.2 C2 draft topk 封顶 —— ⚠ 离线判高风险，降级为可选 A/B

真实权重路由几何（mtp.0 draft gate，sqrtsoftplus+re-normalize 语义复刻）：
- **topk6 的 renormalize 质量中，位置 5-6 合计占 ~32%**（vision 32.1-32.9% / 0731 32.2-32.7%，两伪隐藏集一致）
- topk5 的尾位（pos5）占 ~19%
- 含义：从 topk6 砍到 topk4 将移除 **1/3 的 draft MoE 输出质量**；对照盈亏线（topk4 只能容忍 accept 降 <2.8%），**C2 预期净负**。
- 代码路径（覆盖点完整性）静态核验通过：FusedMoEConfig 是 dataclass（config.py:1274 区）、`router.top_k` 每步现读（base_router.py:181）、`_set_moe_config` 后门在位（moe_runner.py:329）——补丁可构造。

**判定：不 bake in；保留为 env 臂（VLLM_DSPARK_DRAFT_TOPK=5）单窗 A/B 实证，期望负；若有意外收益则升格。** 离线数字同时是 strong signal：draft 把 32% 火力花在几乎不存活的尾部位置（W2 位 5-6 接受率仅 0.26/0.13）——**"draft 尾部过度自信且低存活"正是 C6a/C6b 动态截断的价值所在**。

### 1.3 E1-pretest——目标侧路由展平假设的权重级检验：⚠ 未获支持

offline 对比 layer-40（目标层，non-hash）gate 平坦度（同协议伪隐藏）：
- vision: std=0.207 kurt=3.64 top6-mass-std=0.0009
- 0731:  std=0.213 kurt=3.79 top6-mass-std=0.0010
- **目标侧两权重几乎同平** → "+9.8ms 主因=vision 目标侧路由展平读放大"这一假设**得不到权重级支持**（layer-40 代表性存疑 + 伪隐藏非真实激活；但方向上显著弱化）。

**影响**：E1 仍是决定性的，但若 E1 显示目标侧大差距，机制可能不是行平坦度而是其他（激活范数分布/专家相关结构），E5 插桩（每步唯一专家计数）的权重上升。此 pre-test 使 E1 的预期从"很可能 6-10ms"下调为"不确定，需实测"。

（附带：draft 侧 mtp.0 gate 上 vision 较 0731 平 12-40%，但 draft 仅 3 层、贡献小，且同样受伪隐藏限制。）

### 1.4 C6a regret 控制器 —— ✅ 离线数据强背书（设计就绪）

- 离线：draft 尾部 32% 质量/位置存活 <0.1 → "低接受场景投机空转"是量化既实；
- 社区范本 376884：yield-quench 实测最坏 0.96×；
- 本方案：调度器级（每请求累积 regret=（2.22−实际提交）or 预算−提交，跨阈值关投机），零模型改动、正确性天然安全。
- 无重启即可做**设计冻结**；运行时验证必须开窗（单流/深上下文/agentic 三场景 A/B）。

**判定：E1 定案后立项；设计冻结可立即进行。**

### 1.5 C6b confidence-head 激活 —— ✅ 原料在位（工程前置确认）

- `mtp.2.confidence_head.*` 权重在 checkpoint 中确认存在（第六轮已证）；fork 加载时丢弃（"not wired"）。
- 上游语义（#47808）：生存概率累积 + 双成本表 + top-B。SM12x varlen graph 适配为工程量主项。
- 无窗可做：移植设计 + 成本表 profiling 方法冻结。

### 1.6 k=9 —— 无离线变化，预期维持净负

位置率尾部（0.13/0.07）与新的 32% 尾部质量数据一致：k=9 的位 7-9 边际生存 <0.05，成本 vs 收益不利。变体脚本已在四机（.w2k9）。**待窗实测证伪。**

### 1.7 SKIP_MTP_COPY 条件写反 —— ✅ 静态确认，一字符修复入 baked5

model.py:1141 条件 `!= '0'` 与注释（默认跳过、=0 恢复）相反；四机 env 未设（已核实）→ 死拷贝每步在跑。修复 `!=`→`==`。decode 侧收益微小，**prefill 满批 268MB/步（TTFT）**。

## 2. 小范围组合验证分析（无窗可做的组合矩阵）

| 组合 | 交互 | 离线可证 | 结论 |
|---|---|---|---|
| C1 + SKIP_MTP_COPY 修复 | 无代码耦合（dspark 模型 vs 目标 forward） | 各自独立成立 | 同一 baked5，互不干扰；C1 不改任何 token 流，SKIP 只删死拷贝——组合后接受画像应逐位不变（正式门：decode 探针 + GSM8K10） |
| C1 + fp32 cast 政策 | C1 内部依赖 | 政策已定 | bias 必 fp32；补丁规格锁定 |
| C2 + C1 | C2 只动路由 topk，C1 只动采样头，正交 | 各自几何/中性独立 | 可同 mirror 分臂（C1 默认开、C2 env 门控），互不掩盖 |
| C6a + 任何 | 调度器层、与 speculator 正交 | 设计独立 | 可叠加，但建议 C6a 单独先验 |
| C2 + C6a | C2 静态砍顶 vs C6a 动态关投机——目的重叠 | — | 若 C6a 生效，C2 价值进一步下降；A/B 时互斥对照更清楚 |

**组合判语**：baked5 内组合（C1+SKIP）风险最低、证据最足；C2 作为孤立 A/B 臂与 C6a 冲突（互斥对照）；C6 与一切正交。建议正式窗的臂序：E1（先定案）→ baked5 C1+SKIP（两臂：C1 开/关+S8K sentinel）→ k9 → C2(5) 备选 → C6a。

## 3. 现网 0731 有限探针（2026-09-03，负载下观察）

- 探针：单流"数到 30"，144 字符产出，端到端 0.73s（含 TTFT）——**服务健康、响应快**；word 级估算 ~44w/s（数字是多 token，实际 tok/s 更高；不替代 W1 的 90.6 干净基线，仅作健康锚）。
- 容器 metrics（探针邻近窗）：accept 2.65-3.88、位置率 0.85/0.71/0.47/0.35/0.23/0.16/0.12（安静窗）——0731 k=7 位置画像健康，与 W1 形态一致。
- 注意：现网为生产负载（Drafted 88-178 tok/s 波动），任何基于现网的"基线"都是负载混叠值，须标注，不得与 W1/W2 单流数字同级引用。

## 4. 正式测试 Runbook（预注册协议，待排窗）

窗 0（~35min）：**E1** spec-off 双臂（vision / 0731）+ 单流探针；门：Δ≥6ms=目标侧定案、Δ≤3ms=转 E5；附带每臂 boot 哨兵（autotune/图捕获/0 异常）。
窗 1（~20min）：**baked5**（C1+SKIP 修复，env 门控）vs baked4 基线——门：decode 探针≥基线、accept 画像逐位可比、GSM8K10 哨兵逐位一致（C1 数值中性的运行时证明）、0 异常。
窗 2（~15min）：**k=9**（脚本就绪）——门：净增负则记录并回 k6。
窗 3（~15min，备选）：**C2 topk=5**（env）——门：吞吐净增才保，预期负。
窗 4+：**C6a** regret 控制器（E1 定案后）——门：最坏 ≥0.96×、难内容场景正收益。

全部走 w9r4_restart_guard.sh；每臂单变量；logdump 调试用随臂启停（纪律）。

## 5. 未验证项清单（仅运行时，离线无法覆盖）

E1/E5 实测、baked5 运行时闭环、k9/C2/C6 运行时、CUDA 图捕获与 autotune 增量、SM12x varlen graph（C6b）、markov fp32 cast 运行等价、SKIP_MTP_COPY 修复后 prefill 行为。

## 6. 资产

- 验证脚本：`g1r7-build/perf-inv/offline_validate.py`（C1/C2/E1-pretest，throwaway torch CPU 容器）
- 运行记录：本报告第 1 节数据（容器输出已核）
- 补丁规格：`g1r7-build/perf-inv/DRAFT-OPT-DEEPDIVE-20260902.md`（第 7/8 节）+ `DRAFT-OPT-SPECS-20260902.md`
