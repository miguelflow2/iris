"""Génère build/icon.png et build/icon.ico : le logo VELA (la voile) sur fond encre.

Variante claire — grand-voile crème, foc terracotta — parce que le fond est sombre :
la variante encre y disparaîtrait. C'est la même règle que dans l'application.

La géométrie n'est pas redessinée ici : ce sont les deux chemins de
`renderer/src/components/Voile.tsx`, dans le même repère (viewBox 0 0 120 158).
La courbe de Bézier est aplatie en polygone, puis tout est rendu à 4x et réduit :
PIL ne lisse pas les bords, le suréchantillonnage s'en charge.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)

# --- la palette du logo, et rien d'autre ---
CREME = (248, 240, 231, 255)      # #F8F0E7 — la grand-voile
ENCRE = (27, 20, 14, 255)         # #1B140E — le fond
TERRACOTTA = (179, 107, 59, 255)  # #B36B3B — le foc

SIZE = 1024
SS = 4  # facteur de suréchantillonnage

# Repère du dessin : viewBox 0 0 120 158.
VB_L, VB_H = 120.0, 158.0
# La voile occupe 68,75 % de la hauteur, centrée — mêmes marges que icone-512.png.
HAUTEUR = 0.6875


def bezier_cubique(p0, p1, p2, p3, pas=240):
    """Aplatit une courbe cubique en une suite de points."""
    pts = []
    for i in range(pas + 1):
        t = i / pas
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def bezier_quadratique(p0, p1, p2, pas=160):
    """Aplatit une courbe quadratique en une suite de points."""
    pts = []
    for i in range(pas + 1):
        t = i / pas
        u = 1 - t
        x = u**2 * p0[0] + 2 * u * t * p1[0] + t**2 * p2[0]
        y = u**2 * p0[1] + 2 * u * t * p1[1] + t**2 * p2[1]
        pts.append((x, y))
    return pts


# M 36.5 46.3 L 36.6 158 L 0 158 Z
FOC = [(36.5, 46.3), (36.6, 158.0), (0.0, 158.0)]

# M 41.4 0 C 93.3 52.6 115 105.2 120 157.8 Q 80.4 149.2 41.4 158 Z
GRAND_VOILE = (
    [(41.4, 0.0)]
    + bezier_cubique((41.4, 0.0), (93.3, 52.6), (115.0, 105.2), (120.0, 157.8))[1:]
    + bezier_quadratique((120.0, 157.8), (80.4, 149.2), (41.4, 158.0))[1:]
)


def dessiner(taille_px: int) -> Image.Image:
    """Rend l'icône à `taille_px`, en passant par un tampon `SS` fois plus grand."""
    grand = taille_px * SS
    img = Image.new("RGBA", (grand, grand), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Le fond : carré à coins arrondis, encre pleine.
    rayon = round(grand * 0.195)
    draw.rounded_rectangle((0, 0, grand - 1, grand - 1), radius=rayon, fill=ENCRE)

    # Placement de la voile : hauteur imposée, largeur suivant le rapport du dessin.
    h = grand * HAUTEUR
    echelle = h / VB_H
    dx = (grand - VB_L * echelle) / 2
    dy = (grand - h) / 2

    def place(chemin):
        return [(dx + x * echelle, dy + y * echelle) for x, y in chemin]

    # Le foc d'abord, la grand-voile ensuite : même ordre que le SVG. Le mât laisse
    # entre les deux un mince trait d'encre, qui fait partie du dessin.
    draw.polygon(place(FOC), fill=TERRACOTTA)
    draw.polygon(place(GRAND_VOILE), fill=CREME)

    return img.resize((taille_px, taille_px), Image.LANCZOS)


icone = dessiner(SIZE)
icone.save(OUT / "icon.png")
dessiner(512).save(OUT / "icon-512.png")
# electron-builder lit l'ico pour l'exécutable et le raccourci Windows.
icone.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icônes générées dans", OUT)
