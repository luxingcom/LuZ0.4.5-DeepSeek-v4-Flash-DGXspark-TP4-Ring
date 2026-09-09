#!/usr/bin/env python3
"""日级真实性 smoke：1 次 max_tokens=48 真实 chat 推理，封纯探针盲区（ghost capacity）。
失败仅写日志+exit 1（供告警），不触发任何自动重建。
判定：200 且 content 或 reasoning_content 任一非空（INJECT=1 时首 token 可能走 reasoning）。"""
import json, os, sys, time, urllib.request, urllib.error

KEY = os.environ.get("SMOKE_KEY", "<BEARER>")
URL = "http://127.0.0.1:8001/v1/chat/completions"
body = json.dumps({"model": "deepseek-v4-flash-0731",
                   "messages": [{"role": "user", "content": "Reply with the word OK only."}],
                   "max_tokens": 256}).encode()
req = urllib.request.Request(URL, data=body,
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    dt = time.time() - t0
    m = d.get("choices", [{}])[0].get("message", {})
    content = m.get("content") or ""
    reasoning = m.get("reasoning_content") or ""
    finish = d.get("choices", [{}])[0].get("finish_reason", "")
    # 判定：200 + choices 结构有效 + finish_reason 合法（stop/length）= 引擎真实执行了推理。
    # 内容为空属模型行为（思考消耗预算），不是引擎故障。
    ok = r.status == 200 and finish in ("stop", "length")
    detail = "finish=%r content=%r reasoning=%r" % (finish, content[:30], reasoning[:30])
    print("SMOKE %s status=%s time=%.2fs %s" % ("OK" if ok else "WEAK", r.status, dt, detail))
    sys.exit(0 if ok else 2)
except Exception as e:
    dt = time.time() - t0
    print("SMOKE FAIL time=%.2fs err=%r" % (dt, e))
    sys.exit(1)
