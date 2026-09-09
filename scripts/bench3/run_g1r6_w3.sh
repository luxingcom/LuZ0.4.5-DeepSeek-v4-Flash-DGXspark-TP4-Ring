#!/bin/bash
# G1R6 窗口3: +VLLM_DRAFT_LOGITS_DTYPE=bfloat16 (B1: draft_logits fp32->bf16, 预期 +0.1%)
# 验收: DE C1 x3 + accept-length 变化<0.5% + GSM8K 全量 >=0.9356
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/g1r6-w3
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

echo "==== G1R6 W3 start $(date -u) ===="
echo "ENV=VLLM_DRAFT_LOGITS_DTYPE=bfloat16 (B1)"

# 1) DE C1 x3 (B1 收益验证)
run_cell "DE_C1" 8301 yes 5 \
  --run-type de --concurrency 1 --task-type coding --input-len 2048

# 2) accept-length 统计 (B1 验收: 变化<0.5%)
echo "=== accept-length ==="
printf '%s\n' '_PH_PASSWORD_' | sudo -S docker logs vllm028-tp4-rank0 2>&1 | grep -iE "accept|MTP|speculative" | tail -5 || echo "no accept log"

# 3) GSM8K 全量 (B1 验收门 >=0.9356)
echo "== GSM8K full start $(date -u) =="
bash /home/_PH_USER_/w6-kit/gsm8k_full_g1r6.sh >> $OUT/gsm8k_run.log 2>&1
echo "GSM8K_EXIT=$?"
cat /home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R6/gsm8k_merged_summary.json 2>/dev/null; echo

echo "==== G1R6 W3 done $(date -u) ===="
echo "BENCH_G1R6_W3_DONE"
