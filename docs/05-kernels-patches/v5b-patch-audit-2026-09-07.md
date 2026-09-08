# Code Review: V5b 五补丁逐行审计（digest bb22a8c7，B窗1 落地批次）

- 日期：2026-09-07
- 审查人：code-reviewer（只读审计，零生产变更；发现问题报告，不自行修改）
- 生产面：V5b 现役四机 healthy，GSM8K10 10/10，真实生成 OK
- **材料口径（重要）**：node01 SSH 执行层故障（Bash 空输出、PowerShell exit 1，与 S3 期间同症状），
  现役文件 md5 无法直接核对。本审计为**基于本地镜像血统的静态审查**：
  - `apply_v5b_patches.py` / `apply_v5b_b_patches.py`（补丁生成器，内嵌全部 old/new 锚点串与断言门）
  - `Dockerfile.LuZ-0.4.5-V5b`（A1 正门/负门构建期断言）
  - A3 内核原源全文（`集群部署/.../remote-src/dsv4/cache_utils.py` L461–508）
  - **g1r3 时代安全评审**（`g1r3-solidification-safety-review-2026-09-01.md`——A1 的来龙去脉在此有
    白盒+现场实证记载）+ `g1r3-whitebox/whitebox_verify.py`、`model.patched.py`/`model.g1r3.py` 镜像
  - 残余风险：生成器→现役文件之间若有人工二次改动则不在视野内；§7 附远端核验命令。

---

## 概要

- **A1 是对已知历史 bug 的正确修复**（非新变更）——g1r3 评审已白盒实证原条件反转导致 D 优化从未生效，
  A1 恢复语义，且本窗 GSM8K/真实生成已实证新默认行为。**Approve**。
- **B2 确认为死代码**（主理人疑心正确）：`_apply_draft_topk_override` 由补丁全新引入且**无任何调用点**，
  `VLLM_DSPARK_DRAFT_TOPK` 环境旋钮**不生效**。零生产风险（反而消除了 B2 自述的高风险面），
  但与交接清单预期不符，需修正文档或补接线。
- **B1 维持 🔴：`VLLM_DSPARK_MARKOV_REPL` 必须保持禁用**——全表替换未配任何 forward 改动，
  启用即 rank1–3 查表错位静默数值错乱；且清单描述的"fp32 bias 路径"**在实现中缺失**。
- A2 结构面成立，两项数值定案待远端；A3 位级不变性逐行证实，Approve；guard 脚本 v3 逻辑正确。

## 逐补丁 Verdict 总表

| 补丁 | 文件 | Verdict | 最高发现 |
|------|------|---------|---------|
| A1 | model.py L1141 | ✅ **Approve** | 🟢 语义正确（历史 bug 修复，有 g1r3 白盒血统）|
| A2 | rope.py | ⚠️ **Conditionally Approve** | ❓ 两项数值定案待远端 |
| A3 | cache_utils.py L482 | ✅ **Approve** | 🟢 位级不变性逐行证实 |
| B1 | qwen3_dspark.py + dspark.py | 🔴 **Request Changes**（默认关零暴露）| 🔴 启用即静默数值错乱；fp32 bias 路径缺失 |
| B2 | dspark.py（hook）| 🟠 **死代码确认** | 🟠 env 旋钮不生效（预期不符，零风险）|
| guard v3 | w9r4_window_restart.sh | ✅ **Approve with comments** | 🟠 sudo 口令明文；🟡 head 旧名容器漏清 |

---

## 1. A1：model.py SKIP_MTP_COPY 条件反转 —— ✅ Approve

**diff**（生成器 L16–17，断言门保证全文件唯一 1 处 + Dockerfile 正/负门）：

```python
- if os.environ.get('VLLM_DSPARK_SKIP_MTP_COPY', '1') != '0':   # 条件真 → 执行 copy_
+ if os.environ.get('VLLM_DSPARK_SKIP_MTP_COPY', '1') == '0':   # 仅显式 =0 执行 copy_
```

**① 反向语义正确性——确认，且有完整历史血统**：

- 该条件守卫的是 `_mtp_hidden_buffer` 的每步 `copy_`（守卫块=拷贝本身，非跳过动作）。
  旧逻辑默认（'1'/未设）`!= '0'` → True → **copy 仍在执行**，即 g1r3 D 优化在生产从未生效；
  设 `=0` 反而跳过——与变量名及文档完全相反。这正是
  `g1r3-solidification-safety-review-2026-09-01.md` 🚨 确认项 + 白盒实证的**已知 bug**，当时 P1
  建议修正为 `!= '1'`（或等价）。A1 的 `== '0'` 与该建议等价：默认/='1' → False → 跳过 copy
  （**死拷贝消除，D 优化首次真正生效**）；显式 `=0` → True → 拷贝恢复（回退逃生门）。
