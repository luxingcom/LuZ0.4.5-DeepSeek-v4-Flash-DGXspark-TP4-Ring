# VL KV 缓存缩水归因——内存空间与 KV 构成完整分解（只读取证）

| 项 | 值 |
|---|---|
| 编号 | G1R7VL-KVDECOMP-20260909 |
| 执行人 | Rex（SRE 工程师，sre-engineer-2） |
| 日期 | 2026-09-09 |
| 性质 | **只读取证**：全程 docker logs / docker run --rm（一次性临时容器）/ curl 只读抓取 / safetensors 头部读取；未重启服务、未修改任何配置、未执行任何变更类命令 |
| 关联 | 督导指令 #1；`vl-governance-audit-2026-09-08.md`；G1R7VL 基线交付 20260908 |
| 证据主源 | `<INSTALL_DIR>/backup/vllm-logdump/vllm-tp4-rank0.log`（跨代存档，**替代已轮转的实时日志**，下称"存档 L<行号>"）；vLLM `/metrics`（:8001）实抓；两模型 config.json 与 safetensors 头扫描；fork 源码（本轮前序取证） |

---

## 0. 一句话结论

**督导口径的 "KV 池 2.72M tokens，比 V5b 5.9M 缩水 54%" 大部分是统计口径混淆 + 基线 boot 非典型档案，VL 与 V5b 常态生产的 KV 容量基本持平（−1.9pp，范围 −2.5%~+0.9%）。**

对 −53.0pp 表观缩水（督导取整 5.9M 记为 −54%）的三段精确分解（token 数，证据见 §3/§4/§7）：

| 分解项 | 贡献 | 性质 |
|---|---|---|
| ① scheduler/worker 口径折叠（×1.884） | **−41.6pp** | 统计口径 artifact |
| ② V5b 交接基线 boot（04:08）非典型档案（eager + 无投机解码 + B 路径加载） | **−9.6pp** | boot 档案差异，非模型差异 |
| ③ VL 对 V5b 常态生产的真实差异 | **−1.9pp** | 真实（处于 V5b 自身 11 次 boot 间噪声带内） |
| 合计 | −53.1pp ≈ −53.0pp（取整误差） | — |

---

## 1. 证据源与方法（只读命令清单）

1. 存档日志全量 grep：`grep -n 'weights take|activation|non.torch|Available KV|GPU KV cache size|Maximum concurrency'` 于 `vllm-tp4-rank0.log`（26.4MB 的 `vllm028-tp4-rank0.log` 为 09-07 前旧档；`vllm-tp4-rank0.log` 覆盖 09-06 23:48 至 09-08 16:54 全部 boot，共 18 次完整启动台账）。
2. 两个生产 boot 的引擎配置原文：`sed -n` 行窗 + `grep -o` 关键赋值（04:05:01 V5b 基线 boot L43247；VL 生产 boot 窗口 L52040-52260）。
3. 实时指标：`curl http://127.0.0.1:8001/metrics` 抓 `vllm:cache_config_info`（2026-09-09 实抓）。
4. Prometheus 历史回溯：`http://127.0.0.1:8191/api/v1/query`（time=09-08T06:00Z / 10:30Z / 13:00Z）+ `/api/v1/targets`。
5. 权重构成：Python 标准库逐文件解析两模型全部 48+48 个 safetensors 头部（struct '<Q' + JSON header），按 key 前缀分桶求和。
6. 源码机制（本轮前序取证，docker run --rm 只读 grep fork 镜像）：`vllm/v1/core/kv_cache_utils.py:937/1797/1819/2150-2200`、`vllm/v1/kv_cache_interface.py:817`、`vllm/models/deepseek_v4/compressor.py`。

---

## 2. 第一手台账：四个 boot 群体

存档共 18 次完整启动台账，按权重足迹/代码路径分为三群体 + bf16 测试组：

### 2.1 VL 生产 boot（验收对象，09-08 11:31，A 路径）

