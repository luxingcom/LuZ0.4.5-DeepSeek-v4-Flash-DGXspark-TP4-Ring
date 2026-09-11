# Stage 1 补丁草案先行版——置信头接线 + per-request 截短（含验证侧管线）

**日期**：2026-09-10 ｜ 编制：implementer-s1 ｜ 任务 #17（S1 实现草案先行版，不等 S0）
**依据**：conf-head-adaptive-verification-plan v2 §1、confidence-head-field-analysis（实地证据）、qa-program G1-G4、adaptive-verification-research（#47808 / RFC #48202）
**代码基底现状**：本地无生产 fork 源码树。唯一本地参照 `g1r3-e-base/dspark.py`（491 行，构建版基底；生产运行版 542 行，差 9/7 热补丁内容——**S0 diff 未到手，本文一律用唯一字符串锚点定位，不写死行号**）。
**诚实纪律**：所有标注 ⚠️待服务器核验 的位置，落真补丁前必须以 SRE 容器内 grep/diff 结果定谳；本文不给猜测行号。

---

## 0. 设计总原则（对应 v2 审计硬条件）

| 约束 | 本文落实 |
|---|---|
| C1 验证侧管线必须真通到调度 | §3 专章：speculator 置信分 → D2H 双缓冲 → scheduler per-request 长度向量 → verify metadata（query_start_loc/num_draft_tokens）→ rejection sampler 变长消费，四跳各有落点 |
| D2H 禁 graph 内同步 | §2.3 stale 双缓冲（#47808 同款）：graph 内只写 GPU buffer，D2H 在 capture 外的非阻塞拷贝 + event，CPU 用 N-1 步置信分调度 N 步长度 |
| 固定张量形状 | 捕获形状恒为 B×(1+6)，长度向量是 capture 外可更新的持久输入缓冲内容（RFC #48202）；不新增/不删除捕获档 |
| G2-T4 贪心不变性 | 截短只改 verify 记账长度（num_draft_tokens），不改 draft 采样与目标 logits 计算；门控开但 thr=0（默认）时长度向量恒 k = 行为零变化 |
| env 门控默认关 | `VLLM_DSPARK_CONF_GATE` 默认 off：confidence_head 子模块不创建、remap 不改语义、speculator 不进新分支——**逐代码路径确认 gate off 时零新增执行**（G4 bit 级一致的最强保证） |
| `VLLM_DSPARK_CONF_MIN` | 截短阈值，默认 0.0（=不截短，长度恒 k）；仅 gate on 时生效 |

---

## 1. 数据流总图（gate on 全链路）

```
                     ┌────────────── GPU（graph 捕获内，形状固定） ──────────────┐
 target 前向 aux hidden│                                                         │
   │                  │  dspark draft 骨干 forward → head_hidden [B*k, H]        │
   ▼                  │  _sample_sequential 循环 i=0..k-1:                        │
 speculator           │    markov_embed_i = markov_embed(prev)   ←（现已在算）      │
   _run_model ───────►│    logits_i = base_logits[:,i] + markov_bias_i            │
                      │    prev = gumbel_sample(logits_i)                         │
                      │    [新] conf_i = compute_confidence(head_hidden_i,        │
                      │              markov_embed_i) → 写入 _conf_gpu_buf[:, i]    │
                      │                                                         │
                      │  graph replay 结束（capture 外）:                          │
                      │    cpu_stage[step%2].copy_(_conf_gpu_buf,                 │
                      │        non_blocking=True)  + event.record()  ← 不阻塞     │
                      └────────────────────────────┬────────────────────────────┘
                                                   │ D2H（stale 一拍）
                                                   ▼
                     CPU: scheduler 拿上一步 cpu_stage[(step-1)%2]（event 已完成的）
                       survival = cumprod(conf, dim=1)             ← #47808 公式
                       L_r = 1 + #{j: survival[r,:j] ≥ CONF_MIN}，clamp ≤ k
                        （thr=0 → L_r ≡ k → 与现役记账完全一致）
                                                   │
                                                   ▼  per-request 长度向量 L[B]
                     scheduler（消费点，⚠️待核验是否需走 metadata 通道见 §4）
                       ├─ verify metadata: num_draft_tokens = L
                       │    query_start_loc / cu_num_logits 按 L 截短
                       ├─ draft_token_ids 切片 [:, :L_r] 供验证
                       └─ rejection sampler: 变长 num_draft_tokens 消费
                            （贪心+前缀全接受场景输出 = 全接受前 L_r 个，路径不变）
```

