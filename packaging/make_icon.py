"""Genera assets/app.ico (lente ámbar sobre fondo grafito) en varios tamaños."""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "app.ico")


def draw(size: int) -> Image.Image:
    s = size * 4  # supermuestreo para bordes suaves
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=(23, 23, 26, 255))
    cx = cy = s / 2
    ring = s * 0.30
    w = max(2, int(s * 0.075))
    d.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=(233, 178, 74, 255), width=w)
    dot = s * 0.11
    d.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=(229, 72, 77, 255))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    draw(256).save(OUT, sizes=[(n, n) for n in sizes])
    print("Icono generado:", OUT)
