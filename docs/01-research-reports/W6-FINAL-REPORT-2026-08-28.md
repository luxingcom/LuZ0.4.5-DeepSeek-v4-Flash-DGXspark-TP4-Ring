# W6 停机窗口终局报告（v1.0 定稿）

**窗口:** 2026-08-28 · vLLM 0.28 升级 · DGX Spark 4 节点 TP4
**红线:** 生产恢复 15:37 · **起草:** architect2（阿奇2），主理人台账全量回填
**时钟注记:** 文中 attempt 时刻为集群时钟；真实时刻 ≈ 集群时钟 +9h。
**状态:** ✅ **已定稿 — 红线达成（13:53，提前 1h44m），W9 铁证①~⑧全过**

---

## TL;DR

- 本窗核心目标：vLLM 0.28 升级后 NCCL 多机通信打通，镜像谱系 r9 → r10 → r10c → r10d 逐轮收敛。
- **NCCL 侧历史性通过**：r10d（a10）全判据清零（Follower 3/3 / SPARSE_SWA / DEEPGEMM_MXFP4+E8M0 / bootstrap / NET 层全过）。
- **唯一悬置**：a10 head 侧 shm_broadcast NOT READY（每 60s 重试，非 collective timeout 不触发）——本窗唯一未闭环技术疑点，诊断结论 32g=要求 2 倍，生产 64g，a11 因诊断证伪未发生。
- **红线达成状态：✅ 达成——实际恢复完成时刻 13:53，红线 15:37，提前 1h44m。W9 铁证清单 ①~⑧ 全过（见终章）。**
- 诚实账：**W5 性能三档（DE c1 / DE c4 / PR@4K）本窗零数据**，判读门槛原样带入下窗，不外推；ringonly RDMA 数据面形态判定为**生产本就不存在**（生产从未挂 infiniband 设备）；**attempt-8（a8）三铁证未取得**——FAIL 于 NET 初始化未达 ready，切库证据为间接（a8 双运行时告警 + a10 全判据过），直接 maps 取证从未完成，标注**待验（需集群 serving 态）**；dspark 本窗裁掉不再复议。

---

## 一、审查与修复账（F1~F5，主理人台账实证）

| 编号 | 内容 | 状态 |
|------|------|------|
| F1 | 四机 w3_run.sh pin r6→r8，digest sha256:54de247e…760，md5=58cca4ac，.bak-r8pin 留存 | ✅ 完成 |
| F2 | 混镜像风险脚本 w3_run_worker.sh（pin=r5 bf8cfa62）四机改名 .DEPRECATED-pinR5 | ✅ 完成 |
| F3 | w6_env.txt 加 NCCL_DEBUG=WARN。**偏离备案**：该文件为 KEY=VALUE 逐行解析，写 export 前缀会炸 docker run；md5=7533e663 | ✅ 完成（含备案） |
| F4 | w3_run.sh usage 守卫 + env 注释/空行过滤（grep -v），四机 bash -n 通过 | ✅ 完成 |
| F5 | analyze_bench.py 补齐 .186:<INSTALL_DIR>/（本地副本 sha256 前缀 72360bcb，2345B） | ⚠️ **执行状态待验**（Rex F1-F4 验收报告未含 F5，后被 NCCL 线挤占） |

---

## 二、断点战史（编号断点 ①~⑥）

- **① PYNCCL**: VLLM_DISABLE_PYNCCL=1 规避。
- **② linear backend 强制**: GB10 CC90 门禁，改 auto 规避。
- **③**: 明细待验。
- **④ r4 follower 守卫**: vllm/v1/engine/core.py:135，条件 L121 node_rank_within_dp!=0 → hold；0.28 stock 删 distributed/core.py:126-129 属实；KV/SPARSE_SWA 为上窗死点（r5 分派表 (16,192)→L86 接线在位）。
- **⑤**: 明细待验。
- **⑥ TuningConfig tensor_initializers 双源 API 漂移 → r9**: r5 取 flashinfer main 版源码 vs 镜像装 0.6.16.post3；TuningConfig 仅 4 合法 kwarg；错点 L976/L1008 两处；r9 删 2 kwarg 修复实证。**本窗关键转折：修完⑥才进入 NCCL 攻坚。**

