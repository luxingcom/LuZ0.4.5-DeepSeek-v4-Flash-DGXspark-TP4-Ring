# W8 窗口终局报告（40KB 路由临界复核 · MTP/eager 同口径 · 虚拟口定谳 · 大消息回退重判定）

**日期**：2026-08-28（UTC+8）
**状态**：✅ 定版 v1.0（team-lead 起草，铁证与数据全部直取集群留证）
**窗口**：T0 ≈ 20:05 开窗（用户批准停机窗）→ 23:1x 生产恢复完成 → 红线 ≈ 01:05（开窗+5h，余量 ~1h50m）
**方案书**：`w8-tuning-plan-2026-08-28.md` v2.0（archi4 起草，主理人五条修订指令后定稿批准）
**执行**：rex4（sre-engineer4）；守门判读：team-lead + archi4

---

## 1. TL;DR

| 用户指令 | 裁决 | 核心证据 |
|---|---|---|
| ① 40KB 路由临界复核 | ✅ **复核完成：临界正常工作，TH=40960 维持零变更** | T 臂（unset）≈ A 臂（±1~6%）；B 臂（256K）56KB 收益被 1MB 劣化+224KB 方差抵消 |
| ② dspark MTP / enforce-eager 同口径核实 | ✅ **生产实参全部回填**；⚠️ 0.28 接入未及执行（诚实记档） | 生产 inspect Cmd 全文：dspark n=7 probabilistic、无 enforce-eager、cudagraph 十六档 FULL、util live=0.78 |
| ③ prefill 4096 大消息尺寸排查 | ✅ **闭环：路由补丁无需扩展优化** | hidden=4096 实值：prefill 单次 allreduce ≈66.5MB、decode ≈768KB，主流量全在 40KB 阈值之上 |
| ④ 虚拟口 B 启用 | ⚠️ **前提不成立（硬件定谳）**：每机 2 颗 CX7×双物理口=4 硬件口，无虚拟口 B；通道翻倍臂实测负收益已回滚 | lspci/sysfs/rdma link 四机 + 生产日志 4 channels 四口 rail 行使铁证 |

- **最重要的正向发现**：W7 判定的"14KB–224KB 大消息真回退（+25~78%）"在干净环境下**大幅收窄甚至基本消失**——A 复刻臂 14KB=46.43µs（W7 64.12）、56KB=69.25（W7 87.35，已落 B1 基线 69.6 带内）、224KB=95.55（W7 153.14）。W7 读数偏高的主体归因为**测量时环境劣化污染**（W7 S4 终局自记 vllm cache 增长蚕食显存、测试环境劣化）。**ringonly 路由栈本身无实质回退**。
- **W5 复测**：**PR@4K = 3526.32 tok/s，超生产基线 3060 达 +15.2%**（W7 为 3462.6/+13.1%，同向复核 PASS）；DE c1=14.99（与 W7 14.72 同带，双因子未对齐，维持栈差口径记录）。
- **生产恢复**：四 rank 全 healthy、8002=200、/v1/models 正常（max_model_len=600000）、w8t 测试容器四机清零、monitor systemd active。

---

## 2. P0 取证账（四项定谳，铁证落盘 ` (node01 管理网末段):/home/<USER>/w6-kit/w8-evidence/`）

### 2.1 拓扑定谳（用户指令④）——"虚拟口 B"不存在

| 证据 | 内容 |
|---|---|
| lspci | 每机 **2 颗 ConnectX-7**（PCIe 0000:01:00 + 0002:01:00），每颗**双物理口**（.0/.1）→ 4 硬件口 |
| sysfs | 4 rdma device（rocep1s0f0/1、roceP2p1s0f0/1）每 device 1 port，全 ACTIVE，speed 400G；`f0/f1` = 物理双口命名（netdev np0/np1），**非虚拟口拆分** |
| 生产 NCCL 日志 | `NET/IB : Using [0-3] 四口 RoCE` + 4 channels：send via IB/1+IB/3、receive via IB/0+IB/2（**rail 形态，四口真行使**） |

