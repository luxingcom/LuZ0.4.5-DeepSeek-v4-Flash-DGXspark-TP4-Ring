#!/bin/bash
# monitor_tp4_head_v043.sh — v043-r1 (W9R2 rex8) 源: monitor_tp4_head.sh v1.5-r11
# 语义保留: docker wait 跟随 + head 重建前 ssh 清 worker 容器 + D3 rank 就绪门禁(60s 无进展 fail)
# rex-g 20260831: 增加 guard 互斥(本机任一 vLLM TP4 容器-新旧两代-存在即跟随等待, 防双自愈链并发拉起抢端口);
#                 head 重建前清理扩展为两代容器名(旧 vllm-tp4-rank* + 新 vllm028-tp4-rank*)
set -uo pipefail
export HOME=/home/_PH_USER_
NAME=vllm028-tp4-rank0
MASTER_PORT=26000
# guard 互斥: 本机存在任一 vLLM TP4 容器(新旧两代) => 跟随其退出, 绝不并发拉起第二套栈
if docker ps --format '{{.Names}}' | grep -qE '^(vllm028-tp4-rank|vllm-tp4-rank)[0-9]*$'; then
  EXISTING=$(docker ps --format '{{.Names}}' | grep -E '^(vllm028-tp4-rank|vllm-tp4-rank)[0-9]*$' | head -1)
  echo "[guard] 本机已有容器 ${EXISTING}, 跟随等待其退出, 不并发拉起" >&2
  docker wait "$EXISTING" || true
  exit 1
fi
for host in node0X node0X node0X; do
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" \
    "docker rm -f \$(docker ps -aq --filter name=vllm028-tp4-rank) \$(docker ps -aq --filter name=vllm-tp4-rank) 2>/dev/null" >/dev/null 2>&1 || true
done
NO_WAIT=1 bash /home/_PH_USER_/w6-kit/start_tp4_head_v043.sh || exit 1
echo "[i] 等待 head TCPStore :${MASTER_PORT} 就绪..."
for i in $(seq 1 60); do
  if ss -ltn 2>/dev/null | grep -q ":${MASTER_PORT} "; then break; fi
  if [ "$i" -eq 60 ]; then echo "[fail] TCPStore 60s 未监听, 快速失败"; exit 1; fi
  sleep 5
done
echo "[i] TCPStore 就绪, 等待 4 rank 接入 (60s 无新进展即放弃)"
LAST=0
NO_PROGRESS=0
while :; do
  N=$(ss -tn state established 2>/dev/null | grep -c ":${MASTER_PORT} ")
  if [ "$N" -ge 3 ]; then
    echo "[ok] rank 全齐 (TCPStore ${N} 连接)"
    break
  fi
  if [ "$N" -gt "$LAST" ]; then
    LAST="$N"; NO_PROGRESS=0
    echo "[i] rank 进展: ${N}/3 worker 接入"
  else
    NO_PROGRESS=$((NO_PROGRESS+1))
  fi
  if [ "$NO_PROGRESS" -ge 12 ]; then
    echo "[fail] 60s 无新 rank 接入 (当前 ${N}/3), 触发 head-first 全链重建" >&2
    exit 1
  fi
  sleep 5
done
# ===== CUDA 图/关键 kernel 首次运行预热 (W9R11 2026-09-02 督导指令) =====
# 目的: 长上下文(如 400K)首次运行时 JIT 编译(flashinfer/tilelang/cute-dsl)可能在 prefill
#       中途触发, 导致首请求极慢/疑似卡死; 预热使编译在正式流量前完成。
#       注意: head 发预热请求经 TP4 分发会触发全链各 rank worker 的 kernel 编译。
echo "[warmup] 等待引擎 health=200 (最长 10min) 后执行 CUDA 图首次运行预热..."
WARMUP_READY=0
for i in $(seq 1 60); do
  if curl -sf -o /dev/null -m 5 http://127.0.0.1:8002/health 2>/dev/null; then WARMUP_READY=1; break; fi
  sleep 10
done
if [ "$WARMUP_READY" = "1" ]; then
  echo "[warmup] 引擎就绪 (${i}x10s), 发送预热请求 (max_tokens=16, timeout 120s)..."
  WARMUP_RC=$(curl -sf -o /dev/null -w "%{http_code}" -m 120 \
    http://127.0.0.1:8002/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"deepseek-v4-flash-0731","prompt":"warmup-cuda-graph","max_tokens":16,"stream":false}' 2>&1)
  echo "[warmup] 预热请求完成 http=$WARMUP_RC (CUDA 图首运行 + JIT kernel 编译已触发)"
else
  echo "[warmup] 引擎 10min 内未就绪, 跳过预热 (自愈链将接管)"
fi
# ===== 预热结束 =====
docker wait "$NAME" || true
exit 1