**省算力机制说明（诚实批注）**：FULL graph 内 target verify 前向仍按 B×7 静态形状重放；截短省的是
(a) rejection sampler 消费与记账（被截位置恒判拒绝，无 bonus）；
(b) **若** attention metadata（query_start_loc / seq_lens）是 capture 外可更新缓冲且 SM121 MLA kernel 尊重 per-request q_len（#47808 varlen 前提，#48202 prototype 依赖同款），则 attention/MoE 对 0 长度位置实际短路。
(b) 是否成立是 G3-T4（step-time 单调性）要实测裁决的——本草案按"先通记账、(b) 顺带获得"设计，与 QA 程序 G3-T4 的判定方法完全对齐。若 (b) 不成立，G3 判"收益不成立"，不是安全问题。

---

## 2. 文件一：`vllm/models/deepseek_v4/nvidia/dspark.py`

锚点基线 = 本地 `g1r3-e-base/dspark.py`；生产运行版行号会漂移（542 行），**补丁全部用锚点上下文**。

### 2.1 `DSparkDeepseekV4Model.__init__` —— 置信头子模块（gate on 才创建）

锚点：`self.markov_head = DSparkMarkovHead(` 代码块之后、`def embed_input_ids` 之前插入。

```python
# [S1] Confidence head (DSpark AcceptRatePredictor). Created only when the
# gate is on; weights are mtp.last.confidence_head.proj.weight (4352->1).
# Gate off => attribute is None => zero behavioral/param delta (G4 bit-identical).
conf_gate = envs.VLLM_DSPARK_CONF_GATE  # 新增 env，vllm/envs.py（见 §5）
self.confidence_head = None
if conf_gate:
    self.confidence_head = ReplicatedLinear(
        config.hidden_size + config.dspark_markov_rank,  # 4096 + 256 = 4352
        1,
        bias=False,
        dtype=torch.float32,          # 参考实现 model.py L855-864：fp32 proj
        return_bias=False,
        prefix=maybe_prefix(prefix, "confidence_head"),
    )
```

要点：
- `ReplicatedLinear` 已在本文件 import（本地基线 L32）。
- 权重 bf16→fp32 上转由 `dtype=torch.float32` 参数化交给 weight_loader；bit-exact 上转小验证列入 S1 实现第一步（QA 程序 §6 "fp32 加载 bit-exact 小验证"）。⚠️待服务器核验：fork weight_loader 对 dtype 参数化的上转行为（对照参考实现 L860 注释语义）。
- gate off → `self.confidence_head is None` → 模块不创建、state_dict 无新参数、checkpoint 权重走 §2.2 丢弃分支（与现役逐字节同路径）。

### 2.2 `_remap_dspark_name` —— 条件化丢弃

锚点（本地基线 L474-476）：
```python
        # The confidence head is not wired into inference yet; drop its weights.
        if rest.startswith("confidence_head."):
            return None
```
改为（#47808 同款改写）：
```python
        # [S1] Confidence head: drop only when not wired (gate off / degraded).
        if rest.startswith("confidence_head.") and self.model.confidence_head is None:
            return None
        if rest.startswith("confidence_head."):
            return f"model.{rest}"   # -> model.confidence_head.proj.weight
```
- `_remap_dspark_name` 是 `DSparkDeepseekV4ForCausalLM` 的方法，`self.model` 即 DSparkDeepseekV4Model，可直接判 None。⚠️待服务器核验：生产运行版热补丁是否已改动此函数体（S0 diff）。
- **自动降级**：gate on 但 checkpoint 无该权重 → `load_weights` 末尾检查 `loaded_params` 无 `model.confidence_head.proj.weight` 时打 `logger.warning` 并置 `self.model.confidence_head = None`（QA 程序 G1-T2 把该 warning 视为接线 bug 信号，符合预期语义）。

### 2.3 `DSparkDeepseekV4ForCausalLM` 新增 `compute_confidence`

锚点：`def markov_bias(...)` 方法之后插入（与 markov 系列钩子同区，speculator 钩子区）。

