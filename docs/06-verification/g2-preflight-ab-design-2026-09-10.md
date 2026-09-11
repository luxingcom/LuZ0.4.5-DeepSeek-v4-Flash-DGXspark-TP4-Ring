# G2 前置「CONF_MIN=0.1 单请求 A/B 数值对拍」验收方案设计

日期：2026-09-10 ｜ 设计：Cody（代码审查师，工程保障团队）｜ 性质：**只读设计，未 SSH、未碰生产、不写补丁**
上位：S1 修复复审（#26）定谳的四条放行条件之 **条件 2**（G2 前置）。镜像 sha256:<BAKE_IMAGE_DIGEST> / tag `…VL-S1-20260910b`。
目的：在开 CONF_MIN 五档扫描（G2-T4）之前，用**单请求、贪心、逐步对拍**证明「截短只改记账、不改采样路径」——即 P0-2 修复后 KV 分配量、token_budget 扣减、verify 长度三者同源收缩，且输出 token 序列与 gate off 逐位一致。

---

## 0. TL;DR（判定卡）

| 对拍字段 | 准则 | FAIL 阈值 |
|---|---|---|
| 输出 token 序列（贪心） | **严格逐位相等** | 任一位置不等 = FAIL（P0，阻断） |
| `_conf_lengths_frame` vs 本帧 `scheduled_spec_decode_tokens` 长度 | **严格相等**（l_r 生效证据） | 任一帧不等 = FAIL |
| KV 分配 block 数（截短臂） vs 期望 ⌈(1+l_r)/block_size⌉·步数 | **≤ 全 k 臂**（同源收缩） | 截短臂 ≥ 全 k 臂 = FAIL（P0-2 未生效） |
| `token_budget` 扣减 = Σ num_new_tokens | **严格相等**（自洽） | 扣减 ≠ Σnum_scheduled_tokens = FAIL |
| verify 步数（截短臂 vs gate off） | **≤** gate off | > gate off = FAIL |
| verify 被验 token 数（截短臂 vs gate off） | **≤** gate off | > gate off = FAIL |
| `num_invalid_spec_tokens` | 允许 >0（async guard 正常记账） | 非 async 路径出现 >0 = FAIL |

**一句话判定**：贪心输出序列严格相等 = 语义正确性成立；KV/预算/verify 三者同步收缩 = P0-2 修复生效。二者同时成立才放行 G2-T4。

---

## 1. 对拍对象与口径

### 1.1 两臂定义（单变量）

| 臂 | env | 说明 |
|---|---|---|
| **A（对照）** | `VLLM_DSPARK_CONF_GATE` 未设（gate off） | 纯基线，声明 k=6，全 k 验证 |
| **B（截短）** | `VLLM_DSPARK_CONF_GATE=1` + `VLLM_DSPARK_CONF_MIN=0.1` | 开 gate，thr=0.1 → 按置信 cumprod 截短 l_r |

其余参数**完全一致**：同 prompt、`temperature=0`（贪心）、`max_tokens` 固定、`max-num-seqs=1`（单请求、无并发混杂）、前缀缓存口径一致（建议 uuid 冷算，避免缓存命中影响步数对齐）、同 GPU 频率制。

### 1.2 必须对拍的数值字段（逐帧）

| # | 字段 | 代码位置（work 树行号） | 采集途径 |
|---|---|---|---|
| F1 | 输出 token 序列 | API response `choices[0].message` / `usage.completion_tokens` | HTTP 响应 |
| F2 | `_conf_lengths_frame`（本帧各请求 l_r） | scheduler.py L1257 冻结处 | 需新增 info 日志（见 §3） |
| F3 | `scheduled_spec_decode_tokens[req]` 长度 | scheduler.py L704 写入处 | 需新增 debug 日志 |
| F4 | `num_scheduled_tokens[req]`（=num_new_tokens） | scheduler.py L676 | 同上 |
| F5 | `token_budget` 每帧扣减 | scheduler.py L677 | 帧级差分（budget_after-budget_before） |
| F6 | KV 分配 block 数 | `allocate_slots` 返回值 `new_blocks` | `kv_cache_manager.log_stats` 既有日志 / `kv_cache_usage` 差分 |
| F7 | verify 步数 / 被验 token 数 | `vllm:spec_decode_num_drafts_total` / `num_draft_tokens_total` | Prometheus :8002/metrics |
| F8 | 被接受 token 数 | `vllm:spec_decode_num_accepted_tokens_total` | 同上 |
| F9 | `num_invalid_spec_tokens` | scheduler.py L2267/2296 | 需 debug 日志 |

