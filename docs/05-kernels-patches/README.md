# 05 — Kernels & Patches

本目录索引 LuZ0.4.5 检查点版本相关的 kernel 路线与补丁资产。

## 补丁（patches/）

| 补丁 | 目录 | 状态 | 说明 |
|---|---|---|---|
| FlashInfer Autotune Cache 固定路径 | `../patches/autotune-cache-fix-2026-09-02/` | ✅ 已内置镜像 | 消除跨重启 autotune 缓存漂移（固定路径命中） |
| DeepSeek V4 工具参数编码 | `../patches/tool-call-encoding-fix-2026-09-02/` | ✅ 已内置镜像 | 空参数/非法 JSON 工具调用不再崩溃 |

## Kernel 路线摘要（生产判定）

| Kernel 路径 | 结论 | 依据 |
|---|---|---|
| routeA（per-expert / W4A4-fused） | No-Go（慢于 B12X-only） | `../docs/01-research-reports/w9r3-compute-path-audit-2026-08-29.md` |
| routeB（B12X MoE GEMM 替代） | No-Go（TP4 归档，368.1 TFLOPS SASS-Go） | `../docs/01-research-reports/w9-known-issues-crosscheck-2026-08-29.md` |
| 现役生产路径 | **flashinfer B12X + W4A4**（`VLLM_MOE_W4A4=2` + `VLLM_MOE_W4A4_CG=1`） | 生产配置见 `../scripts/w6_env.txt` |
| routeB FP8 kernel 改进 | 立项中（P0 NCU 微基准 → P1 SMEM/流水重构） | 后续版本 |

## 数据源

- 完整基准数据：`../docs/02-performance-benchmarks/`
- 已知问题交叉核对：`../docs/01-research-reports/w9-known-issues-crosscheck-2026-08-29.md`
