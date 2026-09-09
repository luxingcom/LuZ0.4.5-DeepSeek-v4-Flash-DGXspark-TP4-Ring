#!/usr/bin/env python3
# 单流视觉吞吐: PIL 生成图 + 长描述请求, 测 decode tok/s
import json, urllib.request, time, base64, io
from PIL import Image, ImageDraw

img = Image.new("RGB", (640, 400), "white")
dr = ImageDraw.Draw(img)
for i, c in enumerate([(255,0,0),(0,0,255),(0,128,0),(255,165,0),(128,0,128),(0,255,255)]):
    dr.rectangle([20+i*100, 100, 110+i*100, 300], fill=c)
    dr.text((30+i*100, 50), "S%d" % (i+1), fill="black")
buf = io.BytesIO(); img.save(buf, format="PNG")
b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

body = {"model": "deepseek-v4-flash-vision-exp",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "详细描述这张图中的六个色块：从左到右每个色块的颜色名称、大致位置关系，并编写一段关于色彩搭配的设计评述，约600字。"}]},
            {"type": "image_url", "image_url": {"url": b64}}]},
        "max_tokens": 1024, "temperature": 0.7}
req = urllib.request.Request("http://127.0.0.1:8001/v1/chat/completions",
                             data=json.dumps(body).encode(),
                             headers={"Authorization": "Bearer <BEARER>", "Content-Type": "application/json"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=900) as r:
    d = json.loads(r.read())
dt = time.time() - t0
ct = d["usage"]["completion_tokens"]; pt = d["usage"]["prompt_tokens"]
print("VISION_TPS: completion_tokens=%d wall=%.1fs decode=%.1f tok/s prompt_tokens=%d" % (ct, dt, ct/dt, pt))
print("VISION_DONE")
