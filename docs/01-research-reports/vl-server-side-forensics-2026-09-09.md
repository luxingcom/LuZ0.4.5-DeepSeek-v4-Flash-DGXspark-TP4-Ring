# VL §5.6 服务器侧验证清单执行报告（grep 类只读项）

日期：2026-09-09 ｜ 执行人：sre-engineer-2 (Rex) ｜ 性质：**只读取证**（零写入、零重启、零配置变更、零探测请求）
清单来源：`spec-head-research-2026-09-09.md` §5.6「服务器侧验证清单」+ §5.7 env 护栏核对项（vl-spec-research 产出，本报告为其服务器侧执行回执）
取证窗口（服务器时钟 **UTC**，GMT+8 = UTC+8）：2026-09-08T23:59:15Z ~ 2026-09-09T00:04:11Z（= GMT+8 09-09 07:59~08:04）。窗口位于 vl-acceptance GSM8K@4096 运行期间，全部命令为 `docker logs -t` / `docker exec grep|sed|find` / `docker inspect` / `ssh 对端 docker inspect`，未触碰 GPU 链。

---

## 0. 一句话结论

**§5.6 清单 grep 类可做项全部闭环：三大工程根因候选中 #49133（draft 量化错配）与 FlyCockpit（wrapper 拦截）均被服务器证据排除；`VLLM_DSPARK_MARKOV_REPL=0` 护栏四机在位（§5.7 的 w6_env.txt desync 疑点被推翻）；thinking 服务端默认值仅剩 6b 探针可裁决（按指令暂缓等冷窗口）。**

### 裁决总表

| 项 | 内容 | 结论 | 证据等级 |
|---|---|---|---|
| S56-1 | #49133 指纹（MXFP4 backend 行） | **排除**：指纹 PRESENT——`[mxfp4.py:426] Using 'B12X_MXFP4' Mxfp4 MoE backend.` | 服务器日志实锤 |
| S56-2 | #49133 代码面 | 结构"未修复"成立（draft 复用 target vllm_config，`get_quantization_config` 命中 0 处），但现役 FP8 target **不触发**错配 | 容器内源码实锤 |
| S56-3 | draft 专家 quant_method 直证 | 直证不可得（`enable_return_routed_experts=False`），由 S56-1/2 间接闭合 | 引擎 init 原文实锤 |
| S56-4 | wrapper 存在性 | **无自定义 wrapper**：命中全为 vLLM in-tree 官方实现 + registry.py 注册表误命中 | 容器内源码实锤 |
| S56-5 | FlyCockpit 透传判据 | **不适用**（前提不成立） | — |
| S56-6a | thinking 模板默认 | **部分闭环**：双模式在位、effort 默认 low、drop_thinking 默认 True；服务端默认 thinking_mode 未能 grep 定位 → 须 6b 探针 | 源码实锤 + pending |
| S56-6b | thinking 探针（发请求） | **已由 vl-acceptance 代执行并裁决（09-09 01:4x-02:1x UTC，冷窗口回产后校准段 tp2/tp3/tp4 三轮）**：默认态响应 reasoning=None（API 层无独立思考通道，逐步推理 content 内联）；两态 accept_len 2.423 vs 2.648（单请求噪声内无显著差）→ thinking 不构成接受率测量混杂 | 见 FINAL-METRICS-VL-2026-09-09.md §9-2 + 服务器 /tmp/vl-acceptance/{tp2,tp3,tp4}.py |
| S56-6c | 现网 bench 产物 reasoning_content 抽查 | **已被 6b 默认态裁决覆盖**（reasoning=None 直证无独立思考通道） | 同上 |
| S56-7 | MT-Bench 80 题真实负载交叉校准 | **暂缓**（占 GPU） | — |
| S56-8 | draft logits 精度（G1r6 bf16 残留） | G1r6 "B1 bf16 draft logits" 代码**不在现役路径**（spec_decode/dspark 无 bf16 字符串）；现役为 checkpoint 原生精度 | 容器内源码实锤 |
| ENV | env 核对 + §5.7 护栏 | **`VLLM_DSPARK_MARKOV_REPL=0` 四机一致在位**；引用点唯一（dspark.py:123） | docker inspect 实锤 |

---

## 1. 取证方法

