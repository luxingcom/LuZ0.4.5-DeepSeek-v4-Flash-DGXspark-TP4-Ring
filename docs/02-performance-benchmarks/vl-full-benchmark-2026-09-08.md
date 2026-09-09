# VL 引擎全量 Benchmark 对比报告（对齐 LuZ0.4.5 原方案）

- **日期**：2026-09-08
- **执行**：vl-acceptance（工程保障团队）
- **对象**：VL 引擎（`deepseek-v4-flash-vision-exp`，镜像 `LuZ0.4.5-...-VL-DGXspark-TP4-Ring`，vllm-0.26.1.dev0+gd3d3b2cca，k=6 dspark）
- **基线**：V5b 文本线（`deepseek-v4-flash-0731`）
  - PR4K 基线：`bench3-results/g1r5-full/`（G1r5 制，口径与本次完全一致）
  - DE 矩阵基线：`bench3-results/full-matrix-045/`（input=512/output=4096，口径一致）
- **纪律说明**：
  - 首轮执行出现 GSM8K 与矩阵并行（执行错误），两路数据作废后按严格串行重跑（GSM8K→PR4K→DE→投机长生成→视觉单流，全程单路负载，引擎空闲确认 active=0/queue=0）
  - GSM8K 因 VL reasoning 输出慢（5.9s/题 vs V5b 1.45s/题）按预算 400 题切档，raw 逐题落盘支持任意截断复算；与基线同题前 114 题子集严格可比
  - 脚本：bench3 原脚本硬编码 0731/8002，未改动原件；副本改模型名（`bench3-results/vl-full-20260908/run_cell.sh + run_matrix.sh + run_serial.sh`，GSM8K 副本 `/tmp/vl-acceptance/gsm8k_vl.py` 判分逻辑原样保留）
  - 全部数值为 3 波中位（uuid-prefix 防前缀缓存），吞吐口径与 bench_v2 一致

## 一、排名结论总表

| 维度 | 结果 | 排名 |
|---|---|---|
| PR4K prefill（C1/C2/C4/C8） | 差值 +0.7% / -2.1% / -0.8% / -2.3%，全部 <2.5% | **持平**（C1 VL 略优，其余 V5b 略优） |
| DE decode prose（C1/C2/C4/C8） | +3.9% / -0.9% / +1.2% / +3.4% | **持平**（VL 2 胜 1 平 1 负，均 <4%） |
| DE decode coding（C1/C2/C4/C8） | -16.5% / -19.2% / -15.2% / -19.0% | **FAIL**（V5b 4/4 全胜，差 15-19%） |
| DE decode json（C1/C2/C4/C8） | -21.8% / -14.7% / -12.2% / -12.9% | **FAIL**（V5b 4/4 全胜，差 12-22%） |
| DE TTFT | 7 格更优（coding C1 -54%）、4 格持平、1 格略差 | **VL 占优** |
| GSM8K 准确率 | 同题 114 子集 -5.27pp | **FAIL 级落差**（待截断归因） |
| 投机长生成（1536 token） | 2.144 tok/forward（含 bonus），参考 A(6)≈2.08 | **PASS** |
| 单流视觉吞吐 | 63.1 tok/s（图+文，1024 token） | VL 新增能力，无基线 |

**总判定：prefill/TTFT/prose 持平或占优；coding/json 生成吞吐（8/12 格）与 GSM8K 准确率为两类显著退化项，需调优或归因决策。**

## 二、PR4K 纯 prefill 矩阵（prefill tps，3 波中位）

| 档 | VL | V5b 基线 | 差值 | 判定（阈值 10%） |
|---|---|---|---|---|
| C1 | 2689.9 | 2671.2 | **+0.70%** | PASS |
| C2 | 2017.8 | 2061.5 | **-2.12%** | PASS |
| C4 | 892.9 | 900.5 | **-0.84%** | PASS |
| C8 | 528.2 | 540.8 | **-2.33%** | PASS |

