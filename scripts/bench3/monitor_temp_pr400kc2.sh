#!/bin/bash
# monitor_temp_pr400kc2.sh — PR400K C2 运行期温度监控（03 刚断电, 必须防再次过热断电）
# 逻辑: 每 20s 轮询四机 GPU 温度; >=93C 告警; 检测 BENCH_PR400K_C2_DONE 后退出
set -u
OUT=/home/_PH_USER_/bench3-results/full-matrix-045
NODES="186 187 188 189"
echo "== TEMP MONITOR start $(date '+%F %T') =="
for i in $(seq 1 400); do
  done_flag=$(ssh node01 "grep -c 'BENCH_PR400K_C2_DONE' $OUT/ext400k_nohup.log 2>/dev/null" 2>/dev/null)
  if [ "$done_flag" = "1" ]; then
    echo "PR400K_C2_DONE at check $i ($(date '+%F %T'))"
    break
  fi
  temps=""
  warn=0
  for h in $NODES; do
    t=$(ssh -o ConnectTimeout=6 -o BatchMode=yes _PH_USER_@_PH_HEAD_IP_.$h \
        "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null" 2>/dev/null)
    [ -z "$t" ] && t="NA"
    temps="$temps $h:$t"
    if [ "$t" != "NA" ] && [ "$t" -ge 93 ] 2>/dev/null; then
      warn=1
    fi
  done
  if [ $((i % 6)) -eq 0 ] || [ "$warn" = "1" ]; then
    echo "[temp $(date +%H:%M:%S)] $temps$([ $warn = 1 ] && echo '  <<< 93C ALERT!')"
  fi
  sleep 20
done
echo "== TEMP MONITOR EXIT $(date '+%F %T') =="
