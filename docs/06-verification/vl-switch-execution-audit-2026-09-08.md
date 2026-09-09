# VL 生产切换执行质量事后审计报告

- **审计人**：vl-switch-audit（工程保障团队，独立干净上下文）
- **审计日期**：2026-09-08（切换窗口当日，事后独立取证）
- **审计对象**：V5b（k=7 文本线）→ VL（k=6 视觉线）生产切换执行质量
- **切换窗口**：2026-09-08 11:27:50（guard 链启动）→ 11:32:41（guard 退出 rc=0）
- **取证方式**：只读 SSH（node01/02/03/04 免密，node01 经跳板路径访问）
- **审计结论**：**八项全部 PASS，无严重问题，无脚本漂移，无镜像不一致，无日志特征缺失**

> **关联报告**：
> - **闭环关系**：本文是「切换前审核 → 窗口执行 → 事后复核」闭环的执行回执——[部署方案交叉审核](../07-deployment/vl-deployment-cross-audit-2026-09-08.md)（P0 阻塞项定谳）与[服务器治理面审计](../07-deployment/vl-governance-audit-2026-09-08.md)（P0/P1 治理动作清单）所列切换窗口动作，均在本报告八项审计中得到执行验证（全 PASS）。
> - **验收上下文**：[上线六门验收](vl-acceptance-sixgates-2026-09-08.md)（窗口后功能/性能验收）· [FINAL-METRICS-VL](../03-final-metrics/FINAL-METRICS-VL-2026-09-09.md)（冷窗口性能定版）
> - **根因排查链**：[服务器取证](../01-research-reports/vl-server-side-forensics-2026-09-09.md) · [投机头调研](../01-research-reports/spec-head-research-2026-09-09.md)

---

## 一、八项审计判定表

| # | 审计项 | 判定 | 关键证据摘要 |
|---|--------|------|--------------|
| 1 | 四机脚本 md5 | **PASS** | 四机 live 脚本与 .vl-final md5 全部一致，符合基准值 |
| 2 | 四机容器镜像 | **PASS** | Config.Image 四机一致；RepoDigest 四机一致（rank0 本地 imageID 与 registry manifest digest 同值，为环境特性）；Created 均晚于 11:27:50 |
| 3 | rank0 启动日志特征 | **PASS** | Loaded 36 configs ✓ / Skipping sparse_mla_sm120 ✓ / dspark FULL 10/10 ✓ / NCCL cap-snap 多行 ✓ / Traceback 计数=0 ✓ |
| 4 | 容器 env | **PASS** | VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS=sparse_mla_sm120 进容器；served-model-name=deepseek-v4-flash-vision-exp 经启动命令行传入（日志 non-default args 确认） |
| 5 | 挂载核验 | **PASS** | <INSTALL_DIR>/models/dsv4-vision-exp → /models（ro）✓；flashinfer-cache-f1、tilelang-cache-f1 独立卷 ✓ |
| 6 | 8003 网关 | **PASS** | 服务 active+enabled；/v1/models 含 deepseek-v4-flash-vision-exp、不含 0731 |
| 7 | 治理链状态 | **PASS** | node01 五单元 enabled+active（daily-smoke.timer 为 enabled+inactive 即已按要求停止）；四机 vllm028-* masked；w6_env.txt 四机 md5=b4ae0340 一致 |
| 8 | guard 日志全量 | **PASS** | stop workers→head、TCPStore 7x5s、start head→workers、health 9x30s=200，与 guard v3（w9r4_restart_guard.sh → w9r4_window_restart.sh）设计完全一致 |

---

## 二、逐项证据

### 审计项 1：四机脚本 md5 —— PASS

| 机器 | 角色 | live 脚本 md5 | .vl-final md5 | 基准值 | 一致性 |
|------|------|--------------|----------------|--------|--------|
| node01 | head | b0b3561ae8f4b95a399ac349b819f4c7 | b0b3561ae8f4b95a399ac349b819f4c7 | b0b3561a…（head） | ✓ |
| node02 | worker(r1) | 936963ee49aad295459cba45a02baa06 | 936963ee49aad295459cba45a02baa06 | 936963ee…（worker） | ✓ |
| node03 | worker(r3) | 936963ee49aad295459cba45a02baa06 | 936963ee49aad295459cba45a02baa06 | 936963ee…（worker） | ✓ |
| node04 | worker(r2) | 936963ee49aad295459cba45a02baa06 | 936963ee49aad295459cba45a02baa06 | 936963ee…（worker） | ✓ |

