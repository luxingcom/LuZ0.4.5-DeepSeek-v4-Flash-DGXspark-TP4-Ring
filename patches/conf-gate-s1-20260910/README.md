# Stage 1 补丁集 —— 置信头接线 + per-request 验证截短（含验证侧管线）

> **发布注记（2026-09-10）**：本 README 为内部工程文档的脱敏发布版。`base/` 与 `work/` 完整源文件（含内部路径形态）不入发布树；镜像 RepoDigest 以 `<BAKE_IMAGE_DIGEST>` 占位；补丁应用目标路径 = fork 内 `vllm/models/deepseek_v4/nvidia/dspark.py` 等五文件（见各 patch 头部）。现役镜像仅含主体 4 补丁（gate-off），`w5_diag.patch` 属 G2 开臂阶段可选项。

**日期**：2026-09-10 ｜ 编制：implementer-s1 ｜ 任务 #17
**基底**：S0/S0b 定谳的镜像构建版（digest <BAKE_IMAGE_DIGEST>，运行版与构建版逐字节一致，9/7 热补丁已 baked）
**基底 md5**（与本目录 `base/` 一致）：

| 文件 | 目标路径 | 基底 md5 |
|---|---|---|
| dspark.patch | `vllm/models/deepseek_v4/nvidia/dspark.py` | 497aad88e52ca3c54a3d4156326befa8 |
| dspark_speculator.patch | `vllm/v1/worker/gpu/spec_decode/dspark/speculator.py` | c291c3c43b8f5f724a91c97cbd344436 |
| scheduler_verify.patch | `vllm/v1/core/sched/scheduler.py` | 13e5cd2a8ffae3431a610c9680525432 |
| w1_glue.patch | `vllm/v1/outputs.py` + `vllm/v1/worker/gpu/model_runner.py`（新版 GPUModelRunner，非 legacy gpu_model_runner.py）+ `vllm/v1/engine/core.py` | outputs/gpu_model_runner_NEW/engine_core 三基底 md5 见 base/ 目录 |
| w5_diag.patch | `vllm/v1/core/sched/scheduler.py`（**增量**，见下方 ⚠️ 应用顺序） | 基底 = 应用 `scheduler_verify.patch` 之后的 scheduler.py（md5 `f95874aa23342a2292508aea4ad83775`）；补丁后 md5 `1c344c8284f566eb7dde4d3816691332` |

⚠️ **w5_diag.patch 是第五补丁，必须叠在 `scheduler_verify.patch` 之后**：三条 `[S1-DIAG]` 打点依赖 verify 补丁引入的 `_conf_gate` / `_conf_lengths` / `_conf_lengths_frame` 符号，无法对 base 原始 `scheduler.build.py` 单独套用。三个补丁（speculator/scheduler 取新版 + w5）无其它叠加顺序负担。

`work/` 目录为补丁后完整目标文件（`patch` 应用失败时的兜底替换物，内容与三补丁逐行对应）：
- `work/scheduler.py` = base + `scheduler_verify.patch`（md5 `f95874aa…`）
- `work/scheduler_diag.py` = base + `scheduler_verify.patch` + `w5_diag.patch`（md5 `1c344c82…`，DIAG 已并入的完整文件，可整体覆盖）

**应用方式**（构建上下文中，以 base 为基底）：
```bash
patch -p0 vllm/models/deepseek_v4/nvidia/dspark.py < dspark.patch
# 或直接用 work/ 三文件覆盖（已含全部改动，md5 见下）
# 第五补丁（叠在 scheduler_verify.patch 之后）：
patch -p0 vllm/v1/core/sched/scheduler.py < scheduler_verify.patch
patch -p0 vllm/v1/core/sched/scheduler.py < w5_diag.patch   # [S1-DIAG] 打点
```

**门控 env**（fork 惯例 os.environ 直读，无需改 envs.py；与现役 22 项 VLLM_* 无命名冲突，lead 已确认）：
- `VLLM_DSPARK_CONF_GATE=1`：总开关，**默认关**。关 = 模块不创建 / 无状态 / 无分支，G4 bit 级一致
- `VLLM_DSPARK_CONF_MIN=<float>`：截短阈值（默认 0 = 不截短，长度恒 k=6，可开臂观测）；G2-T4 扫 {0.1..0.9}

---

## 1. 数据流图（gate on）

