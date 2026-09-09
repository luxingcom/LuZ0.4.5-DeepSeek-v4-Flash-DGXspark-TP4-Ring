#!/usr/bin/env python3
# VL GSM8K 抽样门禁（对齐 w9r2_gsm8k_spot.py 口径: 8-shot CoT, temp=0.6, max_tokens=1024, 顺序）
# 基线口径差异说明: 历史口径走 8003 网关（旧版密钥体系）；VL 现役网关为 8001（现役密钥体系）
import json, re, time, urllib.request, argparse

BASE = "http://127.0.0.1:8001"
MODEL = "deepseek-v4-flash-vision-exp"
API_KEY = "<BEARER>"
DATA = "/home/_PH_USER_/data/gsm8k_test.jsonl"
MAX_TOKENS = 2048
TEMPERATURE = 0.6
NQ = 114
SHOTS = 8

EXAMPLES = [
    ("There are 15 trees in the grove. Grove workers will plant trees in the grove today. After the day", 21),
    ("If there are 3 cars in the parking lot and 2 more cars arrive", 5),
    ("Leah had 32 chocolates and her sister had 42. If they ate 35", 39),
    ("Jason had 20 lollipops. He gave Denny some lollipops. Now Jason has 12 lollipops", 8),
    ("Shawn has five toys. For Christmas, he got two toys each from his mom and dad", 9),
    ("There were nine computers in the server room. Five more computers were installed each day", 68),
    ("Michael had 58 golf balls. On tuesday, he lost 23 golf balls", 35),
    ("Benny bought a new video game for 37 dollars", 15),
]

def build_prompt(q):
    parts = []
    for ex, ans in EXAMPLES:
        parts.append("Q: %s\nA: #### %d" % (ex, ans))
    parts.append("Q: %s\nA:" % q)
    return "\n\n".join(parts)

def extract_content(text):
    if text is None:
        return None
    m = re.search(r"\boxed\{([^}]*)\}", text)
    if m:
        return m.group(1).strip()
    nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?", text.replace(",", ""))
    return nums[-1] if nums else None

def extract_marker(text):
    if text is None:
        return None
    m = re.search(r"####\s*(-?[\d,\.]+)", text)
    if m:
        return m.group(1).replace(",", "")
    return None

def norm(s):
    if s is None:
        return None
    s = str(s).strip().rstrip(".")
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except Exception:
        return s

def main():
    nq = NQ
    lines = [json.loads(l) for l in open(DATA)]
    print("loaded=%d nq=%d base=%s model=%s temp=%s max_tokens=%d" % (len(lines), nq, BASE, MODEL, TEMPERATURE, MAX_TOKENS))
    ok_c = ok_m = err = 0
    t0 = time.time()
    with open("/tmp/vl-acceptance/gsm8k_f2_raw.jsonl", "w") as fraw:
        for i in range(nq):
            item = lines[i]
            q = item["question"]
            gold = item["answer"].split("####")[-1].strip().replace(",", "")
            prompt = build_prompt(q)
            body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE}
            req = urllib.request.Request(BASE + "/v1/chat/completions",
                                         data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + API_KEY,
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    d = json.loads(r.read())
                ch = d["choices"][0]
                content = ch["message"]["content"]
                fr = ch.get("finish_reason")
                ct = d["usage"]["completion_tokens"]
            except Exception as e:
                fr = None; ct = None
                err += 1
                fraw.write(json.dumps({"i": i, "err": str(e)[:200]}) + "\n")
                fraw.flush()
                continue
            pc = norm(extract_content(content))
            meta = {"fr": fr, "ct": ct}
            pm = norm(extract_marker(content))
            c_ok = (pc == norm(gold))
            m_ok = (pm == norm(gold))
            ok_c += c_ok
            ok_m += m_ok
            fraw.write(json.dumps({"i": i, "gold": gold, "pc": pc, "pm": pm, "c_ok": c_ok, "m_ok": m_ok, "fr": fr, "ct": ct}) + "\n")
            fraw.flush()
            if (i + 1) % 100 == 0:
                el = time.time() - t0
                print("progress %d/%d acc_c=%.4f acc_m=%.4f elapsed=%.0fs" % (i + 1, nq, ok_c / (i + 1), ok_m / (i + 1), el), flush=True)
    el = time.time() - t0
    summary = {"nq": nq, "accuracy_content": ok_c / nq, "accuracy_marker": ok_m / nq,
               "correct_content": ok_c, "correct_marker": ok_m, "err": err,
               "elapsed_s": el, "ts": time.strftime("%F %T"),
               "base": BASE, "model": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
    json.dump(summary, open("/tmp/vl-acceptance/gsm8k_f2_summary.json", "w"), indent=1)
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == "__main__":
    main()