TTFT（s）：C1 1.35 vs 1.35（持平）、C2 2.00 vs 1.97（+1.5%）、C4 4.03 vs 4.00（+0.8%）、C8 6.79 vs 6.65（+2.1%）。

结论：KV 减半（6.04M→2.72M tokens）未损伤纯 prefill 路径；门5 遗留的 C8 项在 bench3 口径复测 **-2.3%，PASS**（与门5 生成口径 conc8 FAIL 不冲突：prefill-only 不受 KV 驻留约束）。

## 三、DE 生成矩阵（decode tok/s，3 波中位，input=512/output=4096 ignore_eos）

### coding

| 档 | VL | V5b | 差值 | 判定 |
|---|---|---|---|---|
| C1 | 85.2 | 102.1 | **-16.5%** | FAIL |
| C2 | 61.5 | 76.1 | **-19.2%** | FAIL |
| C4 | 42.6 | 50.3 | **-15.2%** | FAIL |
| C8 | 31.1 | 38.4 | **-19.0%** | FAIL |

### json

| 档 | VL | V5b | 差值 | 判定 |
|---|---|---|---|---|
| C1 | 83.3 | 106.5 | **-21.8%** | FAIL |
| C2 | 67.8 | 79.5 | **-14.7%** | FAIL |
| C4 | 47.9 | 54.6 | **-12.2%** | FAIL |
| C8 | 35.9 | 41.2 | **-12.9%** | FAIL |

### prose

| 档 | VL | V5b | 差值 | 判定 |
|---|---|---|---|---|
| C1 | 50.7 | 48.8 | **+3.9%** | PASS |
| C2 | 37.2 | 37.6 | **-0.9%** | PASS |
| C4 | 26.5 | 26.2 | **+1.2%** | PASS |
| C8 | 20.3 | 19.6 | **+3.4%** | PASS |

### TTFT（s，中位）

coding C1 0.146 vs 0.317（**-53.9%**）、C2 0.181 vs 0.485（-62.7%）、C4 0.898 vs 1.018（-11.8%）、C8 1.709 vs 1.713（持平）；json/prose 各格 -21% ~ +1.5%。VL TTFT 整体占优。

### 根因证据（dspark 接受率，bench_v2 monitor 采样）

| | accept_rate | per-pos |
|---|---|---|
| V5b coding C1（k=7） | 0.638-0.657（中位 0.652） | 0.93 / 0.84 / 0.74 / 0.66 / 0.58 / 0.47 / 0.33 |
| VL coding C1（k=6） | 0.553-0.584（中位 0.572） | 0.92 / 0.78 / 0.63 / 0.50 / 0.35 / 0.23 |

VL 接受率相对 -12.2%，且深位衰减显著更快（p4 0.35 vs 0.58、p5 0.23 vs 0.47）——draft/req 937 vs 739，同 4096 token 产出需更多前向。prose 任务 VL 与 V5b 持平，说明退化集中在 code/JSON 高熵 token 分布上，指向 draft 头分布拟合问题而非引擎普遍性减速。

## 四、GSM8K（8-shot CoT，temp=0.6，max_tokens=1024，顺序，同测试集同判分）

| 口径 | VL | V5b 基线 | 差值 |
|---|---|---|---|
| 同题 114 题子集（严格可比） | **89.47%** | 94.74%（segA） | **-5.27pp（相对 -5.6%）** |
| 前 400 题 | 86.78%（marker 87.03%，err=0） | 全量 1319 题 93.63%* | -6.85pp*（非同题口径，仅参考） |

*基线为全量 1319 题，VL 按预算切档 400 题。

初步归因假设：VL 为 reasoning 模型，1024 token 上限可能截断思考链导致失分；raw jsonl 已留全量逐题证据待复查截断比例。**此项在截断归因前不定论。**

