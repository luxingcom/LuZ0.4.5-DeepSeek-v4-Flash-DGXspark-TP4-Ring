# G2 开臂前置清单（Go / No-Go）

日期：2026-09-10 ｜ 编制：Cody（代码审查师）｜ 性质：**只读设计文档，未 SSH、未碰生产、未写补丁**
上位：`g2-preflight-ab-design-2026-09-10.md`（对拍方案 v1.1）｜ 镜像：tag `…VL-S1-20260910b`，digest `sha256:<BAKE_IMAGE_DIGEST>`（四机一致）
定位：**开 G2 主窗（CONF_MIN 单请求对拍）之前的最后一道就绪闸**。本清单**不重复**对拍方法，只回答「现在能不能开臂」。
关联证据源：`accept-rate-cheat-detection-2026-09-10.md`、`non-anticipating-check-2026-09-10.md`、`conf-min-calibration-research-2026-09-10.md`、`g2-preflight-ab-design-2026-09-10.md`、`g1g4-evidence-checklist-2026-09-10.md`。

**状态标记**：✅ 已就绪 ｜ ⚠️ 部分就绪 / 未启用（不阻断但须记录） ｜ 🚨 未就绪（阻断开臂）

---

## 0. TL;DR

**当前判定：NO-GO（4 项 🚨 阻断 + 1 项前置依赖）**。全部为**开臂前可离线/短窗补齐**，无不可解项：
1. 🚨 **P1** `[S1-DIAG]` 日志补丁**只是归档、未并入 b' 镜像**（F2/F3/F9 无出口 → 对拍三根支柱缺两根）；
2. 🚨 **P2** CONF_MIN 三档扫描脚本 + 采集口径**未就绪**（无脚本、无 per-pos 抽取器）；
3. 🚨 **P3** position 语义核对（S1-S4）**未执行**——S3（`ΔA_i` 单调不增）未钉死前，D3/D4 **整条作废**；
4. 🚨 **P4** lag 断言（`used_step − conf_step ≥ 1`）**未实测**。

> **◀ 前置依赖（非独立阻断）**：**P10（gate env 生效实锤）依赖 P1**。P10 的 (ii) 行为级实锤要求「gate-on 出现 `l_r<k` 帧」，而 `l_r` **只有 P1 的 `[S1-DIAG]` 打点才输出** → **P1 不补齐，P10 (ii) 根本无法执行**。故关系为 **`P1 → P10`（串行依赖）**，**不是** `P1 ∧ P10` 的并列合取；补齐顺序必须为：**P1 补丁 → Cody 复审 → rebuild 镜像 → 过 E0 元门 → 再跑 P10**。

> **编号口径统一以 §1 前置项表为准**：`P1=DIAG日志`、`P2=三档扫描`、`P3=position语义`、`P4=lag断言`、`P5=样本量`、`P6=D1/D2恒等式`、`P7=D1-D5采集点`、`P8=几何衰减带`、`P9=C9门`、`P10=env生效实锤`。**P1 与 P10 的区别**：P1 = "DIAG 补丁是否并入镜像"（工具层）；P10 = "gate env 是否真生效"（行为层）。

未阻断但必须随窗记录的 ⚠️：P5 样本量门、P6 D1/D2 脚本、P7 采集点接线、P8 几何衰减带（须用本负载 gate-off 臂**重标定**而非搬用六门值）、G2/G8 下期盲区。

---

## 1. 前置项表

> 每项：**前置条件 / 当前状态 / 证据来源 / 缺失时的后果 / 标记**

