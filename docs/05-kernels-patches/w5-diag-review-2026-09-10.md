# w5_diag.patch 独立复审报告（`[S1-DIAG]` 三条打点）

- **审查对象**：`s1-patch-20260910/w5_diag.patch`（md5 `fcdbd55994c97cc819f49944b18713ea`，8025 B）
- **审查人**：code-reviewer-15（代号 s2-diag-review），fresh eyes，与补丁作者无上下文重叠
- **审查方式**：纯本地只读（bash + python 3.13.12，临时目录 `/tmp/w5rev`），**禁 SSH / 禁碰生产 / 未改动任何原文件**
- **日期**：2026-09-10
- **基底**：`base/scheduler.build.py`（md5 `13e5cd2a8ffae3431a610c9680525432`）→ `scheduler_verify.patch`（md5 `2a463be7e3bc1623d14b445b8c291784`）→ w5

---

## 1. TL;DR

# ✅ PASS — 该补丁可用于 rebuild 并入镜像

三条打点**全部落在 `if self._conf_gate:` 守卫内**；w5 为**纯增量 +99 行、0 删 0 改**；链式回放 `base→verify→w5` 后**逐字节等于**目标文件 md5 `1c344c8284f566eb7dde4d3816691332`；`l_r` 取值来源、`frame` 快照时机、`conf_step/used_step` 语义、日志级别惰性求值**均核验通过**。

**无 P0 / 无 P1 阻断项。** 仅 2 条 P2 观察项（均为运维纪律/文档口径，不阻断合入）。

---

## 2. A 节 · 复现自验（实测输出）

### A1+A2 链式回放

```
$ cp base/scheduler.build.py mid.py            # md5 13e5cd2a8ffae3431a610c9680525432
$ patch -p0 mid.py < scheduler_verify.patch    # patching file mid.py
$ md5sum mid.py
f95874aa23342a2292508aea4ad83775 *mid.py       # = README 声明的 verify 中间态 md5 ✓

$ patch -p0 mid.py < w5_diag.patch             # patching file mid.py
$ md5sum mid.py
1c344c8284f566eb7dde4d3816691332 *mid.py       # = 目标 md5 ✓
```

### A3 逐字节 cmp（证据）

```
$ cmp mid.py work/scheduler_diag.py   →  无输出，exit 0
CMP: IDENTICAL (byte-for-byte)
$ wc -l / wc -c :  3104 行 / 147800 字节（两文件一致）
```

> 说明：python `splitlines()` 报 3005 是因其按更多换行边界切分，非文件差异；权威判据是 `cmp` 逐字节一致。

### A3 hunk 命中 / fuzz / offset

```
$ grep -c "^@@" w5_diag.patch                       →  6
$ patch -p0 --dry-run base.py < w5_diag.patch       →  "checking file base.py"，exit 0
                                                        （无 "with fuzz"，无 "offset" 警告）
```
**结论：6/6 hunk 全中，零 fuzz 零 offset** —— 与作者声明一致（= 依据，实测复核）。

### A4 `ast.parse`

```
$ python -c "import ast; ast.parse(open('mid.py').read())"
ast.parse OK                                    # 补丁后完整文件语法通过
```

### A5 反向验证（作者声明 2 的关键反证）

```
$ cp base/scheduler.build.py solo.py            # pristine base
$ patch -p0 --dry-run solo.py < w5_diag.patch
Hunk #1 FAILED at 285.
Hunk #2 succeeded at 517 with fuzz 2 (offset -58 lines).
Hunk #3 succeeded at 1196 with fuzz 2 (offset -92 lines).
Hunk #4 FAILED at 2192.
Hunk #5 FAILED at 2248.
Hunk #6 succeeded at 2155 with fuzz 2 (offset -182 lines).
3 out of 6 hunks FAILED
exit=1
```
**结论：声明 2「w5 无法对 base 单独套用」成立（= 证据）。** 6 个 hunk 中 3 个硬失败；另 3 个即便"命中"也带 fuzz 2，属就近误匹配，不可靠。w5 结构性依赖 verify 引入的符号。

**A 节判定：作者自验 5 项全部独立复现通过，无夸大。**

---

## 3. B 节 · 语义正确性（逐项核验）

### B1 · `l_r` 取值来源 ✔ 正确