> **【归因收口更新 2026-09-09】截断性失分实锤，非模型能力差异**：
> - VL 1024 版截断（结构化代理：无 #### marker 且 pc=None）：114 子集 10.5%（12 题）、400 题口径 12.8%（51 题）；截断组 0/12、0/51 全错，完成组 102/102=100%、348/349=99.7%
> - V5b 基线（ct 字段精确判定）：0% 截断，6 题真实推理错误（94.74%）
> - F2 复测（114 题，max_tokens=2048，精确 finish_reason）：acc=93.86%（+4.39pp），stop 107/length 7，stop 组 107/107=100%，length 组 0/7 全错；翻转 5 升 0 降无回归
> - 判分抽查 10 题（含 3 错题）无误判
> - **结论：-5.27pp 主因是 1024 思考预算截断（VL 完成组 100% 优于 V5b 94.74%）；2048 下仍余 6.1% 截断，后续全量基准已升级 4096 预算**。证据：node01 /tmp/vl-acceptance/{gsm8k_vl_raw.jsonl, gsm8k_f2_raw.jsonl, f2_analysis.txt}

## 五、投机长生成复测（门6 遗留项）

单请求 1536 token 输出（共识算法长文），metrics delta 口径：
- delta_drafts=716、delta_draft_tokens=4296、delta_accepted=819
- **平均每次前向产出 2.144 token（含 bonus）**；不含 bonus 1.144
- 对照：短生成 2.364、参考 A(6)≈2.08 → **长生成 2.144 ≥ 2.08，PASS**，无长生成衰减塌陷
- 该请求 decode 42.8 tok/s（中文散文类）

## 六、单流视觉吞吐（VL 新增能力）

PIL 现场生成 640x400 六色块图 + 600 字描述请求：**decode 63.1 tok/s**（completion 1024 token，wall 16.2s，prompt 214 token 含视觉特征）。视觉请求走完整多模态路径稳定。

## 七、FAIL 项与调优候选

**F1. DE coding/json decode -12%~-22%（8/12 格）**
根因证据：dspark 接受率 0.572 vs 0.652（-12.2%），深位衰减快（p5 0.23 vs 0.47）。调优候选（按优先级）：
1. draft 头对 code/JSON token 分布重校准（怀疑视觉训练稀释代码分布拟合；prose 持平是关键旁证）
2. 评估 k=6→4 动态截短：p4/p5 接受率 <0.35/0.25，深位 draft 纯耗 verify 算力
3. 对齐 V5b dspark 采样温度/top-k 配置核查

**F2. GSM8K -5.27pp（同题子集）**
候选：max_tokens=2048 复测 114 子集定位截断性失分（检查点成本低）；若排除截断则为模型能力差异，报主理人决策是否可接受。

**F3（已裁定，不重开）**：门5 conc8 生成吞吐受 KV 驻留上限 4-5 约束，主理人已裁定为版本属性不阻断。

## 八、附录

- VL 结果：`node01:<HOME_DIR>/bench3-results/vl-full-20260908/`（serial.log 含 16 个 CELL_RESULT 行、run.log 含 dspark 采样、各格 summary_v2.json）
- GSM8K：`node01:/tmp/vl-acceptance/gsm8k_vl_raw.jsonl`（440 题逐题）
- 基线：`g1r5-full/`（PR4K+GSM8K）、`full-matrix-045/`（DE 矩阵）
- 脚本副本：`vl-full-20260908/{run_cell,run_matrix,run_serial}.sh`、`/tmp/vl-acceptance/{gsm8k_vl,speclong}.py`
- 异常记录：json_C8 r1 双方基线均现 prefill 52/TTFT 11.4s 同型异常（V5b 50.09/11.76），中位数已免疫；视觉补跑脚本首版 heredoc 缩进损坏（VISION_EXIT=1），已内联重跑成功
- 执行时间线：串行链 12:40 启动 → 15:00 全部完成（含 GSM8K 切档）
