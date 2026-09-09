# G1R7-VL 窗口#3 报告 — IMA 专项公关 + PIECEWISE 修复 + F1 A/B（2026-09-08）

用户指令：IMA 专项安排停机窗口公关，启动前子代理完成社区调查；PIECEWISE 84vs88 修复与
F1 flashinfer main A/B 同窗口落实。本窗口全部达成，**VL 上生产的 FULL 图阻塞解除**。
生产已恢复 V5b 基线（k=7、health=200、sanity"9.9"正确）。

## 0. 一句话总览

| 项 | 结论 |
|---|---|
| FULL 图 IMA（窗#1 遗留，VL 上生产唯一阻塞） | **解除**。根因=0.6.18 内核族（含 TK512 手补丁）×图捕获/重放×VL；换 F1 内核（flashinfer 453aa7c）后 FULL 图 10/10 捕获干净，五门禁全绿 |
| PIECEWISE 84vs88 | **根因修正+修复落地**：非"图像哨兵计数"，而是 indexer decode 切片不变量（84=12reqs×qlen7 vs token 桶 88）。b7-fix 修好启动+单图；四图重放在旧内核仍 Xid31（内核层问题），F1 内核下 FULL 已可用的前提下 PIECEWISE 转 backlog |
| F1 A/B（pin 453aa7c） | **adopt**。功能门+数值门+性能全过；TK512 手补丁按计划退役 |
| 新约束发现 | **VL 检查点 n_predict=3 → k 必须 ∈{3,6}**（k=7 pydantic 直接拒绝）。窗#2 报告中 boot B 的 next_n=7 即 k=6 所致 |
| 下窗头号候选 | **VL k=3 A/B**：k=6 实测 A(6)≈2.08，位置 4-6 接受率 <6% 近乎死亡；上游 #54566 官方参考即 k=3 |

## 1. 调查结论（两个子代理，报告在 perf-inv/agent-reports/E-*.20260908.md）

- **E-ima-survey**（38 条带号 URL）：我们命中社区"已知家族病"象限（DSV4-Vision × SM120/121 ×
  topk512 双缓存 × mm-pad 形状 × FULL 图）。关键参照：vllm#53574（DSv4+SM120+投机**捕获期崩溃**，
  DGX Spark 独立确认；但 fork 的 build_c128a_topk_metadata 已是全宽切片，无需 cherry-pick）、
  flashinfer#5015（GB10+FULL 图+投机 padded replay 设备挂死，PIECEWISE/eager/精确 capture 干净）、
  #4012（autotune ON→捕获期必炸）、#4732（SM121 prefill hang 修复+**ninja stale .so 警告**）。
  cap-snap 嫌疑降级：四个社区案例表明 watchdog 报 IMA 多为转报；纯文本+FULL 图同 NCCL 栈正常是决定性反证。
- **E-piecewise-f1-survey**：pin 453aa7c 判定干净（sparse_mla_sm120 csrc 之后零改动），净赚 #4732；
  边界=main Python plan/dispatch 层已领先（#4955/#4811）、#4973 仍 open（故设 Gate4）。
  #4802 自带 CUDA-graph-safe wrapper + 拒绝捕获中校准；Defilan（GB10）实证换装需整组 overlay
  且移除预编译 .so 让其 JIT——本窗口构建已照此办理。

## 2. Boot 时间线（guard 全程 flock）

| # | 形态 | 结果 |
|---|---|---|
| 1a | b7pw7（首版变体，误挂 0731 文本权重） | READY——PIECEWISE+VL代码+文本权重+K7 可启动（对照样本） |
| 1b | b7pw7 改挂 VL 权重（k=7） | **秒败：`num_speculative_tokens:7 must be divisible by n_predict=3`** → 新约束发现，全变体改 k=6 |
| 1c | b7pw7（VL 权重 + PIECEWISE + k=6） | READY；g1 单图 ✅；**g2 四图 → Xid 31 MMU Fault（rank0 GPU 图形引擎非法读），worker 无 Python 异常直接死亡** |
| 2 | **b7f1full7（baked7f1 + FULL_AND_PIECEWISE + k=6 + autotune skip-ops + 独立 flashinfer-cache-f1）** | **READY；dspark FULL 图 10/10 捕获；全部门禁绿（见 §3）** |
| 3 | 恢复生产 V5b 基线 | READY health=200，sanity 通过 |