| # | 前置条件 | 当前状态 | 证据来源 | 缺失时的后果 | 标记 |
|---|---|---|---|---|---|
| **P1** | **`[S1-DIAG]` 日志补丁已并入镜像并启用**（F2 `_conf_lengths_frame` / F3 `scheduled_spec_decode_tokens` 长度 / F9 `num_invalid_spec_tokens`） | **仅归档，未启用**：方案 §3.1 三条打点尚在 source 侧，未编入 `20260910b`。当前镜像内**无**这些 debug 出口 | `g2-preflight-ab-design §3.1`；`VLLM_DSPARK_CONF_DIAG` env 未设 | **对拍三根支柱缺两根**：无 F2 则「l_r 生效」无证据、无 F3 则「F2==F3」恒真而无法判、无 F9 则 async guard 记账不可核。**只剩 F1 序列 + F5/F6/F7 指标**，无法定谳 P0-2 | 🚨 |
| **P2** | **CONF_MIN 三档扫描（0.05 / 0.1 / 0.2）脚本就绪 + 采集口径确定** | **未就绪**：无三档循环脚本、无 per-position 抽取器（`spec_decode_num_accepted_tokens_per_pos_total{position="i"}` 抽取未封装）。口径**已定**于 conf-min 报告 §2.3 收敛框（作用在 survival 累积乘积）+ accept-rate 报告 §5.6（同 run 同 engine label、冷口径、Δ 非累计） | `conf-min-calibration §4.2`（三档来源）、`accept-rate-cheat §5.6 B.1`（口径） | 无三档则**无法做 D3 边界漂移**（回顾性接纳的一次性铁证）；且 L3 扫描层整层缺失 | 🚨 |
| **P3** | **position 语义核对（S1-S4 四步）已执行，S3 = `ΔA_i` 单调不增为核心判据** | **未执行**：方法已给（accept-rate 报告 §5.5），但**未在真实数据上跑过**；当前仅按「暂定槽位语义」 | `accept-rate-cheat §5.5`（S1-S4 表） | **S3 未钉死 → D3/D4 分母 `O_i` 无意义 → D3/D4 整条作废**；若实为「第 i 个被接受 token」语义，则 `r_i=A_i/O_i` 崩塌 | 🚨 |
| **P4** | **stale 步数实证**：`used_step − conf_step ≥ 1`（lag 断言） | **未实测**：源码静态倾向满足（`get_stale_confidences` 取 `_conf_step−1`），但 **async 路径可能 2 拍、需实证** | `non-anticipating §4.3 R1/§5 C7`（**第一优先检查项**） | lag=0 → **直接违反 non-anticipating** → 正确性根基因失效。本窗**必须**跑通该断言，否则 NO-GO | 🚨 |
| **P5** | **样本量下限**：待判位置 `O_i ≥ 2000`（建议 3000-4000）+ ≥3 波独立重复 + 抽样脚本 | **有方法、无脚本**：按 D3 可检性反推（δ=20% → O_i≈1760），安全系数 1.5-2× → 3000-4000；3 波中位 + 极差作噪声带。抽样脚本未落地 | `accept-rate-cheat §4.2`（表格）、`§5.2`（3 波中位） | O_i<2000 → 该位 D3 **降级为参考**，不得据此单独定案；低并发下深位 O_i 天然不足（CONF_MIN 越大越缺） | ⚠️ |
| **P6** | **D1/D2 恒等式采集**（含 `Σper-pos`、`accept_len`、`ΣA+D`、`R` 四个量的复算脚本） | **公式已钉死、脚本未落地**：D1 `accepted+drafts==completion`；D2 `accept_len==completion/drafts−1`；自洽 `Σper-pos A_i == accepted_total`；`R==k/accept_len`（代数冗余，**不列独立判据**） | `accept-rate-cheat §2.1/§2.6/§5.6`；六门实测 Σ=5191 ✓ | 缺 D1/D2 → 失去**零成本、不依赖样本量的硬门**（L1 先验层全空），只剩需两臂的形状判据 | ⚠️ |
| **P7** | **接受率作弊判别量 D1-D5 采集点 + 预期值域** | **方法已定、采集点已列，未接线** | `accept-rate-cheat §0 表 / §2`（D1-D5 定义与预期） | 见 P6/P3；D5 需两臂同载荷冷口径 | ⚠️ |
| **P8** | **几何衰减带写入放行条件**：`r_{i+1}/r_i ∈ [0.50, 0.68]`（六门实测 0.5259-0.6323），越界判阈 **>0.70**；等效几何比 **0.5726**（log σ=0.0929） | **数值已核验**，但**须用本负载 gate-off 臂重标定**，不可跨负载搬用 | `accept-rate-cheat §0.5`（六门比值 + 独立复算一致） | 直接搬用六门带 → 负载相关会误判（来源①短答案 vs 来源②热态 vision 形状不同）；须本窗 gate-off 臂重算带 | ⚠️ |
| **P9** | **C9 一锤定音门**：贪心(temperature=0) 同 seed 同 prompt，gate-on 序列逐位 == gate-off | **方法就绪**（属对拍方案 F1）；**seed 固定为硬前置**（见 G3） | `non-anticipating §5 C9`、`g2-preflight §0` | seed 未固定 → 假阳性 FAIL；序列不等 → 立即 FAIL，优先级高于一切 | ✅（方法）/ ⚠️（seed 须固定） |
| **P10** | **gate env 生效实锤（三选二）**：门控是否真被读取并产生行为差异——**①差分实锤**（gate-on/gate-off 行为差异）**②解析路径实锤**（env 被真正解析进 `_conf_gate`/`_conf_min`，而非被忽略/短路）**③反证实锤**（gate-off 侧反向排除：无截短、staging 单次行计数=0）；**健康 200 不算证据** | **未执行**：门控生效性尚未实证。**注意**：`confidence staging` 是 speculator **初始化单次 info 行**，与 `[S1-DIAG]` 同属"启动期不出现、需 `--since StartedAt` 口径"的证据 | **交叉引用（互引）**：`qa-program-conf-head-2026-09-10.md §2 G1-T2b`（**(i) 模块级** = staging `--since StartedAt` 双向计数：gate-off==0 且 gate-on≥1 且 n_spec==6；**(ii) 行为级** = gate-on 须有 gate-off 无的行为差异：`l_r<k` / num_new_tokens 收缩 / `[S1-DIAG]` 帧含 l_r<6）。**G1-T2b 搭本清单阶段 1/2 的车执行，不额外起停** | 仅"健康 200"或"模块级计数一致但无行为差异" → **判 env 未生效/接线死路，不得 PASS**；三选二缺项 → 生效性存疑 | 🚨 |

