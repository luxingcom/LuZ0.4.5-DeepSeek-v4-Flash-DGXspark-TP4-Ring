# 05 — Kernels & Patches（VL 线）

本目录索引 VL 检查点版本（k=6 dspark）相关的 kernel 路线与补丁资产。

## 状态：补丁包待整合

VL 线复用文本线（master）的全部生产补丁面（W4A4 full + CUDA Graph + 池补丁 + FlashInfer B12X + autotune 固化），引擎基座同为 vLLM 0.26.1.dev0+gd3d3b2cca（fork，FlashInfer 0.6.18 + B12X MXFP4）。VL 专属差异为模型权重（Vision-Exp checkpoint 自带 DSpark 头 + vision 模块，磁盘 +0.77 GiB，runtime 权重持平）与投机配置（k=7→6），详见 [`../01-research-reports/vl-kv-memory-decomposition-2026-09-09.md`](../01-research-reports/vl-kv-memory-decomposition-2026-09-09.md)。

| 项 | 状态 | 说明 |
|---|---|---|
| 补丁源码包（patches/） | ⏳ 待整合 | VL 生产镜像内补丁面与 master 同源；服务器素材（脚本/补丁/systemd 单元）将由素材包补入后发布于 `patches/` 与 `scripts/` |
| 投机解码路径审计 | ✅ 已收录 | draft 量化路径 / wrapper 透传 / thinking 口径三根因排查：`../01-research-reports/spec-head-research-2026-09-09.md` + `../01-research-reports/vl-server-side-forensics-2026-09-09.md` |
| Kernel 路线 | 同 master | 现役生产路径 = flashinfer B12X + W4A4（`VLLM_MOE_W4A4=2` + `VLLM_MOE_W4A4_CG=1`）+ `VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS=sparse_mla_sm120` |

## 数据源

- 接受率退化归因与 k 截短调优候选：`../01-research-reports/spec-head-research-2026-09-09.md`
- 服务器侧代码面取证（dspark/utils.py、mxfp4 backend 指纹、env 护栏）：`../01-research-reports/vl-server-side-forensics-2026-09-09.md`
- master 线补丁先例：master 分支 `docs/05-kernels-patches/` 与 `patches/`