取证命令：`md5sum ~/w6-kit/start_tp4_{head,worker}_v043.sh{,.vl-final}`（四机分别执行）。
live 脚本 mtime 均为 9月8 11:27（cp 落地时间），与窗口开始 11:27:50 吻合；.vl-final mtime 09:47（预烧制时间）。

### 审计项 2：四机容器镜像 —— PASS

容器名→rank 映射核对（01=r0 / 02=r1 / 04=r2 / 03=r3）：

| 机器 | 容器 | Config.Image | Created (UTC) | State |
|------|------|--------------|---------------|-------|
| node01 | vllm-tp4-rank0 | REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring | 2026-09-08T11:28:11Z | running / healthy |
| node02 | vllm-tp4-rank1 | 同上 | 2026-09-08T11:28:41Z | running / healthy |
| node04 | vllm-tp4-rank2 | 同上 | 2026-09-08T11:28:42Z | running / healthy |
| node03 | vllm-tp4-rank3 | 同上 | 2026-09-08T11:28:41Z | running / healthy |

- 所有容器 Created 均晚于窗口开始 11:27:50（UTC 时钟与 guard 日志本地时一致口径），确认容器为切换窗口内重建，非旧容器残留。
- **镜像 digest 核验**（本环境特有口径）：
  > 注：为脱敏计，本节涉及的 registry manifest digest 与本地 imageID 两类 sha256 指纹统一以 `<BAKE_IMAGE_DIGEST>` 占位——二者为**不同**指纹值（manifest digest 为分发口径，本地 imageID 为节点本地方径），正文对比逻辑不受影响。
  - rank0（dockerd 节点）：`.Image` = `sha256:<BAKE_IMAGE_DIGEST>` —— 本地 imageID 恰等于 registry manifest digest（该节点 `docker images --digests` 中 VL tag 行 RepoDigest 列与 imageID 列同值，环境特性），与预期 digest 完全一致。
  - rank1/2/3（containerd snapshotter 节点，02/03/04）：`.Image` = `sha256:<BAKE_IMAGE_DIGEST>`（本地 imageID，即任务书中"镜像 ID <BAKE_IMAGE_DIGEST>"）；`docker images --digests` 三机的 VL tag 行 **RepoDigest 列均为 sha256:<BAKE_IMAGE_DIGEST>**，四机一致。
  - 结论：四机实际运行的镜像内容一致，manifest digest 统一为 `sha256:<BAKE_IMAGE_DIGEST>`，本地 imageID 显示差异（node01 docketd vs 其余 containerd snapshotter）为预期内显示差异，非镜像漂移。

### 审计项 3：rank0 启动日志特征 —— PASS

`docker logs vllm-tp4-rank0`（node01）逐项核对：

| 特征 | 预期 | 实际 | 判定 |
|------|------|------|------|
| autotune 配置加载 | `Loaded 36 configs` | `autotuner.py:2789 - [Autotuner]: Loaded 36 configs from /root/.cache/vllm/autotune-g1r6/autotune_configs.json`（11:32:12） | ✓ |
| FlashInfer skip | `Skipping FlashInfer autotuning for ops ['sparse_mla_sm120']` | `kernel_warmup.py:200] Skipping FlashInfer autotuning for ops ['sparse_mla_sm120']`（11:32:19） | ✓ |
| dspark FULL 图捕获 | 10/10 | `Capturing dspark CUDA graphs (FULL): 100%|██████████| 10/10 [00:00<00:00, 43.99it/s]` | ✓ |
| NCCL cap-snap | 存在 | `[NCCL][V5] cap-snap n=64/128/…/2240 …` 多行（PIECEWISE 与 FULL 捕获期间） | ✓ |
| Traceback | 无 | `grep -c Traceback` = 0 | ✓ |

