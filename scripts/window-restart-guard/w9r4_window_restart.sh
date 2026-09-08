#!/bin/bash
# w9r4_window_restart.sh — W9-R4 全链受控重启（head→workers, 等待 health=200）
# 用途: 换镜像 tag/换形态后的标准化全链重启原语; 顺序: stop workers(.187/.188/.189)→stop head
#       →start head→等 :26000 TCPStore→start workers→轮询 /health=200(最长 30x30s), 失败 tail rank0 日志
# 口径: 纯运维原语, 无基准输出、无 TAG(与 w9r4_s2_baseline.sh / w9r8_full_suite.sh 的 TAG 隔离无关);
#       经 systemctl 重启即按 start_tp4_*_v043.sh 当前内容重建容器(镜像 tag/挂载以脚本为准)
# V5b-窗口修订 (2026-09-07, 交接清单 D2 + 容器更名配套):
#   1. D2: TCPStore 等待超时后 fail-fast 全链退出(不再落入 start workers 产生分裂集群);
#   2. 单元/容器名双代名兼容(vllm028-tp4-* 与 vllm-tp4-*, 2026-09-07 更名后现役为后者);
#   3. 退出前清理: 超时即 stop head 单元, 保持四机静止便于人工介入.
set -u
PW='_PH_PASSWORD_'
# 双代名: 优先新名, 旧名回退(旧单元 inactive+disabled 但保留)
# 单元名固定为新名（vllm-tp4-*）——旧单元 vllm028-* 仅用于 stop（防残留 monitor 抢拉）。
# 教训（2026-09-07 B窗1）：用 grep 探测旧单元文件存在性来选名是错的——旧单元文件
# inactive+disabled 保留作回退，探测会误选旧名导致新单元从未被 start。
UNIT_HEAD="vllm-tp4-head"
CNAME="vllm-tp4-rank"

date '+[restart] stop workers %T'
for X in 187 188 189; do
  timeout 30 ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=no _PH_USER_@_PH_HEAD_IP_.${X} \
    "echo '$PW' | sudo -S systemctl stop vllm-tp4-worker vllm028-tp4-worker 2>/dev/null; sleep 1; docker rm -f \$(docker ps -aq --filter name=tp4-rank) 2>/dev/null; sleep 1; echo .${X}:\$(docker ps -aq --filter name=tp4-rank | wc -l)" 2>&1 | tail -1
done
date '+[restart] stop head %T'
echo "$PW" | sudo -S systemctl stop vllm-tp4-head vllm028-tp4-head 2>/dev/null
docker rm -f vllm-tp4-rank0 2>/dev/null
sleep 2
echo "local rank containers: $(docker ps -aq --filter name=tp4-rank | wc -l)"
date '+[restart] start head %T'
echo "$PW" | sudo -S systemctl start "${UNIT_HEAD}" 2>/dev/null
TCPSTORE_UP=0
for i in $(seq 1 24); do
  N=$(ss -ltn 2>/dev/null | grep -c ":26000 ")
  if [ "$N" -ge 1 ]; then echo "[TCPStore up] ${i}x5s"; TCPSTORE_UP=1; break; fi
  sleep 5
done
# D2 修复: TCPStore 超时 => fail-fast, 不再起 workers (历史两次分裂集群事故根因)
if [ "$TCPSTORE_UP" -ne 1 ]; then
  echo "[FAIL-D2] TCPStore 26000 未在 120s 内监听 -- head 未就绪, 拒绝启动 workers (防分裂集群)" >&2
  echo "[FAIL-D2] 自动停 head 单元保持四机静止: systemctl stop ${UNIT_HEAD}" >&2
  echo "$PW" | sudo -S systemctl stop "${UNIT_HEAD}" 2>/dev/null
  docker logs ${CNAME}0 2>&1 | tail -20 || docker logs vllm028-tp4-rank0 2>&1 | tail -20
  exit 2
fi
date '+[restart] start workers %T'
for X in 187 188 189; do
  timeout 25 ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=no _PH_USER_@_PH_HEAD_IP_.${X} \
    "echo '$PW' | sudo -S systemctl start vllm-tp4-worker 2>/dev/null || echo '$PW' | sudo -S systemctl start vllm028-tp4-worker 2>/dev/null; echo .${X} started" 2>&1 | tail -1
done
date '+[restart] wait health %T'
for i in $(seq 1 40); do
  H=$(curl -s -o /dev/null -w "%{http_code}" -m 5 http://127.0.0.1:8002/health 2>/dev/null)
  [ "$H" = "200" ] && { echo "[READY] ${i}x30s health=200"; exit 0; }
  sleep 30
done
echo "[FAIL] health 未就绪"; docker logs vllm-tp4-rank0 2>&1 | tail -20 || docker logs vllm028-tp4-rank0 2>&1 | tail -20
exit 1