### 1.3 单请求逐步对齐前提

- `max-num-seqs=1` → 每帧恰好 1 个请求，`_conf_lengths_frame` 只有 1 条，步序可对齐。
- 贪心 `temperature=0` → 采样确定性，两臂 decode 步数若因截短而不同，**输出序列仍应逐位相同**（这是核心断言：截短 = 少验证尾部，被截 token 下步重验，最终提交序列不变）。
- ⚠️ 步数可能不同（截短臂每步推进少 → 总步数略多），故**序列按 token 对齐、不断言步数相等**；步数只作 F5~F7 的聚合口径。

---

## 2. 判定准则

### 2.1 严格相等（P0，任一违反即 FAIL）

1. **输出 token 序列** A == B，逐位。→ 语义正确性（督导批准的 G2-T4 前提边界）
2. **`token_budget` 自洽**：每帧 `budget_before - budget_after == num_new_tokens`（= F4）。→ 验证 P0-2「预算按截短后扣」
3. **F2 == F3 长度**（同帧）：本帧为 req 算出的 l_r 必须等于本帧写入 `scheduled_spec_decode_tokens` 的长度（thr=0.1 时 l_r<k 应真实体现）。→ 验证截短真实生效
4. **`num_invalid_spec_tokens` 语义**：非 async 路径下恒为空；async 路径下 = 被截短槽位数。

### 2.2 允许差异（带范围）

| 项 | 期望关系 | 说明 |
|---|---|---|
| F6 KV block 数 | B ≤ A | 截短臂每帧少分配（同源收缩）。**允许 B < A，绝不允许 B > A** |
| F7 verify 步数 | B ≤ A | 截短后少验尾部；允许相等（若 l_r 恰好=6） |
| F7b verify token 数 | B ≤ A | 同上 |
| F8 接受数 | 允许 B ≤ A（绝对值），但**接受率** accepted/drafts 应 ≥ A | 截短删的都是低置信尾槽（深位 p5≈0.23 本就低接受），故分母降幅 > 分子降幅 |
| F5 总 budget 消耗 | 允许 B 略高（步数多） | 每步少推进→步数补偿，总 token 数≈A |

### 2.3 FAIL 确切断言

- 序列任一处不等 → **FAIL（P0，阻断）**
- 截短臂 F6 任一帧 > 对照臂对应帧 → **FAIL（P0-2 未生效）**
- `token_budget` 自洽等式破 → **FAIL（记账 bug）**
- B 的 verify token 数 > A → **FAIL（截短方向反了）**
- 注意：**F2 中 l_r 必须出现过 <k**（否则 thr=0.1 未生效，等同 thr=0，对拍无效 → 视为**无效测试**而非 PASS）

---

## 3. 脚本设计（只出设计，不写补丁）

### 3.1 采集途径与日志级别

| 途径 | 需开 | 落点 |
|---|---|---|
| **P1 序列对拍** | 无（HTTP） | 独立脚本直连 :8001 `vllm/chat/completions`（Bearer） |
| **P2 帧级记账** | `VLLM_LOGGING_LEVEL=DEBUG` + 新增 3 条日志 | scheduler.py：F2（冻结处 L1257 旁）、F3+F4+F5（L676-704 段）、F9（L2267/2296） |
| **P3 KV/metrics** | `--enable-log-stats`（scheduler `log_stats=True`） | 既有 `kv_cache_manager.log_stats`；Prometheus :8002/metrics |
| **P4 增量日志（实现线补）** | gate 内条件打点 | **只在 `self._conf_gate` 为真时** logger.debug，避免 gate off 污染与性能开销 |

**新增日志建议字段（实现线落地，本设计不写代码）**：
```
[S1-DIAG] step=%d req=%s l_r=%s spec_sched=%d num_new_tokens=%d budget_before=%d
[S1-DIAG] frame=%s      # 冻结帧 dict 快照，仅 gate on
[S1-DIAG] invalid=%s    # num_invalid_spec_tokens，仅非空
```
用统一前缀 `[S1-DIAG]` 便于 grep；采集命令（**必须带 `--since`，见 §3.0**）：
```bash
# 每臂/每阶段重启后重新取本容器实例的 StartedAt（新容器实例该值必变）
S=$(docker inspect vllm-tp4-rank0 --format '{{.State.StartedAt}}')
docker logs --since "$S" vllm-tp4-rank0 2>&1 | grep "\[S1-DIAG\]"   # 仅 rank0（单请求，无需四机）
```

