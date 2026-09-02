# tools/ — 发布辅助工具

## redact.py — 脱敏工具

对工作树中的文本文件执行敏感信息脱敏替换（占位符语义见仓库根目录 `REDACTION-MAP.md`）。

### 用法

```bash
python3 redact.py apply <target_dir>   # 递归脱敏文本文件
python3 redact.py check <target_dir>   # 复扫残留（应为 0）
```

### 说明

- **模式文件私有**：真实敏感值映射存于本地 `redact-patterns.json`（**gitignored，不随仓库分发**）。外部使用者按 `REDACTION-MAP.md` 的占位符语义自建映射。
- 支持扩展名：`.md/.sh/.py/.txt/.json/.yaml/.yml/.env/.conf/.service/.c/.h/.cfg/.toml/.ini` + `.patch/Dockerfile/Makefile`。
- 脚本类文件（`.sh/.py`）使用无尖括号占位符（如 `_PH_USER_`）保证语法不被尖括号破坏。
- 二进制/编译产物（`.so/.pyc`）自动跳过。

### 依赖

仅 Python 3 标准库（`re`/`json`/`pathlib`）。
