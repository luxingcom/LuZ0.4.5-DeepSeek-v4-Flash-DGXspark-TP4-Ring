# VL 网关完善 + 识图测试方案报告

**报告**：vl-gateway-vision-test-plan-2026-09-08.md
**编写**：Tessa（测试专家，EngineeringAssuranceTeam）｜ **团队**：engineering-bwindow1-audit
**性质**：只读规划 + 本地测试脚本（未修改任何服务器文件、未触碰生产）
**事实来源**：node01 `~/.local` 无 proxy 代码（proxy 实际在 `<INSTALL_DIR>/scripts/concurrency_proxy_v2.py`，systemd `ExecStart=/usr/bin/python3 ...` 实证）；8003 实际在 **node02**`<HOME_DIR>/responses_gateway/main.py`（进程 pid 527473 cmdline 实证）。

---

## A. 网关完善方案（设计稿，供主理人审）

### A.1 8001 代理长 prompt 路由（R1 缓解：VL 单引擎形态）

#### A.1.1 现状核实（只读实证）

- 代理源码：`<INSTALL_DIR>/scripts/concurrency_proxy_v2.py`（649 行，md5 `0606e1e2...`，VERSION `concurrency-proxy-v2-rc3.6.1`），aiohttp，systemd `concurrency-proxy-v2.service`。
- 现役 env：`MAX_CONCURRENCY=6`、`GW_API_KEY`（已设）、**`INJECT_ENABLE_THINKING=1`**（`/etc/systemd/system/concurrency-proxy-v2.service.d/inject.conf` drop-in）。
- 代理**无任何模型名/长度校验**，全量转发 8001→8002（审计结论一致）。

#### A.1.2 关键设计判断：VL 单引擎形态下 R1 的正确姿势

> **>12K 纯文本 prompt 必须直接 4xx 拒绝，而非路由。**

理由：8002 单引擎同一时刻只服务一个模型。V5b 转回退备用后**文本线引擎不存在**——「路由到文本线模型名」的请求会被 VL 引擎以 404 model not found 拒绝（更糟：若调用方直接打 8001 用旧模型名，错误来自引擎侧，语义混淆）。交接报告 §8.1 的「长纯文本路由建议」隐含 V5b 并存双活前提，而**并存双活需上层路由，属后续工程项**（§8.1 原文）。单引擎形态下唯一安全姿势 = 网关侧提前拒绝 + 明确报错文案，让调用方自行改写 prompt（压缩/分段）。

#### A.1.3 方案设计（改动定位到行号）

**改动位置**（`concurrency_proxy_v2.py`，行号基于现役 md5 `0606e1e2` 版本）：

1. **旋钮定义**（第 117-118 行 `INJECT_ENABLE_THINKING`/`VERSION` 附近新增）：
   ```python
   TEXT_PROMPT_TOKEN_LIMIT = int(os.environ.get("TEXT_PROMPT_TOKEN_LIMIT", "0"))   # 0=off
   ```
   另建议 `VL_TEXT_REJECT_CODE = os.environ.get(..., "413")`（默认 413 Payload Too Large，语义贴切；如调用方框架只认 400 可切）。
2. **判定函数**（第 219 行 `maybe_inject` 之后新增，约 246 行处）：
   ```python
   def text_prompt_over_limit(body: bytes, path: str) -> int | None:
       """纯文本 prompt token 估算超限检测（VL 单引擎 R1 缓解，rc3.7）。
       返回估算 token 数（超限时）或 None。仅拦 chat/completions 与 completions
       POST 路径；含 image 内容的多模态请求不拦（#4973 风险面=纯文本）。"""
       if TEXT_PROMPT_TOKEN_LIMIT <= 0:
           return None
       if not (("/chat/completions" in path) or ("/completions" in path)):
           return None
       if b'"image_url"' in body or b'"input_image"' in body:
           return None                     # 多模态请求放行
       try:
           obj = json.loads(body)
       except Exception:
           return None                     # 非法 body 走原转发逻辑（上游报 400）
       texts = []
       for msg in (obj.get("messages") or []):
           if not isinstance(msg, dict):
               continue
           c = msg.get("content")
           if isinstance(c, str):
               texts.append(c)
           elif isinstance(c, list):
               texts += [p.get("text", "") for p in c
                         if isinstance(p, dict) and p.get("type") == "text"]
       if obj.get("prompt"):               # /v1/completions 裸 prompt 字段
           texts.append(obj["prompt"])
       n_chars = sum(len(t) for t in texts)
       # 中文主导语料 ~1 token/字（vLLM DeepSeek tokenizer 中文≈0.9-1.1）；
       # 英文 ~4 chars/token → 1/4。取保守并集：中文按 1.0、ASCII 按 0.3 折算
       ascii_n = sum(1 for t in texts for ch in t if ord(ch) < 128)
       est = (n_chars - ascii_n) * 1.0 + ascii_n * 0.3
       if est > TEXT_PROMPT_TOKEN_LIMIT:
           return int(est)
       return None
   ```
   **token 估算选型说明**：网关无 tokenizer 依赖（轻量约束），采用**字符比启发式**——非 ASCII（中文等）1 token/字、ASCII 0.3 token/字符。依据：DeepSeek 系 tokenizer 中文≈0.9-1.1 token/字、英文≈3.5-4.5 chars/token；0.3 偏保守（高估），保证**宁可误拦不漏拦**（R1 是 IMA 崩溃级风险）。若未来要求精确，可在 node01 用 HF tokenizer 离线拟合系数后再调 env，不需要改代码结构。
