# 运维交接：生产版本（V5）待修复补丁与 Bug 完整清单

日期：2026-09-07 ｜ 适用对象：当前生产 `TP4-Ring-V5`（digest `<BAKE_IMAGE_DIGEST>`，0731 权重，k=7，mmlen 600000，引擎 fork v0.26.1.dev0+gd3d3b2cca）
核实方式：本文所有"在产状态"均为 2026-09-07 当日只读实证（容器日志/镜像内容探针/env 快照），非推断。
配套文档：总编排 [G1R7VL-PROD-TUNING-MASTERPLAN-20260907.md](./G1R7VL-PROD-TUNING-MASTERPLAN-20260907.md)；baked5 蓝本 `g1r7-build/vl-baked5-ctx/`。

---

## 0. 总览表

| 编号 | 名称 | 类别 | 优先级 | 载体 | 默认状态 | 结论 |
|---|---|---|---|---|---|---|
| A1 | SKIP_MTP_COPY 条件反转（死拷贝） | **bug** | **P0** | V5b 镜像 | 修复即生效 | 本轮必修 |
| A2 | #54815 RoPE/YaRN-SWA 长上下文正确性 | **bug（已实锤）** | **P0** | V5b 镜像补丁 | 未修复 | 本轮必修（§1b） |
| A3 | #55636 warmup 越界 2 行防护 | bug(防御性) | P2 | V5b 镜像补丁 | 未修复 | 搭车（§1c） |
| B1 | C1 Markov 双复制（消 14 次串行跨机通信/步@k7） | 优化 | P1 | V5b 镜像 | env 门默认关 | 搭车带入 |
| B2 | C2 draft MoE topk 封顶 | 优化 | P3 | V5b 镜像 | env 门默认关 | 搭车带入（仅 A/B 用） |
| B3 | 权重加载多线程 flag（零补丁） | 优化 | P1 | 启动脚本参数 | 未启用 | 本轮可开 |
| B4 | draft 加载二遍全量扫描修复（mtp 分片子集） | 优化 | P2 | V5b 镜像补丁 | 未构建 | 可选搭车 |
| C1-C3 | ~~待子代理结论~~ | — | — | — | — | **已落定：V 组判 fork 结构性不中，全部 reject/N-A（见 §3）** |
| D1 | 重启 autotune 死锁防护程序 | 程序 | **P0(程序)** | 重启 runbook | — | R 组 checklist 已回填 §5.1 |
| D2 | window_restart TCPStore 超时仍起 worker | 工具 bug | P1 | guard 脚本 | 已记录两次未修 | 本轮修 |
| D3 | 切换窗 env 清单携带与核对 | 程序 | **P0(程序)** | 脚本 | — | §5.3（37 变量快照） |
| D4 | 8001 长 prompt 准入控制 | 待办功能 | P2 | 代理层 | — | 排队真因的解法，另行排期 |
| D5 | live 脚本共享编辑纪律 + 陈旧容器清理 | 程序 | P2 | — | — | §5.4 |
| E1 | #49002 DSpark+tool-call 停顿监控 | 观察 | P1 | Grafana | — | §6.1 |
| E2 | mmlen 600000 vs KV 池容量核对 | **风险核对** | **P1** | 只读 | — | §6.2（历史实测池仅 ~103K tokens） |
| E3 | eugr#358 塌缩筛查 / render_message 缓修 / 192 autotune 键 / TPOT 口径 | 观察 | P2-P3 | — | — | §6.3-6.6（eugr#358 当前干净，R 组两护栏条件） |

**明确不带入本轮**：TK512 kernel（0731 SWA 恒 128 用不到，属 VL 分支）；VL 全链补丁（Phase C 单独构建）；flashinfer main 重建（待 K 组结论+专窗 A/B）；k 调整（脚本级，不在镜像，随 B窗1 三臂 A/B）。

---

## 1. A1（P0，必修）：SKIP_MTP_COPY 条件反转 — 死拷贝每步在跑

