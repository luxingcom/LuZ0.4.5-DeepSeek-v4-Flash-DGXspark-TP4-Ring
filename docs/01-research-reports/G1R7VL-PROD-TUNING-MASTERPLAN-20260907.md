# 生产调优 + VL 分支重建 总编排计划（MASTERPLAN，2026-09-07）

> **⚠ 定稿后状态（2026-09-08 VL 定稿时标注，正文保留作过程档案）**：
> - Phase A/B 已闭环：k=5 判定门未过 → **生产维持 k=7**（窗1 数据）；"k=5 候选⏳"作废。
> - Phase C 落地超预期：VL 分支定稿为 **baked7f1 + FULL 图 + k=6**（非本文件当时的 baked6 预估），
>   官方名 `LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`，见 G1R7VL-BASELINE-DELIVERY-20260908.md。
> - Phase F 中 C1 已在窗2 **否决**（并发 -13~21%），"待窗"作废。
> - B窗3（F1 flashinfer A/B）已在窗3 执行完毕：**adopt**（453aa7c 换装即定稿镜像成分）。
> - VL k 约束更新：检查点 n_predict=3 → k∈{3,6}，本文件写作时的 k=5/k=7 选项对 VL 不适用。

# 生产调优 + VL 分支重建 总编排计划（MASTERPLAN，2026-09-07）

对应四项工作目标：①生产接受率审计与 k=7→k=5 判定 ②生产调优后以生产镜像为基座准备 VL 分支 ③社区优化总表 + 子代理逐项深查 + VL 全量优化 ④真实有效优化方案清单。
停机窗口由用户排期；本计划标注每阶段的窗口需求。红线沿用：一切重启走 `w9r4_restart_guard.sh`；不动其他团队资产；本地操作限内存；rank0 容器禁 import torch；长动作挂超时。

---

## 1. Phase A（已完成 2026-09-07，无窗，只读+轻量探针）— 目标①

### A0 生产现状快照（重要发现：生产镜像已演进为 V5）

| 项 | 值 |
|---|---|
| 容器 | node01 头节点 `vllm028-tp4-rank0`（名字有误导），healthy，boot 集群时 09-06 23:48 |
| 引擎 | **仍是我们的 fork** `v0.26.1.dev0+gd3d3b2cca.d20260805`（非 0.28） |
| 镜像 | `…DGXspark-TP4-Ring-V5`（digest `<BAKE_IMAGE_DIGEST>`，09-04 11:41 UTC 构建） |
| V5 血统 | toolfix1 层(09-02) + "W9R14 autotune 固定路径缓存"层 + **2×60MB `sleep 300` commit 层（09-05 前后，内容未鉴定）** |
| V5 不含 | baked5 三补丁（C1/C2 env 门）、SKIP_MTP_COPY 修复（model.py:1141 仍是写反的 `!= '0'`，**死拷贝在生产上活着**）、VL 补丁链全部、TK512（flashinfer stock 0.6.18，.cu md5 `af781a7e`） |
| 服务形态 | 0731 权重、**k=7** dspark probabilistic、**mmlen 600000**、fp8_ds_mla、flashinfer_b12x、seqs 12、CG sizes 1..96、容器口 8002（API 8001）、auto-tool-choice on |
| 流量 | 活跃，背景 accepted ~21 tok/s 均值，有空闲间隙 |

推论：目标②的"当前生产镜像"= V5 血统（不再是 Ring-baked）；VL 分支 FROM V5 线。

### A2 三负载逐位接受率（temp 0.7，15×3 请求×384tok，并发 5，探针流量占窗口 ~80%）

