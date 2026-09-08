# B窗1 V5b 切换 —— 三路综合审查报告（代码审计 / QA 验证 / 运维复盘）

**日期**：2026-09-07
**工作流**：工作流 1（综合代码审查）+ 工作流 4（部署前检查要素）
**参与成员**：Cody（代码审查）/ Tessa（测试）/ Rex（SRE）/ Zhen（主理人·编排与修复落实）
**团队**：engineering-bwindow1-audit（前代 engineering-gateway-v2-upgrade 因派发绑定异常经督导批准删团重建）

---

## 📌 TL;DR（执行摘要）

- **整体结论：🟢 通过**。B窗1 切换 LuZ0.4.5-V5 → **V5b fix2**（digest sha256:bb22a8c7，四机 RepoDigest 一致，k=7 MTP）收口成立：A1/A3 审计通过、A2 有条件通过（远端核验项无阻断）、行为级 QA 全绿（A2 needle 4/4 含 500K 大关、A1 5/5、流式 3/3）。
- 严重度分布：🔴严重 0 项 / 🟠高 3 项（B1 forward 缺陷维持禁用、B2 死代码、口令卫生）/ 🟡中 5 项 / 🟢低若干。
- 本轮共发生 3 次窗口内重启失败，根因三类已全部定位并修复（flock 缺失 / 旧单元误选 / A2 首版 rope 血统切换），实际生产影响 SEV3（25min 中断，操作员在场）；无人值守复评等效 SEV2。
- **雷克斯 P1 清单 4/5 已当场落实**（w6_env 四机同步 / 旧单元 mask / worker-start 旧 tag 修正 / proxy v1 disable），全程零中断（8001 实测 200）。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（V5b fix2 维持现役，无需回退） |
| 阻塞项数量 | 0（B1 禁用护栏已在位，B2 死代码生产零暴露） |
| 关键行动项 | 4 条已落实 + 3 条待办（见行动清单） |
| 建议下一步 | SSH 稳定窗口跑科迪 §7 七条远端核验命令，收口 A2 两项数值定案 |

---

## 🔍 三路审查发现（按严重度排序）

### 科迪（code-reviewer）逐行审计 —— v5b-patch-audit-2026-09-07.md

| # | 严重度 | 对象 | 判定 | 要点 |
|---|--------|------|------|------|
| 1 | 🔴→🛡️已防护 | B1 Markov replicate | Request Changes | finalize_replication 只改权重未改 forward（VocabParallelEmbedding 按 id-vocab_start 查本地行）→ rank1-3 查错行静默数值错乱；docstring 声称的 fp32 bias 路径实际不存在。**MARKOV_REPL 保持禁用**，w6_env 护栏（b4ae0340）已在位 |
| 2 | 🟠 | B2 draft topk hook | 死代码定案 | `_apply_draft_topk_override` 补丁全新引入、只定义无调用 → `VLLM_DSPARK_DRAFT_TOPK` 旋钮完全不生效。生产零风险，但与交接预期不符，需二选一处置（补接线 / 删死码）。另注意 footgun：`isdigit()` 放行 "0"，k=0 会崩坏 |
| 3 | ⚠️ | A2 YaRN 修复 | 有条件通过 | 结构面成立（只翻 apply_yarn_scaling 布尔，不动 rope_type 类血统）；两项数值定案（dict 键集 / deepseek_llama_scaling 数学等价性）待远端核验 |
| 4 | ✅ | A1 / A3 | 通过 | A1=g1r3 白盒血统佐证的正确历史修复；A3=位级不变性逐行证实，OOB 防住 |
| 5 | 🟠 | guard v3 | 通过附意见 | fail-fast 逻辑正确；sudo 口令明文落盘 + ssh 命令行外泄面，下窗处理 |

> 口径说明：科迪本轮为静态审计（本地镜像血统逐行审查），§7 附 7 条远端核验命令。

### 泰莎（testing-expert）行为级 QA —— qa-bwindow1-v5b-2026-09-07.md

| # | 验证项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | A2 needle 30K-mid@68% | ✅ PASS | 30064 tok，ENM-8091 精确复述 |
| 2 | A2 needle 128K-end@91% | ✅ PASS | 127909 tok，RTT-0935 精确复述 |
| 3 | A2 needle 500K-mid@44% | ✅ PASS | 501096 tok（600K 上限 83%），356s prefill，AJA-1117 精确复述 |
| 4 | A2 needle 128K-start@6% | ✅ PASS（复测归因） | 首轮 FAIL=512 预算全耗 reasoning（检索正常），max_tokens=3072 复测精确输出 JPC-7165；全新 seed needle@4% 复测 BLI-5399 |
| 5 | A1 max_tokens=256 完整性 | ✅ PASS 5/5 | completion=256 全额（finish=length），/tokenize 账目差恒 1，序列严格 +1 连续零丢字 |
| 6 | 流式回归 SSE | ✅ PASS 3/3 | 无空帧/无中断（帧间隔≤0.30s）、finish_reason 正常、TTFT 0.26-0.30s |
| 7 | B2 | 不适用 | 死代码（引用科迪审计结论） |

防缓存纪律：每档独立 seed 现场生成、唯一 SN-<8hex> 串行标记、/tokenize 校准 ±2%、位置覆盖开头/中间/结尾。
**经验**：该栈 reasoning 不可经 API 关闭且不可配预算——长上下文任务生成预算需预留 reasoning 余量（512 不够、3072 充足）。

