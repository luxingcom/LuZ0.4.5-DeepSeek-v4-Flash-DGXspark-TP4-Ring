import json, urllib.request, time

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}
MODEL = "deepseek-v4-flash-vision-exp"

questions = [
    {"q": "小明有 3 个苹果，妈妈又给了他 5 个苹果，请问小明现在一共有多少个苹果？请给出最终数字。", "expect": "8"},
    {"q": "一个班级有 24 名学生，平均分成 6 个小组，每个小组有多少名学生？请给出最终数字。", "expect": "4"},
    {"q": "一本书价格是 45 元，一支笔价格是 12 元，买一本书和两支笔一共需要多少元？请给出最终数字。", "expect": "69"},
]

def ask(q):
    body = {"model": MODEL, "messages": [{"role": "user", "content": q}], "max_tokens": 256, "temperature": 0}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HEADERS)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"], time.time() - t0

for i, item in enumerate(questions, 1):
    ans, dt = ask(item["q"])
    exp = item["expect"]
    ok = exp in ans
    print("==G2 Q%d== expect=%s pass=%s time=%.1fs" % (i, exp, ok, dt))
    print("ANSWER:", ans.strip().replace("\n", " | ")[:400])