- **位置**：镜像内 `/usr/local/lib/python3.12/dist-packages/vllm/models/deepseek_v4/nvidia/model.py` **第 1141 行**（当日探针实证）。
- **现状**：`if os.environ.get('VLLM_DSPARK_SKIP_MTP_COPY', '1') != '0':` → 默认（env 未设='1'）条件为真 → `self._mtp_hidden_buffer[:num_tokens].copy_(...)` **每步执行**。该 buffer 下游（DSpark）不消费，是纯白拷（W9-R9 权重计算审计同源结论："_mtp_hidden_buffer 128MB 死路径"）；满批 prefill 268MB/步 + 每次 launch 开销，属 TTFT/step 净浪费。注释（1139-1140 行）写明意图是默认跳过、`=0` 回退——条件写反了。
- **修复（1 字符）**：`!= '0'` → `== '0'`。修复后语义：env 未设=跳过死拷贝（注释原意）；`VLLM_DSPARK_SKIP_MTP_COPY=0`=恢复当前行为（回退开关）。
- **验证**：已在 VL 线 baked5 同修复验证过（py_compile + 正门 `== '0'` 存在 + 负门 `!= '0'` 不存在 + boot 正常 + GSM8K 全对）。上产后看 prefill 段耗时与日志无异常即可。
- **风险**：极低（单分支布尔反转，回退=设 env 0，无需回滚镜像）。

## 1b. A2（P0，必修，已实锤）：#54815 — SWA 层被错误套用 YaRN

**判定过程（2026-09-07 当日完整链条实证）**：
1. 0731 config.json：`rope_parameters=null`、`rope_scaling={type:"yarn", factor:16, original_max_position_embeddings:65536}`、`rope_theta=10000`、`compress_rope_theta=160000`、`sliding_window=128`、`compress_ratios` 混排 4/128。
2. 镜像 `transformers_utils/configs/deepseek_v4.py:22`：`self.rope_parameters = rope_scaling or rope_parameters` → **0731 的 rope_parameters = 那个 yarn 字典**。
3. `common/rope.py build_deepseek_v4_rope`：SWA 层（compress_ratio≤1）theta 取 10000（这步正确）；但随后 `if rope_type != "default"` → 0731 的 rope_type 是 **"yarn"≠"default"** → 走 `apply_yarn_scaling` 分支，而 **`apply_yarn_scaling` 默认 True** 且 0731 字典里没有这个键 → **SWA 层也拿到 "deepseek_yarn"（factor=16）**。
4. `rotary_embedding/__init__.py:284` → `DeepseekV4ScalingRotaryEmbedding`（yarn 插值 inv_freq：低频维按 factor 16 压缩）；正确行为（上游 #54815 后）SWA 层应为 plain theta=10000。
5. 数学差异：低频维 inv_freq 差 16×（如 0.000316 vs 0.00002），**位置越远偏差越大；ompe=65536 之后（生产 mmlen 600000 恰在 YaRN 外推区）偏差最大**。fork 已置 mscale=0 使幅度因子中性，但频率插值差异无法抵消。

**修复方案（2 行，改 `common/rope.py`）**：在 `rope_parameters` 处理前为 SWA 层强制 plain 路径——`compress_ratio <= 1` 时设 `rope_parameters = dict(rope_parameters); rope_parameters["rope_type"]="default"`（或加 `apply_yarn_scaling=False`），保留 compress 层（ratio>1）的 deepseek_yarn 语义不变。对照上游 #54815 的最终形态核对命名。
**验证**：修复前先跑 30K/128K/500K needle 各 4 针（当前生产预期在 >65K 区显著劣化）；修复后复跑应全对；另 GSM8K10 哨兵（短上下文不受影响，应零变化）。
**风险**：低（只动 SWA 层 rope 构造，compress 层路径不变；短文本完全无感）。**注意**：此 bug 也存在于 VL 线镜像（同一 rope.py）——VL 分支构建时一并带上。

## 1c. A3（P2，防御性搭车）：#55636 warmup 越界 2 行防护

R 组在 fork `models/deepseek_v4/common/ops/cache_utils.py:461-508` 逐字定位到上游报告的脆弱内核（req_idx 无界、local_idx 只查下界）。历史 boot 干净=低现险，但存在静默错 KV slot 模式。修复=2 行 bounds mask（-1 哨兵）+ 可选 boot 行数断言，随 V5b 一起构建。

