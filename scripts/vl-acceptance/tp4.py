import json, urllib.request
EP = "http://127.0.0.1:8002"
KEY = "<BEARER>"
MODEL = "deepseek-v4-flash-vision-exp"
PROMPT = "一个小车以每小时 60 公里的速度行驶 2.5 小时，然后以每小时 80 公里的速度行驶 1.5 小时。总路程是多少公里？请先在内心思考再作答。"
def chat(kwargs):
    body = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "temperature": 0.6, "max_tokens": 512, "ignore_eos": True}
    if kwargs: body["chat_template_kwargs"] = kwargs
    req = urllib.request.Request(EP + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
    msg = r["choices"][0]["message"]
    rsn = msg.get("reasoning")
    ct = (msg.get("content") or "")
    return {"reasoning_is_none": rsn is None, "reasoning_len": len(rsn) if rsn else 0, "reasoning_head": (rsn or "")[:60].replace(chr(10), " "), "content_head": ct[:60].replace(chr(10), " "), "ct": r["usage"]["completion_tokens"]}
a = chat(None)
b = chat({"thinking": False})
print(json.dumps({"default": a, "thinking_false": b}, ensure_ascii=False, indent=1))
