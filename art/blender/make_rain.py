"""
make_rain.py - procedural rain-streak overlay for the side render (transparent, vertically tileable).

Plain Python 3 (numpy + Pillow), not Blender:
  python3 art/blender/make_rain.py [--w 3200 --h 1400 --seed 13]

Writes  web/public/renders/ns31-side-rain.webp  (RGBA, same pixel grid as ns31-side-render.webp)
and a preview composite (screen blend) in the scratchpad.  Streaks wrap top<->bottom so the layer can
be animated by scrolling it downward (background-position-y) without a seam.
Suggested CSS: mix-blend-mode: screen; opacity: .8; animate translateY(0 -> 1400px) linearly ~0.6s.
"""
import argparse
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRATCH = os.environ.get(
    "A321_SCRATCH",
    "/private/tmp/claude-501/-Users-justinstoica-calhacks13/629b8d31-5e1a-4eb9-bd4e-f5cad7638d44/scratchpad/blender",
)

ap = argparse.ArgumentParser()
ap.add_argument("--w", type=int, default=3200)
ap.add_argument("--h", type=int, default=1400)
ap.add_argument("--seed", type=int, default=13)
a = ap.parse_args()

SS = 2  # supersampling
W, H = a.w * SS, a.h * SS
rnd = random.Random(a.seed)
angle = math.radians(11.0)  # wind from the left


def layer(n, length, width, alpha, blur=0.0, warm=0.15):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for _ in range(n):
        L = rnd.uniform(*length) * SS
        a0 = rnd.uniform(*alpha)
        wdt = max(1, int(round(rnd.uniform(*width) * SS)))
        ang = angle + rnd.gauss(0, math.radians(1.2))
        x = rnd.uniform(-0.05 * W, 1.05 * W)
        y = rnd.uniform(0, H)
        dx, dy = math.sin(ang) * L, math.cos(ang) * L
        col = (255, 226, 190) if rnd.random() < warm else (214, 228, 255)
        # draw with wrap-around so the layer tiles vertically
        for oy in (-H, 0, H):
            # fade the tail of each streak: draw 4 segments with rising alpha
            for k in range(4):
                t0, t1 = k / 4, (k + 1) / 4
                aa = int(a0 * (0.35 + 0.65 * t1))
                d.line([(x + dx * t0, y + oy + dy * t0), (x + dx * t1, y + oy + dy * t1)], fill=col + (aa,), width=wdt)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur * SS))
    return im


far = layer(3200, (10, 26), (0.7, 1.0), (22, 55), warm=0.1)
mid = layer(1300, (28, 70), (1.0, 1.5), (35, 85), warm=0.15)
near = layer(170, (90, 230), (2.0, 3.4), (40, 95), blur=1.6, warm=0.2)
out = Image.alpha_composite(Image.alpha_composite(far, mid), near)
out = out.resize((a.w, a.h), Image.LANCZOS)

os.makedirs(os.path.join(SCRATCH, "renders"), exist_ok=True)
png = os.path.join(SCRATCH, "renders", "ns31-side-rain.png")
out.save(png)
web = os.path.join(REPO, "web", "public", "renders", "ns31-side-rain.webp")
out.save(web, "WEBP", quality=70, alpha_quality=70, method=6)
print("wrote", web, "%.1f KB" % (os.path.getsize(web) / 1024))

# preview: screen-blend over the side render
base = os.path.join(SCRATCH, "renders", "ns31-side-render.png")
if os.path.exists(base):
    b = np.asarray(Image.open(base).convert("RGB"), dtype=np.float32) / 255
    r = np.asarray(out, dtype=np.float32) / 255
    rgb, al = r[..., :3], r[..., 3:4] * 0.85
    comp = 1 - (1 - b) * (1 - rgb * al)
    Image.fromarray((comp * 255).astype(np.uint8)).resize((1600, 700), Image.LANCZOS).save(
        os.path.join(SCRATCH, "renders", "side_rain_preview.jpg"), quality=90)
    print("preview written")