| 分项 | GiB | 证据 |
|---|---|---|
| 权重（weight） | 45.56 | 存档 L52134（model_runner.py:305）/ L52254 |
| 峰值激活（peak activation） | 2.03 | L52254 |
| 非 torch 内存（non-torch） | 4.03 | L52254 |
| CUDAGraph | 1.13 | L52253-52254（**在 0.8 预算外**，见 §2.5） |
| **可用 KV 池** | **45.68** | L52179 |
| KV tokens（worker 口径） | **5,128,378** | L52180（kv_cache_utils.py:2177） |
| 最大并发（worker 口径，600k/req） | **8.55x** | L52181 |
| num_gpu_blocks（scheduler 口径） | 45,540 | 验收期指标快照（kv6.txt，09-08 抓取） |
| KV tokens / 并发（scheduler 口径） | **2,720,971 / 4.535x** | 同上（= 验收实测 = 督导引用值） |

**预算闭合**：45.56 + 2.03 + 4.03 + 45.68 = **97.30 GiB = 0.8 × 121.63 GiB（GB10 单卡）精确闭合** ✓（CUDAGraph 1.13 不计入，实际总占用 98.43 GiB ≈ 80.9%）。

### 2.2 V5b 交接基线 boot（督导 "5.9M" 的来源，09-08 04:08，B 路径，**非典型档案**）

| 分项 | GiB | 证据 |
|---|---|---|
| 权重 | **42.46** | L43320（gpu_model_runner.py:5368）/ L43385 |
| 激活 / 非 torch | 1.84 / 2.43 | L43385 |
| CUDAGraph | 0.0（enforce_eager=True，无图） | L43385 |
| **可用 KV 池** | **50.57** | L43362 |
| KV tokens / 并发（worker 口径） | **5,791,869 / 9.65x** | L43363-43364 |

**配置原文（L43247，04:05:01）**：`speculative_config=None`、`enforce_eager=True`、`max_seq_len=600000`、`kv_cache_dtype=fp8_ds_mla`、`quantization=deepseek_v4_fp8`、`dtype=torch.bfloat16`、`enable_prefix_caching=True`、`served_model_name=deepseek-v4-flash-0731`。

**预算闭合**：42.46 + 1.84 + 2.43 + 0 + 50.57 = **97.30 精确闭合** ✓。

**非典型性**：该 boot 同时具备 ①eager 无图 ②无投机解码 ③B 路径加载打印（`gpu_model_runner.py:5368`，含 "memory" 字样）。**权重足迹 42.46 与 A 路径常态 boot 的 45.56-45.68 相差 3.10 GiB/rank，且与加载代码路径 100% 相关**（18 个 boot 中无一例外：42.4x/42.68 ⟷ gpu_model_runner.py:5368；45.5x ⟷ model_runner.py:305）。触发机制未定位（P2），但群体差异是实测事实。

### 2.3 V5b 常态生产 boot（图模式，11 次，A 路径）——**正确的对照基线**

| boot 时刻 | 池 GiB | tokens | 并发(600k) | 权重 | non-torch | 图 |
|---|---|---|---|---|---|---|
| 09-06 23:52 | 46.62 | 5,233,896 | 8.72x | 45.34 | 3.31 | 1.42 |
| 09-07 12:53 | 47.10 | 5,253,378 | 8.76x | 45.59 | 2.58 | 1.23 |
| 09-07 15:33 | 46.35 | 5,202,927 | 8.67x | 45.59 | 3.33 | 0.29 |
| 09-07 15:49 | 46.80 | 5,176,576 | 8.63x | 45.68 | 2.79 | 1.82 |
| 09-07 16:47 | 47.16 | 5,179,054 | 8.63x | 45.59 | 2.52 | 1.21 |
| 09-08 04:20 | 46.80 | 5,225,563 | 8.71x | 45.68 | 2.79 | 1.18 |
| 09-08 04:28 | 46.27 | 5,193,918 | 8.66x | 45.59 | 3.41 | 1.01 |
| 09-08 08:19 | 47.05 | 5,258,108 | 8.76x | 45.59 | 2.64 | 1.16 |
| 09-08 08:34 | 47.37 | 5,241,103 | 8.74x | 45.56 | 2.34 | 1.13 |
| 09-08 08:45 | 46.66 | 5,124,662 | 8.54x | 45.56 | 3.05 | 1.69 |
| 09-08 09:03（切换前最后一次 V5b 生产） | 46.55 | 5,225,225 | 8.71x | 45.59 | 3.14 | 1.00 |
| **中位数** | **46.80** | **5,225,225** | **8.71x** | 45.59 | — | — |