```
━━━━━━━━ GPU（FULL graph 捕获内，形状固定 B×k，无分配/无同步）━━━━━━━━
dspark.py  forward → head_hidden [num_sample, H]（pre-norm，现成）
dspark_speculator.py  _sample_sequential 逐步循环 i=0..5:
    markov_embed = model.markov_embed(prev)          ← 原有代码
    ... gumbel_sample → draft_tokens[:, i]           ← 原有代码
  + conf_i = model.compute_confidence(sample_hidden[i::n_spec], markov_embed)
  + _conf_gpu_buf[:B, i] = conf_i                    ← 预分配 buffer 写入
━━━━━━━━━━━━━━━━━━━━━━━━━ capture 外（replay 尾） ━━━━━━━━━━━━━━━━━━━━
  + _conf_cpu_stage[step%2][:B].copy_(_conf_gpu_buf[:B], non_blocking=True)
  + _conf_d2h_events[step%2].record()                ← 零设备同步
                              │ stale 一拍
                              ▼
━━━━━━━━━━ CPU（scheduler，经 update_confidences 注入）━━━━━━━━━━━━━━━━
scheduler.py  schedule() 开头:
  + _conf_pull_lengths(): survival = cumprod(conf, fp64)
      l_r = 最长前缀使 survival ≥ CONF_MIN（thr=0 → l_r ≡ k）
调度循环 spec-token 段（唯一消费点，单点生效全链传播）:
  + l_r < num_scheduled_spec_tokens 时:
      num_new_tokens -= (截短数)          → KV 分配/token 记账同步缩小
      num_scheduled_spec_tokens = l_r     → scheduled_spec_decode_tokens 切短
      num_scheduled_tokens[req] 更新      → verify metadata query 数缩小
                                            → rejection sampler 按 l_r 消费
被截槽位留在 request.spec_token_ids，下一步重新验证（延迟≠丢失）
━━━━━━━━━ async 路径补丁（AsyncScheduler 继承复用，Rex 关键提示）━━━━━━
update_draft_token_ids_in_output 尾部:
  + guard：placeholder(静态 k) 替换回真 draft 后重施 l_r 截短，
    被截槽位填 -1 记入 num_invalid_spec_tokens
    → num_computed_tokens / num_output_placeholders 记账与截短 verify 一致
    （堵住 RFC #48202 fixed-shape async 记账坑）
```

## 2. 每文件改动点与行数

### dspark.patch（+82 行）
| # | 位置（锚点） | 改动 |
|---|---|---|
| 1 | `DSparkDeepseekV4Model.__init__`，markov_head 之后 | gate on 才创建 `confidence_head = ReplicatedLinear(4096+256, 1, bias=False, params_dtype=fp32, return_bias=False)`；gate off → None（state_dict/参数零增量） |
| 2 | `DSparkDeepseekV4ForCausalLM`，markov_bias 之后 | 新增 `compute_confidence(head_hidden, markov_embed)`：cat→fp32→proj→sigmoid，纯函数捕获安全 |
| 3 | `load_weights` 末尾，finalize_replication 之后 | gate on 但 checkpoint 无权重 → warning + `confidence_head=None` 自动降级（G1-T2 视为接线 bug 信号） |
| 4 | `_remap_dspark_name` 丢弃点（唯一字符串 `"The confidence head is not wired"`） | 无条件 `return None` → 条件化：头存在则映射 `model.{rest}`（#47808 同款改写），否则维持丢弃（gate off 字节级同路径） |

### dspark_speculator.patch（+100 行）
| # | 位置（锚点） | 改动 |
|---|---|---|
| 1 | docstring + imports | S1 机制说明；`import numpy as np`（get_stale_confidences 返回类型） |
| 2 | `__init__` 末尾 | gate on（= confidence_head 已接线）才预分配：`_conf_gpu_buf`[max_num_reqs,k] fp32 GPU、双 pinned CPU stage、双 cuda Event、步计数 |
| 3 | `_sample_sequential` 循环尾（`prev = draft_sampled_i` 之后） | 逐步 `compute_confidence(sample_hidden[i::n_spec], markov_embed)` 写入 GPU buffer；捕获内零分配零同步 |
| 4 | `_generate_draft` 尾部（capture 外） | 非阻塞 D2H 双缓冲 + event record + 步进 |
| 5 | 新增 `get_stale_confidences(num_reqs)` | event 级等待（host 等 D2H 完成，非 device 同步）返回 N-1 步 fp32 [B,k]；gate off / 首步返回 None |

