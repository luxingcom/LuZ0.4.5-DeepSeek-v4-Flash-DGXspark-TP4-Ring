# Runbook：故障后恢复（决策树）

> 场景：任意 rank 掉线 / 拉起重启 / 集群失联后的标准化恢复路径。

## A. 就地拉起不行的决策树

```
rank0 拉起即崩?
 ├─ 日志含 "ibv_modify_qp ... errno 61" 或 "local GID ::"
 │    → 先查 GID: bash gid_preflight.sh   [根因: 对端断电→NM 撤 IP→GID idx3 全零]
 │       ├─ 异常 → bash gid_preflight.sh --fix (nmcli disconnect+connect 硬复位)
 │       │    └─ 仍失败 → 人工核查 NM/IP (勿判 NCCL/驱动)
 │       └─ 正常 → 查下一步
 ├─ 8002 重复 5xx / 无响应, 容器反复重启
 │    → 查 TCPStore 26000: ss -ltn | grep 26000  [monitor 60s 快速失败 = head 未监听]
 │    → 查 GID → 查显存(gpu-memory-utilization 0.80 是否超) → 查 NVIDIA 驱动
 └─ 满载过热断电 (history: 03 号机)
      → nvidia-smi 温度; >93°C 告警 → gb10-clock-cap 降频
```

## B. 标准恢复序列（任何 rank 掉线）

1. **先停自愈链**（防 monitor 无限重建打架）：
   ```bash
   systemctl stop vllm-healthcheck.timer
   systemctl stop vllm028-tp4-head.service vllm028-tp4-worker.service  # 四机
   ```
2. **GID 预检**（四机）：`for h in node02 node03 node04; do ssh $h bash gid_preflight.sh; done`
3. **停容器**：`docker rm -f $(docker ps -aq --filter name=vllm028-tp4-rank) 2>/dev/null || true`
4. **起 head**：`systemctl start vllm028-tp4-head.service` → 等 TCPStore
5. **起 worker**：`systemctl start vllm028-tp4-worker.service`（node02-04）
6. 恢复 timer 与 proxy，验证：
   ```bash
   curl -sf localhost:8002/health   # 全机 200
   systemctl start vllm-healthcheck.timer concurrency-proxy.service
   ```

## C. 自愈链自检

```bash
# 引擎日志近 300s 有推进 = 初始化中, 不干预; 停更 = 交重建判定
journalctl -u vllm028-tp4-head.service -f   # head
# 恢复后验证 autotune 命中: 日志应见 "Loaded 24 configs"
```

## D. 高风险边界

- **max-num-batched-tokens=4096 红线**：≥4608 触发 `num_tokens exceeds max_num_tokens` 引擎崩溃，**勿上调**
- 自愈链"冷却窗+failcnt+8002 存活"三重防误杀：高频重启优先怀疑 GID/温度，非自愈链缺陷