```python
    def compute_confidence(
        self, head_hidden: torch.Tensor, markov_embed: torch.Tensor
    ) -> torch.Tensor | None:
        """[S1] Per-position acceptance confidence, P(accept | prefix accepted).

        head_hidden: pre-norm hc_head output [T, hidden_size]（forward 原样返回值）
        markov_embed: 该采样步的 markov 嵌入 [B, dspark_markov_rank]
        Returns fp32 [B] 或 None（头未接线）。
        Mirrors /models/inference/model.py L906-924 (cat -> fp32 proj -> sigmoid).
        """
        if self.model.confidence_head is None:
            return None
        # head_hidden 为 [B*k, H] 平铺；本方法按整块 [T, H] 投影，分步切片由
        # speculator 侧负责（speculator 知道 B 与 k 的切分）。
        x = torch.cat([head_hidden, markov_embed_expanded], dim=-1)
        logits = self.model.confidence_head(x.float())          # fp32
        return torch.sigmoid(logits.squeeze(-1))                # fp32 [T]
```

- `markov_embed_expanded`：markov_embed 是 [B, rank] 每请求一维，head_hidden 是 [B*k, H] 每位置——参考实现里 forward_head 拿的是 stack 后对齐形状。**对齐方式（广播到 k 个位置 vs 每步单独投影）⚠️待服务器核验**：参考实现 `/models/inference/model.py` L906-924 原文（SRE 已可只读 cat，实地报告 §3 确认 `confidence = self.confidence_head(x, markov_embed)`，x 是 hc_head 输出、markov_embed 是 stack 后每步嵌入）——真补丁落笔前取该函数逐行语义定谳。倾向：每步 `i` 对该步的 k 个候选位置共享同一个 markov_embed_i，即 cat([hidden_slice_i, markov_embed_i.expand(k, -1)])。此形状问题影响 `x.float()` 的输入形状，不影响门控与数据流。
- 计算发生在 `_sample_sequential`（调用方），本方法保持纯函数（无 buffer 写入、无同步），保证可被 graph 捕获且门控关时不被调用。

---

## 3. 文件二：`vllm/v1/worker/gpu/spec_decode/dspark/speculator.py`

⚠️本地无此文件，以下以实地报告 §3 给出的结构（`_sample_sequential` L108-152 循环内已有 `markov_embed = self.model.markov_embed(prev)`、`logits_i = base_logits[:,i] + bias`、`gumbel_sample`；`_generate_draft` L154-168 = `_run_model` → `_sample_sequential`）为锚点设计。真补丁前须 SRE 提供 `sed -n '1,200p'` 全文或 S0 侧 `cat`。

### 3.1 `__init__` / graph 初始化 —— 预分配缓冲

锚点：`init_cudagraph_manager` 或等价捕获初始化处（⚠️待核验确切函数名）。

```python
        # [S1] Confidence staging buffers (gate on only).
        self._conf_enabled = envs.VLLM_DSPARK_CONF_GATE
        if self._conf_enabled:
            k = self.num_speculative_tokens            # 6，捕获形状不变
            max_b = self.cudagraph_max_capture_size    # ⚠️待核验属性名
            # GPU 侧：graph 捕获内写入，无动态分配
            self._conf_gpu_buf = torch.zeros(max_b, k, dtype=torch.float32,
                                             device=self.device)
            # CPU 侧：stale 双缓冲（#47808 同款，一拍滞后）
            self._conf_cpu_stage = [torch.zeros(max_b, k, dtype=torch.float32,
                                                pin_memory=True) for _ in range(2)]
            self._conf_d2h_events = [torch.cuda.Event() for _ in range(2)]
            self._conf_step = 0
```

### 3.2 `_sample_sequential` —— 循环内收集置信分写 GPU buffer

锚点：循环体内 `markov_bias` / `gumbel_sample` 行之后。

```python
            # [S1] per-step confidence; write into preallocated GPU buffer
            # (capture-safe: fixed shape, no allocation, no sync).
            if self._conf_enabled and self.model.confidence_head is not None:
                conf_i = self.model.compute_confidence(
                    head_hidden_slice_for_step_i, markov_embed_i)
                self._conf_gpu_buf[:B, i] = conf_i.view(B)   # [S1-A] 形状对齐见 §2.3 待核验
```

- `head_hidden_slice_for_step_i`：draft 骨干一次 forward 产出整块 [B*k, H]，逐步采样在第 i 步消费的 hidden 切片是哪一段——⚠️待服务器核验（需 speculator 全文确认 `_run_model` 输出与逐步的对应关系；实地报告 §3 确认"接线所需中间量均存在"）。
- 若 fork 的 `_sample_sequential` 是逐样本（per-request）内层循环（实地报告 §3 措辞"逐样本循环里 markov_embed 已经在算"），则写入方式改为 `self._conf_gpu_buf[b, i] = conf_i`，语义等价。⚠️待核验循环结构。

