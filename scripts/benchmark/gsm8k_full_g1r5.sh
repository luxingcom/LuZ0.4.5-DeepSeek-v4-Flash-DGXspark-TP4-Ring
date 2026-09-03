#!/bin/bash
# sre10_s8c_gsm8k.sh — T5 GSM8K 全量 1319 题: --skip 114 双下标法 (seg A: skip0 nq114, seg B: skip114 nq1205)
set -u
KIT=/home/_PH_USER_/w6-kit
LOGD=/home/_PH_USER_/w6-logs
OUT=$LOGD/W9R2_S8_GSM8K_G1R5
mkdir -p $OUT
echo "== S8c gsm8k full start $(date '+%F %T') =="

echo "== seg A: skip=0 nq=114 =="
python3 $KIT/w9r2_gsm8k_spot.py \
  --base http://_PH_NODE_IP_:8002 \
  --nq 114 --skip 0 \
  --out-raw $OUT/gsm8k_segA_raw.jsonl \
  --out-summary $OUT/gsm8k_segA_summary.json \
  > $OUT/gsm8k_segA_run.log 2>&1
echo "SEG_A_EXIT=$?"
cat $OUT/gsm8k_segA_summary.json 2>/dev/null; echo

echo "== seg B: skip=114 nq=1205 =="
python3 $KIT/w9r2_gsm8k_spot.py \
  --base http://_PH_NODE_IP_:8002 \
  --nq 1205 --skip 114 \
  --out-raw $OUT/gsm8k_segB_raw.jsonl \
  --out-summary $OUT/gsm8k_segB_summary.json \
  > $OUT/gsm8k_segB_run.log 2>&1
echo "SEG_B_EXIT=$?"
cat $OUT/gsm8k_segB_summary.json 2>/dev/null; echo

echo "== merged =="
python3 - << 'PYEOF'
import json, os
OUT = "/home/_PH_USER_/w6-logs/W9R2_S8_GSM8K_G1R5"
a = json.load(open(f"{OUT}/gsm8k_segA_summary.json"))
b = json.load(open(f"{OUT}/gsm8k_segB_summary.json"))
na, nb = a["nq"], b["nq"]
cc = a["correct_content"] + b["correct_content"]
cm = a["correct_marker"] + b["correct_marker"]
merged = {
  "nq_total": na + nb,
  "accuracy_content": round(cc / (na + nb), 4),
  "accuracy_marker": round(cm / (na + nb), 4),
  "correct_content": cc, "correct_marker": cm,
  "err": a["err"] + b["err"],
  "anchor_upstream_0p9492": True,
  "gate_pass_0p930_content": round(cc / (na + nb), 4) >= 0.930,
  "gate_pass_0p930_marker": round(cm / (na + nb), 4) >= 0.930,
  "ts": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
}
json.dump(merged, open(f"{OUT}/gsm8k_merged_summary.json", "w"), indent=2)
print(json.dumps(merged, indent=2))
PYEOF
echo "== S8c gsm8k end $(date '+%F %T') =="
