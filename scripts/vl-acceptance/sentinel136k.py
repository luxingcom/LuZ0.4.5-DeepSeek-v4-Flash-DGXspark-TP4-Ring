import json, urllib.request, time, random

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}
MODEL = "deepseek-v4-flash-vision-exp"
SEED = random.randrange(10**6)

random.seed(SEED)
# ~13.6K chars pure text (#4973 IMA risk sentinel)
words = ["系统", "数据", "服务", "网络", "模型", "参数", "部署", "监控", "日志", "任务",
         "缓存", "节点", "接口", "配置", "队列", "线程", "副本", "索引", "带宽", "延迟"]
lines = []
target_len = 13600
cur = 0
i = 0
while cur < target_len:
    i += 1
    n = random.randint(4, 9)
    sent = "".join(random.choice(words) for _ in range(n))
    line = "条目%d：%s标记%d，状态正常。" % (i, sent, random.randint(1000, 99999))
    lines.append(line)
    cur += len(line)
doc = "\n".join(lines)
question = "以下是纯文本数据。请阅读后回答：文中共有多少个条目？（格式为 条目N）只输出一个数字。\n\n" + doc
print("doc_chars=%d seed=%d lines=%d" % (len(doc), SEED, len(lines)))

body = {"model": MODEL, "messages": [{"role": "user", "content": question}], "max_tokens": 300, "temperature": 0}
req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HEADERS)
t0 = time.time()
with urllib.request.urlopen(req, timeout=600) as r:
    d = json.loads(r.read())
dt = time.time() - t0
ans = d["choices"][0]["message"]["content"]
usage = d.get("usage", {})
print("time=%.1fs prompt_tokens=%s completion_tokens=%s finish=%s" % (dt, usage.get("prompt_tokens"), usage.get("completion_tokens"), d["choices"][0].get("finish_reason")))
print("ANSWER:", (ans or "<None>").strip()[:200])
expected = str(len(lines))
ok = ans and expected in ans
print("==G4b sentinel136k== pass=%s expected_lines=%s" % (ok, expected))