### 3.3 `_generate_draft` 尾部 —— capture 外非阻塞 D2H + stale 消费接口

锚点：`_generate_draft` 返回 draft token ids 之前。

```python
        # [S1] Non-blocking D2H of the confidence buffer (capture-external).
        if self._conf_enabled and self.model.confidence_head is not None:
            idx = self._conf_step % 2
            self._conf_cpu_stage[idx].copy_(self._conf_gpu_buf[:B],
                                            non_blocking=True)
            self._conf_d2h_events[idx].record()
            self._conf_step += 1
```

```python
    def get_stale_confidences(self, num_reqs: int) -> np.ndarray | None:
        """[S1] Last-completed-step confidence [num_reqs, k] fp32 (numpy view).

        Consumer (scheduler via model_runner) must wait on the matching event
        before reading. One-step-stale by design (#47808 stale double buffer).
        """
        if not self._conf_enabled or self.model.confidence_head is None:
            return None
        idx = (self._conf_step - 1) % 2
        self._conf_d2h_events[idx].synchronize()   # event 级等待，非 device 同步
        return self._conf_cpu_stage[idx][:num_reqs].numpy()
```

- `synchronize()` 是 Event 对象等待（host 等 D2H event 完成），不是 `torch.cuda.synchronize()` device 级停摆——事件通常在调度间隙已自然完成，stall 风险≈0（#47808 专用 stream + event 同款机制）。⚠️待核验：fork 是否有专用 copy stream 基建可复用（async_utils.py），无则默认 current stream 亦可（capture 外）。
- graph replay 路径下 `_generate_draft` 是"replay 封装"，D2H 代码必须在 replay 调用之后（capture 外）。⚠️待核验 FULL graph 模式下 `_generate_draft` 的 replay 分支结构。

### 3.4 门控关路径自查承诺

`_conf_enabled=False` 时：3.1 不分配、3.2 分支短路、3.3 分支短路、`get_stale_confidences` 返回 None 且 scheduler 侧（§4）对 None 走原路径。无任何新增张量操作进入采样热路径。

---

## 4. 文件三（验证侧管线）：scheduler → metadata → rejection sampler

**这是 v1 被审计打回的遗漏面，v2 C1 硬条件**。⚠️本地无 scheduler.py/rejection_sampler.py 源码，锚点基于实地报告（scheduler.py L243-245 已有 `num_speculative_tokens_per_batch_size` 按档调整逻辑）与 #48202 记账坑。真补丁前需 SRE grep 清单（§6）结果。

### 4.1 长度向量计算（scheduler 侧或 AdaptiveVerification-lite 辅助模块）

```python
# [S1] per-request verify length from stale confidences.
# survival = cumprod(conf)  (#47808 formula); L = max prefix length whose
# survival >= VLLM_DSPARK_CONF_MIN, clamped to [1?, k]. thr=0 => L == k.
def compute_request_lengths(stale_conf: np.ndarray, k: int, thr: float) -> np.ndarray:
    survival = np.cumprod(stale_conf.astype(np.float64), axis=1)   # [B, k] 单调递减
    if thr <= 0.0:
        return np.full(stale_conf.shape[0], k, dtype=np.int32)     # 恒等快捷路径
    ok = survival >= thr
    lengths = ok.cumsum(axis=1).argmax(axis=1) + 1                 # 最长 True 前缀
    lengths[~ok[:, 0]] = 1                                         # 首位不达标 → 只验证 1
    return np.minimum(lengths, k).astype(np.int32)
```

- 首位为 0 置信的请求 L=1（仍验证 bonus 位，保证请求每步至少前进判定位；具体下界语义 ⚠️待核验 scheduler 对 num_draft_tokens≥1 的约束）。
- **stale 一拍的安全性**：置信分变化平缓（实测先验：DSpark 论文置信分布连续），一拍滞后最坏造成次优长度，不造成正确性问题（截短多/少都是合法拒绝采样）。

### 4.2 消费点接线（三处，锚点全待服务器核验）