- 三轮主取证 + 两轮补充：`ssh node01 bash -s <<'REMOTE'` heredoc（防本地展开），输出重定向本地 `kv28~kv32.txt`。
- 容器：`vllm-tp4-rank0`（node01，head 节点），镜像 `REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`，`Up 8 hours (healthy)`，本次 boot 2026-09-08T16:19:31Z 引擎 init。
- rank1-3 位于对端节点：`vllm-tp4-rank1`@node02、`vllm-tp4-rank2`@node04、`vllm-tp4-rank3`@node03，经 ssh + `docker inspect` 核对 env。
- 模型挂载：`<INSTALL_DIR>/models/dsv4-vision-exp -> /models`；日志挂载 `<HOME_DIR>/vllm-logs -> /var/log/vllm`（内仅 nccl 日志与 startup-trace，**无引擎主日志**——主日志只进 docker logs / rank0 存档）。

## 2. 逐项详证

### S56-1 #49133 指纹 —— 排除

- verbatim（当前 boot 全日志**恰 1 次**，构建期、权重加载前）：
  `2026-09-08T16:19:59.808987715Z (Worker_TP0 pid=243) INFO 09-08 16:19:59 [mxfp4.py:426] Using 'B12X_MXFP4' Mxfp4 MoE backend.`
- 判读：#49133 原文的指纹串 `FLASHINFER_TRTLLM_MXFP4_MXFP8` 在本 fork 对应枚举分支 `Mxfp4MoeBackend`（mxfp4.py L156-163：FLASHINFER_TRTLLM_MXFP4_MXFP8 / FLASHINFER_TRTLLM_MXFP4_BF16 / AITER_MXFP4_BF16 / **B12X_MXFP4**（fork 新增）/ NONE）。SM121 + FlashInfer 0.6.18 + B12X 环境下选中 B12X_MXFP4——**MXFP4 MoE backend 行出现 = MoE 量化解析走了正确 MXFP4 backend，未走 `ModelOptNvFp4FusedMoE` 错配路径**。判据逻辑与原清单等价（backend 行出现 → 未命中）。
- 叠加：现役 `quantization=deepseek_v4_fp8`（FP8 target），#49133 触发前提（FP4/NVFP4 target）根本不存在。draft 与 target 同 checkpoint（见 S56-3 init 原文 `speculative_config model='/models'`），draft 头 mtp.0-2 的 `expert_dtype=fp4` 专家同走该 backend。

### S56-2 #49133 代码面 —— 结构未修复，但形态不触发

- `v1/worker/gpu/spec_decode/dspark/utils.py` L19-47（全函数已取）：`load_dspark_model` 以 `replace(vllm_config, ...)` 从 **target vllm_config 派生** draft_vllm_config，仅覆写 attention_config 与 cache_config(kv_cache_dtype)，**quant_config 原样继承**；`grep -c get_quantization_config` = **0**。与 #49133 描述的"复用 target quant_config"形态一致——fork 未含上游修复（与 spec-research §5.2 "上游 merged=false" 结论自洽）。
- `config/speculative.py` L331-345：`hf_config_override` 对 `model_type == "deepseek_v4"` 改写为 `deepseek_mtp` + `architectures=["DeepSeekV4MTPModel"]`——#49133 根因①的 model_type 改写路径在位（与主线同构）。
- 加固证据：`models/deepseek_v4/nvidia/dspark.py` L404 `if getattr(self.config, "expert_dtype", "fp4") == "fp4"` 显式分支 + L444 `float8_e8m0fnu` scale 处理——MXFP4 专家 scale 按正确 dtype 加载的代码在位。
- **终裁：代码面"命中形态"存在 × 触发条件（FP4/NVFP4 target）不存在 × S56-1 指纹 PRESENT → #49133 排除。**

### S56-3 draft 专家 quant_method 直证 —— 直证不可得，间接闭合

- 引擎 init 原文（16:19:31 `[core.py:116]`，关键配置 verbatim）：`speculative_config=SpeculativeConfig(method='dspark', model='/models', num_spec_tokens=6)`、`quantization=deepseek_v4_fp8, quantization_config=None`、`kv_cache_dtype=fp8_ds_mla`、`max_seq_len=600000`、`dtype=torch.bfloat16`、`enforce_eager=False`、`enable_prefix_caching=False`、`served_model_name=deepseek-v4-flash-vision-exp`、`tokenizer_mode=deepseek_v4`、`reasoning_parser='deepseek_v4'`、`enable_return_routed_experts=False`。**确认 k=6、draft=同 checkpoint 自 draft。**
- `enable_return_routed_experts=False` → 引擎不打印 routed_experts/quant_method 明细 → 清单第 3 项的日志直证不可得。结论由 S56-1（backend 指纹）+ S56-2（代码面+scale dtype 处理）间接闭合。

### S56-4/5 FlyCockpit wrapper —— 排除

