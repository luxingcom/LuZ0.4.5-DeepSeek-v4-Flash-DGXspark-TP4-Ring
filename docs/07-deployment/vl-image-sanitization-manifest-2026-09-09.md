# VL 生产镜像脱敏导出清单（SANITIZATION MANIFEST）

日期：2026-09-09（产物生成 UTC 05:39 / GMT+8 13:39；本清单 UTC 05:4x）
执行：sre-engineer-2 (Rex)；性质：只读取证 + 临时容器脱敏构造，**零触碰生产容器**（未 stop/rm/restart 任何生产服务，docker ps 全程 healthy）

## 1. 镜像谱系（源 → 产物）

- 源镜像：`REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`（即生产容器 vllm-tp4-rank0 所用）
- 四机一致性：RepoDigest **完全一致** = `sha256:<BAKE_IMAGE_DIGEST>`（node01/02/03/04 实测；ID/大小显示差异为 01 的 containerd image store 与 02-04 传统 store 的口径差异，不影响内容一致性判据）
- 源镜像体量：inspect Size 12.88GB（解压内容）；RootFS 117 层；build 历史 197 层
- 构造方法：`docker export`（tmp-san-vl 临时容器，**无 --gpus**，纯文件系统操作）→ `docker import --change`（ENV 白名单 + ENTRYPOINT/CMD/WORKDIR 原样保留）→ **单层扁平镜像** `vl-sanitized:20260909`
- 构造过程披露：共 3 次 import——第 1 次发现遗漏 `NVIDIA_REQUIRE_CUDA`；第 2 次补入时含空格值被 Dockerfile ENV 语法拆分为垃圾变量 `brand=nvidia,driver>=535`（发现即修）；**第 3 次为最终版**（EnvCount=25，无垃圾项）

## 2. 剔除项（逐条）

### 2.1 ENV 剔除（4 项，内网拓扑泄漏面）
| 原镜像 ENV 项 | 值 | 剔除理由 |
|---|---|---|
| AR2_PEERS | node01,node02,node04,node03 | 内网节点 IP 拓扑 |
| AR2_DEV0 | rocep1s0f1 | 内网网卡拓扑 |
| AR2_DEV1 | roceP2p1s0f0 | 内网网卡拓扑 |
| AR2_CTRL_PORT | 9520 | 内网端口拓扑 |

**可运行性影响评估（诚实更正）**：经 grep 实证，`start_head_E.sh` **不含任何 AR2_* 注入**（`grep -n 'AR2_'` 零命中）——即上述 4 项是**镜像 config 内嵌**而非脚本注入。剔除后：
- **外发场景（本任务目的）**：无损失。AR2_PEERS 是源内网固定拓扑，外部方环境本就不存在 内网网段，需自行配置集群拓扑（原值对外部方本就无效）。
- **若在源内网用 sanitized 镜像重启生产**：需宿主启动命令补注 `-e AR2_PEERS=... -e AR2_DEV0=... -e AR2_DEV1=... -e AR2_CTRL_PORT=...`（一次性 env 补注，非代码改动）。
- **本地生产不受影响**：生产容器继续使用原镜像运行，sanitized 镜像仅用于外发。

### 2.2 ENV 值调整（1 项，披露）
| 项 | 原值 | 产物值 | 说明 |
|---|---|---|---|
| NVIDIA_REQUIRE_CUDA | NVIDIA 兼容矩阵长声明（brand=unknown/grid/tesla/...，driver>=535,<536 系列） | `cuda>=13.0` | 短版等价；该变量仅为 nvidia-container-runtime 版本声明，vLLM 运行不依赖；完整矩阵非敏感但无外发意义 |

### 2.3 运行时注入文件（不入 tar 的决定性证据）
`docker save` 产物内 **etc/resolv.conf、etc/hosts、etc/hostname 三文件 ABSENT**（`tar -xzOf` 实测三次均 ABSENT）——宿主 DNS/hosts 拓扑零泄漏。export/import 流程中 bind mount（docker 运行时注入的三个文件）天然不入镜像层。

### 2.4 层历史
源镜像 197 层 build 历史（buildkit 门禁脚本 + COPY 记录）随扁平化**全部丢弃**。历史本身无秘密注入（`docker history` 全量 grep：36 命中均为门禁断言字符串/基础镜像 ENV/tokenizers 文件名子串，无 AS1217/LuZvLLm/密码/私钥），扁平化使历史面归零。

## 3. 敏感面扫描记录