| # | 消费点 | 改动 | 锚点 |
|---|---|---|---|
| ① | scheduler 调度循环（实地报告：scheduler.py L243-245 附近已有动态 k 档表逻辑） | 在既有 num_draft_tokens 决定处叠加：`if gate and stale_conf is not None: num_draft_tokens = compute_request_lengths(...)`（per-request 向量替换标量） | `num_speculative_tokens_per_batch_size` / `num_draft_tokens` 于 `vllm/v1/core/sched/scheduler.py` |
| ② | verify metadata 构建（SpecDecodeMetadata / attention metadata builder） | `query_start_loc`、`cu_num_logits` 按 L 截短；`draft_token_ids[r] = draft_token_ids[r][:L_r]` | `grep -rn "num_draft_tokens" vllm/v1/` |
| ③ | rejection sampler | 确认其已按 per-request `num_draft_tokens` 变长消费（v1 主线 rejection_sampler 支持 per-request 变长，eagle 路径先例）；**贪心+前缀全接受时输出不变性自验**：L_r 截短 = 把第 L_r..k 位标记为拒绝，贪心比较路径前 L_r 位与全 k 验证完全相同 | `vllm/v1/spec_decode/rejection_sampler.py` |

### 4.3 async 调度路径（P1 定谳前的双分支设计）

RFC #48202 实锤的坑：**默认 async 路径下改 DraftTokenIds 不影响验证/调度记账**。因此：

- **若 fork 未启用 async 调度**（P1 结论 = 同步路径）：§4.2 ① 的 scheduler 直接改 num_draft_tokens 即生效。
- **若启用 async**：per-request 长度必须走 metadata 通道——speculator 产出的置信分经 model_runner 打入 `SpecDecodeMetadata`（或等价 EngineCore metadata 结构），scheduler 从 metadata 读长度，**不依赖 DraftTokenIds 对象**。改动点 ②③ 不变，① 的落点换成 metadata 构建函数。
- 双分支以一个薄适配函数 `resolve_conf_lengths(...)` 收敛，P1 定谳后只接线一支，另一支留 TODO 删除。

---

## 5. env 门控（vllm/envs.py）

```python
# [S1] DSpark confidence-gated adaptive truncation (Stage 1).
VLLM_DSPARK_CONF_GATE: bool = False   # 默认关 = 行为与现役 bit 级一致
VLLM_DSPARK_CONF_MIN: float = 0.0     # 截短阈值；0.0 = 不截短（长度恒 k）
```

- 环境定义格式 ⚠️待核验 fork envs.py 的注册约定（部分版本要求 environment_variables 装饰器清单）。
- G2-T4 的 5 档扫描（thr∈{0.1..0.9}）直接用 `VLLM_DSPARK_CONF_MIN`，无需代码改动。
- 回退清单须含 systemd/guard 层 env 清除点（v2 R12，SRE 部署项）。

---

## 6. async 路径核验问题清单（P1，转 SRE 容器内执行）

> 以下全部只读命令；结果回传 implementer-s1 落真补丁。

```bash
# A. async 调度启用状态（P1 主问题）
grep -rn "async_scheduling" /usr/local/lib/python3.12/dist-packages/vllm/config/scheduler.py
grep -n "async.schedul\|async-schedul" /etc/systemd/system/vllm-tp4-head.service /etc/systemd/system/vllm-tp4-worker.service 2>/dev/null
grep -rn "async_scheduling\|AsyncScheduler" /usr/local/lib/python3.12/dist-packages/vllm/v1/core/sched/ | head -20

# B. DraftTokenIds 记账链（#48202 坑）
grep -rn "DraftTokenIds\|draft_token_ids" /usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu/model_runner.py | head -30
grep -rn "class DraftTokenIds" /usr/local/lib/python3.12/dist-packages/vllm/v1/

# C. num_draft_tokens 消费链
grep -rn "num_draft_tokens" /usr/local/lib/python3.12/dist-packages/vllm/v1/core/sched/scheduler.py
grep -rn "num_draft_tokens" /usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu/spec_decode/ | head -30
grep -rn "num_draft_tokens" /usr/local/lib/python3.12/dist-packages/vllm/v1/spec_decode/rejection_sampler.py | head -20

# D. 动态 k 基建（实地报告 §4 的 uses_dynamic_speculative_decoding 分支）
grep -rn "num_speculative_tokens_per_batch_size\|uses_dynamic_speculative_decoding" /usr/local/lib/python3.12/dist-packages/vllm/ | head -10
sed -n '230,260p' /usr/local/lib/python3.12/dist-packages/vllm/v1/core/sched/scheduler.py

# E. speculator 全文（落真补丁的锚点来源）
cat -n /usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu/spec_decode/dspark/speculator.py
grep -n "def \|cudagraph\|CUDAGraph" /usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu/spec_decode/dspark/speculator.py

# F. metadata / sampler 结构
grep -rn "class SpecDecodeMetadata" -A 25 /usr/local/lib/python3.12/dist-packages/vllm/v1/worker/gpu/spec_decode/metadata.py 2>/dev/null \
  || grep -rn "class SpecDecodeMetadata" -A 25 /usr/local/lib/python3.12/dist-packages/vllm/v1/spec_decode/
grep -n "def \|num_draft_tokens" /usr/local/lib/python3.12/dist-packages/vllm/v1/spec_decode/rejection_sampler.py | head -30

# G. envs 注册约定
grep -n "VLLM_DSPARK\|environment_variables" /usr/local/lib/python3.12/dist-packages/vllm/envs.py | head -10

# H. 运行版 dspark.py 现状（S0 diff 的补充锚点）
md5sum /usr/local/lib/python3.12/dist-packages/vllm/models/deepseek_v4/nvidia/dspark.py
grep -n "confidence" /usr/local/lib/python3.12/dist-packages/vllm/models/deepseek_v4/nvidia/dspark.py
sed -n '890,930p' /models/inference/model.py   # 参考实现 forward_head 逐行语义（§2.3 形状对齐定谳）
```