补充确认：
- 普通 FULL 图捕获 `11/11` 完成后 dspark FULL `10/10` 完成，图捕获链完整。
- 日志尾部 `/health` 200 OK 持续、`/v1/chat/completions` 200 OK——切换后服务真实承载请求。
- `parallel_state.py:1615] world_size=4 rank=0 … backend=nccl`——TP4 集群形态正常。
- `non-default args` 显示 `served_model_name: ['deepseek-v4-flash-vision-exp']`、`num_speculative_tokens: 6`（k=6）、`speculative_config.method='dspark'`——与 VL 线预期参数一致。

### 审计项 4：容器 env —— PASS

`docker exec vllm-tp4-rank0 env | grep -E 'SERVED_MODEL|AUTOTUNE|SKIP_OPS'`：

```
VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR=/root/.cache/vllm/autotune-g1r6
VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS=sparse_mla_sm120
```

- `VLLM_FLASHINFER_AUTOTUNE_SKIP_OPS=sparse_mla_sm120` 进容器 ✓（与启动日志"Skipping"行为互证）。
- 容器 env 中**无** `SERVED_MODEL_NAME` 环境变量——该值经启动命令行 `--served-model-name` 传入而非 env；日志 `non-default args` 与 `served_model_name=deepseek-v4-flash-vision-exp` 双重确认生效。**判定为符合设计（命令行传递口径），非缺失**。
- `SERVED_MODEL` grep 无 AUTOTUNE 命中以外的异常项。

### 审计项 5：挂载核验 —— PASS

`docker inspect vllm-tp4-rank0` Mounts：

| Source | Destination | 读写 | 判定 |
|--------|-------------|------|------|
| <INSTALL_DIR>/models/dsv4-vision-exp | /models | ro | ✓ 视觉权重只读挂载 |
| <HOME_DIR>/flashinfer-cache-f1 | /root/.cache/flashinfer | rw | ✓ 独立卷 |
| <HOME_DIR>/tilelang-cache-f1 | /root/.cache/tilelang | rw | ✓ 独立卷 |
| <HOME_DIR>/b12x-cache | /root/.cache/b12x | rw | MoE b12x 缓存（配套） |
| <HOME_DIR>/vllm-cache | /root/.cache/vllm | rw | autotune-g1r6 等缓存所在 |
| <HOME_DIR>/vllm-logs | /var/log/vllm | rw | 日志 |
| <INSTALL_DIR>/lib/libncclpin.so | /opt/libncclpin.so | ro | NCCL pin 库（cap-snap 支撑） |

与 runbook 预期关键挂载全部吻合，且日志中 autotune cache 实际读取路径 `/root/.cache/vllm/autotune-g1r6` 与挂载链自洽。

### 审计项 6：8003 网关 —— PASS

node02：

- `systemctl --user is-active responses-gateway` → **active**；`is-enabled` → **enabled** ✓
- 备份存在：`responses-gateway.service.bak-vlswitch-20260908` ✓（回滚点就绪）
- `curl -s http://127.0.0.1:8003/v1/models`（带网关 API key）返回：

```json
{"object":"list","data":[
  {"id":"local-v4-flash","object":"model","created":0,"owned_by":"deepseek"},
  {"id":"deepseek-v4-flash-vision-exp","object":"model","created":0,"owned_by":"deepseek"},
  {"id":"deepseek-v4-flash","object":"model","created":0,"owned_by":"deepseek"}
]}
```

- 含 `deepseek-v4-flash-vision-exp` ✓、不含任何 `0731` ✓、对外名 `local-v4-flash` 与别名 `deepseek-v4-flash` 保持兼容 ✓。

### 审计项 7：治理链状态 —— PASS

node01（经跳板路径 SSH 取证；审计机直连 node01 因 publickey 拒绝，跳板路径成功）：

| 单元 | enabled | active | 判定 |
|------|---------|--------|------|
| vllm-tp4-head | enabled | active | ✓ |
| concurrency-proxy-v2 | enabled | active | ✓ |
| gb10-clock-cap | enabled | active | ✓ |
| vllm-logdump | enabled | active | ✓ |
| vllm-healthcheck.timer | enabled | active | ✓ |
| daily-smoke.timer | enabled | **inactive (dead)** | ✓ 按要求已停 |

