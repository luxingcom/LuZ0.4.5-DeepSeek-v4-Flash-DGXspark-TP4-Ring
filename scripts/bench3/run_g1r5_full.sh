#!/bin/bash
# G1r5 全量重测 (LuZ-0.4.4-G1r5, digest 353697b2)
# 序列: DE C1 -> PR@4K uuid冷算 C1/C2/C4/C8 -> GSM8K 全量1319题 -> PR131K C2/C4
# 口径: uuid-prefix 冷算 3 轮中位; 对照: DE c1 103-113 / PR4K 2893系 / GSM8K >=0.930
# 先轻后重: 131K 最重放最后, 配合外部温度监控 (>=93C 干预)
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/g1r5-full
mkdir -p $OUT
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"

run_cell () {
  local name=$1 seed=$2 warmup=$3 cooldown=$4
  shift 4
  echo "== CELL $name base_seed=$seed warmup=$warmup cooldown=$cooldown $(date -u +%H:%M:%S) =="
  if [ "$warmup" = "yes" ]; then
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $seed --cooldown $cooldown --out "$OUT/${name}_warmup" >> $OUT/run.log 2>&1
    echo "${name}_warmup_exit=$?"
  fi
  for r in 1 2 3; do
    local rs=$((seed + r * 1000))
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $rs --cooldown $cooldown --out "$OUT/${name}_r$r" >> $OUT/run.log 2>&1
    echo "${name}_r${r}_exit=$?"
  done
  python3 - <<PYEOF
import json
vals={}
for r in (1,2,3):
    try:
        d=json.load(open("$OUT/${name}_r%d/summary_v2.json"%r))
        s=d["summary"][0]
        vals[r]={"prefill_tps":s.get("p50_prefill_tps"),"decode_tps":s.get("p50_decode_tps"),"ttft_s":s.get("p50_ttft_s"),"total_s":s.get("p50_total_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL_RESULT $name", json.dumps(vals), flush=True)
PYEOF
}

echo "==== G1R5 FULL start $(date -u) ===="

# 1) DE C1 (对照带 103-113)
run_cell "DE_C1" 5101 yes 5 \
  --run-type de --concurrency 1 --task-type coding --input-len 2048

# 2) PR@4K uuid 冷算 (对照 2893/4743 系)
for cc in 1 2 4 8; do
  run_cell "PR4K_C$cc" $((41000 + cc)) yes 5 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 4096 --uuid-prefix
done

# 3) GSM8K 全量 (>=0.930 门)
echo "== GSM8K full start $(date -u) =="
bash /home/_PH_USER_/w6-kit/gsm8k_full_g1r5.sh >> $OUT/gsm8k_run.log 2>&1
echo "GSM8K_EXIT=$?"
cat /home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R5/gsm8k_merged_summary.json 2>/dev/null; echo

# 4) PR131K C2/C4 (uuid 冷算, 最重最后, 控制并发)
for cc in 2 4; do
  run_cell "PR131K_C$cc" $((92000 + cc)) yes 20 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 131072 --uuid-prefix
done

echo "==== G1R5 FULL done $(date -u) ===="
echo "BENCH_G1R5_FULL_DONE"
