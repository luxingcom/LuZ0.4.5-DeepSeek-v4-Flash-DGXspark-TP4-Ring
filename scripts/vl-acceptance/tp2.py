import json, urllib.request, re, time
EP = "http://127.0.0.1:8002"
KEY = "<BEARER>"
MODEL = "deepseek-v4-flash-vision-exp"
def metrics():
    txt = urllib.request.urlopen(EP + "/metrics", timeout=10).read().decode()
    pos = {}
    drafts = acc = dtok = 0.0
    for m in re.finditer(r"vllm:spec_decode_num_accepted_tokens_per_pos_total\{.*?position=\"(\d+)\".*?\}\s+(\S+)", txt, re.M):
        pos[int(m.group(1))] = float(m.group(2))
    m1 = re.search(r"(?m)^vllm:spec_decode_num_drafts_total\s+(\S+)", txt, re.M)
    m2 = re.search(r"(?m)^vllm:spec_decode_num_accepted_tokens_total\s+(\S+)", txt, re.M)
    m3 = re.search(r"(?m)^vllm:spec_decode_num_draft_tokens_total\s+(\S+)", txt, re.M)
    if m1: drafts = float(m1.group(1))
    if m2: acc = float(m2.group(1))
    if m3: dtok = float(m3.group(1))
    return {"pos": pos, "drafts": drafts, "accepted": acc, "draft_tokens": dtok}
def chat(kwargs):
    body = {"model": MODEL, "messages": [{"role": "user", "content": "用两百字介绍一下长江三峡大坝的主要功能。"}], "temperature": 0.6, "max_tokens": 512, "ignore_eos": True}
    if kwargs: body["chat_template_kwargs"] = kwargs
    req = urllib.request.Request(EP + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
    dt = time.time() - t0
    msg = r["choices"][0]["message"]
    rc = msg.get("reasoning_content")
    return {"reasoning_len": len(rc) if rc else 0, "ct": r["usage"]["completion_tokens"], "wall_s": round(dt, 1)}
def diff(x, y):
    return {k: round(y[k] - x[k], 1) for k in ("drafts", "accepted", "draft_tokens")}
m0 = metrics()
a = chat(None)
m1 = metrics()
b = chat({"thinking": False})
m2 = metrics()
da, db = diff(m0, m1), diff(m1, m2)
pa = {p: round(m1["pos"].get(p, 0) - m0["pos"].get(p, 0), 1) for p in sorted(set(m0["pos"]) | set(m1["pos"]))}
pb = {p: round(m2["pos"].get(p, 0) - m1["pos"].get(p, 0), 1) for p in sorted(set(m1["pos"]) | set(m2["pos"]))}
def alen(d):
    return round(1 + d["accepted"] / d["drafts"], 3) if d["drafts"] else None
out = {"default_resp": a, "thinking_false_resp": b, "delta_default": da, "delta_tfalse": db, "perpos_default": pa, "perpos_tfalse": pb, "acceptlen_default": alen(da), "acceptlen_tfalse": alen(db)}
print(json.dumps(out, ensure_ascii=False, indent=1))
