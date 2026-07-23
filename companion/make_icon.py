"""
Generates logo.png and logo.ico for AdolarRadio using Pillow only (no Cairo).
Run once before building: python make_icon.py
"""
import os

from PIL import Image, ImageDraw

OUT_PNG = os.path.join(os.path.dirname(__file__), "logo.png")
OUT_ICO = os.path.join(os.path.dirname(__file__), "logo.ico")

def draw_icon(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # Background circle
    d.ellipse([0, 0, s-1, s-1], fill=(48, 48, 46, 255))

    # Rocket body (rotated 45° → draw tilted ellipse via polygon)
    # Center of rocket body in upright position, then rotate
    cx, cy = s * 0.5, s * 0.5

    import math
    angle = math.radians(45)

    def rot(x, y, a=angle, ox=cx, oy=cy):
        x -= ox; y -= oy
        rx = x * math.cos(a) - y * math.sin(a)
        ry = x * math.sin(a) + y * math.cos(a)
        return rx + ox, ry + oy

    # Body ellipse as polygon
    body_pts = []
    bw, bh = s * 0.22, s * 0.38
    for i in range(36):
        a = math.radians(i * 10)
        x = cx + bw * math.cos(a)
        y = cy + bh * math.sin(a)
        body_pts.append(rot(x, y))
    d.polygon(body_pts, fill=(127, 119, 221, 255), outline=(60, 52, 137, 255))

    # Nose cone
    nose_pts = [
        rot(cx,        cy - bh * 1.45),
        rot(cx - bw,   cy - bh * 0.6),
        rot(cx + bw,   cy - bh * 0.6),
    ]
    d.polygon(nose_pts, fill=(83, 74, 183, 255), outline=(60, 52, 137, 255))

    # Left fin
    fin_l = [
        rot(cx - bw * 0.8, cy + bh * 0.55),
        rot(cx - bw * 1.8, cy + bh * 1.0),
        rot(cx - bw * 0.8, cy + bh * 1.1),
    ]
    d.polygon(fin_l, fill=(83, 74, 183, 255), outline=(60, 52, 137, 255))

    # Right fin
    fin_r = [
        rot(cx + bw * 0.8, cy + bh * 0.55),
        rot(cx + bw * 1.8, cy + bh * 1.0),
        rot(cx + bw * 0.8, cy + bh * 1.1),
    ]
    d.polygon(fin_r, fill=(83, 74, 183, 255), outline=(60, 52, 137, 255))

    # Flame
    flame_pts = []
    fw, fh = s * 0.12, s * 0.18
    for i in range(36):
        a = math.radians(i * 10)
        x = cx + fw * math.cos(a)
        y = (cy + bh * 0.95) + fh * math.sin(a)
        flame_pts.append(rot(x, y))
    d.polygon(flame_pts, fill=(255, 140, 0, 255))

    # Flame inner
    fw2, fh2 = fw * 0.55, fh * 0.6
    flame_inner = []
    for i in range(36):
        a = math.radians(i * 10)
        x = cx + fw2 * math.cos(a)
        y = (cy + bh * 0.92) + fh2 * math.sin(a)
        flame_inner.append(rot(x, y))
    d.polygon(flame_inner, fill=(255, 214, 0, 255))

    # Window
    wr = s * 0.1
    wx, wy = rot(cx, cy - bh * 0.05)
    d.ellipse([wx-wr, wy-wr, wx+wr, wy+wr], fill=(30, 30, 28, 255), outline=(175, 169, 236, 255))
    d.ellipse([wx-wr*0.7, wy-wr*0.7, wx+wr*0.7, wy+wr*0.7], fill=(127, 119, 221, 255))

    # Music note ♫ in window (simple two-dot representation)
    nr = wr * 0.18
    d.ellipse([wx-nr*2.2-nr, wy+nr*0.5-nr, wx-nr*2.2+nr, wy+nr*0.5+nr], fill=(30, 30, 28, 255))
    d.ellipse([wx+nr*0.5-nr,  wy+nr*0.5-nr, wx+nr*0.5+nr,  wy+nr*0.5+nr], fill=(30, 30, 28, 255))

    return img


def main():
    img = draw_icon(256)
    img.save(OUT_PNG)
    print(f"Saved {OUT_PNG}")
    img.save(OUT_ICO, format="ICO", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
    print(f"Saved {OUT_ICO}")


if __name__ == "__main__":
    main()