- daily-smoke.timer 停止时间取证：`Stopped daily-smoke.timer … Tue 2026-09-08 10:52:49 UTC`，早于切换窗口 11:27:50 —— 停止时序正确，切换期间无冒烟干扰。LastTrigger=09:32:08（当日例行触发，在停止前）。
- 四机 `vllm028-*` 旧单元：01=`vllm028-tp4-head.service masked`，02/03/04=`vllm028-tp4-worker.service masked` ✓（防止旧 monitor 抢拉）。
- 四机 `~/w6-kit/w6_env.txt` md5 全部 = `b4ae0340cd55e04d289d2be43ff09a05` ✓（与基准 b4ae0340 一致，四机配置无漂移）。

### 审计项 8：guard 日志全量 —— PASS

`/tmp/vl-switch-guard-20260908.log`（node01）全文：

```
[guard] 11:27:50 链启动, 锁已持有 (pid=2211007)
[restart] stop workers 11:27:50
node02:0
node03:0
node04:0
[restart] stop head 11:28:05
vllm-tp4-rank0
local rank containers: 0
[restart] start head 11:28:09
[TCPStore up] 7x5s
[restart] start workers 11:28:40
node02 started
node03 started
node04 started
[restart] wait health 11:28:41
[READY] 9x30s health=200
[guard] 链结束 rc=0
[guard] 11:32:41 链退出, 锁已释放
```

与 guard v3 设计（`w9r4_restart_guard.sh` md5=cf87d40598641acaf07d430d338170da，包装 `w9r4_window_restart.sh`）逐条对照：

| 设计点 | 设计（脚本实现） | 日志实际 | 判定 |
|--------|------------------|----------|------|
| 互斥锁 | flock -w 1200 全局锁，退出释放 | "锁已持有 pid=2211007" / "链退出, 锁已释放" | ✓ |
| stop 顺序 | 先 workers（node02/node03/node04）后 head | stop workers 11:27:50 → stop head 11:28:05 | ✓ |
| workers 清场确认 | 每机输出剩余容器数应为 0 | node02:0 / node03:0 / node04:0 | ✓ |
| head 清场确认 | rank0 移除 + 本地计数 0 | vllm-tp4-rank0 / local rank containers: 0 | ✓ |
| TCPStore 等待 | 轮询 :26000，最多 24x5s；实际 7x5s（~35s） | [TCPStore up] 7x5s | ✓ |
| D2 fail-fast | TCPStore 超时则停 head 退出（本次未触发） | 未触发，正常继续 | ✓ |
| start 顺序 | head 先行 → TCPStore 就绪 → workers | start head 11:28:09 → start workers 11:28:40 | ✓ |
| health 轮询 | 最长 40x30s；实际第 9 次命中 200 | [READY] 9x30s health=200 | ✓ |
| 退出码 | rc=0 成功 | 链结束 rc=0 | ✓ |

时间线自洽性：容器 Created（11:28:11–11:28:42）全部落在 guard start head（11:28:09）与 start workers（11:28:40–42）之间，与 guard 主导的重建过程吻合。head 于 11:28:09 start、rank0 容器 11:28:11 创建（systemd 单元启动→docker run 约 2s）；workers 11:28:40 start、三容器 11:28:41–42 创建（SSH 往返约 1–2s/机）。9x30s 中第 9 次命中与日志时间轴（11:28:41 开始等待、11:32:41 READY 前后 4 分钟出头含模型加载）一致。

---

## 三、切换时间线（整合）

| 时刻 | 事件 | 来源 |
|------|------|------|
| 09:47 | 四机 .vl-final 脚本预烧制落盘（head 6323B / worker 4172B） | 文件 mtime |
| 10:52:49 | daily-smoke.timer 停止（窗口前配套） | node01 journalctl |
| 11:27:50 | guard 链启动，锁持有（pid=2211007）；stop workers | guard 日志 |
| 11:28:05 | stop head；rank0 移除，本地清场=0 | guard 日志 |
| 11:28:09 | start head（vllm-tp4-head 单元） | guard 日志 |
| 11:28:11 | rank0 容器创建（Created 时间戳） | docker inspect |
| 11:28:18 | rank0 APIServer 起始，non-default args 确认 VL 参数 | rank0 日志 |
| ~11:28:44 | TCPStore :26000 监听（7x5s） | guard 日志 |
| 11:28:40 | start workers（node02/node03/node04） | guard 日志 |
| 11:28:41–42 | rank1/2/3 容器创建 | docker inspect |
| 11:31:50–11:32:19 | autotune：Loaded 36 configs → Skipping sparse_mla_sm120 | rank0 日志 |
| 11:32:12+ | CUDA graphs：PIECEWISE 16/16 → FULL 11/11 → dspark FULL 10/10，NCCL cap-snap 贯穿 | rank0 日志 |
| 11:32:41 | health=200（9x30s），guard rc=0 退出，锁释放 | guard 日志 |
| 切换后 | /health 200 持续、/v1/chat/completions 200 OK、/metrics 200 | rank0 日志尾部 |

