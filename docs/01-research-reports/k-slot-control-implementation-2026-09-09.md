# K 槽位控制（draft slot control）实现路径调研 — 代码级方案

日期：2026-09-09 ｜ 调研人：Cody（代码审查师，工程保障团队）｜ 性质：本地代码 + 网络调研，**零接触生产、未 SSH、未改服务器**
目标：保持引擎合法声明（k=6 过 pydantic 整除校验），每步只验证前 N 个 draft 槽位（N=3/4/5），供 A/B 逐个测试。
产出：给 lead 审查 / SRE 落地执行 / 评审 A/B 合并窗口。

---

## 0. TL;DR

- **短期（不重建镜像）只能测 N=3（=k=3，方案 A）与 k=6 基线。N=4/5（方案 B）必须重建镜像，本期不做。**
- 方案 A 零代码、零重建、立即可测；方案 B 在 fork 的 FULL CUDA Graph 形态下**必然撞图 → 性能崩 → 且跨多文件改 Python 必须重建镜像**，短期不可落地。
- 根因（已实锤）：fork `FULL_AND_PIECEWISE` 下 DSpark propose 的 CUDA graph 按 `num_speculative_tokens=6` **静态捕获**（vLLM DSpark 实现原文），运行时把每步 draft 数从 6 降到 N 会改变 graph shape → FULL graph miss → 回退 eager/PIECEWISE（性能塌陷）。

---

## 1. 判定卡

| 问题 | 判定 | 证据链 |
|---|---|---|
| 方案 A（k=3）是否零代码可测？ | **是** | `num_speculative_tokens=3` 是被 3 整除的合法值（k∈{3,6,9}）；纯配置改启动脚本；k3 A/B 框架已就绪（k3-thr-ab-analysis）。Community 同 checkpoint 同硬件 k=3 净赢（forums 381911/44）。 |
| 方案 B（声明 k=6，每步取前 N=4/5）是否撞 CUDA graph？ | **是（撞）** | fork cudagraph_mode=FULL_AND_PIECEWISE；DSpark propose 全图单次捕获（#46995 "capture the full DFlash backbone and autoregressive sampling loop in a single graph"）；graph shape=f(B×(1+6))，运行时 6→N 改变 shape → FULL miss → eager/PW fallback。 |
| 方案 B 是否必须重建镜像？ | **是** | fork dspark.py 与 vllm/v1/spec_decode 均在容器镜像内；VL 镜像 12.88GB，改 Python 需 rebuild + 四机 digest 同步（不确认 fork 支持 site-packages 热覆盖）。叠加 #45953（DSD+FULL CG 兼容）fork 基座不确认含。 |
| N=4/5 是否天然合法？ | **否** | 必须是 3 的倍数；4/5 在 dspark block（3 层/轮）上会产生残块，propose 循环截短非最小改动。 |
| 保持 6 捕获、仅验证侧截短（c 层）可否不撞图？ | **图不撞，但需多文件改 + 重建镜像** | graph shape 恒为 f(B×7) 不 miss；但改 SpecDecodeMetadata.num_draft_tokens + rejection sampler 变长消费 + SRE 重打包。且 fork **无置信头**（dspark.py L491-493 显式丢弃 confidence_head weight）→ 只能无置信的静态硬截（= 白跑 propose 尾部槽，收益极有限）。 |

**专项结论（给 lead 的关键判定）**：方案 B 必须重建镜像 → 短期测不了 N=4/5，只能测 N=3（=k=3）与 k=6 基线。

---

## 2. 方案 A/B 对比表

| 维度 | 方案 A：k=3 | 方案 B：槽位 cap N（N=4/5） |
|---|---|---|
| 形态 | 声明 k=3（合法，=强制 1 轮 3 槽） | 声明 k=6（过校验）+ 每步把 num_draft_tokens 截到 min(N, 可用) |
| 改动点 | 启动脚本 `--speculative-config` 的 `num_speculative_tokens: 6→3`（start_tp4_head_v043.sh L72 同形字符串） | fork `vllm/v1/spec_decode/` 多文件：dspark/DSpark proposer propose 循环上界 + `SpecDecodeMetadata.num_draft_tokens` 计算 + rejection sampler 变长消费；引入 `VLLM_DSPARK_SLOT_CAP=N` env 门控 |
| 是否撞 CUDA graph | **否**（k=3 是合法静态值，graph 按 3 捕获，`12×(3+1)=48≤96` 容量无忧） | **是**：6→N 改变 graph shape → FULL miss → eager/PW fallback 性能崩；除非保持 6 捕获仅验证侧截短（则 propose 白跑尾部） |
| 是否需重建镜像 | **否（零代码）** | **是**（约 12.88GB VL 镜像 + 四机 digest 同步；fork 无热补丁确认） |
| 可测槽位档 | **N=3 立即测**；N=6（基线）对照 | N=4/5 理论上可，但**短期不可行**（重建+撞图）；实际等价兜底形态 = 保持 6 捕获仅验证侧硬截（收益有限） |
| 无损性 | **是**（rejection sampling 对任意 k 分布等价） | **是**（拒绝尾槽=白送不算账；无置信静态 cap 仍无损） |
| prose 接受长度上限 | ≤4（3 draft + 1 bonus） | N=4 → ≤5；N=5 → ≤6 |
| 风险 | 低（纯配置，CV 框架已就绪） | 高：撞图性能塌陷 + 跨文件改动 + 镜像重建运维 + N 非 3 倍数残块兜底逻辑 |

