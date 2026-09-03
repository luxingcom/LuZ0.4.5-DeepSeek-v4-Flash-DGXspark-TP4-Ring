#!/bin/bash
# run_ext_400k_only.sh — 扩展档精简版：仅 PR400K C1（131K 段已被完整矩阵同口径覆盖，跳过）
# 口径: 与 run_ext_full.sh 的 PR400K C1 一致 (prefix-len 400000, output-len 1, uuid-prefix, cooldown 30)
# 输出: /home/_PH_USER_/bench3-results/full-matrix-045/ (与矩阵同目录, 便于 FINAL-METRICS 汇总)
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/full-matrix-045
EP="http://_PH_NODE_IP_:8002/v1"
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

echo "==== EXT 400K ONLY start $(date -u) ===="
echo "MODE=prefix-caching OFF (cold data); 131K skipped (already in full matrix)"

# PR400K C1 (warmup+3 计量, cooldown 30s, output-len 1)
run_cell "PR400K_C1" 960001 30 \
  --run-type pr --concurrency 1 --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix

echo "==== EXT 400K ONLY done $(date -u) ===="
echo "BENCH_EXT_400K_DONE"
