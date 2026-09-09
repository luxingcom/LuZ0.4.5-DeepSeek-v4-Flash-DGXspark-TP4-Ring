import json, urllib.request, time, base64, io
from PIL import Image, ImageDraw, ImageFont

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}
MODEL = "deepseek-v4-flash-vision-exp"

def png_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

def solid(color, size=200):
    return Image.new("RGB", (size, size), color)

def math_img():
    img = Image.new("RGB", (400, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    d.text((40, 70), "12+34=?", fill="black", font=font)
    return img

def ask(content, max_tokens=400):
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": 0}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HEADERS)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"], time.time() - t0

def text_part(t):
    return {"type": "text", "text": t}

def img_part(b64):
    return {"type": "image_url", "image_url": {"url": b64}}

results = []

def run(name, content, check, note):
    ans, dt = ask(content)
    ok = check(ans)
    results.append((name, ok, dt, ans, note))
    print("==%s== pass=%s time=%.1fs" % (name, ok, dt))
    print("ANSWER:", (ans or "<None>").strip().replace("\n", " | ")[:300])
    print()

# g1 single-image color
run("g1", [text_part("图中主要是什么颜色？请直接回答。"), img_part(png_b64(solid((255,0,0))))],
    lambda a: a and (("红" in a) or ("red" in a.lower())), "expect red")

# g2 four images order (purple 4th)
imgs = [solid((255,0,0)), solid((0,0,255)), solid((255,255,0)), solid((128,0,128))]
content = [text_part("下面有四张图片，按顺序排列。请问第四张图片是什么颜色？请直接回答。")]
for im in imgs:
    content.append(img_part(png_b64(im)))
run("g2", content,
    lambda a: a and (("紫" in a) or ("purple" in a.lower())), "expect purple")

# g3 cross-image span
run("g3", [text_part("这里有两张图片。请回答：第一张图片是什么颜色？请直接回答。"),
           img_part(png_b64(solid((255,0,0)))), img_part(png_b64(solid((0,255,0))))],
    lambda a: a and (("红" in a) or ("red" in a.lower())), "expect red")

# g4 math in image
run("g4", [text_part("图中写了一个算式，请说出算式并计算结果。"), img_part(png_b64(math_img()))],
    lambda a: a and ("46" in a), "expect 46")

print("===GATE3 SUMMARY===")
for name, ok, dt, ans, note in results:
    print(name, "PASS" if ok else "FAIL", "%.1fs" % dt, note)
