# B窗1（V5→V5b 切换 + guard 重启链修复）运维复盘报告

- **事故编号**：INC-BW1-20260907-RESTART
- **日期**：2026-09-07（B窗1 停机窗口 20:23–21:05 北京时间 = 12:23–13:05 UTC）
- **撰写**：SRE Rex（engineering-bwindow1-audit）
- **性质**：运维复盘（含四项遗留核查 + SEV 复评），全程只读取证，未做任何生产变更
- **生产现状（取证时 13:44 UTC）**：四机容器 `vllm-tp4-rank{0,1,3,2}` 全部 `Up (healthy)`，8001 `/v1/models` 返回 200，daily-smoke 11:03 UTC OK，GSM8K10 10/10（窗口收口报告口径）。**无未收口生产风险；行动项中无 P0。**

---

## 一、事故时间线（UTC，证据链）

| 时间 | 事件 | 证据 |
|---|---|---|
| 02:56–03:46 | 前置窗口：gateway v1→v2 切换（concurrency-proxy-v2 rc3.3），verify1–4 全 PASS，watch 6/6 稳定 | `~/w6-kit/gateway-v2-switch-20260907-rex.log` |
| 11:03:31 | daily-smoke 最后一次窗口前运行 OK（status=200, finish=stop） | `journalctl -u daily-smoke` |
| 12:24:13 | head start 脚本改 V5b tag（`.bak-v5b-20260907` 留档） | `stat start_tp4_head_v043.sh` mtime |
| 12:24:44 | `systemctl stop vllm-tp4-head`（窗口开始，停现役栈）。**dump #122444 = 此干净停止的 ExecStopPost 产物**（inspect: State=running→stop、ExitCode=0、日志以 12:24:34 正常流量结尾，**非崩溃**） | journalctl + `crash-dumps/crash-20260907-122444-354025118/docker-inspect.json` |
| **12:24:48** | **重启失败①（guard v2 单元名误选）**：`vllm028-tp4-head.service`（**旧单元，文件仍在盘，disabled 但可 start**）被启动——grep 探测旧单元文件存在 → 误选旧名 → 新单元 `vllm-tp4-head` 从未被 start | journalctl: `Started vllm028-tp4-head.service` |
| 12:24:51 | 旧单元的 monitor（同名脚本）创建容器 vllm-tp4-rank0（V5b + **A2 首版补丁**） | journalctl monitor 输出 |
| **12:28:28** | **重启失败②（A2 首版 rope 改动崩溃）**：Worker_TP0 → `fused_inv_rope_fp8_quant.py:189 assert cos_sin_cache.dtype == torch.float32` **AssertionError** → EngineCore failed to start → 容器 Exited(1)。rope_type 改动破坏 fp32 契约（与 code-review A2-3 预警的 <MGMT_OCTET> 行断言完全吻合） | logdump `vllm-tp4-rank0.log` L21785–22030（两次崩溃同因） |
| 12:35:56 | monitor warmup 10min 未就绪（引擎已死）→ exit 1 → 旧单元 Failed → ExecStopPost 产出**空壳 dump** #123556（docker-logs 116B：`vllm028-tp4-rank0` 容器根本不存在） | journalctl + crash-dumps |
| 12:36:11–16 | 旧单元 `Restart=always` 15s 自动重启（counter=1）与操作者手动 `stop vllm028-tp4-head` **叠跑**——**重启失败③（guard 首版无 flock 互斥）**：手动链/自动链/窗口脚本并发，容器被反复重建（12:24:51 / 12:36:15 / 12:36:20 / 12:47:21 四次创建） | journalctl（Started 与 Stopping 相隔 1s） |
| 12:39:25 | A2 首版崩溃复发（EngineCore pid=166，同一 AssertionError） | logdump L22285–22530 |
| 12:47:00–13:03:33 | 旧单元失败-重启循环尾段，空壳 dump #124700 / #124841 / #124914 / #130333 | journalctl + crash-dumps |
| **12:49:18** | **fix2 重建成功**：现役容器 StartedAt=12:49:18，镜像 `LuZ0.4.5-…-Ring-V5b`（A2 改为只设 `apply_yarn_scaling=False`） | `docker inspect vllm-tp4-rank0` |
| 13:28:07 | head `w6_env.txt` 追加 `VLLM_DSPARK_MARKOV_REPL=0` 护栏（41 变量，md5 b4ae0340；B1 审计裁定） | `stat` + `diff .bak-guard-20260907` |
| ~13:05 后 | 窗口收口：四机 healthy、GSM8K10 10/10、head/timer/proxy/daily-smoke 全 enabled | 本次核查终态 |