### 3.0 时间序纪律（全方案通用，硬要求）

> **两臂共用同一容器名 `vllm-tp4-rank0`**（先臂 B、后臂 A，或反之），若用全量 `docker logs` 必然**跨臂串台**：
> - gate-on 臂 grep 到 gate-off 臂旧帧 → 制造"gate-on 有 DIAG 帧"的**伪证据**；
> - gate-off 臂读到 gate-on 帧 → **P10 (i) 的 `gate-off==0` 判据直接作废**；
> - 而 `[S1-DIAG]` 帧是 **F2/F3/F9 三支柱的唯一数据源**、亦是 **P10 (ii) `l_r<k` 的唯一来源**——串台即全窗数据不可用，且**日志会被覆盖写、无法事后补救**。

**铁律**：
1. 本方案**所有**"日志中应/不应出现 X"的判据，**一律用 `docker logs --since "$S"`**；**禁用全量 `docker logs`**。
2. `S` = 本容器实例的 `StartedAt`，**每阶段（臂）切换、容器重启后必须重新采集**——阶段 1/2 是两个独立容器实例，StartedAt 不同。
3. 每个日志判据执行前**先断言 `StartedAt` 晚于本阶段重启时刻**，否则该判据作废。
4. 采集产物**文件名须显式绑定 `S`**（如 `B-frames.$S.log`），使"该文件属于哪一臂"可审计，杜绝串台（见 §3.2 步骤 6）。
5. **⚠️ `--since` 隔离不了镜像身份（两半纪律的后一半）**：`StartedAt` 只能回答"读哪一段日志"，**不能回答"这段日志属于哪个镜像"**。若同一容器名被换成另一个镜像实例，`--since "$S"` 照样命中——**镜像身份必须由 tag/digest 承担**。故**每阶段除记录 `S` 外，必须同时记录镜像 tag/digest**：
   ```bash
   TAG=$(docker inspect vllm-tp4-rank0 --format '{{.Config.Image}}')   # 期望含 …S1-20260910b
   DIG=$(docker inspect vllm-tp4-rank0 --format '{{.Image}}')          # 期望 sha256:<BAKE_IMAGE_DIGEST>…
   ```
   产物文件名**同时绑定二者**（如 `B-frames.<TAG>.<S>.log`）。**背景**：G1-T5 的 BASE = 旧镜像 `<BAKE_IMAGE_DIGEST>`、NEW = 新镜像 `…S1-20260910b`（**两个不同镜像**）——若只记 StartedAt，事后审计无法回答"某轮 −4% 是镜像造成还是配置造成"，这正是 G1-T5 争议核心。本条与 G1-T5 §4 配置漂移四联、g1g4 元门 E0（`docker inspect --format '{{.Image}}'`）互为**镜像身份三重记录**，口径须一致。

### 3.2 脚本骨架（伪码，SRE 落地）

