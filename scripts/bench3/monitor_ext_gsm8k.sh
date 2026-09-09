#!/bin/bash
# monitor_ext_gsm8k.sh — 扩展档衔接监控: PR400K 完成 → 自动启动 GSM8K 全量 → 监控 merged summary
# 依赖: run_ext_400k_only.sh 已在服务器后台运行 (ext400k_nohup.log)
set -u
OUT=/home/_PH_USER_/bench3-results/full-matrix-045
GSM8K_SH=/home/_PH_USER_/w6-kit/gsm8k_full_g1r5.sh
GSM8K_OUT=/home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R5

echo "== MONITOR start $(date '+%F %T') =="

# ---- Phase 1: 等 PR400K 完成 (ext400k_nohup.log 出现 BENCH_EXT_400K_DONE) ----
for i in $(seq 1 60); do
  done_flag=$(ssh node01 "grep -c 'BENCH_EXT_400K_DONE' $OUT/ext400k_nohup.log 2>/dev/null" 2>/dev/null)
  if [ "$done_flag" = "1" ]; then
    echo "PR400K_DONE at check $i ($(date +%H:%M:%S))"
    ssh node01 "grep -E 'CELL_RESULT_EXT|_exit' $OUT/ext400k_nohup.log | tail -8"
    break
  fi
  # 每 5 次打印一次状态
  if [ $((i % 5)) -eq 0 ]; then
    last=$(ssh node01 "tail -2 $OUT/ext400k_nohup.log 2>/dev/null | head -1" 2>/dev/null)
    echo "[ext check $i] $last"
  fi
  sleep 30
done

# 若 PR400K 超时未完成, 仍继续检查一次最终状态
if ! ssh node01 "grep -q 'BENCH_EXT_400K_DONE' $OUT/ext400k_nohup.log" 2>/dev/null; then
  echo "WARN: PR400K not done after 30min; proceeding to check final status"
  ssh node01 "tail -10 $OUT/ext400k_nohup.log" 2>/dev/null
fi

# ---- Phase 2: 启动 GSM8K 全量 (串行, 避免负载干扰) ----
echo "== Starting GSM8K full at $(date '+%F %T') =="
ssh node01 "nohup bash $GSM8K_SH > $OUT/gsm8k_full_nohup.log 2>&1 & echo GSM8K_STARTED_PID=\$!" 2>/dev/null

# ---- Phase 3: 等 GSM8K merged summary 出现 (最长 2h) ----
for i in $(seq 1 120); do
  merged=$(ssh node01 "ls -la $GSM8K_OUT/gsm8k_merged_summary.json 2>/dev/null | wc -l" 2>/dev/null)
  if [ "$merged" = "1" ]; then
    echo "GSM8K_DONE at check $i ($(date +%H:%M:%S))"
    ssh node01 "cat $GSM8K_OUT/gsm8k_merged_summary.json 2>/dev/null"
    break
  fi
  if [ $((i % 10)) -eq 0 ]; then
    seg=$(ssh node01 "tail -1 $GSM8K_OUT/gsm8k_segB_run.log 2>/dev/null" 2>/dev/null)
    echo "[gsm8k check $i] segB: $seg"
  fi
  sleep 60
done

echo "== MONITOR EXIT $(date '+%F %T') =="
