#!/bin/bash
# G1R6 窗口1: 只换镜像 (LuZ-0.4.4-G1r6, digest _PH_BAKE_IMAGE_DIGEST_), 不设新 env = G1r5 等价
# 验证: DE C1 x3 (对照 G1r5 99.72) + GSM8K spot200 (哨兵, 对照 >=0.930 门 / G1r5 0.9363)
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/g1r6-w1
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
        vals[r]={"prefill_tps":s.get("p50_prefill_tps"),"decode_tps":s.get("p50_decode_tps"),"ttft_s":s.get("p50_ttft_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL_RESULT $name", json.dumps(vals), flush=True)
PYEOF
}

echo "==== G1R6 W1 start $(date -u) ===="
echo "IMAGE=LuZ-0.4.4-G1r6 (digest _PH_BAKE_IMAGE_DIGEST_, 默认 env = G1r5 等价)"

# 1) DE C1 x3 (平台等价: 对照 G1r5 99.72)
run_cell "DE_C1" 6101 yes 5 \
  --run-type de --concurrency 1 --task-type coding --input-len 2048

# 2) GSM8K spot200 哨兵 (平台等价 + 精度无退化)
echo "== GSM8K spot200 start $(date -u) =="
mkdir -p /home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R6
python3 /home/_PH_USER_/w6-kit/w9r2_gsm8k_spot.py \
  --base http://_PH_HEAD_IP_.186:8002 \
  --nq 200 --skip 0 \
  --out-raw /home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R6/gsm8k_spot200_raw.jsonl \
  --out-summary /home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R6/gsm8k_spot200_summary.json \
  > $OUT/gsm8k_spot200_run.log 2>&1
echo "GSM8K_SPOT200_EXIT=$?"
cat /home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R6/gsm8k_spot200_summary.json 2>/dev/null; echo

echo "==== G1R6 W1 done $(date -u) ===="
echo "BENCH_G1R6_W1_DONE"