3. **拦截点**（`dispatch` 第 604-606 行附近，`maybe_inject` 调用之后、`is_stream` 之前）：
   ```python
   body = await request.read()
   if request.method == "POST":
       body = maybe_inject(body, request.path)
       # rc3.7：VL 单引擎 R1 缓解——>阈值纯文本 prompt 直接拒绝（无文本线可路由）
       est = text_prompt_over_limit(body, request.path)
       if est is not None:
           METRICS["rejected_text_prompt_limit"] = METRICS.get("rejected_text_prompt_limit", 0) + 1
           return web.json_response(
               {"error": {"message":
                   f"text-only prompt too long (~{est} tokens > "
                   f"{TEXT_PROMPT_TOKEN_LIMIT}); vision engine cannot serve "
                   f"long pure-text prompts (known upstream issue #4973). "
                   f"Shorten the prompt or attach images.",
                   "type": "gateway_text_prompt_limit", "code": 413}},
               status=413)
   ```
   拦截在 `maybe_inject` **之后**可复用已 parse 的思路（但注意：inject 失败/未开时 body 未解析——上面函数自带 `json.loads`，与 rc3.4 prefilter 一样仅对 POST chat 路径解析，非流式常见请求已被 `is_stream` 的 prefilter 证明可承受）。
4. **metrics**：`METRICS` dict（第 125 行附近）加 `"rejected_text_prompt_limit": 0`。
5. **systemd unit** 增 env：`Environment=TEXT_PROMPT_TOKEN_LIMIT=12000`（交接建议阈值 12K，Gate4 哨兵 13.6K 留裕量）。
6. **版本**：`VERSION` bump 至 `rc3.7`（沿用版本纪律），`/gw/health` 可见。
7. **部署纪律**（对齐既有惯例）：改前 `cp concurrency_proxy_v2.py concurrency_proxy_v2.py.bak-rc3.6.1-<date>`；改后 `systemctl restart concurrency-proxy-v2`；首日人工 watch（unit 注释明示自愈链只探 8002）。

**性能影响**：只对 POST chat/completions 且无 image 键的请求多一次 `json.loads`——与 rc3.4 已论证的 `is_stream` prefilter 同量级（数 MB body 数 ms~数十 ms）；600K token 极端 body 在 64MB client_max_size 内，json.loads 一次可承受（且该请求本来就要被拒，早拒省了引擎 prefill）。

**默认 off 零行为差**：`TEXT_PROMPT_TOKEN_LIMIT=0`（未设/0）时函数第一行即返回 None——与 INJECT 门同款「off=现行为零变化」纪律，可先合码后开阈值。

#### A.1.4 测试用例清单（8001 长 prompt 门）

前置：node01 影子端口起 rc3.7 实例（如 PORT=18001 UPSTREAM=127.0.0.1:8002），勿直改现役。

| # | 用例 | 预期 |
|---|---|---|
| T1 | env 未设（默认 off）+ 15K 字纯文本 | 放行（零行为差回归） |
| T2 | LIMIT=12000 + 13K 字中文纯文本 | 413 + 明确文案（含 #4973 提示） |
| T3 | LIMIT=12000 + 11K 字中文纯文本（阈值下） | 放行 |
| T4 | LIMIT=12000 + 40K 字英文（估算 ~12K） | 413（ASCII 0.3 系数路径） |
| T5 | LIMIT=12000 + 15K 字文本 **+ 1 张图** | 放行（多模态豁免） |
| T6 | LIMIT=12000 + 非法 JSON body | 放行走原逻辑（上游 400） |
| T7 | LIMIT=12000 + /v1/responses 15K 文本 | 放行（responses 路径不拦——8003 的 responses 线暂无 VL 消费方；如需覆盖再扩 path 判定） |
| T8 | LIMIT=12000 + /v1/completions 裸 prompt 15K | 413 |
| T9 | GET /gw/metrics | `rejected_text_prompt_limit` 计数与用例数一致 |
| T10 | 拦截请求不占用并发槽语义复核：413 发生在 acquire 之后 → finally release 正常，连发 20 个超限请求后正常请求仍可入（无槽泄漏） |
| T11 | stream=true + 15K 纯文本 | 413（非流式 JSON 错误，不进 SSE 分支——拦截点在 is_stream 判定前） |

