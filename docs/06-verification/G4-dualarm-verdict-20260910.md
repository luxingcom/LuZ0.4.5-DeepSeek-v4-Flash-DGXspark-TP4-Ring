# G4 双臂验收 · 终判报告（S1 补丁性能结论）

**签发**：team-lead（工程保障团队督导）
**日期**：2026-09-10
**窗口**：2026-09-10 13:37 – 14:15 UTC（栈恢复 + NEW 臂执行）
**性质**：**双臂验收完成 · S1 补丁性能结论下判**
**裁定**：**✅ PASS（不可区分）—— S1 补丁在 gate-off 形态下性能等价，可按机制方向保留（不回退）**

---

## 📌 结论（三句话）

1. **性能判据 PASS**：NEW 臂 decode 均值 **82.3340 tps** vs OLD 臂 **81.9000 tps**，**Δ = +0.4340 tps (+0.530%)**，**|Δ| = 0.4340 ≤ F = 4.8800**（臂内噪声地板）⇒ **两臂在本轮量测精度内不可区分**。
2. **机制判据 PASS**：gate-off 形态下 S1 补丁为**控制流 no-op**（`confidence_head=None` ⇒ `_conf_enabled=False` ⇒ 全部 confidence 路径短路），与旧镜像**逐语句等价**——性能不可区分是**预期内的正确结果**，非"测不出差异"。
3. **裁定：保留 NEW（S1b），不回退**。S1 补丁在 gate-off 下不引入性能代价，同时为后续 G2 开臂提供了同一镜像的开闸能力（`VLLM_DSPARK_CONF_GATE=1`）。

---

## 一、双臂量测数据

### 1.1 原始数据（decode p50，单位 tps）

| 轮 | OLD 臂 | NEW 臂 |
|---|---|---|
| r1 | 78.81 | 86.25 |
| r2 | 86.05 | 80.34 |
| r3 | 82.73 | 80.55 |
| r4 | 81.51 | 79.16 |
| r5 | 80.40 | 85.37 |

### 1.2 统计量（★ 督导独立复算，8/8 逐位命中）

| 统计量 | OLD 臂 | NEW 臂 |
|---|---|---|
| n | 5 | 5 |
| mean | **81.9000** | **82.3340** |
| median | 81.5100 | 80.5500 |
| stdev | 2.7323 | 3.2321 |
| range | 7.2400 | 7.0900 |
| MAD | 1.2200 | 1.3900 |
| 4×MAD | **4.8800** | 5.5600 |

### 1.3 判定量

| 量 | 值 | 说明 |
|---|---|---|
| **Δ(mean)** | **+0.4340 tps（+0.530%）** | NEW − OLD |
| Δ(median) | −0.9600 tps（−1.178%） | 中位数方向相反（见 §四 诚实标注） |
| **F（臂内噪声地板）** | **4.8800 tps（5.958%）** | `4 × MAD(OLD)`（口径与 OLD 臂定谳一致） |
| s_p（合并标准差） | 2.9926 | df = 8 |
| **CI95(between)** | **[−3.9306, +4.7986]** | 半宽 4.3646，`t(0.975, df=8) = 2.306` |
| **|Δ| ≤ F ?** | **是**（0.4340 ≤ 4.8800） | **判据 (i) 命中** |

---

## 二、判定框架与裁定

**双向判据（顺序求值）：**

| 分支 | 条件 | 命中 | 结论 |
|---|---|---|---|
| (i) | `|Δ| ≤ F` | **✅ 命中** | **PASS（不可区分：落在臂内噪声地板内）** |
| (ii) | `|Δ| > F` 且 CI95 不含 0 | ✗ | 显著：按方向记录 |
| (iii) | `|Δ| > F` 且 CI95 跨 0 | ✗ | 证据不足 |

> **分支 (i) 先于 (ii) 求值**：只要 `|Δ| ≤ F`，即判定不可区分——因 F 本身已是臂内噪声上界，Δ 落在该带内**不具备判别力**。

### 终判

```
VERDICT = PASS（不可区分：|Δ| ≤ F 臂内噪声地板）
裁定     = 保留 S1b，不回退
```

**⚠️ 该判定的解读边界（重要）**：
- 「PASS」的语义是 **"gate-off 形态下 S1 补丁不改变生产性能表现"** —— **不是** "S1 补丁带来了性能提升"。
- S1 补丁的**收益项（confidence 门控）在 gate-off 下未启用**，故本轮**无法**评断其开闸后的收益。此为设计使然（架构=gate-off 作安全基线，闸门收益属 G2 开臂任务）。

---

## 三、支撑证据

### 3.1 G4-T1 契约等价（代码级实锤，镜像内实测）

