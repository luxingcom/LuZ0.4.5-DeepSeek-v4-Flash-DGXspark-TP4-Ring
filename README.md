# LuZ0.4.5 — DeepSeek V4 Flash **VL** · DSpark · DGX Spark TP4 · Ring

4× DGX Spark（GB10/sm_121a）TP4 环网部署 DeepSeek V4 Flash **视觉线（VL）**的现役生产快照归档：多模态识图 + 文本推理双能力，k=6 DSpark MTP 投机解码。

**生产形态基线（VL）**：W4A4 full（`VLLM_MOE_W4A4=2`）+ CUDA Graph（`VLLM_MOE_W4A4_CG=1`）+ 池补丁（`VLLM_B12X_SHARED_WRAPPER=1`）+ FlashInfer 0.6.18 + `--moe-backend flashinfer_b12x` + TILE_CAP=0 + autotune 手动固化 + util 0.80 + **DSpark MTP k=6**（probabilistic，served-model `deepseek-v4-flash-vision-exp`）。服务链路：**8003**（responses 网关）→ **8001**（concurrency-proxy-v2 鉴权/并发网关）→ **8002**（vLLM 引擎）。

> 本分支为 VL 视觉线独立归档；文本线（V5b，k=7，served-model `deepseek-v4-flash-0731`）见 master 分支。VL 已于 2026-09-08 完成生产切换（V5b→VL），为当前现役线。

**变更记录**：见 [`CHANGES-VL-2026-09-09.md`](CHANGES-VL-2026-09-09.md)（V5b→VL 生产切换 / 冷窗口 49 格全套 / GSM8K 思考预算修正 / KV 口径反转定案 / 投机头三根因排除 / 脱敏镜像分发）；**2026-09-10 起追加** [`CHANGES-2026-09-10.md`](CHANGES-2026-09-10.md)（S1 置信门控补丁集 / 参数组合门禁定谳 / G4 双臂验收 PASS / 自愈链冷却窗缺陷 / 接受率护栏）。

**S1 置信门控补丁集（默认关门）**：现役镜像已并入主体 4 补丁（gate-off 形态，G4 双臂验收 PASS），提供 `VLLM_DSPARK_CONF_GATE` / `VLLM_DSPARK_CONF_MIN` 两个 env 门控，为 G2 开臂（置信驱动的 per-request 验证截短）提供同一镜像的开闸能力。见 [`patches/conf-gate-s1-20260910/`](patches/conf-gate-s1-20260910/README.md)。

**最终性能指标**：见下方「典型性能指标」与 **[FINAL-METRICS-VL 完整测试报告](docs/03-final-metrics/FINAL-METRICS-VL-2026-09-09.md)**。

---

## 📊 典型性能指标（冷数据口径 · 前缀缓存关闭 · 2200MHz · 3 波中位）

> 完整 49 格矩阵（DE 18 + PR 30 + PR400K C2）、原始数据与口径说明见 **[FINAL-METRICS-VL 完整测试报告](docs/03-final-metrics/FINAL-METRICS-VL-2026-09-09.md)**。
>
> **⚠️ 关于前缀缓存（prefix caching）的说明**：本报告所有性能数据均在**前缀缓存关闭**（`--no-enable-prefix-caching`，metrics `prefix_cache_hits=0` 实证）的**冷数据口径**下测得——目的是消除缓存命中干扰，反映引擎对全新请求的真实处理能力。**生产部署中该功能默认开启**（生产实测相同前缀第二请求 TTFT 从 9.92s 降至 0.22s，约 45×）；uuid 冷算下冷/热双态 12 格重叠 DE 中位偏差 ~3%，前缀缓存开/关不引入冷算伪差。复现基准时请保持关闭以对齐口径。
>
> **⚠️ 时钟制说明**：本报告全程 **2200MHz 降频制**（现行生产制）。master 分支 09-02 报告矩阵段（DE/PR）为 2400MHz 制、其 PR400K/GSM8K 段为 2200MHz 制——与矩阵段对比时 VL 处 ~8% 时钟劣势，与 PR400K/GSM8K 段同制。各表对比均已按此解读。

