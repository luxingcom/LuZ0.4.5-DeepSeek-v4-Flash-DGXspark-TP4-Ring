# Patch: FlashInfer Autotune Cache — Fixed-Path Mode

**日期**：2026-09-02 · **镜像**：LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring（已内置本补丁）

## 问题

`resolve_flashinfer_autotune_file` 原版按 `root / sha256(aot_compile_hash_factors)` 写缓存。`aot_compile_hash_factors` 的哈希因子跨进程重启漂移，导致缓存目录哈希每次变化 → autotune cache 永 miss → 每次启动全量重新 benchmark（日志 `24 new, 0 from previous`），跨重启性能 ±2-4% 噪声。

## 修复

设置 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` 环境变量时，跳过 hash 子目录，固定写入 `<dir>/autotune_configs.json`：

```python
def resolve_flashinfer_autotune_file(runner):
    override_dir = envs.VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR
    if override_dir:
        # fixed-path mode: stable across restarts
        root = Path(override_dir).expanduser()
        output_dir = root
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / "autotune_configs.json"
    # else: original hash-subdir behavior (backward compatible)
```

未设置 env 时行为与原版完全一致（向后兼容）。

## 应用

**镜像已内置**（`vllm/model_executor/warmup/flashinfer_autotune_cache.py`，md5 `702f8f56`）。
若需手动覆盖：

```bash
cp flashinfer_autotune_cache.py \
  /usr/local/lib/python3.12/dist-packages/vllm/model_executor/warmup/flashinfer_autotune_cache.py
python3 -m py_compile /usr/local/lib/python3.12/dist-packages/vllm/model_executor/warmup/flashinfer_autotune_cache.py
```

运行时 env（start 脚本注入）：

```
VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/root/.cache/vllm/autotune-g1r6
```

## 验证

- 启动日志出现 `Loaded N configs`（N>0，跨重启命中）
- 行为验证：设 env 时 resolve 返回固定路径（无 hash 子目录）；未设时回退原版
- 文件 md5（修复版）：`702f8f561496948bb0ac3d075d12670e`
