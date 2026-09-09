#!/bin/bash
# G1R6 窗口2: +VLLM_MOE_DYNAMIC_TILE_CAP=0 (解除 tile_m 封顶 64, 免费回收候选 -7.4%)
# 验证: PR@4K uuid冷算 C1/C2/C4/C8 x3 (对照 G1r5 2671/2061/900/541) + DE C1 x3
# 崩溃哨兵: dmesg Xid 43 新增 + moe/decode launch 失败 grep
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/g1r6-w2
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

echo "==== G1R6 W2 start $(date -u) ===="
echo "ENV=VLLM_MOE_DYNAMIC_TILE_CAP=0 (解除 tile_m 封顶 64)"

# 崩溃哨兵基线
dmesg 2>/dev/null | grep -c "Xid" > $OUT/xid_baseline.txt || echo 0 > $OUT/xid_baseline.txt
echo "xid_baseline=$(cat $OUT/xid_baseline.txt)"

# 1) PR@4K uuid 冷算全格 x3 (核心性能横向对比)
for cc in 1 2 4 8; do
  run_cell "PR4K_C$cc" $((71000 + cc)) yes 5 \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 4096 --uuid-prefix
done

# 2) DE C1 x3 (decode 侧无回归)
run_cell "DE_C1" 7201 yes 5 \
  --run-type de --concurrency 1 --task-type coding --input-len 2048

# 崩溃哨兵复核
echo "=== crash sentinel ==="
echo "xid_now=$(dmesg 2>/dev/null | grep -c 'Xid' || echo 0)"
echo "moe_launch_fail=$(printf '%s\n' '_PH_PASSWORD_' | sudo -S docker logs vllm028-tp4-rank0 2>&1 | grep -icE 'cudaErrorLaunchFailure|launch failed' || echo 0)"
echo "engine_dead=$(printf '%s\n' '_PH_PASSWORD_' | sudo -S docker ps --format '{{.Status}}' 2>/dev/null | grep -c healthy || echo 0)"

echo "==== G1R6 W2 done $(date -u) ===="
echo "BENCH_G1R6_W2_DONE"
