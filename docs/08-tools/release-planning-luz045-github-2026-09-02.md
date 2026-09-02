# LuZ0.4.5 GitHub 发布副本规划（文档治理 + 脱敏 + QA）

**日期**：2026-09-02
**参照**：LuZ0.3.1 开源仓库 `luxingcom/LuZ0.3.1-DeepSeek-v4-Flash-DSpark-DGXspark-TP4-Ring`（线上可见）
**目标**：为 `LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring` 定版准备可直接提交 github 的发布副本，脱敏干净、结构对齐、QA 通过。

---

## 1. 发布仓库结构（对齐 LuZ0.3.1）

```
luz045-github/
  README.md                  # 仓库说明（生产形态基线 + 最终指标入口 + 快速导航）
  CHANGES-2026-09-02.md      # 本版本变更记录（0.4.5 定版 + 修复 + 加固）
  REDACTION-MAP.md           # 脱敏映射表（净化版，不含真实值）
  .gitignore                 # 排除二进制/密钥/原始数据
  docs/
    01-research-reports/     # 研究报告（G1r5/G1r6 窗口、autotune、路线裁决）
    02-performance-benchmarks/# 性能测试报告与基准数据
    03-final-metrics/        # 最终性能指标汇总（FINAL-METRICS + CSV，benchmark 后填充）
    04-issues/               # 缺陷/事故/根因（工具编码 bug、热安全、超时守卫）
    05-kernels-patches/      # 算子/kernel/补丁相关报告（autotune 固化、W9R13）
    06-verification/         # 验证/QA/恢复演练/验收
    07-deployment/           # 部署/runbook/运维手册/回滚锚点
    08-tools/                # 工具链说明
  kernels/                   # 算子源码（W4A4 插件 / b12x 内核 / routeB）[如有可交付]
  patches/                   # 补丁包（autotune 固化、W9R13 工具编码、超时守卫）
  scripts/                   # 启动/部署/基准/巡检脚本（脱敏版）
  data/                      # 基准原始数据（json/csv，benchmark 后填充）
```

## 2. 文档治理：来源与去向映射

| 来源（本地 deliverables/engineering-assurance/） | 去向（发布 docs/） | 备注 |
|---|---|---|
| g1r6-release-finalization-2026-09-02.md | 07-deployment/ | 定版 + 活性探针关闭 |
| g1r6-experiment-benchmark-2026-09-02.md | 02-performance-benchmarks/ | 三窗口 + autotune + B1 |
| g1r5-full-benchmark-2026-09-02.md | 02-performance-benchmarks/ | G1r5 全量重测 |
| timeout-guard-cudagraph-warmup-2026-09-02.md | 04-issues/ | 超时守卫 + 预热 |
| bug-tool-call-encoding-2026-09-02.md | 04-issues/ | W9R13 工具编码根因 |
| W6/W7/W8/W9 系列报告 | 01-research-reports/ | 历史攻坚（选优） |
| 基准数据（benchv2-data 等） | data/ | benchmark 后 |
| FINAL-METRICS（待产出） | 03-final-metrics/ | benchmark 后 |

## 3. 脱敏规则（严格参照 LuZ0.3.1 REDACTION-MAP.md）

| 占位符 | 语义 | 本栈真实值（私有模式文件，gitignored） |
|---|---|---|
| `<PASSWORD>` | 明文密码 | <PASSWORD> |
| `<USER>` | 内部用户名 | <USER> |
| `<HOME_DIR>` / `<MODELS_DIR>` | 目录 | /home/<USER> / <INSTALL_DIR>/models |
| `<NODE_IP>` | 内网 IP（端口保留） | <NODE_IP><MGMT_OCTET> |
| `<MGMT_OCTET>` | 管理网末段 | .186/.187/.188/.189 及 ~18x |
| `<RING_SUBNET>` | 环网子网 | 10.100.x/10.20.x 及简写 |
| `<DOCKER_IP>` | bridge 容器 IP | 172.18.x.x |
| `REGISTRY_HOST` | 镜像仓库 | REGISTRY_HOST:5000 |
| `<API_KEY>` / `<BEARER>` | key/token | （若出现） |
| `<BASE_IMAGE_DIGEST>` | 镜像 digest | sha256:<BAKE_IMAGE_DIGEST> 等 |
| `node0X` | 主机名 | node0X~04 / DGXspark0X |

**机制**：`tools/redact.py` + `redact-patterns.json`（本地，gitignored，含真实值）→ 全量替换 → 重扫残留=0。

## 4. QA 检查清单

1. **脱敏扫描**：内网 IP / 环网子网 / 管理网末段 / docker bridge / 主机名 / 用户名 / 密码 / key / 路径 / registry / digest 全类残留 = 0（工作树 + 待提交树）
2. **文档一致性**：报告中的镜像 tag、digest、参数、md5 与生产实测一致
3. **脚本可执行性**：脱敏版脚本 bash -n / python 语法通过；占位符语义明确（README 说明）
4. **结构完整性**：docs/01-08 + kernels + patches + scripts + data + README + CHANGES + REDACTION-MAP + .gitignore 齐全
5. **零密钥/零模型**：无 .pem/.key/.env/id_rsa 等；模型走网盘分发（如 LuZ0.3.1 模式）

## 5. 阶段划分

- **P1 骨架 + 工具**：目录结构 + redact.py + redact-patterns.json + REDACTION-MAP.md + .gitignore
- **P2 文档组织**：按 §2 映射收集/复制报告 → 脱敏
- **P3 脚本收集**：从四机拉取脱敏版脚本（start/monitor/healthcheck/watchdog/bench）
- **P4 QA**：全类扫描残留=0 + 一致性核对 + 语法校验
- **P5 待 benchmark**：FINAL-METRICS + data/ 填充（督导通知后）

---
*规划：2026-09-02（执行中）*
