#!/bin/bash
# G1r3 cB 扩展轮：PR@131K + PR@400K × C1/C2/C4/C6 (output-len 1)
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/ext-g1r3-cB
mkdir -p $OUT
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"

run_cell () {
  local name=$1 seed=$2 cooldown=$3
  shift 3
  # warmup 1 轮
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
    "$@" --rounds 1 --random-seed $seed --cooldown $cooldown --out "$OUT/${name}_warmup" >> $OUT/run.log 2>&1
  echo "${name}_warmup_exit=$?"
  # 3 计量轮
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
        vals[r]={"p50_prefill":s.get("p50_prefill_tps"),"p50_ttft":s.get("p50_ttft_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL ${name}", json.dumps(vals), flush=True)
PYEOF
}

echo "==== BENCH ext-g1r3-cB start $(date -u) ===="
# 全局 warmup（131K 单请求，验证可行性）
python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
  --run-type pr --concurrency 1 --task-type coding --prefix-len 131072 --output-len 1 --uuid-prefix \
  --rounds 1 --random-seed 888800 --cooldown 20 --out "$OUT/global_warmup_131k" >> $OUT/run.log 2>&1
echo "global_warmup_131k_exit=$?"

# PR131K: C1 先行 → C2 → C4 → C6
for cc in 1 2 4 6; do
  run_cell "PR131K_C$cc" $((90000 + cc)) 20 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 131072 --output-len 1 --uuid-prefix
done

# PR400K: C1 先行验证（OOM/超时降级）→ C2 → C4 → C6
for cc in 1 2 4 6; do
  run_cell "PR400K_C$cc" $((95000 + cc)) 30 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix
done

echo "==== BENCH ext-g1r3-cB done $(date -u) ===="
echo "BENCH_EXT_G1R3_CB_DONE"
