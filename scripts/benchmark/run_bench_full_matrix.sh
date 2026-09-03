#!/bin/bash
# run_bench_full_matrix.sh — LuZ0.4.5 完整矩阵基准（督导确认口径, 2026-09-02）
# 覆盖: DE 3任务×C1/C2/C4/C6/C8/C12 + PR 5档×C1/C2/C4/C6/C8/C12
# 口径: uuid-prefix 冷算 3 波中位; 直连 8002; 目标镜像 LuZ0.4.5-...-Ring-baked
# 扩展档(131K/400K)与 GSM8K 由既有脚本单独跑（run_pr400k_c1.sh / gsm8k_full_g1r5.sh）
# 用法: bash run_bench_full_matrix.sh [--quick]  (--quick = 跳过 C6/C12 减半时间)
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/full-matrix-045
mkdir -p $OUT
EP="http://_PH_NODE_IP_:8002/v1"
MODEL="deepseek-v4-flash-0731"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

DE_CONC="1 2 4 6 8 12"
[ $QUICK -eq 1 ] && DE_CONC="1 4 8"
PR_CONC="1 2 4 6 8 12"
[ $QUICK -eq 1 ] && PR_CONC="1 4 8"
PR_PREFIX="512 2048 8192 32768 131072"

run_cell () {
  local name=$1 seed=$2 cooldown=$3
  shift 3
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
    "$@" --rounds 1 --random-seed $seed --cooldown $cooldown --out "$OUT/${name}_warmup" >> $OUT/run.log 2>&1
  echo "${name}_warmup_exit=$?"
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
        vals[r]={"prefill":s.get("p50_prefill_tps"),"decode":s.get("p50_decode_tps"),"ttft":s.get("p50_ttft_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL_RESULT $name", json.dumps(vals), flush=True)
PYEOF
}

echo "==== FULL MATRIX start $(date -u) ===="
echo "IMAGE=LuZ0.4.5-DeepSeek-v4-Flash-DGXspark-TP4-Ring-baked (digest 153e31d2)"

# 全局 warmup
python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
  --run-type pr --concurrency 1 --task-type coding --prefix-len 4096 --uuid-prefix \
  --rounds 1 --random-seed 999901 --out "$OUT/global_warmup" >> $OUT/run.log 2>&1

# ===== 阶段1: DE 文本生成吞吐 (3 任务 × 并发) =====
for task in coding json prose; do
  for cc in $DE_CONC; do
    run_cell "DE_${task}_C$cc" $((51000 + 100*$(echo "$task" | wc -c) + cc)) 5 \
      --run-type de --concurrency $cc --task-type $task --input-len 512 --output-len 4096
  done
done

# ===== 阶段2: PR 纯 prefill (5 档 × 并发) =====
for plen in $PR_PREFIX; do
  for cc in $PR_CONC; do
    run_cell "PR${plen}_C$cc" $((61000 + plen/1000 + cc)) 5 \
      --run-type pr --concurrency $cc --task-type coding --prefix-len $plen --uuid-prefix
  done
done

echo "==== FULL MATRIX done $(date -u) ===="
echo "BENCH_FULL_MATRIX_DONE"