（各行证据行号样例：L194-196/271、L22860-22862/22937、L26751-26753/26831、L27516-27518/27589、L28613-28615/28690、L43984-43986/44061、L44406-44408/44483、L47927-47929/47983、L48357-48359/48415、L49189-49191/49319、L49826-49828/49903。）

### 2.4 bf16 未压缩测试组（参考，用于 KV 字节解剖交叉验证，§5）

- VL bf16：09-08 03:38 / 03:44 / 04:01，池 47.76/47.77/47.21 GiB，tokens 944,871/951,141/950,959（@65,536），实测 54,292/53,932/53,316 B/token（L42157-42159、L42511-42513、L42958-42960）。
- V5b bf16：09-08 04:13，池 50.49 GiB，1,057,517 tokens（@65,536，16.14x），实测 51,266 B/token（L43652-43654）。

### 2.5 两条路径的记账规则（硬证据）

- **A 路径**（model_runner.py:305；VL 生产 + V5b 常态）：池 = 97.30 − (权重+激活+非torch)；**CUDAGraph 在池分配后捕获、位于 0.8 预算外**（顶部 20% 余量吸收；VL 生产 boot 实际总占用 98.43/121.63 = 80.9%）。佐证：L52254 提示 "--kv-cache-memory=44.4 GiB to fit into requested memory"。
- **B 路径**（gpu_model_runner.py:5368；V5b 基线等）：池 = 97.30 − (权重+激活+非torch+**预计**图内存)。佐证：09-07 15:56 boot（L27909-27963）"Estimated CUDA graph memory: 1.42 GiB" 后池 48.74，闭合 42.46+1.84+2.83+1.42+48.74 = 97.29 ✓。

---

## 3. 双口径机制：×1.884 从何而来（督导 −54% 的第一大成分）

### 3.1 源码机制（前序取证已读 fork 源码）

- `kv_cache_utils.py:1797` `generate_scheduler_kv_cache_config`：把同型层组（UniformTypeKVCacheSpecs，DSV4 是代码中唯一特例）**替换为"任意一个代表层"的 spec**（`next(iter(spec.kv_cache_specs.values()))`）→ scheduler 拿到的 per-request 页数被放大。
- `kv_cache_utils.py:937`：`并发 = num_blocks / blocks_per_request`。
- `kv_cache_utils.py:1819` + `:2150-2200`：`capacity_tokens = int(并发 × max_model_len)`（启动打印注释原文 "GPU KV cache size in tokens = max_concurrency * max_model_len"）。
- `kv_cache_interface.py:817`：UniformTypeKVCacheSpecs 的 page_size = Σ成员 spec 页大小（worker 侧真实口径）。

### 3.2 算术复现（全部实测数字，无拟合）

| 量 | 值 | 复现 |
|---|---|---|
| VL 验收 boot scheduler 并发 | 4.534953196574388 | 45,540 / 10,042 = 4.53495（**精确**） |
| VL 验收 boot scheduler tokens | 2,720,971 | int(4.534953 × 600,000) = 2,720,971.9 → 2,720,971（**精确**） |
| VL 验收 boot worker 并发 | 8.55x | 5,128,378 / 600,000 = 8.5473；45,540 / 5,328 ≈ 8.548（反解） |
| 折叠系数 | **×1.884** | 5,128,378 / 2,720,971 = 1.8848；10,042 / 5,328 = 1.8848 |
| VL 现行 boot（16:22）实测 | 2,797,972 / 4.6616x / 46,812 blocks | 5,271,621 / 2,797,972 = 1.8840 ✓ 同系数；每 block 池字节 49.05GB/45,540 = 1.077MB 与 50.42GB/46,812 = 1.077MB 恒定 ✓ |

