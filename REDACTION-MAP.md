# 脱敏映射表（REDACTION MAP）

本文件说明开源发布副本中应用的**占位符语义**（不包含任何真实敏感值，真实映射与批量替换工具保留在本地未提交）。

> 本表以 master 分支 REDACTION-MAP.md 为基底（既有占位符定义与规则原样沿用），追加 **VL 分支（视觉线）** 增补语义与政策，见下方标注「VL 分支」的小节。

## 占位符语义

| 占位符 | 语义 | 示例场景 |
|---|---|---|
| `<PASSWORD>` | 明文密码/提权口令 | 运维脚本中的 sudo 密码 |
| `<API_KEY>` | API key 值 | `--api-key`、`VLLM_API_KEY` |
| `<BEARER>` | Bearer token | 网关/监控鉴权 |
| `<USER>` | 内部用户名 | 集群操作账号 |
| `<INSTALL_DIR>` | 内部安装目录 | 应用部署根目录 |
| `<MODELS_DIR>` / `<HOME_DIR>` | 模型/用户主目录 | 用户 home 与模型目录 |
| `<NODE_IP>` | 内网 IP（端口保留） | 内网地址（形如私有网段） |
| `<RING_SUBNET>` | 环网 RoCE 子网对/段（`10.100.x/y`、`10.100.x~y`、`10.20.x` 及裸简写形式） | 环网数据面子网、iptables 白名单段 |
| `<MGMT_OCTET>` | 管理网 IP 末段（当前末段档 / 旧节点末段档 / `~` 范围形式） | 管理网地址末段、旧节点引用 |
| `<DOCKER_IP>` | Docker bridge 容器 IP（`172.18.x.x` 等桥接网段） | docker daemon 重启后容器 IP 漂移记录 |
| `REGISTRY_HOST` | 镜像仓库主机（内部 registry，端口保留） | `REGISTRY_HOST:5000/vllm/…` 镜像引用 |
| `<BASE_IMAGE_DIGEST>` / `<BAKE_IMAGE_DIGEST>` | 镜像内容哈希（digest）占位符 | 基座 / 定版镜像 digest，现场 `docker inspect` resolve |
| `node0X` | 主机名 | 四节点主机名（统一匿名） |

### 脚本类占位符对照表（`_PH_*_` 无尖括号变体）

shell/Python 脚本中为避免与代码语法冲突（如 bash 数组字面量不支持尖括号），部分占位符使用下划线变体，语义与上表一一对应：

| 脚本占位符 | 对应语义 | 使用场景 |
|---|---|---|
| `_PH_USER_` | `<USER>` 内部用户名 | ssh 目标、home 路径 |
| `_PH_PASSWORD_` | `<PASSWORD>` 提权口令 | sudo 纪律注释 |
| `_PH_NODE_IP_` | `<NODE_IP>` 内网 IP | 端点地址 |
| `_PH_HEAD_IP_` | `<NODE_IP>` 管理网前三段 | 四机节点数组（`_PH_HEAD_IP_.186` 等，末段序号 186-189 为节点编号语义，非敏感） |
| `_PH_INSTALL_DIR_` / `_PH_INSTALL_` | `<INSTALL_DIR>` 内部安装目录 | 脚本路径、状态文件 |
| `_PH_USER_KIT_` | `<HOME_DIR>` 下工具目录 | monitor/preflight 脚本路径 |
| `_PH_BAKE_IMAGE_DIGEST_` | `<BAKE_IMAGE_DIGEST>` 定版镜像 digest | 基准脚本 IMAGE 标注、部署文档 |
| `_PH_KEY_` | `<API_KEY>` API key | 脚本环境变量 |

**VL 分支实际使用的脚本变体（发布树实测）**：`_PH_USER_`、`_PH_INSTALL_`（统一短形态，未用 `_PH_INSTALL_DIR_`）、`_PH_HEAD_IP_`、`_PH_NODE_IP_`、`_PH_PASSWORD_`、`_PH_BAKE_IMAGE_DIGEST_`。其余变体为 master 既有定义，VL 发布树未使用、语义保留。