### scheduler_verify.patch（+102 行）
| # | 位置（锚点） | 改动 |
|---|---|---|
| 1 | imports | `os`、`numpy` |
| 2 | `__init__` speculative_config 块尾（use_dspark 之后） | `_conf_gate`（=dspark + env=1 + k>0）、`_conf_min`、`_conf_lengths`、`_conf_snapshot` 状态；默认全空 |
| 3 | `schedule()` 开头 | `_conf_pull_lengths(len(self.running))`：survival=cumprod（fp64）→ thr 最长前缀长度；thr≤0 快捷恒 k；消费后清空 snapshot |
| 4 | 调度循环 spec-token 段（`num_scheduled_spec_tokens` 计算后） | **唯一截短消费点**：l_r<num_scheduled_spec_tokens 时同步缩小 num_new_tokens / num_scheduled_spec_tokens / num_scheduled_tokens —— KV 分配、spec 切片、verify metadata、rejection sampler 全链自动传播 |
| 5 | 新增 `_conf_pull_lengths` / `update_confidences` | worker→scheduler 置信分注入接口（P1 async 定谳后的 metadata/状态通道，单路径） |
| 6 | `update_draft_token_ids_in_output` 尾部 | **async placeholder guard（Rex 关键提示）**：静态 k placeholder 替换后重施 l_r 截短，被截槽位 -1 记入 num_invalid_spec_tokens，修正 num_computed_tokens/num_output_placeholders 记账 |

合计 **+284 / −2 行**（v2 方案 §1.1 预算 150-250 行上缘略超，超出部分主要在注释与 async guard——后者是 P1 定谳后新增的必要面）。

> 本表为**前三补丁**（dspark / dspark_speculator / scheduler_verify）的改动点；`w1_glue.patch` 见 §3，`w5_diag.patch`（第五补丁，DIAG 打点）见 §3.2。

## 3. w1_glue.patch：worker→scheduler 注入通道（A' 方案，Rex 定谳）

W1 已由 A' 方案落地（第四补丁，2026-09-10 补齐），替代本节原"待接线"状态：

| # | 文件 | 改动 |
|---|---|---|
| 1 | `vllm/v1/outputs.py` | `ModelRunnerOutput` dataclass 尾部（routed_experts 后）加 `stale_dspark_confidences: Any \| None = None`——随既有序列化输出流穿过 AsyncGPUModelRunnerOutput.get_output()，零新 RPC 零 device sync |
| 2 | `vllm/v1/worker/gpu/model_runner.py` | sample_tokens() 的 ModelRunnerOutput 构造（基底 L1457，propose **之前**）加 kwarg：`getattr(self.speculator, "get_stale_confidences", None) is not None and self.speculator.get_stale_confidences(len(input_batch.req_ids))`——gate off 内部自返 None；挂在 `self.speculator`（非 self.drafter，本 fork 无该属性，Rex 实测修正）；注意旧版 legacy `vllm/v1/worker/gpu_model_runner.py` 本栈不走其 speculative 路径，不覆盖 |
| 3 | `vllm/v1/engine/core.py` | 两处 ModelRunnerOutput 物化点（step() update_from_output L605 前 + step_with_batch_queue() async 物化点 L719-724 前）各回调 `scheduler.update_confidences(model_output.req_ids, model_output.stale_dspark_confidences)`——放 core.py 而非 update_from_output 内部：async 在后者拿到的是 AsyncModelRunnerOutput 包装；post_step 在 async 被显式跳过且 take_draft_token_ids 走 collective_rpc 同步 barrier，不可照抄（注释已写明否决理由 + async 2-step stale 时序注记） |

时序语义：构造点在 propose 前 → 注入的是 N-1 步（speculator 内部双缓冲再滞后一拍）的置信分；async 下最坏 2-step stale——损最优化不损正确性（任意长度选择都是合法拒绝采样）。

**自验（第四补丁专项）**：
- 第四跳落点 ✅：get_stale_confidences（worker）→ ModelRunnerOutput 字段（序列化）→ engine_core 两物化点（同步+async 双路径全覆盖）→ scheduler.update_confidences → _conf_pull_lengths → 截短消费点，全链闭合
- gate off 零行为 ✅：字段默认 None（dataclass 序列化恒 None）；model_runner 侧 getattr 判定下非 DSpark speculator（eagle/mtp）恒 None；engine_core 侧 `is not None` 守卫恒假 → 不调用 update_confidences；scheduler 侧 update_confidences 自带 gate 判断。三层守卫无任何 gate off 新执行
- 语法 ✅：三文件 ast.parse 全过；补丁由 base→work 全量 diff 生成可回放