- 行为变更面：**env 未设时行为改变**（copy 不再执行）——正确性依赖"该 copy 为死拷贝"论断。
  佐证：①g1r3 白盒+现场实证；②D-f-forkcode 审计称唯一读者是 runner:5167 备用绑定死代码；
  ③**本窗实证**：V5b 上线后 GSM8K10 10/10 + 真实生成 OK，即新默认行为已被生产流量验证。
- **② 下游消费者论断**：本地无 v5 model.py 源，runner:5167 死代码论断无法独立复核（SSH 故障）。
  给出远端 grep 命令（§7-2）做全量读者枚举兜底。鉴于实证③，此为 belt-and-braces 项，非阻断。

**结论**：语义正确、血统完整、已被本窗实证。Approve。（历史注：g1r3 评审建议的正是本修复，
迟到一个版本窗口落地。）

---

## 2. A2：rope.py SWA 层 YaRN 泄漏修复 —— ⚠️ Conditionally Approve

**diff**（生成器 L31–41）：`compress_ratio <= 1` 时局部重指向 `rope_parameters = dict(rope_parameters)`
并置 `apply_yarn_scaling=False`。

- **①deepseek_llama_scaling 数学语义**（等价 plain theta=10000、无 inv_freq 插值）与 **cos_sin_cache
  fp32 契约**（首版栽在 `fused_inv_rope_fp8_quant.py:189` 断言）：**本地无 rope.py 与
  rotary_embedding 源，无法验证**——不猜。结构面有利：补丁只翻转布尔、**不动 rope_type/类血统**
  （DeepseekV4ScalingRotaryEmbedding lineage 保留，正是首版强制 default 崩溃的根因规避），
  理论风险面显著低于首版。待核命令 §7-4/5。
- **②compress（ratio>1）层零影响——结构上确认**：if 分支只改局部变量指向；
  `config.rope_parameters` 原对象不被 mutate，ratio>1 层读到的仍是原 dict，逐字节零改动。✅
- **③dict 拷贝副作用——有条件成立**：`dict()` 浅拷贝，安全性依赖 rope_scaling 值域全为标量/字符串
  （0731 典型 yarn 配置满足）；若有嵌套 dict 且下游 mutate 内层则污染全局。一条命令定案（§7-3）。
  另：`rope_parameters=None` 无防御（dict(None)→TypeError），0731 config 实际携带 yarn 字段
  且现网已启动，未踩，仅记录。

---

## 3. A3：cache_utils.py OOB clamp —— ✅ Approve

内核原源全文在手（L461–508），逐行比对补丁 diff：

- **clamp-to-0 lane 的 load 语义**：被污染 lane（`local_idx>=0` 但 `local_idx//block_size >= stride`）
  clamp 后读 `block_table[req][0]`——**读到的是本请求的真实 block0**（in-bounds，非野指针）；
  该 slot_id 随后经 `tl.where(is_valid, slot_ids, -1)` 不会因 clamp 本身被置 -1（is_valid 只看
  `local_idx>=0`），会作为"合法但错误"引用写入 `global_topk_indices`——**内存安全达成（防 OOB 读），
  语义污染被洗白为 in-bounds 错值**。对 #55636 防御性定位可接受，相对基线（OOB 读）纯改进无回归；
  更稳变体：`tl.where(local_idx < stride*block_size, slot_ids, -1)` 直接置哨兵（可选项）。
- **block_table_stride 语义=列深**：入参为 `block_table.stride(0)`（L452），对行主序 2D 表
  即每 req 的行宽=列深。clamp 上界正确。✅
- **正常路径位级不变**：合法 lane `tl.where` 取原值（整数向量位模式不变）；新增
  `& (local_idx >= 0)` 与原 `is_valid = local_idx >= 0`（L489）恒等，任何 lane 的 load mask
  都不变；无效 lane（other=-1）本就被 mask，垃圾值被下游 -1 哨兵丢弃、`count` 不受影响。✅
- **标量广播**：`block_table_stride` 标量入参，`tl.where(向量<标量, 向量, 标量0)` 标准
  Triton 广播。✅

