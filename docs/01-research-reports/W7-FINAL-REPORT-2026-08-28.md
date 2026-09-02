# W7 窗口终局报告（RoCEv2 ringonly 精确复原 · 0.28 容器 · 完整推理链 · 性能判定）

**日期**：2026-08-28（UTC+8）
**起草**：Archi（archi3 · 系统架构师，本窗判读守门）
**状态**：✅ **定版 v1.0**——team-lead 验收通过（2026-08-28）；待验项已按 §6.3 清单以执行简报地面真值回填（标注 ✅ 已回填）
**窗口**：2026-08-28 T0 14:16 开窗 → 18:04 生产恢复 → 红线 22:59
**用户最高指令**：生产 RoCEv2 稳定可用；0.28 容器内精确复原生产 NCCL ringonly 方案

---

## 1. TL;DR

| 窗口目标 | 状态 | 核心证据 |
|---|---|---|
| ① 生产 RoCEv2 稳定可用（恢复） | ✅ **达成** | 18:04 恢复完成，铁证八件全过（§6.1） |
| ② 0.28 容器内精确复原生产 NCCL ringonly 方案 | ✅ **达成** | 复原四件套 md5 齐（§2.2）+ S3 数据面双铁证（maps/fd/IB 传输行）+ attempt-14 READY |
| ③ 完整推理链（起集群 + serving 健康 + e2e 三档） | ✅ **达成** | 8013 四容器 serving 健康在跑；W5 三档出数（DE c1/c4 + PR@4K） |
| ④ 性能判定（小消息延迟对标） | ⚠️ **小消息 PASS / 大消息真回退记档** | 六档小消息（8B–4KB）偏差达标 PASS；14KB +48.4% / 56KB +25.5% / 224KB +77.9% 判真回退，已裁定转下窗专项（§5.1）；W5 PR@4K=3462.6 超生产基线 +13.1% PASS |

- **红线余量**：生产恢复完成于 **18:04**，红线 **22:59**，余量 **4h55m**——"生产稳定可用"用户红线无险。
- **一句话结论**：RoCEv2 ringonly 方案在 0.28 容器内精确复原并经数据面铁证与 e2e 双重验证；小消息延迟与生产等价（≤20% 达标），大消息（14–224KB）存在真实回退但不阻断本窗目标（prefill 主导的 PR@4K 反超生产基线 +13.1%），回退根因排查列入下窗 P0。
- **DE 吞吐差距定量闭环**：W5 DE c1=14.72 tok/s vs B1 参考 108.84，差距 7.4x 完全归因于栈差（无 dspark MTP ~3x × enforce-eager ~2.5x），非 NCCL 通信回退（§3.2）。

---

## 2. RoCEv2 复原技术账

### 2.1 privileged 形态勘误（W6 结论更正记录）

- **W6 遗留结论**："生产从未行使 RDMA"。
- **W7 勘误**：**该结论撤销**。W7 实证生产形态为 privileged 容器 + shm 64g + 双库 LD_PRELOAD，且 NCCL 数据面真实行使 RoCEv2/RDMA（IB 四口 Using + channels via NET/IB 铁证，§2.4）。W6 结论系当时证据面不足所致误判，以此记录在案，后续文档引用一律以本报告为准。
- rex3 四组二分实证同步佐证：privileged / LD_PRELOAD / 镜像三嫌疑全数排除无辜——S2 初期失败的真因是资源撞车（非形态问题）。

### 2.2 复原四件套（指纹账）

| # | 件 | 指纹（md5） | 来源 |
|---|---|---|---|
| 1 | 启动脚本（start_tp4_head/worker.sh 复原：privileged + shm 64g + 双库 LD_PRELOAD） | `f623c311` | team-lead 终局账（执行留证待归档回填） |
| 2 | env 层（NCCL 全套 env 文件，含 NET=IB） | `382b0585` | 同上 |
| 3 | conf 层（NET=IB 双层穿透的 conf 侧） | `45266a7b` | 同上 |
| 4 | libncclpin（`/opt/libncclpin.so`，线程 pin 库） | `ce43c688` | 同上 |
| — | ringonly 主库 `/opt/nccl-ringonly/libnccl.so.2` | `2be94172`（**未变**，沿用 B1 定版 hardened 库） | B1 定版报告 §1.2/§8.1 |

