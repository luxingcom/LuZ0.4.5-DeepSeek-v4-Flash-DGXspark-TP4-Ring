# VL 版本基线交付报告（运维部署用）

**版本名**：`LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`
**定稿形态**：baked7f1 镜像 + FULL_AND_PIECEWISE 图模式 + dspark 投机 k=6 + 视觉检查点
**定稿日期**：2026-09-08 ｜ **状态**：待运维部署（验收与审计见 §7/§8）

**定稿决策记录（用户，2026-09-08）**：
1. VL 版本定稿为 baked7f1 + FULL + k6，正式名 `LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`；
2. 不进行 VL k=3 A/B 测试（k=6 为定稿且唯一已验证形态）；
3. 定稿复核检验 + 交叉审计 + 文档/注释/档案编制 + 本交付报告，交运维团队部署。

**与文本生产线关系**：并存不互斥。文本生产 = V5b（k=7，不动）；VL 为独立镜像/脚本/权重/缓存卷，
切换与回退互不影响。建议 VL 上线初期长纯文本 prompt 仍路由文本线（见 §7 残余风险 R1）。

---

## 1. 版本谱系

```
LuZ-0.4.4-DeepSeek-v4flash-DGXspark-TP4-ring  (fork d3d3b2cca 快照 2026-08-05 + sm121a 系)
  └─ +toolfix1（工具编码崩溃修复，W9-R13）
      └─ V5b（运维构建 2026-09-07：+A1/A2/A3 三补丁 + B1/B2 env 门 + W9R14 autotune + 2×commit 层）
          └─ baked6（VL overlay 三方合并：18 继承文件 + 4 新文件 + 2 合并文件 + TK512 内核）
              └─ baked7（+ b7-fix：sparse_attn_indexer decode 切片钳制）
                  └─ baked7f1（+ flashinfer 453aa7c 换装：csrc/include/jit/mla 包整组，TK512 退役）
                      └─ 【官方定名】LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring  ← 本版本
```

| 镜像 | image ID | registry digest |
|---|---|---|
| **官方定名** | `<BAKE_IMAGE_DIGEST>` | `<BAKE_IMAGE_DIGEST>` |
| 别名（保留） | 同上 | `...TP4-Ring-VL-baked7f1` |

镜像已在 registry（REGISTRY_HOST:5000）与全部四节点（_PH_HEAD_IP_.186-node04）就位。

## 2. 代码变更清单（相对文本生产 V5b）

| # | 变更 | 内容 | 引入代 |
|---|---|---|---|
| C1 | VL overlay（24 文件） | vl_model/vl_stub/vision/mm_preprocess 等视觉栈 + 三方合并 model.py/cache_utils.py | baked6 |
| C2 | **b7-fix** | `vllm/model_executor/layers/sparse_attn_indexer.py` else 分支：decode q 切片按 decode 张量自身形状钳制（`decode_lens.shape[0] × decode_metadata.seq_lens.shape[-1]`），修 PIECEWISE token 桶 padding 与 reshape 不变量冲突（文件 md5 `f50b451a`） | baked7 |
| C3 | **F1 换装** | flashinfer sparse-MLA SM120 全栈换 453aa7c：`data/csrc/sparse_mla_sm120*.cu`×5 + `data/include/.../sparse_mla_sm120/` + `flashinfer/mla/` 包（新增 `_sparse_mla_sm120_plan/_cpb/_batch_mla`）+ `flashinfer/jit/mla.py`。带回 #4802（graph-safe wrapper、原生 topk512 prefill、latent OOB 修复×5、标定 dispatch）与 #4732（SM121 prefill barrier hang 修复） | baked7f1 |
| C4 | **TK512 退役** | baked6 世代的手补丁 prefill 内核被 453aa7c 原生实现取代（K-group D-k 预判落地） | baked7f1 |

继承自 V5b（不在本版本差异内但属版本血统）：A1 SKIP 修复、A2 #54815 rope 修复、A3 #55636 clamp
守卫、B1 C1 门（OFF）、B2 C2 门（OFF）、toolfix1。全部在镜像内有断言门（见构建档案 §9）。

## 3. 参考配置（定稿脚本 = 生产基线的**最小差异集**）