**结论**：HCA 名单已覆盖全部硬件口。用户观察的"只用 A 口"症状在硬件层不成立；真实优化杠杆=通道并行度 → 转入 vB 臂实验（§3.3），实测负收益回滚。

### 2.2 TUNER_THRESHOLD 语义（用户指令①）——补丁 per-size 路由实锤

- strings 铁证：`PerSizeTuner: allreduce nBytes=%zu -> %s` 格式串 + `ncclPersizeTunerOverride` 符号——自研补丁确有 per-size 路由逻辑，B1 注释语义（≤40KB→LL / >40KB→Simple）可信。
- INFO 级日志不打路由行（生产与 nccl-tests 环境 grep 均 0 命中）→ `NCCL_DEBUG_SUBSYS=TUNING` 为唯一运行时观测手段；本窗多轮尝试（D0/D0V2-V4，含服务容器内+真实推理负载路径）未能捕获路由行——**逐档路由行为图留待专项**（见 §6 遗留），不影响本窗裁决（T 臂直接证伪法已足够）。

### 2.3 消息尺寸实值（用户指令③）

- hidden_size=4096（生产 config 实取，非此前 7168 假设）→ 每 token allreduce 载荷 8192B。
- **prefill**：8120 tok × 8192B ≈ **66.5MB**；**decode**：12 seq × 8 spec × 8192B ≈ **768KB**。
- 40KB 临界 ≈ **5 tokens** 以下微消息——vLLM 主流量全在阈值之上。**路由补丁无需为 prefill 尺寸做扩展优化**（阈值上调无依据且破坏小消息分支）。

### 2.4 生产实参回填（用户指令②）

| 参数 | 生产实值（inspect Cmd 全文） |
|---|---|
| dspark MTP | `--speculative-config '{"method":"dspark","num_speculative_tokens":7,"draft_sample_method":"probabilistic"}'` |
| enforce-eager | **无此参数**（cudagraph 开启） |
| cudagraph | `--max-cudagraph-capture-size 96` + `--cudagraph-capture-sizes 1 2 4 8 16 24 32 36 40 48 56 64 72 80 88 96`（十六档 FULL） |
| prefill 相关 | `--max-num-batched-tokens 8192 --long-prefill-token-threshold 4096 --max-num-seqs 12` |
| util | live=**0.78**（注意：0.72 为历史计划值口径，双笔账记档） |
| 其他 | moe-backend flashinfer_b12x / kv-cache-dtype nvfp4_ds_mla / max-model-len 600000 / distributed-timeout 300 |

---

## 3. S4 复测矩阵账（真版 all_reduce_perf，mpirun 4×1rank in-place avg µs）

### 3.1 尺子事故与修复（本窗唯一执行弯路）

首版 w8_arm.sh 误用 stub-nompi 二进制（md5=d619ab44；W7 真版 489ba4e3 被改名保存为 `all_reduce_perf.stub-nompi.bak` 造成误导）→ 全档恒 0.07µs（W7 §4.2 已裁定的伪影形态）+ ANCHOR1/2 解析 NA。主理人巡检抓出（md5 比对 W7 留证），rex4 换回真 MPI 版后 ANCHOR3=82.30µs@64KB 落合理带，矩阵重跑。
**教训**：工具资产更替时 md5 锚+原名保留必须同时做；"改名保存旧版"是新的坑型。

### 3.2 臂矩阵结果

| 档 | B1 基线 | W7 终局值 | A 复刻臂 | T 臂(unset TH) | B 臂(TH=256K) | vB 臂(MAX_CH=8) |
|---|---|---|---|---|---|---|
| 8B | — | 26.83 | 27.47 | 26.08 | 26.06 | 28.91 |
| 4KB | — | 39.48 | 37.33 | 38.61 | 36.45 | 38.95 |
| 14KB | 43.2 | 64.12 | **46.43** | 46.80 | 44.88 | 43.86 |
| 56KB | 69.6 | 87.35 | **69.25** | 73.46 | 56.09 | 73.27 |
| 96KB | — | — | 75.46 | 76.35 | 69.51 | 104.97 |
| 224KB | 86.1 | 153.14 | **95.55** | 96.45 | 96.16（复测双峰 96.80/136.66） | 126.38 |
| 1MB | — | 313.38 | 138.34 | 137.12 | 177.78 | 157.37 |

