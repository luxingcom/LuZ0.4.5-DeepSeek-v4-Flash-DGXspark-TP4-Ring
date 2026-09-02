#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复现 DeepSeek V4 工具参数编码 bug（#21 族）: arguments 空值/非法 JSON 崩溃"""
import hashlib, sys

def fname():
    return "/usr/local/lib/python3.12/dist-packages/vllm/tokenizers/deepseek_v4_encoding.py"

def main():
    print("== 本镜像文件 md5 ==")
    try:
        with open(fname(), "rb") as fp:
            print("md5:", hashlib.md5(fp.read()).hexdigest())
    except Exception as e:
        print("read-fail:", e)

    from vllm.tokenizers.deepseek_v4_encoding import encode_arguments_to_dsml

    cases = [
        ("arguments='' (空字符串)", {"name": "tool_x", "arguments": ""}),
        ("arguments=None (JSON null)", {"name": "tool_x", "arguments": None}),
        ("arguments=非法JSON '{bad'", {"name": "tool_x", "arguments": "{bad"}),
        ("arguments=合法dict", {"name": "tool_x", "arguments": '{"q":"hello","n":3}'}),
        ("arguments=非str非dict(list)", {"name": "tool_x", "arguments": [1, 2, 3]}),
    ]
    for label, tc in cases:
        try:
            out = encode_arguments_to_dsml(tc)
            print(f"[OK]   {label} -> {out!r}")
        except Exception as e:
            print(f"[CRASH] {label} -> {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
