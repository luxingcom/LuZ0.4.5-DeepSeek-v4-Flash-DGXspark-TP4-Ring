#!/usr/bin/env python3
# 投机长生成复测: >=1K token 输出, 取 metrics spec 计数 delta 算接受长度
import json, urllib.request, time, re

METRICS = "http://127.0.0.1:8002/metrics"
API = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}

def get_spec():
    d = urllib.request.urlopen(METRICS, timeout=30).read().decode()
    def g(name):
        m = re.search(name + r"\{[^}]*\} ([0-9.e+]+)", d)
        return float(m.group(1)) if m else 0.0
    return {"drafts": g("vllm:spec_decode_num_drafts_total"),
            "draft_tokens": g("vllm:spec_decode_num_draft_tokens_total"),
            "accepted": g("vllm:spec_decode_num_accepted_tokens_total")}

def gen(max_tokens, prompt):
    body = {"model": "deepseek-v4-flash-vision-exp",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.7}
    req = urllib.request.Request("http://127.0.0.1:8001/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers=API)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    return d, time.time() - t0

# warmup 短请求
gen(32, "你好")
s0 = get_spec()
d, dt = gen(1536, "请写一篇约1500字的短文，主题：分布式系统中的共识算法。要求连续成文，涵盖 Paxos、Raft、ZAB 三类算法的原理对比、适用场景与工程实践要点，分多个段落展开。")
s1 = get_spec()
ct = d["usage"]["completion_tokens"]
dd = s1["drafts"] - s0["drafts"]
da = s1["accepted"] - s0["accepted"]
dtok = s1["draft_tokens"] - s0["draft_tokens"]
print("completion_tokens=%d wall=%.1fs decode_tps=%.1f" % (ct, dt, ct / dt))
print("delta_drafts=%d delta_draft_tokens=%d delta_accepted=%d" % (dd, dtok, da))
if dd > 0:
    print("mean_accepted_per_draft(excl_bonus)=%.3f" % (da / dd))
    print("mean_tokens_per_forward(incl_bonus)=%.3f" % ((da + dd) / dd))
print("SPEC_LONG_DONE")