---

## 4. B1：Markov replicate —— 🔴 Request Changes（MARKOV_REPL 必须保持禁用）

**①all_gather 时序**：load_weights 尾部调用、`_replicated` 幂等守卫、dist 未初始化/world≤1 早退——
时序与幂等本身无问题。✅（重入边缘：若运行期再次 load_weights 分片写，`_replicated` 守卫使
finalize 跳过，分片 weight_loader 按 shard 偏移写全表恰好落对位置——非现役路径，仅记录。）

**②gather 后 w2 形状/forward 影响——🔴 核心缺陷**：`markov_w1=VocabParallelEmbedding`、
`markov_w2=ParallelLMHead` 的 forward 均内嵌 per-rank vocab range 假设（`id - vocab_start`
本地行号 + 输出集合通信合并）。`t.data = torch.cat(full, dim=0)` 全表替换后 **forward 零配套改动**
（生成器中唯一的 embed"替换"是字面 no-op `s.replace(old_embed, old_embed)`，其注释"分片
lookup 语义不变"为错误论断）→ rank1–3 每次 embed 查表错位 vocab_start_r 行（静默、无 NaN/形状
信号）、w2 分片 matmul/gather 假设破坏。注释声称"bitwise-neutral, proven offline"——离线证明的
是"forward 直用全表"那种实现，不是这份代码。**启用即静默数值错乱 → 必须保持禁用**
（默认 off，现网零暴露，与本窗 healthy 自洽）。

**③"fp32 bias 路径"缺失——确认**：生成器 docstring（L14）声称"B1: 加 replicate 参数+分支+
fp32 bias 路径"，但补丁正文**零 fp32/bias 代码**（全文仅 L86 注释提及 bias() 收益）。
与 ② 同根因：forward 侧工作整体未落地——不仅缺 fp32 bias 路径，连利用复制表的任何路径都没有。
启用 REPL=1 净效果 = +132MB/rank HBM + 查表错乱，零收益纯风险。

**④默认关路径零行为差——确认**：`replicate=False` → finalize 首行早退；新 kwarg 带默认值；
`_replicated`/world≤1/dist 未初始化早退均无害。✅

**🟡 附带**：dspark.py 的 finalize 调用按"load_weights 内最后一个 return 行前插入 8 空格"
启发式落位——若该 return 在更深缩进分支内，位置可能语义错（py_compile 过≠位置对）；
py_compile 过≠位置对）；需远端核对插入行上下文（§7-6）。

---

## 5. B2：draft MoE topk 封顶 hook —— 🟠 死代码确认（主理人疑心成立）

**定案依据（生成器血统，100%）**：
- `_apply_draft_topk_override` 方法名由补丁**全新引入**（补丁前不存在该名字 → 补丁前代码不可能调用它）；
- 生成器 `patch_b2_topk` 仅在 `embed_input_ids` 前插入方法**定义**，全脚本无任何调用语句插入
  （grep 全部本地镜像：该方法只出现在生成器定义串中）；
- 无动态分派风险（方法名新造，不存在 getattr/字符串调用既有路径）。

**后果**：`VLLM_DSPARK_DRAFT_TOPK=<n>` 环境旋钮**完全不生效**（hook 永不被执行）。
生产风险为零——反而消除了 hook docstring 自述的"High-risk: A/B only"面；但与交接清单
"B2：C2 draft MoE topk 封顶（env 门默认关）"的预期不符：默认关的开关是"关了不生效"而非
"关了可用"。**处置建议**（下窗二选一）：①在构造路径补一行调用（如 `__init__` 尾部
`self._apply_draft_topk_override()`，同时审计其三处 override 的联动正确性——hook 内部逻辑
本次未深审，因死代码无现役影响）；②删除死代码+修正交接文档，避免未来误信该旋钮可用。

---

## 6. guard 脚本 v3（w9r4_window_restart.sh）—— ✅ Approve with comments

全逻辑审查（本地镜像全文在手）：

- **stop 序列**：workers(.187/.188/.189) `systemctl stop` 双单元名 + `docker rm -f` 按
  `--filter name=tp4-rank` 双代名通杀 + 计数回显；head 双单元名 stop + `docker rm -f
  vllm-tp4-rank0`。✅（🟡 head 仅清新名容器，旧名 `vllm028-tp4-rank0` 漏清——与 worker 侧
  不一致，残留概率低（旧单元 inactive），下窗补齐。）
