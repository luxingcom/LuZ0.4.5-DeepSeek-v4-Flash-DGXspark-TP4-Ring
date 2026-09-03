#!/bin/bash
# server_monitor_c2_gsm8k.sh — 服务器端(186)运行: PR400K C2 温度监控 + 完成后自动衔接 GSM8K
# 部署: scp 到 186 /home/_PH_USER_/w6-kit/bench3/ + nohup 运行 (本地沙箱无法 SSH, 故放服务器端)
set -u
OUT=/home/_PH_USER_/bench3-results/full-matrix-045
C2LOG=$OUT/pr400kc2_nohup.log
GSM8K_SH=/home/_PH_USER_/w6-kit/gsm8k_full_g1r5.sh
GSM8K_OUT=/home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R5
OTHERS="_PH_NODE_IP_ _PH_NODE_IP_ _PH_NODE_IP_"
echo "== SERVER MONITOR C2 start $(date '+%F %T') =="

# ---- Phase 1: 温度 + 等 C2 DONE (最长 2h, 每 30s) ----
for i in $(seq 1 240); do
  done_flag=$(grep -c 'BENCH_PR400K_C2_DONE' $C2LOG 2>/dev/null)
  if [ "$done_flag" = "1" ]; then
    echo "PR400K_C2_DONE at check $i ($(date '+%F %T'))"
    grep -E 'CELL_RESULT_EXT|_exit' $C2LOG | tail -8
    break
  fi
  # 温度: 186 本地 + 其他三机 ssh
  local_t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null)
  temps="186:$local_t"
  warn=0
  for h in $OTHERS; do
    t=$(ssh -o ConnectTimeout=6 -o BatchMode=yes _PH_USER_@$h \
        "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null" 2>/dev/null)
    [ -z "$t" ] && t="NA"
    temps="$temps $h:$t"
    if [ "$t" != "NA" ] && [ "$t" -ge 93 ] 2>/dev/null; then warn=1; fi
  done
  if [ $((i % 4)) -eq 0 ] || [ "$warn" = "1" ]; then
    echo "[temp $(date +%H:%M:%S)] $temps$([ $warn = 1 ] && echo '  <<< 93C ALERT!')"
  fi
  sleep 30
done

# 超时检查
if ! grep -q 'BENCH_PR400K_C2_DONE' $C2LOG 2>/dev/null; then
  echo "WARN: C2 not done after 2h; tail:"
  tail -8 $C2LOG
fi

# ---- Phase 2: 启动 GSM8K ----
echo "== Starting GSM8K full at $(date '+%F %T') =="
nohup bash $GSM8K_SH > $OUT/gsm8k_full_nohup.log 2>&1 &
echo "GSM8K_PID=$!"

# ---- Phase 3: 等 merged summary (最长 2h) ----
for i in $(seq 1 120); do
  if [ -f $GSM8K_OUT/gsm8k_merged_summary.json ]; then
    echo "GSM8K_DONE at check $i ($(date '+%F %T'))"
    cat $GSM8K_OUT/gsm8k_merged_summary.json
    break
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "[gsm8k check $i] $(tail -1 $GSM8K_OUT/gsm8k_segB_run.log 2>/dev/null)"
  fi
  sleep 60
done

echo "== SERVER MONITOR EXIT $(date '+%F %T') =="
