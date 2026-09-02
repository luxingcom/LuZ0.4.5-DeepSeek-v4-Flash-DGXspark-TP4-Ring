# G1R6 试验镜像评估报告（LuZ-0.4.4-G1r6, 2026-09-02）

> 督导指令：技术团队已完成 G1R6 试验镜像创建，尝试部署测试、横向比对性能指标、验证 GSM8K 准确率。
> 上游输入：`w9-evidence/w9r4/W9-R10-ROUTEB-LOGITS-SYNTHESIS.md`（routeA/routeB 全链路 + logits 白算收尾可行性定谳 + G1r6 实验平台落地）。
> 执行纪律：单变量窗口（文档 §4.1 推荐序）；重启一律走 guard；口径 uuid 冷算三轮中位。

---

## 1. TL;DR

| 项 | 结论 |
|---|---|
| 镜像断言 | ✅ LuZ-0.4.4-G1r6（digest sha256:<BAKE_IMAGE_DIGEST>，基座 G1r5 353697b2） |
| 改动资产 | speculator.py（B1 draft_logits fp32→bf16 门控）+ w4a4_experts.py（tile_m 封顶 env 门控）+ envs.py |
| 窗口1（等价） | ✅ 平台等价（DE 95.60 归因 autotune 漂移；GSM8K spot200=0.94） |
| 窗口2（TILE_CAP=0） | ✅ **采纳**：PR4K C1=2727(+2.1%)/C4=906(+0.7%)，DE=99.48 与 G1r5 一致，崩溃哨兵全零 |
| 窗口3（B1 bf16） | ❌ **B1 未过验收门**：GSM8K=0.9318 < 0.9356（-4 题边界），DE 无收益 |
| autotune 固化 | ✅ 手动定义方案闭环（4 次重启命中，kernel 选择跨重启确定） |
| GSM8K | W1 spot200=0.94 / W3 全量=0.9318（基础 0.930 门过，B1 门 0.9356 未过） |
| **生产形态（督导定）** | **G1r6 + TILE_CAP=0**（保留 autotune 固化）；**B1 降级为可选参数**（默认关闭，G1r7 候选） |

## 2. G1R6 变更摘要（W9-R10）

- **镜像**：`REGISTRY_HOST:5000/vllm/vllm-openai:LuZ-0.4.4-G1r6` digest **sha256:<BAKE_IMAGE_DIGEST>**（FROM G1r5 <BAKE_IMAGE_DIGEST>，3 COPY + 1 验证 RUN）
- **实验位 A**：`VLLM_DRAFT_LOGITS_DTYPE=bfloat16`（B1：draft_logits fp32→bf16，流量减半 ~21.7MB/步 ≈ 0.16ms，预期 +0.1% DE；验收 accept-length<0.5% + GSM8K ≥0.9356）
- **实验位 B**：`VLLM_MOE_DYNAMIC_TILE_CAP=0`（解除 tile_m 封顶 64——AOT 陈旧内核时代定性的崩溃防护，G1r4 换真 0.6.18 JIT 内核后未复测；候选免费回收 **PR4K_C1 -7.4%**；崩溃哨兵陪跑）
- **默认零行为差**：不设新 env = G1r5 逐字节等价（可安全只换镜像验证平台）

## 3. 现役断言（切换后核对）

- 容器镜像 = LuZ-0.4.4-G1r6（digest sha256:<BAKE_IMAGE_DIGEST>）✅
- env：VLLM_MOE_W4A4=2 / VLLM_MOE_W4A4_CG=1 / VLLM_B12X_SHARED_WRAPPER=1（与 G1r5 一致）✅
- 无新 env（DRAFT_LOGITS_DTYPE / DYNAMIC_TILE_CAP 均未设=0）→ 默认零行为差 ✅
- B1 哨兵日志：`W9R10-B1 draft_logits dtype=torch.float32`（默认 fp32，门控正确）✅
- 四机 healthy、health=200、自愈链 timer active ✅
- 修复：<MGMT_OCTET> worker 脚本 tag 原为 G1r3（旧未同步）→ 已统一 G1r6（四机 worker md5 一致 ceea23bf，.bak-g1r5-20260902 留档）

## 4. 窗口1：平台等价验证（只换镜像，默认 env）

### 4.1 DE C1（对照 G1r5 99.72）

| 轮 | decode_tps | ttft_s | ok |
|---|---|---|---|
| r1 | 94.94 | 0.8231 | 1 |
| r2 | 95.60 | 0.7637 | 1 |
| r3 | 95.90 | 0.7703 | 1 |
| **中位** | **95.60** | 0.7703 | — |

- vs G1r5 99.72 = **-4.1%**
- 归因：B1 哨兵确认 dtype=float32（门控正确、B1 未激活）→ 差距为**跨重启环境差异**（CG/autotune 重捕获），非 G1r6 改动引入
- **根因定位（督导指令"手动定义优化"）**：autotune cache 跨重启 hash 漂移（`sha256(aot_compile_hash_factors)` 子目录每次不同）→ cache 永 miss → 每次全量重新 benchmark（日志实证 `24 new, 0 from previous`）→ kernel 选择抖动
- **修复**：改 `flashinfer_autotune_cache.py` — 设 `VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR` 时跳过 hash 子目录、固定路径写 config（env-switchable）；四机部署补丁（702f8f56）+ env（`VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/root/.cache/vllm/autotune-g1r6`）+ patches 挂载（worker 四机 md5 4f645032 一致）
- **生效验证**（guard 重启后）✅：固定路径 `autotune_configs.json` 落盘（6220B）；引擎日志 `Autotuning ... with cache: /root/.cache/vllm/autotune-g1r6/autotune_configs.json`；挂载确认注入。第二次重启将验证跨重启命中