## VL 分支新增占位符

VL 视觉线镜像分发链新增以下指纹类占位符（沿用尖括号风格）：

| 占位符 | 语义 | 示例场景 |
|---|---|---|
| `<INDEX_DIGEST>` | OCI manifest-list / image index digest（多架构分发口） | 镜像分发清单、`docker buildx` 产物校验记录 |
| `<CONFIG_DIGEST>` | arm64 platform image config digest | platform 级 config 校验记录 |
| `<BASE_IMAGE_DIGEST>` | 基座镜像 digest | **VL 语境明确指 baked4 基座**（VL 线首次烧制所用的基座镜像；master 已有该占位符，VL 沿用并收窄语义） |

## VL 分支节点引用政策

- **散文/报告引用**：统一 `node01`~`node04`（匿名主机名序号）。
- **脚本功能数组与循环**：保留管理网末段编号形态（如 `NODES="186 187 188 189"`、`for X in 187 188 189`）——末段 186-189 在脚本语境中为**节点编号语义，非敏感**（与 master 发布树先例一致：`scripts/disk_preflight.sh` 的 `for h in 186 187 188 189`、`scripts/window-restart-guard/w9r4_window_restart.sh` 的 `for X in 187 188 189`）。
- **行号/小数等非地址形态**：保留原样（不构成地址信息）。
- **管理网前三段（网段前缀）**：以 `_PH_HEAD_IP_` 占位，脚本中形如 `_PH_HEAD_IP_.186`（末段序号明示节点）。

## VL 分支保留声明

- `0.26.1.dev0+gd3d3b2cca` 中的 `d3d3b2cca` 为 vLLM fork 的 git commit 短哈希（版本串组成部分，公开信息），**非**内网镜像 digest，不做脱敏；请勿与 `<BAKE_IMAGE_DIGEST>` / `<INDEX_DIGEST>` / `<CONFIG_DIGEST>` 等镜像指纹占位符混淆。

## 规则

1. 批量替换工具 `redact.py` + 私有模式文件 `redact-patterns.json` 仅存在于本地（`redact-patterns.json` 已 gitignore，含真实值，勿提交）。
2. 已对发布副本执行全量替换并重扫验证：**工作树与已提交树敏感模式残留 = 0**（扫描类别：内网 IP / 环网子网对 / 管理网末段 / docker bridge / 主机名 / 内部用户名 / 密码 / key / 内部路径 / api key 形态 / 镜像 digest，含 8 位十六进制 digest 短前缀形态）。
3. 若后续发现遗漏（如新 IP、新路径、新 key），重新运行 `redact.py` 后提交。
4. **（VL 分支）** VL 发布树按同款规则执行替换与复扫：报告类文档敏感模式残留 = 0（扫描含裸管理网末段与带点尾段 `.18X` 形态）；脚本/数据按上述节点引用政策保留末段编号数组形态。vl-acceptance 运行日志（`gsm8k_f2_run.log` 等 4 件）与含真实敏感值的素材清单（MATERIALS-MANIFEST-20260909.md）裁定不入发布树。
5. **（范围声明）** 上文"敏感模式残留 = 0"覆盖本分支发布内容；master 主线既有公开内容（历史 commit 已推送）中的历史镜像 digest 短前缀裸值属既成公开事实，按"master 既有公开内容豁免"处理，不在本次重写范围；本分支文件中的同款形态已按 `<BAKE_IMAGE_DIGEST>` 占位符化。

## 已知简化

- 主机名统一映射为 `node0X`；monitor 跨机清理等需要序号语义的场景保留 `node01`~`node04` 序号（序号本身非敏感，真实 IP 已脱敏）。
- 端口号在 IP 脱敏时保留（如 `<NODE_IP>:8001`），端口不视为敏感。
- 裸管理网末段（如节点引用 `186`/`187`）统一映射为 `<MGMT_OCTET>` 或 `node0X` 序号语义（2026-09-03 复扫补齐 61 处）。

*本映射表不包含真实敏感值，可随开源仓库发布。*
