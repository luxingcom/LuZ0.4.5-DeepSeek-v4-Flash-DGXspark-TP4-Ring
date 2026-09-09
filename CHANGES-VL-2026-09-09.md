# CHANGES — 2026-09-09（VL 生产定版）

LuZ0.4.5-DeepSeek-v4-Flash-**VL**-DGXspark-TP4-Ring 为现役生产视觉线，于 2026-09-08 由 V5b 文本线（k=7）完成切换，2026-09-09 冷数据窗口全量基准与归因收口定版。本文件为 VL 线变更记录（写法对齐 master `CHANGES-2026-09-02.md`）。

## 生产形态基线（VL）

- 引擎：vLLM 0.26.1.dev0+gd3d3b2cca（fork 基座，FlashInfer 0.6.18 + B12X MXFP4）
- 模型：`deepseek-v4-flash-vision-exp`（多模态识图 + 文本；Vision-Exp checkpoint 自带 DSpark 头）
- 量化：W4A4 full（`VLLM_MOE_W4A4=2`）+ CUDA Graph（`VLLM_MOE_W4A4_CG=1`）+ 池补丁（`VLLM_B12X_SHARED_WRAPPER=1`）
- MoE：`--moe-backend flashinfer_b12x`；KV `fp8_ds_mla`；`VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS=sparse_mla_sm120`
- 投机解码：**DSpark MTP k=6**（probabilistic，自同 checkpoint draft；护栏 `VLLM_DSPARK_MARKOV_REPL=0` 四机在位）
- 参数：max-model-len 600000 / max-num-seqs 12 / batched-tokens 4096（红线勿动）/ util 0.80 / CUDA Graph FULL_AND_PIECEWISE
- 服务链路：8003（responses 网关，模型别名映射）→ 8001（concurrency-proxy-v2，Bearer 鉴权 + 并发准入 + thinking 注入）→ 8002（vLLM 引擎）
- GPU 频率：**2200MHz 降频制**（现行生产制；09-02 散热修复后纪律延续）
- 与 V5b 差异核心：k 7→6、权重换 Vision-Exp（磁盘 +0.77 GiB vision，runtime 权重持平）、served-model 换名；KV 容量同口径持平（见下）

## 变更清单（2026-09-08 ~ 09-09）

### 生产切换（09-08）
- **V5b → VL 切换收口**：guard v3 链（flock 互斥 / stop workers→head / TCPStore fail-fast / start head→workers / health 轮询）**4 分 51 秒**完成（11:27:50 → 11:32:41 UTC），零 Traceback、零容器异常；四机脚本 md5 与 `.vl-final` 基准一致、镜像 manifest digest 四机一致、治理链完整（daily-smoke 停止、旧单元 masked、8003 回滚备份就绪）
- 切换执行事后审计**八项全 PASS**（脚本 md5 / 容器镜像 / 启动日志特征 / env / 挂载 / 8003 网关 / 治理链 / guard 日志），详见切换执行审计报告
- 切换前交叉审核定位 4 项 P0（runbook md5 验收口径修正 / 8003 模型映射 / monitor 预热模型名 / daily_smoke 模型名）均在窗口内落实；治理审计另定位 SERVED_MODEL_NAME 注入断点，以 vllm.env 注入方案闭环
- 8003 网关以 **B 案（env-only）**切换：`SERVED_MODEL=deepseek-v4-flash-vision-exp`，`local-v4-flash`/legacy 别名全部映射 VL，0731 名退役（404 语义正确）

### 上线验收（09-08）
- 六门验收 **5 PASS / 1 FAIL（如实归档）**：门1 健康 / 门2 GSM8K 三题 / 门3 视觉五门 g1-g5（单图/多图顺序/跨图/图内 OCR+数学/投机形态）/ 门4 长上下文（needle 30K + 哨兵 13.6K）/ 门6 投机指标 2.364（含 bonus，≥参考 A(6)≈2.08）全过；**门5 conc8 吞吐 98.0-106.5 < 120 tok/s 未达标**（conc4 达标）——督导裁定为版本属性、不阻断，机制归因按 KV 分解报告 worker 口径重述