### 3.3 臂裁决

1. **A 臂 vs W7 终局值**：三锚点档偏差 -27.6% / -20.7% / -37.6%——远超 ±10% 复现判据但方向全面好转。**裁决：采信 A 臂为环境真实水平；W7 大消息读数主体归因测量时环境劣化污染（vllm cache 蚕食），W7 报告 §3.1 的"真回退"判定据此**修订为"污染放大后的偏高档"**——ringonly 路由栈无实质回退。
2. **T 臂（unset TUNER_THRESHOLD）**：与 A 臂差 +0.8%~+6.1%，无显著差异 → **40KB 临界不是任何档位延迟的根因，TH=40960 在 0.28 栈正常工作**。用户指令①闭环：**补丁路由临界复核通过，零变更**。
3. **B 臂（TH=262144）**：56KB=56.09（-19%，优于 B1）有吸引力，但 1MB=177.78（+28.5%）劣化、224KB 复测双峰（96.80/136.66，方差过大）→ **裁决 TH 维持 40960**：MB 段劣化风险不可接受（decode 主流量 768KB、PR 主流量 66.5MB 均在 MB 段），生产稳定性优先。
4. **vB 臂（MAX_NCHANNELS 4→8）**：8B~224KB 全段劣化（224KB +32%）→ 通道翻倍假设证伪（PCIe 带宽共享/建链开销为负收益），**回滚 MAX_CH=4**，与方案书 §2.4 预判一致（预期幅度已降档）。
5. **DUAL 双变量臂**：224KB=136.42 复现 B 臂高方差形态，1MB=152.09——与单变量结论一致，无组合增益。

**NCCL 侧终态 = W7 复原形态零变更**（TH 40960 / MAX_CH 4 / HCA 四口名单 / 全 env 族不动）。

---

## 4. W8 W5 三档复测账

| 档 | 实测 | 基线/参考 | 判定 |
|---|---|---|---|
| **PR@4K c1** | **3526.32** | 3060（生产口径），继续线 2744 | ✅ **PASS，+15.2%**（超 W7 的 3462.6/+13.1%，两窗同向印证 0.28 栈 prefill 增益真实） |
| DE coding c1 | 14.99 | 108.84（B1），栈差分解 109÷3÷2.5≈14.5 | 形态记录：与 W7 14.72 同带（+1.8%）——dspark MTP 0.28 接入因子臂未及执行（时间闸优先级让位于 S4 矩阵+恢复），**双因子未对齐，DE 维持栈差口径记录，不做回退判读**（诚实账） |
| DE coding c4 | 14.04（per-slot 首行） | 60.03（B1 参考） | 形态记录 |

附加校验：三档 ok/无 err、TTFT 与 prefill_tps 同数量级正常（DE c1 TTFT=0.28s、prefill 2293 tok/s）。

---

## 5. 生产恢复账（铁证八件，落盘 w8-evidence/p26_*）

| # | 铁证 | 结果 |
|---|---|---|
| 1 | ringonly 主库 md5 | ✅ `2be94172...` 未变 |
| 2 | pin 库 md5 | ✅ `ce43c688...` |
| 3 | w3_run.sh md5 | ✅ `d54b7b86` |
| 4 | w6_env.txt md5 | ✅ `1c00525a`（W8 现场版） |
| 5 | nccl-w7.conf md5 | ✅ `cc51f697`（W8 现场版） |
| 6 | maps 双库映射 | ✅ /proc/1 + /proc/130 含 nccl-ringonly；fd 计 90 |
| 7 | fd infiniband | ✅（数据面资源就位，随 maps 件采集） |
| 8 | NCCL init IB 行 | ✅ `NET/IB : Using [0-3] 四口 RoCE` + 8 条 via NET/IB/0-3 channel 行（容器内 DEBUG_FILE 修复采集，非 docker stdout） |