## 3.1 历史记录：W1 原开放项描述（已被 A' 闭合）

scheduler 侧入口 `update_confidences(req_ids, confidences)` 与 worker 侧出口 `speculator.get_stale_confidences(num_reqs)` 均已就位，但 **worker 出口 → scheduler 入口的每步调用粘合点在 model_runner / 引擎输出泵（本任务基底四文件之外）**。这是 S1 剩余的唯一跨层接线，两种落法（约 10-20 行，在 model_runner.py 或 async output 处理路径中）：

- 落法 A：model_runner 每步 propose 后调 `get_stale_confidences(num_reqs)`，随 ModelRunnerOutput 带回 scheduler（`update_from_output` 时调 `update_confidences`）——干净但需给 ModelRunnerOutput 加字段；
- 落法 B：scheduler 侧持 worker 代理引用直接拉取——侵入小但引入跨对象耦合。

~~**当前默认安全**：未接线时 `update_confidences` 永不被调 → `_conf_lengths` 恒空 → 截短恒不触发 → 行为=门控开但零截短（thr=0 等价态），G1/G4 门不受影响。~~ → 已按落法 A 变体（A'）闭合，见 §3。

## 3.2 w5_diag.patch：三条 `[S1-DIAG]` 打点（F2/F3/F9 出口，G2 前置 P1）

第五补丁（2026-09-10 补齐，此前**未产出**）。落地 `g2-preflight-ab-design §3.1` 的三条打点，是 G2 CONF_MIN=0.1 单请求 A/B 对拍 **F2/F3/F9 三支柱的唯一数据源**，亦是 P10 (ii)「`l_r<k`」判据的唯一来源（见 `g2-open-arm-readiness-2026-09-10.md` P1 → P10 串行依赖）。

**改动点（全部落在 `scheduler.py`，纯增量 +99 行、0 删 0 改）**：

| # | 落点（补丁后行号） | 打点 | 消费判据 |
|---|---|---|---|
| 1 | 调度循环头（截短已作用、`allocate_slots` 前，L598） | `[S1-DIAG] step=%d req=%s l_r=%s spec_sched=%d num_new_tokens=%d budget_before=%d conf_step=%d used_step=%d` | F3/F4/F5 + P10 (ii) `l_r<k` + P4 lag(`used_step-conf_step≥1`) |
| 2 | 冻结帧快照点（`_conf_lengths_frame` 构造之后，L1303） | `[S1-DIAG] frame=%s` | F2（与 F3 长度比对，`len(frame[req])==len(scheduled_spec_decode_tokens[req])`） |
| 3 | `update_draft_token_ids_in_output` 尾（async guard 之后，L2390） | `[S1-DIAG] invalid=%s` | F9（async 期望 >0；非 async >0 = FAIL） |

辅助：新增 `_diag_frame_str()`（帧 dict 的紧凑确定性渲染）；`__init__` 增 `_conf_conf_step` 步戳，`update_confidences` 记收帧步、`_conf_pull_lengths` 消费后可算 lag。

**硬约束逐条落实**：

- **gate off 零输出**：三处打点均在 `if self._conf_gate:` 内。静态核查证明本补丁**不删除、不修改任何原有语句行**（delimiter 比对：deleted/replaced original lines = 0），gate off 语句流与原版逐语句等价 → 满足 G4-T1 判据 (ii)。
- **日志级别 = `logger.debug`**：第 1 条每步每已调度请求触发（内循环尾部，热路径），`info` 会淹没默认 INFO 日志；而采集协议（`g2-preflight §3.1` P2 / `readiness §3` 阶段 2.2）**本就要求 `VLLM_LOGGING_LEVEL=DEBUG`**，故 `debug` 既是预期开关又是默认最省档。
- **不用 print**：`print` 写 stdout 可能在热路径触发流刷新 / host sync，本栈为 b12x CUDA graph 静态捕获架构不可接受。打点只格式化**已在 CPU 侧物化的记账量**（int / 请求 id 字符串），**不引入任何新的 device 同步**（无 `.item()` / 无 `.cpu()` / 无 tensor 入参）。
- **前缀逐字节精确** `[S1-DIAG]`：三条格式串已核对 verbatim（`grep "\[S1-DIAG\]"` 直接命中）。
- **帧快照仅 gate on**：`frame` 行的实参 `_conf_lengths_frame` 本身仅 gate on 时非空，双重保证。

