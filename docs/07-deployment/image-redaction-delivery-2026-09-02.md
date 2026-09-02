# LuZ0.4.5 检查点镜像 — 脱敏分发版交付说明

**日期**：2026-09-02
**工作流**：镜像脱敏与分发（W9R14）

---

## 📌 TL;DR

- **交付物**：`luz045-checkpoint-redacted-2026-09-02.tar.gz`（docker save 脱敏版镜像）
- **镜像**：`LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-redacted`
  - 基座：`LuZ0.4.5-...-Ring-baked`（修复团队检查点 + autotune 内置）
  - 脱敏层：清理缓存/网络配置/tmp 残留
- **脱敏原则**：参照 LuZ0.3.1——零密钥、零内网 IP、零用户名；镜像可安全上传网盘分发。

---

## 1. 脱敏范围与证据

### 1.1 已清理项

| 项 | 处理 | 依据 |
|---|---|---|
| `/root/.cache/pip`（含 http-v2 缓存） | 删除 | pip 下载缓存，含 URL 元数据 |
| `/opt/uv/cache`（694MB） | 删除 | uv 构建缓存（nvidia 源码包等） |
| `/etc/resolv.conf` 内网 nameserver | 重置为通用 `search .` | 原含 `NODE_IP_REDACTED`（运行时 Docker 注入，重写为通用） |
| `/etc/hosts` | 重置为标准 localhost | 原含容器 IP |
| `/etc/hostname` | 清空 | 原为容器 ID |
| `/tmp` 全部残留 | 清空 | 验证脚本/编译临时/cutlass cache |
| `/root/.launchpadlib` | 删除 | Ubuntu 残留点文件 |

### 1.2 扫描验证（复扫证据）

- **敏感模式扫描**（`MGMT_SUBNET_REDACTED` / `<USER>` / `AS1217` / `dgxspark` / `10.100` / `10.20` / `172.17`）：**文本文件零残留**（dpkg md5sums/许可证中的版本号如 `libavfilter.so.7.110.100` 为误报，已人工核验非 IP）
- **镜像 Config 检查**：ENV/Labels 无敏感（`VLLM_IMAGE_TAG=local/vllm-openai:dev`、构建元数据均 local/unknown；`org.opencontainers.image.source` 为公开上游 github/anemll/dspark-vllm-gx10）；Volumes=null
- **/opt**：仅编译库（libncclpin.so / nccl-ringonly / wheels / uv），无脚本/配置含敏感

### 1.3 保留项（核心资产，脱敏不破坏功能）

| 项 | 状态 | 说明 |
|---|---|---|
| autotune 内置补丁 | md5 `702f8f56` | 固定路径 autotune 缓存（跳过 hash 漂移） |
| 工具编码修复 | md5 `a1f46b6c` | W9R13 encode_arguments_to_dsml 兜底 |
| `/etc/nccl.conf` | 保留 | 网卡名为 DGX Spark 标准硬件命名（非机密）；运行时由 w6_env env 覆盖 |
| `/root/.cache/flashinfer` | 保留 | 运行时 JIT 编译缓存（无凭据） |
| `/opt/wheels/flashinfer_cubin-0.6.14` | 保留 | flashinfer cubin wheel（构建资产） |
| vLLM 版本 | 0.26.1.dev0+d20260805 | 与检查点一致 |

---

## 2. 使用说明（网盘分发后）

### 2.1 加载镜像

```bash
docker load -i luz045-checkpoint-redacted-2026-09-02.tar.gz
docker images | grep LuZ0.4.5
```

### 2.2 配套文件（同一仓库 release/luz045-github/scripts/ 已脱敏）

| 文件 | 用途 |
|---|---|
| `start_tp4_head_v043.sh` / `start_tp4_worker_v043.sh` | 启动脚本（R5 指向 `-baked`/`-redacted`，已移除 autotune 挂载） |
| `w6_env.txt` | 运行时 env 注入（含 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` 触发补丁） |
| `monitor_tp4_head_v043.sh` | head 监控 + CUDA 图预热 |
| `healthcheck_hardened.sh` / `healthcheck-rebuild.sh` | 自愈探针 |
| `watchdog_hardened.sh` | watchdog |

### 2.3 注意事项

- **模型权重不包含在镜像内**（`/models` 为运行时挂载），需单独分发 `deepseek-v4-flash-0731` checkpoint
- 镜像不含内网 IP/用户名/密码/密钥，可直接对外分发
- 首次启动会在 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` 指定路径生成 autotune 缓存（`Loaded N configs`）

---

## 3. 文件校验信息

| 项 | 值 |
|---|---|
| 镜像 tag | `LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-redacted` |
| 镜像 ID | <BAKE_IMAGE_DIGEST> |
| 导出文件 | `luz045-checkpoint-redacted-2026-09-02.tar.gz` |
| 文件大小 | 13,185,916,181 字节（12.3 GiB，gzip -1 压缩，源 22.6GB） |
| 文件 md5 | `bc8756e1d04b6d862ca775cdc94b7726`（<MGMT_OCTET> 与本地一致，传输校验通过） |
| 本地路径 | `release/images/luz045-checkpoint-redacted-2026-09-02.tar.gz` |

---

> 本说明由工程保障团队 AI 生成，供网盘分发与外部使用参考。