打点表达式（补丁后 `work/scheduler_diag.py` L604）：
```python
self._conf_lengths.get(request.request_id)
```
其**生产点**（`_conf_pull_lengths`，L2255-2268）：
```python
k = self.num_spec_tokens
...
    survival = np.cumprod(conf[j].astype(np.float64))
    ok = survival >= self._conf_min
    length = int(ok.cumsum().argmax()) + 1 if ok[0] else 1
    length = min(max(length, 1), k)          # ← 夹紧到 [1, k]
lengths[req_id] = length
self._conf_lengths = lengths
```
- `l_r` 取值域 `∈ [1, k]`，是**真正"实际验证的 draft 槽位数"**（置信头推导的验证长度），非任何近似量。
- **`l_r < k` 语义成立**：当置信前缀未满 k 时 `l_r < k`，恰好是 **P10 (ii)** 的判据来源。✔ 与规格一致。

### B2 · `frame` 快照构造时机 ✔ 正确

补丁后 L1293-1306：
```python
        scheduler_output._conf_lengths_frame = (        # L1293 先构造快照
            dict(self._conf_lengths) if self._conf_gate else {}
        )
        # [S1-DIAG] call site 2/3 ...
        if self._conf_gate:
            logger.debug(
                "[S1-DIAG] frame=%s",
                self._diag_frame_str(scheduler_output._conf_lengths_frame),   # L1305 后读
            )
```
打点**在 `_conf_lengths_frame` 赋值之后**（L1305 晚于 L1293），快照已完整。✔

### B3 · 三条打点是否都在 `if self._conf_gate:` 守卫内 ✔ 三处全在

| 打点 | 守卫行 | 缩进层级（`cat -A` 实测） | 判定 |
|---|---|---|---|
| site 1 | L597 `if self._conf_gate:` | 12 空格（`while` 体 8 → if 12） | ✅ 守卫内 |
| site 2 | L1302 `if self._conf_gate:` | 8 空格 | ✅ 守卫内 |
| site 3 | L2389 `if self._conf_gate and num_invalid_spec_tokens:` | 8 空格 | ✅ 守卫内（gate + 非空 双守卫） |

`_conf_gate` 为 `__init__`（L274）中定义的实例属性，非恒真/恒假占位。✔

### B4 · gate off 零输出（deleted/replaced = 0）✔ 关键项通过

```
$ grep -c "^-[^-]" w5_diag.patch     →  0        # 删除行 = 0
$ grep -c "^+"        w5_diag.patch  →  100      # 含 +++ 头
$ grep "^+" | grep -vc "^+++"        →  99       # 纯新增 = +99
$ grep -c "^ "        w5_diag.patch  →  36       # 纯上下文
```
**w5 为纯增量：+99 行、0 删、0 改**（= 证据）。
⟹ gate off 时三处 `logger.debug` 均被 `if self._conf_gate:` 短路，**gate-off 语句流与原版逐语句等价** ⟹ G4-T1 判据 (ii) 成立。✔

### B5 · 惰性求值（最关键）⚠ 部分注意

**格式串插值**：三处均为 **位置参数形式** `logger.debug("fmt %d", arg1, arg2, ...)`，**非** `logger.debug("fmt" % (...))`。实测（证据）：

```
positional-args style, formatter calls (expect 0): 0     ← 惰性，INFO 下不格式化
%-format        style, formatter calls (expect >=1): 1    ← 立即求值
```
⟹ **字符串 `%` 插值确为惰性**，INFO 默认级别下零格式化开销。✔ 这一点作者说法成立。

**但存在一个作者未提及的 Python 语言事实（P2）**：Python 在**调用前**即对所有**实参表达式**求值，`logger.debug(...)` 自身虽在 INFO 下立即返回，其**实参表达式的副作用已发生**。实测（证据）：

```
gate-on at INFO: argv captured = [(..., 5, 'x', None, 6, 7, 100, 0, 5)]  probe calls = 1
```
⟹ 对本次打点，INFO 下仍会**先构造好**这些实参：
- site 1：`self._conf_lengths.get(...)`（dict 查，O(1)）、`request.request_id` 等 —— 开销可忽略；
- site 2：`self._diag_frame_str(dict(self._conf_lengths))` —— **主动构造一个 dict 副本 + 拼接字符串**；
- site 3：`",".join(f"{k}:{v}" ...)` —— 构造字符串（但已被 `num_invalid_spec_tokens` 非空守卫，通常不触发）。

量化 site 2（64 请求在飞，实测）：
```
site2-style DEBUG at INFO, 64-req dict, 200000 iters: 5.69 us/call
empty loop: 0.0218 us/call
```
即 **gate-on 但 logger 停在 INFO 时**，site 2 每步白付 ~5.7 µs 的字符串构造。

