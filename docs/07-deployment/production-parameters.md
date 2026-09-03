# LuZ0.4.5 生产参数基线（唯一可信源）

**维护纪律**：本文档为**参数层唯一权威定义点**。任何调优/改参必须先在此登记（值 / 层级 / 依据 / 回滚 / 是否红线），再改对应脚本；脚本头注只写依赖锚点不复制数值。与 [FINAL-METRICS](../../docs/03-final-metrics/FINAL-METRICS-2026-09-02.md)、[g1r6 定版](../../docs/07-deployment/g1r6-release-finalization-2026-09-02.md) 交叉引用。

**env 分层优先级**（高→低，同名高层覆盖低层）：
1. **本文件层**：`start_tp4_*_v043.sh` 逐行注入（`scripts/w6_env.txt`）
2. **镜像烘焙层**：`/etc/nccl.conf`（LuZ-0.4.4+ COPY 入镜像）
3. **进程层**：SERVE_CMD 前缀 `LD_PRELOAD='/opt/libncclpin.so /opt/nccl-ringonly/libnccl.so.2'`

---

## 一、镜像形态基线（LuZ0.4.5-baked）

| 参数 | 值 | 语义 | 依据 |
|---|---|---|---|
| 镜像 | `REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-baked` | 定版镜像（autotune 内置, digest `_PH_BAKE_IMAGE_DIGEST_`） | [checkpoint-autotune-baked](../../docs/07-deployment/checkpoint-luz045-autotune-baked-2026-09-02.md) |
| base fork | vLLM 0.26.1.dev0 + B12X MGX / FlashInfer 0.6.18 | 引擎基座 | g1r6 定版 |
| 硬件 | 4×DGX Spark (GB10/sm_121a) TP4 环网, RoCE | 拓扑 | W6-W9 报告 |
| 时钟 | 2400MHz（完整矩阵制） / 2200MHz（PR400K C2 与 GSM8K 制, 09-02 热修复降频） | gb10-clock-cap | [g1r6 定版] §热安全 |

---

## 二、MoE 权重精度与算子开关（env 层）

| env 变量 | 生产值 | 语义 | 依据 | 回滚 |
|---|---|---|---|---|
| `VLLM_MOE_W4A4` | `2` | full W4A4（A4/B4 全量化）量化模式；`2`=full W4A4, 其他档位见上游 | README 基线 | 改 1/0 需重 benchmark |
| `VLLM_MOE_W4A4_CG` | `1` | W4A4 启用 CUDA Graph | 同上 | 置 0 降 graph 收益 |
| `VLLM_B12X_SHARED_WRAPPER` | `1` | shared 专家 pooled overlay 修复 | W9 G1r1 pool | 置 0 用裸 shared |
| `VLLM_MOE_DYNAMIC_TILE_CAP` | `0` | **0=解除动态 tile 封顶**（非"封 0"）；已实测 C4 ≥906 无振荡 | G1r6 W2 采纳 | 置默认/其他值回滚 |

---

## 三、FlashInfer / 采样开关（env 层）

| env 变量 | 生产值 | 语义 |
|---|---|---|
| `VLLM_USE_FLASHINFER_SAMPLER` | `1` | FlashInfer 采样器（配合 w4a4 sampler） |
| `FLASHINFER_DISABLE_VERSION_CHECK` | `1` | 免版本告警 |
| `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` | `/root/.cache/vllm/autotune-g1r6` | autotune 缓存固定路径（W9R10, 内部固化） |
| `VLLM_USE_BREAKABLE_CUDAGRAPH` | `1` | 可断 CUDA Graph |
| `VLLM_PREFIX_CACHE_RETENTION_INTERVAL` | `8192` | 前缀缓存保留间隔 |

---

## 四、NCCL / RoCE（env 层，22 项）

| 变量 | 值 | 要点 |
|---|---|---|
| `NCCL_ALGO` / `NCCL_NET` | `RING` / `IB` | ring 算法 + IB 网 |
| `NCCL_IB_HCA` | `rocep1s0f0,rocep1s0f1,roceP2p1s0f0,roceP2p1s0f1` | 四 RoCE 口 |
| `NCCL_IB_GID_INDEX` | `3` | **GID 索引 3；对端断电可致全零→NCCL 建链失败(errno 61)**，见 gid_preflight |
| `NCCL_MIN/MAX_NCHANNELS` | `4 / 4` | 固定 4 通道 |
| `NCCL_TUNER_THRESHOLD` | `40960` | tuner 阈值 |
| `NCCL_NET_PLUGIN` | `none` | 用内置, 禁插件 |
| `NCCL_SOCKET_IFNAME` / `GLOO_SOCKET_IFNAME` | `enP7s7` | 管理面 netdev |
| `VLLM_DP_MASTER_IP` | `_PH_NODE_IP_` | head 地址 |
| `VLLM_TOPO_SAME_NODE_MAP` | `0,1,2,3` | 同节点 map |
| 绑核 shim | `LD_PRELOAD libncclpin.so` | NCCL 线程落隔离核 8-9（V9），见 [roce-gid](../../docs/04-issues/roce-gid-index3-zero-fault-2026-09-03.md) |

---

## 五、vLLM CLI 参数（进程层）

| 参数 | 生产值 | 语义 | 红线 |
|---|---|---|---|
| `--kv-cache-dtype` | `fp8_ds_mla` | KV cache 精度 | — |
| `--max-model-len` | `600000` | 最大上下文 | 与 KV 预算耦合 |
| `--max-num-seqs` | `12` | 并行序列上限 | — |
| `--max-num-batched-tokens` | `4096` | 单步批 token 上限 | 🔴 **红线**：≥4608 触发 B12X MoE `max_num_tokens` 超硬上限崩溃（flashinfer 0.6.18 CUDA graph 静态容量），**不可调大** |
| `--gpu-memory-utilization` | `0.80` | 显存占比 | — |
| 投机 | dspark MTP `num_speculative_tokens=7, probabilistic` | 投机解码 | — |
| CUDA Graph sizes | 十六档（见脚本） | 捕获尺寸 | — |

---

## 六、高频坑位速查

| 场景 | 提示 |
|---|---|
| `ibv_modify_qp errno 61` | 先查 GID（`gids/3` 非零），勿误判 NCCL/驱动；`gid_preflight.sh --fix` |
| GPU 满载 >93°C | 03 号机曾过热断电；`gb10-clock-cap` 降频 / 温度巡检 |
| `num_tokens exceeds max_num_tokens` | `--max-num-batched-tokens` 触碰 4096 上限，勿上调 |
| autotune 每重启重编 | 若 `Loaded 24 configs` 未命中=缓存路径失配，查 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` |

*本文档由综合审查产出（Rex/Archi 建议合并），作为后续调优登记的单一入口。*