## 2. P1/P3 优化补丁（随 V5b 搭车，env 门默认关 = 零行为差）

### B1：C1 Markov 双复制（`VLLM_DSPARK_MARKOV_REPL=1` 启用）
- 机理：DSpark Markov 头的 w1（VocabParallelEmbedding）/w2 逐迭代产生 12 次串行跨机小消息（6 allreduce+6 allgather，占 draft 通信面 20 次/步的大头）；复制化为每 rank 本地表（+132MB/rank 显存）后全部消除。数值位级中性已在真实权重离线证明（行分片 matmul == 全量 matmul）。
- 改动文件：`qwen3_dspark.py`（DSparkMarkovHead 加 `replicate` 参数+分支+fp32 bias 路径）+ `dspark.py`（构造入口读 env）。0731 文本路径与 VL 同构，同样生效。
- 预期：+2~4% decode（窗口 A/B 定量）。默认关；启用=启动脚本 env。
### B2：C2 draft topk 封顶（`VLLM_DSPARK_DRAFT_TOPK=<n>`）
- 三处联动 override（router.top_k / moe_config / n_activated_experts）。离线判高风险（topk6 位置 5-6 承载 ~32% 质量），**默认关、仅日后 A/B**，带入是为了不再动镜像。
### B3：加载多线程（零补丁，立即可用）
- fork 自带 `--model-loader-extra-config '{"enable_multithread_load": true, "num_threads": 8}'`（default_loader.py:47）。现状未启用。四机加载 93.5-172.1s，NFS 侧（rank2/3）受益最大。
### B4（可选）：draft 加载二遍扫描修复
- 现状：DSpark draft 取 96 个 mtp 参数会**重扫全部 48 分片 ×155GiB**（`dspark/utils.py:41`）。补丁=按 index weight_map 只读 mtp 所在的 46/47/48 三分片（10.12GiB，纯度 99.995%）。收益=每 rank 省 ~145GiB 读，boot 段显著缩短；env `VLLM_DSPARK_LEGACY_FULLSCAN=1` 回退。中等工作量，若本轮来不及可下轮（与 VL 分支共享此补丁）。

## 3. 子代理结论回填（V/F/R 三组已交付，K/S 后补）

