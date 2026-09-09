#!/bin/bash
# =============================================================
# SCRIPT: start_tp4_head.sh
# VERSION: v1.5-r11
# USAGE: bash start_tp4_head.sh [--help]  (systemd 由 monitor_tp4_head.sh 调用)
# ROLE: head(rank0) 启动 — node01 (_PH_HEAD_IP_.186)
# HOST: node01
# DOCS: file:///opt/_PH_INSTALL_/docs/scripts/REFERENCE.md
# DOCS: file:///opt/_PH_INSTALL_/docs/ops/server-maintenance-handbook.md
# DOCS: file:///opt/_PH_INSTALL_/docs/runbook-tp4-v1.5-2026-08-12.md
# EXITCODES: 0=成功 1=业务失败 2=用法错误 130=被signal
# 控制面: MASTER_ADDR/VLLM_HOST_IP=_PH_NODE_IP_ MASTER_PORT=25999
# 容器: vllm-tp4-rank0 --restart no
# =============================================================
set -euo pipefail

# -h/--help (无位置参数, 不干扰 systemd/monitor 调用)
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'EOF'
start_tp4_head.sh — TP4 head(rank0) 启动 (node01)
  R11 关键参数: seqs=6 | util=0.65 | capture=1..64(max64) | PSR: NCCL=8-9 EngineCore=15-19
  用法: systemd(monitor_tp4_head.sh) 调用, 或手动 bash start_tp4_head.sh [--help]
参考: /opt/_PH_INSTALL_/docs/scripts/REFERENCE.md（脚本↔文档索引）| /opt/_PH_INSTALL_/docs/README.md（入口）
EOF
  exit 0
fi

[ "$(hostname)" = "node01" ] && [ "${NODE_RANK:-0}" = "0" ] || {
  echo "ERROR: 本脚本仅可在 node01(NODE_RANK=0) 运行" >&2
  exit 1
}

IMG="REGISTRY_HOST:5000/anemll/dspark-vllm-gx10:LuZ0.3.1"
NAME="vllm028-tp4-rank0"
NEW_SERVED_NAME="deepseek-v4-flash-0731"
PORT="8002"
MASTER_ADDR="_PH_HEAD_IP_.186"
MASTER_PORT="26000"
NODE_RANK=0

# ---- 回滚锚点 ----
docker inspect "$NAME" > "/opt/_PH_INSTALL_/backup/rollback_tp4-rank0.json" 2>/dev/null || true

SERVE_CMD="rm -rf /tmp/plugin_a1_install; cp -r /opt/_PH_INSTALL_/nvfp4/plugin_a1 /tmp/plugin_a1_install 2>/dev/null; pip install --no-deps -q /tmp/plugin_a1_install >/dev/null 2>&1; vllm serve\
  --model /models\
  --served-model-name deepseek-v4-flash-0731\
  --kv-cache-dtype nvfp4_ds_mla\
  --max-model-len 600000\
  --max-num-seqs 12\
  --max-num-batched-tokens 8192\
  --long-prefill-token-threshold 4096\
  --scheduling-policy priority\
  --gpu-memory-utilization 0.80\
  --enable-auto-tool-choice\
  --tool-call-parser deepseek_v4\
  --reasoning-parser deepseek_v4\
  --speculative-config '{\"method\":\"dspark\",\"num_speculative_tokens\":7,\"draft_sample_method\":\"probabilistic\"}'\\
  --moe-backend flashinfer_b12x\
  --distributed-executor-backend mp\
  --distributed-timeout-seconds 300\
  --port 8002\
  --api-key \"${VLLM_API_KEY:-dummy-bench}\"\
  --enable-flashinfer-autotune\
  --max-cudagraph-capture-size 96\
  --cudagraph-capture-sizes 1 2 4 8 16 24 32 36 40 48 56 64 72 80 88 96\
  --enable-prefix-caching\
  --enable-prompt-tokens-details\
  --generation-config vllm\
  --tensor-parallel-size 4 --nnodes 4 --node-rank 0\
  --master-addr ${MASTER_ADDR} --master-port ${MASTER_PORT}"
echo "[i] serve 命令: $SERVE_CMD"

