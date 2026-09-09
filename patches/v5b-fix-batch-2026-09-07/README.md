# V5b 修复批次（2026-09-07）

生产镜像 `LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-V5b`（registry digest `sha256:<BAKE_IMAGE_DIGEST>`）对应的修复批次发布：三个 bug 修复（A1/A2/A3）+ 两个环境门控特性（B1/B2）+ 窗口重启守卫脚本 + 工程审查文档。

## 内容索引

| 路径 | 内容 |
|------|------|
| `patches/apply_v5b_patches.py` | A1/A2/A3 补丁生成器（锚点校验 + 断言门，幂等可重跑） |
| `patches/apply_v5b_b_patches.py` | B1/B2 补丁生成器（env 门控，默认关闭） |
| `scripts/w9r4_window_restart.sh` | 窗口重启守卫 v3（flock 互斥 + D2 TCPStore fail-fast + 固定 systemd 单元名） |
| `docs/engineering/2026-09-07-v5b/` | 本批次完整工程审查文档（代码审计 / QA 验证 / 运维复盘 / 综合评审） |

## 修复项

- **A1（bug fix）**：`SKIP_MTP_COPY` 环境变量条件反转修复（`!= '0'` → `== '0'`）。历史缺陷：默认值下 MTP hidden buffer 的每步 `copy_` 死拷贝从未被跳过。修复后默认跳过死拷贝，`SKIP_MTP_COPY=0` 可恢复拷贝行为。
- **A2（bug fix）**：SWA 层 YaRN 缩放泄漏修复。compress 层只设置 `apply_yarn_scaling=False`（不触碰 `rope_type`，避免 rotary 类血统切换导致的 fused rope dtype 断言崩溃）。行为验证：长上下文 needle 30K/128K/500K 全通过（含 600K 上限 83% 的 501K 载荷）。
- **A3（robustness）**：`block_indices` 越界 clamp（`cache_utils.py`），污染 lane 从 OOB 读变为本请求 block0 的合法引用；正常路径位级不变。
- **B1（gated feature，默认关闭）**：Markov replicate 词表复制。**⚠️ 已知缺陷：forward 侧未适配（VocabParallelEmbedding 按 `id - vocab_start` 查本地行），启用会导致 rank1-3 静默数值错乱。生产环境必须保持 `VLLM_DSPARK_MARKOV_REPL` 关闭**，直至 forward 适配重写。详见审计文档。
- **B2（gated feature，默认关闭）**：draft router top-k override hook。**注：当前版本 hook 仅定义未接线（死代码），`VLLM_DSPARK_DRAFT_TOPK` 环境变量不生效**；待后续版本补接线或移除。另注意实现用 `isdigit()` 判定，`"0"` 会通过并置 `top_k=0`（已知 footgun，接线时需加 `k>=1` 下界）。

## 验证记录摘要

- GSM8K10：10/10 通过
- A2 长上下文 needle：4/4 位置精确复述（30K / 128K-end / 500K / 128K-start 复测）
- A1 输出完整性：max_tokens=256 采样 5/5 全额（finish=length，token 账目差恒 1）
- 流式回归 SSE：3/3（无空帧/无中断，finish_reason 正常）
- 详见 `docs/engineering/2026-09-07-v5b/` 四份文档

## 脱敏声明

本文档集由内部工程记录脱敏生成：SSH 凭据、API key、内网地址、主机名、操作者账号均已替换为占位符（`<REDACTED-*>`、`node0X`、`<operator>`、`<lan-subnet>`）。