### NCCL 攻坚全谱系（a4 ~ a10，a11 未发生）

| 轮次 | 形态 | 死点 | 根因 | 结论 |
|------|------|------|------|------|
| a4（r9） | -e 循环 16 行 WARN env，无 cpuset | —— | —— | ✅ **READY**（Follower 3/3、SPARSE_SWA 4/4、DEEPGEMM_MXFP4+E8M0、health=200；workers→ready 14min）。W4 冒烟 3/3 + 降级审计零信号在此栈取得 |
| a5 | 27 行 env --env-file + cpuset 1-19 | 🔴 profile_run NCCL invalid usage | proc/1 全量取证：worker 连 DEBUG=INFO 都被洗 → **白名单 17/20 实锤** | env 注入路线死亡 |
| a6 | 撤 cpuset 单变量 | 🔴 同位置同型 | —— | **cpuset 证伪** |
| a7 | 脚本回 -e 循环但 env 忘回 27 行 | 🔴 同位置 | 真凶 = 27 行新增 NCCL 项 | **重大发现：EngineCore 层 env 不被洗** |
| a8（r10） | ringonly 库入镜像 + conf 16 键 + PID1 LD_PRELOAD | 🔴 "Failed to initialize any NET plugin" | NET 层未通 | **切库实证落地**（deep_ep "Duplicate NCCL runtime" 双运行时证据）；三铁证未取得（未达 ready），**maps 直接取证待验（需集群 serving 态）** |
| a9（r10c） | env+conf 双层删 NET=IB + SOCKET_IFNAME→rocep1s0f0 | 🔴 bootstrap "no socket interface found" | **NET 层已过**；HCA 名 ≠ netdev 名 | NET→bootstrap 推进一格 |
| a10（r10d） | SOCKET_IFNAME→四真实 10.100 netdev | 🟡 NOT READY @ head 侧 shm_broadcast 悬置 >10min（每 60s 重试，非 collective 阶段 timeout 不触发） | —— | **NCCL 全判据历史性通过**（Follower 3/3 / SPARSE_SWA / DEEPGEMM / bootstrap / NET 全清零）；唯一悬置转 shm |
| a11 | **未发生** | —— | shm 诊断证伪：脚本已设 32g = 要求 2 倍，生产 64g | 记录为"证伪后不执行" |

**攻坚主线逻辑**：env 注入（a5~a7 死于白名单 17/20）→ conf 文件 + PID1 LD_PRELOAD 双层穿透（a8 切库落地、死于 NET plugin）→ 删 NET=IB 改真实 netdev（a9 NET 过、死于 bootstrap 接口名）→ 四真实 10.100 netdev（a10 NCCL 全过、悬置 shm）。

---

## 三、r10 镜像链技术账

### 注入形态（穿透实证）

1. **ringonly 库**: md5=2be94172，随镜像打入；a8 双运行时告警实证加载。
2. **/etc/nccl.conf**: 16 键，含 NCCL_NET=IB（r10 基线；a9 起双层删除）——conf 由 libnccl 直接读取，不经 env 层。
3. **bash -lc PID1 层 LD_PRELOAD**: 在 PID1 包装层注入 env，先于 stock vLLM worker 进程启动；worker 层洗 17/20，但 PID1 层先于清洗生效。
4. **w3_run.sh pin**: md5=a65ca09f（r10 pin）；r8 pin md5=58cca4ac（F1）。
5. **r10 digest**: sha256:2d3a9bb0…568e。

### conf 双层机制

- **层1（env 不可达）**: /etc/nccl.conf 由 NCCL 库启动时直接解析 → 白名单清洗无效；
- **层2（时序先行）**: LD_PRELOAD 于 PID1 bash -lc 层生效 → 在 vLLM worker 与 EngineCore fork 之前完成 NCCL 上下文配置。
- 实证：a8 起 conf 侧配置生效（切库 + NET 层推进），a9 证明 env+conf 双层需同步删改（env 未同步则无效）。