ENV_ARGS=(
  -e 'CUDA_DEVICE_ORDER=PCI_BUS_ID'
  -e 'CUDA_VISIBLE_DEVICES=0'
  -e 'DG_JIT_NVCC_COMPILER=/tmp/env-e-build/nvcc_wrapper.py'
  -e 'DG_JIT_USE_NVRTC=0'
  -e 'DSPARK_SLOT_CLAMP=1'
  -e 'FLASHINFER_DISABLE_VERSION_CHECK=1'
  -e 'GLOO_SOCKET_IFNAME=enP7s7'
  -e 'HEADLESS='
  -e 'HF_HOME=/cache/huggingface'
  -e 'HF_HUB_OFFLINE=1'
  -e 'LANG=C.UTF-8'
  -e 'LC_ALL=C.UTF-8'
  -e 'LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/nvidia/nccl/lib:/usr/lib/aarch64-linux-gnu'
  -e 'LD_PRELOAD=/opt/libncclpin.so /opt/nccl-ringonly/libnccl.so.2'
  -e "MASTER_ADDR=${MASTER_ADDR}"
  -e "MASTER_PORT=${MASTER_PORT}"
  -e 'NCCL_ALGO=RING'
  -e 'NCCL_CROSS_NIC=1'
  -e 'NCCL_DEBUG=INFO'
  -e 'NCCL_DEBUG_FILE=/var/log/vllm/nccl-%h.log'
  -e 'NCCL_IB_GID_INDEX=3'
  -e 'NCCL_IB_HCA=rocep1s0f0,rocep1s0f1,roceP2p1s0f0,roceP2p1s0f1'   # 4 twin 口全暴露
  -e 'NCCL_IB_TIMEOUT=1000'
  -e 'NCCL_IB_RETRY_CNT=7'
  -e 'NCCL_IB_TOS=46'
  -e 'NCCL_IGNORE_CPU_AFFINITY=1'
  # === NCCL 延迟优化 T1aM4+MAX_CH16 (2026-08-16 生产生效) ===
  # 来源: deliverables/engineering-assurance/nccl-p0-scan-results-2026-08-16.md
  #       + nccl-maxch16-e2e-verification-2026-08-16.md
  # MIN_NCHANNELS 2->4: 通道下限提升; PROTO=Simple: 368KB档去LL128开销
  # BUFFSIZE 4M->8M: 加深小消息管道; MAX_NCHANNELS=16: 修正64通道协议误判
  #   (368KB/16=23KB/通道选对协议, 368KB allreduce 923->173us, -81%)
  # 端到端: 32K PR+5.5%/DE+6.5%/TTFT-4%; 131K PR+21.7%/TTFT-17.2%
  -e 'NCCL_MIN_NCHANNELS=4'
  -e 'NCCL_TUNER_THRESHOLD=40960'
  -e 'NCCL_BUFFSIZE=8388608'
  -e 'NCCL_MAX_NCHANNELS=4'
  -e 'NCCL_SET_THREAD_NAME=1'
  -e 'NCCL_NET=IB'
  -e 'NCCL_IB_SUBNET_AWARE_ROUTING=1'
  -e 'NCCL_NET_PLUGIN=none'
  -e 'NCCL_IB_MERGE_NICS=0'
  -e 'NCCL_SOCKET_IFNAME=enP7s7'
  -e "NODE_RANK=${NODE_RANK}"
  -e 'NVIDIA_VISIBLE_DEVICES=all'
  -e 'PATH=/opt/venv/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
  -e 'PIP_DISABLE_PIP_VERSION_CHECK=1'
  -e "PORT=${PORT}"
  -e 'PYTHONDONTWRITEBYTECODE=1'
  -e 'PYTHONUNBUFFERED=1'
  -e 'VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=1800'
  -e 'PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True'
  -e 'SERVED_MODEL_NAME=deepseek-v4-flash-0731'
  -e 'TILELANG_CLEANUP_TEMP_FILES=1'
  -e 'TORCH_CUDA_ARCH_LIST=12.1a'
  -e 'VLLM_ALLOW_LONG_MAX_MODEL_LEN=1'
  -e 'VLLM_DISABLE_PYNCCL=1'
  -e 'VLLM_ENGINE_READY_TIMEOUT_S=600'
  -e "VLLM_HOST_IP=${MASTER_ADDR}"
  -e "VLLM_DP_MASTER_IP=${MASTER_ADDR}"
  -e 'VLLM_USE_B12X_MOE=1'
  -e 'VLLM_USE_BREAKABLE_CUDAGRAPH=1'
  -e 'VLLM_PREFIX_CACHE_RETENTION_INTERVAL=4096'
  -e 'VLLM_USE_FLASHINFER_SAMPLER=1'
  -e 'VLLM_DSPARK_LOCAL_ARGMAX=1'
  -e 'PYTHONPATH=/opt/_PH_INSTALL_/nvfp4/kernel1:/opt/_PH_INSTALL_/nvfp4/kernel2'
  -e 'VLLM_TRITON_MLA_SPARSE=1'
  # === W4A4 arm (ws-dedup L3, 2026-08-23) ===
  -e 'VLLM_MOE_W4A4=2'
  -e 'VLLM_MOE_W4A4_MIN_M=3072'
  -e 'VLLM_MOE_W4A4_CG=1'
  -e 'VLLM_B12X_SHARED_WRAPPER=1'
)


