# 08 — Tools

本目录索引发布辅助工具。

| 工具 | 路径 | 用途 |
|---|---|---|
| redact.py | `../tools/redact.py` | 脱敏工具（apply / check），占位符语义见仓库根 `REDACTION-MAP.md` |
| benchmark 套件 | `../tools/`（后续补充） | 官方 benchmark_package 流程脚本（最终基准完成后归档） |

## 说明

- 脱敏模式文件（`redact-patterns.json`）为私有 gitignored，不入库；外部使用者按 `REDACTION-MAP.md` 自建。
- benchmark 工具脚本将在最终性能基准完成后归档至此（与 `../docs/03-final-metrics/` 同步）。
