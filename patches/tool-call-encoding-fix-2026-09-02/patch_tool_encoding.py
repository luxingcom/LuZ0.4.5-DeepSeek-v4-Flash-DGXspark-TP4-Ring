#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W9R13 工具参数编码防御修复补丁（供镜像重建时在容器内执行）
=================================================================
目标: vllm/tokenizers/deepseek_v4_encoding.py 的 encode_arguments_to_dsml()
背景: 多用户 agent 工具调用发送 arguments="" / null / 非法 JSON 时, 旧实现
      直接抛 JSONDecodeError / AttributeError, 请求失败。
修法: 对齐官方 deepseek-ai/DeepSeek-V4-Flash-0731 encoding/encoding_dsv4.py
      (refs/pr/38) 的 try/except 兜底, 并保留 dict 直用分支(不改变合法行为)。
用法: 在镜像重建临时容器内执行: python3 /tmp/patch_tool_encoding.py
      或 宿主机: docker cp 进容器后执行。
退出码: 0=成功 1=失败(未匹配/重复)
"""
import sys, shutil

PATH = "/usr/local/lib/python3.12/dist-packages/vllm/tokenizers/deepseek_v4_encoding.py"
BACKUP = PATH + ".bak-w9r13-20260902"

OLD = """    p_dsml_template = '<{dsml_token}parameter name="{key}" string="{is_str}">{value}</{dsml_token}parameter>'
    P_dsml_strs = []

    if isinstance(tool_call["arguments"], str):
        arguments = json.loads(tool_call["arguments"])
    else:
        arguments = tool_call["arguments"]

    for k, v in arguments.items():
"""

NEW = """    p_dsml_template = '<{dsml_token}parameter name="{key}" string="{is_str}">{value}</{dsml_token}parameter>'
    P_dsml_strs = []

    # W9R13 (2026-09-02): 工具参数防御修复 — 对齐官方 encoding_dsv4.py (refs/pr/38)
    # 多用户 agent 工具调用会发 arguments="" / null / 非法 JSON / list, 旧版直接
    # JSONDecodeError / AttributeError 崩溃, 现统一兜底为 {"arguments": 原值} 不崩溃。
    try:
        if isinstance(tool_call["arguments"], str):
            arguments = json.loads(tool_call["arguments"])
        elif isinstance(tool_call["arguments"], dict):
            arguments = tool_call["arguments"]
        else:
            arguments = {"arguments": tool_call["arguments"]}
    except Exception:
        arguments = {"arguments": tool_call["arguments"]}

    for k, v in arguments.items():
"""


def main():
    try:
        with open(PATH, "r", encoding="utf-8") as fp:
            text = fp.read()
    except FileNotFoundError:
        print(f"[FAIL] 文件不存在: {PATH}"); sys.exit(1)

    if OLD not in text:
        print("[FAIL] 未找到待替换段 (文件可能已修复或路径不符)")
        print("[INFO] 检查文件中是否已含 'W9R13' 标记:")
        print("       ", "W9R13" in text)
        sys.exit(1)
    if text.count(OLD) != 1:
        print(f"[FAIL] 待替换段出现 {text.count(OLD)} 次, 期望 1 次"); sys.exit(1)

    shutil.copy2(PATH, BACKUP)
    print(f"[OK] 已备份: {BACKUP}")

    text = text.replace(OLD, NEW, 1)
    with open(PATH, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(text)

    # 语法校验
    import py_compile
    try:
        py_compile.compile(PATH, doraise=True)
        print("[OK] py_compile 语法校验通过")
    except py_compile.PyCompileError as e:
        print(f"[FAIL] 语法错误: {e}"); sys.exit(1)

    print("[DONE] W9R13 补丁应用成功")
    sys.exit(0)


if __name__ == "__main__":
    main()