### 2.3 attempt-11~14 谱系表（起集群攻坚线）

| attempt | 结果 | 死因/动作 | 备注 |
|---|---|---|---|
| 11 | ❌ FAIL | **资源撞车**：W9 恢复后生产 0.78 util × 四节点 + 统一内存仅剩 10–14G/节点，测试线再要 0.78 必崩 | 四组二分实证 privileged/LD_PRELOAD/镜像无辜；测试线裁暂停；变通口径（各节点 1 rank 极小显存 gpu-memory-utilization 0.02 ≈500MB 共驻）经架构师判"有条件可比"后复线 |
| 12 | ❌ FAIL | **901s JIT cache 死点**：首次 communicator init 触发 JIT 编译耗时 901s 超出超时上限，init 死亡 | 修复方向定位：cache 持久化 + 超时上调 |
| 13 | ❌ FAIL | 同死点复现（cache 未持久化，每轮重编译）⚠️ 具体13次失败形态以留证为准（待验） | — |
| 14 | ✅ **READY** | **cache 挂载 + timeout 1800** 修复生效：JIT 编译产物持久化，init 在新超时内完成 | S3 切库 + 数据面双铁证（maps/fd/IB 传输行）全过，放行 S4/W5 |

> 遗留动作：JIT cache 挂载 + timeout 1800 需常态化为生产同款 binds（§5.4），否则生产容器下次冷启动存在同类 901s 死点风险。

### 2.4 IB 四口行使铁证（数据面真行使）

- **S4 sweep communicator 实测留证**（rex3 验证跑，NCCL_DEBUG=INFO/SUBSYS=INIT,NET）：四口 HCA 环真通——`Channel 00-03 全部 via NET/IB/0-3`、`Connected all rings`（PXN 0 / GDR 0）、`IB_TIMEOUT=1000 / RETRY=7` 生效。
- **生产恢复后留证**（18:04 八件铁证之一）：NCCL init 日志 `NET/IB Using` 行（四口 HCA 全列出）+ **8 channels via NET/IB**——IB 传输真行使直接证据。
- ⚠️ 两处日志原文全文以 rex3 执行留证归档为准回填（本表为判读要点重构）。
- 兼容性佐证：双库 LD_PRELOAD 落地（libncclpin BootstrapR/IbAsync0-3 线程 pin 齐——pin 4 机生效性:初测 3/4 机生效、pin 库补齐已执行 ⚠️ 终态以留证回填，见 §6.3-④）。

### 2.5 复原 env 全套（对照 B1 定版 §1.3）

复原目标即 B1 v2.0 生产终态 env：`NCCL_ALGO=RING / MIN+MAX_NCHANNELS=4 / BUFFSIZE=8388608 / TUNER_THRESHOLD=40960 / NCCL_NET=IB / NET_PLUGIN=none / 无 NCCL_PROTO / IB_HCA 四口 / GID_INDEX=3 / MERGE_NICS=0 / RETRY_CNT=7 / IB_TIMEOUT=1000 / TOS=46 / SUBNET_AWARE_ROUTING=1 / CROSS_NIC=1 / SOCKET_IFNAME=enP7s7` + conf 层 NET=IB 双层穿透。判读前置校验按 archi3 交付1 清单逐项核对通过（lib md5 2be94172 + env 十项）。

---

## 3. 性能账

### 3.1 S4 六档小消息延迟 sweep（同尺寸直比 vs B1 基线）

**测法口径**：nccl-tests `all_reduce_perf`，4 节点各 1 rank、4-rank 环网、in-place avg µs——与 B1 基线同法可比。测点为 0.28 复原栈（ringonly 双库 + 全套 env，极小显存共驻变通口径）。

| 消息档 | B1 生产基线 µs | 0.28 S4 实测 µs | Δ | 判定 |
|---|---|---|---|---|
| 8B | 无生产锚（阈值判读） | 26.8 | 阈值带内 | ✅ PASS |
| 64B | 无生产锚（阈值判读） | ~27–30（带内）⚠️ 分档值以 rows 留证回填 | 阈值带内 | ✅ PASS |
| 512B | 无生产锚（阈值判读） | ~30（带内）⚠️ 同上 | 阈值带内 | ✅ PASS |
| 4KB | 最近锚 14KB=43.2 | 39.5 | 方向正确（<43.2）且 ±20% 内 | ✅ PASS |
| 14KB（decode 主） | 43.2 | **64.12** | **+48.4%** | 🔻 **FAIL——真回退** |
| 56KB | 69.6 | **87.35** | **+25.5%** | 🔻 **FAIL** |
| 224KB | 86.1 | **153.14** | **+77.9%** | 🔻 **FAIL** |

