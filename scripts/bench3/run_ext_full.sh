#!/bin/bash
# run_ext_full.sh — 长上下文扩展档完整执行（矩阵完成后衔接）
# 覆盖: PR131K C1/C2/C4 + PR400K C1（uuid-prefix 冷算 3 波中位）
# 前提: 完整矩阵已完成; 温度联动 >=93C 干预; 直连 8002
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/full-matrix-045
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"

run_cell () {
  local name=$1 seed=$2 cooldown=$3
  shift 3
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
    "$@" --rounds 1 --random-seed $seed --cooldown $cooldown --out "$OUT/${name}_warmup" >> $OUT/run_ext.log 2>&1
  echo "${name}_warmup_exit=$?"
  for r in 1 2 3; do
    local rs=$((seed + r * 1000))
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $rs --cooldown $cooldown --out "$OUT/${name}_r$r" >> $OUT/run_ext.log 2>&1
    echo "${name}_r${r}_exit=$?"
  done
  python3 - <<PYEOF
import json
vals={}
for r in (1,2,3):
    try:
        d=json.load(open("$OUT/${name}_r%d/summary_v2.json"%r))
        s=d["summary"][0]
        vals[r]={"prefill":s.get("p50_prefill_tps"),"ttft":s.get("p50_ttft_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL_RESULT_EXT $name", json.dumps(vals), flush=True)
PYEOF
}

echo "==== EXT FULL start $(date -u) ===="
echo "MODE=prefix-caching OFF (cold data)"

# PR131K C1/C2/C4 (uuid 冷算, 重档最后, 长 cooldown)
for cc in 1 2 4; do
  run_cell "PR131K_C$cc" $((92000 + cc)) 20 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 131072 --uuid-prefix
done

# PR400K C1 (warmup+3 计量, cooldown 30s)
run_cell "PR400K_C1" 960001 30 \
  --run-type pr --concurrency 1 --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix

echo "==== EXT FULL done $(date -u) ===="
echo "BENCH_EXT_FULL_DONE"
