#!/bin/bash
# 93C watchdog: sample all 4 hosts GPU temps every 60s, kill load if breach
set -u
PW=_PH_PASSWORD_
while true; do
  TS=$(date "+%F %T")
  TMP_LOCAL=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1)
  MAX=$TMP_LOCAL
  for X in 187 188 189; do
    T=$(timeout 10 ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no _PH_USER_@_PH_HEAD_IP_.$X "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1" 2>/dev/null)
    [ -n "$T" ] && [ "$T" -gt "$MAX" ] 2>/dev/null && MAX=$T
  done
  echo "$TS max=${MAX}C" >> /tmp/vl-acceptance/vlcold_temp.log
  if [ -n "$MAX" ] && [ "$MAX" -ge 93 ] 2>/dev/null; then
    echo "$TS BREACH ${MAX}C - killing bench load" >> /tmp/vl-acceptance/vlcold_temp.log
    pkill -f "bench_v2.py" 2>/dev/null
    pkill -f "gsm8k_cold.py" 2>/dev/null
    touch /tmp/vl-acceptance/TEMP_BREACH
  fi
  sleep 60
done