**风险评估（关键）**：此开销**仅在"gate on 且 `VLLM_LOGGING_LEVEL<DEBUG`"组合下发生**；而采集协议（`g2-preflight §3.1`）**本就强制 `VLLM_LOGGING_LEVEL=DEBUG`** —— 一旦 DEBUG 开启，日志真实输出，该格式化开销是**必要的、非冗余**的。因此：
- **不构成 gate-off 污染**：gate off 时零开销（B4 已证）。
- **不构成 gate-on 正确性风险**：仅是一段**非必需但在协议下必被消费**的格式化成本，且量级 µs 级、每步每请求最多一次。
- **结论：P2 观察项，不阻断。** 见 §4 问题清单 P2-1。

### B6 · `conf_step` / `used_step` 两字段 ✔ 语义成立

- 定义：`self._conf_conf_step = 0`（`__init__` L292）。
- 赋值：`update_confidences()` L2292 `self._conf_conf_step = self.current_step`（worker→scheduler 提交陈旧置信矩阵的**接收步**）。
- 消费：site 1（L610）emit `self._conf_conf_step`；`used_step` = `self.current_step`（L611，**消费步**）。
- 时序：`update_confidences`（收帧）必然先于**后续某步**的 `schedule()`（用帧）⟹ **`used_step - conf_step ≥ 1` 由构造保证**，正是 **G4 / P4 lag 断言**（对齐 non-anticipating C7）。✔
- 由设计文档 §G4（L190）**明确要求**该断言，此扩展**非作者擅加**，是 G2 门映射的硬需求。

### B6+ · `budget_before` 语义 ✔ 正确

`token_budget` 初始化于 L477；扣减 `token_budget -= num_new_tokens` 在 **L713**；打点 emit `token_budget` 在 **L609（早于 L713）** ⟹ 语义为"本请求扣账前的预算"，与注释一致。✔

### B7 · 无 device sync ✔

- 文件内 `print(` **零命中**（全库确认）。
- DIAG 区域（L2190-2400）内 `.item()` / `.cpu()` / `.numpy()` **零命中**。
- 打点仅格式化 CPU 侧记账量（int / request_id 串），无 tensor 入参。✔ 对齐作者声明 6。

---

## 4. C 节 · 与规格一致性（§3.1 逐字比对）

规格原文（`g2-preflight-ab-design-2026-09-10.md` L100-102）：
```
[S1-DIAG] step=%d req=%s l_r=%s spec_sched=%d num_new_tokens=%d budget_before=%d
[S1-DIAG] frame=%s      # 冻结帧 dict 快照，仅 gate on
[S1-DIAG] invalid=%s    # num_invalid_spec_tokens，仅非空
```

实测比对（证据）：

| 项 | 规格 | 补丁实测 | 判定 |
|---|---|---|---|
| 前缀 | `[S1-DIAG]` | `[S1-DIAG]`（3 处逐字节，9 字符） | ✅ verbatim |
| site1 字段顺序 | `step req l_r spec_sched num_new_tokens budget_before` | **完全一致**（`s1.startswith(spec1)==True`），其后**追加** `conf_step used_step` | ✅ 超集、顺序保持 |
| site2 | `frame=%s` | `frame=%s` | ✅ verbatim |
| site3 | `invalid=%s` | `invalid=%s` | ✅ verbatim |

**扩展字段风险评估**（下游解析鲁棒性，实测）：
```
name-based regex 解析:  {'step','req','l_r','spec_sched','num_new_tokens','budget_before','conf_step','used_step'}  → 规格 6 字段全含
positional（前缀）解析: tokens[1:7] == [step, req, l_r, spec_sched, num_new_tokens, budget_before]  → True
```
⟹ 尾部追加 `conf_step`/`used_step` **同时兼容按名解析与按位前缀解析**，**不破坏下游**。且该扩展由设计 §G4 明文要求，**可接受**。✔

---

## 5. 发现的问题清单

### P0（阻断）— 无
### P1（需改）— 无

### P2（观察 / 文档口径，不阻断合入）

**P2-1 · site 2 在 gate-on+INFO 组合下有空转字符串构造**
- **证据**：`logger.debug("[S1-DIAG] frame=%s", self._diag_frame_str(dict(...)))`；实测 INFO 下实参表达式仍被求值，64 请求时 ~5.7 µs/步。
- **依据**：Python 实参先于调用求值；`logging` 的惰性只覆盖 `%` 插值，不覆盖实参构造。
- **影响面**：仅"gate on 且日志未开 DEBUG"时；采集协议强制 DEBUG，故实务中不发生。
- **修复建议**（可选，非必须）：二层守卫 `if self._conf_gate and logger.isEnabledFor(logging.DEBUG):`，或改 `logger.debug("[S1-DIAG] frame=%s", lambda: self._diag_frame_str(...))` 不可行（logging 不支持 callable 惰性）——**推荐前者**。若坚持零改动，应在采集 runbook 里**硬性钉死 `VLLM_LOGGING_LEVEL=DEBUG`**，以免运维漏设时把这段空转计入性能。