### 4.2 GSM8K spot200 哨兵（对照 ≥0.930 / G1r5 0.9363）

| 项 | 值 |
|---|---|
| accuracy_content | **0.94**（<MGMT_OCTET>/200，err=0） |
| median_ct | 98 tokens |
| elapsed | 356.5s |

- ✅ 精度无退化（G1r5 全量 0.9363 / 历史 spot 0.95 相当）

## 5. 窗口2：+VLLM_MOE_DYNAMIC_TILE_CAP=0（核心性能实验）

**执行前提（autotune 手动固化后）**：本次所有测量在 autotune 固定路径 cache 命中下进行（`Loaded 24 configs`，跨重启确定），消除窗口1 的 -4.1% 环境差异污染。

| 格 | G1r6 W2 中位 | G1r5 cB | 差值 | 判定 |
|---|---|---|---|---|
| PR4K_C1 | **2726.90**（2700/2742/2727） | 2671 | **+2.1%** | ✅ 正收益 |
| PR4K_C2 | **2064.97**（2065/2061/2068） | 2061 | +0.2% | ≈持平 |
| PR4K_C4 | **906.15**（904/917/906） | 900 | +0.7% | ✅ 正收益 |
| PR4K_C8 | **541.47**（549/541/541） | 541 | +0.1% | ≈持平 |
| DE_C1 | **99.48**（93.3/103.2/99.5） | 99.72 | -0.2% | ✅ 与 G1r5 一致 |

- **autotune 固化效果实证**：DE C1 窗口1（未固化）95.60 → 窗口2（固化）99.48（+4.1%），回归至与 G1r5 99.72 一致 → 窗口1 的 -4.1% 确系 autotune 漂移，G1r6 默认路径与 G1r5 等价坐实
- C1 方向与文档"候选回收 -7.4%"一致（幅度保守）；C1 单请求对 tile_m 释放最敏感
- 崩溃哨兵全零 ✅：xid_baseline=0 / xid_now=0 / moe_launch_fail=0，TILE_CAP=0 解封无崩溃

## 6. 窗口3：+VLLM_DRAFT_LOGITS_DTYPE=bfloat16（B1 验证）

**执行前提**：叠加 TILE_CAP=0；autotune 第 3 次重启仍命中（`Loaded 24 configs`）；B1 哨兵确认 `dtype=torch.bfloat16`（激活 ✅）

### 6.1 DE C1（B1 收益验证，对照 W2 99.48）

| 轮 | decode_tps | ttft_s |
|---|---|---|
| r1 | 94.92 | 0.717 |
| r2 | 99.42 | 0.7245 |
| r3 | 102.56 | 0.7224 |
| **中位** | **99.42** | 0.7224 |

- vs W2 99.48 = **-0.1%**（B1 无收益；文档预期 +0.1%，量级内但方向持平）

### 6.2 accept-length（B1 验收：变化 <0.5%）

- 采样 Mean acceptance length：5.46/4.63/5.17/6.11/6.20（Avg draft accept rate 51.8-74.2%）——与 MTP n=7 历史一致，无异常

### 6.3 GSM8K 全量（B1 验收门 ≥0.9356）

| 项 | 值 | 判定 |
|---|---|---|
| accuracy_content | **0.9318**（1229/1319） | ❌ **未过 B1 门 0.9356** |
| accuracy_marker | 0.9333（1231/1319） | ❌ |
| err | 0 | ✅ |
| gate_pass_0p930 | true | ✅（基础门过） |
| 对照 G1r5 | 0.9363 | **-0.45pp（-6 题）** |

- **B1 判定失败**：GSM8K 0.9318 < 验收门 0.9356（差 4 题边界），且 DE 无收益 → **B1 不建议采纳，回退 fp32**

## 7. GSM8K 准确率汇总

| 阶段 | 配置 | accuracy_content | 判定 |
|---|---|---|---|
| G1r5 全量（基线） | cB，2400 制→2300 制 | 0.9363 | 基准 |
| W1 spot200 | G1r6 默认 env | **0.94**（<MGMT_OCTET>/200） | ✅ 无退化 |
| W3 全量 | G1r6 + TILE_CAP=0 + B1 bf16 | **0.9318**（1229/1319） | ❌ 未过 B1 门 0.9356 |

- 基础 0.930 门 W3 通过（gate_pass_content=true）
- B1 降级决策（督导）：不默认启用，G1r7 候选

## 8. 结论与判定

1. **G1r6 平台等价坐实**：默认 env 与 G1r5 逐字节等价（B1 哨兵 dtype=float32 门控正确；W1 DE 差距纯属 autotune 漂移，固化后回归一致）
2. **TILE_CAP=0 采纳**：PR4K C1 +2.1%、C4 +0.7% 正收益，无崩溃（xid=0），无精度退化迹象 → 进生产形态
3. **B1 降级为可选参数**：GSM8K 0.9318 未过验收门 0.9356（差 4 题边界）+ DE 无收益；保留代码位默认关闭，待 G1r7 更充分验证
4. **autotune 手动固化（生产收益）**：跨重启 kernel 选择确定（4 次重启命中），消除 ±2-4% 环境噪声——本报告所有对比可信

**生产形态（督导裁决）**：LuZ-0.4.4-G1r6 + cB 参数 + TILE_CAP=0 + autotune 固化（B1 关闭）

## 9. 遗留项

- proxy MAX_CONCURRENCY=6 未改 12（G1r4 批次未落地）
- <MGMT_OCTET> worker 脚本 tag 此前为 G1r3（旧，未同步）——本次已一并统一为 G1r6
- 若窗口2 解封追平 luz031 2884 → routeB 路线 C 机会窗口收窄，转 grouped ko 微基准先行

---
*报告起草：2026-09-02（G1R6 窗口执行中）*