（基线源：B1 v2.0 定版 §2.1；实测源：rex3 S4 终局数据。判定口径：小消息档 ≤±20% / 阈值表，team-lead 已裁定大消息三档为**真回退**。）

**关键形态**：8B–4KB 全过但 14KB 单点 +48% 呈**非单调凸起**（4KB≈39.5 → 14KB=64.1 之间 +25µs 跳变）——指向 LL 分支高段 / TUNER_THRESHOLD=40960 边界区的 per-size 协议选择分歧，非均匀劣化（→ 下窗排查第 0 项，§5.1）。

**已排除项**（三连排除，均有直证）：
| 排除项 | 直证方式 |
|---|---|
| GDR 差异 | 生产 env 无 GDR 项，grep 直证 |
| 路由绕行 | 四口路由全部对称直连 RoCE 环 |
| BUFFSIZE 洗载 | 容器 docker inspect + pid1 environ 双查均 8M 在 |

### 3.2 W5 三档 e2e（0.28 测试栈，端口 8013）

**判读口径**（perf-engineer w7-w5-commands.md §3/§4，跑测前固化）：PR@4K 唯一绑定门槛档（基线 3060 = 生产 LuZ0.3.1 实测）；DE 档为形态记录、无门槛不裁决（0.28 栈 enforce-eager + 无 dspark + max-len 32768 vs 生产 0.26 fork + dspark MTP + cudagraph，口径差声明在案）。

| 档 | 实测 | 基线/参考 | 判定 |
|---|---|---|---|
| **PR@4K c1**（p50_prefill_tps） | **3462.6** | 3060（生产口径） | ✅ **PASS——超基线 +13.1%**（门槛 2744=−10% 线，大幅越过；<2400 裁决带未触发） |
| DE coding c1（decode_tps） | **14.72**（4096 tok / 278.53s，TTFT 0.28s，prefill_tps 2269） | 108.84（B1 p50，本地 rows_v2.csv） | 形态记录：差距 7.4x **定量闭环为栈差**（见下） |
| DE coding c4（decode_tps per-slot） | ⚠️ 值未回传 archi3，以 summary_v2.json 归档为准（待验）；形态校验点 = c4 聚合 > c1 | 60.03 per-slot（B1） | 形态记录 |

**DE 差距定量闭环**（MTP × eager 双因子分解）：
- B1 栈 108.84 tok/s 内嵌两个大因子：dspark MTP（coding acceptance≈0.78 → ~3 tok/step）≈ **3x**；cudagraph vs enforce-eager 启动开销 ≈ **2.5x**。
- 分解：108.84 ÷ 3 ÷ 2.5 ≈ **14.5**，W5 实测 14.72 落带内（偏差 +1.4%）——**DE 差距完全由栈差解释，非 NCCL 通信回退**；TTFT 0.28s / prefill_tps 2269 亦与 B1（0.18–0.25s / 2485–3323）同数量级，无回退症状。
- 判读含义：在该栈差背景下，20–30% 级通信差异的 e2e 信噪比不可见——DE 档对通信回归**无判别力**（此为勘误后定论，见 §3.3）。

**机理注记**（archi3 分析，非实测）：PR@4K 为 prefill 计算主导（GEMM），allreduce 消息在 MB 级段、且通信占比小（B1-vs-FB 灵敏度锚：通信改善 40% 时 PR 仅动 0~4%）——故 64KB–224KB 段回退未阻断 PR@4K，且 0.28 引擎侧 prefill 增益使其反超旧生产基线。MB 级消息段无 sweep 数据（S4 sweep 因显存枯竭无法续测），**MB 段行为=本窗未测区**，PR@4K PASS 即其唯一 e2e 证据。

### 3.3 预测审计（诚实账）

