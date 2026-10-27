#!/usr/bin/env python3
"""生成一张人工绘制的教学占位图；不是任何真实五金商品。"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "assets" / "input" / "DEMO_only.png"
out.parent.mkdir(parents=True, exist_ok=True)
image = Image.new("RGBA", (900, 1100), (0, 0, 0, 0))
d = ImageDraw.Draw(image)
d.rounded_rectangle((260, 90, 640, 980), radius=50, fill="#B7C6D0", outline="#6B7C88", width=15)
d.rounded_rectangle((325, 200, 575, 860), radius=30, fill="#E3EDF3", outline="#738593", width=10)
for y in (285, 770):
    d.ellipse((390, y, 510, y + 120), fill="#9AAAB6", outline="#4B5B69", width=14)
d.rectangle((432, 390, 468, 660), fill="#728999")
image.save(out)
print(f"演示占位图（非真实商品）：{out}")
