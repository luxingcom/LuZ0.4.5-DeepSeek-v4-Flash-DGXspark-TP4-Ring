#!/bin/bash
# monitor_tp4_worker_v043.sh — v043-r1 (W9R2 rex8) 源: monitor_tp4_worker.sh v1.5-r11
# 语义保留: head-first TCPStore 门禁(≤120s) + 集群成形后本 rank 缺失→触发 head 重建
# 适配: head 健康=8002, 容器名 vllm-tp4-rank*
# rex-g 20260831: 增加 guard 互斥(本机任一 vLLM TP4 容器-新旧两代-存在即跟随等待, 防双自愈链并发拉起抢端口)
set -uo pipefail
export HOME=/home/_PH_USER_
NAME="vllm-tp4-rank${NODE_RANK}"
MASTER_ADDR="_PH_HEAD_IP_.186"
MASTER_PORT="26000"
# guard 互斥: 本机存在任一 vLLM TP4 容器(新旧两代) => 跟随其退出, 绝不并发拉起第二套栈
if docker ps --format '{{.Names}}' | grep -qE '^(vllm-tp4-rank|vllm-tp4-rank)[0-9]*$'; then
  EXISTING=$(docker ps --format '{{.Names}}' | grep -E '^(vllm-tp4-rank|vllm-tp4-rank)[0-9]*$' | head -1)
  echo "[guard] 本机已有容器 ${EXISTING}, 跟随等待其退出, 不并发拉起" >&2
  docker wait "$EXISTING" || true
  exit 1
fi
HCODE=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://_PH_HEAD_IP_.186:8001/ping 2>/dev/null || true)
FORMED=$(ssh -o BatchMode=yes -o ConnectTimeout=5 node01 \
  "ss -tn state established 2>/dev/null | grep -c ':${MASTER_PORT} '" 2>/dev/null || echo 0)
if [ "$HCODE" = "200" ] && [ "${FORMED:-0}" -ge 3 ]; then
  echo "[i] head 健康且集群成形, 但 ${NAME} 缺失 => 触发 head 全链路重建"
  ssh -o BatchMode=yes -o ConnectTimeout=5 node01 "docker rm -f vllm-tp4-rank0" >/dev/null 2>&1 || true
  sleep 25
fi
for i in $(seq 1 24); do
  if (exec 3<>/dev/tcp/${MASTER_ADDR}/${MASTER_PORT}) 2>/dev/null; then exec 3>&- 2>&-; break; fi
  if [ "$i" -eq 24 ]; then echo "[fail] head TCPStore 不可达(120s), 放弃"; exit 1; fi
  sleep 5
done
# GID 预检 (W9R15 2026-09-03): 对端硬断电可致本机 RoCE GID idx3 全零 -> NCCL 建链必败
# (rank0: ibv_modify_qp errno 61, local GID ::). 空 GID 先 nmcli 复位再拉起, 避免重建死循环。
# 诊断口诀: rank0 日志 ibv_modify_qp errno 61 = 先查 GID, 勿误判为 NCCL/驱动问题。
bash /opt/_PH_INSTALL_/scripts/gid_preflight.sh --fix \
  || echo "[gid-preflight] WARN: GID 预检后仍异常, 继续(可能非 GID 根因)"
NODE_RANK="$NODE_RANK" VLLM_HOST_IP="$VLLM_HOST_IP" NO_WAIT=1 \
  bash /home/_PH_USER_/w6-kit/start_tp4_worker_v043.sh
exit $?