> 说明：12:47–13:03 段落的单元级归因部分为推断（journal 粒度所限），但"旧单元循环 + fix2 于 12:49:18 接管"两条均有直接证据。

## 二、影响范围

- **服务中断**：12:24:44–12:49:18 ≈ **25 分钟**推理不可用（8001 proxy 存活但后端引擎崩溃；8002 直连本就收敛）；至 13:05 完全收口共约 40 分钟窗口。
- **数据面**：无状态推理服务，无数据丢失；GSM8K 评估在 fix2 后完成。
- **副作用**：9 个取证 dump 落盘（1 个有效 + 6 个空壳 + 2 个窗口前置），logdump 产生新 `vllm-tp4-rank0.log`。
- **波及面**：仅生产 TP4 栈本身；gateway-v2 切换（凌晨窗口）不受影响。

## 三、SEV 评级与无人值守复评

**实际评级：SEV3**（受控维护窗口内的次要故障，操作员在场，25 分钟内恢复）。

**无人值守爆炸半径复评（假设三次失败发生在无操作员场景）**：

1. **自愈链不会收敛**：A2 崩溃是确定性 bug（断言必炸），`Restart=always 15s` + `vllm-healthcheck.timer`(60s) + `healthcheck_hardened FAIL=1`→重建判定，全部指向**重建同一坏状态** → 崩溃循环。节流上限 = 单元 `StartLimitBurst=20/1800s`。
2. **不会"误自愈到更坏状态"**，四个闸门均验证有效：
   - `healthcheck-rebuild.sh` 内**无任何单元名逻辑/无 vllm028 引用**（grep 证实），不存在误选旧单元路径——单元误选只发生在操作面的 guard v2，不是自愈链；
   - monitor guard 互斥（docker ps 跟随等待）防双栈并发拉起抢端口；
   - guard v3 D2 fail-fast：TCPStore 120s 不监听 → 停 head → exit 2，杜绝分裂集群；
   - worker monitor 的 head 健康门禁已改探 8001/ping：引擎死时 /ping 失败 → 不会误触发"head 健康+集群成形但本 rank 缺失"分支去重建 head。
3. **唯一失效面 = 感知**：崩溃循环期间唯一的"防无限循环"机制是 StartLimit 节流，**无任何告警闭环**（healthcheck 连续 FAIL 不告警）。无人值守场景等效于静默降级>15min，按定级标准应为 **SEV2**。
4. **结论**：现行自愈链"fail-safe 但 fail-silent"。必修项：healthcheck 连续 FAIL 告警（行动项 P1-5）。

## 四、根因（5 Why）

### 链 A：为何 guard 首版无 flock（叠跑互踩）

1. 为什么容器被反复重建？→ 手动 `systemctl stop` 与旧单元 `Restart=always` 自动重启、窗口脚本并发执行。
2. 为什么并发无人拦截？→ guard 首版没有全局互斥锁。
3. 为什么没有锁？→ 脚本按"单操作员、串行窗口"假设编写；systemd 自动重启链与手动链并发这一场景未进入设计输入。
4. 为什么场景缺失？→ 此前 W9-R8 已发生过"后台恢复链与手动链叠跑"事故（guard wrapper 注释自证），但修复（flock）只挂在**事后**的 wrapper（`w9r4_restart_guard.sh`），窗口切换当时执行的仍是未包 guard 的裸链。
5. **流程根因**：**重启原语的互斥不是默认内置，而是依赖调用方记得包一层 guard**——"安全默认值"缺位。→ 已修：wrapper flock `/var/lock/w9r4-restart.lock`（等锁 20min，超时 exit 3）；预防措施见 §七。