**自验（全过）**：

1. `ast.parse`（补丁后完整文件，3104 行）✅
2. dry-run 回放：`base → scheduler_verify.patch → w5_diag.patch` 链式，6/6 hunk 全中、**零 fuzz 零 offset** ✅
3. 实套用后 md5 = `1c344c8284f566eb7dde4d3816691332`，与目标逐字节 `cmp` 一致 ✅
4. gate off 静态核查：新增/替换 99 行中 3 处 `logger.debug` 调用，逐处位于 `if self._conf_gate:` 守卫内一层缩进 ✅
5. 三条格式串 verbatim 命中 + 渲染样例通过（`l_r<k`、lag≥1 语义可表达）✅

**镜像落地判据（E0-d 纪律）**：rebuild 后镜像内 `scheduler.py` md5 必须 == `1c344c8284f566eb7dde4d3816691332`（**不可用 boot grep `[S1-DIAG]`**——该行须有请求经过 scheduler 才输出，boot 必为空，见 `readiness §3` 阶段 2.2）。

## 4. 自验结论（§8 checklist 逐条）

1. **数据流完整性** ✅：head→`compute_confidence`→`_conf_gpu_buf`（捕获内）→`_conf_cpu_stage`（D2H）→`get_stale_confidences`→`update_confidences`→`_conf_pull_lengths`→`_conf_lengths`→调度消费点（num_new_tokens/spec 切片/verify metadata 三处同源）→rejection sampler，每跳有落点、每跳有 gate 短路。唯一开放跳：worker→scheduler 粘合（§3，安全默认）。
2. **gate off 零行为** ✅：dspark——模块不创建（state_dict 无新键、remap 维持原丢弃、无降级逻辑触发）；speculator——`_conf_enabled=False`，不分配 buffer、循环内与 replay 尾分支全短路、`get_stale_confidences` 返回 None；scheduler——`_conf_gate=False`，`_conf_pull_lengths`/消费点/guard 三处全短路，无新张量、无新导入副作用（os/numpy 为 stdlib/必装依赖）。逐行核对无 gate off 新执行路径。
3. **贪心不变性**（G2-T4 前提）✅：截短只改 `scheduled_spec_decode_tokens` 长度记账（-1 填充复用 grammar-invalid 既有语义），不触 draft 采样、不触目标 logits、不触 rejection sampler 算法本体；l_r 位内贪心验证路径与全 k 逐位相同；门控开 + CONF_MIN=0 时长度恒 k = 完全恒等。
4. **捕获安全** ✅：捕获区内仅 `_conf_gpu_buf` 定形写入（预分配、固定 [max_num_reqs,k]）与一次 `compute_confidence`（无分配的 cat/proj/sigmoid）；D2H 与 event 均在 `_generate_draft` 尾（replay 入口之后、capture 外）；形状恒 B×k，不新增捕获档。
5. **降级路径** ✅：gate on + 权重缺失 → load_weights 末尾 warning + `confidence_head=None` → speculator `_conf_enabled=False` + scheduler remap 回丢弃 → 行为回到 gate off 等价态。

静态检查：三文件 `ast.parse` 全过；三补丁由 base→work 全量 diff 生成，可回放（`patch -R` 干跑验证建议部署窗口前由 SRE 在容器内执行一次 `patch --dry-run`）。

## 5. 剩余待验项（部署窗口 G 门裁决，不阻塞补丁合入）

| # | 项 | 裁决点 |
|---|---|---|
| V6→已闭合 | bf16→fp32 上转 bit-exact | fp32 是 bf16 的精确超集（float32 尾数 24 bit ⊇ bf16 8 bit，上转无舍入），本项解析闭合；G1-T2 加载日志 + G2 数值对拍兜底 |
| W1→已闭合 | worker→scheduler 注入粘合 | 已按 A' 方案落 w1_glue.patch（§3） |
| W2 | `params_dtype=fp32` 在 fork ReplicatedLinear 的实际加载 dtype | G1-T2 boot 日志置信头加载实锤一并核验 |
| W3 | FULL graph 捕获时 `_generate_draft` 尾部 D2H 代码是否被卷入捕获 | G1-T3 捕获统计 + 冒烟；理论上 replay 入口在捕获外（cudagraph manager 只包住 `_run_model`+采样），若卷入则把 D2H 移至 propose 调用方（一行级调整） |
| W4 | 全量 22 项现役 env 与新门控共存 | G1-T5 门控关臂基准（回归 ≤1.1%）实测兜底 |