| 项 | 裁定 | 依据（报告） |
|---|---|---|
| #55341 图捕获前 warmup | **reject** — fork 已实现（`_warmup_and_capture` eager warmup + lock_workspace，gpu_model_runner.py:6859-6914） | D-v-upstream item3 |
| #55299 prefill 哨兵 | **reject/N-A** — fork `combine_topk_swa_indices` 恒 `torch.full(fill_value=-1)`（cache_utils.py:549-554），bug 结构性不存在 | D-v-upstream item4 |
| #55234 DSpark cache-group | **reject/N-A** — 特性在位（sparse_swa.py:485-510），回归 #54277 晚于 fork | D-v-upstream item5 |
| #55455 adaptive verification 延迟 | **reject/N-A** — fork 无 adaptive verification（grep=0） | D-v-upstream item6 |
| #54631 DSpark block size | **reject（无需移植）** — fork 校验语义已覆盖 0731 k=7 / vision k=6；⚠记 rebase 风险：上游合入后 k=7/k=6 可能触整除失败（k→{5,10}） | D-v-upstream item2 |
| #51725+#47808 自适应预算 | **defer→rebase 后免费获得**（XL 移植量 vs 当前 c≤96 的 ±3% EV）；列为 rebase 头号动机 | D-v-upstream item1 |
| #54815 rope | **adopt-now（P0）** — 见 §1b，已实锤 | D-r-stability item1 + 当日实证 |
| #55636 防护 | **adopt-after-next-build（P2 搭车）** — 见 §1c | D-r-stability item4 |
| eugr#358 stale draft KV | **defer + 两护栏**：fork 未触碰 v1/spec_decode（changed_files.txt 证据），衰减筛查通过（探针窗 MAL 2.93 vs 窗外 3.98、探针后 30s 内回弹、p0 接受率从不低于 0.75 而 eugr#358 钉死在 ~0.02）。护栏=①MAL<2.0 看门狗 ②VL 切换前 60min soak | D-r-stability item3 |
| C1 文本移植 | **adopt-now** — V5↔baked5 差异仅 C1+C2 三文件，无 vision 分支，纯 drop-in；k=7 通信面修正为 22 次/step（F 组），消 14 次 | D-f-forkcode item1 |
| SKIP 修复 | **adopt-now 升满级** — 完整调用面审计：`_mtp_hidden_buffer` 唯一读者 runner:5167 备用绑定，dspark aux 路径下死代码 | D-f-forkcode item2 |
| #50424 W4A16 markov_w2 | **adopt-after-C1** — 与 C1 叠加（C1 复制化后 W4A16 多赚 4 倍：−1.26ms/step≈+2.5%）；非位级中性（需离线量化 mtp.2 一个张量+数值门） | D-f-forkcode item7 |
| C6a regret 控制器 | **adopt-after-k5/E1** — ~150-250 LOC，scheduler 级零模型改动，信号已在 update_from_output 中 | D-f-forkcode item4 |
| C6b confidence head | **defer** — 权重在位（mtp.2.confidence_head.proj.weight，两 checkpoint 均有）但 fork 零消费者，激活需 SM12x varlen graph 大件 | D-f-forkcode item6 |
| drafter 私有 CG sizes | **verify-at-k5-window（很可能 N/A）** — fork 已是 round_up(num_tokens, decode_query_len) 均匀 descriptor 血统；k=5 时验证≈免费 | D-f-forkcode item5 |
| C2 topk 封顶 | **defer/A-B only（不变）** — 高风险维持 | D-f-forkcode item7 |
| k=7→k=5 决策 | **adopt-after-A/B（两臂即可）** — 盈亏平衡 t(5)：prose 49.1/code 47.6/json 46.8/背景 45.3ms（t7=49.7）；**决策门=单次 k=5 boot 中位 t(5)<46.8ms 即切换**；k=6 数学上从不是 >2% 的唯一赢家（从 A/B 删除）；k=3 需 F>0.8 拒绝；MiaAI 实测 k5vs k6 +2.4-5.6% 暗示 F≈0.34-0.54 有利；**k=5=dspark_block_size 训练形状**（block-k 溯源佐证）；附带门=p1..p5 曲线与 k=7 审计一致（截断精确性） | D-s-config item1/4 |
| 流量混合监控脚本 | **adopt-now（零风险）** — `perf-inv/spec_mix_monitor.py` 已在 68 行样本验证（滚动 p 曲线/A(k)/尾部/最近审计混合/t(k) 重排，--watch/--json 模式）；A/B 后用 `--f` 校准 F=1−4·(1−t5/49.7) | D-s-config item2 |
| 动态 per-request k | **defer** — k 为 boot 静态（buffer/index/预留全静态）；#51725 实为调度器 token 预算重构非 adaptive-k（我们 seqs=12 时静态税 ~2% 近零）；真动态 k=#47808+varlen decode graphs（SM12x 未证明）+confidence_head（我们 loader 丢弃）；静态 k+监控+步粒度淬灭控制器优先 | D-s-config item3 |
| block-k 补丁 | **reject（无物可移植）** — 溯源=MiaAI 一行条件补丁（放宽 n_predict 整除校验，让 vision n_predict=3 能跑 k=5），我们 0731 n_predict=1 任意 k≥5 已合法；其 +2.4-5.6%=k5vs k6 步时差与 S-1 互证；⚠voktolom "JSON+15%" 数字原始来源不可定位（source gap 记账）；rebase 陷阱：#54631 若无条件合入，text k=7 会被拒（若已切 k=5 则 moot） | D-s-config item4 |
| F1 flashinfer main 重建（#4802=`453aa7c`） | **adopt-after-gates** — 合并触及 decode+prefill 内核：quantize_q 单遍、单索引读 gather（小 T decode −24%、位级一致）、连续 H∈[1,128] envelope（杀 TP4 pad-to-128，off-grid H=80 例 +1.14×）、标定解析 cpb（带 L2 足迹守卫）替代 autotune、crossover 重路由 DSv4 topk-128 −27%/topk-512 −26% @T∈{24..64}——**我们 decode T≈96 正在此域，步时效应界 −1%~−5% of 49.7ms**。构建=源码 csrc/jit 换入现有 0.6.18 包（PyPI 无 aarch64 wheel），**精确 pin `453aa7c`**（其后 14 commits 无一触 sparse_mla_sm120=pin 干净；避开 09-05 autotune-v2）；删死 tactic 缓存+离线标定 schema-v1；**TK512 手补丁退役确认**（arms 已并入）；可选 `prefill_impl="swapab"`（VL prefill 1.37-1.79×）。门：zero-KV→zero-output/VL span 原子性/text tok/s + **Gate-4 #4973 replay** | D-k-kernel item1 |
| #4931 ragged prefill 去同步 | **reject** — 本地验证：DSV4 sparse 路径调 `flashinfer_trtllm_batch_decode_sparse_mla_dsv4`，从不调 `trtllm_ragged_attention_deepseek`（flag 是 0.6.19-only per-call kwarg） | D-k-kernel item2 |
| #55180 SM12.x FP8 L2 swizzle | **defer** — decode M≈96 远低于 14MiB 激活守卫=零 decode 效应；~30-60 行，仅当 FP8-blockwise dense 权重实际配置时再取（rebase 清单） | D-k-kernel item3 |
| #54110 persistent topk 回退 | **reject（no-op）** — GB10 确是目标类（101KiB SMEM）但我们 fork 早于 persistent_topk，现跑的 `top_k_per_row_decode` 就是该 PR 要装的那个 fallback；rebase 时自然获得 | D-k-kernel item4 |
| #4990 grouped MoE latency-bound | **defer（track）** — 我们正处 latency-bound 域（≤96 rows/~256 experts ≈ M=1-4，kernel 1.2-1.6× 高于字节下限，潜在 2-4ms/step）；issue 排除一切 config 旋钮，需上游 2-CTA/SM 内核变体（尚无修复）；每周盯 | D-k-kernel item5 |
| **#4973（VL 风险类，bonus）** | **观察+缓解** — DSV4-Vision 在 ~13.6k 纯文本 prompt IMA，两种 topk-512 实现（手补丁与上游）都复现，issue 仍开。**我们 baked5 VL 镜像在风险类**：临时缓解=生产长纯文本 prompt 路由出 VL（文本走 V5 线）；F1 A/B 加 Gate-4 replay | D-k-kernel bonus |