定稿脚本（四节点 `~/w6-kit/`，已放置，头部含注释块）：
- head（node01）：`start_tp4_head_v043.sh.vl-final`（md5 `b0b3561ae8f4b95a399ac349b819f4c7`）
- worker（node02/node03/node04 三份一致）：`start_tp4_worker_v043.sh.vl-final`（md5 `936963ee49aad295459cba45a02baa06`）

相对生产基线（.bak-window-20260907）的**全部**差异（共 6 处，交叉审计逐行核对）：

| 项 | 值 | 理由 |
|---|---|---|
| 镜像 `R5=` | `...Flash-VL-DGXspark-TP4-Ring` | 本版本 |
| 权重挂载 | `/opt/_PH_INSTALL_/models/dsv4-vision-exp:/models:ro` | 视觉检查点（四机本地化符号链接，W9-R13） |
| `--served-model-name` | `deepseek-v4-flash-vision-exp` | 上游 #54566 命名 |
| `--speculative-config` | `dspark k=6 probabilistic` | **硬约束**：VL 检查点 draft head `n_predict=3`（config.json `num_nextn_predict_layers=3`），k 必须 ∈{3,6}（k=7 pydantic 拒绝；k=3 在本 fork 受 k≥5 历史放宽约束不可直接启动，用户已决策不做 k=3 A/B）——**k=6 为唯一已验证 VL 形态** |
| `-e VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS` | `sparse_mla_sm120` | 验证形态自带；boot2 日志实证生效（`Skipping FlashInfer autotuning for ops ['sparse_mla_sm120']`） |
| 缓存挂载 | `~/flashinfer-cache-f1`、`~/tilelang-cache-f1` | **独立 F1 JIT 缓存卷**（防 0.6.18 陈旧 .so 被 ninja 复用，#4732 教训）；已有 boot2 暖缓存 |

不变项（与生产一致，运维无需关注）：端口 8002（容器）/8001（代理）、max-model-len 600000、
max-num-seqs 12、max-num-batched-tokens 4096、fp8_ds_mla KV、b12x W4A4、`w6_env.txt`（版本无关）、
NODE_RANK/MASTER 地址、LD_PRELOAD ringonly、W9R14 autotune 缓存卷（vllm-cache，MoE 策略仍有效）。

## 4. 部署 Runbook（运维执行）

前置条件（当前已满足）：
1. 四节点已 pull 官方 tag（image ID `<BAKE_IMAGE_DIGEST>` 一致）；
2. 四节点 `~/flashinfer-cache-f1/`、`~/tilelang-cache-f1/` 存在且非空（boot2 已 JIT 暖缓存，
   首次部署**无需**冷编译；若清空该卷，首次启动将追加 5-10 分钟 JIT，属预期）；
3. 生产文本线不受影响（改动仅涉及 `.vl-final` 脚本与独立缓存卷）。

切换步骤（停机窗口内，约 8-12 分钟）：
1. `cp ~/w6-kit/start_tp4_head_v043.sh.vl-final ~/w6-kit/start_tp4_head_v043.sh`（node01）；
   三台 worker 各自 `cp ~/w6-kit/start_tp4_worker_v043.sh.vl-final ~/w6-kit/start_tp4_worker_v043.sh`；
2. **md5 验证（整文件 md5，cp 后直接验收）**：head=b0b3561a、三 worker=936963ee、三 worker 互相一致（注意 1a8c5090/0ee0fde5 是去 VL-FINAL 注释头后正文口径，勿用于 cp 后验收）（历史教训：脚本不同步会分裂集群）；
3. `bash ~/w6-kit/w9r4_restart_guard.sh`（唯一合法重启入口，flock 防叠跑）；
4. 等 `[READY] health=200`（首启含 capture+autotune，约 5-8 分钟；正常日志特征见 §5）。

验收门（上线必跑，脚本与判据见 §9 证据目录）：
1. 健康：`curl 127.0.0.1:8002/health` = 200；
2. 文本 sanity：GSM8K 三题全对；
3. 视觉五门（w2_gates 脚本）：单图颜色/四图计数/跨图跨度/GSM/投机形态；
4. 长上下文：needle 30K 命中（≈11s）；13.6K 纯文本正常响应（#4973 常规哨兵）；
5. 并发抽测：conc4 ≥85、conc8 ≥120 tok/s（参考验证值 96-98 / 140-150）；
6. 投机指标：metrics 端口 `SpecDecoding` 均值接受长度 ≈2（k=6 形态）。