（窗#1 崩溃同形态对照：baked6+FULL+捕获=rank1 IMA → 本窗 boot2 同图模式换内核后干净。）

## 3. Boot 2（baked7f1 FULL）门禁与性能

功能门：
- W2 五门：g1 深红 ✅ / g2 四图计数 ✅（窗#2 boot B 与本窗 boot1c 的崩溃点）/ g3 跨图 ✅（复测 3/3，
  首测空串为偶发）/ g4 GSM $5 ✅ / 投机形态正常
- **Gate4（#4973 类）**：13.6K 纯文本 prompt 9.4s 正常摘要 ✅（upstream 仍 open 的 IMA 类未复现）
- needle 30K：HIT（10.7s）✅；GSM 哨兵 3/3 ✅

性能（VL 权重、k=6、FULL 图；单流/并发聚合）：

| 探针 | 本窗 baked7f1 | 参照 |
|---|---|---|
| TextITL | 600 tok / 15.3s ≈ **39.2 tok/s** | 窗#1 V5b 文本 graph 29.1ms/步（≈34 tok/s）|
| VisionITL | 385 tok / 7.9s ≈ **48.7 tok/s** | 窗#2 vision eager spec-off 61.3ms/步 |
| conc4 | **97.5 / 96.0** tok/s | 生产文本基线 88.3/91.0 |
| conc8 | **149.8 / 140.3** tok/s | 生产文本基线 130.5/129.2 |

（并发探针内容与生产基线探针不完全同语料，非严格 A/B；量级结论=VL 分支 FULL 形态吞吐≥文本生产基线带。）

投机接受（k=6）：A(6)≈2.08；per-position 0.57/0.29/0.12/0.05/0.015/0.002——位置 4-6 近乎死亡
→ k=3（上游官方 VL 参考配置）损失接受 ≈3% 但省 3 级 draft 链，**大概率净赚，列下窗 A/B**。

## 4. PIECEWISE 84vs88：根因修正与修复（b7-fix）

窗#2 报告将 84vs88 解读为"图像哨兵计数错配"——**有误，特此修正**。真实根因链（代码+日志双实锤）：

1. `.b6pw` 变体 k=6 → decode_query_len=7（boot B 日志 `use_flattening=True (next_n=7)`）；
2. warmup decode 步：12 reqs × 7 tok = 84 tokens，PIECEWISE 补到 capture 桶 **88**（桶表含 88；k=7 时
   12×8=96 恰为桶顶，生产纯靠桶表覆盖躲过）；
3. `split_decodes_and_prefills` 均匀快路径把补过的 num_actual_tokens=88 当 `num_decode_tokens` 返回，
   而 decode 张量按真实 84 行展开；
4. `sparse_attn_indexer.py:544` `q_quant[:88].reshape(84,-1,64,128)` → 84∤88 → RuntimeError。

**b7-fix**（baked7 镜像，md5 f50b451a）：else 分支切片改为按 decode 张量自身形状
（`decode_lens.shape[0] × seq_lens.shape[-1]`）钳制。效果：boot 1c 启动+单图通过（窗#2 同形崩溃消除）；
四图多图重放仍 Xid31 → 该层之上还有内核层问题（TK512/0.6.18 族），F1 内核下 FULL 可用后，
PIECEWISE×多图在 F1 上的验证转 backlog（PIECEWISE 已无上生产的必要——FULL 更优）。

## 5. 窗口#1 FULL IMA 根因定谳

证据链：eager 全绿（窗#2）+ 文本 FULL 正常（生产）+ 本窗 boot1c（旧内核 PIECEWISE 多图 Xid31）+
boot2（F1 内核 FULL 图 10/10 干净+全门禁）→ **根因=0.6.18 flashinfer SM120 内核族（含 baked 系
TK512 手补丁 prefill .cu）在图捕获/重放×VL mm-pad 形状下的设备侧内存错误**；#4732（SM121 barrier）、
#4802（重构+graph-safe wrapper+原生 topk512+latent OOB 修复×5）一并带入后消失。TK512 手补丁按
K-group D-k 预判退役（能力并入 #4802）。

## 6. 交付物与资产