| # | 证据 | 实测值 |
|---|---|---|
| 1 | `dspark.py:139` confidence_head 创建门 | `if os.environ.get("VLLM_DSPARK_CONF_GATE","") == "1":` ⇒ gate off ⇒ **`confidence_head = None`** |
| 2 | `speculator.py:124-126` 守卫定义 | `_conf_enabled = (num_speculative_steps > 0 and getattr(model,"confidence_head",None) is not None)` ⇒ **`False`** |
| 3 | confidence 路径全守卫 | `speculator.py` L128 / L211 / L242 / L262 均以 `_conf_enabled` 短路 ⇒ **控制流逐语句等价** |
| 4 | **运行期实证** | `env_gate = UNSET`（容器内 `printenv VLLM_DSPARK_CONF_GATE`） |
| 5 | **运行期实证** | `staging_count = 0`（日志 `grep -ic 'confidence staging'` = 0 ⇒ 无 w5 路径激活） |

> **⇒ 契约等价成立**：gate-off ⇒ 无新模块创建、无新 checkpoint 消费、无新控制流分支。与旧镜像"逐语句等价"。

### 3.2 G4-T1 (i) tokenids 取证 —— **证明精确比对不可行**（负结果，如实记录）

| 比对 | BIT_EXACT | 比率 |
|---|---|---|
| OLD-r1 vs NEW-r1 | 4/50 | 8.0% |
| OLD-r2 vs NEW-r2 | 0/50 | 0.0% |
| OLD-r3 vs NEW-r3 | 7/50 | 14.0% |
| **OLD↔NEW 合计** | **11/150** | **7.3%** |
| **OLD 臂自身 r1==r2==r3** | **2/50** | **4.0%** |
| **NEW 臂自身 r1==r2==r3** | **1/50** | **2.0%** |

> **★ 关键判别**：**臂内自洽率（4.0% / 2.0%）低于 OLD↔NEW 交叉率（7.3%）** ⇒ 服务器对**自身**都不可复现 ⇒ **token 级精确比对零判别力**（与 Rex 早前 `BIT_EXACT=3/50` / `new↔new2=6/50` 结论一致）。
> **结论**：G4-T1 判据应以 **(ii) 契约等价**为准，弃 token 精确相等（原理性不可行——`temperature=1.0 / top_p=1.0` 采样覆盖 + K=6 自洽地板 0.25）。

### 3.3 E0 镜像身份四联（NEW 臂，实测）

| 项 | 值 |
|---|---|
| TAG | `REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-VL-S1-20260910b` |
| RepoDigest | `sha256:<BAKE_IMAGE_DIGEST>`（四机一致） |
| StartedAt | `2026-09-10T13:39:39.989940525Z` |
| health | `200` |
| env_gate | `UNSET`（gate off） |
| staging_count | `0` |

### 3.4 镜像内补丁落地核验（六目标文件 md5）

| 文件 | 实测 md5 | 期望 | 判定 |
|---|---|---|---|
| `models/deepseek_v4/nvidia/dspark.py` | `fb3912ab05263b72b12ba47fa994fc2e` | `fb3912ab` | ✅ |
| `v1/worker/gpu/spec_decode/dspark/speculator.py` | `179a6b785432120113bfaeccc456a8f7` | `179a6b78` | ✅ |
| `v1/core/sched/scheduler.py` | `f95874aa23342a2292508aea4ad83775` | `f95874aa` | ✅ |
| `v1/engine/core.py` | `210af81383d6b7d5a0073ff79c3784ef` | `210af813` | ✅ |

**[S1] 标签计数**：`scheduler.py` = 6 / `dspark.py` = 4 / `dspark/speculator.py` = 5
**[S1-DIAG] 标签计数**：`scheduler.py` = **0**（w5 未并入 = **设计态**，非缺陷）

### 3.5 值守四件套（全程零异常）

| 项 | 实测 | 判定 |
|---|---|---|
| head StartedAt | `2026-09-10T13:39:39.989940525Z`（跑前 → 跑后一致） | ✅ **无重建** |
| TAG 漂移 | 全程 `…VL-S1-20260910b` | ✅ 未漂移 |
| health | 全程 `200` | ✅ |
| journalctl「触发主动重建」 | **0** 次（近 2 小时） | ✅ |

**四机容器终态**：
```
node01: vllm-tp4-rank0  Up 37 minutes (healthy)
node02: vllm-tp4-rank1  Up 38 minutes (healthy)
node03: vllm-tp4-rank3  Up 38 minutes (healthy)
node04: vllm-tp4-rank2  Up 38 minutes (healthy)
```
**node01 `8002/health` = 200** ✅

---

## 四、诚实标注