**含义**：`vllm:cache_config_info` 的 2.72M/4.535x 是**同一物理池的保守下界**（代表层折叠把 per-request 页数高估 1.884 倍）；worker 口径 5.13M/8.55x 才是池的真实 token 容量。验收抓到的 4.535 与启动日志 8.55 从不矛盾——相差恒为 ×1.884。

---

## 4. 权重构成分解（safetensors 头扫描，48 文件 × 2 模型）

| 分桶（磁盘 GiB） | VL（dsv4-vision-exp） | V5b（deepseek-v4-flash-0731） | Δ |
|---|---|---|---|
| text+embed+head+indexer 权重（"OTHER"） | 145.40 | 145.30 | +0.10 |
| MTP.0 / MTP.1 / MTP.2 | 3.36 / 3.32 / 3.44 = **10.12** | 3.36 / 3.32 / 3.44 = **10.12** | **0** |
| VISION | 0.77 | 0 | +0.77 |
| **合计** | **156.29**（佐证 L52042 "Checkpoint size: 156.29 GiB"） | **155.42** | +0.87 |
| 每 rank（TP4） | 39.07 | 38.86 | +0.22 |

**关键发现**：
1. **两个 checkpoint 都携带 3 组 MTP 权重**（mtp.0/1/2 完全同尺寸），V5b config `num_nextn_predict_layers=1` 只用 1 组 → **磁盘级 VL−V5b 差 = 纯 vision 0.87 GiB**。
2. **runtime 权重两模型持平**：VL 生产 45.56 vs V5b 常态 45.56-45.68（§2.1/§2.3）→ vision 的在载成本 ≈0.2 GiB/rank，**完全淹没在 boot 间 non-torch 噪声带（2.34-4.03 GiB）内**。
3. 基线 boot 的 42.46 与磁盘构成无关（eager/no-spec/B 路径的组合效应，机制 P2）。
4. MTP 1→3 的"权重增量"在 checkpoint 层面为零；真正的 MTP 增量在 KV 池侧（见 §5）。

---

## 5. KV per-token 公式核算（取证清单第 3 项）

### 5.1 教科书公式为何不适用

MHA 公式 `2(K/V)×L×H_kv×D_head×bytes` 对本模型失效：DSv4 为 MLA 架构（config：`kv_heads=1`，latent `head_dim=512` + `qk_rope_head_dim=64`），K/V 合一为单一 latent；`kv_cache_dtype=fp8_ds_mla`（1 byte）。修正后的**未压缩 MLA 每 token 每层 = 576 B**：

- V5b：44 个 KV 层（43 text + 1 MTP）× 576 = **25,344 B/token**
- VL：46 个 KV 层（43 text + 3 MTP，compress_ratios 46 项）× 576 = **26,496 B/token**

### 5.2 bf16 测试组交叉验证层结构（硬证据）

bf16（2 byte）未压缩时：VL 理论 46×576×2 = **52,992** vs 实测 53,316-54,292（+0.6~2.5%，池取整+块取整误差）；V5b 理论 44×576×2 = **50,688** vs 实测 51,266（+1.1%）→ **46/44 层 × 576 B 的层结构得到独立验证** ✓。

### 5.3 实测有效 per-token（fp8_ds_mla + compress_ratios 摊销后）

| 群体 | B/token |
|---|---|
| V5b 常态（11 boot） | 9,564 - 9,778（中位 ≈9,65x） |
| V5b 基线（04:08，无 spec → 假设 MTP 层不进池，43 层） | 9,375（×44/43 = 9,593 落入常态带 ✓） |
| VL 生产（11:31 / 16:22） | **9,566 / 9,563** |