### 链 B：为何单元名用 grep 探测而非固定白名单

1. 为什么新单元从未被 start？→ guard v2 选名逻辑探测到旧单元文件存在 → 选择了 `vllm028-tp4-head`。
2. 为什么会探测旧单元？→ 2026-09-07 容器/单元更名（vllm028-* → vllm-*）采取"新名优先 + 旧名回退"兼容策略，回退判定信号 = "旧单元文件是否存在"。
3. 为什么旧单元文件在盘？→ 更名时旧单元仅 `disabled` 未 `mask`，保留作"回退"。
4. 为什么回退信号错了？→ "文件存在"≠"单元现役"；disabled 单元永远可被 `start`，该信号在更名后**必中旧名**。
5. **流程根因**：**更名/迁移操作没有"旧入口必须封死（mask）+ 现役名固定白名单"的配套纪律**；兼容回退层把一次性的历史包袱变成了现网活性风险。→ 已修：v3 固定 `UNIT_HEAD=vllm-tp4-head`（脚本 L15–17 已写入教训）；遗留旧单元文件仍在盘 → 行动项 P1-2（mask）。

### 附：A2 首版崩溃（链上第三个根因，工程侧已闭环）

rope_type 改动 → cos_sin_cache dtype 偏离 fp32 → `fused_inv_rope_fp8_quant.py:189` 断言崩溃。该断言正是 code-review（A2-3）预警的 fp32 契约点；fix2 改为只设 `apply_yarn_scaling=False` 后恢复。**流程教训**：触碰 rope/dtype 的补丁，其契约断言清单应作为窗口 precheck 显式执行（模拟加载/首 token 探针）而不是靠重启验证。

## 五、四项遗留核查结果（含命令与原始输出）

### a. monitor 容器名与 8002 探针 —— ✅ 达标，探针已改 8001 且验证可达

- 现役 monitor 脚本全量 grep `vllm028`：**零功能残留**（仅注释与 stop-both 语句有意保留旧名）。
  - head `monitor_tp4_head_v043.sh`（d48e8b9a）：`NAME=vllm-tp4-rank0`；
  - worker `monitor_tp4_worker_v043.sh`（7e27c2df，02/03/04 与 head 副本**四方一致**）：`NAME="vllm-tp4-rank${NODE_RANK}"`，L18 **已改为 `http://<NODE_IP>:8001/ping`**；
  - unit：`ExecStopPost=<INSTALL_DIR>/scripts/crash_dump.sh vllm-tp4-rank{0..3}`（新名）；timer：vllm-healthcheck.timer / daily-smoke.timer 均新名体系；crontab 无 vllm 相关条目。
- **8002 收敛实证**（node0X）：`curl <NODE_IP>:8002/health` → `000`（不可达）；`curl <NODE_IP>:8001/ping` → `200`。
- **结论与建议**：改探 8001 **必要且正确**——若维持 8002 探针，worker 侧"head 健康门禁"将永久失效（HCODE 永不为 200，触发 head 重建的分支成死支）。遗留观察项：/ping 经 proxy 透传到引擎，需确认不占用 `MAX_CONCURRENCY` 排队名额（proxy_v2 路由表中未显式定义 /ping，走通用透传）；另 head monitor L11–12 正则 `(vllm-tp4-rank|vllm-tp4-rank)` 为 sed 更名产生的重复分支，功能等价、建议清理（P2）。

### b. 陈旧 crash-dump 归类 —— 12:24 唯一有效，其余 6 个为根因②空壳

| dump | container 名 | docker-logs | 判定 |
|---|---|---|---|
| crash-20260907-122444 | vllm-tp4-rank0 | 2.4MB | **有效**：窗口开始停栈的 ExecStopPost 产物（running/ExitCode0，非崩溃），含 V5 期完整运行日志（404 探针、SpecDec 指标）→ **归档保留**（切换前基线证据） |
| 123556 / 123616 / 124700 / 124841 / 124914 / 130333 | vllm028-tp4-rank0 | 116B（空） | **根因②空壳 dump**：旧单元循环期间 ExecStopPost 指向不存在的旧名容器 → 时间戳佐证价值已入本报告，**可归档清理** |
| crash-20260907-060911 / 062513、crash-20260906-* | — | — | 窗口前置/前日产物，超出本窗范围，按 ADR-20260906-CKPT1 保留策略统一处理 |