---

## 2. Go / No-Go 判定矩阵

**规则**：**全部阻断项满足（无 🚨）+ 前置依赖 P10 通过 → GO**；**任一 🚨 → NO-GO**，并给出最短补齐路径。**注意 P1 → P10 为串行依赖**（P10 的 `l_r` 出口来自 P1），须先补 P1 再验 P10。

| 场景 | 条件 | 判定 |
|---|---|---|
| **GO** | P1✅ ∧ P2✅ ∧ P3✅ ∧ P4✅ ∧（P5-P8 满足各自下限）∧ P9 seed 固定 ∧（**P1 完成后方可执行**）P10✅ | **开臂** |
| **NO-GO（当前）** | P1🚨 ∨ P2🚨 ∨ P3🚨 ∨ P4🚨（P10 因依赖 P1 亦不可执行） | **不开臂**，按下表补齐 |

**当前最短补齐路径（4 项 🚨，总预估 ≈ 1 个短窗 + 离线分析；P10 串行其后）**：

| 阻断项 | 最短补齐动作 | 负责线 | 预估 |
|---|---|---|---|
| **P1** `[S1-DIAG]` 未启用 | implementer-s1 在 `scheduler.py`/`speculator.py` 加三条 `[S1-DIAG]` debug 打点（**仅 `_conf_gate` 为真时输出**）→ 出补丁 → Cody 复审 → rebuild `20260910b'` → **落地判据 = 镜像内文件 md5 == 补丁后 md5**（E0-d 纪律；**不可用 boot grep `[S1-DIAG]`——该行须有请求经过 scheduler 才输出，boot 必为空**，见 §3 阶段 2.2 与 §4 R13/时间序纪律） | implementer-s1 + Cody | 补丁 + 复审 ≈ 半天；rebuild 并入既有窗 |
| **P2** 三档扫描脚本 | 写三档循环 + per-pos 抽取器（`position="i"` 0..5）+ 冷口径 uuid + 同 run Δ 差分；落 `deliverables/engineering-assurance/g2-preflight-ab/`（SRE 执行目录） | SRE（脚本）/ Cody（口径复审） | 脚本 ≈ 2h |
| **P3** position 语义核对 | 用 1 条已知输出请求（gate-off、贪心、prose 512 token）跑 S1-S4，**核心看 S3**：断言 `ΔA_0 ≥ ΔA_1 ≥ … ≥ ΔA_5`。若通过 → D3/D4 可用；若不通过 → 改 offered-count 重算 `O_i` | SRE 执行 / Cody 判定 | 短窗 ≈ 30min |
| **P4** lag 断言 | 随 P1 的 `[S1-DIAG]` 打点一起出 `conf_step`/`used_step`，断言差 ≥1 | implementer-s1 + SRE | 随 P1 |
| **P10** env 生效实锤 | **串行依赖 P1**：待 P1 补丁 rebuild 进镜像并使 `l_r` 出口可用后，按 §3 阶段 0.4（gate-off 反证）+ 2.2b（gate-on 模块级）+ 2.4（行为级 `l_r<6`）执行；交叉引用 `qa-program-conf-head-2026-09-10.md §2 G1-T2b` | SRE 执行 / Cody+Tessa 判定 | 搭阶段 1/2 的车，**不额外起停** |