- 镜像（registry node02，四节点已拉）：
  - `...TP4-Ring-VL-baked7`（baked6 + b7-fix）image ID `<BAKE_IMAGE_DIGEST>...`，digest `<BAKE_IMAGE_DIGEST>`
  - `...TP4-Ring-VL-baked7f1`（baked7 + flashinfer 453aa7c 换装）image ID `<BAKE_IMAGE_DIGEST>`，digest `<BAKE_IMAGE_DIGEST>`
  - 官方定名 `LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring` = baked7f1 同一镜像（定稿重 tag）
  - 注：node01 启用 containerd snapshotter，`docker images` 的 ID 列显示 manifest digest（<BAKE_IMAGE_DIGEST>），
    与 node02-node04 的 e4e643a0 为同一镜像（RootFS 层序列 md5 一致，交叉审计已验证）；ID 核对以 node02-node04 为准
- 补丁：b7-fix（sparse_attn_indexer.py else 分支钳制）；Dockerfile 双份（门禁内置）
- 变体脚本（四节点 ~/w6-kit/，md5 互验）：.b7pw7 / .b7full7sa / .b7f1full7 / .b7f1pw7（f1 独立缓存
  flashinfer-cache-f1/tilelang-cache-f1，防 ninja stale）
- 调查报告：E-ima-survey-20260908.md、E-piecewise-f1-survey-20260908.md
- 结果数据：w2_gates_b7f1full7.json 等（w6-logs/g1r7-tune-20260907/）

## 7. 下窗候选（按优先级）

1. **VL k=3 vs k=6 A/B**（本窗接受数据已给出强信号；k=3 为上游 #54566 参考配置）
2. **VL 上生产决策**：baked7f1+FULL+k6 已具备条件——切流窗口+8001 代理路由策略（长纯文本 prompt
   是否仍走 V5 文本线规避 #4973 残余风险，建议维持）
3. F1+PIECEWISE 多图验证（仅当需要 PIECEWISE 形态时）
4. F1 后续：#4955（NVFP4 sparse MLA）与 #4811（topk 阈值修复）在 main 已领先，可作 F2 增量窗
5. #4973 上游跟进（仍 open，Gate4 已纳入常规门禁）

---

## 附录 A：定稿交叉审计整改记录（2026-09-08）

三审计（E-镜像代码 PASS 0 实质 / E-配置 1 项经 A 证据解决 / E-文档 9 项缺口）后的整改：

1. **证据归档补全**（原 H2/M1/H3）：boot2 探针数据落盘 `w6-logs/g1r7-tune-20260907/
   evidence_b7f1full7_boot2.json`（W2 五门+Gate4+needle+GSM+ITL+conc 全套，含 g3 复测 3/3 与
   首测空串说明）；投机指标从 logdump 提取归档 `evidence_boot2_spec_and_boot1c_xid.txt`
   （6 窗 SpecDecoding 原始行）；boot1c 的 Xid31 dmesg 原文同文件存证。
2. **门禁文件正名**（原 H3）：boot2 的门禁结果曾误存两份同名拷贝，已归并为
   `w2_gates_b7f1full7_boot2.json`（boot1c 因 g2 即崩、json 未落盘，属预期）。
3. **镜像 digest 修正**（原 H1）：baked7f1 image ID=<BAKE_IMAGE_DIGEST>、digest=<BAKE_IMAGE_DIGEST>...；
   node01 的 ID 显示差异系 containerd snapshotter（RootFS 层序列一致，四节点同一镜像）。
4. **构建档案本地化**（原 M3）：vl-baked7-ctx / vl-baked7f1-ctx 已从 node02 同步至本地
   `~/w6-kit/g1r7-build/`（含 Dockerfile 门禁与 b7-fix 源文件，md5 f50b451a 复验一致）；
   vl-baked6-ctx 本地保留（TK512 手补丁源）。
5. **k=3 调和**（原 M4）：W2 轮记录 fork DSpark 要求 k≥5（n_predict 整除放宽前），
   故 k=3 在本 fork 不可直接启动；定稿 k=6 为唯一已验证 VL 形态（用户已决策不做 k=3 A/B）。
6. **MASTERPLAN 过时项标注**：见该文件头部"定稿后状态"段。
7. needle 30K 三口径说明（原 L2）：11.2s（窗1，V5b 文本 k7）/ 11.1s（窗2，V5b 复测）/
   10.7s（窗3，baked7f1 VL k6）——三次不同形态的在线实测，量级一致。
