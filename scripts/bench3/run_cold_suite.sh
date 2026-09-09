#!/bin/bash
# VL cold full suite - strict serial
set -u
rm -f /tmp/vl-acceptance/TEMP_BREACH
source /home/_PH_USER_/bench3-results/vl-cold-20260909/run_cell.sh

echo "== C1 DE matrix 18 cells start $(date "+%F %T") =="
for task in coding json prose; do
  for cc in 1 2 4 6 8 12; do
    run_cell DE_${task}_C$cc $((81000 + 100*$(echo $task | wc -c) + cc)) --run-type de --concurrency $cc --task-type $task --input-len 512 --output-len 4096 --uuid-prefix
  done
done

echo "== C2 PR matrix 30 cells start $(date "+%F %T") =="
for pl in 512 2048 8192 32768 131072; do
  for cc in 1 2 4 6 8 12; do
    run_cell PR${pl}_C$cc $((92000 + pl/512 + cc)) --run-type pr --concurrency $cc --task-type coding --prefix-len $pl --output-len 1 --uuid-prefix
  done
done

echo "== C3 PR400K C2 start $(date "+%F %T") =="
run_cell PR400K_C2 960101 --run-type pr --concurrency 2 --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix --cooldown 30

echo "== C4 GSM8K full 1319 @4096 start $(date "+%F %T") =="
python3 /tmp/vl-acceptance/gsm8k_cold.py
echo "GSM8K_EXIT=$? $(date "+%F %T")"

echo "== C5 spec long-gen + vision start $(date "+%F %T") =="
python3 /tmp/vl-acceptance/speclong.py
echo "SPEC_EXIT=$?"
python3 /tmp/vl-acceptance/vision_tps.py
echo "VISION_EXIT=$?"

echo "COLD_SUITE_DONE $(date "+%F %T")"