| 块 | 窗口数 | 均值接受长 | p1 | p2 | p3 | p4 | p5 | p6 | p7 | p6+p7 边际 |
|---|---|---|---|---|---|---|---|---|---|---|
| 背景基线(15min) | 31 | 3.89 | .807 | .631 | .476 | .355 | .278 | .216 | .131 | **0.347** |
| prose 散文 | 5 | 2.43 | .649 | .385 | .210 | .109 | .048 | .020 | .010 | **0.030** |
| code 代码 | 4 | 3.11 | .739 | .532 | .354 | .221 | .138 | .082 | .047 | **0.129** |
| json 结构化 | 3 | 3.57 | .813 | .628 | .429 | .294 | .198 | .140 | .070 | **0.210** |

（加权按 Drafted tokens；原始窗口留档 `w6-logs/g1r7-tune-20260907/spec_metrics.log` + `probe_results.json`；模型输出带 reasoning，prose 实测含推理文本，纯创意文本接受率只会更低——强化 k=5 结论。）

### A3 k=7 → k=5 判定

- **边际收益**：k=7 比 k=5 多赚的 token/步 = p6+p7 = prose 0.03 / code 0.13 / json 0.21 / 背景混合 0.35，占均值的 1–9%。
- **边际成本**：verify 多 2 个 token/步（8 vs 6，+33% verify token），draft 多 2 个 query（+40%）；0731 k=7 步时 49.7ms 的主项是 61 层目标 verify，token 数近似线性（MoE 唯一专家重叠会略缓和）。
- **净效应预估**：若步时随 token 线性，k=5 省 ~15–25% 步时，换 1–9% token 损失 → **净正 +5~+20%**（prose 最大，结构化最小但依然为正）。
- **警示**：背景生产流量尾部（0.347）明显肥于探针——生产混有工具调用/重复模式负载（曾见均值 7.5 的窗口，p6=0.88），这类负载吃深 k。**最终决策必须窗口内同基准 A/B**，并按生产负载构成加权判读。
- fork 合法域：0731 n_predict=1 → k≥5 任意值合法（k=5/6 都可测）。
- **结论：支持调整，建议窗口内三臂 A/B（k=7 / k=6 / k=5），判读用本探针套件（复跑）+ 背景流量形态对比。**

---

## 2. Phase B 生产调优窗（目标①收口 + 目标②前半）— 需窗

**B窗1（建议 90 分钟，guard 重启 ×2 次——S 组数学已简化为两臂）**
1. 前置（无窗可先做）：构建 `V5b = V5 + 五补丁`（A1 SKIP 1 字符 + **A2 #54815 rope 2 行（P0 正确性）** + A3 #55636 防护 2 行 + C1/C2 env 门文件）。**不能直接复用 baked5**——它 FROM Ring-baked 线，不含 toolfix1/W9R14/V5 的两个 commit 层。构建沿 Dockerfile 纪律（md5 断言+负门），四机预拉。
2. 窗内：boot V5b@k=5 → 复跑三负载探针 + GSM8K10 哨兵 + 长上下文 needle 门（#54815 验证：30K/128K/500K 各 4 针）+ **决策门 t(5)<46.8ms（中位）即切 k=5**（盈亏平衡全表：prose 49.1/code 47.6/json 46.8/背景 45.3ms；附带门=p1..p5 曲线与 k=7 审计一致）→ k=7 复核基线 → 定稿。**k=6 臂删除**（S 组数学：k=6 从不是 >2% 的唯一赢家）；k=3 拒绝（需 F>0.8）。
3. 验收门：health 200 / GSM8K ≥0.9 / needle 修复前后 A/B（#54815 生效证据）/ 探针均值与逐位形态合理 / 吞吐对比记录。
4. 回退链：R5 指回 V5 + guard（k 回 7），一次重启。

**B窗2（可选 30 分钟）**：`VLLM_DSPARK_MARKOV_REPL=1`（C1）叠加 A/B——消 12 次/步串行跨机通信，预期 +2~4%（离线已证位级中性）。

