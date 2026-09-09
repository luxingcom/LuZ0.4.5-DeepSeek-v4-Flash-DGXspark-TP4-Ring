#!/bin/bash
# bench_short_suite.sh v2 — 用户定版短测矩阵（2026-08-31）
# PR@32K(C1/2/4/8) + DE@2K->4K(C1/2/4/8)；每格 warm-up 1 轮不计统计 + 3 计量轮 per-round seed
# 用法: bash bench_short_suite.sh <TAG> <OUT_BASE>
set -u
TAG=$1
OUT=$2
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"
LOGD=$OUT/$TAG
mkdir -p "$LOGD"

run_cell () {
  local name=$1 seed=$2 warmup=$3
  shift 3
  echo "== [$TAG] cell=$name base_seed=$seed warmup=$warmup $(date -u +%H:%M:%S) =="
  if [ "$warmup" = "yes" ]; then
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $seed --out "$LOGD/${name}_warmup" >> $LOGD/run.log 2>&1
    echo "${name}_warmup_exit=$?"
  fi
  for r in 1 2 3; do
    local rs=$((seed + r * 1000))
    python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
      "$@" --rounds 1 --random-seed $rs --out "$LOGD/${name}_r$r" >> $LOGD/run.log 2>&1
    echo "${name}_r${r}_exit=$?"
  done
  python3 - <<PYEOF
import json
vals={}
for r in (1,2,3):
    try:
        d=json.load(open("$LOGD/${name}_r%d/summary_v2.json"%r))
        s=d["summary"][0]
        vals[r]={"seed":s.get("random_seed") or s.get("seed"),"p50_tps":s.get("p50_prefill_tps"),"p50_decode_tps":s.get("p50_decode_tps"),"ttft":s.get("p50_ttft_s"),"total":s.get("p50_total_s"),"ok":s.get("requests_ok")}
    except Exception as e:
        vals[r]={"err":str(e)}
print("CELL_RESULT $TAG $name", json.dumps(vals), flush=True)
PYEOF
}

echo "==== SUITE $TAG start $(date -u) ===="
python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
  --run-type de --concurrency 1 --task-type coding --input-len 512 --output-len 128 \
  --rounds 1 --random-seed 999900 --out "$LOGD/global_warmup" >> $LOGD/run.log 2>&1
echo "global_warmup_exit=$?"

# DE 格：input 2048 -> output 4096（bench_v2 默认 DE_OUTPUT_LEN=4096，禁止 --output-len 覆盖）
# 并发映射（dspark spec=7）：C1->8 / C2->16 / C4->32 / C8->64 tokens/step，对应 capture 档 A(16档)/C(11档) 均存在
for cc in 1 2 4 8; do
  run_cell "DE_C$cc" $((5000 + cc)) yes \
    --run-type de --concurrency $cc --task-type coding --input-len 2048
done

# PR@32K 格：--uuid-prefix 杜绝 APC 跨 run 命中；PR 模式自动 output_len=1
for cc in 1 2 4 8; do
  run_cell "PR32K_C$cc" $((60000 + cc)) yes \
    --run-type pr --concurrency $cc --task-type coding --prefix-len 32768 --uuid-prefix
done

echo "==== SUITE $TAG done $(date -u) ===="
echo "SUITE_${TAG}_DONE"
