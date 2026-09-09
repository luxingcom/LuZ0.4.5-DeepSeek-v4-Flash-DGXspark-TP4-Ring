# G1R7-VL 窗口#2 报告 — 遗留清单处置定谳（2026-09-08）

承接 `G1R7VL-WINDOW-REPORT-20260907.md` §7 遗留清单。本窗口将四项遗留全部处置完毕，
生产已恢复 V5b 基线（k=7、C1 关、health=200），恢复后在线完成 needle 长上下文补测。

## 0. 一句话总览

| 遗留项 | 结论 |
|---|---|
| baked6 boot IMA 二分 | **定位收窄完成**：eager 模式全绿 → IMA 在 CUDA graph 捕获路径；baked6+0731 文本形态健康 → **视觉特异性**。全图修复转专项（嫌疑集：#4973 族 / V5 NCCL cap-snap × VL FULL 捕获） |
| E1 视觉 -27.7% 归因 | **部署侧无罪**（同 eager 口径 Δ=0.6ms ≤ 3ms 门）；根因=投机税 × 检查点 draft-head 接受率 |
| C1 Markov 替换 | **并发回归实锤，否决**：conc4 -13~15%、conc8 -19~21%。生产 env 门保持 OFF |
| needle 500K 补测 | **4/4 内容全中**（含 500K 中位/尾部两位置）。#54815 rope 修复 needle 证据链闭合 |
| PIECEWISE 备选 | 发现**独立形状 bug** `[84,-1,64,128]` vs 720896（84 vs 88 图像哨兵计数，G1r6 代 runner），另列修复项 |

## 1. 重启序列（guard 全程 flock，六次引导）

| # | 形态 | 结果 |
|---|---|---|
| 在线 | V5b 基线 C1-off 并发基线（不重启） | conc4 88.3/91.0、conc8 130.5/129.2 tok/s |
| A | baked6+VL + enforce-eager（k7 投机保留） | READY，W2 五门禁全绿（见 §2） |
| B | baked6+VL + PIECEWISE 图模式 | 启动失败：形状 bug（见 §3，独立问题） |
| C | baked6 + 0731 权重 + eager + spec-off | READY，text-eager 60.7ms |
| D | baked6 + vision 权重 + eager + spec-off | READY，vision-eager 61.3ms |
| E | V5b + k7 + C1-on | READY，C1 并发数据（见 §5） |
| F | 恢复生产基线（.bak-window-20260907 脚本，k7 无 C1） | READY health=200，guard 04:29:34 释放锁 |

本地结果文件时间戳（`~/w6-logs/g1r7-tune-20260907/`）：03:32 基线 → 03:40 W2 门禁 → 04:10 text-eager → 04:15 vision-eager → 04:22-23 C1-on → 恢复 → 04:38 needle。

## 2. Boot A — baked6 eager 存活 + 五门禁全绿（IMA 定位关键证据）

baked6+VL 在 `--enforce-eager` 下正常起服并通过全部功能门禁（`w2_gates_eager.json`）：

- g1 单图描述：「深红色」✅（16.9s）
- g2 四图计数：「红色，蓝色，绿色，黄色」✅（11.7s）
- g3 跨图跨度：「红色和蓝色。」✅（10.9s）
- g4 GSM8K 算术：$5 ✅（答案链完整）
- g5（投机形态）：接受率正常

**推论**：VL 权重加载、mm preprocessor、视觉塔前向、投机链在 eager 下全部工作正常
→ 窗口#1 的 rank1 IMA（图捕获期 NCCL cap-snap 后 watchdog）发生在 **CUDA graph 捕获路径**，
不是权重/数据/模板层问题。

## 3. Boot B — PIECEWISE 独立形状 bug（deferred）

`--enforce-eager` 关掉后尝试 PIECEWISE 图模式（full-graph 之外的折中），
启动崩溃：

```
RuntimeError: shape '[84, -1, 64, 128]' is invalid for input of size 720896
```

720896 / 64 / 128 = 88，但 reshape 目标首维 84 —— **84 vs 88 = 图像哨兵 token 计数错配**，
属 G1r6 世代 gpu_model_runner 的 PIECEWISE 视觉 padding 缺陷，与 FULL-graph IMA **不是同一问题**。
不阻塞主二分结论，另列修复项（见 §7 backlog）。

## 4. E1 归因闭合 — 部署侧无罪（同 eager 口径双臂）

窗口#1 遗留问题：两种形态的 29.1ms（graph）不可比，需要同口径。本窗口双臂均 eager + spec-off：

| 臂 | 样本 ITL 中位 (ms) | 汇总 |
|---|---|---|
| baked6 + 0731 文本 | 60.54 / 60.91 | **60.7** |
| baked6 + vision | 61.06 / 61.57 | **61.3** |

**Δ = 0.6ms ≤ 3ms 判定门 → 部署侧（VL 权重/mm 链路/视觉塔）无罪。**