**B窗3（可选 45-60 分钟，K 组终稿设计）**：F1 flashinfer main A/B——**pin `453aa7c` 精确 commit**（其后 14 commits 无一触 sparse_mla_sm120，避开 09-05 autotune-v2）；方式=源码 csrc/jit 换入现有 0.6.18 包（PyPI 无 aarch64 wheel）+删死 tactic 缓存+离线标定 cpb schema-v1；**TK512 手补丁退役**（arms 已并入 #4802）；预期=步时 −1%~−5%（crossover 重路由域 T∈{24..96} + 连续 H envelope 杀 TP4 pad-to-128）；门=zero-KV→zero-output 数值/VL span 原子性/text tok/s/**Gate-4 #4973 replay（长纯文本 prompt IMA 复现测试）**。VL 侧另获 `prefill_impl="swapab"` 可选（prefill 1.37-1.79×）。**#4973 缓解（无需等窗）**：baked5 VL 镜像在风险类，生产长纯文本 prompt 暂路由 V5 文本线。

## 3. Phase C VL 分支镜像准备（目标②后半，无窗构建）

基座 = Phase B 定稿的生产镜像（V5b 或其后续）。迁移清单（自 baked2/3/4/5 线搬运，逐项过门）：

| # | 迁移项 | 来源 | 备注 |
|---|---|---|---|
| C-1 | VL 模型注册+类（DeepseekV4ForConditionalGeneration、vl_model.py、mm processor、input_ids 注入） | baked3/4 | compose 与 V5 的 toolfix1 层已验证无冲突（toolfix 只动 encoding） |
| C-2 | TK512 kernel 或 flashinfer main | baked2 / #4802 | **依 Agent K 结论**：若 F1 采纳则手补丁退役；否则搬 .cu 补丁 |
| C-3 | baked5 三补丁 | baked5 | 若 B窗1 已上产则基座自带，免搬 |
| C-4 | 脚本族 | .w2b5 系 | 重命名为 VL2 系列，参数形态（k=6 起、mmlen 65536、limit-mm 4、served-name）不变 |
| C-5 | 权重挂载/符号链接 | 现有 P1 分发资产 | 不动 |

前置安全项：**鉴定 V5 两个 60MB commit 层内容**（registry diff 或容器内文件级对比），确认与 VL 补丁无冲突后才能 FROM。
构建门：py_compile ×N + 基座/补丁 md5 双断言 + 负门 + 离线 processor 全链验证；四机预拉。
验收（首次 VL 窗）：W2 三门复用（GSM8K×2、单图/4图/span 原子性、boot 哨兵 105 params/autotune/图捕获）。

## 4. Phase D 社区优化总表 + 子代理深查（目标③前半，无窗，进行中）

五组代理（K 内核 / V vLLM 合入 / F 本地码 / S 配置调度 / R 正确性稳定）逐项产出结论报告至 `~/w6-kit/g1r7-build/perf-inv/agent-reports/`，判据统一：**adopt-now / adopt-after-X / defer / reject** + 机理、预期（本拓扑定量或界）、fork 实施路径、风险与验证法。

| 组 | 项 |
|---|---|
| K | flashinfer main `453aa7c` 重建路径与 A/B 设计；#55180 SM12.x FP8 L2 raster swizzle；#54110 persistent topk 回退；#4990 grouped MoE 1-CTA/SM 瓶颈量化；#4931 ragged prefill 去同步 |
| V | #55234 DSpark cache-group；#55341 图捕获前 kernel warmup；#55299 prefill 哨兵；#55455 adaptive verification 延迟；#51725/#47808 自适应预算回取 0.26 可行性；#54631 n_predict 语义 |
| F | C1 双复制（0731 路径适用确认）；SKIP 修复（V5:1139-1143 对照）；C2 topk 封顶；C6a regret 控制器设计；C6b confidence-head（查 checkpoint 权重）；tonyd2wild Patch A drafter 私有 CG sizes；#50424 Markov W4A16 |
| S | k 分负载策略（用 Phase A 曲线）；block-k 补丁是什么/可否移植；调度级动态 k 可行性 |
| R | #54815 RoPE/YaRN-SWA（**生产 mmlen 已 600K，暴露面升高，优先**）；#52292/#54618 重启死锁（baked 暖 autotune 缓存正中 #54618）；eugr#358 stale draft KV（fork 是否有同缺陷） |

