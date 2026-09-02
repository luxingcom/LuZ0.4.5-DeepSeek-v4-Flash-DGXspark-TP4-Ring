# Patch: DeepSeek V4 Tool-Call Argument Encoding Fix

**日期**：2026-09-02 · **镜像**：LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring（已内置本补丁）

## 问题

`vllm/tokenizers/deepseek_v4_encoding.py` 的 `encode_arguments_to_dsml()` 对 tool_call 的 `arguments` 字段无防御处理：

| 输入 | 原版行为 |
|---|---|
| `arguments=""` | `json.loads("")` → **JSONDecodeError** |
| `arguments=None` | `None.items()` → **AttributeError** |
| 非法 JSON 字符串 | **JSONDecodeError** |
| 非 dict（如 list） | **AttributeError** |

多用户 agent 工具调用（Claude Code / opencode 等框架会发送空参数/`null`）时，chat template 渲染 assistant tool_calls **直接抛异常 → 请求失败**。

## 修复（官方 refs/pr/38 语义 + 增强）

```python
args = kwargs.get("arguments")
if args is None:
    args = "{}"
elif isinstance(args, str):
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        parsed = {"arguments": args}
    args = parsed
if isinstance(args, dict):
    ...  # normal path
else:
    args = {"arguments": str(args)}
```

要点：解析失败 → 兜底 `{"arguments": 原值}`，**永不崩溃**。

## 应用

**镜像已内置**（`vllm/tokenizers/deepseek_v4_encoding.py`，md5 `a1f46b6c`）。

若需手动打补丁，在容器内执行：

```bash
python3 patch_tool_encoding.py
# 校验（5 组输入应全部 [OK]）
python3 repro_tool_encoding.py
```

## 验证

- `repro_tool_encoding.py`：5 组输入（合法 dict / `""` / `null` / 非法 JSON / list）修复前 4/5 崩溃 → 修复后全部 [OK]
- 文件 md5（修复版）：`a1f46b6c0bf4f30d1f7cb50535557515`

## 相关

- 根因分析：`docs/04-issues/bug-tool-call-encoding-2026-09-02.md`
- 官方修复参照：deepseek-ai/DeepSeek-V4-Flash-0731 `encoding_dsv4.py` refs/pr/38；上游 vLLM #36654