### 3.1 第一轮（源镜像 tmp 容器，全盘 `grep -rIl`）
- 精确敏感串 `<PASSWORD>|<BEARER>|<API_KEY>`：**零命中**（全文件系统）
- 拓扑串 `<NODE_IP>|<USER>|REGISTRY_HOST:5000`：仅命中 /etc/resolv.conf 与 /run/systemd/resolve/stub-resolv.conf（均为 docker 运行时注入视图，非镜像层；§2.3 已证实 tar 内 ABSENT）
- 高误报串（重点目录）：命中均为良性——/etc/pam.d/* 与 /etc/login.defs 的 passwd 策略、/etc/ssl/openssl.cnf 配置键、vllm-nonroot-entrypoint.sh 的 /etc/passwd 处理注释（vLLM 官方脚本）、asio ssl C++ 头文件名（password_callback.hpp）、launchpadlib 公开 API WADL schema 缓存（HTTP 200 头 + XML，无凭据）
- 凭据文件：/root/.bash_history、pip.conf、.git-credentials、.ssh、.netrc 全部**不存在**；/root 仅 .bashrc/.cache/.launchpadlib/.profile；/home/vllm 仅标准 skeleton

### 3.2 复扫（sanitized 镜像容器，`--network none`）
- 精确敏感串：**零命中**
- 凭据文件：不存在（`NONE-EXISTS`）
- ENV 检查：容器 env 无内网网段/<USER>/AR2 拓扑项（仅保留的 AR2_CROSSOVER_B/AR2_V5_HISTOGRAM 算法参数）

### 3.3 大文件（权重夹带检查，停机条件④）
`find / -xdev -type f -size +1G`：**零命中**——镜像内无任何模型权重（safetensors/bin/ckpt 均不存在）。外发不涉及模型分发 IP 问题。权重经宿主 -v 挂载注入（<INSTALL_DIR>/models/dsv4-vision-exp → /models），不随镜像分发。

## 4. 产物信息

- 路径：`<HOME_DIR>/vl-sanitized-export/LuZ0.4.5-VL-TP4-sanitized-20260909.tar.gz`
- 产物 IMAGE ID：`2a1b41dbaa0eb0d11063ca9259b08734802a892b7b667ff2cbf0a95ee904c8b5`（单层扁平）
- 文件大小：**7,499,634,958 bytes ≈ 6.98 GiB**
- MD5：`b5934e6ec09187e06204b9e2efef0565`
- SHA256：`ae7db30f5d9173399e5ca6fcd7f1bf17d74c8f1225224c3d7fc33106979aaee9`
- 伴随文件：同目录 `.md5` / `.sha256`
- 加载方式：`docker load < LuZ0.4.5-VL-TP4-sanitized-20260909.tar.gz` → tag `vl-sanitized:20260909`
- 运行前提（外发方须知）：GB10/SM121 GPU（TorchMan SM121a arch）、NVIDIA driver（CUDA 13 兼容）、nvidia-container-runtime；模型权重/autotune 缓存/nvcc wrapper 补丁经宿主 -v 挂载注入（不随镜像分发）；集群拓扑 env（AR2_* 4 项）与 NCCL 调优 env 由启动方配置（见 §2.1）

## 5. Config diff 表（原 29 项 ENV → 产物 25 项）

**保留 25 项**：PATH / NVARCH / NVIDIA_REQUIRE_CUDA(短版) / NV_CUDA_CUDART_VERSION / CUDA_VERSION / LD_LIBRARY_PATH / NVIDIA_VISIBLE_DEVICES / NVIDIA_DRIVER_CAPABILITIES / DEBIAN_FRONTEND / UV_HTTP_TIMEOUT / UV_INDEX_STRATEGY / UV_LINK_MODE / UV_PYTHON_INSTALL_DIR / UV_CACHE_DIR / VLLM_ENABLE_CUDA_COMPATIBILITY / TORCH_CUDA_ARCH_LIST / VLLM_USAGE_SOURCE / VLLM_BUILD_COMMIT / VLLM_BUILD_PIPELINE / VLLM_BUILD_URL(空) / VLLM_IMAGE_TAG / FLASHINFER_DISABLE_VERSION_CHECK / FLASHINFER_CUDA_ARCH_LIST / AR2_CROSSOVER_B / AR2_V5_HISTOGRAM

**剔除 4 项**：AR2_PEERS / AR2_DEV0 / AR2_DEV1 / AR2_CTRL_PORT（§2.1）

ENTRYPOINT `["/bin/bash"]`、CMD `["-c","sleep 300"]`、WORKDIR `/vllm-workspace`、User=root：与原镜像一致。RootFS 117 层 → 1 层。

## 6. 磁盘与落盘点决策（停机条件①）

四机 df 实测：node01 `/` 可用 2.2T、node02 1.5T、node03 341G、node04 340G。需求 = 镜像实测 12.88GB×3 ≈ 39GB（按 containerd 口径上限 35.9GB×3=108GB 亦远满足）。**落盘点选 node01（督导 SSH 主入口）**。

## 7. 临时资源清理记录

- 临时容器 `tmp-san-vl`、`tmp-rescan`：用毕删除（sleep infinity 临时容器，均无 --gpus）
- 本地 sanitized 标签 `vl-sanitized:20260909`：tar 产物校验后删除（见执行记录）
- 生产容器/服务：零触碰（vllm-tp4-rank0 全程 Up healthy；GSM8K 冒烟等验收流量未受任何影响）

## 8. 取证档案

执行记录本地归档：`C:/Users/novAI/WorkBuddy/kv34~kv42.txt`（阶段 A/B 全部命令与输出，UTC 时间戳）