- **TCPStore 等待 + fail-fast（D2）**：24×5s=120s 轮询 `ss -ltn :26000`；超时 → 打印
  FAIL-D2 → `systemctl stop head` 保持四机静止 → tail rank0 日志（新旧名回退）→ exit 2。
  **正确**，杜绝"head 未就绪先起 workers"的分裂集群历史根因。✅
- **单元名固定新名**：`UNIT_HEAD="vllm-tp4-head"` 固定 + worker start 新名优先旧名回退
  （`||` 链）——与 B窗1 教训（grep 探测单元文件选名是错的）一致。✅
- **health 轮询/退出码**：40×30s=20min 轮询 `:8002/health`，200→exit 0；失败 tail 日志
  （新旧名回退）→exit 1。三档退出码（0/1/2）可供上游分诊。✅
- 🟢 头注释漂移：写"30x30s"实际 40×30s。
- **🟠 S-1 卫生问题**：sudo 口令明文落盘（L12 `PW='<PASSWORD>'`）且经 `echo '$PW' | sudo -S`
  拼进 ssh 远端命令串（远端 ps 执行瞬间可见）。建议 sudoers NOPASSWD 限定单元名，或运行时注入。

---

## 7. 远端核验命令清单（SSH 恢复后执行，全部只读）

```bash
# 1. md5 血统核对（生成器产出 vs 现役）
md5sum ~/g1r7-build/v5b-ctx/orig/{model.py,rope.py,cache_utils.py} \
       ~/g1r7-build/v5b-ctx/patched/{model.py,rope.py,cache_utils.py} \
       ~/g1r7-build/v5b-ctx/patched-b/{qwen3_dspark.py,dspark.py} \
       ~/w6-kit/w9r4_window_restart.sh ~/w6-kit/daily_smoke.py

# 2. A1 兜底：SKIP_MTP_COPY 全量读者枚举（验证"唯一读者 runner:5167 死代码"论断）
docker exec vllm-tp4-rank0 grep -rn "SKIP_MTP_COPY\|_mtp_hidden_buffer" \
  /usr/local/lib/python3*/dist-packages/vllm/ --include=*.py

# 3. A2-③ 键集定案：rope_scaling 是否全标量
docker exec vllm-tp4-rank0 python3 -c \
  "import json;print(json.load(open('/path/to/0731-config.json')).get('rope_scaling'))"

# 4. A2-① deepseek_llama_scaling 分支数学（是否无 inv_freq 插值）
docker exec vllm-tp4-rank0 grep -n -A25 "deepseek_llama_scaling" \
  /usr/local/lib/python3*/dist-packages/vllm/model_executor/layers/rotary_embedding/__init__.py | head -60

# 5. A2-① fp32 契约：与 apply_yarn_scaling / cos_sin_cache dtype 的耦合断言
docker exec vllm-tp4-rank0 grep -n "dtype\|assert\|apply_yarn" \
  /usr/local/lib/python3*/dist-packages/vllm/model_executor/layers/rotary_embedding/fused_inv_rope_fp8_quant.py

# 6. B1-③ finalize 插入点上下文（缩进/分支归属）
grep -n -B3 -A1 "finalize_replication()" ~/g1r7-build/v5b-ctx/patched-b/dspark.py

# 7. B1 护栏现状：四机 env 均未设 MARKOV_REPL（预期无输出）
for h in 186 187 188 189; do ssh _PH_USER_@_PH_HEAD_IP_.$h \
  "docker exec \$(docker ps --format '{{.Names}}' | grep tp4-rank | head -1) env | grep MARKOV" ; done
```

命令 4/5 若证实 `deepseek_llama_scaling` 无 inv_freq 插值且 fp8 断言无耦合 → A2 升 Approve。

## 8. 总结论

- **现网风险面**：A1/A2/A3 生效 + B1/B2 env 默认关（B2 死代码=永关）→ 🔴 不构成现网暴露；
  本窗 GSM8K10 10/10 + 真实生成与审计结论自洽。
- **最优先行动**：①B1 护栏——unit Environment 显式 `VLLM_DSPARK_MARKOV_REPL=0` + 交接文档禁开令；
  ②B2 处置（补接线或删死码，二选一，防"旋钮可用"误信）；③SSH 恢复后跑 §7 七条命令
  （md5 血统 + A2 两定案 + A1 读者枚举兜底）；④S-1 口令卫生下窗处理。