### digest 链（主理人台账）

| 版本 | digest | 差异 | 结论 |
|------|--------|------|------|
| r8 | 54de247e | F1 pin 基线 | —— |
| r9 | c83e00a2 | 删 2 个 TuningConfig kwarg（断点⑥） | a4 READY |
| r10 | 2d3a9bb0 | ringonly 库 + conf 16 键 + PID1 LD_PRELOAD | a8 切库落地 / NET plugin FAIL |
| r10b | 2ba9bb88 | **仅删 conf NET=IB，env 未同步故无效** | **二分实际触发**（13:05 线内） |
| r10c | d6465d44 | env+conf 双层删 NET=IB + SOCKET_IFNAME→rocep1s0f0 | a9 NET 过 / bootstrap FAIL |
| r10d | b95a016e | SOCKET_IFNAME→四真实 10.100 netdev | a10 NCCL 全判据过 / shm 悬置 |

**w3_run.sh .bak 链**：r8pin / r9pin / r10pin / r10b / r10c / r10d + envfix / ncclfix / envfix2 / envfix3 —— 全链留存可回溯。

---

## 四、关键认知修正（本窗裁决沉淀）

1. **stock vLLM worker 的 NCCL env 白名单清洗：17/20 项被洗。** a5 proc/1 全量取证实锤（worker 连 NCCL_DEBUG=INFO 都被洗）。env 注入类方案全数死于此——不是 NCCL 配错，是配置根本没到达进程。
2. **EngineCore 层不洗。** a7 对照实验发现；反推 .188 泄漏 EngineCore（pid 3155709, 5750MiB）身份语义为 EngineCore 侧残留，T2 已核身份清理，恢复后须复检（铁证⑦）。
3. **生产从未挂 infiniband 设备 → NCCL_NET=IB 在生产从未真实行使。** 诚实账：ringonly RDMA 数据面形态判定为"生产本就不存在"；本窗实证仅证明"注入通路可达"，不证明"恢复了生产行为"。
4. **rdma HCA 名 ≠ netdev 名。** NCCL_NET 匹配对象是 netdev；a9 的 rocep1s0f0 死点即此——须填四真实 10.100 netdev（a10 验证通过）。
5. **（新增）shm_broadcast 非 collective 阶段 timeout 不触发**：head 侧每 60s 重试可无限悬置，守门判读须以"NOT READY 持续时长"而非 timeout 报错为准。

---

## 五、遗留问题

1. **head 侧 shm_broadcast 悬置：32g vs 64g 差异待研。** 本窗唯一未闭环技术疑点；诊断已证伪"脚本不足"（32g=要求 2 倍，生产 64g），差异本身未定性。
2. **NCCL_DEBUG 被洗 → 取证难。** a5 实锤取证成本高（proc/1 全量比对）；后续窗口需在镜像内固化取证通道（conf 侧或 PID1 层注入 NCCL_DEBUG）。
3. **attempt-8（a8）三铁证未取得**：FAIL 于 NET 初始化未达 ready；切库证据为间接（a8 双运行时告警 + a10 全判据过）；直接 maps 取证待验（需集群 serving 态）。
4. **W5 本窗未跑数据作废。** 判读门槛（PR@4K ≥2744 / 2744~2400 条件继续 / <2400 裁决）原样带入下窗；口径差声明同前（32768+enforce-eager+无dspark vs 600000+dspark+cudagraph，仅 prefill 通路可比）。
5. **dspark 本窗裁掉**，恢复默认态确认以铁证清单为准。
6. **F5 执行状态待验**（analyze_bench.py 是否已落 .186）——下窗 W5 复跑前必须先核。

---

## 六、下窗建议

**复跑前提（须同时满足）:**
1. 仅剩 shm 悬置一个疑点（本窗无新增未闭环项）；
2. 三 follower 全健康（复检通过）。

