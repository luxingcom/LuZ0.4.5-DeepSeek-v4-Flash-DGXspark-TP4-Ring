#!/bin/bash
# ==============================================================
# SCRIPT: start_tp4_worker_v043.sh
# VERSION: v044-r1 (W9-R8 定版, 2026-08-29)  [文件名沿用以保 systemd/monitor 兼容]
# USAGE: NODE_RANK=N VLLM_HOST_IP=<ip> bash start_tp4_worker_v043.sh (或由 monitor_v043 调用)
# HOST: node0X/03/04 (_PH_NODE_IP_/_PH_MGMT_OCTET_/_PH_MGMT_OCTET_)
# ─── 研究资料索引 ───（完整版见 start_tp4_head_v043.sh 头注）
#   全参数 dossier: w9-evidence/w9r4/W9-R8-PARAMETER-DOSSIER.md
#   镜像烘焙清单:   w6-kit/Dockerfile.LuZ-0.4.4（FI0.6.18+indexer门控+ringonly-v5+shim+conf）
#   W4A4 判决:      w9-evidence/w9r4/W9-R6-PHASE3-W4A4-REPORT.md
#   稳定性规程:     w9-evidence/w9r4/W9-R8-COMMUNITY-SURVEY.md §4
# 回滚: .bak-mtp-20260829 + 镜像 tag 回 LuZ-0.4.3-RingMOD
# ==============================================================
set -uo pipefail
export HOME=/home/_PH_USER_
NODE_RANK="${NODE_RANK:?need NODE_RANK}"
VLLM_HOST_IP="${VLLM_HOST_IP:?need VLLM_HOST_IP}"
NAME="vllm028-tp4-rank${NODE_RANK}"
KIT=/home/_PH_USER_/w6-kit
R5="REGISTRY_HOST:5000/vllm/vllm-openai:LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-baked"
ENVS=""
while IFS='=' read -r k v; do ENVS="$ENVS -e $k=$v"; done < <(grep -v '^\s*#' $KIT/w6_env.txt | grep -v '^\s*$')
mkdir -p /home/_PH_USER_/vllm-logs /tmp/vllm-crash
docker rm -f $NAME 2>/dev/null
docker run -d --name $NAME --gpus all --privileged --shm-size 64g \
  --ulimit memlock=-1 --ulimit nofile=1048576 \
  --ipc=host --network host --cpuset-cpus=1-19 --memory 116g --memory-swap 116g \
  -e PYTHONFAULTHANDLER=1 \
  $ENVS \
  -e NODE_RANK=$NODE_RANK -e MASTER_ADDR=_PH_NODE_IP_ -e MASTER_PORT=26000 \
  -e VLLM_HOST_IP=$VLLM_HOST_IP \
  -v _PH_INSTALL_DIR_/models/deepseek-v4-flash-0731:/models:ro \
  -v /home/_PH_USER_/vllm-logs:/var/log/vllm \
  -v /home/_PH_USER_/flashinfer-cache:/root/.cache/flashinfer:rw \
  -v /home/_PH_USER_/tilelang-cache:/root/.cache/tilelang:rw \
  -v /home/_PH_USER_/b12x-cache:/root/.cache/b12x:rw \
  -v /home/_PH_USER_/vllm-cache:/root/.cache/vllm:rw \
  --health-cmd "pgrep -f VLLM::EngineCore >/dev/null 2>&1 || exit 1" \
  --health-interval 30s --health-timeout 10s --health-retries 5 --health-start-period 900s \
  --log-opt max-size=100m --log-opt max-file=3 \
  --entrypoint /bin/bash \
  $R5 -lc "export LD_PRELOAD='/opt/libncclpin.so /opt/nccl-ringonly/libnccl.so.2' && vllm serve --model /models --served-model-name deepseek-v4-flash-0731 \
  --kv-cache-dtype fp8_ds_mla \
  --max-model-len 600000 --max-num-seqs 12 --max-num-batched-tokens 4096 \
  --long-prefill-token-threshold 2048 \
  --gpu-memory-utilization 0.80 \
  --moe-backend flashinfer_b12x \
  --disable-custom-all-reduce \
  --scheduling-policy priority \
  --distributed-executor-backend mp --distributed-timeout-seconds 1800 \
  --compilation-config '{\"cudagraph_mode\":\"FULL_AND_PIECEWISE\"}' \
  --speculative-config '{\"method\":\"dspark\",\"num_speculative_tokens\":7,\"draft_sample_method\":\"probabilistic\"}' \
  --attention-backend FLASHINFER_MLA_SPARSE_DSV4 \
  --max-cudagraph-capture-size 96 \
  --cudagraph-capture-sizes 1 2 4 8 16 24 32 36 40 48 56 64 72 80 88 96 \
  --enable-auto-tool-choice --tool-call-parser deepseek_v4 --reasoning-parser deepseek_v4 \
  --load-format safetensors \
  --port 8002 \
  --tensor-parallel-size 4 --nnodes 4 --node-rank $NODE_RANK \
  --master-addr _PH_NODE_IP_ --master-port 26000"
echo "[v044] worker 容器已启动: $NODE_RANK $NAME (镜像烘焙态)"