回退链（任一门失败即回退）：
`cp .bak-window-20260907 回 live → w9r4_restart_guard.sh`（文本生产基线，与 VL 无耦合；
VL 专属改动不残留）。Xid/IMA 类失败同时留证：crash_dump 自动归档 + `dmesg -T | grep Xid`
（窗3 boot1c 的 Xid31 存证样例见证据目录）。autotune 死锁类失败的处置 checklist 见
`G1R7VL-PROD-PENDING-FIXES-20260907.md` §5.1。

## 5. 正常运行日志特征（值班判读）

- 启动期（预期 INFO）：`Loaded 36 configs from /root/.cache/vllm/autotune-g1r6/autotune_configs.json`
  → `Skipping FlashInfer autotuning for ops ['sparse_mla_sm120']` → dspark FULL 图捕获 10/10 →
  `[NCCL][V5] cap-snap` 系列行（V5 NCCL 快照机制，正常）；
- 运行期：`SpecDecoding metrics` 周期打印；`/metrics` 由 prometheus 抓取（node02:8000 网段）；
- 崩溃取证：`systemctl stop` 会触发 crash_dump.sh 留档 `/opt/_PH_INSTALL_/backup/crash-dumps/`；
  容器日志跨代留存 `/opt/_PH_INSTALL_/backup/vllm-logdump/`（logdump 常开）。

## 6. 验收记录（本窗 boot2 = 定稿配置实测，2026-09-08）

| 门 | 结果 |
|---|---|
| FULL 图捕获 | dspark CUDA graphs 10/10（窗#1 同位置 IMA 不再复现） |
| W2 视觉五门 | g1 深红 ✅ / g2 四图 ✅ / g3 跨图 ✅（复测 3/3）/ g4 GSM $5 ✅ / 投机形态 ✅ |
| Gate4（#4973 哨兵） | 13.6K 纯文本 9.4s 正常摘要 ✅ |
| needle 30K | HIT（10.7s）✅；GSM 哨兵 3/3 ✅ |
| 并发（320-token 探针×2 轮） | conc4 97.5/96.0；conc8 149.8/140.3 tok/s（≥文本生产基线带 88-91/129-131） |
| 单流 | 文本 39.2 tok/s；视觉 48.7 tok/s |
| 投机 | A(6)≈2.08；per-position 0.57/0.29/0.12/0.05/0.015/0.002 |

## 7. 已知问题与残余风险

| # | 级别 | 内容 | 缓解 |
|---|---|---|---|
| R1 | 中 | flashinfer #4973（open）：DSV4-Vision × SM120/121 × ~13.6K 纯文本 prompt IMA，上游无修复 | **Gate4 已入常规门禁**；建议 8001 代理对 >12K 纯文本 prompt 路由文本线（运维待办，见 §9） |
| R2 | 中 | k=6 位置 4-6 接受率 <6%（draft-head 弱接受） | 用户已决策不做 k=3 A/B；性能已达标；draft-head 微调列为远期方向 |
| R3 | 低 | W9R14 autotune 策略系旧内核标定，F1 内核下可能非最优 | boot2 实测性能达标；重调优列为后续优化窗（非阻塞） |
| R4 | 低 | PIECEWISE×多图在 F1 内核上未验证（b7-fix 修好启动与单图；多图仅旧内核 Xid31） | 生产形态=FULL，不受影响；如需 PIECEWISE 形态先补验证 |
| R5 | 低 | autotune skip-ops 使 sparse_mla 通用调优跳过（DSv4 专用 warmup 仍走暖缓存） | 验证形态即如此；如需解除须重跑全套门禁 |

## 8. 定稿交叉审计结论（三个只读子代理，2026-09-08）

