# W9 · 已知问题交叉归纳表（我栈 × 上游两仓 issues）

**日期**：2026-08-29（UTC+8）
**起草**：tech-writer5（tw5 · 技术文档师，engineering-w9-optimize）· Task #34 联动派单
**用途**：rex5 S8 前修复参考——判定哪些问题"上游已修无需动作 / 上游未修需我栈自防 / 仅我栈独有需自研闭环"
**方法**：WebFetch 两仓 issues 现势状态（2026-08-29 快照：标题+状态+标签级交叉，未逐条通读正文全文）× `w9-port-assessment-2026-08-28.md`（archi5）裁决联动 × 我栈 W6/W7/W8 报告已知问题
**上游 A 仓**：luxingcom/LuZ0.3.1——**GitHub issues 为 0 条**（`q=is:issue` 无结果）；其问题沉淀走 `docs/04-issues/` 缺陷处置文档形态（非 issues 体系），交叉以文档为准
**上游 B 仓**：MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark——issues 活跃（2026-08-28 仍有新开 #154）

---

## 表 1 · 派单指定 12 项逐一交叉（#21~#141）

| # | 标题（缩略） | 上游状态 | 我栈裁决（archi5 评估） | 三类归类 | S8 行动 |
|---|---|---|---|---|---|
| #21 | encode_arguments dict 工具参损坏 | **已修**（closed 8-11） | checkpoint 级文件、版本无关；复现一试便知 | 上游已修 | P2：冒烟即验，无预动作 |
| #22 | nvfp4_ds_mla 长上下文 decode 劣化 | **已修**（closed 8-11） | **0.28 不适用**：SM12x KV 白名单仅 fp8_ds_mla，我栈不触发 | 上游已修（对我栈=免疫） | 无 |
| #26 | prefix cache 32K×8/62K×8 崩塌 | **已修**（closed 8-13） | **0.28 原生已含**：`VLLM_PREFIX_CACHE_RETENTION_INTERVAL`（diff-matrix P5 ✅） | 上游已修 | 无（env 迁移即可） |
| #27 | x8 并发 decode 饿线 | **已修**（closed 8-12） | 0.27 已移除 `max_num_partial_prefills`（#49244）语义重构，**需重验再定** | 上游已修（0.28 面需重验） | P2：语义重验 |
| #31 | thinking_token_budget / V2=0 破 dspark | **已修**（closed 8-13，v2 补丁；后传 #66 悬崖复现已再修） | 0.28 有 reasoning-effort（#50580）但 budget 字段支持未见 | 上游已修（0.28 面待验） | P2：按功能需求再验 |
| #43 | #27 修复后 32K/62K 冷车道仍不公平 | **不修**（skipped 8-13；关联 #45 enhancement 仍 OPEN） | 长档并发 ≤c3 认知固化已在我栈（v027 D5）， fairness 非我栈主战场 | 上游未修（官方放弃，转 #45 跟踪） | 观测项，不设修复动作 |
| #55 | 工具调用截断 finish_reason=length + 非法 JSON | **已修**（closed 8-14） | 0.28 原生 tool-call-parser 行为需冒烟 | 上游已修（0.28 面待验） | P1：5min 冒烟（带截断的工具请求） |
| #79 | shm 读端单核自旋烧 CPU（spin-wait） | **B 仓已修**（closed 8-19，busy_loop_s 1s→2ms）⚠️ **vLLM 0.28 未含**：v0.28.0 tag 源码实证默认 1s 在位、无 env 控制 | 我栈"AR stall=单核压栈"**同族**；TP2 实证有害，TP4 争核面更大 | **上游未修（vLLM 0.28）** | ⭐ P1：一行级移植 + A/B（判据 decode TPOT/AR stall 频率） |
| #133 | Triton 指针对齐重复特化（#117 族） | **已修**（closed 8-25，commit 1fec5b78） | 0.28 修复状态**无证据两侧**（待验） | 上游已修（0.28 面待验） | P2：混合 prefill 负载数 Triton compile key，或 diff 源码销案 |
| #136 | MTP+xgrammar livelock（vLLM #52805） | **已修**（closed 8-28，回移上游） | 大概率已含 0.28（#52805 与已收录 #52816 同号段，号段推断） | 上游已修（待一行销案） | P2：grep `backend_xgrammar.py` 快核 |
| #138 | Responses API type-less 全历史回放 | **已修**（closed 8-28） | 0.28 原生 Responses API+store；兼容形态差异需验 | 上游已修（0.28 面待验） | P2：Responses 冒烟 |
| #141 | sparse-MLA decode >64 行死锁 | **已修**（closed 8-28，64 行分片补丁）⚠️ 0.28+FlashInfer 0.6.16.post3 是否仍受限**无源码证据** | 我栈 MTP n=7×12 seq≈**96 行触发面真实**（无 MTP 时仅 12 行不触发） | **上游未修（0.28 面待验）** | ⭐ P1 观察哨兵：MTP 接入 c>1 首测；命中即移植 64 行分片 |

