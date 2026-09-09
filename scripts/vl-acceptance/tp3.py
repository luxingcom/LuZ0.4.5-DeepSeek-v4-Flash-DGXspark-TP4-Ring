import json, urllib.request, re, time
EP = "http://127.0.0.1:8002"
KEY = "<BEARER>"
MODEL = "deepseek-v4-flash-vision-exp"
def g(name, txt):
    m = re.search(r"(?m)^" + re.escape(name) + r"\{[^}]*\}\s+(\S+)", txt)
    return float(m.group(1)) if m else 0.0
def metrics():
    txt = urllib.request.urlopen(EP + "/metrics", timeout=10).read().decode()
    pos = {}
    for m in re.finditer(r"(?m)^vllm:spec_decode_num_accepted_tokens_per_pos_total\{[^}]*position=\"(\d+)\"[^}]*\}\s+(\S+)", txt):
        pos[int(m.group(1))] = float(m.group(2))
    return {"pos": pos,
            "drafts": g("vllm:spec_decode_num_drafts_total", txt),
            "accepted": g("vllm:spec_decode_num_accepted_tokens_total", txt),
            "draft_tokens": g("vllm:spec_decode_num_draft_tokens_total", txt)}
def chat(kwargs):
    body = {"model": MODEL, "messages": [{"role": "user", "content": "小华有 47 颗糖，她把糖分给 3 位朋友，每位朋友得到 12 颗，随后妈妈又给了她 8 颗。请问小华现在有多少颗糖？请一步步推理。"}], "temperature": 0.6, "max_tokens": 512, "ignore_eos": True}
    if kwargs: body["chat_template_kwargs"] = kwargs
    req = urllib.request.Request(EP + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
    dt = round(time.time() - t0, 1)
    msg = r["choices"][0]["message"]
    rc = msg.get("reasoning_content")
    ct = (msg.get("content") or "")
    return {"msg_keys": sorted(msg.keys()), "reasoning_len": len(rc) if rc else 0, "reasoning_head": (rc or "")[:50], "content_head": ct[:50], "ct": r["usage"]["completion_tokens"], "wall_s": dt}
def diff(x, y):
    return {k: y[k] - x[k] for k in ("drafts", "accepted", "draft_tokens")}
m0 = metrics()
a = chat(None)
m1 = metrics()
b = chat({"thinking": False})
m2 = metrics()
da, db = diff(m0, m1), diff(m1, m2)
pa = {p: m1["pos"].get(p, 0) - m0["pos"].get(p, 0) for p in sorted(set(m0["pos"]) | set(m1["pos"]))}
pb = {p: m2["pos"].get(p, 0) - m1["pos"].get(p, 0) for p in sorted(set(m1["pos"]) | set(m2["pos"]))}
def alen(d):
    return round(1 + d["accepted"] / d["drafts"], 3) if d["drafts"] else None
out = {"default_resp": a, "thinking_false_resp": b,
       "delta_default": da, "delta_tfalse": db,
       "perpos_default": pa, "perpos_tfalse": pb,
       "acceptlen_incl_bonus_default": alen(da), "acceptlen_incl_bonus_tfalse": alen(db)}
print(json.dumps(out, ensure_ascii=False, indent=1))