- models dir `VisionForCausalLM|VisionModel` 命中 10 文件全为 in-tree 官方实现：interns1 / cosmos3_edge / eagle2_5_vl / h2ovl / gemma3_mm / **registry.py** / phi3v / blip / clip / cohere2_vision——无 fork 自定义 VL 包装类。
- registry.py 系注册表字符串误命中（S56-5 对其 grep 仅出 L604 `ExtractHiddenStatesModel` 注册行，非 forward/kwargs 语义）。
- `/models/config.json`：`model_type: deepseek_v4`、`num_nextn_predict_layers: 3`——走原生 deepseek_v4 模型实现路径。
- **终裁：无第三方包装层 → FlyCockpit 拦截假设排除 → S56-5 透传判据不适用。**（spec-research §2-2(c) 的排查项就此关账）

### S56-6a thinking 模板默认 —— 部分闭环

- `/models` 下**无标准 HF chat_template**：`tokenizer_config.json` 仅 801 字节且无 thinking 字段；无 *.jinja。`tokenizer_mode=deepseek_v4` → 模板逻辑在自定义 encoding：`/models/encoding/encoding_dsv4.py`。
- 该文件实锤：`thinking_mode ∈ {"chat","thinking"}`（L237/256 断言）；`REASONING_EFFORT_PROMPTS` `low=""` 且 `DEFAULT_REASONING_EFFORT="low"`（L67-71/82）；`drop_thinking` 默认 True（L237）；user turn 仅在 `not drop_thinking and thinking_mode=="thinking"` 时预置 `<think>`（L402-405）。
- `encode_messages` / `_encode_messages_text` 的 `thinking_mode` 为**必传无默认**（L746-750 / L519-524）→ 服务端默认值在引擎 tokenizer_mode=deepseek_v4 集成层，grep 未定位到硬编码（chat_utils.py 的 thinking 命中均为 interleaved-thinking 消息解析 L1457 `_ThinkParser`，非模式默认）。
- **结论：6a 无法仅靠 grep 确定现役默认 thinking 状态；须由 6b 探针（同 prompt 带/不带 `chat_template_kwargs:{"thinking":false}` 的 per-pos 接受率差分）一锤定音。**
- 对 0.572 口径的意义：spec-research §5.4 已证 bench_v2.py 请求体无任何 thinking 字段（T=0.6，纯依赖服务端默认）。若默认 thinking=on，则 0.572 内含 thinking 稀释成分（classmethod 口径：ON→OFF 接受率 24.2%→40.4%，+67% 量级），与"训练稀释"假设混同——**探针是分摊两种解释的唯一低成本手段**。

### S56-8 draft logits 精度 —— G1r6 bf16 实验代码不在现役路径

- `v1/worker/gpu/spec_decode/dspark/` 仅 3 文件：`__init__.py`(107B) / `speculator.py`(7.8KB) / `utils.py`(2.7KB)；`grep -rn 'bf16|bfloat16'` **零命中**。
- 判读：G1r6 "B1（bf16 draft logits）" 实验无代码残留于 spec_decode 路径，与 CHANGES 中"GSM8K 门未过、默认关闭"记载一致；现役 draft logits 为 checkpoint 原生精度。Rarri 数据（bf16 头 accept_len 4.09 vs FP8 头 3.51，-14%）指向的优化项在本 fork **未实施**——保留为可选优化方向（需权重/训练改造，非配置项）。

### ENV 核对 —— 护栏四机在位，§5.7 疑点推翻

- rank0 关键 env（docker inspect verbatim，完整表见 kv28.txt）：
  `VLLM_MOE_W4A4=2`、`VLLM_MOE_W4A4_CG=1`、`VLLM_B12X_SHARED_WRAPPER=1`、`VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/root/.cache/vllm/autotune-g1r6`、`VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS=sparse_mla_sm120`、`TORCH_CUDA_ARCH_LIST=12.1a`、`FLASHINFER_CUDA_ARCH_LIST=12.1a`、`VLLM_USE_BREAKABLE_CUDAGRAPH=1`、`VLLM_DISABLE_CUSTOM_ALL_REDUCE=1`、`VLLM_DISABLE_PYNCCL=1`、`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`、`FLASHINFER_DISABLE_VERSION_CHECK=1`、`VLLM_PREFIX_CACHE_RETENTION_INTERVAL=8192` + 全套 NCCL IB 调优。