## 4. V5b 构建规范（运维执行）

1. **前置鉴定（必须先做）**：V5 含 2 个 60MB `sleep 300` docker-commit 层（09-05 前后，内容未知）。方法：`docker save` V5 与其父层对比，或起 throwaway 容器 `diff -r` 关键目录（`vllm/`、`flashinfer/`、启动脚本、env 文件）。确认与下列三文件补丁无冲突后才能开工。
2. **⚠ 血统警告：不能整文件拷贝 baked5 ctx**。VL 线 model.py 与 V5 的已分叉（同一条件 V5=1141 行，baked5 ctx=1172 行，偏移 31 行）。正确方法：
   - 从 V5 提取三个目标文件的原版：`model_executor/models/qwen3_dspark.py`、`models/deepseek_v4/nvidia/dspark.py`、`models/deepseek_v4/nvidia/model.py`；
   - **model.py**：只做 1 字符 diff（§1）；**dspark.py/qwen3_dspark.py**：先比 V5 原版 md5 与 VL 线基座原版（work 树参照 `g1r7-build/work/vllm/`）——一致则可直接落 baked5 已打补丁版（md5 `ab111bc9…`/`9f170d3f…`），不一致则按 baked5-ctx 的 hunks 手工移植；
   - 重算补丁后 md5 写入 Dockerfile 断言。