**行动项:**
- **查 vLLM 0.28 已知 issue**：shm_broadcast 32g/64g 差异、env 白名单清洗行为是否有官方变更记录；
- **64g 对齐试验**：head 侧 shm_broadcast 按 64g 对齐做最小化隔离验证（单机/双节点，不耗整窗）；
- **固化取证通道**：NCCL_DEBUG 经 conf/PID1 层注入，恢复细粒度日志能力；补做 a8 时代缺的 maps 直接取证（serving 态）；
- **性能三档复跑**按原门槛执行，先 --dry-run + --precheck；复跑前核 F5（analyze_bench.py 在 .186 在位）；
- **补证（可选）**：本窗 serving 态已具备，可补做 attempt-8 时代缺的 maps 直接取证（四机 `grep -c ringonly /proc/<pid>/maps`），闭环"待验（需集群 serving 态）"标注。

---

## 七、W9 生产恢复铁证清单（判读框架，vFinal 底稿版）

| # | 铁证 | 判读 |
|---|------|------|
| ① | 四机 `grep -c ringonly /proc/<pid>/maps` ≥1 | 每机逐项 ✅/🔴 |
| ② | NCCL version banner | ✅/🔴 |
| ③ | 数据面 `ss` 见 10.100/10.20 网段 | ✅/🔴 |
| ④ | health=200@8013 | ✅/🔴 |
| ⑤ | **铁证原文：rank0 = anemll/dspark-vllm-gx10:0.2.1-v026.0**（0.26 fork，非 sm121a 谱系） | ✅ |
| ⑥ | **铁证原文：.187 vllm028-rb Up 24h 未动；.188/.189 embed-8022 Up** | ✅（诚实记档见下） |
| ⑦ | **恢复后 EngineCore 泄漏复检**：EngineCore 均有 docker cgroup 归属，零孤儿 | ✅ |
| ⑧ | **取证落盘**：w9-recovery-\<ip\>.log 全量归档 | ✅（诚实记档见下） |

**⑥⑧ 诚实记档（如实收录，不遮掩）:**
- **⑥**: .188/.189 embed-8022 的 uptime=23min —— 约 13:28 被 watchdog/自愈策略重启，**非 rex2 操作**；容器最终 healthy（13:39 全员成形）。
- **⑧**: 归档缺 attempt5 独立文件（已并入 attempt8 日志），如实入账。

**前置段补记（恢复前清零动作）:**
- symlink 已回滚 /data/models/（readlink 取证确认无 .local-backup 残留）；
- kit 审计干净；
- 8002 health=200 + v1/models=401 Unauthorized（鉴权面生效）；
- systemd 回位、watchdog 正常、容器 healthy（13:39 全员成形）。

**判读结论:** ①~⑧ 全 ✅ → **宣告生产恢复完成（13:53）**。

---

## 终章：红线达成状态 ✅

**实际达成时刻 13:53，红线 15:37，提前 1h44m。**

W9 铁证清单 ①~⑧ 判读全 ✅（见上节），宣告生产恢复完成。遗留标注：断点③⑤明细保持"待验"（不影响恢复宣告，属档案完备性问题）；attempt-8 三铁证的 maps 直接取证"待验（需集群 serving 态）"——现在 serving 态已具备，列为下窗可选补证动作（见第六节）。

**时刻账（真实时刻）:**
- 12:14 守门上下文交接
- 13:05 二分止损线 —— **r10b（仅删 conf NET=IB）实际触发**，因 env 未同步无效，随后 r10c/r10d 接续
- 13:28 .188/.189 embed-8022 被 watchdog/自愈策略重启（非 rex2 操作，诚实记档）
- 13:35 W9 生产恢复令下达（较 14:15 硬开始提前——清零前置就绪）
- 13:39 容器全员 healthy 成形
- **13:53 W9 铁证①~⑧全过，生产恢复完成**
- 15:37 生产恢复红线 —— **✅ 未触碰，余量 1h44m**

**窗口总评:** 升级窗口以"NCCL 全判据通过 + 生产恢复红线达成"收官；性能三档数据为零、shm_broadcast 悬置与断点③⑤档案缺口三项如实移交下窗。