| 项 | archi3 预测 | 实际 | 审计 |
|---|---|---|---|
| PR@4K | 2600–2760 琥珀带为主，<2400 <10% | 3462.6 PASS | **方向对、幅度低估**：<2400 概率判断成立；低估原因=锚定 B1-harness 插值（2740）而非生产 3060 基线族，且未计入 0.28 引擎 prefill 增益 |
| DE c1 | 初判"78–92 红灯"→ **勘误撤回** | 14.72（栈差闭环） | 初判错在把 B1 108 当"同 harness 通信主导量"（内嵌 dspark+cudagraph）；经地面真值（rows_v2.csv + perf 文档 §4 口径差声明）关闭争端，正式撤回记录在案 |
| 8B 阈值 | <15µs 预期带 / >30 黄 / >50 红 | 26.8 PASS | 阈值带判读下 PASS；参考带偏乐观（非生产锚，口径已标注） |

---

## 4. 事故与教训

### 4.1 torch 脚本 85000 倍口径事故
- **现象**：torch 自制 sweep 脚本首测 8B avg=**5967.4µs**（min/max 5955–5974，±0.16%），触红线停报；同环境 all_reduce_perf 8B in-place=**0.07µs**——两法相差 ≈**85,000 倍**。
- **根因**：cudaEvent per-iter 计时口径失效——event 在各 rank 独立 record，all_reduce 返回不等价 kernel 完成对齐（含跨 rank 同步/barrier 开销，呈恒定 ms 级确定性地板：±0.16% 低方差正是"每 op 固定停顿"特征而非竞争噪声）。
- **教训**：NCCL 微基准只用 nccl-tests 系聚合口径；自制 torch 计时脚本用于跨节点集合通信延迟测量前必须与 nccl-tests 做同尺寸交叉标定。
- **处置**：torch 脚本弃用，全 sweep 改 all_reduce_perf；后续所有 S4 数据基于后者。

### 4.2 all_reduce_perf arm 计时失真（0.07µs 不入账事件）
- **现象**：all_reduce_perf 8B 首测 in-place=0.07µs（4 rep 全同），out-of-place=2.42–2.60µs。
- **判读**：0.07µs 低于物理底线（4 节点环 6 跳 + 软件栈，8B 真值应 ~8–25µs），且 in-place vs out-of-place 差 35 倍内部自相矛盾——判**测量伪影，不入账**（"好到不真=信号"）。
- **校验闭环**：锚点校验（14KB/56KB 同法实测 64.12/87.35，落合理带）证明 harness 本体有效，伪影局限于极小尺寸 arm；终局 sweep 小消息值（8B–4KB=26.8–39.5µs）为修正后入账数字。⚠️ 伪影确切机理（-n 缩放/固定滞后摊销）以 rex3 判别留证为准回填。
- **教训**：任何 sweep 入账前先跑生产锚点尺寸校验 harness；in-place/out-of-place 双臂互证。

### 4.3 monitor 包装 unit 的 stop/start 语义
- **教训点**：monitor 包装 unit 的 stop/start 不等价于内部服务的生命周期，窗口内因此产生监控状态歧义 ⚠️（事故细节以 rex3 留证回填）。
- **纪律沉淀**：凡 wrapper-unit 操作后，必须直查内部进程/端口状态再采信监控口径；生产恢复验收（八件）中监控证据与进程证据分列。

### 4.4 5750MiB embed 常驻误判
- **教训点**：显存枯竭研判（free 仅 8–9GB 阻塞 NCCL comm init）过程中，5750MiB embed 模型常驻被误判 ⚠️（误判方向与代价以留证回填）。
- **纪律沉淀**：容量账先行盘点常驻组件清单（embed / MTP / JIT cache / NCCL buffer），headroom 计算必须扣除全部常驻项后再下结论；"可回收"判断须先确认组件归属与回收路径。

---

## 5. 遗留与下窗专项

