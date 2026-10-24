"""Map data shared by server, client and bots — pure Python, no pygame.

Coordinates are map pixels (the map image is 5792x3168). A player's position is
the point between their feet; the collision hitbox sits just above that point.
"""
import math
import os
import random
import xml.etree.ElementTree as ET
from collections import deque

from .config import ASSETS

MAP_W, MAP_H = 5792, 3168
TMX_PATH = os.path.join(ASSETS, "Maps", "map.tmx")

HITBOX_W, HITBOX_H = 36, 20
SOLID_NAMES = {"walls", "tables", "props", "generator", "medbay_comp", "engines", "reactor",
               "security_room_comp", "admin_btn1", "admin_btn2", "wall"}

ROOMS = [  # (name, x, y, w, h) — first match wins
    ("Cafeteria", 2680, 30, 1320, 1340),
    ("Weapons", 4250, 260, 690, 740),
    ("O2", 3900, 1080, 470, 390),
    ("Navigation", 5250, 1050, 560, 640),
    ("Shields", 4230, 1960, 610, 650),
    ("Communications", 3580, 2350, 620, 590),
    ("Storage", 2800, 1860, 740, 1080),
    ("Admin", 3620, 1530, 650, 540),
    ("Electrical", 2160, 1630, 650, 640),
    ("Lower Engine", 1060, 1880, 620, 660),
    ("Security", 1660, 1060, 340, 610),
    ("Reactor", 560, 950, 600, 1030),
    ("Upper Engine", 1060, 340, 620, 670),
    ("MedBay", 2000, 760, 680, 810),
]

# Stations: things a player interacts with. pos is the interaction point.
STATIONS = {
    # task stations
    "wires_electrical": {"pos": (2256, 1690), "label": "Electrical"},
    "wires_admin": {"pos": (3721, 1571), "label": "Admin"},
    "wires_navigation": {"pos": (5453, 1121), "label": "Navigation"},
    "wires_storage": {"pos": (3190, 1872), "label": "Storage"},
    "wires_weapons": {"pos": (4457, 354), "label": "Weapons"},
    "garbage": {"pos": (3960, 352), "label": "Cafeteria"},
    "wifi": {"pos": (3766, 2511), "label": "Communications"},
    "steering": {"pos": (5600, 1330), "label": "Navigation"},
    "divert": {"pos": (1056, 1233), "label": "Reactor"},
    "align": {"pos": (1151, 868), "label": "Upper Engine"},
    "gas_can": {"pos": (3081, 2476), "label": "Storage"},
    "fuel_lower": {"pos": (1259, 2343), "label": "Lower Engine"},
    "asteroids": {"pos": (4571, 523), "label": "Weapons"},
    "swipe": {"pos": (3838, 1846), "label": "Admin"},
    "simon": {"pos": (909, 1023), "label": "Reactor"},
    "scan": {"pos": (2528, 1433), "label": "MedBay"},
    "download": {"pos": (3098, 416), "label": "Cafeteria"},
    "upload": {"pos": (4086, 1846), "label": "Admin"},
    "shields": {"pos": (4544, 2289), "label": "Shields"},
    # utilities
    "admin_map": {"pos": (3960, 1880), "label": "Admin"},
    "cams": {"pos": (1860, 1130), "label": "Security"},
    "emergency": {"pos": (3320, 716), "label": "Cafeteria"},
    # sabotage fixes
    "fix_lights": {"pos": (2495, 1735), "label": "Electrical"},
    "fix_reactor_a": {"pos": (909, 1023), "label": "Reactor"},
    "fix_reactor_b": {"pos": (870, 1866), "label": "Reactor"},
    "fix_o2_a": {"pos": (4100, 1180), "label": "O2"},
    "fix_o2_b": {"pos": (4180, 1640), "label": "Admin"},
    "fix_comms": {"pos": (3880, 2800), "label": "Communications"},
}

WIRING_PANELS = ["wires_electrical", "wires_admin", "wires_navigation", "wires_storage", "wires_weapons"]

