# 07 — Deployment（VL 线）

本目录收录 VL 视觉线的部署资产：镜像脱敏分发与部署/运维手册。

## 已收录

| 文档 | 说明 |
|---|---|
| [vl-image-sanitization-manifest-2026-09-09.md](vl-image-sanitization-manifest-2026-09-09.md) | **脱敏镜像导出清单**：`LuZ0.4.5-VL-TP4-sanitized-20260909.tar.gz`（6.98 GiB，SHA256 `ae7db30f…aaee9`）的构造方法、剔除项逐条披露（AR2_* 拓扑 ENV 4 项）、敏感面两轮扫描记录、Config diff 表、运行前提。下载链接见仓库根 README「镜像下载」节 |

## 生产形态速览（VL）

- 镜像：`REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`（生产 tag；外发用上表 sanitized 产物，零权重零密钥）
- 服务链路：8003（responses 网关，模型别名映射 `SERVED_MODEL=deepseek-v4-flash-vision-exp`）→ 8001（concurrency-proxy-v2，Bearer 鉴权 + 并发准入）→ 8002（vLLM 引擎）
- 权重挂载：`<INSTALL_DIR>/models/dsv4-vision-exp → /models`（ro）；FlashInfer/tilelang 独立缓存卷 `-f1` 四机就绪
- 投机解码：DSpark MTP k=6；护栏 `VLLM_DSPARK_MARKOV_REPL=0` 四机在位

## 状态：runbook/脚本待整合

以下服务器素材将由素材包补入后发布（结构与 master 分支对齐）：

| 待整合项 | 目标位置 | 说明 |
|---|---|---|
| 启动/部署脚本（head/worker，脱敏版） | `scripts/` | `start_tp4_head_v043.sh` / `start_tp4_worker_v043.sh`（VL 变体：k=6、vision-exp、-f1 缓存卷） |
| 网关源码 | `scripts/`（或 `tools/`） | 8003 responses_gateway（模型别名映射）与 8001 concurrency-proxy-v2（rc3.7 长 prompt 门设计稿见 `../06-verification/vl-gateway-vision-test-plan-2026-09-08.md`） |
| 自愈/治理 systemd 单元 | `scripts/systemd/` | vllm-tp4-head/worker.service、vllm-healthcheck.timer、guard 链脚本 |
| runbook（窗口切换/回退/巡检） | 本目录 | VL 切换执行链（guard v3）与回退推演已由审计记录佐证（收录裁定见 BRANCH-NOTES） |
| 基准原始数据 JSON | `data/` | 49 格矩阵 CELL_RESULT / summary_v2.json 归档 |
