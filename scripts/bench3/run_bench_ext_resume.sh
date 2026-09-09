#!/bin/bash
# G1r3 cB 扩展轮续跑（2026-09-01，2300MHz 新频率制）: 仅续跑此前因过热断电失败的单元格
#   PR131K: C4(重跑全3轮) + C6
#   PR400K: C1/C2/C4/C6
# 输出目录沿用 ext-g1r3-cB（C1/C2@131K 保留既有有效数据）
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/ext-g1r3-cB
mkdir -p $OUT
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"
LOG=$OUT/run_resume.log

run_cell () {
  local name=$1 seed=$2 cooldown=$3
  shift 3
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
    "$@" --rounds 1 --random-seed $seed --cooldown $cooldown --out "$OUT/${name}_warmup" >> $LOG 2>&1
  echo "${name}_warmup_exit=$?"
  for r in 1 2 3; do
    local rs=$((seed + r * 1000))
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $rs --cooldown $cooldown --out "$OUT/${name}_r$r" >> $LOG 2>&1
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

echo "==== BENCH ext-resume start $(date -u) ===="
# PR131K: C4 全量重跑 + C6
run_cell "PR131K_C4" 91000 20 \
  --run-type pr --concurrency 4 --task-type coding --prefix-len 131072 --output-len 1 --uuid-prefix
run_cell "PR131K_C6" 92000 20 \
  --run-type pr --concurrency 6 --task-type coding --prefix-len 131072 --output-len 1 --uuid-prefix
# PR400K: C1 先行 → C2 → C4 → C6
for cc in 1 2 4 6; do
  run_cell "PR400K_C$cc" $((95000 + cc)) 30 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix
done
echo "==== BENCH ext-resume done $(date -u) ===="
echo "BENCH_EXT_RESUME_DONE"