## 6. 验收门映射（qa-program G1-G4）与评审修复记录

### 评审修复（fix_conf_gate，2026-09-10，Cody 评审 P0×2+P1×2+P2）

**结论**：gate-off PASS（G4 成立）；gate-on 修复后放行 CONF_MIN>0。修复以**更新版
dspark_speculator.patch / scheduler_verify.patch** 形式交付（原两补丁作废，SRE 直接取
base→新版重放，无叠加顺序负担），逐 hunk 清单见 `fix_conf_gate-NOTES.md`。

| 项 | 缺陷 | 修复 | 落点 |
|---|---|---|---|
| P0-1 | `_conf_enabled` 在 `__init__` 判定，但 `self.model` 于 load_model 后才存在 → gate on 恒死路 | 判定+buffer 分配移至 `load_draft_model` 尾，用局部 `model`（未来 self.model）判定 + logger.info（G1-T2 消费） | dspark_speculator.patch |
| P0-2 | 截短在 allocate_slots 之后 → KV 按全 k 分配 + token_budget 多扣 | 截短上移至 num_new_tokens 定型区（allocate_slots 前），KV 量与预算扣减同源一致；截短未调度 spec tokens 回填 request.spec_token_ids 下步重验 | scheduler_verify.patch |
| P1-1 | "KV 全链自动传播"表述过强 | 注释改写：省 verify 计算；KV 自 P0-2 后按 l_r 分配 | scheduler_verify.patch |
| P1-2 | async guard 用 live `_conf_lengths`，batch queue 交错下 -1 记账错配 | schedule() 末尾冻结当帧快照 `scheduler_output._conf_lengths_frame`，guard 改读冻结帧 | scheduler_verify.patch |
| P2-1 | 双缓冲视图可能被覆写 | update_confidences 改 `np.array(..., copy=True)` | scheduler_verify.patch |
| P2-2 | l_r 命中率记录 | 未采纳：G3 数据可由 verify 长度分布推得，避免热路径计数开销 | — |

### 门映射

- G1-T2：dspark 改动 1/3/4 的加载实锤与降级 warning 语义直接对应；P0-1 修复后 speculator 侧新增 info 日志为第二实锤
- G4-T1：约束 2（gate off 零行为）+ remap 字节级同路径；P0-1 修复后 gate off 仍零分配零判定（`_conf_enabled=False` 静态占位）
- G4-T3：env 清除点（systemd/guard 层）回退清单项，SRE 部署项
- G2-T4：CONF_MIN 五档扫描直接可用；贪心不变性 = 约束 3
- G3-T1/T2/T4：update_confidences→截短链路 + CONF_MIN 阈值响应；P0-2 修复后 G3-T4 step-time 单调性检验才真正有效（截短前 KV 已按 l_r 收缩）；step-time 实测裁决截短是否真省算力（档位 padding 风险依方案 v2 §4 如实记录）
- **G2 前置 P1（`[S1-DIAG]` 打点，w5_diag.patch）**：F2（`frame=`）/ F3（`spec_sched=`）/ F9（`invalid=`）出口，见 §3.2；P10 (ii) 行为级实锤（`l_r<k`）与 P4 lag（`used_step-conf_step≥1`）的唯一数据源。落地判据 = 镜像内 scheduler.py md5 == `1c344c82…`（E0-d 纪律）
- G4-T1（w5 专项）：打点全部在 `if self._conf_gate:` 内，且补丁零删零改原有语句行 → gate off 语句流逐行等价

---
*补丁基底与目标路径以 S0-VERDICT.md 为准；qwen3_dspark 变体在本 fork 不存在（S0 定谳），无连带改动。*
*2026-09-10 追加：第五补丁 `w5_diag.patch`（`[S1-DIAG]` 三条打点，G2 前置 P1 补齐）已产出并归档，见 §2 表尾与 §3.2；此前该补丁只存在于设计文档、未产出（判定 (b)）。补丁零删零改原有语句行，打点全部在 `if self._conf_gate:` 守卫内。*