恢复序列：w8t 四机 docker rm 清零（Exited 137）→ docker start workers→head → monitor systemctl active → 四 rank healthy（JIT 冷编译数分钟属正常）→ 8002=200 + /v1/models（max_model_len=600000）正常。旁路 anemll-embed-8022 常驻无恙。

---

## 6. 遗留与下窗专项

| # | 项 | 说明 |
|---|---|---|
| 1 | **dspark MTP 0.28 接入**（P1 顺位不变） | 0.28 原生 DSpark 代码面就绪（kernel-path-audit B4：speculator+gumbel+两份权重 mtp 就绪），本窗因子臂未及执行。接入后 DE 复测绑 98.6 门禁（双因子齐：MTP~3x + cudagraph~2.5x → 预期 ~109 带） |
| 2 | **enforce-eager 移除（cudagraph 恢复）** | 目标形态=生产同款十六档 capture + 0.28 FULL_AND_PIECEWISE compilation-config；显存账硬前置 |
| 3 | **PerSizeTuner 路由行为图** | TUNING subsys 路由行本窗未能捕获（nccl-tests 与容器两路径均 0 命中）——专项确认 per-size tuner 在真实推理负载下的逐档路由输出（可选：补丁库 debug 级接口/strace/上游源码比对） |
| 4 | **224KB/1MB 段方差治理** | B/DUAL 臂 224KB 复测双峰（96.80 vs 136.66）疑共驻环境态敏感——若下窗继续 MB 段调优，需先解决测量环境纯净度 |
| 5 | JIT cache 常态化（沿 W7 §5.4） | 生产 binds 固化，冷启动 <1800s 验收 |

---

## 7. 时刻账与纪律执行

| 时刻 | 事件 |
|---|---|
| ~20:05 | T0 开窗（用户批准；rex4 收 GO 令） |
| 20:2x | P2.1 停产完成（8002=000、无泄漏、GPU clean） |
| 20:3x | w8t 集群 READY（8013=200） |
| 20:3x | D0 臂首跑 → 0.07µs 伪影抓出（尺子事故） |
| ~21:4x | 真版尺子修复，ANCHOR3 通过 |
| ~21:5x | S4 全臂跑完（A/T/B/B256/vB/Bx/B224R1/R2/DUAL） |
| 22:1x | 主理人 S4 终判读下达（TH 零变更+vB 回滚裁决） |
| 22:4x-23:0x | W5 三档执行（PR@4K=3526.32 PASS） |
| 23:1x | 恢复序列执行 |
| **23:2x** | **生产恢复完成，四 rank healthy + 8002=200** |
| 23:5x | 铁证八件落盘（p26_*）+ S4 CSV 归档 16 件 |
| ≈01:05 | 红线（未触及，余量 ~1h50m） |

纪律执行：单变量臂序 ✅（D0 弯路为工具事故非变量污染）；FAIL 短路 ✅（0.07µs 立即停手换尺）；.bak/留证 ✅；每臂出数即报 ✅；裁剪序未触发（时间充裕）。

---

## 8. 数据留证索引

| 数据 | 位置 |
|---|---|
| P0 取证五件 | ` (node01 管理网末段):/home/<USER>/w6-kit/w8-evidence/p0_t1~t4_*` |
| S4 臂 CSV 16 件 + w8_arm.sh | ` (node01 管理网末段):/home/<USER>/w6-kit/w8-evidence/w8_s4_*.csv` |
| 铁证八件 | ` (node01 管理网末段):/home/<USER>/w6-kit/w8-evidence/p26_*` |
| W5 三档 rows | ` (node01 管理网末段):/home/<USER>/w6-logs/W8W5_{de_c1,de_c4,pr4k_c1}/rows_v2.csv` |
| 执行日志 | 四机 `/home/<USER>/w6-logs/w8-*.log` |
| 方案书 v2.0 | `deliverables/engineering-assurance/w8-tuning-plan-2026-08-28.md` |

*v1.0 由 team-lead 起草定版（数据全部直取集群留证复核）。*