```bash
# ==== 臂 B（gate on, thr=0.1）====
# 1) 起服前置：两 env 注入（清旧、设新）
#    VLLM_DSPARK_CONF_GATE=1  VLLM_DSPARK_CONF_MIN=0.1
#    VLLM_LOGGING_LEVEL=DEBUG  --enable-log-stats
# 1b) 重启后【重新采集本臂 StartedAt + 镜像身份】——每阶段独立容器实例，S 必变
#     S_B=$(docker inspect vllm-tp4-rank0 --format '{{.State.StartedAt}}')
#     TAG=$(docker inspect vllm-tp4-rank0 --format '{{.Config.Image}}')   # 镜像 tag
#     DIG=$(docker inspect vllm-tp4-rank0 --format '{{.Image}}')          # 镜像 digest
# 2) 冒烟：短请求 warmup（不计入）
# 3) 采基线 metrics 快照 s0 = /metrics 的 spec_decode_* 与 kv_cache_usage
# 4) 发单请求：max-num-seqs=1 口径，temperature=0，固定 prompt，max_tokens=N（建议 512）
# 5) 采 s1；落盘【绑定 TAG+S_B】的产物：B-seq.json / B.metrics（记录 s0、s1 与 TAG/S_B 区间）
# 6) grep [S1-DIAG] 落盘帧级轨迹，【文件名绑定 TAG+S_B】：B-frames.$TAG.$S_B.log
#    docker logs --since "$S_B" vllm-tp4-rank0 2>&1 | grep "\[S1-DIAG\]" > B-frames.$TAG.$S_B.log
# ==== 臂 A（gate off）====
# 7) 清两 env（gate off）重启；其余同 B，重复 3)~6)
#    重启后【重新采集】S_A + TAG_A + DIG_A；产物 = A-seq.json / A.metrics / A-frames.$TAG_A.$S_A.log
#    ★S_A ≠ S_B 且 TAG 须各自记录：两臂产物按"镜像身份 + StartedAt"双绑，杜绝串台与镜像混淆
# 8) 对拍脚本 diff：序列逐位 / F2==F3 / budget 自洽 / F6B<=F6A / F7B<=F7A
#    ★读帧级数据时，A 臂只读 A-frames.$TAG_A.$S_A.log、B 臂只读 B-frames.$TAG_B.$S_B.log，禁跨臂混读
```

**脚本落点**：`deliverables/engineering-assurance/g2-preflight-ab/`（SRE 侧执行目录），本地仅留设计。
**只读纪律**：本设计不产出可执行补丁文件；F2/F3/F9 的日志打点由 implementer-s1 出补丁，Cody 复审后并入 b' 版镜像。

### 3.3 prompt 选择建议

- 用**中长输出**（512 token）而非短答案：截短在深位才显现，短答案可能 1~2 步就结束，F7 区分度不足。
- 建议复用 speclong.py 的散文 prompt（已知 prose 深位衰减快 p5≈0.23，最能触发 l_r<k）。
- 固定 prompt 文本 + 固定随机种子（贪心下种子对主采样无影响，但 gumbel draft 用 seed，**需同 seed 保证两臂 draft 提议一致**——见 §4 盲区 G3）。

---

## 4. 盲区清单（本方案测不到的东西）

| # | 盲区 | 影响 | 缓解 |
|---|---|---|---|
| **G1** | **单请求 ≠ 多请求**：无法覆盖 P0-2 修复针对的「token_budget 被下一请求继承」的多请求竞争场景 | 预算错配在单请求下不可见（单请求 budget 充裕） | 单请求只验「同源收缩」；多请求预算竞争须 G3 并发臂补测（建议 conc=8 双请求对拍 budget 总和） |
| **G2** | **无法证伪 CUDA graph 行为**：读的是 CPU 侧记账，看不到 FULL graph 是否因截短产生额外 capture/miss | 若截短改变了 verify shape，图 miss 只在性能体现 | 靠 G3 step-time 单调性 + CUDA graph 统计日志（`cudagraph_stats`）补 |
| **G3** | **两臂 draft 提议一致性**：gumbel_sample 用 seed + temperature，若两臂 seed 不同则 draft 候选不同，序列对拍会假阳性 FAIL | 误判 | 必须固定 seed（同 `sampling_params.seed`）；否则退化为「统计等价」而非「逐位等价」 |
| **G4** | **stale 时序**：置信分 stale 一拍/async 下 2-step，F2 的 l_r 是「上一帧置信」推出的，**无法在单帧内验证 l_r 与当帧真实置信的关系** | 看得到结果、看不到因果 | 需交叉核对 `get_stale_confidences` 的 D2H 时序（另属 G1-T2/G3 面） |
| **G5** | **thr=0.1 的截短幅度**：若该 prompt 置信全高（l_r 恒=6），对拍退化为恒等，**测不到截短路径** | 无效测试 | §2.3 已定：必须观测到 l_r<k 才算有效；否则换 prompt/调 thr |
| **G6** | **KV block 数精度**：block 按 block_size 取整，小 l_r 差异可能落在同一 block 内不显现 | F6 区分度弱 | 用 `kv_cache_usage` 高位差分 + 长上下文（多 block）放大信号 |
| **G7** | **async placeholder guard 的实际触发**：单请求同步路径可能不走 async guard | guard 分支未覆盖 | 需确认服务是否 `async_scheduling`；若否，guard 属 G4/G3 另测 |
| **G8** | **多模态（VL）路径**：本对拍建议纯文本，未覆盖 vision prefill 与 spec 交互 | VL 线风险敞口 | 需另一条 vision 五门 + spec 对拍（G3 面） |