- **VL 与 V5b 常态 per-token 持平**（VL 落在常态带下沿；未压缩层的 +4.5% 差异被压缩摊销吸收至噪声内，字节级解剖 P2）。
- 有效值 ≈ 未压缩 fp8 MLA 的 37%：摊销来自 per-layer `compress_ratios`（sw128/sw8 层仅存窗口，ratio 4→sw8、128→sw128，compressor.py `coff=1+(ratio==4)`），叠加 DSA Lightning Indexer 的 FP8 独立缓存（VL boot 日志 L52040 "Using FP8 indexer cache for Lightning Indexer"；其每 token 字节未定位，P2）。
- 物理块闭合：池 / num_gpu_blocks = 1.077 MB/block 恒定（两个 VL boot 独立验证），即 worker 侧真实页粒度记账自洽。

---

## 6. 差值归因瀑布（取证清单第 5 项）

### 6.1 tokens 表观缩水 −53.0pp 的精确分解

```
V5b 基线 boot worker 口径        5,791,869 tokens (9.65x)   ── 督导取整 "5.9M"
 │ ② 基线 boot 非典型档案（−9.6pp）：eager+无spec+B路径 → 权重 42.46
 │    vs 常态 45.56-45.68，池 +3.2 GiB → tokens 5,791,869 → 5,225,225（V5b 常态中位）
 ▼
V5b 常态生产 worker 口径         5,225,225 tokens (8.71x)   ── 11 boot 中位
 │ ③ VL 真实差异（−1.9pp）：MTP 层 + vision，per-token 持平、权重持平
 ▼
VL 生产 worker 口径              5,128,378 tokens (8.55x)   ── 验收 boot
 │ ① 口径折叠（−41.6pp）：scheduler 代表层折叠 ÷1.884
 ▼
VL 生产 scheduler 口径（验收实测） 2,720,971 tokens (4.535x)  ── 督导引用 "2.72M"
```

验证：46.0%（折叠）× … 精确相加 41.6 + 9.6 + 1.9 = 53.1 ≈ 53.0pp（取整）✓。

### 6.2 KV 池 GiB 差（每 rank）：VL 验收 boot vs V5b 基线 boot

| 分项 | V5b 基线 | VL 验收 | Δ | 归因 |
|---|---|---|---|---|
| 权重 | 42.46 | 45.56 | +3.10 | **boot 档案差异**（B 路径/eager/no-spec），非 VL 结构成本 |
| 激活 | 1.84 | 2.03 | +0.19 | boot 间噪声带 |
| 非 torch | 2.43 | 4.03 | +1.60 | boot 间噪声带（常态 2.34-3.41） |
| CUDAGraph | 0.0 | 1.13 | +1.13 | **在 0.8 预算外**，不占池（§2.5） |
| **KV 池** | **50.57** | **45.68** | **−4.89** | = −(3.10+0.19+1.60)，**精确闭合，逐项均为档案差异/噪声** |

### 6.3 同口径（A 路径图模式）真实对比

| 口径 | V5b 常态（中位） | VL 验收 boot | VL 现行 boot(16:22) | 结论 |
|---|---|---|---|---|
| worker tokens | 5,225,225 | 5,128,378（−1.9%） | 5,271,621（**+0.9%**） | 持平 |
| worker 并发 | 8.71x | 8.55x（−1.8%） | 8.79x（+0.9%） | 持平 |
| scheduler tokens（V5b 为 DERIVED¹） | ≈2.77M | 2,720,971 | 2,797,972 | 持平 |
| scheduler 并发（DERIVED¹） | ≈4.62x | 4.535 | 4.662 | 持平 |
| per-token | ≈9,65x | 9,566 | 9,563 | 持平 |

¹ **DERIVED 标注**：Prometheus `vllm` job health=down、lastScrape 停在 2026-09-08T17:03Z（目标 <NODE_IP>:8001/metrics），09-08T06:00Z/10:30Z/13:00Z 三个时点查询均 0 series → **V5b 期 scheduler 口径无任何存档**，只能用 ÷1.884 折算（系数取 VL 实测 1.884，V5b 层组合略有差异，误差 <±2%）。

---

## 7. 参数差异单列（取证清单第 6 项）

