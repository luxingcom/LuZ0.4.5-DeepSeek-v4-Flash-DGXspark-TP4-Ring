# LuZ0.4.5 — DeepSeek V4 Flash · DSpark · DGX Spark TP4 · Ring

4× DGX Spark（GB10/sm_121a）TP4 环网部署 DeepSeek V4 Flash 的生产调优与算子工程开源归档。

**生产形态基线（LuZ0.4.5）**：W4A4 full（`VLLM_MOE_W4A4=2`）+ CUDA Graph（`VLLM_MOE_W4A4_CG=1`）+ 池补丁（`VLLM_B12X_SHARED_WRAPPER=1`）+ FlashInfer 0.6.18 + `--moe-backend flashinfer_b12x` + TILE_CAP=0 + autotune 手动固化 + util 0.80 + DSpark MTP n7。

**变更记录**：见 [`CHANGES-2026-09-02.md`](CHANGES-2026-09-02.md)（G1r5 全量重测 / G1r6 三窗口 / TILE_CAP=0 采纳 / W9R13 工具调用修复 / 超时守卫 / 热安全解除 / 定版）。

**最终性能指标**：见下方「典型性能指标」与 **[FINAL-METRICS 完整测试报告](docs/03-final-metrics/FINAL-METRICS-2026-09-02.md)**。

---

## 📊 典型性能指标（冷数据口径 · 前缀缓存关闭 · 3 波中位）

> 完整 48 格矩阵（DE 18 + PR 30）、原始数据与口径说明见 **[FINAL-METRICS 完整测试报告](docs/03-final-metrics/FINAL-METRICS-2026-09-02.md)**。

| 指标 | 结果 | 备注 |
|---|---|---|
| DE C1 prefill | **1841–1862 tps** | coding/json/prose 三型近一致 |
| DE C1 decode | ~102 / ~106 / ~49 t/s | coding / json / prose |
| PR prefill 峰值 | **PR2048 C1 ≈ 2748 tps** | 规模化拐点前峰值 |
| PR TTFT 线性 | 512→131K：**0.25s→48.8s**（C1） | ~190× 前缀 / ~195× TTFT，无异常拐点 |
| PR131K 全并发 6 格 | C1=2362 → C12=361（C12 TTFT 324.7s） | uuid 冷算 |
| PR400K C2（更大压力） | prefill **921.5 tps** / TTFT **381.9s** | 2200MHz 制，3 波中位 |
| GSM8K 全量（1319 题） | **content 0.9363 / marker 0.9371** | 双项 ≥0.930 门 **PASS** |

### PR/DE 聚合口径（总吞吐）

> 口径：**总PR = 同并发下 5 档前缀（512/2048/8192/32768/131072）prefill 吞吐求和**；**总DE = 同并发下三 task（coding/json/prose）decode 吞吐求和**。全精度中位求和，表内单格已四舍五入（手工相加可能有 ±1 / ±0.1 差异）。完整推导见 [FINAL-METRICS §6](docs/03-final-metrics/FINAL-METRICS-2026-09-02.md)。

#### PR 段总吞吐（纯 prefill，output-len 1）

| 并发 | PR512 | PR2048 | PR8192 | PR32768 | PR131072 | **总PR (prefill tps)** |
|---|---|---|---|---|---|---|
| C1 | 1812 | 2748 | 2721 | 2650 | 2362 | **12293** |
| C2 | 1332 | 2096 | 1654 | 1484 | 1276 | 7841 |
| C4 | 607 | 935 | 937 | 1029 | 920 | 4427 |
| C6 | 410 | 745 | 681 | 719 | 615 | 3170 |
| C8 | 350 | 562 | 568 | 593 | 509 | 2583 |
| C12 | 295 | 398 | 418 | 417 | 361 | 1889 |

#### DE 段总吞吐（文本生成混合负载，input 512 / output 4096）

| 并发 | coding | json | prose | **总DE (decode t/s)** |
|---|---|---|---|---|
| C1 | 102.1 | 106.5 | 48.8 | **257.3** |
| C2 | 76.1 | 79.5 | 37.6 | 193.3 |
| C4 | 50.3 | 54.6 | 26.2 | 131.0 |
| C6 | 44.0 | 46.3 | 22.0 | 112.3 |
| C8 | 38.4 | 41.2 | 19.5 | 99.1 |
| C12 | 32.5 | 34.7 | 16.8 | 83.9 |