## 表 2 · 我栈五已知问题反向对照（我栈 → 上游）

| 我栈已知问题 | 上游对应检索结果 | 三类归类 | 我栈处置（现状/建议） |
|---|---|---|---|
| **AR stall = 单核压栈**（生产历史定位；W7 §5.1 排查项 #3 亲和面） | B 仓 **#79 同族已修**（spin-wait）但 vLLM 0.28 未含；#87（EngineDeadError 集合通信超时）不同族已修 | 上游未修（0.28） | 表 1 #79 行动：spin-wait 补丁移植 + libncclpin（NCCL→CPU8-9）pin 复核 4/4 生效 |
| **EngineCore 泄漏**（W6  (node03 管理网末段) pid 3155709/5750MiB 实证；sudo kill 处置；铁证⑦零孤儿门） | 两仓 issues 清单内**无对应 issue**（仅 #87 EngineDeadError 名称相近、机制不同） | **仅我栈独有**（诚实注记：未做 vLLM 全量上游检索，以两仓清单为界） | 处置经验已内化 runbook §9-2；恢复验收铁证⑦把关 |
| **shm_broadcast 卡死**（W6 a10 head 侧 NOT READY 无限悬置；8/26 生产 conc=16 卡死 HEALTHCHECK 未检出） | B 仓 **#143 OPEN P1**（MAX_NUM_SEQS=16 首 c=16 burst 稳定杀引擎）——与 8/26 conc=16 事故**同族**；#141 为 64 行死锁（另族）；"32g/64g 诊断差异"无对应 | 上游未修（#143 OPEN） | ① concurrency_proxy 入口限流（P1 廉价护栏，阈值勿照抄）；② healthcheck_hardened 闭合"卡死仍 healthy"盲区（P0 思路）；③ shm 悬置判读以"NOT READY 持续时长"为准（runbook §9-3 已入） |
| **901s JIT timeout**（W6 a12/a13 → attempt-14 cache 挂载+1800s 闭环） | B 仓 **#65 已修**（1800s 缓解落地）；**#117 OPEN P0**（**mid-serve** Triton JIT 仍拖垮 600s watchdog——#65 缓解覆盖不了 mid-serve 场景） | 上游未修（mid-serve 面 #117 OPEN） | 我栈主缓解=三 JIT cache 持久卷（P0，与 rex5 持久化项合并）；NCCL Flight Recorder 四件 env 为超时取证利器（P1） |
| **PerSizeTuner host 平面 3/4 口枚举失效**（W9 发现，细节待留证） | **无对应**——PerSizeTuner 为我栈自研 ringonly 补丁逻辑（strings 铁证 `PerSizeTuner`/`ncclPersizeTunerOverride`），上游 NCCL 与两仓均无此物 | **仅我栈独有**（自研补丁面，上游无从修复） | 修复责任在我栈：rex5 留证（枚举路径/host 平面日志）→ 补丁侧闭环；host 平面回退路径=conf 层静态四口名单兜底 |