### 性能与归因（09-08 → 09-09 冷窗口）
- **冷数据 49 格全套**（DE 18 + PR 30 + PR400K C2，3 波中位，uuid 冷算，严格串行单路负载，93°C 盯防 0 breach）：PR2048 C1 **2747.76 tps**（2200 制追平 master 2400 制峰值 2748）；PR400K C2 **955.88 tps / 368.18s**（vs V5b 同制 +3.7% / -3.6%）；PR131072 段 C4-C12 反超 +1.3%~+2.5%
- **GSM8K 思考预算修正**：1024 预算截断率 10.5%（截断组全错）→ 复测 2048 仍余 6.1% → **全量升级 4096 预算：content 0.9583（1264/1319）**，vs V5b 0.9363 = **+2.20pp**，VL 唯一精度占优大项；截断证据链完整（finish_reason 精确判定，判分抽查无误判）
- **DE coding/json 如实定级 FAIL**：coding 6/6 负（-12.7%~-20.5%）、json 6/6 负（-9.5%~-17.5%）、prose 持平略优——dspark 接受率 0.572 vs 0.652（-12.2%）、深位衰减快（p5 0.23 vs 0.47）
- **KV 口径反转定案**：此前"KV 池 2.72M vs V5b 5.9M 缩水 54%"表述**不成立**——三段精确分解：① scheduler/worker 口径折叠 ×1.884（-41.6pp）② V5b 交接基线 boot 非典型档案（eager+无投机+B 路径，-9.6pp）③ VL 真实差异 **-1.9pp（范围 -2.5%~+0.9%，处于 V5b 自身 11 次 boot 噪声带内）**→ 同口径 KV 容量基本持平；今后所有容量数字强制双口径标注（worker 启动打印为真实池容量，scheduler 值 = worker ÷1.884 保守下界）
- **投机头调研 + 服务器取证：三大工程根因候选全部排除**——#49133 draft 量化错配（backend 指纹 PRESENT + FP8 target 前提不成立）、FlyCockpit wrapper 拦截（无自定义包装类）、thinking 状态混杂（服务端 6b 探针裁决：默认态 reasoning=None、两态 accept_len 2.423 vs 2.648 无显著差）→ coding/json 退化维持 **draft 头对 code/JSON 分布拟合不足**假设；调优候选：k 截短 6→4（纯配置、同硬件社区实测支持）为首选，PR #47808 自适应验证 SM121 验证为中期项，draft 头重校准（NeMo recipe）为备选
- **视觉吞吐波动如实报告**：单流视觉冷 41.3 / 热 63.1 tok/s（-34.5%）——PIL 图像与描述非固定样本，波动源未定位；视觉五门独立 PASS，不构成能力回退证据，P2 以固定图像样本复测归因
- 冷/热双态对照：uuid 冷算下 12 格重叠 DE 中位偏差 ~3%，前缀缓存开/关不引入冷算伪差；缓存真实收益 = 生产重复前缀 TTFT 45×

### 镜像脱敏分发（09-09）
- **`LuZ0.4.5-VL-TP4-sanitized-20260909.tar.gz`（6.98 GiB）**：`docker export` + `docker import` ENV 白名单构造的单层扁平镜像；剔除 AR2_* 内网拓扑 ENV 4 项；resolv.conf/hosts/hostname 天然不入 tar；敏感面两轮扫描零命中、凭据文件不存在、`find +1G` 零命中（**零权重零密钥**）；SHA256 `ae7db30f…aaee9`；逐项披露见脱敏导出清单
- 镜像谱系四机一致性：生产镜像 RepoDigest 四机完全一致（源镜像 12.88GB 解压内容、RootFS 117 层 → 产物单层）；构造过程 3 次 import（首次遗漏 NVIDIA_REQUIRE_CUDA、二次空格拆分垃圾变量、三次定稿）如实披露

### 治理与文档
- 网关配套方案定稿：8001 长纯文本 prompt 门（rc3.7 设计稿，>12K 413 拒绝 + 多模态豁免，默认 off 零行为差）+ 8003 模型映射 B 案 + 视觉五门/边界测试脚本（本地 py_compile + node01 ast.parse 双验证）
- VL 分支开源归档筹备：本 CHANGES + README + docs/ 八篇报告（脱敏后），审计类三篇收录待裁定

## 性能指标入口

- 完整基准与最终指标：`docs/02-performance-benchmarks/vl-full-benchmark-2026-09-08.md`（warm 态）、`docs/03-final-metrics/FINAL-METRICS-VL-2026-09-09.md`（冷窗口 49 格定版）
- KV 口径权威口径：`docs/01-research-reports/vl-kv-memory-decomposition-2026-09-09.md`