**补齐后的复核**：P1 镜像 rebuild 走 `g1g4-evidence-checklist` 元门 E0（digest / StartedAt / 镜像内 md5 三件套），**E0 不过则 G2 结论作废**。

---

## 3. 开臂首小时执行序（命令级，含回退锚点）

> 前提：**Go 判定通过**（§2）。全部命令**仅在授权窗口内**由 SRE 执行；本文件只给序，不含凭证。`<rank0>` 均为 rank0 容器名（当前口径 `vllm-tp4-rank0`；8002 直连，**不用 8001 网关**——已知塌陷）。

> **⚠️ 日志判据时间序纪律（全章通用，追加 B(5)）**：本清单所有"日志中应/不应出现 X"的判据，**一律用 `docker logs --since <本容器 StartedAt>`**；**禁用全量 `docker logs`**（会混入上一轮残留，造成假通过/假失败）。每个日志判据执行前**先断言 `StartedAt` 晚于本次重启**，否则该判据作废。`StartedAt` 即阶段 0.1 采集并落盘的那个值，为后续**所有** `--since` 的唯一基准。

### 阶段 0 · 开臂前锚点（T+0，5 min）
```bash
# 0.1 记录「回退锚点」：当前镜像 digest + 容器 StartedAt（回滚时以此为准）
#     ★该 StartedAt 即后续【所有】--since 的唯一基准，必须首件事采集并落盘（缺失则本章全部日志判据失效）
docker inspect vllm-tp4-rank0 --format '{{.Image}} {{.State.StartedAt}}'   # 四机各跑
# 0.2 记录基线 metrics 全量快照（含 spec_decode_* 与 kv_cache_usage）
curl -s http://127.0.0.1:8002/metrics | grep -E 'spec_decode|kv_cache_usage' > /root/g2-snap-A-.metrics
# 0.3 确认 gate env 现值（回退锚 = 清此二 env）
docker exec vllm-tp4-rank0 printenv | grep -E 'VLLM_DSPARK_CONF_(GATE|MIN)'   # 期望：无输出（gate off）
# 0.4 【P10 / G1-T2b (i) 采集点】gate-off 侧模块级反证：staging 单次行必为 0
#     ⚠️纪律：confidence staging 是 speculator 初始化「单次 info 行」，与 [S1-DIAG] 同属
#     「启动期一次性、须用 --since StartedAt 口径」的证据——不可用全量 docker logs（含上轮残留）
docker logs --since $(docker inspect vllm-tp4-rank0 --format '{{.State.StartedAt}}') \
  vllm-tp4-rank0 2>&1 | grep -c "confidence staging"   # 期望 0（gate-off 反证实锤）
```
**回退锚点**：`{digest, StartedAt, 二 env 现值=空}` 三项落盘。任何回退 = 恢复这三项。

### 阶段 1 · 臂 A（gate off，对照）（T+5 → T+20）
```bash
# 1.1 冷口径单请求：贪心、同 seed、prose 512 token、max-num-seqs=1
#     prompt 固定文本 + seed 固定（两臂同 seed，见 §1 G3）
# 1.2 发请求，落盘：输出 token 序列 + usage.completion_tokens
# 1.3 结束后快照 → g2-snap-A.metrics；Δ = A - A-
# 1.4 抽 per-position：for i in 0..5: ΔA_i
```
产出：`A-seq.json`、`A.metrics`、`A-pos.tsv`。