- **`VLLM_DSPARK_MARKOV_REPL=0`**：rank0 在位；四机核对 rank1(node02) / rank2(node04) / rank3(node03) **均 =0**，且 W4A4/B12X/autotune-g1r6 四机一致。
- 护栏代码唯一引用点：`models/deepseek_v4/nvidia/dspark.py:123` `replicate=os.environ.get("VLLM_DSPARK_MARKOV_REPL","") == "1"` → 现役 `replicate=False`（Markov replicate 关闭，B2 补丁路径 off）。
- **§5.7 更正记录的 desync 疑点被推翻**：w6_env.txt 发布副本缺行 ≠ 服务器缺失；服务器四机 env 均有护栏行且取值 0。
- 附注：autotune cache 目录名 `autotune-g1r6` 表明现役 autotune 缓存继承自 G1r6 实验期（版本延续性事实，供配置溯源）。

## 3. 对接受率退化（0.572 vs 0.652）归因的更新

| 候选根因 | 本轮裁决 | 后续 |
|---|---|---|
| #49133 draft 量化错配 | **排除**（S56-1 指纹 PRESENT + FP8 target 前提不成立 + S56-2 代码面） | 无 |
| FlyCockpit wrapper 拦截 | **排除**（S56-4 无自定义包装类） | 无 |
| bench 随机 filler 伪影（#51009 教训） | 存留 | S56-7 MT-Bench 交叉校准（暂缓，GPU 窗口） |
| thinking 口径污染 | **已排除**（6b 由 vl-acceptance 代执行裁决：两态 accept_len 2.423 vs 2.648 无显著差、reasoning=None；对 0.572 无修正，coding/json 退化维持 draft 头拟合不足假设；见 FINAL-METRICS-VL §9-2） | 无 |
| 训练稀释（VL draft 头） | **存留且权重上升**（两大工程根因排除后，剩余解释集中于口径+训练侧） | 6b/7 裁决后归因 |

- spec-research §2 行动建议不受影响：**k 截短 6→4（纯配置）仍为首选低成本项**；PR #47808 自适应验证 SM121 验证仍为中期项。

## 4. 暂缓项与触发条件

| 项 | 触发条件 | 预计成本 |
|---|---|---|
| S56-6b thinking 探针 | **已闭环**：由 vl-acceptance 代执行并裁决（09-09 01:4x-02:1x UTC，tp2/tp3/tp4 三轮），结论见 FINAL-METRICS-VL-2026-09-09.md §9-2 + 服务器 /tmp/vl-acceptance/{tp2,tp3,tp4}.py；不再重跑 | — |
| S56-6c bench 产物抽查 | **已闭环**：被 6b 默认态裁决覆盖（reasoning=None 直证无独立思考通道） | — |
| S56-7 MT-Bench 80 题 | 同上（GPU 空闲） | ~30-60 分钟 |
| rank1-3 指纹 grep 加固 | 可选（rank0 已裁决；四机同镜像同构） | 低 |

## 5. 局限

- `docker logs` 仅覆盖当前容器生命周期（16:19Z boot 起）；历史 18 次 boot 的指纹状态可从 rank0 logdump 存档复核（本轮未做，kv26 采集口径已有档案）。
- rank1-3 仅核对了 env 一致性，未逐一 grep 容器内源码/日志（同镜像同构，风险低）。
- thinking 服务端默认值未做源码全链路考证（tokenizer_mode=deepseek_v4 引擎集成层），以 6b 实测替代源码考证。

## 附录 A：取证窗口与证据文件索引

| 轮次 | 窗口（UTC） | 文件 | 覆盖 |
|---|---|---|---|
| R1 | 2026-09-08T23:59:15Z ~ 23:59:17Z | `C:/Users/novAI/WorkBuddy/kv28.txt`（227 行） | META/S56-1/2/3/4/5/6a/8/env 主取证 |
| R2 | 2026-09-09T00:01:29Z 起 | `C:/Users/novAI/WorkBuddy/kv29.txt`（330 行） | utils.py 全函数、/models 全量 ls、护栏代码、对端节点 env |
| R3 | 2026-09-09T00:02:51Z | `C:/Users/novAI/WorkBuddy/kv30.txt`（93 行） | encoding_dsv4.py thinking 引用、mxfp4 上下文 |
| R4 | 2026-09-09T00:03:44Z | `C:/Users/novAI/WorkBuddy/kv31.txt`（47 行） | thinking_mode 引擎侧 grep、Mxfp4MoeBackend 枚举 |
| R5 | 2026-09-09T00:04:11Z | `C:/Users/novAI/WorkBuddy/kv32.txt`（84 行） | encode_messages 签名、chat_utils thinking 链 |

所有时间戳为服务器 UTC；GMT+8 = UTC + 8h。

（报告完）