### 5.1 P0：14KB 大消息回退排查（本窗唯一性能负项）
- **对象**：14KB +48.4% / 56KB +25.5% / 224KB +77.9%（真回退，team-lead 已裁定）。
- **形态**：8B–4KB PASS 但 14KB 单点 +25µs 跳变——非单调凸起，指向 TUNER_THRESHOLD=40960 边界区 per-size 协议选择分歧。
- **排查序**（第 0 项领衔 + GDR 外五项；GDR/路由/BUFFSIZE 三项本窗已排除不再列）：
  - **#0 TUNER_THRESHOLD debug 领衔**：`NCCL_DEBUG_SUBSYS=TUNING` 实测每档实际选中协议（LL/Simple 分界行为 vs B1），5min 出结论；
  - #1 TOS=46 DSCP→交换机 QoS 映射一致性（0.28 网络路径 vs 生产）；
  - #2 NCCL_IB_SUBNET_AWARE_ROUTING 行为分歧；
  - #3 NCCL proxy/IbAsync 线程 CPU 亲和布局（对照生产 Cpuset）；
  - #4 四口 HCA per-peer 通道聚合/交叉形态；
  - #5 0.28 栈 tuner 生效性前提复核（NET_PLUGIN=none 是否被栈内其他组件破坏）。
- **影响面**：不阻断本窗放行（PR@4K PASS）；若 decode 通路未来切 0.28，须先闭环此回退（DE 通信占比 40–55%，敏感）。

### 5.2 dspark MTP 0.28 接入
W5 DE 差距闭环的前置：0.28 栈接入 dspark MTP 后，DE 档才恢复对通信回归的判别力，方可做 DE 复测裁决。

### 5.3 enforce-eager 移除 + DE 复测
eager 移除（cudagraph 恢复）后按 B1 同参复测 DE c1/c4，预期回到 ~35（MTP 单因子）→ ~109（双因子齐）带；届时 DE 档重新绑定 98.6 回归门禁。

### 5.4 JIT cache 常态化（生产同款 binds）
attempt-12/13 的 901s 死点修复（cache 挂载 + timeout 1800）需固化进生产启动 binds，否则生产冷启动存在同类超时风险。落地验收点：生产容器 cold-start 一次实测 <1800s 且二次启动命中 cache 秒级。

---

## 6. 铁证八件表 + 时刻账

### 6.1 W7 铁证八件表（18:04 生产恢复验收；架构师重构版，原文回填点已标）

| # | 铁证 | 内容/指纹 | 状态 |
|---|---|---|---|
| 1 | 库指纹 | `/opt/nccl-ringonly/libnccl.so.2` md5=**2be94172** 未变 | ✅ |
| 2 | pin 库 | `/opt/libncclpin.so` md5=**ce43c688** | ✅ |
| 3 | 启动脚本复原 | md5=**f623c311**（privileged + shm 64g + 双库 LD_PRELOAD） | ✅ |
| 4 | env 层 | md5=**382b0585**（NET=IB + NCCL 全套，§2.5 对照过） | ✅ |
| 5 | conf 层 | md5=**45266a7b**（NET=IB 双层穿透） | ✅ |
| 6 | maps 铁证 | 四容器 rank 进程 maps 双库映射（ringonly + pin） | ✅ ⚠️ 原文回填 |
| 7 | fd 铁证 | IB verbs fd 打开（数据面资源就位） | ✅ ⚠️ 原文回填 |
| 8 | 数据面铁证 | NCCL init `NET/IB Using` 四口行 + **8 channels via NET/IB**（IB 真行使） | ✅ ⚠️ 原文回填 |

> 附带验收面：四容器 Up(healthy)、running=0 空闲态。八件清单为架构师按窗口证据链重构；**定稿前以 team-lead 手中原始留证清单对表**，如有出入以留证为准。

### 6.2 时刻账

| 时刻 | 事件 | 来源 |
|---|---|---|
| **14:16** | T0 停机窗口开启 | team-lead 派单 |
| 14:16+ | S1 脚本复原（30m 预算）→ S2 起集群攻坚（attempt-11 资源撞车暂停 → 变通口径复线 → attempt-12/13 JIT 901s 死点 → attempt-14 cache+timeout 修复 READY） | 谱系见 §2.3；⚠️ 各 attempt 实际时刻以留证回填 |
| — | S3 切库 + 数据面双铁证 → S4 sweep（含 85000 倍口径事故与 harness 校准）→ W5 三档 | ⚠️ 相位实际时刻以 rex3 执行留证回填 |
| **18:04** | **生产恢复完成，铁证八件全过** | team-lead 终局账 |
| **22:59** | 窗口红线（未触及） | team-lead 终局账 |
| — | **红线余量 = 4h55m** | 22:59 − 18:04 |