3. **Dockerfile 门**（沿 baked5 纪律）：FROM V5；COPY 3 文件；RUN 门=py_compile×3 + 基座文件预断言（防 V5 漂移）+ 补丁后 md5 断言 + 正门（`== '0'`、`MARKOV_REPL`、`DRAFT_TOPK` 存在）+ 负门（`!= '0'` 不存在、默认关路径正确）。注意 Dockerfile heredoc 里 `from` 会被解析成 FROM 的历史坑。
4. 命名建议：`LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-V5b`；推 node02 registry；四机预拉 + md5 抽验。
5. **不在镜像内**：k 值（脚本）、任何 VL 内容（Phase C 从 V5b 出）。

## 5. 运维程序与工具项

### 5.1 重启死锁防护（本轮 V5b 切换窗即需；R 组 T-1/T-0 checklist）
背景：#52291（多节点 autotune 死锁，open；分布式 autotuner 每 tactic all-reduce 在 host-staged NCCL 上死锁——GB10 级 fabric 正中）、#52292（opt-out，已获 DSV4+DSpark 实地验证但未合）、**#54618（暖缓存模式：部分 rank 命中缓存跳过其他 rank 在等的 all-reduce——首次冷启 OK、下次重启挂起）**。我们四机共用镜像内固定路径缓存 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/root/.cache/vllm/autotune-g1r6`，同镜像+完整缓存可缓解，但 topk/C128A 缓存键缺口（#53600）会重新暴露冷路径。程序：
- **T-1（重启前一晚）**：四机 autotune 缓存目录 md5 对比（必须字节级一致且完整）；不一致则统一清空（走全冷路径）或统一恢复同一份；
- **T-0（重启时）**：若镜像内有 `VLLM_FLASHINFER_AUTOTUNE_DISTRIBUTED_SYNC` 变量可设 0（workaround：各 rank 独立 tune）；
- **中止签名**：rank0 停在模型 all-reduce + rank1-3 卡在 autotune all-reduce、GPU0 100% 其余空闲 → 判死锁；**禁止单机重启（必败，历史事故），四机协同 stop→清缓存→guard 重来**；
- boot 卡 autotune 阶段 >5 分钟即按上述流程处置。
### 5.2 D2：window_restart TCPStore 缺陷
现象已记录两次（W2 07:05 链等）：TCPStore 超时后仍继续起 worker，产生分裂集群。修复=guard 脚本对 TCPStore 超时路径直接 fail-fast 全四机。属 guard 脚本（`w9r4_restart_guard.sh`）小改，建议本轮窗口前修掉。
### 5.3 D3：env 清单携带（切 V5b 时必查）
当日快照（37 个有效变量）已留档 `w6-logs/g1r7-tune-20260907/`。**必须携带的关键开关**：`VLLM_MOE_W4A4=2`、`VLLM_MOE_W4A4_CG=1`、`VLLM_B12X_SHARED_WRAPPER=1`、`VLLM_MOE_DYNAMIC_TILE_CAP=0`（解封 tile 封顶，现役已设）、`VLLM_USE_BREAKABLE_CUDAGRAPH=1`、`VLLM_ALLOW_LONG_MAX_MODEL_LEN=1`（600K 的准入开关）、`VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/root/.cache/vllm/autotune-g1r6`、`VLLM_PREFIX_CACHE_RETENTION_INTERVAL=8192`、全套 NCCL ring/IB 变量（含 `NCCL_TUNER_THRESHOLD=40960`、HCA 四口清单）。**清理候选**：`FLASHINFER_DISABLE_VERSION_CHECK=1`（G1r4 修复后的惰性残留，可在 V5b 窗口顺手去除并观察 boot）。
### 5.4 D5：纪律与小项
- live 脚本是共享资产（他人 09-03 00:32 版 md5 `8cab7652`）：任何修改先 `.bak-<tag>-<date>` + 记录四机 md5 一致性；
- 陈旧容器（如 node01 的 `wizardly_hoover` Created 残留）可在窗口顺手清理；
- logdump 调试期启用、完成即关（纪律不变）。

## 6. 观察与监控项（无本地修复，需上报/盯盘）