- **A2 首版崩溃没有独立 crash_dump**（崩溃发生在新容器上，dump 证据在 logdump `vllm-tp4-rank0.log`）——取证链覆盖盲区：**容器级崩溃（docker rm 后日志随容器消失）依赖 logdump daemon 兜底**，本次兜底成功；建议将此依赖关系写入 runbook（P2）。

### c. guard 脚本一致性 —— ✅ 达标（术语澄清见下）

- head `w9r4_window_restart.sh` = **517c4c0e** ✅（= 任务口径 v3）；
- **flock 互斥在 wrapper** `w9r4_restart_guard.sh`（cf87d405）：`flock /var/lock/w9r4-restart.lock`、等锁 1200s、EXIT 释放 → 调用 window_restart.sh。链路已通读验证（D2 fail-fast L38–44、固定 `UNIT_HEAD="vllm-tp4-head"` L17 均在位）；
- worker 侧单元执行脚本 `monitor_tp4_worker_v043.sh` 四机 md5 一致（7e27c2df）✅；
- 注意点：worker 三机上残留的 `w9r4_window_restart.sh` 副本为旧版（cdc0fd23），但 worker 不执行它（操作面脚本，仅 head 使用）——P2 清理防止误用。

### d. w6_env 一致性 —— 文件达标 ✅；发现两处真实漂移（默认关语义下无暴露）

- head `~/w6-kit/w6_env.txt`：**41 生效变量、md5 b4ae0340 ✅、L61 `VLLM_DSPARK_MARKOV_REPL=0` ✅**；`bak-guard-20260907` = **1e096536 ✅**；`diff bak-guard 现役` 仅差护栏块（5 行注释+1 行变量）。
- **容器 env 逐项比对**（rank0 与 rank1 全量，rank3/rank2 关键项抽查）：40/40 变量名值**零漂移**；extra 项（VLLM_BUILD_*/VLLM_IMAGE_TAG/FLASHINFER_CUDA_ARCH_LIST 等）为镜像烘焙/运行时注入，四机同构，无异常。
- **漂移①（护栏未进容器）**：四机容器 env 中均**无** `VLLM_DSPARK_MARKOV_REPL`——护栏行 13:28:07 加入，容器 12:49:18 启动，**文件护栏 ≠ 容器生效**。当前默认关语义（env 未设 → replicate=False）下**无暴露**，但下次 head 重建才会吸收；workers 因漂移②则**重建也不会吸收**。
- **漂移②（worker w6_env 未同步）**：02/03/04 的 `w6_env.txt` 均为旧版 **1e096536（40 变量、无护栏行）**，与 head b4ae0340 不一致 → 行动项 P1-1。
- **漂移③（head 副本过期）**：head 上的 `start_tp4_worker_v043.sh`（7d6f9dec）镜像 tag 仍为 **Ring-V5**，而 worker 实际执行副本（31d60685，02/03/04 一致）已指向 **Ring-V5b**——若有人从 head 分发恢复 worker，会拉起旧镜像 → 行动项 P1-3。

## 六、行动项分级

**P0（阻塞生产）：无。** 四机 healthy、护栏默认关语义无暴露、自愈链 fail-safe 闸门齐全。

**P1（本周期内）**：

| # | 行动 | 命令要点 | 预期 |
|---|---|---|---|
| 1 | 同步 w6_env 至三台 worker | `scp node0X:~/w6-kit/w6_env.txt node0{2,3,4}:~/w6-kit/` 后 `md5sum` 四机核对 = b4ae0340 | 下次 worker 重建可注入 MARKOV_REPL=0 |
| 2 | **mask 旧单元**（根因②结构性闭环） | head: `printf '<PASSWORD>' \| sudo -S systemctl mask vllm028-tp4-head`；workers 同理 mask `vllm028-tp4-worker`（逐步执行验证） | `systemctl is-enabled` = masked；任何 `start vllm028-*` 直接失败 |
| 3 | 修正 head 副本 worker start 脚本镜像 tag | 以 worker 版（31d60685）覆盖 head 副本，或改 L20 R5=…-V5b，md5 备案 | head 副本与 worker 执行版一致，防误分发旧镜像 |
| 4 | disable 并存的 proxy v1 | `sudo systemctl disable concurrency-proxy.service`（当前 v1 inactive/v2 active，均 enabled → 重启后 :8001 竞争风险） | `is-enabled v1 = disabled` |
| 5 | 无人值守告警闭环 | healthcheck_hardened 连续 FAIL≥3（3min）→ 告警通道（配合 testing-expert 验证判定阈值） | 崩溃循环 3 分钟内可感知（SEV2 级场景的兜底） |

