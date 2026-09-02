# 热安全解除 + 超时守卫复查 + CUDA 图预热（2026-09-02）

> 督导指令：①热安全频率限制可解除，调回 2400MHz；②复查各类超时守卫时间，避免超长上下文（如 C4+400K）下执行超时重启或关机；③启动脚本内添加 CUDA 图首次运行预热，避免长上下文卡死。

---

## 1. TL;DR

| 项 | 结论 |
|---|---|
| GPU 频率 | ✅ 已恢复 2400MHz（gb10-clock-cap 四机持久化，2385-2392 MHz 生效） |
| 超时守卫 | ✅ 5 项修复（详见 §3）。**⚠️ W9R12 更新：GPU 利用率旁证经督导判定准确性太低已关闭**，恢复纯探针/failcnt 判定；其余守卫保留 |
| CUDA 图预热 | ✅ monitor head 已加首运行预热（health=200 后发 warmup 请求触发 JIT/CUDA 图） |
| 验证 | 探针实际执行 healthy；guard 重启验证中 |

## 2. 频率恢复 2400MHz（热安全解除）

- 四机 `gb10-clock-cap.service`：`-lgc 0,2300` → `-lgc 0,2400`，daemon-reload + restart + enable 保留
- 当前时钟：**2385-2392 MHz**（≤2400 cap），空闲温度 56-61°C
- ⚠️ 提示：2400MHz 满载温度预计较 2300 制高 ~5°C（2300 制满载峰值 83-91°C → 2400 制预计 88-96°C），接近 GB10 热限；温度监控保持 93°C 告警阈值

## 3. 超时守卫复查与修复（C4+400K 长上下文防误杀）

### 风险链分析
400K 长 prefill busy 时：①活性探针（max_tokens=1）排队超时 → ②8002 也可能被阻塞 → ③failcnt 2 → **docker rm -f 强杀** → 长上下文执行中断。此为督导关注的核心风险。

### 修复清单（四机同步，.bak 留档）

| # | 守卫 | 修复 | 作用 | 状态 |
|---|---|---|---|---|
| 1 | healthcheck_hardened.sh 活性探针 | 探针超时/失败时查 GPU 利用率，**≥50% = 繁忙(BUSY)非卡死，不判失败** | 防长 prefill 误判卡死 | ⛔ **W9R12 已关闭**（督导：准确性太低；恢复 FAIL=1 直接判定） |
| 2 | healthcheck-rebuild.sh 8002 判定 | 8002 不可达时查 GPU 利用率，满载 = busy **放行不计数** | 防 8002 阻塞误判重建 | ⛔ **W9R12 已关闭**（恢复纯 failcnt 判定） |
| 3 | monitor head | 预热插入（见 §4） | 防首运行编译卡死 | ✅ 保留 |
| 4 | head 容器 health-cmd | `curl -m 5` → `-m 30`，`--health-timeout 10s` → `35s` | 防 400K busy 时容器误判 unhealthy | ✅ 保留 |
| 5 | systemd 单元 | 加 `TimeoutStopSec=300`（默认 90s） | 防停机时超时 SIGKILL | ✅ 保留 |

> **W9R12 补充（2026-09-02 午间，督导指令）**：GPU 利用率旁证（#1/#2）经实况判定准确性低（nvidia-smi utilization 瞬时采样波动大、50% 阈值缺乏依据），已从四机移除（md5 hardened=94869b4d / rebuild=650a91ca，bash -n 通过，GPU_UTIL 零残留，<MGMT_OCTET> head 试跑 healthy）。同时修复 rebuild 重建容器名四机统一 `vllm028-tp4-rank`（02/03/04 原为 `vllm-tp4-rank` 匹配不到容器，自愈重建失效隐患）。长上下文防误杀改由「日志活性 300s + 8002 存活判定 + failcnt 2 + 冷却窗」承担，防护链完整。详见 `g1r6-release-finalization-2026-09-02.md`。

- worker 容器 health-cmd 为 `pgrep -f VLLM::EngineCore`（进程检查），400K busy 不受影响，无需改
- 探针实际执行验证：healthy（宽限 skip），GPU 旁证不破坏正常判定

### 保留的既有保护
- P2 繁忙判定（2026-08-26）：探针失败但 8002 存活 = BUSY 不重建
- 8002 不可达 failcnt 2 才重建（防单次抖动）
- 冷却窗口 1800s（防重启风暴）
- 宽限 900s + 进度式存活（引擎日志推进 = 初始化中）

## 4. CUDA 图首次运行预热（monitor head，<MGMT_OCTET>）

- 位置：rank 聚合后、`docker wait` 前
- 逻辑：等 health=200（最长 10min）→ 发 warmup 请求（max_tokens=16, timeout 120s）→ 触发 CUDA 图首运行 + flashinfer/tilelang/cute-dsl JIT 编译
- 覆盖：head 发请求经 TP4 分发触发全链各 rank worker kernel 编译
- 生效：下次容器重建起（当前引擎 JIT 缓存已持久化，历史已预热）

## 5. 验证状态

- [x] 探针/rebuild 实际执行 healthy
- [x] 四机 2400MHz 生效
- [x] W9R12 GPU 旁证已关闭（四机 md5 一致 + bash -n + GPU_UTIL 零残留 + <MGMT_OCTET> head 试跑 healthy）
- [ ] guard 重启验证（monitor 预热段执行 + 预热请求 http=200 + 2400MHz 下引擎正常）— 进行中

---
*报告：2026-09-02 12:40（W9R12 更新 13:00：GPU 旁证已关闭，详见 g1r6-release-finalization-2026-09-02.md）*