**P2-2 · README §3.2 行号/口径需与下游对齐**
- README L159 写"**不可用 boot grep `[S1-DIAG]`**——该行须有请求经过 scheduler 才输出，boot 必为空"。此表述**正确且比"boot grep 必空"更严谨**：boot 时无请求 ⟹ grep 本就空，**不能**拿 boot grep 当镜像身份判据，**必须**用镜像内 md5 `1c344c82…`。
- **建议**：交接给 SRE 的落盘判据以 **md5 == `1c344c8284f566eb7dde4d3816691332`** 为唯一身份判据（E0-d 纪律），boot grep 仅作"管道连通性"冒烟，**不得**作为身份证据。

---

## 6. 做得好的地方

- **纯增量、0 删 0 改**（+99/0/0）是 gate-off 等价性的最强静态证据，比"逐行阅读"更硬。
- 三条打点**格式串插值全部用位置参数**，规避了 `%` 立即求值的经典坑。
- `l_r` **直接复用生产消费点的同一表达式** `self._conf_lengths.get(req_id)`，与 L571 截短逻辑**同源**，杜绝了"打点值与实际用量不一致"的缺陷。
- site 3 叠加 `and num_invalid_spec_tokens` 非空守卫，精确落实规格"仅非空"契约。
- `conf_step/used_step` 的时序由 `update_confidences` 的接收步 vs `schedule()` 消费步**结构性保证**，非人工约定。

---

## 7. 放行结论与下游约束

**结论：PASS。该补丁可用于 rebuild 并入镜像**（第五补丁，叠于 `scheduler_verify.patch` 之后）。

**下游必须遵守的约束**：
1. **应用顺序**：`base → scheduler_verify.patch → w5_diag.patch`（顺序不可换；w5 单独套 base 必败，已证）。
2. **镜像身份判据（唯一）**：rebuild 后镜像内 `vllm/v1/core/sched/scheduler.py` 的 md5 **必须 == `1c344c8284f566eb7dde4d3816691332`**（E0-d 纪律）。
3. **boot grep `[S1-DIAG]` 必空且不得作身份证据**：boot 无请求经过 scheduler，该行为空是**设计使然**；仅可作管道连通性冒烟。
4. **采集必须 `VLLM_LOGGING_LEVEL=DEBUG`**：否则 `logger.debug` 不输出（且按 P2-1 会有 µs 级空转）。这是三条打点可见的**前提**。
5. **仅 rank0 采集**：单请求 A/B 无需四机（`g2-preflight §3.1`）。
6. **`--since` 铁律**：采集命令必须带时间锚，产物文件名 TAG+S 双绑（`§3.0`）。
7. **语义消费纪律**：`l_r < k` 是 P10 (ii) 唯一来源；`frame` 是 F2/F3/F9 唯一数据源，**不可串台**；`used_step − conf_step ≥ 1` 未跑通则 **G2 NO-GO**（P4）。

---

## 附：证据 / 依据 分栏

| 陈述 | 类型 |
|---|---|
| 链式回放后 md5 = `1c344c82…`、`cmp` 逐字节一致 | **证据**（实测） |
| 6/6 hunk 全中、零 fuzz/offset | **证据**（实测） |
| w5 单独套 base：3/6 FAILED | **证据**（实测） |
| `ast.parse` 通过 | **证据**（实测） |
| 删除行 = 0、新增 = 99 | **证据**（grep 实测） |
| 位置参数惰性 vs `%` 立即求值 | **证据**（实测） |
| INFO 下实参表达式仍被求值（5.69 µs/步） | **证据**（实测） |
| `l_r` 生产点夹紧到 [1,k] | **依据**（代码推理，附源码行） |
| `frame` 快照后于构造点 | **依据**（代码阅读，附行号） |
| `used_step − conf_step ≥ 1` 由时序保证 | **依据**（调用序推理） |
| 规格字段顺序一致、扩展字段下游安全 | **证据**（逐字比对 + 解析模拟） |

*报告落盘：2026-09-10 · code-reviewer-15（s2-diag-review）· 纯本地只读，未改动任何原文件*
