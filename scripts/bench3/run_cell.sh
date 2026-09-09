#!/bin/bash
set -u
EP="http://127.0.0.1:8002/v1"
MODEL="deepseek-v4-flash-vision-exp"
KEY="<BEARER>"
OUTROOT=/home/_PH_USER_/bench3-results/vl-cold-20260909

check_idle () {
  local R=$(curl -s -m 5 http://127.0.0.1:8002/metrics | grep "^vllm:num_requests_running" | grep -oE "[0-9.]+$")
  echo "$(date "+%T") pre-cell num_requests_running=${R:-NA} ${1:-}"
  if [ -f /tmp/vl-acceptance/TEMP_BREACH ]; then echo "TEMP_BREACH flag - abort chain"; exit 9; fi
}

run_cell () {
  local name=$1 seed=$2; shift 2
  check_idle "$name"
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key $KEY --model $MODEL \
    "$@" --rounds 1 --random-seed $seed --cooldown 5 --out "$OUTROOT/${name}_warmup" >> $OUTROOT/run.log 2>&1
  echo "${name}_warmup_exit=$?"
  for r in 1 2 3; do
    check_idle "${name}_r$r"
    local rs=$((seed + r * 1000))
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key $KEY --model $MODEL \
      "$@" --rounds 1 --random-seed $rs --cooldown 5 --out "$OUTROOT/${name}_r$r" >> $OUTROOT/run.log 2>&1
    echo "${name}_r${r}_exit=$?"
  done
  python3 - <<PYEOF
import json
vals={}
for r in (1,2,3):
    try:
        d=json.load(open("$OUTROOT/${name}_r%d/summary_v2.json"%r))
        s=d["summary"][0]
        vals[r]={"prefill":s.get("p50_prefill_tps"),"decode":s.get("p50_decode_tps"),"ttft":s.get("p50_ttft_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL_RESULT $name", json.dumps(vals), flush=True)
PYEOF
}