**P2（择机）**：

| # | 行动 | 说明 |
|---|---|---|
| 6 | 清理 `w9r4_window_restart.sh` L49 `… \|\| systemctl start vllm028-tp4-worker` 旧名回退 | 与 L15 教训注释自相矛盾；顺手修头注释 30x30s→40x30s |
| 7 | monitor 正则重复分支 `(vllm-tp4-rank\|vllm-tp4-rank)` 清理 + "两代容器名"注释更新 | sed 更名痕迹，功能等价 |
| 8 | 6 个空壳 crash-dump 归档清理 | md5 存档入证据链后删除 |
| 9 | sudo 口令卫生（code-review S-1 延续） | sudoers NOPASSWD 白名单限 `systemctl start/stop vllm-*` |
| 10 | `vllm_logdump.sh` 旧名引用确认 | 老文件 `vllm028-tp4-rank0.log` 已停更（06:25），确认 logdump 是否需双名采集过渡期 |

## 七、预防措施

1. **重启原语安全默认**：flock 互斥内置于 window_restart.sh 本体（而非依赖 wrapper 包装）；任何新增重启入口必须先过 guard。
2. **更名/迁移纪律**：旧入口一律 `mask`（disabled ≠ 封死）；现役单元名固定白名单常量；更名后 48h 内全量 grep 残留审计（含 unit/bak 单元/crontab/脚本）。
3. **env 变更生效纪律**：w6_env.txt 修改 ≠ 容器生效；文件头标注 `pending-restart` 状态或维护"文件版 vs 容器生效版"双 md5 台账，与下个维护窗口滚动合并。
4. **崩溃取证补盲**：crash_dump.sh 对"容器不存在"场景跳过落盘（消空壳噪音）；容器级崩溃以 logdump daemon 为权威兜底，写入 runbook。
5. **契约断言前移**：触碰 rope/dtype/数值路径的补丁，把 fp32 等契约断言检查做成窗口 precheck（容器内模拟加载 + max_tokens=1 探针）后才进入全链重启。
6. **自愈链"可收敛"验收**：新镜像/新补丁窗口必须演练"确定性故障注入→确认自愈链行为符合预期（收敛或告警）"，禁止只验证 happy path。

## 八、证据索引

- journal：`journalctl -u vllm-tp4-head -u vllm028-tp4-head --since "2026-09-07 12:20" --until "13:10"`（单元启停全时序）
- 崩溃证据：`<INSTALL_DIR>/backup/vllm-logdump/vllm-tp4-rank0.log` L21785–22030、L22285–22530（AssertionError 全栈）
- dump：`<INSTALL_DIR>/backup/crash-dumps/crash-20260907-*`（context.txt / docker-inspect.json / docker-logs.txt 尺寸）
- md5 台账：w9r4_window_restart.sh=517c4c0e、w9r4_restart_guard.sh=cf87d405、monitor_tp4_worker_v043.sh=7e27c2df（四机）、monitor_tp4_head_v043.sh=d48e8b9a、w6_env.txt=b4ae0340（head）/1e096536（workers+bak）、start_tp4_worker_v043.sh=31d60685（workers）/7d6f9dec（head 副本）
- 关联文档：`code-review-bwindow1-v5b-2026-09-07.md`（同目录，A2-3/B1 审计裁定与本次崩溃互证）

> 复盘原则声明：以上时间线与根因聚焦系统与流程，不指向任何个人；12:47–13:03 段落单元级归因为部分推断，已在文中标注。
