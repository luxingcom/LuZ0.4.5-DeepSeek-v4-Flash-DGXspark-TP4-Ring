#!/bin/bash
# PR400K C1 验证（单请求 400K 前缀, output-len 1）
set -uo pipefail
OUT=/home/_PH_USER_/bench3-results/ext-g1r3-cB
EP="http://_PH_HEAD_IP_.186:8002/v1"
MODEL="deepseek-v4-flash-0731"
# warmup + 3 计量
python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
  --run-type pr --concurrency 1 --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix \
  --rounds 1 --random-seed 960001 --cooldown 30 --out "$OUT/PR400K_C1_warmup2" >> $OUT/pr400k.log 2>&1
echo "warmup_exit=$?"
for r in 1 2 3; do
  python3 /opt/_PH_INSTALL_/bench_v2.py --endpoint $EP --key dummy-bench --model $MODEL \
    --run-type pr --concurrency 1 --task-type coding --prefix-len 400000 --output-len 1 --uuid-prefix \
    --rounds 1 --random-seed $((960000 + r * 1000)) --cooldown 30 --out "$OUT/PR400K_C1_r${r}b" >> $OUT/pr400k.log 2>&1
  echo "r${r}_exit=$?"
done
python3 - <<PYEOF
import json
for r in (1,2,3):
    try:
        d=json.load(open("$OUT/PR400K_C1_r%db/summary_v2.json"%r))
        s=d["summary"][0]
        print("PR400K_C1 r%d: prefill=%s ttft=%s ok=%s"%(r,s.get("p50_prefill_tps"),s.get("p50_ttft_s"),s.get("requests_ok")))
    except Exception as e:
        print("PR400K_C1 r%d: ERR %s"%(r,e))
PYEOF
echo "PR400K_C1_DONE"