## 表 3 · 表 1 之外新发现的高相关 OPEN issues（增量，S8 触发面核对）

| # | 标题（缩略） | 状态 | 与我栈触发面交叉 | S8 建议 |
|---|---|---|---|---|
| **#115** | perf backports #50004/#49486 在 **MTP+APC+CUDA graphs** 下间歇静默输出损坏（引 vLLM #51318/#52492） | **OPEN P1** | 新生产形态 = MTP n=7 + cudagraph 十六档 FULL（+APC 待核对）**同构触发面**；且 GSM8K 历史锚数值恰来自 #50004 body（acc≈0.9492） | ⭐ **S8 必做**：① 核对新生产是否启用 prefix-caching（APC）；② GSM8K-20 + quality_gate 抽验作为输出正确性第一道网；异常即对照 #51318/#52492 特征 |
| **#117** | mid-serve JIT 拖垮 600s watchdog，TP 对死亡 | OPEN P0 | 见表 2·901s 行 | 三 cache 持久化主缓解；Flight Recorder 备取证 |
| **#143** | seqs=16 + c=16 burst 杀引擎 | OPEN P1 | 见表 2·shm_broadcast 行 | 入口限流 + hardened 健康探针 |
| **#146** | ConnectX-7 PCIe fatal AER recovery 软锁 head | OPEN P0 | 我栈同为每机 2×CX7 拓扑，硬件风险共享 | 主机侧监控项；preflight_roce_gid 只读预检照常；无软件修复可移植 |
| **#32** | 单发 256K 冷 prefill 硬复位 GB10 head | OPEN P0 | 我栈 max_model_len=600000 且 LuZ0.3.1 曾实测 400K PASS——差异因子疑为我栈时钟限频（gb10-clock-cap）+8192 分段 | 深档冷 prefill 压测前预告自愈链；限频服务勿在压测窗动 |
| #144 | reasoning_effort high/max 打破 prefix cache（0% hit） | OPEN P2 | 0.28 原生 reasoning-effort；新生产若开放该参数需知悉 | 记档；产品侧确认参数策略 |
| #140 | live 混合 prefill 负载 decode 崩至 1.5–3.3 tok/s | OPEN P1 | 长档并发 ≤c3 固化已覆盖大半；观测 | 观测项 |
| #80 | 双 400K 冷 prompt 对端 prefill 时 decode 车道塌 0.69 tok/s | OPEN P1 | 同上（长档公平性） | 观测项 |
| #154 | Anemll 0.1.1 吞吐远低于宣传/间歇崩 <2 tok/s | OPEN（8-28 新开） | 基座 0.25.2.dev 问题，与我栈 0.28 基座不同代 | 不适用，仅跟踪 |

---

## 三类归纳汇总（S8 速览）

- **上游已修、我栈无需动作（8 项）**：#21/#22/#26/#31/#55/#79(B 仓)/#133/#136/#138/#141 中，#22/#26 为完全免疫，其余 0.28 面待一行级快核（grep/冒烟级）——全部进 P2 快核批，不占 S8 主线。
- **上游未修、我栈触发面真实（5 项，S8 修复/防护重点）**：① spin-wait #79（0.28 未含，一行级移植+A/B）；② mid-serve JIT #117（cache 持久化+Flight Recorder）；③ conc burst #143（限流+hardened 探针）；④ issue141 64 行边界（MTP 哨兵，命中即移植）；⑤ **#115 MTP+APC+CUDA graphs 静默损坏族（GSM8K/quality_gate 首道网，⭐ 新增必做）**。另硬件类 #146/#32 无修复可移植，转主机侧防护纪律。
- **仅我栈独有（3 项）**：PerSizeTuner host 平面 3/4 口枚举失效（自研补丁，rex5 留证→补丁侧）；EngineCore 泄漏（处置已内化 runbook §9-2）；shm 32g/64g 诊断差异（证伪后未复现，保留观测）。

## S8 灰度观察清单——五项重点验收/销案方法（一行一项，2026-08-29 team-lead 指令增补）