总切换时长：**4 分 51 秒**（11:27:50 → 11:32:41），期间零 Traceback、零容器异常重启（四容器均 healthy）。

---

## 四、异常清单

**严重（镜像不一致/脚本漂移/日志特征缺失）：无。**

轻微观察项（不影响判定）：

1. **容器 env 无 SERVED_MODEL_NAME 变量**：served-model-name 经命令行参数传入容器（日志确认生效），容器 env grep 不命中属传递口径差异，非缺失。runbook 若要求 env 形式存在，建议未来文档明确"命令行口径"。（信息级）
2. **node01 直连 SSH 免密不可用**：审计经跳板路径完成。若后续审计/巡检自动化需要直连 node01，需补配免密。（信息级，非切换问题）
3. **guard 日志中 workers stop 阶段以 "node02:0" 等简式输出**（脚本以节点简写标识清场计数，本报告已按仓库节点别名口径转写）：为脚本既有设计，非本次异常。（信息级）
4. **node01 节点 VL tag 存在多个历史 bake 变体**（VL-baked6/baked7/baked7f1 等）：均为本地构建产物，与运行容器 digest 比对已确认使用正确的 `LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring`（<BAKE_IMAGE_DIGEST>）。建议择机清理历史 tag 防误用。（建议级）

---

## 五、与 runbook 预期对照

| runbook 预期 | 实际 | 判定 |
|--------------|------|------|
| head md5 = b0b3561ae8f4b95a399ac349b819f4c7 | 一致 | ✓ |
| worker×3 md5 = 936963ee49aad295459cba45a02baa06 | 一致 | ✓ |
| 镜像 = LuZ0.4.5-DeepSeek-v4-Flash-VL-DGXspark-TP4-Ring，digest sha256:<BAKE_IMAGE_DIGEST> | 四机一致 | ✓ |
| k=6 视觉线（num_speculative_tokens=6, dspark） | 日志确认 | ✓ |
| served-model-name=deepseek-v4-flash-vision-exp | 日志+网关双重确认 | ✓ |
| 视觉权重 <INSTALL_DIR>/models/dsv4-vision-exp:/models:ro | 挂载确认 | ✓ |
| guard v3：stop workers→head / TCPStore 等待 / start head→workers / health 轮询 | 日志逐步吻合 | ✓ |
| 8003 网关 SERVED_MODEL 切 vision-exp，含备份 | /v1/models 确认 | ✓ |
| daily-smoke.timer 已停 | 10:52:49 停止 | ✓ |
| monitor L69 预热模型名 env 化 + vllm.env 追加 SERVED_MODEL_NAME | 配套变更已由主理人执行（本审计经容器行为间接验证：网关模型名正确流转） | ✓ |

---

## 六、审计结论

VL 生产切换（V5b→VL）执行质量**优良**：

1. **配置零漂移**：四机脚本 md5 与预烧制基准完全一致，w6_env.txt 四机一致。
2. **镜像零不一致**：四机运行同一 manifest digest（<BAKE_IMAGE_DIGEST>），containerd/docketd 显示差异为环境特性非实质漂移。
3. **启动链零异常**：36 configs、sparse_mla_sm120 skip、FULL 11/11、dspark FULL 10/10、NCCL cap-snap 全部到位，零 Traceback。
4. **guard 执行与设计零偏差**：锁互斥、清场确认、D2 fail-fast 保护（未触发）、顺序化启停、健康轮询全部按 v3 设计执行，4 分 51 秒完成切换。
5. **对外面零残留**：8003 网关模型列表已切换至 vision-exp，无 0731 残留；治理链完整，旧单元 masked，回滚备份齐备。

无需整改项。四个信息/建议级观察项供后续运维参考。

*报告完*