---

## 3. 推荐路径

1. **短期（本窗口，立即）**：方案 A，k=6→3 单变量 A/B（复用 k3-thr-ab-analysis 的 C 臂框架与判定门槛：coding DE ≥+8% / json ≥+8% / prose ≥-2% / GSM8K ≤0.3pp / TTFT 无劣化）。这是唯一零代码零重建能覆盖的"少槽位"档。社区同 checkpoint 同硬件 k=3 净赢为先验。
2. **中期（若需 N=4/5 细粒度）**：单独排重建镜像窗口，评估方案 B——优先参考 #45953（DSD+FULL CG capture-all-shapes）+ 静态 cap（=#44336 的 min(adaptive_k, num_spec_tokens) 静态化），验证侧截短形态保持 graph shape 不变最稳。**需 SRE 排期镜像重建 + #45953 移植状态核实**。
3. **长期（production 形态）**：移植 #47808 自适应验证（置信 top-B）替代人为静态 cap，但 fork 无置信头（dspark.py L491-493），需先补 confidence head 接线——列为独立工程。

---

## 4. 风险标注

- **P0（方案 B 短期执行拦截）**：FULL CUDA graph 撞车 = 每步 shape 变化 → eager/PW fallback → 吞吐塌陷；且必须重建镜像。**短期禁跑方案 B**。
- **P1**：N=4/5 非 3 倍数，dspark 3 层 block 的 propose 循环截短存在残块边界，验证侧消费逻辑需兜底，改动面大。
- **P1**：fork DSpark 无置信头 → 验证侧只能"无打分硬截"，propose 尾部槽位白跑（compute 不省），cap 收益主要只在验证矩阵变小，需以基准证伪。
- **P2**：方案 A 的 prose 接受上限降为 4；bench_v2 的 per-pos 指标（position=0..4 正则）在 k=3（≤2）下口径变化，对照需同脚本重测。
- **P2**：fork 是否含 #45953 未在本地源码树核实（本地无完整 vllm 包），若做方案 B 需先服务器 grep `vllm/v1/spec_decode/` 确认。

---

## 5. 诚实空白（fork 行号确认）

- fork 的 propose 循环上界、`num_draft_tokens` 计算的确切**函数名/行号在 vllm 包本体，本地无完整源码树**（fork 仅归档 dspark.py 模型文件与硬件补丁）。方案 B 具体改哪几行需 SRE 服务器侧 `grep -rn "num_draft_tokens\|num_speculative_tokens" /path/to/vllm/v1/spec_decode/` 确认。
- 已确认：fork `dspark.py`（本地副本）L491-493 显式丢弃 `confidence_head.*` 权重（"not wired into inference yet"）→ **fork 无置信头接线**【实锤·本地代码】。

---

## 6. 执行步骤（给 SRE 用，方案 A 短期）

```
# 1) 前置会签（lead）
确认走方案 A（k=3），锁定窗口；读 k3-thr-ab-analysis 判定门槛。

# 2) head 启动参数单变量改动（四机同步）
start_tp4_head_v043.sh，--speculative-config 改：
  {"method":"dspark","num_speculative_tokens":3,"draft_sample_method":"probabilistic"}
其余参数不动（max-num-seqs=12 / bsz=4096 / 2200 制 / FULL_AND_PIECEWISE）。

# 3) 采集（同 k3-thr-ab-analysis 协议：3 波中位、冷口径 uuid、同负载）
- A 臂 = 本报告 §3 基线（k=6+thr2048 已提取）
- C 臂(k=3) 采集 DE/coding|json|prose + PR + TTFT + GSM8K + spec 指标
- speclong.py 记录 accept_len（k=3 理论上限 ≤4）
- CV：k=3 逐位分布重测（同脚本同负载，禁跨源直比）

# 4) 判定（门槛不可事后修改）
coding DE ≥+8% 且 json ≥+8%，prose ≥-2%，GSM8K ≤0.3pp，TTFT 无劣化 → 晋级

# 5) 回退
回退 = 改回 num_speculative_tokens:6 + 四机同步重启（guard v3 链既有的 flock/stop/start/health 流程）。
```

---

*调研完成。方案 B（N=4/5）短期判定为不可行（撞 FULL CG + 必须重建镜像），本期唯一可落地的"少槽位"测试为方案 A（k=3）。*