> 同步收录于 runbook §6.7（S8 现场两处可引，以本表为源）；命中/销案均即时回报 team-lead。

| # | 问题 | 验收/销案方法（一行） |
|---|---|---|
| 1 | **spin-wait #79**（shm 读端 1s 忙轮询烧单核，0.28 未含修复） | 销案 = A/B 两臂：基线臂与 `busy_loop_s 1s→2ms` 补丁臂各跑一轮 decode（DE c1），判据 = decode TPOT 与 AR stall 频率；补丁臂优且无回归 → 移植转正；无差 → 销案"TP4 幅度不显著"记档 |
| 2 | **issue141 64 行边界**（sparse-MLA decode >64 行死锁，0.28 面无源码证据） | 销案 = MTP 接入后首测即验：构造 decode verify 批 >64 行（12 seq×8 spec≈96 行）跑 4 轮短测，无死锁/崩溃 → 销案"0.28 路径不受限"；命中死锁 → 立即停，移植 64 行分片补丁（§2.2 出处） |
| 3 | **#117 mid-serve JIT**（推理中 Triton 重编拖垮 600s watchdog，#65 缓解不覆盖） | 销案 = 三 JIT cache 持久卷 bind 落地后：① 二次启动命中 cache 秒级（901s 族销案）；② 长跑 30min+ 混合负载 0 次 mid-serve re-JIT（日志 grep 编译行）→ 销案；复现 → NCCL Flight Recorder 四件 env 取证留档 |
| 4 | **#143 conc burst**（高并发 burst 杀引擎/shm 卡死族，8/26 生产同型事故） | 销案 = ① concurrency_proxy 入口限流上线（阈值=0.28 栈实选 max-num-seqs 对齐）；② 限流后 c=16 burst 压测一轮无 EngineDead/无 shm 悬置 → 销案"入口受控"；另 healthcheck_hardened 接入后"卡死仍 healthy"盲区闭合验一轮 |
| 5 | **#115 静默输出损坏族**（perf backports × MTP+APC+CUDA graphs，vLLM #51318/#52492） | 销案 = 输出正确性双门：① GSM8K-20 G3 过（runbook §6.6 判定语义：LuZ-0.4.3 自测 vs 上游锚 0.9492，−2% 带内 PASS）；② quality_gate 0.28 快照重建后 4/4 过；①② 双过 → 销案"本组合未触发"；任一异常 → 停灰度，核对 APC 是否启用（只读核对项）并对照 #51318/#52492 特征上报 |

> 附注：硬件类 #146（CX7 PCIe AER 软锁）/#32（256K 冷 prefill 复位）无软件销案法，转主机侧防护纪律（preflight_roce_gid 预检 + 深档压测前预告自愈链），见表 3。

## 诚实账

| # | 事项 | 状态 |
|---|---|---|
| 1 | issues 状态为 2026-08-29 WebFetch 快照（标题+状态+标签级），未逐条通读正文全文 | 声明；关键项（#79/#141/#115）判读均有 archi5 源码级证据背书 |
| 2 | 上游 A 仓（LuZ0.3.1）issues=0 条结论基于列表页查询 | 高置信（页面直证" No results"） |
| 3 | #115 的 APC 触发面："新生产是否启用 prefix-caching"未在 W8 inspect 记录中显式出现 | 待集群只读核对 |
| 4 | PerSizeTuner host 平面 3/4 口枚举失效：细节仅来自 team-lead W9 指令口径，本地报告无先例记载 | 待 rex5 W9 留证回填 |
| 5 | issue141 的 64 行边界在 0.28 FlashInfer 0.6.16.post3 是否存在：无源码证据 | 待验（MTP 接入首测即真值） |
| 6 | 表 1"0.28 面待验"各项（#31/#55/#133/#136/#138/#27）均为冒烟/一行级成本 | 与 archi5 §2.2 建议一致 |

*表完。上游状态时效以抓取时刻为准；集群真值归 rex5。*
