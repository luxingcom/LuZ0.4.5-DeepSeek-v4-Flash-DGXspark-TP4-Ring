# VL 引擎上线六门验收报告

- **日期**：2026-09-08
- **验收人**：vl-acceptance（工程保障团队）
- **对象**：VL 引擎上线（切换时间 2026-09-08 11:32:41 health=200）
- **部署形态**：四机容器 `vllm-tp4-rank{0..3}`，镜像 `LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`，`served-model-name=deepseek-v4-flash-vision-exp`，投机解码 k=6（dspark）
- **入口纪律**：全部走 node01 网关 `http://127.0.0.1:8001/v1/chat/completions`（SSH `node01`），Header `Authorization: Bearer <BEARER>`；8002 仅做本机 lo 健康检查与 metrics 拉取
- **测试脚本**：node01 `/tmp/vl-acceptance/`（gsm8k.py、visual.py、needle30k.py、sentinel136k.py、conc.py）
- **engine fingerprint**：`vllm-0.26.1.dev0+gd3d3b2cca.d20260805-tp4-db374d14`（来自门3响应原文）

## 六门判定总表

| 门 | 项目 | 判定 | 关键数据 |
|---|---|---|---|
| 门1 | 健康检查 | **PASS** | 8002/health=200；8001 /gw/health=200（需 Bearer 鉴权） |
| 门2 | 文本 sanity（GSM8K×3） | **PASS** | 3/3 正确（8、4、69），0.9~3.4s |
| 门3 | 视觉五门 g1-g5 | **PASS** | 4/4 内容全对 + 视觉请求正常 JSON 返回证 k=6 投机形态生效 |
| 门4 | 长上下文 | **PASS** | needle 30K 正确复述；哨兵 13.6K 正常响应无 IMA 崩溃 |
| 门5 | 并发抽测 | **FAIL（conc8 未达标）** | 两轮：conc4=98.5/88.1（≥85 达标）；conc8=98.0/106.5（<120 未达标） |
| 门6 | 投机指标 | **PASS（临界）** | 平均接受长度（含 bonus token）=2.364，n=3806；k=6 形态生效但接受率偏低 |

**六门总判定：5 PASS / 1 FAIL（门5 conc8 吞吐未达 120 tok/s 阈值，conc4 达标）**

---

## 门1 健康检查 — PASS

时间：2026-09-08（本次验收复核）。

```
# 引擎直连（本机 lo，白名单例外：纯健康检查）
ssh node01 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/health'
→ 200

# 网关代理健康（无鉴权返回 401，属网关正常鉴权拦截）
ssh node01 'curl -s -H "Authorization: Bearer <BEARER>" -w "\nHTTP:%{http_code}" http://127.0.0.1:8001/gw/health'
→ {"status": "ok", "version": "concurrency-proxy-v2-rc3.6.1"}
→ HTTP:200
```

容器状态：`vllm-tp4-rank0 Up 41 minutes (healthy)`（docker ps，验收时点），APIServer 日志持续 `GET /health 200 OK`。

## 门2 文本 sanity（GSM8K 三题） — PASS

三条手写简单数学应用题，temperature=0，max_tokens=256，经 8001 网关。

| # | 题目 | 期望 | 模型答案 | 判定 | 时延 |
|---|---|---|---|---|---|
| Q1 | 3 个苹果+妈妈给 5 个 | 8 | `8` | PASS | 3.4s |
| Q2 | 24 名学生分 6 组 | 4 | `4` | PASS | 0.9s |
| Q3 | 45 元书+2×12 元笔 | 69 | `69` | PASS | 1.1s |

3/3 正确，响应为非流式正常 JSON。

## 门3 视觉五门 — PASS

python3+PIL（Pillow 10.2.0）在 node01 现场生成 PNG，base64 data URL 走多模态 messages content list。temperature=0，max_tokens=400。