vision 线上 -27.7% 的根因确认为**投机税 × 检查点 draft-head 接受率交互**（vision 检查点的
draft head 对文本任务接受率更低），与部署实现无关。后续增益路径在 draft-head 微调，
不在部署链。

附：text graph 29.1ms vs text eager 60.7ms → eager 惩罚 ≈ -31.6ms（-52%），坐实
eager 不能作为生产形态，也解释了为何 baked6 上生产必须先修 FULL-graph IMA。

## 5. C1 终审 — 并发回归，否决

窗口#1 已证 C1 单流无收益（k5 48.1 → k5+C1 49.4ms）。本窗口补并发臂（各 2 轮，320-token 探针）：

| 场景 | C1-off (tok/s) | C1-on (tok/s) | Δ |
|---|---|---|---|
| conc4 | 88.3 / 91.0 | 76.9 / 77.8 | **-13~15%** |
| conc8 | 130.5 / 129.2 | 106.0 / 101.5 | **-19~21%** |

机制解释成立：C1 Markov 替换省下的通信量 < 全表复制的额外带宽，且并发越高带宽压力越大回归越深。
线上比特中性 + GSM8K 10/10 已证无害，但**无收益且并发负** → 生产 `VLLM_DSPARK_MARKOV_REPL` 门保持 OFF，
C1 从"观察项"改判"否决项"归档。

## 6. needle 长上下文补测 — 4/4 全中（#54815 证据闭合）

生产恢复后在线执行（8001 入口，k=7，内容抓取验证），`needle_final.json`：

| 长度 | 暗号位置 | 延迟 | 内容命中 |
|---|---|---|---|
| 30K | 50% | 11.1s | ✅ 青竹-7 |
| 128K | 50% | 47.3s | ✅ 云杉-3 |
| 500K | 50% | 260.0s | ✅ 星岩-9 |
| 500K | 90% | 173.2s | ✅ 星岩-9 |

窗口#1 的 500K 240s 超时确认为超时预算不足（实际需 ~260s）。中位+尾部双位置命中
→ **A2（#54815 rope 修复，SWA 层 `apply_yarn_scaling=False`）的长上下文 needle 证据链闭合**，
此前 30K/128K 仅延迟验证的欠账一并结清。

## 7. 更新后 backlog（移交下一窗口/专项）

| 项 | 状态 | 入口 |
|---|---|---|
| baked6 FULL-graph IMA 修复 | 专项（VL 上生产唯一阻塞） | WINDOW-REPORT §5 取证入口 + 本报告 §2 收窄（capture path、视觉特异、嫌疑集 #4973 族 / V5 NCCL cap-snap × VL FULL 捕获交互） |
| PIECEWISE 84vs88 形状 bug | 独立修复项 | G1r6 代 gpu_model_runner PIECEWISE 视觉 padding；修好前 VL 图模式只剩 FULL（IMA）与 eager（-52%）两档 |
| F1 flashinfer main A/B（pin 453aa7c） | B窗3 候选 | K 组报告 D-k |
| VL 生产上线决策 | 等 IMA 修复 | baked6 镜像 + 四节点 .b6/.b6ee/.b6d 脚本在位，随时可测 |
| 8001 长 prompt 准入控制 | 旧待办 | W9-R8 |

## 8. 本窗口资产

- 结果数据：`~/w6-logs/g1r7-tune-20260907/{w2_gates_eager,e1_text_eager_results,e1_vision_eager_results,base_c1off_conc*,c1on_conc*,needle_final}.json`
- 脚本变体（四节点 `~/w6-kit/`，均 md5 验证）：`.b6ee`（boot A）、`.b6pw`（boot B）、`.b6c`（boot C）、`.b6d`（boot D）、`.k7c1`（boot E）、`.bak-window-20260907`（生产基线档）
- 生产现状：V5b 基线 k=7、C1 OFF、health=200，恢复后已在线承载 needle 全部流量

---

## ⚠ 勘误（2026-09-08 窗口#3）

§0 表"PIECEWISE 84vs88 = 图像哨兵计数（G1r6 代 runner 视觉 padding）"解读**有误**。真实根因：
.b6pw 变体 k=6 → decode_query_len=7 → warmup decode 批 12×7=84 tokens 被 PIECEWISE 补到 capture
桶 88，`split_decodes_and_prefills` 均匀快路径把补过的 num_actual_tokens 当 num_decode_tokens
返回，`sparse_attn_indexer.py:544` 的 reshape（batch×next_n 不变量）被破坏。与视觉无关
（k=7 时 12×8=96 恰为桶顶，生产未触发纯靠桶表覆盖）。修复=b7-fix（见
`G1R7VL-WINDOW3-REPORT-20260908.md` §4）；boot B 的 next_n=7 日志即为 k=6 所致。
