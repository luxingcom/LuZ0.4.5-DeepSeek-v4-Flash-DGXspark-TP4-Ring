import json, urllib.request, time, base64, io
from PIL import Image

URL = "http://127.0.0.1:8001/v1/chat/completions"
HEADERS = {"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"}
MODEL = "deepseek-v4-flash-vision-exp"

def png_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

imgs = [Image.new("RGB", (200,200), c) for c in [(255,0,0),(0,0,255),(255,255,0),(128,0,128)]]
content = [{"type":"text","text":"下面有四张图片，按顺序排列。请问第四张图片是什么颜色？请直接回答。"}]
for im in imgs:
    content.append({"type":"image_url","image_url":{"url":png_b64(im)}})

body = {"model": MODEL, "messages":[{"role":"user","content":content}], "max_tokens":200, "temperature":0}
req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HEADERS)
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    print(json.dumps(d, ensure_ascii=False)[:2000])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:1000])
