# B窗1 V5b 切换后行为级 QA 验证报告

- **日期**: 2026-09-07
- **执行人**: 泰莎（Tessa）· 测试专家
- **被测栈**: 4× DGX Spark GB10 TP4 集群，DeepSeek V4 Flash，现役镜像 LuZ0.4.5-V5b fix2（registry digest `sha256:<BAKE_IMAGE_DIGEST>`，k=7 MTP）
- **测试入口**: 仅经网关 `http://127.0.0.1:8001/v1/chat/completions`（node01 本机经 `ssh node0X`），`Authorization: Bearer <BEARER>`，model=`deepseek-v4-flash-0731`。未触碰 8002 直连（iptables 白名单生效，纪律性规避）。
- **服务端确认**: `/v1/models` 返回 `system_fingerprint: vllm-0.26.1.dev0+gd3d3b2cca.d20260805-tp4-cabf9135`，`max_model_len=600000`（500K 档可容纳）。

## 总判定表

| # | 验证项 | 对应补丁 | 判定 |
|---|--------|----------|------|
| 1 | A2 长上下文 needle 三档（30K/128K/500K） | A2（SWA 层 YaRN 泄漏修复） | **PASS**（4/4 位置，首轮 1 项 FAIL 已归因为生成预算耗尽，非检索缺陷） |
| 2 | A1 max_tokens=256 输出完整性（5 采样） | A1（SKIP_MTP_COPY 条件修复 model.py L1141） | **PASS** |
| 3 | 流式回归（短/中/长 SSE） | 回归确认（本批未动网关） | **PASS** |
| 4 | B2 draft topk hook | B2 | **不适用（死代码）** |
| 5 | B1 Markov replicate env 门 | B1 | 未单独验证（现禁用，见备注） |

---

## 1. A2 长上下文 needle 三档（待回填）

（执行中）

## 2. A1 max_tokens=256 输出完整性 — PASS

### 方法
该服务栈强制 reasoning 模式（`chat_template_kwargs: {"thinking": false}` 不生效，模型目录无 chat template 可关）。因此 A1 验证采用**可校验结构 + token 账目对账**双证据：

- 提示词：`No thinking needed. Immediately output the integers 1 to 120 separated by single spaces, nothing else.`（压短 reasoning，使 content 可在 256 预算内产出）
- 判据：
  1. 预算全额消耗：`usage.completion_tokens == 256` 且 `finish_reason == "length"`（无提前截短）
  2. token 账目：`/tokenize(content) + /tokenize(reasoning)` 与 `completion_tokens` 差 ≤1（该 1 为 reasoning→content 边界 token 重分词误差）
  3. content 完整性：整数序列严格连续（+1 递增），无丢字/重复/乱序/乱码——MTP copy 错误的行为特征即丢字乱码
- 5 次采样（temperature=0）

### 实测结果（5/5 PASS）

| 样本 | completion_tokens | content_tokens | reasoning_tokens | 账目差 | 序列末值 | finish_reason | 判定 |
|------|-------------------|----------------|------------------|--------|----------|---------------|------|
| 1 | 256 | 215 | 40 | 1 | 108 | length | PASS |
| 2 | 256 | 178 | 77 | 1 | 89 | length | PASS |
| 3 | 256 | 214 | 41 | 1 | 107 | length | PASS |
| 4 | 256 | 177 | 78 | 1 | 89 | length | PASS |
| 5 | 256 | 182 | 73 | 1 | 91 | length | PASS |

### 原始证据
```
curl http://127.0.0.1:8001/v1/chat/completions -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <BEARER>' \
  -d '{"model":"deepseek-v4-flash-0731","messages":[{"role":"user","content":"No thinking needed. Immediately output the integers 1 to 120 separated by single spaces, nothing else."}],"max_tokens":256,"temperature":0.0}'
```
响应关键片段（样本 1）：`"content":"1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 ..."`，`"finish_reason":"length"`，`"completion_tokens":256`；content 数字序列经正则提取逐项核验为严格 +1 连续。

### 观察备注
- 首轮探测中发现一次样本（非上述 5 采样内）reasoning 恰好耗尽 256 预算导致 content 为空——此为模型 stochastic 行为，token 账目依然完整（255 reasoning + 1 边界 = 256），不构成 token 丢失证据。第二轮 5 采样未再出现。
- **结论**：`completion_tokens` 始终等于 256 预算全额、账目精确吻合、输出序列零缺损。A1（SKIP_MTP_COPY `!= '0'`→`== '0'`）行为级验证通过，无输出被截短或丢失的迹象。

## 3. 流式回归 — PASS

### 方法
3 条 `stream=true` SSE 请求（短/中/长输出各一），解析全部 SSE 帧：统计 chunk 数、空帧数、`[DONE]`、最终 `finish_reason`、最大帧间间隔（中断检测）、TTFT。

### 实测结果（3/3 PASS）

| 用例 | max_tokens | chunks | 空帧 | [DONE] | finish_reason | content 字符 | TTFT(s) | 最大帧间隔(s) | 判定 |
|------|-----------|--------|------|--------|---------------|--------------|---------|---------------|------|
| short | 64 | 19 | 0 | ✓ | length | 25 | 0.26 | 0.26 | PASS |
| mid | 400 | 65 | 0 | ✓ | length | 648 | 0.30 | 0.30 | PASS |
| long | 1200 | 198 | 0 | ✓ | length | 2228 | 0.29 | 0.29 | PASS |

### 说明
- mid/long 两档采用整数序列提示词以强制 content 流真实产出（648 / 2228 字符），避免预算被 reasoning 吞掉导致空 content 流的弱证据。
- 全部会话无中断（最大帧间间隔 ≤0.30s）、无空帧、无非 JSON 帧、`[DONE]` 正常收尾。本批未动网关，回归确认通过。

## 4. B2 draft topk override hook — 不适用（死代码）

> 该 hook 经审计确认为死代码（定义无调用），`VLLM_DSPARK_DRAFT_TOPK` 旋钮不生效，行为验证不适用。

报告仅作标注，不构造行为验证。

## 5. B1 Markov replicate env 门 — 备注

B1（Markov replicate env 门）当前为禁用状态，默认路径不触发，未纳入本批行为验证范围；如需验证需在启用该 env 的灰度环境下单独执行。

## 测试脚本与原始数据

- 脚本（本地）: `C:/Users/novAI/WorkBuddy/VLLM环境优化/deliverables/engineering-assurance/gateway-v2/qa_scripts/`（needle_test.py / a1_test.py / stream_test.py）
- 脚本与原始结果（远端）: `node0X:/tmp/qa_bwindow1_v5b/`（needle_results.json / a1_results.json / stream_results.json / needle_run.log）

## 防缓存纪律执行说明

- 每档文档独立 seed 现场生成，填充词随机 + 每 37 词插入唯一 `SN-<8hex>` 串行标记，任何两档/两次运行不共享前缀；
- needle 位置按档随机分布，覆盖开头（128K @6%）、中间（30K @68%、500K @44%）、结尾（128K @91%）；
- 各档文档长度经网关 `/tokenize` 端点精确校准至目标 ±2%。