| 指标 | 结果 | 备注 |
|---|---|---|
| PR2048 C1 prefill | **2747.76 tps** | vs master 2400 制峰值 2748 **持平（0.0%）**——2200 制下追平 |
| PR400K C2（更大压力） | prefill **955.88 tps** / TTFT **368.18s** | vs V5b 同 2200 制 921.5/381.86 = **+3.7% / -3.6%**，VL 占优 |
| GSM8K 全量（1319 题） | **content 0.9583 / marker 0.9575** | vs V5b 0.9363 = **+2.20pp**，VL 相对 V5b 唯一精度占优大项 |
| DE coding decode | **6/6 格 FAIL**（-12.7%~-20.5%） | 如实标注；归因 draft 头对 code/JSON 分布拟合不足（thinking 混杂已排除） |
| DE json decode | **6/6 格 FAIL**（-9.5%~-17.5%） | 同上；prose 6 格持平略优（-2.1%~+5.7%），排除引擎普遍性减速 |
| 单流视觉吞吐 | 冷 41.3 / 热 63.1 tok/s | ⚠️ PIL 图像与描述非固定样本，波动待归因（视觉五门 g1-g5 均独立 PASS，不构成能力回退证据） |
| 投机长生成 | 冷态 **2.191** token/前向（含 bonus） | ≥ 参考 A(6)≈2.08，PASS；热态 2.144（+2.2%） |
| 温度 | 满载 82-90°C（PR400K 峰值 90°C） | 93°C kill-line 盯防 **0 breach** |

### DE/PR 排名结论（vs master 基线）

- **prefill 全线追平**：PR2048-32768 段 -0.0%~-5.1%（2200 制时钟劣势下），PR131072 段 C4-C12 **+1.3%~+2.5% 反超**；唯一显著负格 PR512_C12（-16.2%，单格、3 波中位稳定复现，聚焦复测候选）
- **decode 排名**：coding 6/6 负（FAIL）、json 6/6 负（FAIL）、prose 持平略优——VL dspark 接受率 0.572 vs V5b 0.652（-12.2%），深位衰减快（p5 0.23 vs 0.47），退化集中于 code/JSON 高熵 token 分布（draft 头分布拟合问题）；thinking 状态混杂已由服务端探针排除
- 总吞吐：峰值总PR C1 2747.8 → C12 **4844.8 tps**（PR32768）；峰值总DE C1 93.0 → C12 **363.5 t/s**（json）。总PR 与总DE 共享 GPU 算力/带宽（B12X MoE），**不可叠加**

**结构化数据**：矩阵原始数据位于服务器 `bench3-results/vl-cold-20260909/`（49 格 CELL_RESULT + 各格 summary_v2.json），data JSON 归档随后续素材包补入。

---

## 📥 镜像下载

- **脱敏检查点镜像**：`LuZ0.4.5-VL-TP4-sanitized-20260909.tar.gz`（**6.98 GiB**，零权重/零密钥）
  - SHA256：`ae7db30f5d9173399e5ca6fcd7f1bf17d74c8f1225224c3d7fc33106979aaee9`
  - MD5：`b5934e6ec09187e06204b9e2efef0565`
  - 百度网盘：<https://pan.baidu.com/s/1GLuK_z3OaJXbPZ4q5ySAZg?pwd=luzi>（提取码：`luzi`）
  - 加载方式：`docker load < LuZ0.4.5-VL-TP4-sanitized-20260909.tar.gz`
  - 部署/校验/剔除项披露：见 [`docs/07-deployment/vl-image-sanitization-manifest-2026-09-09.md`](docs/07-deployment/vl-image-sanitization-manifest-2026-09-09.md)（脱敏导出清单：ENV 剔除 4 项、运行时注入文件不入 tar、敏感面扫描零命中、无任何模型权重）
  - 运行前提：GB10/SM121 GPU、NVIDIA driver（CUDA 13 兼容）、nvidia-container-runtime；模型权重/autotune 缓存经宿主 `-v` 挂载注入，不随镜像分发

---

## 目录结构

```
docs/
  01-research-reports/      研究报告（G1R7VL 历史系列 14 篇 + KV 内存分解/投机头调研/服务器取证 + K 槽位控制实现路径）
  02-performance-benchmarks/性能测试报告与基准数据（含参数组合门禁判定 gate-combo-verdict）
  03-final-metrics/          最终性能指标汇总（FINAL-METRICS-VL）
  05-kernels-patches/        算子/kernel/补丁相关报告（含 S1 设计草案 + w5_diag 复审）
  06-verification/           验证/QA/验收（六门验收 + 切换执行审计 + G4 双臂验收终判 + 接受率护栏 + G2 开臂预备）
  07-deployment/             部署/镜像脱敏/审计（服务器治理面审计 + 部署方案交叉审核）
patches/                    补丁包（028 系列 11 件 + sparse_attn_indexer_sm121.py + v5b-fix-batch + conf-gate-s1-20260910 置信门控 S1 补丁集）
scripts/                    启动/部署/基准/验收脚本（脱敏版）
  start_tp4_*_v043.sh 等    head/worker 启动 + 自愈链四件（monitor 双件 / healthcheck_hardened / healthcheck-rebuild / watchdog_hardened）、w6_env.txt、Dockerfile.LuZ-0.4.5-VL、daily_smoke.py
  bench3/ benchmark/        基准套件（全量 47 件 / 现役 9 件）
  proxy8001/ proxy8003/     8001 并发代理 / 8003 responses 网关（main.py 409 行）
  systemd/                  systemd 单元（7 unit + proxy drop-in）
  window-restart-guard/     维护窗口重启防护脚本（w9r4，09-07 D2 fail-fast 修订版）
  vl-acceptance/            六门验收探针脚本（15 件）
data/                       基准原始数据（49 格矩阵 + ext JSON、GSM8K 逐题 jsonl ×3 + summary ×3）
```