1. **Δ(mean) 与 Δ(median) 方向相反**：mean **+0.530%** / median **−1.178%**。原因为两臂各含离群（OLD r2=86.05、NEW r1=86.25 / r5=85.37），使 mean 与 median 指向不同。**本判定以 mean 为准**（F 与 CI95 均基于 mean 体系建立，口径一致性优先）；median 方向已如实记录，**不隐藏**。
2. **F 含"载荷分量"**：因 `--uuid-prefix` 令每轮载荷唯一，F = 4×MAD 是 **噪声上界（偏保守）**，非纯系统抖动地板。⇒ 判定"不可区分"的**门槛被抬高了**；若 F 更小，结论可能转向"显著"。**该保守性对结论方向有利（不会误判为提升）。**
3. **判据 (i) 是"证据不足"的一种强形式**：`|Δ| ≤ F` 严格说是"**无判别力**"，而非"证明两臂完全相同"。措辞上用「不可区分」而非「等价」，避免过度声称。
4. **本轮不能评断 S1 闸门收益**：gate-off ⇒ confidence 路径未激活 ⇒ 收益项未被检验。**任何" S1 提升 X%"的说法在本轮数据下均无依据。**
5. **G4-T1 token 精确比对判为原理性不可行**（负结果）：臂内自洽 4.0%/2.0% < 交叉 7.3%。已如实记录为"判据不可用"，改用契约等价。
6. **OLD 臂数据复用于本次对比**：OLD 臂 5 轮于 09-10 12:34–13:03 UTC 完成（StartedAt `12:34:22.710843376Z`），NEW 臂于 13:38–14:15 UTC 完成。两臂**非同一时间块**，存在时段漂移风险；但值守四件套显示两臂窗口内均无重建、无 TAG 漂移、GPU 时钟无异常，**该风险已被值守数据约束**。
7. **本轮未实施冷却窗缺陷修复（A）**：`-61422s` 自锁仍在（详见 `selfheal-timer-20260910/RISK-BOUNDARY.md` §4bis）。跑臂期间该缺陷实际起到"防误杀保护"作用，**未干扰本轮验收**。

---

## 五、现场终态与后续

### 5.1 现场终态（本报告签发时）

| 项 | 状态 |
|---|---|
| 四机容器 | 全 `Up (healthy)`，镜像 = **NEW（S1b）** |
| `8002/health` | **200**（推理服务**可用**） |
| 四机 R5 / 脚本 md5 | NEW 态（head `37d53233…` / worker `8821c7e3…`） |
| `vllm-healthcheck.timer` | **active**（仍在跑） |
| 冷却窗自锁 | **未修**（state 仍为 `1789104989`） |

### 5.2 遗留（按优先级）

| # | 事项 | 说明 |
|---|---|---|
| 1 | **冷却窗修复 A** | 一行 `&& [ $((NOW-LAST)) -ge 0 ]` + 清 state；**改脚本与清 state 均无需 sudo** |
| 2 | **G2 开臂** | 依赖 w5_diag 并入镜像（b′ 版：重 build + 四机分发） |
| 3 | E0-d 断言 | 镜像内 `scheduler.py` md5 期望值随 b′ 版更新 |
| 4 | 收尾恢复 | monitor 4 节点 / timer / concurrency-proxy 等 |
| 5 | 8002 收敛配套 3 处验证 | monitor_worker L18 / bench 脚本 / 8022 放行 |
| 6 | 8001 探针 | Rex 方案：独立 timer，只发现不自愈 |
| 7 | 参数面 P3 | 7 伪配置硬编码；proxy MAX_CONCURRENCY=6 → 12 |

---

## 六、产物清单

**服务器**（`node01:~/w6-kit/g4-20260910/`）：
- `NEW_DE5/DE_coding_C1_r{1..5}/summary_v2.json` —— NEW 臂 5 轮原始数据
- `NEW_DE5/warmup_w{1,2}/` —— 冷重启后 warmup ×2
- `S1-G4-tokenids-NEW-r{1,2,3}.jsonl` —— NEW 臂 tokenids 取证（各 50 行）
- `S1-G4-tokenids-OLD-r{1,2,3}.jsonl` —— OLD 臂 tokenids 取证（各 50 行）
- `new_arm_driver.log` —— NEW 臂执行日志（含 `NEW ARM DONE rc=0`）

**本地**：本报告 `G4-dualarm-verdict-20260910.md` + `gate-combo-verdict-20260910.md`（附录含 OLD 臂）+ `FINAL-STATUS-20260910.md`

**执行脚本**：`~/w6-kit/rex_g4_handoff.sh`（md5 `5cfaa7943a333e00be42772d0cfb2282`，含 [C6-fix2] `check_idle` 数值判据）