| 参数 | V5b 基线 boot(04:08) | V5b 常态 | VL 生产 | KV 容量影响 |
|---|---|---|---|---|
| gpu_memory_utilization | 0.8（97.3 GiB） | 0.8 | 0.8（指标实测 0.8） | 无（两路径预算均精确闭合 97.30） |
| max_model_len（max_seq_len） | 600,000 | 600,000 | 600,000（打印行 "for 600,000 tokens per request"） | 无 |
| kv_cache_dtype | fp8_ds_mla | fp8_ds_mla | fp8_ds_mla（指标 cache_dtype） | 无 |
| speculative | **None** | 未单独取证 | DSpark draft 已载（L52130 "DSpark draft model loaded: 105 params"） | 基线少 1 层 KV（per-token 9,375 vs 9,56x，一致于 43 层假设） |
| enforce_eager / CUDAGraph | True / 0 | False / 1.0-1.42 | False / 1.13-1.21 | 记账规则不同（§2.5），图不占池 |
| enable_prefix_caching | True | 未取证 | **False**（指标实测） | 不影响容量；影响前缀命中/TTFT（P2 确认是否有意关闭） |
| max_num_batched_tokens | 4096（chunked prefill，L252 行打印） | 4096 | 未单独取证该行 | 不影响 KV 池大小 |
| num_gpu_blocks | 未暴露 | 未暴露 | 45,540 → 46,812（随 non-torch 噪声 +2.8%） | — |
| served_model_name | deepseek-v4-flash-0731 | 同 | deepseek-v4-flash-vision-exp | — |
| 量化 | deepseek_v4_fp8 | 同族 | 同族（config 一致性已由 Task-1 审计确认） | — |

---

## 8. 局限与证据替代说明

1. **日志轮转替代**：实时容器日志已轮转，本报告全部 boot 台账取自 logdump 跨代存档 `vllm-tp4-rank0.log`（该存档机制与 md5 由 Task-1 审计项覆盖）。存档仅 rank0（node01 head），`vllm-tp4-rank1.log` 不存在 → worker 副本 KV 一致性未直接验证（同池由 TP 集体分配，风险低，P2 可在下次窗口双 rank 采样）。
2. **V5b scheduler 口径不可回溯**：Prometheus vllm job down + 无历史（§6.3 注），DERIVED 值已标注。
3. **B 路径触发机制未定位**：42.46/45.56 双权重足迹与加载代码路径 100% 相关，且基线 boot 同时具备 eager+no-spec；未能远程定位开关来源（启动脚本/环境变量），P2 走读 + 受控复现。
4. **KV 字节解剖留白**：indexer FP8 缓存与 MTP 层在池内的每 token 字节未定位（有效 per-token 与未压缩理论值差 63% 由 compress_ratios 摊销 + indexer 共同解释，比例未拆分），P2。
5. 09-06/09-07 部分中断 boot（如 09-07 16:01/16:23）无完整台账，不影响本报告（未纳入任何群体统计）。

---

## 9. 行动项

**P0（服务风险）**：无。本任务为归因澄清，数据面正确、服务健康，无需变更动作。

**P1**
1. **更正验收/督导口径**：把 "−54%" 更正为「同口径对比 −1.9%（中位；范围 −2.5%~+0.9%），KV 容量基本持平」；今后所有容量数字强制标注口径（worker 启动打印 / vllm:cache_config_info），并注明 scheduler 值 = worker 值 ÷1.884（保守下界）。
2. **修复 Prometheus vllm scrape job**（现 health=down、lastScrape 2026-09-08T17:03Z）：否则容量口径永远无历史可回溯（本次即被迫 DERIVED）。
3. **治理链固化"标准生产 boot 档案"**（图模式 + DSpark draft + fp8_ds_mla + 600k）：本次 V5b 交接基线 boot 恰是 eager/no-spec 非典型档案，导致容量基线虚高 9.6pp；应写入启动脚本与交付 runbook 防复发。

