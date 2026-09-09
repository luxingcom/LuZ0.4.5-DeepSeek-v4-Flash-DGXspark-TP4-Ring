# 窗口执行报告 — 2026-09-07（B窗1 + E窗0 + baked6 首boot）

窗口范围：运维 V5b 上产后的第一个停机窗。计划四项：k=5 A/B、C1 叠加验证、E1 归因、baked6 VL 切换+W2 门。实际完成前三项，baked6 boot 触发 IMA 转专项，生产已恢复运维基线（k=7，health=200，sanity 正确）。

---

## 1. 执行时间线（6 次 guard 重启）

| boot | 形态 | 结果 |
|---|---|---|
| 1a | V5b@k=5（变体分发到错误路径 /opt/_PH_INSTALL_/scripts/） | **失败**：workers 仍 k=7、head k=5，缓冲不一致 → rank0 shm_broadcast 挂起。教训：**变体必须放各节点 ~/w6-kit/（live 脚本真身所在），且切换后必须 md5 验证** |
| 1b | V5b@k=5（分发修正后） | ✅ 5min ready |
| 2 | V5b@k=5+C1（MARKOV_REPL=1 四机） | ✅ 4.5min ready |
| 3 | V5b spec-off（E1 文本侧） | ✅ 4min ready |
| 4a | baked6 vision spec-off（E1 vision 侧） | **卡死**：rank0 等 shm_broadcast 19min；清四机 autotune 缓存走冷路径重试 |
| 4b | 同上（冷 autotune） | **rank1 CUDA illegal memory access**（16:24:09，图捕获期 cap-snap n=320 后）→ 中止，转专项 |
| 5 | 恢复运维基线（k=7 原版 live） | ✅ 5min ready，sanity「9.11 vs 9.9」回答正确 |

## 2. k 决策：维持 k=7（数据定案）

| 口径 | k=7 基线 | k=5 实测 | 判定 |
|---|---|---|---|
| t(5) 单流 ITL（prose，137 chunks） | 49.7ms | 48.1ms（boot1）/ 49.4ms（boot2+C1） | **> 46.8ms 决策门，不过** |
| 截断精确性（k5 前5位 vs k7 审计） | — | prose/code/json 三负载形态一致 ✓ | 门过（无截断副作用） |
| 净收益估算（A5/A7 × t7/t5） | — | prose +5% / code 持平 / json +1% / **背景混合 −12%** | 混合负载净负 |

**结构性发现**：步时几乎不随 k 下降（draft 链 3 层 MoE 读主导步时，verify token 数变化被掩盖）——与 voktolom 同拓扑结论一致。k=7 的尾部两位在背景混合（含工具调用/重复模式负载）贡献 0.35 token/步，砍掉伤害大于步时节省。**生产保持 k=7。**

## 3. C1（Markov 双复制）判定：保留但预期修正

- 四机 env 激活确认、boot 正常、GSM8K 10/10（初测 8/10 中 2 题为 512-token 截断空提取，1024 重测实质全对：282.33/40）
- **单流步时无显著改善**（49.4 vs 48.1ms，噪声内）——"+2~4% 步时"预期未兑现（单流口径）。可能收益在多并发（通信/计算重叠恶化时），留指标观察
- V5b 镜像内 env 门默认关，生产未启用（运维基线形态），无需回退

## 4. E1 归因：文本侧完成，vision 侧待 baked6 修复

- **spec-off 单流步时（0731）= 29.1ms**（两次独立一致：29.16/29.10）
- 投机附加成本（k=7）= 20.6ms/步；净收益 = 3.89 tok/步 ÷ (49.7/29.1) = **2.3× vs 无投机**
- vision 侧对照（baked6 spec-off）因 boot IMA 未取得。E1 判据（Δ≥6ms 权重侧/≤3ms 部署侧）待补
- 现有替代证据链（W2：90.6→65.5 + 社区 voktolom"checkpoint draft-head 主导"）继续支持权重侧定性

## 5. baked6（VL 分支镜像）：构建交付 ✅ / boot IMA ❌ → 专项

- **构建成功**：FROM V5b；三方对比（G1r6 基座 vs V5b vs VL overlay）定案 18 文件直拷（V5b 各层未触碰，g16==v5b 实证）+ 4 新文件（vl_model/vl_stub/vision/mm_preprocess[baked4 终版]）+ 2 merge（model.py=VL+SKIP 修复；cache_utils.py=VL+A3 #55636 防护）+ TK512 cu；构建五门全绿（py_compile 439 文件/VL 注册/merged 补丁/TK512/基座特性）；四机预拉完成。**V5 的 2×60MB commit 层经比对未触及 24 个 overlay 目标文件**（之前的未鉴定风险解除）
- **boot 失败**：rank1（node02）在 CUDA graph 捕获期 IMA（ProcessGroupNCCL watchdog，16:24:09），rank0 停 shm_broadcast 等待。清 autotune 缓存冷路径重试复现 → 非缓存死锁，是真实 IMA
- **取证留档**：node02 rank1 容器日志（watchdog traceback 全文）、node01 rank0 日志（TileLang 16:02 完成 → NCCL V5 cap-snap n=320 → 挂起）、VL 注册与权重加载均正常（Resolved: DeepseekV4ForConditionalGeneration、96.7s/42.68GiB）
- **嫌疑排序**：①#4973 同族（SM120 vision IMA，长 prompt/warmup 触发）②V5 层（NCCL V5 patch/cap-snap 机制，boot1 时间线在 W2 baked4 时代不存在）与 VL 图捕获交互 ③baked6 某文件与 V5b 层的半新半旧（三方对比显示无，但 24 文件外的交互面未查）
- **专项入口**：镜像/上下文/脚本全在库（`vl-baked6-ctx/`、`VL-baked6` 四机、变体 `.b6e1v/.b6`），下次窗口可用 `--enforce-eager` 或禁 graph capture 二分 IMA 发生层；logdump 开启复现

## 6. 生产最终状态

- 镜像/脚本/形态 = 运维 V5b 基线（k=7、mmlen 600K、KV 池 5.25M、C1 门关）
- health=200、sanity 正确、四机 healthy、零错误行
- 现场还原：live 脚本 = `.bak-window-20260907`（备份留在四机 ~/w6-kit/）；autotune 缓存已还原；变体脚本族（.k5/.k5c1/.e1t/.b6e1v/.b6）留在四机 ~/w6-kit/ 备用

## 7. 遗留清单

1. **baked6 IMA 专项**（最高优先）：按 §5 入口二分；修复后补 E1 vision 侧 + W2 三门 + baked6 上线决策
2. needle 长上下文验证：30K/128K 过（内容未抓取，仅延迟正常 11.2s/52.6s），500K 超时（240s 不够，600K prefill 单请求 >4min）；#54815 修复的 needle 证据待专项补（3 长度×抓内容）
3. C1 多并发收益观察（挂生产指标）
4. 窗口教训入册：变体脚本分发路径（~/w6-kit 而非 scripts/）+ 切换后必须三机 md5 验证（已有 D3 条目，本窗实证其重要性）