# kind: common (same for every crewmate), long, short. steps: list of (station, minigame)
TASKS = {
    "wiring": {"name": "Fix Wiring", "kind": "common", "steps": None},  # 3 random panels, see make_task_steps
    "swipe": {"name": "Swipe Card", "kind": "common", "steps": [("swipe", "swipe")]},
    "fuel": {"name": "Fuel Engines", "kind": "long", "steps": [("gas_can", "fuel_can"), ("fuel_lower", "fuel_engine")]},
    "asteroids": {"name": "Clear Asteroids", "kind": "long", "steps": [("asteroids", "asteroids")]},
    "data": {"name": "Upload Data", "kind": "long", "steps": [("download", "download"), ("upload", "upload")]},
    "simon": {"name": "Start Reactor", "kind": "long", "steps": [("simon", "simon")]},
    "scan": {"name": "Submit Scan", "kind": "long", "steps": [("scan", "scan")]},
    "garbage": {"name": "Empty Garbage", "kind": "short", "steps": [("garbage", "garbage")]},
    "wifi": {"name": "Reboot Wifi", "kind": "short", "steps": [("wifi", "wifi")]},
    "steering": {"name": "Stabilize Steering", "kind": "short", "steps": [("steering", "steering")]},
    "divert": {"name": "Divert Power", "kind": "short", "steps": [("divert", "divert")]},
    "align": {"name": "Align Engine Output", "kind": "short", "steps": [("align", "align")]},
    "shields": {"name": "Prime Shields", "kind": "short", "steps": [("shields", "shields")]},
}

SABOTAGES = {
    "lights": {"name": "Fix Lights", "critical": False, "panels": ["fix_lights"], "minigame": "lights"},
    "comms": {"name": "Fix Communications", "critical": False, "panels": ["fix_comms"], "minigame": "comms"},
    "reactor": {"name": "Reactor Meltdown", "critical": True, "panels": ["fix_reactor_a", "fix_reactor_b"], "minigame": "reactor"},
    "o2": {"name": "Oxygen Depleted", "critical": True, "panels": ["fix_o2_a", "fix_o2_b"], "minigame": "o2"},
}
SABOTAGE_ICON_ROOM = {"lights": "Electrical", "comms": "Communications", "reactor": "Reactor", "o2": "O2"}

# Camera points for the Security monitor: (x, y, radius)
CAMERAS = [(1900, 820, 420), (1880, 2120, 420), (4880, 1380, 420), (3300, 1700, 380)]


def room_at(x, y):
    for name, rx, ry, rw, rh in ROOMS:
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return name
    return "Hallway"


def room_center(name):
    for n, rx, ry, rw, rh in ROOMS:
        if n == name:
            return rx + rw / 2, ry + rh / 2
    return MAP_W / 2, MAP_H / 2


def make_task_steps(task_id, rng):
    """Concrete [(station, minigame), ...] for a task. Wiring picks 3 panels."""
    t = TASKS[task_id]
    if t["steps"] is not None:
        return list(t["steps"])
    panels = rng.sample(WIRING_PANELS, 3)
    return [(p, "wiring") for p in panels]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _load_tmx(path):
    root = ET.parse(path).getroot()
    walls, vents = [], []
    for og in root.iter("objectgroup"):
        for o in og.iter("object"):
            name = o.get("name")
            x, y = float(o.get("x")), float(o.get("y"))
            w, h = float(o.get("width", 0)), float(o.get("height", 0))
            if name in SOLID_NAMES and w > 0 and h > 0:
                walls.append((x, y, w, h))
            elif name == "vent":
                vents.append((x + w / 2, y + h / 2))
    return walls, vents


