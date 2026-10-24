"""Line-of-sight vision: walls block what living players can see.

The visibility polygon is ray-cast against wall edges near the viewer (vectorised
with numpy). Without numpy the game falls back to plain radius vision.
"""
import math
import xml.etree.ElementTree as ET

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

from ..world import TMX_PATH

VISION_BLOCKERS = {"walls", "wall"}


def load_vision_walls(path=TMX_PATH):
    rects = []
    for og in ET.parse(path).getroot().iter("objectgroup"):
        for o in og.iter("object"):
            if o.get("name") in VISION_BLOCKERS:
                w, h = float(o.get("width", 0)), float(o.get("height", 0))
                if w > 0 and h > 0:
                    rects.append((float(o.get("x")), float(o.get("y")), w, h))
    return rects


class Vision:
    CELL = 256

    def __init__(self, rects=None):
        self.rects = rects if rects is not None else load_vision_walls()
        self.grid = {}
        for i, (x, y, w, h) in enumerate(self.rects):
            for cx in range(int(x // self.CELL), int((x + w) // self.CELL) + 1):
                for cy in range(int(y // self.CELL), int((y + h) // self.CELL) + 1):
                    self.grid.setdefault((cx, cy), []).append(i)
        self.enabled = np is not None
        self._cache_key = None
        self._cache_poly = None

    def nearby(self, x, y, r):
        idx = set()
        for cx in range(int((x - r) // self.CELL), int((x + r) // self.CELL) + 1):
            for cy in range(int((y - r) // self.CELL), int((y + r) // self.CELL) + 1):
                idx.update(self.grid.get((cx, cy), ()))
        return [self.rects[i] for i in idx]

    @staticmethod
    def _inside(rect, x, y):
        rx, ry, rw, rh = rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def polygon(self, ex, ey, radius, n_uniform=96):
        """World-space visibility polygon around eye (ex, ey), or None if unavailable."""
        if not self.enabled:
            return None
        key = (round(ex), round(ey), round(radius))
        if key == self._cache_key:
            return self._cache_poly
        reach = radius * 1.25
        rects = [r for r in self.nearby(ex, ey, reach) if not self._inside(r, ex, ey)]
        segs = []
        for rx, ry, rw, rh in rects:
            segs += [(rx, ry, rw, 0), (rx + rw, ry, 0, rh), (rx, ry + rh, rw, 0), (rx, ry, 0, rh)]
        angles = list(np.linspace(-math.pi, math.pi, n_uniform, endpoint=False))
        for rx, ry, rw, rh in rects:
            for px, py in ((rx, ry), (rx + rw, ry), (rx, ry + rh), (rx + rw, ry + rh)):
                if (px - ex) ** 2 + (py - ey) ** 2 <= reach * reach:
                    a = math.atan2(py - ey, px - ex)
                    angles += [a - 1e-4, a, a + 1e-4]
        ang = np.sort(np.array(angles))
        dx, dy = np.cos(ang), np.sin(ang)
        t = np.full(ang.shape, reach)
        if segs:
            s = np.array(segs, dtype=float)
            spx, spy, sdx, sdy = s[:, 0], s[:, 1], s[:, 2], s[:, 3]
            # ray: E + t*d ; segment: S + u*sd ;  solve with 2D cross products
            denom = dx[:, None] * sdy[None, :] - dy[:, None] * sdx[None, :]
            qx, qy = spx[None, :] - ex, spy[None, :] - ey
            with np.errstate(divide="ignore", invalid="ignore"):
                tt = (qx * sdy[None, :] - qy * sdx[None, :]) / denom
                uu = (qx * dy[:, None] - qy * dx[:, None]) / denom
            ok = (np.abs(denom) > 1e-9) & (tt > 0) & (uu >= 0) & (uu <= 1)
            tt = np.where(ok, tt, np.inf)
            t = np.minimum(t, tt.min(axis=1))
        pts = np.stack([ex + dx * t, ey + dy * t], axis=1)
        poly = pts.tolist()
        self._cache_key, self._cache_poly = key, poly
        return poly

    def line_of_sight(self, ax, ay, bx, by):
        """True if no vision-blocking wall crosses the segment a-b."""
        minx, maxx = min(ax, bx), max(ax, bx)
        miny, maxy = min(ay, by), max(ay, by)
        r = max(maxx - minx, maxy - miny)
        for rx, ry, rw, rh in self.nearby((ax + bx) / 2, (ay + by) / 2, r / 2 + 1):
            if rx > maxx or rx + rw < minx or ry > maxy or ry + rh < miny:
                continue
            if self._inside((rx, ry, rw, rh), ax, ay):
                continue  # standing inside a wall band (thin walls near doors): don't blind the viewer
            if _segment_hits_rect(ax, ay, bx, by, rx, ry, rw, rh):
                return False
        return True


def _segment_hits_rect(ax, ay, bx, by, rx, ry, rw, rh):
    """Liang-Barsky clip test."""
    dx, dy = bx - ax, by - ay
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - rx), (dx, rx + rw - ax), (-dy, ay - ry), (dy, ry + rh - ay)):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return t0 <= t1
