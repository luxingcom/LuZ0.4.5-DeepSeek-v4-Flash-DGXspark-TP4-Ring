#!/bin/bash
# 通用切换：LuZ0.3.1 组合 <TAG>（四机）
# 用法: bash switch_combo.sh <cA|cB|cC>
set -uo pipefail
TAG="${1:?需要 TAG}"
BENCH=/home/_PH_USER_/w6-kit/bench3
case $TAG in
  cA) THR=1024; BAT=2048;;
  cB) THR=2048; BAT=4096;;
  cC) THR=4096; BAT=8192;;
  *) echo "未知 TAG"; exit 1;;
esac
echo "=== 切换 combo $TAG (thr=$THR bat=$BAT) ==="
docker rm -f vllm028-tp4-rank0 2>/dev/null
ssh -o BatchMode=yes node02 "docker rm -f vllm028-tp4-rank1 2>/dev/null" 2>/dev/null
ssh -o BatchMode=yes node04 "docker rm -f vllm028-tp4-rank2 2>/dev/null" 2>/dev/null
ssh -o BatchMode=yes node03 "docker rm -f vllm028-tp4-rank3 2>/dev/null" 2>/dev/null
sleep 2
cd ~ && NO_WAIT=1 bash $BENCH/start_head_luz031_$TAG.sh 2>&1 | tail -2
ssh -o BatchMode=yes node02 "cd ~ && NO_WAIT=1 NODE_RANK=1 VLLM_HOST_IP=_PH_HEAD_IP_.187 bash ~/w6-kit/bench3/start_worker_luz031_$TAG.sh" 2>&1 | tail -1
ssh -o BatchMode=yes node04 "cd ~ && NO_WAIT=1 NODE_RANK=2 VLLM_HOST_IP=_PH_HEAD_IP_.189 bash ~/w6-kit/bench3/start_worker_luz031_$TAG.sh" 2>&1 | tail -1
ssh -o BatchMode=yes node03 "cd ~ && NO_WAIT=1 NODE_RANK=3 VLLM_HOST_IP=_PH_HEAD_IP_.188 bash ~/w6-kit/bench3/start_worker_luz031_$TAG.sh" 2>&1 | tail -1
sleep 6
docker ps --format "{{.Names}} {{.Status}} {{.Image}}" | grep vllm028
echo "SWITCH_${TAG}_DONE"