⚠️ T10 注意：现设计拦截点在 `acquire_or_none` 之后（dispatch 内），被拒请求占槽 <1ms 即释放，无泄漏；但若想完全不占槽，可上移到 acquire 之前（body 读取需在槽内……不行，`await request.read()` 也在槽内）。结论：**维持槽内拦截**，语义正确（读 body 本身就是网关工作），T10 是回归断言而非缺陷。

#### A.1.5 待主理人决策点

1. **阈值定 12000 还是更高**？R1 实测崩点 ~13.6K，12K 有 12% 裕量；若调用方有合法 12-13K 长文本诉求会误伤（但该诉求在 VL 单引擎下本来就会崩，早拒优于晚崩）。
2. **413 还是 400**？413 语义准；但部分客户端 SDK（含 WorkBuddy openai 兼容层）对 4xx 一视同仁，无差别。默认 413。
3. **responses 路径是否同拦**（T7 现不拦）：8003 的 /v1/responses 线若未来有 VL 消费方需扩。

### A.2 8003 网关模型映射（node02 main.py，v2.0-slim 409 行）

#### A.2.1 现状核实（只读实证，node02 `<HOME_DIR>/responses_gateway/main.py`）

- **model 校验为严格白名单**：`MODEL_ALIAS = {PUBLIC_MODEL: SERVED, LEGACY_MODEL: SERVED, SERVED_MODEL: SERVED}`；`deepseek-v4-flash-vision-exp` **不在表内 → chat/completions 与 /v1/responses 均 404 `model_not_found`**（`if model not in MODEL_ALIAS: return 404`，chat 路由约 297-300 行、responses 路由约 218-221 行）。
- **/v1/models 列表不含 VL**：`list_models` 只列 `PUBLIC_MODEL`（`local-v4-flash`）、`SERVED_MODEL`（`deepseek-v4-flash-0731`）、`LEGACY_MODEL`（`deepseek-v4-flash`）。
- 环境实况（进程 env 实证）：`SERVED_MODEL=deepseek-v4-flash-0731`、`PUBLIC_MODEL=local-v4-flash`、`LEGACY_MODEL=deepseek-v4-flash`。**SERVED_MODEL 是 env 驱动的**——这是最小改动路径的关键。

#### A.2.2 最小改动方案（两案，建议 B 案）

**B 案（env-only，零代码改动，推荐用于切换窗口）**：
切换 VL 时改 8003 的启动环境：`SERVED_MODEL=deepseek-v4-flash-vision-exp`。
- 效果：`local-v4-flash`/`deepseek-v4-flash`/`deepseek-v4-flash-vision-exp` 三个名全部映射到 VL；`deepseek-v4-flash-0731` 将 404（文本别名退役，符合单引擎事实）。
- **代码零改动**，回退 = env 改回 + 重启，切换窗口风险最小。
- 缺点：旧模型名 0731 调用方会 404——但这恰恰正确（单引擎下它本来就无法服务），且 404 文案 `model_not_found` 明确。

**A 案（加 VL 别名条目，代码改动 3 行）**：若需 **0731 与 VL 别名并存暴露**（供调用方灰度切换），在 `MODEL_ALIAS` 构造后加：
```python
VL_SERVED_MODEL = os.environ.get("VL_SERVED_MODEL", "")   # ~line 70 SERVED_MODEL 之后
if VL_SERVED_MODEL:
    MODEL_ALIAS[VL_SERVED_MODEL] = VL_SERVED_MODEL
```
及 `list_models` 的 `data` 列表加：
```python
    if VL_SERVED_MODEL and VL_SERVED_MODEL not in (PUBLIC_MODEL, SERVED_MODEL):
        data.append({"id": VL_SERVED_MODEL, "object": "model", "created": now, "owned_by": "deepseek"})
```
（注意：A 案下 0731 仍映射到它自己——但单引擎时代打 0731 名会被 8002 VL 引擎 404，错误从 8003 提前拦下反而更干净。若要 0731 名映射 VL，那是 B 案行为。）

**建议**：切换窗口用 **B 案**（零代码、零回退成本）；A 案作为后续需要多别名灰度时再上（需走 golden AC 回归，v2.0-slim 的 golden AC-1..AC-10 纪律）。