class Collider:
    """Axis-aligned wall collision with a spatial hash."""
    CELL = 128

    def __init__(self, rects):
        self.rects = rects
        self.grid = {}
        for i, (x, y, w, h) in enumerate(rects):
            for cx in range(int(x // self.CELL), int((x + w) // self.CELL) + 1):
                for cy in range(int(y // self.CELL), int((y + h) // self.CELL) + 1):
                    self.grid.setdefault((cx, cy), []).append(i)

    def _candidates(self, x, y, w, h):
        seen = set()
        for cx in range(int(x // self.CELL), int((x + w) // self.CELL) + 1):
            for cy in range(int(y // self.CELL), int((y + h) // self.CELL) + 1):
                for i in self.grid.get((cx, cy), ()):
                    if i not in seen:
                        seen.add(i)
                        yield self.rects[i]

    @staticmethod
    def hitbox(px, py):
        return px - HITBOX_W / 2, py - HITBOX_H, HITBOX_W, HITBOX_H

    def blocked(self, px, py):
        x, y, w, h = self.hitbox(px, py)
        if x < 0 or y < 0 or x + w > MAP_W or y + h > MAP_H:
            return True
        for rx, ry, rw, rh in self._candidates(x, y, w, h):
            if x < rx + rw and x + w > rx and y < ry + rh and y + h > ry:
                return True
        return False

    def move(self, px, py, dx, dy):
        """Move with per-axis sliding. Returns new (x, y)."""
        steps = max(1, int(max(abs(dx), abs(dy)) // 12) + 1)  # avoid tunnelling through thin walls
        sx, sy = dx / steps, dy / steps
        for _ in range(steps):
            if sx and not self.blocked(px + sx, py):
                px += sx
            if sy and not self.blocked(px, py + sy):
                py += sy
        return px, py


class World:
    GRID = 32  # pathfinding cell size

    def __init__(self, tmx_path=TMX_PATH):
        walls, vents = _load_tmx(tmx_path)
        self.walls = walls
        self.collider = Collider(walls)
        self.vents = vents
        self.vent_links = self._link_vents()
        self.spawns = self._make_spawns()
        self._walk = None
        self._fields = {}

    # ---- vents -------------------------------------------------------
    def _link_vents(self):
        """Vent network roughly matching The Skeld: groups of nearby vents."""
        groups_by_pos = [
            [(1618, 527), (832, 1230)],                   # Upper Engine <-> Reactor top
            [(962, 1695), (1616, 2475)],                  # Reactor bottom <-> Lower Engine
            [(1923, 1654), (2152, 1327), (2252, 1786)],   # Security <-> MedBay <-> Electrical
            [(3929, 863), (3725, 2016), (4542, 1602)],    # Cafeteria <-> Admin <-> Hallway
            [(4475, 435), (5334, 1213)],                  # Weapons <-> Navigation top
            [(4557, 2535), (5335, 1595)],                 # Shields <-> Navigation bottom
        ]
        links = {i: [] for i in range(len(self.vents))}
        for group in groups_by_pos:
            idx = [min(range(len(self.vents)), key=lambda i: dist(self.vents[i], p)) for p in group]
            for i in idx:
                links[i] = [j for j in idx if j != i]
        # any vent left unlinked connects to its nearest neighbour
        for i, l in links.items():
            if not l:
                j = min((k for k in range(len(self.vents)) if k != i), key=lambda k: dist(self.vents[i], self.vents[k]))
                links[i] = [j]
                links[j] = sorted(set(links[j] + [i]))
        return links

    def vent_exit_pos(self, vent_id):
        """A free floor spot next to a vent (vents themselves may overlap props)."""
        vx, vy = self.vents[vent_id]
        return self.nearest_free(vx, vy + 30)

    # ---- spawns ------------------------------------------------------
    def _make_spawns(self, n=12):
        cx, cy = STATIONS["emergency"]["pos"]
        spots = []
        for i in range(n):
            a = -math.pi / 2 + 2 * math.pi * i / n
            for r in range(220, 520, 10):
                x, y = cx + math.cos(a) * r, cy + 40 + math.sin(a) * r * 0.75
                if not self.collider.blocked(x, y):
                    spots.append((round(x), round(y)))
                    break
            else:
                spots.append(self.nearest_free(cx, cy + 300))
        return spots

    def nearest_free(self, x, y, max_r=400):
        if not self.collider.blocked(x, y):
            return (round(x), round(y))
        for r in range(8, max_r, 8):
            for k in range(16):
                a = 2 * math.pi * k / 16
                px, py = x + math.cos(a) * r, y + math.sin(a) * r
                if not self.collider.blocked(px, py):
                    return (round(px), round(py))
        return (round(x), round(y))

    # ---- pathfinding (bots, validation) --------------------------------
    def walkable_grid(self):
        if self._walk is None:
            g = self.GRID
            cols, rows = MAP_W // g, MAP_H // g
            self._walk = [[not self.collider.blocked(c * g + g / 2, r * g + g / 2) for c in range(cols)] for r in range(rows)]
        return self._walk

    def cell_of(self, x, y):
        return int(y // self.GRID), int(x // self.GRID)

    def cell_center(self, cell):
        r, c = cell
        return c * self.GRID + self.GRID / 2, r * self.GRID + self.GRID / 2

    def nearest_walkable_cell(self, x, y):
        walk = self.walkable_grid()
        r0, c0 = self.cell_of(x, y)
        best, bd = None, 1e18
        for r in range(max(0, r0 - 8), min(len(walk), r0 + 9)):
            for c in range(max(0, c0 - 8), min(len(walk[0]), c0 + 9)):
                if walk[r][c]:
                    d = (r - r0) ** 2 + (c - c0) ** 2
                    if d < bd:
                        best, bd = (r, c), d
        return best

    def flow_field(self, target_xy, radius):
        """BFS distance field (cells) to any walkable cell within `radius` of target. Cached."""
        key = (round(target_xy[0]), round(target_xy[1]), round(radius))
        if key in self._fields:
            return self._fields[key]
        walk = self.walkable_grid()
        rows, cols = len(walk), len(walk[0])
        distf = [[-1] * cols for _ in range(rows)]
        q = deque()
        tx, ty = target_xy
        r0, c0 = self.cell_of(tx, ty)
        span = int(radius // self.GRID) + 2
        for r in range(max(0, r0 - span), min(rows, r0 + span + 1)):
            for c in range(max(0, c0 - span), min(cols, c0 + span + 1)):
                if walk[r][c]:
                    x, y = self.cell_center((r, c))
                    if math.hypot(x - tx, y - ty) <= radius:
                        distf[r][c] = 0
                        q.append((r, c))
        while q:
            r, c = q.popleft()
            d = distf[r][c] + 1
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and walk[nr][nc] and distf[nr][nc] < 0:
                    if dr and dc and not (walk[r][nc] and walk[nr][c]):
                        continue  # no corner cutting
                    distf[nr][nc] = d
                    q.append((nr, nc))
        self._fields[key] = distf
        return distf

    def next_waypoint(self, x, y, field):
        """Centre of the neighbouring cell that is closer to the field's target, or None."""
        cell = self.cell_of(x, y)
        r, c = cell
        rows, cols = len(field), len(field[0])
        if not (0 <= r < rows and 0 <= c < cols) or field[r][c] < 0:
            cell = self.nearest_walkable_cell(x, y)
            if cell is None:
                return None
            r, c = cell
            if field[r][c] < 0:
                return None
        if field[r][c] == 0:
            return None
        best = None
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and 0 <= field[nr][nc] < field[r][c]:
                if best is None or field[nr][nc] < field[best[0]][best[1]]:
                    best = (nr, nc)
        return self.cell_center(best) if best else None

    def random_walkable_point(self, rng=random):
        walk = self.walkable_grid()
        while True:
            r = rng.randrange(len(walk))
            c = rng.randrange(len(walk[0]))
            if walk[r][c]:
                return self.cell_center((r, c))


_WORLD = None


def get_world():
    global _WORLD
    if _WORLD is None:
        _WORLD = World()
    return _WORLD