**总吞吐**：C1 下总PR **12293 tps**（5 档前缀 prefill 求和）+ 总DE **257.3 t/s**（三 task decode 求和）；C1→C12 总PR 12293→1889（-85%）、总DE 257.3→83.9（-67%）。总PR 与总DE 为不同负载形态下的系统总吞吐，共享 GPU 算力/带宽（B12X MoE），**不可叠加**。

*口径注：完整矩阵（DE/PR）为 2400MHz 制；PR400K C2 与 GSM8K 为 2200MHz 制（2026-09-02 深夜散热降频修复后，详见 FINAL-METRICS §0）。*

**结构化数据**：`data/final-metrics-matrix-045.json`（48 格全量）+ `data/final-metrics-ext-045.json`（PR400K C2 扩展档）

**测试复现**：完整基准参数与脚本见 [`scripts/benchmark/`](scripts/benchmark/)（`run_bench_full_matrix.sh` 完整矩阵 48 格 / `run_pr400k_c2.sh` PR400K 扩展 / `gsm8k_full_g1r5.sh` GSM8K 全量 / `bench_v2.py` + `w9r2_gsm8k_spot.py` 基准工具，脱敏版）。

---

## 📥 镜像下载

- **脱敏检查点镜像**：`luz045-checkpoint-redacted-2026-09-02.tar.gz`（零权重/零密钥）
  - 百度网盘：<https://pan.baidu.com/s/1PsljdGBfOwCv2c0vcf0mWw?pwd=luzi>（提取码：`luzi`）
  - 部署/校验指引：见 [`docs/07-deployment/image-redaction-delivery-2026-09-02.md`](docs/07-deployment/image-redaction-delivery-2026-09-02.md)

---

## 目录结构

```
docs/
  01-research-reports/      研究报告（架构/设计/根因/上游核对/路线裁决）
  02-performance-benchmarks/性能测试报告与基准数据
  03-final-metrics/          最终性能指标汇总（FINAL-METRICS + CSV）
  04-issues/                 缺陷/事故/根因调查
  05-kernels-patches/        算子/kernel/补丁相关报告
  06-verification/           验证/QA/恢复演练/验收
  07-deployment/             部署/runbook/运维手册/回滚锚点
  08-tools/                  工具链说明
kernels/                    算子源码交付
patches/                    补丁包
scripts/                    启动/部署/基准/巡检脚本（脱敏版）
data/                       基准原始数据（json/csv）
```

## 快速导航

- **📊 完整测试报告**：`docs/03-final-metrics/FINAL-METRICS-2026-09-02.md`（48 格矩阵 + PR400K C2 + GSM8K 全量，冷数据口径）
- **定版报告**：`docs/07-deployment/g1r6-release-finalization-2026-09-02.md`（G1r6→LuZ0.4.5 定版 + 活性探针关闭）
- **G1r6 三窗口评估**：`docs/02-performance-benchmarks/g1r6-experiment-benchmark-2026-09-02.md`（TILE_CAP=0 采纳 / B1 降级 / autotune 固化）
- **G1r5 全量重测**：`docs/02-performance-benchmarks/g1r5-full-benchmark-2026-09-02.md`
- **工具调用 bug 根因**：`docs/04-issues/bug-tool-call-encoding-2026-09-02.md`（W9R13，多用户 agent 触发）
- **超时守卫 + CUDA 图预热**：`docs/04-issues/timeout-guard-cudagraph-warmup-2026-09-02.md`
- **RoCE GID 隐患排查**：`docs/04-issues/roce-gid-index3-zero-fault-2026-09-03.md`（对端断电→NM 撤 IP→GID 全零→NCCL 建链失败，gid_preflight 固化）
- **检查点准备（autotune 内置）**：`docs/07-deployment/checkpoint-luz045-autotune-baked-2026-09-02.md`（W9R14）
- **镜像脱敏分发**：`docs/07-deployment/image-redaction-delivery-2026-09-02.md`
- **脱敏映射**：`REDACTION-MAP.md`

## 说明

- 本仓库为工程保障团队在生产攻坚过程中沉淀的报告与资产归档，所有报告均为当时实验/生产实测记录，含 [实测]/[推断] 口径标注。
- 涉密信息（内网 IP、主机名、内部路径、凭证、镜像 digest）已脱敏为占位符；若发现遗漏请提交 issue。
- 详细脱敏规则见 `REDACTION-MAP.md`。
- 生产镜像与权重不随仓库分发（零密钥/零模型），按 `docs/07-deployment/` 指引构建/获取。
