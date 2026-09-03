#!/bin/bash
# run_pr400k_c2.sh — PR400K C2 重跑（用户指定: C2 并发更大压力）
# 背景: 上一轮 PR400K C1 因 03(188,rank3) 断电, r2/r3 失败, 仅 r1 有效 (prefill 1682/TTFT 209s)
# 口径: uuid-prefix 冷算 3 波中位; prefix-len 400000; output-len 1; cooldown 30s; concurrency=2
# 输出: /home/_PH_USER_/bench3-results/full-matrix-045/PR400K_C2_*
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

echo "==== PR400K C2 rerun start $(date -u) ===="
echo "MODE=prefix-caching OFF (cold data); conc=2; 03(188) 断电已恢复四机 healthy"

# PR400K C2 (warmup+3 计量, cooldown 30s, output-len 1, concurrency 2)
run_cell "PR400K_C2" 970001 30 \
  --run-type pr --concurrency 2 --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix

echo "==== PR400K C2 rerun done $(date -u) ===="
echo "BENCH_PR400K_C2_DONE"