**8003 侧配套验证用例**：
| # | 用例 | 预期（B 案） |
|---|---|---|
| G1 | GET /v1/models | 含 vision-exp，不含 0731 |
| G2 | chat model=local-v4-flash + 图 | 200 识图正常（别名→VL） |
| G3 | chat model=deepseek-v4-flash-vision-exp + 图 | 200 |
| G4 | chat model=deepseek-v4-flash-0731 | 404 model_not_found |
| G5 | /v1/responses model=local-v4-flash 带 image input | 200/或明确的能力错误（responses 线 VL 图输入能力待实测，见 B 测试计划遗留） |
| G6 | 回退演练：env 改回 0731 重启 → G1-G4 反向成立 | 回退链完整 |

---

## B. VL 识图测试方案（摘要）

产物（本地落盘，VL 上线后拷 node01 执行）：
`deliverables/engineering-assurance/vl-deployment/vl_vision_tests/`
- **vision_gates.py** — 视觉五门复刻（g1 单图颜色 / g2 四图顺序 / g3 跨图跨度 / g4 图内 GSM / g5 投机形态），与 boot2 w2_gates.py 判据同源；PIL 现场生成色块/数字图（node01 已实测 Pillow 10.2.0 可用，无 PIL 时 stdlib PNG 兜底）；入口 127.0.0.1:8001、Bearer 走 `GW_API_KEY` env 注入、urllib 标准库实现（node01 无 openai 包，已实测）。
- **vision_edge_tests.py** — E1 多轮带图对话 / E2 4200px 超大图 / E3 灰度+低对比 / E4 图+3K 文混合 / E5 纯文本 GSM 退化 / E6 并发 4 路识图。
- **test_plan.md** — 完整测试计划：每用例判定标准、boot2 对应关系、跑批顺序（预检→五门 3-6min→边界 5-10min）、FAIL 处置矩阵（五门任一 FAIL=回退决策线；E1-E4 观察门；E5/E6 升级线；Xid/IMA 立即留证回退）、覆盖缺口清单（多轮/超大图/鲁棒性/并发正确性已补；视频、JPEG/WebP、流式识图 SSE 记为下窗观察项）。

两脚本已通过：本地 py_compile + 判定逻辑静态冒烟 ✅；node01 python3.12 ast.parse 语法验证 + 环境错误路径实测（不可达端口正确退出码 2）✅。**当前 V5b 现役时不可执行**（model 名会 404，属预期）。

关键执行注意（详见 test_plan.md §4.4）：DEDUP=1 勿并发重跑同 payload；8001 INJECT_ENABLE_THINKING=1 若致 VL 模板报错需先分辨网关配置问题再判模型 FAIL。

---

## C. 待主理人决策点清单

| # | 决策点 | 我的建议 |
|---|---|---|
| 1 | 8001 长纯文本门阈值（12K/13K/其他）与拒绝码（413/400） | 12000 + 413 |
| 2 | 8001 门默认 off 合码、切换窗口开 env（分步）还是一步到位 | 分步（先合码回归，窗口再开） |
| 3 | 8003 用 B 案（env 切 SERVED_MODEL，零代码）还是 A 案（加 VL 别名代码） | 切换窗口 B 案；A 案留灰度需求 |
| 4 | /v1/responses 路径是否纳入长文本拦截（现设计不拦） | 暂不拦，responses 线 VL 消费方出现后再扩 |
| 5 | 五门 g4 由纯文本 GSM 升级为图内数字数学（更强门）是否接受 | 接受（纯文本 sanity 归 Runbook #2/E5） |
| 6 | 流式（stream=true）识图 SSE 链路测试列为下窗观察项 | 是（生产 WorkBuddy 走 SSE，建议优先补） |
| 7 | rc3.7 改动的评审/部署 owner（code-reviewer 复审 + SRE 部署？） | 按团队惯例走 code-reviewer 复审 |

## D. 审核中发现的事实修正（对任务书的补充）

1. 任务书说 proxy 路径「自查 `~/.local/lib/python3.12/site-packages/`」——实际 proxy 不在用户 site-packages，而在 `<INSTALL_DIR>/scripts/concurrency_proxy_v2.py`（systemd ExecStart 实证）；`~/.local` 只有 aiohttp 等。已按实际路径给行号。
2. 8003 在 **node02** `<HOME_DIR>/responses_gateway/main.py`，非 node01；v2.0-slim 实际 409 行属实，model 严格白名单 404 逻辑在 chat/responses 两路由内。
3. 8001 现役已有 `INJECT_ENABLE_THINKING=1` drop-in——rc3.7 改动与注入功能叠加时序已在设计中处理（拦截在注入之后），但 VL 切换后该注入对 VL chat 模板的兼容性需在切换窗口验证（已列入 test_plan §4.4 注意项）。
4. 8003 进程 env 里有 `UPSTREAM_API_KEY=<32字节hex>`（v2.0-slim 已声明为死代码槽位不注入），**建议顺带确认该值是否为遗落的真实密钥并清理**（安全卫生项，非本任务范围，报告备案）。