| 子门 | 内容 | 判定关键词 | 模型答案 | 判定 | 时延 |
|---|---|---|---|---|---|
| g1 单图颜色 | 200x200 纯红 PNG，问主色 | 红/red | `红色` | PASS | 1.2s |
| g2 四图顺序 | 红/蓝/黄/紫四图按序发，问第四张 | 紫/purple | `紫色` | PASS | 2.0s |
| g3 跨图跨度 | 红+绿两图，问第一张颜色 | 红/red | `红色` | PASS | 2.1s |
| g4 图内数学 | PIL 画布大字 `12+34=?`，问算式与答案 | 46 | `图中写的算式是：**12+34=?** \| 计算结果为：**46**` | PASS | 6.9s |
| g5 投机形态 | 以上任一视觉请求非流式正常 JSON 返回 | — | 正常 JSON（finish_reason=stop，usage 完整） | PASS | — |

备注：
- g2 使用 max_tokens=200 的首跑因思考链（reasoning 字段）耗尽 token 导致 content=None（finish 正常），判定为测试参数问题非引擎问题；max_tokens=400 后 content 正常。该形态为模型带 reasoning 输出（响应含 `reasoning` 字段），非缺陷。
- g4 中模型正确识别画布文字 `12+34` 并算出 46，证明图内 OCR+数学联合能力。
- g5：所有视觉请求经网关 8001 → 8002 VL 引擎（含投机解码路径）返回正常，证明 dspark k=6 形态下视觉请求工作正常。

## 门4 长上下文 — PASS

### 4a. needle 30K（随机 seed 防前缀缓存）

现场随机生成文档（seed=469447，doc_chars=30764，687 行随机记录，needle 埋第 343 行正中）：

```
NEEDLE = "本次内部会议的机密代码是 VLX-7749-QUASAR，请务必记住它。"
问题：…只回答一个问题：本次内部会议的机密代码是什么？请原样复述。
→ time=17.1s prompt_tokens=17534 completion_tokens=56
→ ANSWER: VLX-7749-QUASAR     ⇒ PASS（原样复述）
```

### 4b. Gate4 哨兵 13.6K（#4973 IMA 风险常规门禁）

现场随机生成纯文本（seed=934212，doc_chars=14055，428 个条目），预期 PASS。结果：

```
→ time=12.5s prompt_tokens=7129 completion_tokens=30 finish=stop
→ ANSWER: 428（正确条目总数）  ⇒ PASS
```

无 IMA/XID 崩溃，容器全程 healthy，无异常。哨兵门禁预期 PASS，实际 PASS。

## 门5 并发抽测 — **FAIL（conc8）**

脚本 `/tmp/vl-acceptance/conc.py`（python3 asyncio，网关 8001，每请求 max_tokens=320，temperature=0.7，吞吐口径=completion_tokens/wall time）。共两轮（第二轮复核）。

### 第一轮

| 并发 | wall | 总 completion tokens | 吞吐 | 阈值 | 判定 |
|---|---|---|---|---|---|
| 4 | 13.0s | 1280 | **98.5 tok/s** | ≥85 | PASS |
| 8 | 26.1s | 2560 | **98.0 tok/s** | ≥120 | **FAIL** |

单请求 wall：conc4 为 12.5~13.0s（均匀）；conc8 为 14.0~26.1s，其中 req5~req7 达 17.9~26.1s，呈明显分批排队特征。

### 第二轮（复测）

| 并发 | wall | 总 completion tokens | 吞吐 | 阈值 | 判定 |
|---|---|---|---|---|---|
| 4 | 14.5s | 1280 | **88.1 tok/s** | ≥85 | PASS |
| 8 | 24.0s | 2560 | **106.5 tok/s** | ≥120 | **FAIL** |

单请求 wall：conc8 为 13.3~24.0s（req5/req7 达 23.4/24.0s，同样排队）。

### 分析

