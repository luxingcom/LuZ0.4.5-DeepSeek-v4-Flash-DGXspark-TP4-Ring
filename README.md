# LuZ0.4.5 — DeepSeek V4 Flash · DSpark · DGX Spark TP4 · Ring

4× DGX Spark（GB10/sm_121a）TP4 环网部署 DeepSeek V4 Flash 的生产调优与算子工程开源归档。

**生产形态基线（LuZ0.4.5）**：W4A4 full（`VLLM_MOE_W4A4=2`）+ CUDA Graph（`VLLM_MOE_W4A4_CG=1`）+ 池补丁（`VLLM_B12X_SHARED_WRAPPER=1`）+ FlashInfer 0.6.18 + `--moe-backend flashinfer_b12x` + TILE_CAP=0 + autotune 手动固化 + util 0.80 + DSpark MTP n7。

**变更记录**：见 [`CHANGES-2026-09-02.md`](CHANGES-2026-09-02.md)（G1r5 全量重测 / G1r6 三窗口 / TILE_CAP=0 采纳 / W9R13 工具调用修复 / 超时守卫 / 热安全解除 / 定版）。

**最终性能指标**：见 `docs/03-final-metrics/`（完整 benchmark 后填充）。

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

- **定版报告**：`docs/07-deployment/g1r6-release-finalization-2026-09-02.md`（G1r6→LuZ0.4.5 定版 + 活性探针关闭）
- **G1r6 三窗口评估**：`docs/02-performance-benchmarks/g1r6-experiment-benchmark-2026-09-02.md`（TILE_CAP=0 采纳 / B1 降级 / autotune 固化）
- **G1r5 全量重测**：`docs/02-performance-benchmarks/g1r5-full-benchmark-2026-09-02.md`
- **工具调用 bug 根因**：`docs/04-issues/bug-tool-call-encoding-2026-09-02.md`（W9R13，多用户 agent 触发）
- **超时守卫 + CUDA 图预热**：`docs/04-issues/timeout-guard-cudagraph-warmup-2026-09-02.md`
- **检查点准备（autotune 内置）**：`docs/07-deployment/checkpoint-luz045-autotune-baked-2026-09-02.md`（W9R14）
- **镜像脱敏分发**：`docs/07-deployment/image-redaction-delivery-2026-09-02.md`
- **脱敏映射**：`REDACTION-MAP.md`

## 说明

- 本仓库为工程保障团队在生产攻坚过程中沉淀的报告与资产归档，所有报告均为当时实验/生产实测记录，含 [实测]/[推断] 口径标注。
- 涉密信息（内网 IP、主机名、内部路径、凭证、镜像 digest）已脱敏为占位符；若发现遗漏请提交 issue。
- 详细脱敏规则见 `REDACTION-MAP.md`。
- 生产镜像与权重不随仓库分发（零密钥/零模型），按 `docs/07-deployment/` 指引构建/获取。