### 阶段 2 · 臂 B（gate on, thr=0.1）（T+20 → T+40）
```bash
# 2.1 清旧、设新（仅此二 env 变化，其余全同臂 A）
#     VLLM_DSPARK_CONF_GATE=1  VLLM_DSPARK_CONF_MIN=0.1
#     VLLM_LOGGING_LEVEL=DEBUG  --enable-log-stats
# 2.2 重启后的「补丁落地验证」三条（注意：[S1-DIAG] 只在有请求经过 scheduler 时才输出，
#     boot 阶段必为空——不可用 boot grep 判「补丁没打上」）：
#     ① docker inspect vllm-tp4-rank0 --format '{{.Image}}'  ==  期望 digest（sha256:<BAKE_IMAGE_DIGEST>…b'）
#     ② 镜像内文件 md5 == 补丁后 md5（E0-d 纪律；比 scheduler.py / dspark_speculator.py）
#     ③ docker exec vllm-tp4-rank0 printenv | grep VLLM_DSPARK_CONF_DIAG  ==  1
# 2.2b 【P10 / G1-T2b (i) 采集点】gate-on 侧模块级实锤：staging 单次行 ≥1 且 n_spec==6
docker logs --since $(docker inspect vllm-tp4-rank0 --format '{{.State.StartedAt}}') \
  vllm-tp4-rank0 2>&1 | grep "confidence staging"      # 期望 ≥1 且 n_spec==6
# 2.3 同 prompt 同 seed 发请求 → B-seq.json / B.metrics / B-pos.tsv
# 2.4 【发请求之后】验证日志出口工作：grep 必须非空，才证明 DIAG 日志生效
#     —— 同时构成 P10 / G1-T2b (ii) 行为级实锤（gate-on 须出现 l_r<6 的行）
docker logs vllm-tp4-rank0 2>&1 | grep '\[S1-DIAG\]' > /root/g2-B-frames.log   # 非空 = PASS
#     （字段：l_r / spec_sched / num_new_tokens / budget / conf_step / used_step）
#     ★P10 (ii)：若无任何 l_r<6 的帧 → 仅有模块级、无行为级 → 判「env 未生效」，不得 PASS
```

### 阶段 3 · 对拍判定（T+40 → T+60）
```bash
# 3.1 C9 硬门：序列逐位
diff <(jq -r '.token_ids' A-seq.json) <(jq -r '.token_ids' B-seq.json)   # 必须 0 差异
# 3.2 D1/D2 恒等式（L1 先验，两臂各跑；单请求用「严格相等或 +1」允差）
#     accepted + drafts == completion  （±1/请求）
#     accept_len == completion/drafts − 1
# 3.3 F2==F3：每帧 _conf_lengths_frame 长度 == scheduled_spec_decode_tokens 长度
# 3.4 有效性：grep ' l_r=' frames | 必须出现 l_r<6 的帧（否则判无效测试，见 §1 G5）
# 3.5 F6/F7：B 的 KV block / verify token ≤ A
# 3.6 D3/D4：本负载 gate-off 臂重标定 r_{i+1}/r_i 带；查是否 >0.70 且 O_i 塌缩
# 3.7 P4 lag：frames 中 min(used_step - conf_step) ≥ 1（否则直接 FAIL）
```

### 阶段 4 · 收臂（T+60）
```bash
# 4.1 清二 env，恢复 gate off（= 回退路径演练，一箭双雕）
# 4.2 复跑臂 A 的 2 项基准，回到锚 ±1.1% → 证明回退可用
# 4.3 落盘 g2-preflight-ab/ 全部产物 + 判定单
```

---

## 4. 回滚条件（含数值阈值）

**R1–R10、R12b、R13：触发任一 → 立即回滚（清 `VLLM_DSPARK_CONF_GATE` + `VLLM_DSPARK_CONF_MIN` 二 env，恢复阶段 0 锚点镜像/StartedAt）。R11 与 R12 为「非回滚」项，按下表处置**：