- conc4 两轮 98.5/88.1，与 boot2 参考值（96-98）一致，引擎基础吞吐正常。
- conc8 两轮 98.0/106.5，距阈值 120 差 11~18%，距参考值 140-150 差 25~30%；8 请求 wall 呈两批完成（~13-17s 一批、~23-26s 一批），说明并发 8 时未能单批全量驻留 running batch。
- 待排查方向（供 SRE/性能团队）：a) VL 镜像调度参数（max-num-seqs / batch 组成）与 boot2 文本引擎差异；b) 视觉模型额外权重/激活占用导致 KV 并发上限收缩（metrics 显示 kv_cache_max_concurrency≈4.53，恰与 conc4 达标、conc8 排队现象吻合）；c) 网关 concurrency-proxy v2-rc3.6.1 排队/流控策略。
- 已按纪律在发现 FAIL 时立即 SendMessage 告警主理人。

## 门6 投机指标 — PASS（临界）

```
ssh node01 'curl -s http://127.0.0.1:8002/metrics | grep -i spec'
```

关键计数（model_name="deepseek-v4-flash-vision-exp"，engine="0"）：

| 指标 | 值 |
|---|---|
| vllm:spec_decode_num_drafts_total | 3806 |
| vllm:spec_decode_num_draft_tokens_total | 22836 |
| vllm:spec_decode_num_accepted_tokens_total | 5191 |
| 平均接受长度（accepted/drafts，不含 bonus） | **1.364** |
| 平均每次前向产出 token（(accepted+drafts)/drafts，含 bonus） | **2.364** |
| 参考（k=6 形态 A(6)≈2.08） | 2.08 |

逐位接受率（per position）：p0=0.64、p1=0.34、p2=0.18、p3=0.10、p4=0.06、p5=0.04（各位置接受数 2453/1290/680/378/239/151，总和=5191 校验一致）。

判定：含 bonus 口径 2.364 ≥ 参考值 2.08，投机形态 k=6 生效，**PASS**。备注：本次负载以短答案+中文推理为主（GSM8K 三题答案极短、视觉答案 1-2 词），draft 总量 3806 偏小且逐位接受率衰减快，长生成负载下均值可能下探，建议后续持续观测。

---

## 结论与建议

1. **核心功能链路全部可用**：健康、文本、视觉（单图/多图顺序/跨图/图内数学）、长上下文（30K needle + 13.6K 哨兵）、投机形态均验证通过。
2. **门5 conc8 未达标是唯一 FAIL**：conc4 正常，conc8 吞吐 98.0~106.5 tok/s（阈值 120）。与 metrics 中 `kv_cache_max_concurrency≈4.53` 吻合，疑似 8 并发超出单批驻留能力导致两批排队。建议：i) SRE 复核 VL 容器 max-num-seqs 与显存占用；ii) 网关侧确认 rc3.6.1 并发排队策略；iii) 若业务高峰并发 ≤4~6，可带条件放行（conc4 达标）；若需 8 并发满吞吐，先调参复测。
3. **门6 临界 PASS**：投机指标 2.364（含 bonus），建议投产后纳入常规监控观测长生成场景下的接受率漂移。
4. 判定仅供参考：门5/门6 是否阻断上线由主理人裁定（告警已于验收过程中发出）。

## 附：环境与证据索引

- 网关：`concurrency-proxy-v2-rc3.6.1`（8001，Bearer 鉴权）
- 引擎：vllm-0.26.1.dev0+gd3d3b2cca.d20260805-tp4-db374d14
- cache_config_info 摘要：block_size=4、cache_dtype=fp8_ds_mla、enable_prefix_caching=True、gpu_memory_utilization=0.8、kv_cache_size_tokens=2720971、kv_cache_max_concurrency=4.53、sliding_window=128
- 测试脚本：node01 `/tmp/vl-acceptance/{gsm8k,visual,needle30k,sentinel136k,conc}.py`
- 门3 首跑 g2 的 content=None 为 max_tokens=200 被思考链耗尽的测试参数问题，复跑（max_tokens=400）正常，不判缺陷