1. **#49002 DSpark+tool-call 边界停顿**（上游 issue）：生产 auto-tool-choice=ON 正中场景（历史报告 5-12s 停顿）。建议在 node01 现有 prometheus/grafana 栈加 ITL P99 面板+告警，出现长停顿抓 logdump。
2. **mmlen 600000 vs KV 池容量（重要核对）**：W9-R8 实测 B4096 形态 KV 池仅 ~103K tokens；V5 宣称 600K。若池未扩，>100K 的请求会持续排队/抢占。请核对当前 boot 日志的 KV pool 实际值（grep `GPU KV cache size`/`Maximum concurrency` 行），与调用方确认长上下文诉求真实性；不符要么调 mmlen 要么扩池（util/缓存方向），避免线上踩坑。
3. **#55636**（GB10 sparse-MLA warmup 越界，open 无 workaround）：我们历史 boot 干净不符，维持观察；boot 哨兵=启动日志零 `cudaErrorIllegalAddress`/零异常行。
4. **eugr#358 acceptance 塌缩**（持续负载下接受率衰减，MiaAI fork 补丁根因）：R 组正在用当日指标样本做衰减筛查；若发现趋势→升级为 bug 项。
5. **render_message/merge_tool_messages 内容防御缺失**：有意缓修（修复会与 VL 分支 PR#54566 的行冲突）。触发条件：出现 null-content/list-content 类 500，或 VL 分支稳定后随迁。
6. **192 系 autotune 键未落盘**（G1r5 残留，heuristic 兜底 <1%）：低优先，下次 autotune 窗口顺手。
7. **监控 TPOT 口径失真 2.4×**（W9-R9 记录）：Grafana 面板解读时注意，勿据面板值做决策。

## 7. 建议上产顺序（B窗1 runbook 简版，全长见 MASTERPLAN §2）

1. （无窗）V5 两个未知 commit 层鉴定 → V5b 构建（§4）→ 推送/预拉；
2. （无窗）guard 脚本 D2 修复 + env 清单核对（§5.2/5.3）+ 四机 autotune 缓存一致性检查（§5.1）；
3. **B窗1（~90min）**：guard 协同重启 V5b@k=5 → 门（health/GSM8K10/三负载探针/背景指标形态）→ 视结果 k=6 臂 → k=7 复核基线 → 定稿；
4. 回退总链：镜像异常=R5 指回 V5；C1 异常=去 env；SKIP 异常=`VLLM_DSPARK_SKIP_MTP_COPY=0`；k 异常=回 7。全部一层回退，无需连锁。

## 8. 状态与更新记录

- 2026-09-07 初版：A1/B1-B4/D/E 全部条目按当日实证落定；C1-C3/D1 四项待 K/V/R 子代理报告回填。
- 2026-09-07 更新 1（V/F/R 三组报告回填 + #54815 实锤）：新增 **A2 #54815 为 P0 必修**（当日镜像内代码链条全程实证 SWA 层中招，见 §1b）；新增 A3 #55636 防护搭车（§1c）；C1-C3 全部落定（V 组四 reject + #54631 reject + #51725 defer）；§5.1 更新为 R 组 T-1/T-0 checklist；§3 增补 F 组裁定（C1 adopt-now/SKIP 升满级/W4A16 adopt-after-C1/C6a/C6b/drafter-CG/C2）。K/S 两组报告待出（限额中断后重派中），回填 §3 后为终稿。
- 2026-09-07 更新 3（K 组回填，**终稿**）：五组报告全部交付（D-{v,f,r,s,k}-kernel/config/forkcode/stability/upstream-20260907.md）。K 组要点：F1=adopt-after-gates（pin `453aa7c` 源码换入、TK512 退役、步时界 −1~−5%、Gate-4=#4973 replay）；#4931 reject（DSV4 路径不经过）；#55180 defer；#54110 reject（我们跑的就是它的 fallback）；#4990 defer track（潜在 2-4ms/step 待上游 2-CTA/SM 变体）；**#4973 VL 风险类（长纯文本 prompt IMA）→ 缓解=生产长纯文本路由出 VL + F1 加 replay 门**。清单全表定稿，运维可直接按 §4/§7 执行。
