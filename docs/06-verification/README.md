# 06 — Verification

本目录记录 LuZ0.4.5 检查点版本的功能验证与质量门禁结果。

## 验证总表

| 验证项 | 方法 | 结果 | 来源 |
|---|---|---|---|
| 工具编码修复 | `repro_tool_encoding.py` 5 组输入 | 全部 [OK]（修复前 4/5 崩溃） | `../patches/tool-call-encoding-fix-2026-09-02/` |
| autotune 内置 | 镜像内 md5 + 行为验证（固定路径命中） | md5=`702f8f56`，固定路径无 hash 子目录 | `../patches/autotune-cache-fix-2026-09-02/` |
| 生产参数完整性 | 四机 start 脚本 / w6_env / systemd 核对 | TILE_CAP=0、cB(bat=4096)、2400MHz 全部匹配 | `../scripts/` |
| 镜像脱敏 | 敏感模式扫描 + Config 检查 | 文本零残留（用户名/密码/内网 IP） | 交付说明（镜像分发） |
| 自愈链 | healthcheck 探针试跑 | healthy（宽限 skip） | `../docs/04-issues/timeout-guard-cudagraph-warmup-2026-09-02.md` |
| GSM8K 准确率 | 全量 GSM8K | **0.9363**（≥0.930 门） | `../docs/02-performance-benchmarks/g1r5-full-benchmark-2026-09-02.md` |

## 性能基准

| 场景 | C1（并发 1） | C2 | C4 | C8 |
|---|---|---|---|---|
| PR4K（G1r6 cB，2400MHz 制） | 2727 | ~2061 | 906 | ~541 |
| 扩展轮（PR131K 等） | 见基准报告 | — | — | — |

完整数据与口径：`../docs/02-performance-benchmarks/`（G1r6 定版后内置性能基准以最终 benchmark 报告为准）。

## 完整性 md5 清单（关键资产）

| 资产 | md5 |
|---|---|
| flashinfer_autotune_cache.py（修复版） | `702f8f561496948bb0ac3d075d12670e` |
| deepseek_v4_encoding.py（修复版） | `a1f46b6c0bf4f30d1f7cb50535557515` |
| healthcheck_hardened.sh | `94869b4d` |
| healthcheck-rebuild.sh | `650a91ca` |
| watchdog_hardened.sh | `ff50fed0` |