---

## 5. 盲区处置（G1-G8 逐条转可执行动作）

> 追加于 2026-09-10（team-lead 指派的收口项）。**处置方式三选一**：`加日志` / `加门` / `显式接受`（并在"残余风险"列写明依据）。「是否本期必解」= 是否必须在**本次 G2 单请求对拍窗口**内闭环（"本期"= G2 前置这一窗，不含其后的 G3 并发/扫描窗）。

| # | 盲区描述 | 本期必解？ | 处置方式 | 具体动作 / 残余风险 |
|---|---|---|---|---|
| **G1** | 单请求 ≠ 多请求：覆盖不到 P0-2 真正针对的「token_budget 被下一请求继承」竞争场景 | **否** | **加门（下期）** | 本期单请求只证「同源收缩」（F5/F6 单调）；**多请求预算竞争另立 G3 并发门**：`max-num-seqs=8`（≥2 请求同帧），对拍 `Σ token_budget` 与 ΣKV block，断言 B 臂总预算 ≤ A 臂且无跨请求串味。残余风险：本期若 budget 竞争有 bug，单请求窗口**测不出**——故本窗 PASS **不得**被外推为「budget 记账全对」。 |
| **G2** | 读的是 CPU 侧记账，看不到 FULL CUDA graph 是否因截短产生额外 capture/miss | **否** | **显式接受 + 加门（下期）** | 本期**显式接受**：截短发生在调度侧（CPU），FULL graph 为静态 shape 捕获，**捕获形状由 k 决定、不由 l_r 决定**（见 §1.2 k-slot-control 报告：DSpark 捕获整个 draft step）。残余风险：若截短意外改变了 verify 张量 shape，只会在**性能**（step-time）暴露、不在正确性暴露。**下期 G3 补**：`cudagraph_stats` 捕获计数（对齐 g1g4 checklist 的 PIECEWISE 16/16 ∧ FULL 11/11 ∧ dspark 10/10 合取判）+ step-time 单调性。 |
| **G3** | 两臂 draft 提议一致性：gumbel draft 用 seed，若两臂 seed 不同则 draft 候选不同 → 序列对拍假阳性 FAIL | **是** | **加门（硬前置）** | **必须固定 `sampling_params.seed`（两臂同一值）**；并**在脚本里显式打印两臂 seed + 首个 draft 提议的 hash 供核对**。若无法固定 seed → **降级**为「统计等价」（同 prompt 多采样比对 token 频率分布，参照 non-anticipating §3 F2），**不得**再用「逐位相等」作 P0 硬门。残余风险：贪心下主采样虽确定，但 draft 的 gumbel 若不接 seed 仍可能抖动——此为本窗**最高优先**的两个硬前置之一（另一个是 G5 有效性）。 |
| **G4** | stale 时序：F2 的 l_r 来自 stale 一拍（async 下可能 2 拍），单帧内**无法**验证 l_r 与当帧真实置信的因果 | **部分** | **加日志 + 显式接受因果、加门（下期）** | 本期**加日志**：`[S1-DIAG]` 打点输出 `conf_step` 与 `used_step`，**断言 `used_step - conf_step ≥ 1`**（对齐 non-anticipating C7「第一优先检查项」）。**显式接受**：单帧内无法证「l_r ↔ 当帧置信」的因果——这是**设计固有**（stale 就是因果屏障，见 non-anticipating §4.2 NA-1）。残余风险：若 lag 实为 0（当帧 conf 用于当帧），**等于违反 non-anticipating**——故 `used_step-conf_step≥1` 的断言**必须**在本窗跑通，否则 NO-GO（见 readiness 清单前置项 P4）。 |
| **G5** | thr=0.1 截短幅度：若该 prompt 置信全高（l_r 恒=6），对拍退化为恒等，**测不到截短路径** | **是** | **加门（有效性硬判）** | §2.3 已定：**必须观测到 l_r<k 的帧**，否则判「**无效测试**」而非 PASS。动作：prompt 用**中长输出（512 token）+ prose**（已知深位衰减快，p5≈0.23，最易触发 l_r<k）；若首轮无 l_r<k，**改 prompt / 提到 thr=0.2 复采**（但注意 thr=0.2 已属 G2 三档扫描，见 readiness P2）。残余风险：`l_r<k` 出现频次仍需 ≥ 某下限才算「有效样本」——建议**≥ 总帧数 5%** 且绝对 ≥ 20 帧，否则降级为「弱证据」。 |
| **G6** | KV block 数精度：block 按 block_size 取整，小 l_r 差异可能落在同一 block 内不显现（F6 区分度弱） | **否** | **加日志（放大信号）** | 本期：F6 改用 **`kv_cache_usage` 高位差分**（gauge，非 block 计数）为主证；并用**长上下文**（多 block）放大信号。**显式接受**：F6 在单层 block 粒度上可能不单调——**不与 F5/F7 同权**，F6 只作「不同向反例」（B>A 才 FAIL）。残余风险：极端情况下 F6 恒定（block 未跨界）会掩盖截短，故 F6 **不单独**作判定依据，须与 F5+F7 合判。 |
| **G7** | async placeholder guard 的实际触发：单请求同步路径可能不走 async guard（分支未覆盖） | **否** | **加日志 + 显式接受分支** | 本期：**先确认服务是否 `async_scheduling`**（查启动参数 + `[S1-DIAG]` 打点记录 guard 触发次数）。**若同步路径**：guard 分支本窗**不覆盖**，**显式接受**并记录「C6 异步 guard 未实测」为已知缺口，转 G3。**若 async 路径**：guard 必须触发且 F9（invalid 计数）应 >0。残余风险：补丁 P1-2 修的 async guard 若只在 async 生效，本窗走同步会**漏测该修复**——故本窗 PASS **不含** async guard 的结论。 |
| **G8** | 多模态（VL）路径：本对拍建议纯文本，未覆盖 vision prefill 与 spec 交互 | **否** | **显式接受** | 本期**显式接受**：本窗为纯文本单请求，**VL 线风险敞口不因此收窄**。残余风险：VL 的 vision prefill 会改变首步 token 分布与 spec 步数对齐——**VL 线须另立一条「vision 五门 + spec 对拍」**（G3 面，参照 vl-acceptance-sixgates 门6：drafts=3806/draft_tokens=22836/accepted=5191/per-pos 2453/1290/680/378/239/151）。 |