## 5. Phase E VL 全量优化窗（目标③后半，依 D 结论排，全部 guard）

- E窗0：E1 归因实验（e1b→e1a spec-off，门 Δ≥6ms/≤3ms）——不变，先于一切 VL 优化。
- E窗1：VL 新基座切换（Phase C 产物，代号 baked6）+ W2 三门复验。
- E窗2：F1 flashinfer main A/B（若未在 B窗3 做过文本侧验证）。
- E窗3+：按 D 结论逐项 A/B（C1、k 分负载、C2/block-k 视报告、C6a…），每窗单变量、带回退。
- 顺序原则：先归因（E1）→ 再基座（baked6）→ 后叠加优化；文本侧已验证的项（C1/SKIP）直接带默认进 VL。

## 6. Phase F 真实有效优化方案清单（目标④，滚动维护，随 D/E 结果更新）

已可预填（验证状态：✅已证 / ⏳A/B 待窗 / 📋报告待出）：

| 方案 | 机理 | 适用 | 预期 | 状态 |
|---|---|---|---|---|
| k 分负载调整（k=5 候选） | 削 verify/draft 尾部空转 | 0731 全负载，prose 最优 | +5~20%（依构成） | ⏳ B窗1 A/B |
| SKIP_MTP_COPY 1 字符修复 | 消每步 268MB@满批死拷贝 | 0731+VL | prefill 项小正 | ✅离线证，待上产 |
| C1 Markov 双复制 | 消 12 次/步串行跨机通信 | 0731+VL | +2~4% | ✅位级中性，待窗 |
| flashinfer main 重建（#4802） | calibrated-cpb+L2 warming+正式 TK512 | 0731+VL | decode 大项（社区 +26% 长上下文） | 📋 Agent K |
| C6a regret 控制器 | 累积亏损关投机，护最坏 0.96× | 0731+VL | 尾部保护 | 📋 Agent F |
| #54815 backport | RoPE/YaRN-SWA 正确性 | 长上下文（600K 生产） | 正确性非 perf | 📋 Agent R |
| block-k / C2 / C6b / W4A16 / 私有 CG sizes | 各报告定 | 各异 | 各报告定 | 📋 K/V/F/S |

## 7. 窗口需求总表（供排期）

| 窗 | 内容 | 时长 | 依赖 |
|---|---|---|---|
| B窗1 | V5b+k 三臂 A/B + SKIP 修复上产 | 90min | V5b 构建完成（无窗可先行） |
| B窗2(可选) | C1 叠加 A/B | 30min | B窗1 |
| B窗3(可选) | flashinfer main 文本侧 A/B | 45min | Agent K 结论 |
| E窗0 | E1 归因 | 30-40min | 无 |
| E窗1 | VL baked6 切换+W2 门 | 60min | Phase C + B 完成 |
| E窗2+ | VL 逐优化 A/B | 各 30-45min | D 结论 |

## 8. 风险与红线

- V5 是其他团队 09-04 后构建的资产：一切脚本/镜像改动留 .bak + md5 记录，live 脚本共享编辑前快照；两个 60MB 未知 commit 层**必须先鉴定**再 FROM。
- 生产 mmlen 已 600K：长上下文正确性暴露面上升，#54815/#55636 挂高优先观察。
- 探针纪律：并发 ≤5、总量 ≤2 万 token/轮、跑完即停（本轮已遵守）；本地分析全程 <1GB 内存。
- 所有重启走 guard；窗口动作顺序与回退链按 §2/§5 执行。
