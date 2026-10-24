"""Generate per-colour crewmate sprite sheets from the Blue source frames.

Dev-only tool (needs numpy). The game itself only reads the generated PNGs, so
players don't need numpy installed.

    python tools/gen_colours.py

Output: Assets/Images/Player/Sheets/<Colour>.png, layout described in
amongus/client/assets.py (SHEET_* constants).
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import numpy as np
import pygame as pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from amongus.config import COLOURS  # noqa: E402

SRC = os.path.join(ROOT, "Assets", "Images", "Player")
OUT = os.path.join(SRC, "Sheets")
CELL_W, CELL_H = 76, 97
# (folder, frame count) in sheet row order: down, up, left, right
ROWS = [("blue_down_walk", 18), ("blue_up_walk", 17), ("blue_left_walk", 17), ("blue_right_walk", 17)]


def rgb_to_hsv(rgb):
    rgb = rgb.astype(np.float32) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = ((b - r)[gm] / d[gm]) + 2
    h[bm] = ((r - g)[bm] / d[bm]) + 4
    h = h * 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def recolour(surface, main, shadow):
    """Swap the blue body (main V~0.8, shadow V~0.6, outline V<0.3) for main/shadow colours."""
    out = surface.copy()
    px = pg.surfarray.pixels3d(out)
    alpha = pg.surfarray.pixels_alpha(out)
    h, s, v = rgb_to_hsv(px)
    mask = (alpha > 0) & (h >= 212) & (h <= 252) & (s >= 0.45)
    main = np.array(main, np.float32)
    shadow = np.array(shadow, np.float32)
    t = np.clip((v - 0.6) / 0.2, 0.0, 1.0)[..., None]
    col = shadow * (1 - t) + main * t
    bright = np.clip(v / 0.8, 0.0, 1.25)[..., None]
    dark = np.clip(v / 0.6, 0.0, 1.0)[..., None]
    col = np.where(v[..., None] > 0.8, main * bright, col)
    col = np.where(v[..., None] < 0.6, shadow * dark, col)
    col = np.clip(col, 0, 255).astype(np.uint8)
    px[mask] = col[mask]
    del px, alpha
    return out


def main():
    pg.init()
    pg.display.set_mode((1, 1))
    os.makedirs(OUT, exist_ok=True)
    cols = max(n for _, n in ROWS)
    src_rows = []
    for folder, n in ROWS:
        frames = [pg.image.load(os.path.join(SRC, "Blue", folder, f"step{i}.png")).convert_alpha() for i in range(1, n + 1)]
        src_rows.append(frames)
    extras = [
        pg.image.load(os.path.join(SRC, "Blue", "blue_ghost", "step1_left.png")).convert_alpha(),
        pg.image.load(os.path.join(SRC, "Blue", "blue_ghost", "step1_right.png")).convert_alpha(),
        pg.image.load(os.path.join(SRC, "Dead", "Deadblue.png")).convert_alpha(),
    ]
    for name, (main_c, shadow_c) in COLOURS.items():
        sheet = pg.Surface((cols * CELL_W, (len(ROWS) + 1) * CELL_H), pg.SRCALPHA)
        for r, frames in enumerate(src_rows):
            for c, fr in enumerate(frames):
                sheet.blit(recolour(fr, main_c, shadow_c), (c * CELL_W, r * CELL_H))
        for c, fr in enumerate(extras):
            img = recolour(fr, main_c, shadow_c)
            # bottom-align extras inside their cell
            sheet.blit(img, (c * CELL_W, len(ROWS) * CELL_H + CELL_H - img.get_height()))
        pg.image.save(sheet, os.path.join(OUT, f"{name}.png"))
        print("wrote", name)


if __name__ == "__main__":
    main()