**处置汇总**：本期必解 2 项（**G3 seed 固定**、**G5 l_r<k 有效性**）；加门/加日志本期动作 3 项（G4/C7 断言、G6 换口径、G7 探路径）；显式接受并转下期 3 项（G1→G3 并发门、G2→G3 cudagraph 门、G8→VL 线）。

---

## 6. 与四条放行条件的关系

| 条件 | 本方案覆盖 |
|---|---|
| 1. G1-T2 gate off 下 `grep -c "confidence staging"` = 0 | **间接（须带 `--since` 口径）**：本条须为 `docker logs --since "$S_A" … \| grep -c "confidence staging"`（`S_A` = gate-off 臂容器实例 StartedAt），**禁用全量 logs**——否则会读到 gate-on 臂残留，把 `==0` 判据直接做废（见 §3.0）。本方案 gate-off 臂即为该验证的一部分 |
| **2. G2 前置 CONF_MIN=0.1 对拍** | **本方案主体** |
| 3. G4 gate-off 回归 ≤1.1% | **不覆盖**（属 G4 基准回归，另测） |
| 4. 回退 = 清两 env | 本方案两臂切换即验证了回退路径可用性 |

---

*设计 v1 落盘 2026-09-10；§5 盲区处置 v1.1 追加 2026-09-10；§3.0 时间序纪律（`--since` 铁律）+ §3.1/§3.2 产物绑定 StartedAt v1.2 追加 2026-09-10；**§3.0 铁律 5「镜像身份三重记录（S + tag + digest）」+ §3.2 产物 TAG+S 双绑 v1.3 追加 2026-09-10**（回应 team-lead：`--since` 隔离实例但隔离不了镜像）。待 implementer-s1 落地 §3.1 三条 `[S1-DIAG]` 日志补丁（**打点须含足以区分两臂的信息**，见复审要求）并经 Cody 复审后，SRE 方可在 b' 镜像上执行本对拍。开臂前置与 Go/No-Go 见同目录 `g2-open-arm-readiness-2026-09-10.md`。*