**P2**
1. 定位 42.46/45.56 双权重足迹的触发条件（B 路径 `gpu_model_runner.py:5368` 与 eager/no-spec 的耦合）。
2. KV 字节解剖：indexer FP8 缓存与 MTP 层池内每 token 字节（建议读 `generate_scheduler_kv_cache_config` 运行时 dump 或受控 `--kv-cache-memory` 试算）。
3. `enable_prefix_caching` VL=False vs V5b 基线 True：确认是否有意关闭。
4. 双 rank KV 台账采样（下次重启窗口）。
5. G1R7VL 基线交付文档补记：04:08 基线 boot 属非典型档案，后续容量规划不得引用 5.79M/9.65x 作为 V5b 常态（另有 Task-1 已列的 §3/§4 md5 不一致 P1）。

---

## 附录 A：关键 verbatim 证据（存档行号）

```
L43247 (04:05:01,EngineCore pid=245) Initializing a V1 LLM engine (v0.26.1.dev0+gd3d3b2cca.d20260805)
       with config: model='/models', speculative_config=None, ..., dtype=torch.bfloat16,
       max_seq_len=600000, ..., quantization=deepseek_v4_fp8, ..., enforce_eager=True,
       kv_cache_dtype=fp8_ds_mla, ..., served_model_name=deepseek-v4-flash-0731, enable_prefix_caching=True, ...
L43320 Model loading took 42.46 GiB memory and 86.440550 seconds          (gpu_model_runner.py:5368)
L43362 Available KV cache memory: 50.57 GiB
L43363 GPU KV cache size: 5,791,869 tokens                                 (kv_cache_utils.py:2177)
L43364 Maximum concurrency for 600,000 tokens per request: 9.65x           (kv_cache_utils.py:2178)
L43385 ...Actual usage is 42.46 GiB for weight, 1.84 GiB for peak activation,
       2.43 GiB for non-torch memory, and 0.0 GiB for CUDAGraph memory...  Current kv cache memory in use is 50.57 GiB.
L52130 DSpark draft model loaded: 105 params                               (dspark.py:507, VL boot)
L52134 Model loading took 45.56 GiB and 116.357144 seconds                 (model_runner.py:305, VL boot)
L52179 Available KV cache memory: 45.68 GiB
L52180 GPU KV cache size: 5,128,378 tokens
L52181 Maximum concurrency for 600,000 tokens per request: 8.55x
L52253 Graph capturing finished in 9 secs, took 1.13 GiB
L52254 ...Actual usage is 45.56 GiB for weight, 2.03 GiB for peak activation,
       4.03 GiB for non-torch memory, and 1.13 GiB for CUDAGraph memory...  Current kv cache memory in use is 45.68 GiB.
L52040 Using FP8 indexer cache for Lightning Indexer                        (attention.py:735, VL boot)
L52042 Checkpoint size: 156.29 GiB. Available RAM: 73.31 GiB.               (weight_utils.py:869)
L66084-66086 (VL 16:22 boot) 46.96 GiB / 5,271,621 tokens / 8.79x
L66159 ...45.56 weight, 2.03 activation, 2.75 non-torch, 1.21 CUDAGraph...
```

实时指标（2026-09-09 实抓，:8001/metrics）：
```
vllm:cache_config_info{block_size="4",cache_dtype="fp8_ds_mla",enable_prefix_caching="False",
gpu_memory_utilization="0.8",kv_cache_dtype_skip_layers="[]",kv_cache_max_concurrency="4.661621190997809",
kv_cache_size_tokens="2796972",num_gpu_blocks="46812",sliding_window="128", ...} 1.0
```
验收期快照（09-08 抓取，本地取证文件 kv6.txt）：`kv_cache_size_tokens="2720971"`、`kv_cache_max_concurrency="4.534953196574388"`、`num_gpu_blocks="45540"`。

## 附录 B：本地取证文件索引

- `kv2/kv3/kv5.txt`：验收 boot 台账抓取；`kv6.txt`：验收 cache_config_info 快照
- `kv8/kv12.txt`：V5b 基线 boot 台账；`kv26.txt`：本轮全量台账 grep + 双模型权重头扫描 + 实时指标
- `kv27.txt`：Prometheus 回溯 + 两 boot 配置原文提取
- 源码级证据（机制 §3.1）：见前序取证记录（kv_cache_utils.py / kv_cache_interface.py / compressor.py，docker run --rm 只读读取）