---

## 7. 改动量与验收映射（预测，S0 diff 后定稿）

| 文件 | 预估改动 | 服务的验收门 |
|---|---|---|
| dspark.py | +25~35 行 | G1-T2 加载实锤；G4 bit 级（gate off 零新参数） |
| speculator.py | +45~60 行 | G3-T1 置信↔长度相关；G2-T4 阈值扫描 |
| scheduler + metadata + sampler 管线 | +60~100 行 | G3-T4 step-time 单调；G2 分布等价 |
| envs.py | +4 行 | 门控/回退（G4-T3） |
| 合计 | ~150-200 行（v2 §1.1 预算内） | — |

## 8. 自验 checklist（真补丁落盘后逐条执行）

1. **数据流完整性**：置信分 head→conf_gpu_buf→D2H stage→get_stale_confidences→compute_request_lengths→num_draft_tokens→metadata→rejection sampler，每跳有落点、每跳有门控短路。
2. **gate off 零行为**：逐行确认 `VLLM_DSPARK_CONF_GATE=false` 时无任何新代码路径执行（模块不创建/分支全短路/无新张量）；`VLLM_DSPARK_CONF_GATE=true, MIN=0` 时长度恒 k、D2H 与 get_stale_confidences 为唯一新增 host 操作（无采样路径接触）。
3. **贪心不变性**（G2-T4 前提）：确认截短仅体现在 num_draft_tokens 记账；rejection sampler 在贪心+前缀全接受时前 L_r 位输出与全 k 验证逐位相同。
4. **捕获安全**：graph 捕获范围内无新分配（预分配 buffer）、无 D2H 同步（D2H 在 capture 外）、形状恒定。
5. **降级路径**：gate on + 权重缺失 → warning + confidence_head=None + 行为回到 gate off 等价态。

## 9. 待服务器核验项汇总（真补丁的阻塞清单）

| # | 项 | 阻塞什么 |
|---|---|---|
| V1 | async 调度启用状态（§6-A） | §4.3 双分支二选一 |
| V2 | speculator.py 全文结构（§6-E：_sample_sequential 循环粒度、_run_model 输出与逐步 hidden 切片对应、FULL replay 分支、capture max_b 属性名） | §3.2/3.3 落笔 |
| V3 | num_draft_tokens 消费链与 rejection sampler 变长支持现状（§6-C/F） | §4.2 三消费点 |
| V4 | 参考实现 forward_head 的 (x, markov_embed) 形状对齐（§6-H 最后一条） | §2.3 compute_confidence 输入形状 |
| V5 | envs.py 注册约定（§6-G） | §5 |
| V6 | 运行版 dspark.py md5 + confidence 锚点上下文（§6-H） | 补丁基底（S0 diff 一并解决） |
| V7 | weight_loader fp32 上转 bit-exact | G2 前提小验证 |

---

> 本草案为先行版：不等 S0，先把设计钉死、把核验清单发出。S0 diff + §6 结果到手后，据此落 `s1-patch-20260910/`（dspark.patch / speculator.patch / scheduler_verify.patch + README），锚点全部换成运行版实文。
