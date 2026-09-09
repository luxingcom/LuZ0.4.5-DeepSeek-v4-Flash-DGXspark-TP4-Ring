import json, urllib.request, time, random

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}
MODEL = "deepseek-v4-flash-vision-exp"
SEED = random.randrange(10**6)

random.seed(SEED)
NEEDLE = "本次内部会议的机密代码是 VLX-7749-QUASAR，请务必记住它。"
# ~30K chars doc: random sentences, needle in the middle
words = ["系统", "数据", "服务", "网络", "模型", "参数", "部署", "监控", "日志", "任务",
         "缓存", "节点", "接口", "配置", "队列", "线程", "副本", "索引", "带宽", "延迟"]
lines = []
target_len = 30000
cur = 0
i = 0
while cur < target_len:
    i += 1
    n = random.randint(4, 9)
    sent = "".join(random.choice(words) for _ in range(n))
    line = "第%d条记录：%s编号为%d，状态为正常，已通过例行检查。" % (i, sent, random.randint(10000, 99999))
    lines.append(line)
    cur += len(line)
half = len(lines) // 2
doc_lines = lines[:half] + [NEEDLE] + lines[half:]
doc = "\n".join(doc_lines)

question = "以下是一份内部文档。请在阅读全文后，只回答一个问题：本次内部会议的机密代码是什么？请原样复述。\n\n" + doc + "\n\n请给出机密代码："
print("doc_chars=%d seed=%d needle_at_line=%d/%d" % (len(doc), SEED, half, len(doc_lines)))

body = {"model": MODEL, "messages": [{"role": "user", "content": question}], "max_tokens": 400, "temperature": 0}
req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HEADERS)
t0 = time.time()
with urllib.request.urlopen(req, timeout=600) as r:
    d = json.loads(r.read())
dt = time.time() - t0
ans = d["choices"][0]["message"]["content"]
usage = d.get("usage", {})
print("time=%.1fs prompt_tokens=%s completion_tokens=%s" % (dt, usage.get("prompt_tokens"), usage.get("completion_tokens")))
print("ANSWER:", (ans or "<None>").strip()[:300])
ok = ans and "VLX-7749-QUASAR" in ans
print("==G4a needle30k== pass=%s" % ok)
