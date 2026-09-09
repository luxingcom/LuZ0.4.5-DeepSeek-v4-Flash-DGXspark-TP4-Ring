import json, urllib.request, time, asyncio

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}
MODEL = "deepseek-v4-flash-vision-exp"

async def one(i, n):
    body = {"model": MODEL, "messages": [{"role": "user", "content": "请写一段约320 token 的介绍性文字，主题：第%d号分布式系统的架构设计要点，包括组件、数据流、容错与扩展性。" % (i + n * 100)}],
            "max_tokens": 320, "temperature": 0.7}
    data = json.dumps(body).encode()
    loop = asyncio.get_event_loop()
    def call():
        req = urllib.request.Request(URL, data=data, headers=HEADERS)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read())
        return d, time.time() - t0
    d, dt = await loop.run_in_executor(None, call)
    ct = d["usage"]["completion_tokens"]
    pt = d["usage"]["prompt_tokens"]
    return ct, pt, dt

async def bench(n, label):
    t0 = time.time()
    res = await asyncio.gather(*[one(i, n) for i in range(n)])
    wall = time.time() - t0
    tot_ct = sum(r[0] for r in res)
    tot_pt = sum(r[1] for r in res)
    tps = tot_ct / wall
    print("==%s== conc=%d requests=%d wall=%.1fs total_completion_tokens=%d total_prompt_tokens=%d" % (label, n, n, wall, tot_ct, tot_pt))
    for i, (ct, pt, dt) in enumerate(res):
        print("  req%d: completion_tokens=%d wall=%.1fs" % (i, ct, dt))
    print("  THROUGHPUT: %.1f tok/s (completion tokens / wall time)" % tps)
    return tps

async def main():
    t4 = await bench(4, "G5-conc4")
    t8 = await bench(8, "G5-conc8")
    print("SUMMARY conc4=%.1f tok/s (threshold 85) %s" % (t4, "PASS" if t4 >= 85 else "FAIL"))
    print("SUMMARY conc8=%.1f tok/s (threshold 120) %s" % (t8, "PASS" if t8 >= 120 else "FAIL"))

asyncio.run(main())