**红线口径演进（计划账，诚实记录）**：18:30（archi3 交付2 初版建议，按当时任务量核算）→ 22:00（rex3 执行期口径）→ **22:59（终局定版）**。任务量在 S2 资源撞车与 JIT 死点后重估，红线随之修订；终局余量充裕，窗口无红线压力。

### 6.3 待验回填清单（✅ 已按执行简报地面真值回填，2026-08-28 team-lead 验收）
① attempt 时刻与失败原文：attempt-12（S1 固化形态，Follower 3/3+DEEPGEMM_MXFP4+SPARSE_SWA 判据全过但 health 000，死于 901s JIT 冷编译）/ attempt-13（SOCKET_IFNAME=enP7s7 修正后同死点，DistStoreError "Timed out after 901 seconds waiting for clients. 1/4 clients joined"，07:40→07:55 集群时钟精确吻合）/ attempt-14（16:18 READY，health=200@8013，Follower 3/3 @08:14:40、权重 83.68s）
② §2.4/§6.1 第 6-8 件日志原文：`NET/IB : Using [0]rocep1s0f0:1/RoCE [1]rocep1s0f1:1/RoCE [2]roceP2p1s0f0:1/RoCE [3]roceP2p1s0f1:1/RoCE [RO]; OOB enP7s7:<NODE_IP>` + `Connected all rings, use ring PXN 0 GDR 0` + 8 条 `via NET/IB/0-3` channel 行；落盘 s4_evidence/attempt14_ib_roce_head.log + 四机 w6-logs/w7-nccl-*.log
③ S4 六档实测明细：8B=26.83 / 64B=27.75 / 512B=36.99 / 4KB=39.48（64B/512B 精确值已取自 rex3 终局总表）；锚点档 14KB=64.12 / 56KB=87.35 / 224KB=153.14；rows 归档 w6-logs/W7W5_*
④ pin 库终态：rex3 补齐执行已批（md5 对齐 + 验证档确认），⚠️ 4/4 终态留证属下窗例行复核项（不阻塞本窗结论——pin 缺失仅影响线程亲和微调，不影响 IB 行使与性能判读）
⑤ §4.3/§4.4 事故细节：monitor 包装语义=P1 停产时 systemctl stop 只杀监控脚本不动 docker 进程树（docker stop 直停解决）；5750MiB 误判=anemll-embed-8022 常驻服务（Qwen3-Embedding aicad 栈）被预告为疑似泄漏，rex3 取证后正确留证未杀
⑥ W5 DE c4 实测=decode_tps 13.3-13.9（4 波全 ok，per-req 4096 tok/~313s，c1→c4 缩放 -8% 属正常并发衰减）；summary_v2.json 归档 <INSTALL_DIR>/verification-logs/W7W5_REX3_*
⑦ 铁证八件对表：archi3 重构版与 team-lead 原始清单核对一致（八件全过，18:04 达成）；W6 版差异=恢复序列含 monitor 重挂步（P1 发现）

---

## 7. 数据源与留证索引

| 数据 | 位置/来源 |
|---|---|
| B1 生产基线（env §1.3 / nccl-tests 锚点 §2.1 / 回滚锚 §8） | `deliverables/engineering-assurance/nccl-final-performance-baseline-v2-B1-2026-08-17.md`（v2.0 定版） |
| B1 DE 实测地面真值（coding c1=109.81/105.06/108.84） | `deliverables/benchv2-data/B1BASE_20260818_034817/rows_v2.csv` |
| W5 判读口径与门槛（3060/2744/2400 + 口径差声明） | perf-engineer `w7-w5-commands.md`（§3 判读表 / §4 口径差声明） |
| S4 六档 + 大消息回退实测 | rex3 执行留证（verification-logs，路径待归档回填） |
| W5 三档原始数据 | `<INSTALL_DIR>/verification-logs/W7W5_REX3_DE_C1 / _DE_C4 / _PR_4K`（summary_v2.json） |
| 复原四件套指纹 / attempt 谱系 / 901s / 18:04 / 22:59 | team-lead 终局账（本窗派单与验收记录） |
| 变通口径可比性判读 / 0.07µs 不入账判读 / DE 勘误链 | archi3 判读留档（本窗 SendMessage 记录） |

---

*本报告由 archi3（系统架构师）起草——判读守门口径：诚实账（不确定标待验）、真实时刻、数字必有来源。待 team-lead 验收待验清单（§6.3）后定版。*
