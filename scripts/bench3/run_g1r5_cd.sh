#!/bin/bash
# G1r5 cD 对比测试 (threshold=2048 + batched=8192)
# 同口径 uuid 冷算 3 轮中位, 与 g1r5-full(cB: 2048+4096) 对比
# 序列: DE C1 -> PR@4K C1/C2/C4/C8
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/g1r5-cD
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

echo "==== G1R5 cD start $(date -u) ===="

# 1) DE C1
run_cell "DE_C1" 5201 yes 5 \
  --run-type de --concurrency 1 --task-type coding --input-len 2048

# 2) PR@4K uuid 冷算 C1/C2/C4/C8
for cc in 1 2 4 8; do
  run_cell "PR4K_C$cc" $((43000 + cc)) yes 5 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 4096 --uuid-prefix
done

echo "==== G1R5 cD done $(date -u) ===="
echo "BENCH_G1R5_CD_DONE"
