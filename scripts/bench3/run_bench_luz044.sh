#!/bin/bash
# LuZ0.3.1 基础轮基准：PR@4K + PR@32K × C1/C2/C4/C8
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/luz044
mkdir -p $OUT
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"

run_cell () {
  local name=$1 seed=$2
  shift 2
  # warmup 1 轮
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
    "$@" --rounds 1 --random-seed $seed --out "$OUT/${name}_warmup" >> $OUT/run.log 2>&1
  echo "${name}_warmup_exit=$?"
  # 3 计量轮
  for r in 1 2 3; do
    local rs=$((seed + r * 1000))
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $rs --out "$OUT/${name}_r$r" >> $OUT/run.log 2>&1
    echo "${name}_r${r}_exit=$?"
  done
  # 汇总
  python3 - <<PYEOF
import json
vals={}
for r in (1,2,3):
    try:
        d=json.load(open("$OUT/${name}_r%d/summary_v2.json"%r))
        s=d["summary"][0]
        vals[r]={"p50_prefill":s.get("p50_prefill_tps"),"p50_ttft":s.get("p50_ttft_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL $name", json.dumps(vals), flush=True)
PYEOF
}

echo "==== BENCH luz044 start $(date -u) ===="
# global warmup
python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
  --run-type pr --concurrency 1 --task-type coding --prefix-len 4096 --uuid-prefix \
  --rounds 1 --random-seed 999900 --out "$OUT/global_warmup" >> $OUT/run.log 2>&1
echo "global_warmup_exit=$?"

# PR@4K
for cc in 1 2 4 8; do
  run_cell "PR4K_C$cc" $((40000 + cc)) \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 4096 --uuid-prefix
done
# PR@32K
for cc in 1 2 4 8; do
  run_cell "PR32K_C$cc" $((60000 + cc)) \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 32768 --uuid-prefix
done

echo "==== BENCH luz044 done $(date -u) ===="
echo "BENCH_LUZ044_DONE"