| # | 信号 | 阈值 / 条件 | 动作 |
|---|---|---|---|
| **R1** | **C9 序列不一致**（P0，最高优先） | gate-on 与 gate-off 贪心输出 token 序列**任一位不等**（已剔除非确定性来源） | **立即回滚 + FAIL**，回查 C2/C6（当前步置信/实现值是否泄漏进截短边界） |
| **R2** | **D1 三角破** | `|completion − (accepted+drafts)| > N`（单请求 >1） | 立即回滚 + FAIL（记账造假） |
| **R3** | **D2 自洽破** | `accept_len` 与 `completion/drafts − 1` 相对误差 > `1/drafts` | 立即回滚 + FAIL |
| **R4** | **KV 反向** | 截短臂任一帧 KV block / `kv_cache_usage` **> 对照臂对应帧** | 立即回滚 + FAIL（P0-2 未生效，被剪槽仍占 KV） |
| **R5** | **预算等式破** | 任一帧 `budget_before − budget_after ≠ num_new_tokens` | 立即回滚 + FAIL |
| **R6** | **verify 反向** | B 的 verify token 数 **> A**（截短方向反） | 立即回滚 + FAIL |
| **R7** | **lag 违规** | `used_step − conf_step < 1`（出现 lag=0） | **立即回滚 + FAIL**（违反 non-anticipating，正确性根基失效） |
| **R8** | **D3 越界** | 任一深位 `r_{i+1}/r_i > 0.70` **且** 该位 `O_i` 相对塌缩 | 回滚 + FAIL，回查 C2/C6（回顾性接纳指纹） |
| **R9** | **D5 反例** | `accepted(gate-on) > accepted(gate-off)` 且 output 体量持平 | 回滚 + FAIL（出现 gate-off 中不存在的接受） |
| **R10** | **健康/重启异常** | 任一机非 200 / `RestartCount>0` / 出现基线没有的 fallback 行 | 回滚 + 排查（对齐 g1g4 G1-T1/T3） |
| **R11** | **无效测试（非回滚，但结论作废）** | 全部帧 `l_r ≡ 6`（截短未触发） | **不回滚**，判「无效测试」→ 改 prompt/升 thr 复采；**不得**记为 PASS |
| **R12** | **步时观察项（默认不回滚）** | step-time 中位较臂 A 恶化 **> 1.5% 且 ≤ 5%** | **仅记录并标记，不阻断本窗**，留待 G3 高并发窗正式复测。**理由**：G2 是 `max-num-seqs=1` 单请求极小载荷，step-time 由 CPU 侧抖动主导、1.5% 落在噪声内；且 gate-on 截短后 step-time 本应略降或持平——正确性门不应被单请求高噪声指标劫持 |
| **R12b** | **步时硬回滚（远离噪声带）** | step-time 中位较臂 A 恶化 **> 5%** | **回滚 + 排查**（阈值远离单请求噪声带，属真实回归） |
| **R13** | **env 未生效（回滚 + FAIL）** | gate-on 与 gate-off 在同 prompt 同 seed 下**无可观测行为差异**，**且已排除"截短未触发"**（即 `l_r<k` 帧**确实观测到了**，但两态行为仍无差异） | **立即回滚 + FAIL**，判「**env 未生效**」而非「gate 正常」。**与 R11 的区别（相邻但处置相反，现场最易混）**：**R11 = "截短没触发"**（全部帧 `l_r ≡ 6` → 无效测试，**不回滚**，改 prompt/升 thr 复采）；**R13 = "触发了两态仍无差异"**（`l_r<k` 已观测 → 说明门控被忽略/接线死路 → **回滚并 FAIL**）。判据交叉引用 `qa-program-conf-head-2026-09-10.md §2 G1-T2b`（仅 (i) 模块级无 (ii) 行为级 → 即本状态） |

**回滚后**：保留 `g2-preflight-ab/` 全部产物 + 触发信号原文（命令 + 输出两件套），**附 (CONF_MIN, position, r_i) 证据上报**，不得只报「已回滚」。

---

## 5. 与四条放行条件 / 下期门的关系

| 条件 | 本清单覆盖 | 缺口 |
|---|---|---|
| 1. G1-T2 gate off staging=0 | **P10 / G1-T2b 显式采集点**：阶段 0.4（gate-off 反证实锤，`--since StartedAt` 计数=0）+ 阶段 2.2b（gate-on ≥1 且 n_spec==6）+ 阶段 2.4（(ii) 行为级：l_r<6 帧）。交叉引用 `qa-program-conf-head-2026-09-10.md §2 G1-T2b`，**搭本窗 1/2 执行、不额外起停** | — |
| **2. G2 前置 CONF_MIN=0.1 对拍** | **本清单主体（P1-P10）** | P1-P4 补齐前 NO-GO；P10 串行依赖 P1 |
| 3. G4 gate-off 回归 ≤1.1% | 阶段 4.2 顺带核（非主体） | 完整 G4 见 g1g4 checklist |
| 4. 回退 = 清二 env | 阶段 4.1 即回退演练 | — |
| **下期 G3**（并发/扫描/cudagraph/VL） | 盲区 G1/G2/G8 的正式门 | 明确不在本窗 |

---

*清单 v1.2 落盘 2026-09-10。当前 **NO-GO**：4 项阻断（P1/P2/P3/P4）+ 1 项前置依赖（P10，串行依赖 P1），补齐路径见 §2；镜像 rebuild 后须过 g1g4 元门 E0 方生效。P10↔G1-T2b 互引见 §1 P10 行与 §5 条件-1。*
