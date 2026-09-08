#!/usr/bin/env python3
"""V5b 补丁脚本：A1 + A2 + A3 三补丁应用于 V5 原版文件。
用法：python3 apply_v5b_patches.py <orig_dir> <out_dir>
产出：model.py / rope.py / cache_utils.py 补丁版 + md5 报告。qwen3_dspark.py/dspark.py 走 baked5 已打版（另核）。
"""
import hashlib, os, sys

ORIG, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()


def patch_a1_model(src, dst):
    """A1: SKIP_MTP_COPY 条件反转。`!= '0'` → `== '0'`（1 处）。"""
    s = open(src, encoding="utf-8").read()
    old = "if os.environ.get('VLLM_DSPARK_SKIP_MTP_COPY', '1') != '0':"
    new = "if os.environ.get('VLLM_DSPARK_SKIP_MTP_COPY', '1') == '0':"
    assert s.count(old) == 1, f"A1 anchor count={s.count(old)} (expect 1)"
    open(dst, "w", encoding="utf-8").write(s.replace(old, new))
    # 门：正门存在 + 负门不存在
    t = open(dst, encoding="utf-8").read()
    assert new in t and old not in t
    return "A1 model.py: != '0' -> == '0'"


def patch_a2_rope(src, dst):
    """A2 (#54815): SWA 层（compress_ratio<=1）强制 plain rope 路径，不吃 YaRN 插值。
    在 rope_parameters 赋值后、rope_type 判定前插入 SWA 强制 default。"""
    s = open(src, encoding="utf-8").read()
    anchor = "    rope_parameters = config.rope_parameters\n"
    fix = (
        "    rope_parameters = config.rope_parameters\n"
        "    # V5b-A2 (upstream #54815): SWA layers (compress_ratio <= 1) must not receive\n"
        "    # YaRN frequency interpolation. 0731 config carries rope_scaling={yarn, f16}\n"
        "    # which leaked onto SWA layers. Fix: disable yarn scaling for SWA only --\n"
        "    # rotary class lineage (DeepseekV4ScalingRotaryEmbedding) and cos_sin_cache\n"
        "    # fp32 contract stay untouched; compress layers (>1) keep deepseek_yarn.\n"
        "    if compress_ratio <= 1:\n"
        "        rope_parameters = dict(rope_parameters)\n"
        "        rope_parameters[\"apply_yarn_scaling\"] = False\n"
    )
    assert s.count(anchor) == 1, f"A2 anchor count={s.count(anchor)}"
    open(dst, "w", encoding="utf-8").write(s.replace(anchor, fix))
    t = open(dst, encoding="utf-8").read()
    assert "compress_ratio <= 1" in t and 'rope_parameters["apply_yarn_scaling"] = False' in t
    return "A2 rope.py: SWA yarn-scaling disabled (class lineage preserved)"


def patch_a3_cache(src, dst):
    """A3 (#55636 防御性): 内核 _compute_global_topk_indices_and_lens_kernel L482
    block_numbers load 的 mask 只有 mask & is_valid，block_indices 无上界 —— local_idx
    异常时越过 block_table 列深即 OOB。修复 = mask 补列上界 block_indices < block_table_stride。"""
    s = open(src, encoding="utf-8").read()
    old = """        block_indices = local_idx // block_size
        block_numbers = tl.load(
            block_table_ptr + req_idx * block_table_stride + block_indices,
            mask=mask & is_valid,
        )"""
    new = """        block_indices = local_idx // block_size
        # V5b-A3 (#55636 defensive): clamp block_indices to block_table column depth
        # so a corrupted local_idx cannot read past the block table (OOB guard).
        block_indices = tl.where(
            block_indices < block_table_stride, block_indices, 0
        )
        block_numbers = tl.load(
            block_table_ptr + req_idx * block_table_stride + block_indices,
            mask=mask & is_valid & (local_idx >= 0),
        )"""
    assert s.count(old) == 1, f"A3 anchor count={s.count(old)}"
    open(dst, "w", encoding="utf-8").write(s.replace(old, new))
    t = open(dst, encoding="utf-8").read()
    assert "V5b-A3" in t and "block_indices < block_table_stride" in t
    return "A3 cache_utils.py: block_indices OOB clamp added (L482 mask)"


report = []
for name, fn in [("model.py", patch_a1_model), ("rope.py", patch_a2_rope), ("cache_utils.py", patch_a3_cache)]:
    src, dst = os.path.join(ORIG, name), os.path.join(OUT, name)
    report.append(fn(src, dst))
    print(f"{name}: orig={md5(src)} patched={md5(dst)}")

print("\n".join(report))
import py_compile
for name in ["model.py", "rope.py", "cache_utils.py"]:
    py_compile.compile(os.path.join(OUT, name), doraise=True)
print("py_compile x3 OK")