| 审计 | 结论 | 要点 |
|---|---|---|
| 镜像与代码 | **PASS（0 实质异常）** | 官方 tag 四节点同一镜像（node01 的 ID 显示差异系 containerd snapshotter，RootFS 层序列 md5 已证同源）；b7-fix md5/内容逐行核对；F1 换装组 vs 453aa7c pin 逐一 md5 相等（csrc×5+include×22+jit+mla 包）；TK512 未带入（prefill.cu=pin 版）；baked6 遗产标记全在；60 文件 py_compile 全过；V5b 未污染 |
| 配置与部署 | **PASS（1 项疑点已由镜像审计解决）** | 定稿脚本内容与 md5 符合；与生产基线逐行 diff=预期 6 处差异、零意外项；权重 symlink/config n_predict=3 证实；-f1 缓存四节点就绪且 boot2 暖缓存（sparse_mla_sm120.so mtime=boot2 窗口）、生产 flashinfer-cache 无污染；回退链 live==.bak 逐字节一致、guard 脚本语法过；8001 代理无模型白名单（全量转发），VL 上线代理无需改动，客户端仅需换模型名 |
| 文档与档案 | 初判 9 项缺口 → **已全部整改** | 见窗3 报告附录 A 整改记录：证据归档补全（boot2 探针 JSON+logdump 投机指标+Xid31 存证）、门禁文件正名、镜像 digest 表述修正、构建档案本地化（b7-fix 源 f50b451a 可独立复验）、k=3 fork 约束调和、MASTERPLAN 过时项标注、needle 三口径说明；上游引用抽查（#4802/#5015/#54566）属实 |

整改后状态：**三项审计均无未决异常，定稿放行。**

### 8.1 运维补充须知（审计中确认的细节）

- **8001 代理**：`concurrency_proxy_v2.py`（systemd `concurrency-proxy-v2.service`）全量转发
  0.0.0.0:8001→127.0.0.1:8002，`MAX_CONCURRENCY=6`，无模型名约束——VL 与文本线共用 8001 时，
  调用方以 `model` 字段区分（`deepseek-v4-flash-vision-exp` / `deepseek-v4-flash-0731`），
  但**同一时刻后端只能服务其一**（单 8002 引擎）；并存双活需上层路由，属后续工程项。
- **长纯文本路由建议**：纯文本 >12K token 的请求建议仍走文本线模型名（V5b），
  Gate4 哨兵阈值 13.6K 留有裕量（残余风险 R1）。
- **监视工具**：滚动接受率/混合监控 `~/w6-kit/g1r7-build/perf-inv/spec_mix_monitor.py`
  （`--watch/--json`，A/B 校准 `--f`）；guard 链日志在 `/tmp/w3-*.log`（本次窗口命名），
  长期建议落 `~/w6-logs/`。

## 9. 档案索引

- 窗口报告：`~/w6-kit/G1R7VL-WINDOW-REPORT-20260907.md`（窗1）、`G1R7VL-WINDOW2-REPORT-20260908.md`
  （窗2，含 §附录勘误）、`G1R7VL-WINDOW3-REPORT-20260908.md`（窗3，IMA 定谳）
- 调查报告：`~/w6-kit/g1r7-build/perf-inv/agent-reports/E-ima-survey-20260908.md`、
  `E-piecewise-f1-survey-20260908.md`（及 D-{k,v,f,s,r}-* 五组）
- 构建上下文：本地+node02 双份 `~/w6-kit/g1r7-build/vl-baked7-ctx/`（Dockerfile+门禁+b7-fix 源，md5 f50b451a）、
  `vl-baked7f1-ctx/`（Dockerfile+f1csrc/f1include/f1mla/f1jit 换装组）、本地 `vl-baked6-ctx/`（TK512 手补丁源，留档）、
  node02 `fi-453aa7c/`（pin 源码树）
- 证据数据：`~/w6-logs/g1r7-tune-20260907/`（`evidence_b7f1full7_boot2.json` 定稿臂全套探针、
  `evidence_boot2_spec_and_boot1c_xid.txt` logdump 投机指标+Xid31 存证、
  `w2_gates_b7f1full7_boot2.json`、`w2_gates_eager.json`、needle/conc/e1 历史探针 JSON）
- 定稿脚本与变体：四节点 `~/w6-kit/start_tp4_{head,worker}_v043.sh.vl-final`；
  过程变体 `.b7pw7/.b7full7sa/.b7f1full7/.b7f1pw7`；生产基线档 `.bak-window-20260907`
- 运维交接（文本线）：`~/w6-kit/G1R7VL-PROD-PENDING-FIXES-20260907.md`（含 8001 长 prompt 准入待办）
