#!/bin/bash
# ==============================================================
# SCRIPT: start_tp4_head_v043.sh
# VERSION: v044-r1 (W9-R8 定版, 2026-08-29)  [文件名沿用 v043 系列以保 systemd/monitor 兼容]
# 生产形态: LuZ-0.4.4 | DE c1=113.47(+4.3% vs 0.26) PR@4K=2869 GSM8K全量=0.9378 PASS
#
# ─── 研究资料索引（后续调查从这里入手）──────────────────────────
# 证据与报告 (/home/_PH_USER_/w9-evidence/w9r4/):
#   0.4.5-RESUME-HANDBOOK.md      ★0.4.5 暂停归档启动必读(官方 0.28.0+12 补丁迁移暂停: accept/decode/prefill 未达标; 含 12 补丁清单/结论链/恢复步骤)
#   W9-R4-TAKEOVER-REPORT.md      接管调查: 8 项错误结论更正(镜像真身/3060 口径/APC 9.2x 假象/MTP 翻案)
#   W9-R5-PHASE2-REPORT.md        网络拓扑(2×CX-7=同卡 x8 定制,每 function PCIe x4)/W4A4 资产/tonyd2wild 互参/GLM+dflash2 路线
#   W9-R6-PHASE3-W4A4-REPORT.md   W4A4 迁移: --moe-backend flashinfer_b12x(B12X_MXFP4=MXFP4 权重×NVFP4 激活)超越旧生产
#   W9-R7-POOLED-OVERLAY-AB-REPORT.md  池化 overlay A/B 判负(收益前提只存在于 0.2.1 旧镜像)
#   W9-R8-PARAMETER-DOSSIER.md    ★全参数比选 dossier(每项候选/过程/理由)
#   W9-R8-COMMUNITY-SURVEY.md     社区问题×本栈适用性(9 项) + 稳定性规程五条
#   W9-R8-RINGONLY-V5-LATENCY.md  ringonly v4 配对表解读 + v5-quad 门控设计与 A/B
#   s0_capability_matrix.md       镜像能力矩阵(flag/backend 枚举实证)
#   s3_mtp_results.md / s4s5_arms_and_final.md / t8_apc_investigation.md / s8_three_way.csv
# 关键资产:
#   ringonly 源码  _PH_INSTALL_DIR_/backup/nccl-official-2307-hardened-20260816 (git 0dd44cd, 血统 md5 2be94172 一致)
#   v5 库          w6-kit/ringonly-v5/ (NCCL_RING_MAP=quad 门控, 默认 v4 字节兼容)
#   tonyd2wild 归档 w6-kit/reference/GLM-5.3-Flash-NVFP4-1M-KV-4x-DGX-Spark/ (8 项 GB10 修复/dflash2 overlay/取证)
#   W4A4 自研内核  _PH_INSTALL_DIR_/nvfp4/ (routeA kernel1/v17 kernel2/plugin-src/routeb_official_v2 + docs/)
#   0.26 生产档案  _PH_INSTALL_DIR_/backup/luz031-checkpoint-20260823/ (LuZ0.3.1 参考基线 2950/108.84/3057)
#   服务器02(.187) 家目录: 0.26 时代全套测试资料(tessa/gw4000/v026r)
# 已修复雷点(勿回退):
#   ① persistent_topk >24K 上下文必崩(GB10 48SM/99KB) → SM≥78 门控已烘焙入镜像(DEEP-DECODE 29K PASS)
#   ② flashinfer<0.6.18 缺 topk=192 → 0.6.18 已烘焙(DSpark graphs 11/11 铁证判据)
#   ③ bench_v2.py 无 MTP 崩溃 → md5 8c06bc06 (bak: .bak-nomtpfix-20260829)
# 回滚链: .bak-mtp-20260829(无MTP v043) → 镜像 tag 改回 LuZ-0.4.3-RingMOD+恢复挂载 → monitor 自动重建
# 密码纪律: sudo=_PH_PASSWORD_ | 集群钟慢本地 8h | docker rm 重建才刷新挂载
# 保留挂载(数据类): /models(ro) /var/log/vllm(rw) flashinfer-cache/tilelang-cache(rw)
# 移除挂载(已烘焙): fi18-wheels / indexer补丁 / libncclpin.so / nccl-ringonly / nccl-w7.conf
# ==============================================================
set -uo pipefail
export HOME=/home/_PH_USER_
NAME="vllm028-tp4-rank0"
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
  -e NODE_RANK=0 -e MASTER_ADDR=_PH_NODE_IP_ -e MASTER_PORT=26000 \
  -e VLLM_HOST_IP=_PH_NODE_IP_ \
  -v _PH_INSTALL_DIR_/models/deepseek-v4-flash-0731:/models:ro \
  -v /home/_PH_USER_/vllm-logs:/var/log/vllm \
  -v /home/_PH_USER_/flashinfer-cache:/root/.cache/flashinfer:rw \
  -v /home/_PH_USER_/tilelang-cache:/root/.cache/tilelang:rw \
  -v /home/_PH_USER_/b12x-cache:/root/.cache/b12x:rw \
  -v /home/_PH_USER_/vllm-cache:/root/.cache/vllm:rw \
  --health-cmd "curl -sf -o /dev/null -m 30 http://127.0.0.1:8002/health || exit 1" \
  --health-interval 30s --health-timeout 35s --health-retries 5 --health-start-period 900s \
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
  --tensor-parallel-size 4 --nnodes 4 --node-rank 0 \
  --master-addr _PH_NODE_IP_ --master-port 26000"
echo "[v044] head 容器已启动: $NAME (port 8002, 镜像烘焙态: FI0.6.18+indexer门控+ringonly-v5)"
