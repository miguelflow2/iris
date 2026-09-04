"""Génère build/icon.png et build/icon.ico : symbole VELA (anneau ouvert, trait unique) sur fond noir."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)
TEAL = (15, 110, 86, 255)
BLACK = (12, 12, 12, 255)

SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
radius = 220
draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=radius, fill=BLACK)

# anneau volontairement ouvert (continuité vision → mémoire → action, jamais fermé)
margin = 200
box = (margin, margin, SIZE - margin, SIZE - margin)
width = 92
draw.arc(box, start=300, end=225, fill=TEAL, width=width)  # 285° d'arc, ouverture en haut à droite
# extrémité "comète" : bout arrondi côté départ, effilé côté fin
import math

cx = cy = SIZE / 2
r = (SIZE - 2 * margin) / 2 - width / 2
for angle, size in ((225, width), (300, width * 0.55)):
    a = math.radians(angle)
    px, py = cx + r * math.cos(a), cy + r * math.sin(a)
    draw.ellipse((px - size / 2, py - size / 2, px + size / 2, py + size / 2), fill=TEAL)

img.save(OUT / "icon.png")
img.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icônes générées dans", OUT)