### 雷克斯（sre-engineer）运维复盘 —— incident-bwindow1-restart-2026-09-07.md

- **时间线**：12:24:44 停栈（dump=干净停止产物）→ 12:24:48 误启旧单元 vllm028（根因②）→ 12:28/12:39 A2 首版崩溃 ×2（fused_inv_rope_fp8_quant.py:189 dtype 断言，实锤）→ 12:36 手动 stop 与旧单元 Restart=always 叠跑（根因①）→ 12:49:18 fix2 接管 → 13:28 head 护栏落盘。
- **SEV**：实际 SEV3（25min，操作员在场）；无人值守复评等效 SEV2——自愈链对确定性 bug 不收敛但不会误自愈到更坏（四闸门验证有效），唯一失效面=感知（FAIL 不告警）。
- **四项核查**：容器名 ✅ 无 vllm028 功能残留；guard md5 517c4c0e ✅、worker monitor 四机一致 7e27c2df ✅；w6_env head=b4ae0340/bak=1e096536 ✅；8002 收敛实测 000 确认、8001/ping 200。
- **三处真实漂移**（均已处置或记录）：容器未注入 MARKOV_REPL（护栏晚于容器启动，默认关语义无暴露）；worker 三机 w6_env 旧版（→已同步）；head 副本 worker-start 旧 tag（→已修正）。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责 | 紧急度 | 状态 |
|---|------|------|--------|------|
| 1 | w6_env(b4ae0340) 同步至 02/03/04（旧版留底 .bak-preb4ae0340-20260907） | Zhen | P1 | ✅ 已落实（三机 md5 复核一致） |
| 2 | 旧单元 vllm028-tp4-head(worker) 移档留底 + mask（head+三 worker 全 masked，symlink→/dev/null） | Zhen | P1 | ✅ 已落实（结构性闭环根因②） |
| 3 | head 副本 start_tp4_worker_v043.sh L20 镜像 tag V5→V5b（留底 .bak-v5tag-20260907，md5 31d60685） | Zhen | P1 | ✅ 已落实 |
| 4 | disable proxy v1（inactive+enabled → disabled，v2 active 不受影响，8001 实测 200；回退=手动 enable） | Zhen | P1 | ✅ 已落实 |
| 5 | healthcheck 连续 FAIL≥3 告警闭环（唯一失效面=感知；需定告警通道） | 待督导定夺 | P1 | ⏳ 开放 |
| 6 | B2 死代码处置二选一：补接线（+审计三处 override 联动，hook 加 k>=1 下界）或删死码+修文档 | 下窗口 | P2 | ⏳ 开放 |
| 7 | 科迪 §7 七条远端核验命令（A2 两项数值定案 + A1 读者枚举兜底 + 四机 MARKOV env 现状） | SSH 稳定窗口 | P2 | ⏳ 开放 |
| 8 | sudo 口令卫生（guard 脚本明文口令 → sudoers NOPASSWD 精细授权或密钥托管） | 下窗口 | P2 | ⏳ 开放 |
| 9 | guard L49 旧名回退清理 / 6 个空 dump 清理（12:24 有效 dump 归档保留） | 择机 | P2 | ⏳ 开放 |
| 10 | reasoning 预算约束文档化（长上下文任务 max_tokens 预留 reasoning 余量，512 不够/3072 充足） | 文档侧 | P2 | ⏳ 开放 |

**验证记录（本轮修复）**：
- 四机 w6_env：b4ae0340cd55e04d289d2be43ff09a05 ×4 一致。
- 旧单元：head `vllm028-tp4-head=masked`，02/03/04 `vllm028-tp4-worker=masked` ×3，unit 实体均留底 `.bak-masked-20260907`。
- proxy：v1 disabled+inactive / v2 enabled+active / 8001 HTTP 200。
- 修复全程零中断：未触碰任何运行容器与现役服务。

---

## ⚠️ 待完善 / 已知局限

- A2 两项数值定案依赖远端核验（本轮 SSH 执行层在科迪会话中故障，其审计为静态口径）。
- B1 的 forward 侧适配（VocabParallelEmbedding/ParallelLMHead 本地行号假设）未解决，Markov replicate 长期不可用，除非下窗口重写 forward 配套。
- 四机容器当前 env 未含 MARKOV_REPL（护栏晚于容器启动注入），下次容器重建时经 w6_env 自然注入。
- 告警通道（行动 #5）需督导定夺：通道选型（钉钉/webhook/邮件）与告警阈值。

---

## 📚 数据来源 & 成员产出索引

- Cody（代码审查师）：《V5b 五补丁逐行审计》`gateway-v2/v5b-patch-audit-2026-09-07.md`（互补：《code-review-bwindow1-v5b-2026-09-07.md》）
- Tessa（测试专家）：《B窗1 V5b 行为级 QA》`gateway-v2/qa-bwindow1-v5b-2026-09-07.md`（脚本+原始证据：gateway-v2/qa_scripts/、node0X:/tmp/qa_bwindow1_v5b/）
- Rex（SRE 工程师）：《B窗1 运维复盘》`gateway-v2/incident-bwindow1-restart-2026-09-07.md`
- 修复执行（Zhen）：本报告"验证记录"节，命令与 md5 均为实时执行留痕

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