## 快速导航

- **📊 完整测试报告**：`docs/03-final-metrics/FINAL-METRICS-VL-2026-09-09.md`（49 格矩阵 + PR400K C2 + GSM8K 全量 + 投机/视觉 + KV 口径更正声明，冷数据口径）
- **warm 基准（生产态）**：`docs/02-performance-benchmarks/vl-full-benchmark-2026-09-08.md`（PR4K/DE/GSM8K 截断归因/dspark 接受率证据）
- **KV 内存分解**：`docs/01-research-reports/vl-kv-memory-decomposition-2026-09-09.md`（"-54%" 表观缩水三段归因 → 真实 -1.9%~+0.9% 持平）
- **投机头调研**：`docs/01-research-reports/spec-head-research-2026-09-09.md`（draft 头生态调研 + 三大工程根因排查 + k 截短门槛）
- **服务器取证**：`docs/01-research-reports/vl-server-side-forensics-2026-09-09.md`（§5.6 清单 grep 类只读执行回执）
- **上线六门验收**：`docs/06-verification/vl-acceptance-sixgates-2026-09-08.md`（5 PASS / 1 FAIL 如实记录）
- **网关 + 识图测试方案**：`docs/06-verification/vl-gateway-vision-test-plan-2026-09-08.md`（8001 长 prompt 门设计 + 8003 模型映射 + 视觉五门/边界脚本）
- **镜像脱敏分发**：`docs/07-deployment/vl-image-sanitization-manifest-2026-09-09.md`
- **部署方案交叉审核**：`docs/07-deployment/vl-deployment-cross-audit-2026-09-08.md`（切换前 Review：Request Changes 有条件放行，P0-1~P0-4 阻塞项定谳）
- **服务器治理面审计**：`docs/07-deployment/vl-governance-audit-2026-09-08.md`（持久化/自愈链/守卫链/缓存卷/回退推演，P0/P1 治理动作清单）
- **切换执行审计**：`docs/06-verification/vl-switch-execution-audit-2026-09-08.md`（窗口事后八项复核全 PASS，与上述两篇构成「审核 → 执行 → 回执」闭环）
- **G4 双臂验收终判**：`docs/06-verification/G4-dualarm-verdict-20260910.md`（S1 gate-off 性能等价 PASS：|Δ|=0.434 ≤ F=4.88；含 mean/median 背离与 token 比对负结果的诚实标注）
- **参数组合门禁判定**：`docs/02-performance-benchmarks/gate-combo-verdict-20260910.md`（唯一通过组合 = batch4096 × k6 × thr0，其余 11 组合逐一定谳）
- **接受率护栏**：`docs/06-verification/accept-rate-cheat-detection-2026-09-10.md`（回顾性接纳五判别量 D1-D5 + 现场一行判定规则）
- **脱敏映射**：`REDACTION-MAP.md`（沿用 master 规则）

## 📄 License

本项目以 [Apache License 2.0](LICENSE) 发布。补丁源自内部 fork vLLM 0.26.1，使用前请自行确认上游许可链；模型权重（DeepSeek V4 Flash Vision-Exp）不在本仓库分发，其使用受对应模型许可约束。

## 说明

- 本仓库为工程保障团队在生产攻坚过程中沉淀的报告与资产归档（VL 视觉线分支），所有报告均为当时实验/生产实测记录，含 [实测]/[推断] 口径标注。
- 涉密信息（内网 IP、主机名、内部路径、凭证、镜像 digest）已脱敏为占位符；若发现遗漏请提交 issue。
- 详细脱敏规则见 `REDACTION-MAP.md`。
- 生产镜像与权重不随仓库分发（零密钥/零模型），按 `docs/07-deployment/` 指引构建/获取。
- FAIL 项（DE coding/json 6/6 格、验收门5 conc8）如实归档不掩盖：归因与调优候选见 `docs/02-performance-benchmarks/` 与 `docs/01-research-reports/`。