BINDS=(
  -v /opt/_PH_INSTALL_/models/deepseek-v4-flash-0731:/models:ro
  -v /opt/_PH_INSTALL_/envs/nvcc_wrapper.py:/tmp/env-e-build/nvcc_wrapper.py:ro
  -v /opt/_PH_INSTALL_/envs/vllm-envc-cache:/cache/huggingface
  -v /opt/_PH_INSTALL_/nvfp4:/opt/_PH_INSTALL_/nvfp4:ro
  -v "$HOME/vllm-cache:/root/.cache/vllm:rw"
  -v "$HOME/tilelang-cache:/root/.tilelang/cache:rw"
  -v "$HOME/b12x-cache:/root/.cache/b12x:rw"
  -v /opt/_PH_INSTALL_/lib/libncclpin.so:/opt/libncclpin.so:ro
  -v /opt/nccl-ringonly:/opt/nccl-ringonly:ro
  -v /opt/_PH_INSTALL_/overlay-wsdedup/flashinfer_b12x_moe.py:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/fused_moe/experts/flashinfer_b12x_moe.py:ro
  # === FI 0.6.16 overlay (fi016 窗口注入; 2026-08-23 03:01 被 w4a4-ext 恢复误覆盖, luz031 补回) ===
  -v /opt/_PH_INSTALL_/nvfp4/flashinfer-0.6.16/flashinfer:/usr/local/lib/python3.12/dist-packages/flashinfer:ro
  -v "$HOME/flashinfer-cache:/root/.cache/flashinfer:rw"
)

docker run -d --name "$NAME" \
  --restart no \
  --network host --ipc=host --privileged --gpus all \
  --cpuset-cpus=1-19 \
  --memory 116g --memory-swap 116g \
  --log-opt max-size=100m --log-opt max-file=5 \
  --shm-size=64gb --ulimit memlock=-1 --ulimit stack=67108864 --ulimit nofile=1048576 \
  --health-cmd "curl -sf -o /dev/null -m 5 http://127.0.0.1:8002/health || exit 1" \
  --health-interval 30s --health-timeout 10s --health-retries 5 --health-start-period 900s \
  "${BINDS[@]}" \
  -v ~/vllm-logs:/var/log/vllm \
  "${ENV_ARGS[@]}" \
  --entrypoint /bin/bash \
  "$IMG" -lc "$SERVE_CMD"

echo "[i] 容器已启动: ${NAME}"
echo "[i] 等待就绪 (≤15min cold start): 轮询 docker logs 'Application startup complete'"
if [ "${NO_WAIT:-0}" = "1" ]; then echo "[i] NO_WAIT 模式: 容器已启动, 交回 monitor 跟随"; exit 0; fi
for i in $(seq 1 180); do
  if docker logs "$NAME" 2>&1 | grep -q "Application startup complete"; then
    echo "[ok] READY (${i}0s)"; exit 0
  fi
  sleep 10
done
echo "[warn] 未就绪（可能仍在加载权重）; 观察 docker logs ${NAME}" >&2
exit 1
