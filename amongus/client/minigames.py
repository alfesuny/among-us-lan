"""Task, sabotage-fix and utility panels.

Each minigame is a modal panel. It calls `on_success()` exactly once when solved
(the GameScene then tells the server) and sets `closed` when it should vanish.
Geometry used for hit-testing is exposed as attributes so headless tests can
drive every panel with real mouse events.
"""
import math
import random

import pygame as pg

from ..config import COLOURS
from ..world import CAMERAS, MAP_H, MAP_W, ROOMS
from .ui import BLACK, CYAN, GREEN, GREY, RED, WHITE, YELLOW, draw_text, panel

SW, SH = 1280, 720


def blit_center(surf, img, center):
    surf.blit(img, img.get_rect(center=(round(center[0]), round(center[1]))))


class Minigame:
    size = (600, 480)
    title = ""

    def __init__(self, scene, on_success=None, **ctx):
        self.scene = scene
        self.assets = scene.assets
        self.on_success = on_success
        self.ctx = ctx
        self.rng = random.Random()
        w, h = self.size
        self.rect = pg.Rect((SW - w) // 2, (SH - h) // 2 + 10, w, h)
        self.close_rect = pg.Rect(self.rect.right + 6, self.rect.y - 6, 52, 52)
        self.done = False
        self.closed = False
        self.t = 0.0
        self.finish_at = None
        self.drag = None

    # coordinates relative to the panel
    def P(self, x, y):
        return self.rect.x + x, self.rect.y + y

    def succeed(self, delay=0.7):
        if self.done:
            return
        self.done = True
        self.finish_at = self.t + delay
        self.assets.play("task_done", 0.7)
        if self.on_success:
            self.on_success()

    def close(self):
        self.closed = True
        self.on_close()

    def on_close(self):
        pass

    def handle(self, e):
        if e.type == pg.KEYDOWN and e.key == pg.K_ESCAPE:
            self.close()
            return True
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1 and self.close_rect.collidepoint(e.pos):
            self.close()
            return True
        if self.done:
            return True
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
            self.mouse_down(e.pos)
        elif e.type == pg.MOUSEMOTION:
            self.mouse_move(e.pos, e.buttons[0] if e.buttons else 0)
        elif e.type == pg.MOUSEBUTTONUP and e.button == 1:
            self.mouse_up(e.pos)
        return True

    def mouse_down(self, pos):
        pass

    def mouse_move(self, pos, held):
        pass

    def mouse_up(self, pos):
        pass

    def update(self, dt):
        self.t += dt
        if self.finish_at is not None and self.t >= self.finish_at:
            self.closed = True

    def draw(self, surf):
        dim = pg.Surface((SW, SH), pg.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        surf.blit(dim, (0, 0))
        self.draw_panel(surf)
        close = self.assets.image("UI/close.PNG", (52, 52))
        surf.blit(close, self.close_rect)
        if self.title:
            draw_text(surf, self.assets, self.title, 24, (self.rect.centerx, self.rect.y - 34), WHITE, anchor="midtop")
        if self.done:
            draw_text(surf, self.assets, "TASK COMPLETE!", 44, self.rect.center, GREEN, anchor="center", width=3)

    def draw_panel(self, surf):
        panel(surf, self.rect, (60, 64, 76))


# ---------------------------------------------------------------------------- tasks
WIRE_COLOURS = {"red": (230, 40, 40), "blue": (40, 90, 255), "yellow": (250, 225, 40), "pink": (255, 70, 230)}


class Wiring(Minigame):
    size = (620, 500)
    title = "Fix Wiring"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        names = list(WIRE_COLOURS)
        self.left = names[:]
        self.right = names[:]
        self.rng.shuffle(self.left)
        self.rng.shuffle(self.right)
        self.left_pts = [self.P(70, 100 + i * 100) for i in range(4)]
        self.right_pts = [self.P(550, 100 + i * 100) for i in range(4)]
        self.connected = {}
        self.mouse = (0, 0)

    def mouse_down(self, pos):
        for i, p in enumerate(self.left_pts):
            if i not in self.connected and math.dist(p, pos) < 34:
                self.drag = i
                self.mouse = pos

    def mouse_move(self, pos, held):
        self.mouse = pos

    def mouse_up(self, pos):
        if self.drag is None:
            return
        i = self.drag
        self.drag = None
        for j, p in enumerate(self.right_pts):
            if math.dist(p, pos) < 40 and self.right[j] == self.left[i] and j not in self.connected.values():
                self.connected[i] = j
                self.assets.play("select", 0.5)
                if len(self.connected) == 4:
                    self.succeed()
                return

    def draw_panel(self, surf):
        r = self.rect
        panel(surf, r, (34, 34, 40), border=(120, 120, 130), radius=10, width=8)
        for i, name in enumerate(self.left):
            x, y = self.left_pts[i]
            pg.draw.rect(surf, WIRE_COLOURS[name], (r.x + 8, y - 13, x - r.x - 8, 26))
            pg.draw.circle(surf, (200, 200, 200), (x, y), 14)
            pg.draw.circle(surf, WIRE_COLOURS[name], (x, y), 9)
        for j, name in enumerate(self.right):
            x, y = self.right_pts[j]
            pg.draw.rect(surf, WIRE_COLOURS[name], (x, y - 13, r.right - 8 - x, 26))
            pg.draw.circle(surf, (200, 200, 200), (x, y), 14)
            pg.draw.circle(surf, WIRE_COLOURS[name], (x, y), 9)
            lit = j in self.connected.values()
            pg.draw.circle(surf, GREEN if lit else (60, 20, 20), (r.right - 26, y - 30), 7)
        for i, j in self.connected.items():
            pg.draw.line(surf, WIRE_COLOURS[self.left[i]], self.left_pts[i], self.right_pts[j], 16)
        if self.drag is not None:
            pg.draw.line(surf, WIRE_COLOURS[self.left[self.drag]], self.left_pts[self.drag], self.mouse, 16)


class Garbage(Minigame):
    size = (504, 504)
    title = "Empty Garbage - pull the lever and hold"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.full = self.assets.image("Tasks/Empty Garbage/garbage_base_full.PNG")
        self.empty = self.assets.image("Tasks/Empty Garbage/garbage_base_empty.PNG")
        self.lever = self.assets.image("Tasks/Empty Garbage/liver_up.PNG")
        self.lever_top, self.lever_bottom = 120, 400
        self.lever_y = self.lever_top
        self.drain = 0.0
        self.lever_x = 427

    @property
    def lever_center(self):
        return self.P(self.lever_x, self.lever_y)

    def mouse_down(self, pos):
        if math.dist(pos, self.lever_center) < 60:
            self.drag = pos[1] - self.lever_center[1]

    def mouse_move(self, pos, held):
        if self.drag is not None:
            y = pos[1] - self.drag - self.rect.y
            self.lever_y = max(self.lever_top, min(self.lever_bottom, y))

    def mouse_up(self, pos):
        self.drag = None

    def update(self, dt):
        super().update(dt)
        if self.done:
            return
        if self.drag is None:
            self.lever_y = max(self.lever_top, self.lever_y - 900 * dt)  # spring back
        if self.lever_y >= self.lever_bottom - 10:
            self.drain = min(1.0, self.drain + dt / 1.6)
            if self.drain >= 1.0:
                self.succeed()

    def draw_panel(self, surf):
        r = self.rect
        surf.blit(self.empty, r)
        if self.drain < 1:
            clip = surf.get_clip()
            surf.set_clip(pg.Rect(r.x, r.y, 345, r.h))
            surf.blit(self.full, (r.x, r.y + int(self.drain * 504)), pg.Rect(0, 0, 345, 504))
            surf.set_clip(clip)
        blit_center(surf, self.lever, self.lever_center)


class Wifi(Minigame):
    size = (311, 609)
    title = "Reboot Wifi"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.rect.y = (SH - self.size[1]) // 2 + 30
        self.close_rect = pg.Rect(self.rect.right + 6, self.rect.y - 6, 52, 52)
        self.bg = self.assets.scaled("Tasks/Reboot Wifi/panel_wifi_bg.png", 0.85)
        self.lever = self.assets.scaled("Tasks/Reboot Wifi/panel_wifi-lever.png", 0.85)
        self.wifi_on = self.assets.scaled("Tasks/Reboot Wifi/wifi_on.png", 0.85)
        self.lx = 262
        self.top, self.bottom = 262, 540
        self.ly = self.top
        self.state = "pull"  # pull -> rebooting -> push -> done
        self.reboot_left = 0.0

    @property
    def lever_center(self):
        return self.P(self.lx, self.ly)

    def mouse_down(self, pos):
        if self.state in ("pull", "push") and math.dist(pos, self.lever_center) < 45:
            self.drag = pos[1] - self.lever_center[1]

    def mouse_move(self, pos, held):
        if self.drag is not None:
            self.ly = max(self.top, min(self.bottom, pos[1] - self.drag - self.rect.y))
            if self.state == "pull" and self.ly >= self.bottom - 6:
                self.state = "rebooting"
                self.reboot_left = 6.0
                self.drag = None
                self.assets.play("shock", 0.5)
            elif self.state == "push" and self.ly <= self.top + 6:
                self.state = "done"
                self.drag = None
                self.succeed(1.0)

    def mouse_up(self, pos):
        self.drag = None

    def update(self, dt):
        super().update(dt)
        if self.state == "rebooting":
            self.reboot_left -= dt
            if self.reboot_left <= 0:
                self.state = "push"

    def draw_panel(self, surf):
        r = self.rect
        surf.blit(self.bg, r)
        screen = pg.Rect(self.P(40, 320), (190, 230))
        if self.state == "pull":
            msg = ["WIFI ERROR", "Pull lever", "to reboot"]
        elif self.state == "rebooting":
            msg = ["REBOOTING", f"{max(0, math.ceil(self.reboot_left))}", "please wait"]
        elif self.state == "push":
            msg = ["READY", "Push lever", "back up"]
        else:
            msg = ["ONLINE", "", ""]
            blit_center(surf, self.wifi_on, self.P(135, 255))
        for i, ln in enumerate(msg):
            draw_text(surf, self.assets, ln, 22, (screen.centerx, screen.y + 30 + i * 40), (190, 255, 190),
                      anchor="midtop")
        blit_center(surf, self.lever, self.lever_center)


class Steering(Minigame):
    size = (502, 503)
    title = "Stabilize Steering - drag the target to the centre"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.bg = self.assets.image("Tasks/Stabilize Steering/stabilizer_base.PNG")
        self.target = self.assets.image("Tasks/Stabilize Steering/nav_stabilize_target.png")
        a = self.rng.uniform(0, 2 * math.pi)
        d = self.rng.uniform(100, 160)
        self.center = self.P(251, 252)
        self.pos = [self.center[0] + math.cos(a) * d, self.center[1] + math.sin(a) * d]

    def mouse_down(self, pos):
        if math.dist(pos, self.pos) < 60:
            self.drag = (pos[0] - self.pos[0], pos[1] - self.pos[1])

    def mouse_move(self, pos, held):
        if self.drag is not None:
            x, y = pos[0] - self.drag[0], pos[1] - self.drag[1]
            dx, dy = x - self.center[0], y - self.center[1]
            d = math.hypot(dx, dy)
            if d > 190:
                x, y = self.center[0] + dx / d * 190, self.center[1] + dy / d * 190
            self.pos = [x, y]

    def mouse_up(self, pos):
        self.drag = None
        if math.dist(self.pos, self.center) < 16:
            self.pos = list(self.center)
            self.succeed()

    def draw_panel(self, surf):
        surf.blit(self.bg, self.rect)
        blit_center(surf, self.target, self.pos)


class Divert(Minigame):
    size = (500, 500)
    title = "Divert Power - slide the highlighted switch up"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.bg = self.assets.image("Tasks/Divert Power/electricity_Divert_Base.png")
        self.tracks = [60 + i * 53.9 for i in range(8)]
        self.which = self.rng.randrange(8)
        self.top, self.bottom = 332, 448
        self.y = self.bottom

    @property
    def knob(self):
        return self.P(self.tracks[self.which], self.y)

    def mouse_down(self, pos):
        if math.dist(pos, self.knob) < 30:
            self.drag = pos[1] - self.knob[1]

    def mouse_move(self, pos, held):
        if self.drag is not None:
            self.y = max(self.top, min(self.bottom, pos[1] - self.drag - self.rect.y))
            if self.y <= self.top + 3:
                self.drag = None
                self.succeed()

    def mouse_up(self, pos):
        self.drag = None

    def draw_panel(self, surf):
        surf.blit(self.bg, self.rect)
        for i, x in enumerate(self.tracks):
            y = self.y if i == self.which else (self.top if i < self.which or self.done else self.bottom)
            if i != self.which:
                y = self.bottom
            kr = pg.Rect(0, 0, 36, 18)
            kr.center = self.P(x, y)
            pg.draw.rect(surf, (230, 200, 40) if i == self.which else (120, 120, 120), kr, border_radius=4)
            pg.draw.rect(surf, BLACK, kr, 2, border_radius=4)
        if not self.done:
            x = self.tracks[self.which]
            a = 0.5 + 0.5 * math.sin(self.t * 6)
            pg.draw.circle(surf, (255, 255, int(80 + 170 * a)), self.P(x, 160), 12, 3)


class Align(Minigame):
    size = (500, 500)
    title = "Align Engine Output - line it up with the dashes"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.bg = self.assets.image("Tasks/Align Engine Output/engineAlign_base.png")
        self.lever = self.assets.image("Tasks/Align Engine Output/engine_liver.png")
        self.goal = 235
        self.y = self.rng.choice([self.rng.uniform(70, 175), self.rng.uniform(300, 430)])

    def arc_x(self, y):
        return 405 + 55 * ((y - 240) / 215) ** 2

    @property
    def handle_pos(self):
        return self.P(self.arc_x(self.y), self.y)

    def mouse_down(self, pos):
        if math.dist(pos, self.handle_pos) < 50:
            self.drag = pos[1] - self.handle_pos[1]

    def mouse_move(self, pos, held):
        if self.drag is not None:
            self.y = max(45, min(445, pos[1] - self.drag - self.rect.y))

    def mouse_up(self, pos):
        if self.drag is not None:
            self.drag = None
            if abs(self.y - self.goal) < 8:
                self.y = self.goal
                self.succeed()

    def draw_panel(self, surf):
        surf.blit(self.bg, self.rect)
        out_y = self.goal + (self.y - self.goal) * 0.85
        col = GREEN if abs(self.y - self.goal) < 8 else (240, 240, 120)
        pg.draw.line(surf, col, self.P(40, out_y), self.P(338, out_y), 4)
        lever = pg.transform.rotate(self.lever, (self.y - 240) * -0.12)
        blit_center(surf, lever, self.handle_pos)


class Fuel(Minigame):
    size = (526, 497)

    def __init__(self, scene, engine=False, **kw):
        super().__init__(scene, **kw)
        self.title = "Fuel the engine - hold the button" if engine else "Fill the gas can - hold the button"
        self.bg = self.assets.image("Tasks/Fuel Engines/fuel_engines_base.png")
        self.button_rect = pg.Rect(self.P(405, 375), (120, 120))
        self.level = 0.0
        self.holding = False
        self.channel = None

    def mouse_down(self, pos):
        if self.button_rect.collidepoint(pos):
            self.holding = True
            self.channel = self.assets.play("fill", 0.6, loops=-1)

    def mouse_up(self, pos):
        self._release()

    def _release(self):
        self.holding = False
        if self.channel is not None:
            self.channel.stop()
            self.channel = None

    def on_close(self):
        self._release()

    def update(self, dt):
        super().update(dt)
        if self.holding and not self.done:
            self.level = min(1.0, self.level + dt / 3.0)
            if self.level >= 1.0:
                self._release()
                self.succeed()

    def draw_panel(self, surf):
        r = self.rect
        pg.draw.rect(surf, (25, 25, 25), (r.x + 127, r.y + 98, 66, 305))
        h = int(300 * self.level)
        if h:
            pg.draw.rect(surf, (235, 195, 52), (r.x + 127, r.y + 400 - h, 66, h))
        surf.blit(self.bg, r)
        if self.holding:
            pg.draw.rect(surf, (255, 255, 150), self.button_rect.inflate(-40, -40), 4, border_radius=8)
        draw_text(surf, self.assets, f"{int(self.level * 100)}%", 26, self.P(160, 440), WHITE, anchor="center")


class Asteroids(Minigame):
    size = (640, 480)
    title = "Clear Asteroids - click to shoot them"
    GOAL = 15

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        bg = self.assets.image("Tasks/Clear Asteroids/space3.png")
        self.bg = pg.transform.smoothscale(bg, (int(bg.get_width() * 480 / bg.get_height()), 480))
        self.rocks_img = [self.assets.image(f"Tasks/Clear Asteroids/asteroid{i}.png", (74, 66)) for i in range(1, 5)]
        self.rocks = []  # [x, y, vx, vy, img, angle, spin]
        self.spawn = 0.0
        self.destroyed = 0
        self.shots = []  # (x, y, until)
        self.booms = []

    def update(self, dt):
        super().update(dt)
        if self.done:
            return
        self.spawn -= dt
        if self.spawn <= 0 and len(self.rocks) < 7:
            self.spawn = self.rng.uniform(0.35, 0.8)
            self.rocks.append([self.rect.right + 40, self.rng.uniform(self.rect.y + 40, self.rect.bottom - 40),
                               self.rng.uniform(-220, -130), self.rng.uniform(-40, 40),
                               self.rng.choice(self.rocks_img), 0.0, self.rng.uniform(-90, 90)])
        for r in self.rocks:
            r[0] += r[2] * dt
            r[1] += r[3] * dt
            r[5] += r[6] * dt
        self.rocks = [r for r in self.rocks if r[0] > self.rect.x - 60 and self.rect.y - 60 < r[1] < self.rect.bottom + 60]
        self.shots = [s for s in self.shots if s[2] > self.t]
        self.booms = [b for b in self.booms if b[2] > self.t]

    def mouse_down(self, pos):
        if not self.rect.collidepoint(pos):
            return
        self.assets.play("laser", 0.3)
        self.shots.append((pos[0], pos[1], self.t + 0.08))
        for r in self.rocks:
            if math.dist((r[0], r[1]), pos) < 40:
                self.rocks.remove(r)
                self.booms.append((r[0], r[1], self.t + 0.25))
                self.destroyed += 1
                self.assets.play("explode", 0.3)
                if self.destroyed >= self.GOAL:
                    self.succeed()
                break

    def draw_panel(self, surf):
        clip = surf.get_clip()
        surf.set_clip(self.rect)
        surf.blit(self.bg, self.rect)
        for x, y, *_rest, img, ang, _spin in [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in self.rocks]:
            blit_center(surf, pg.transform.rotate(img, ang), (x, y))
        for x, y, _ in self.booms:
            pg.draw.circle(surf, (255, 200, 80), (int(x), int(y)), 30, 5)
        for x, y, _ in self.shots:
            pg.draw.line(surf, (120, 255, 120), (self.rect.centerx, self.rect.bottom), (x, y), 3)
        surf.set_clip(clip)
        pg.draw.rect(surf, (20, 60, 20), self.rect, 6)
        draw_text(surf, self.assets, f"Destroyed: {self.destroyed}/{self.GOAL}", 22, self.P(16, 12), (120, 255, 120))
        m = pg.mouse.get_pos()
        if self.rect.collidepoint(m):
            pg.draw.circle(surf, (120, 255, 120), m, 16, 2)
            pg.draw.line(surf, (120, 255, 120), (m[0] - 24, m[1]), (m[0] + 24, m[1]), 2)
            pg.draw.line(surf, (120, 255, 120), (m[0], m[1] - 24), (m[0], m[1] + 24), 2)


class Swipe(Minigame):
    size = (500, 500)
    title = "Swipe Card"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        A = "Tasks/Swipe Card/"
        self.bg = self.assets.image(A + "admin_BG.png")
        self.top = self.assets.image(A + "admin_sliderTop.png")
        self.bottom = self.assets.image(A + "admin_sliderBottom.png")
        self.wallet = self.assets.image(A + "admin_Wallet.png")
        self.wallet_front = self.assets.image(A + "admin_walletFront.png")
        self.card = self.assets.image(A + "admin_Card.png")
        self.state = "wallet"
        self.card_x = 0.0
        self.msg = "Please insert card"
        self.start_t = None

    @property
    def card_rect(self):
        if self.state == "wallet":
            return pg.Rect(self.P(70, 300), self.card.get_size())
        return pg.Rect(self.P(self.card_x, 88), self.card.get_size())

    def mouse_down(self, pos):
        if not self.card_rect.collidepoint(pos):
            return
        if self.state == "wallet":
            self.state = "slot"
            self.card_x = 4
            self.msg = "Please swipe card"
            self.assets.play("select", 0.5)
        elif self.state == "slot":
            self.drag = pos[0] - self.card_rect.x
            self.start_t = self.t

    def mouse_move(self, pos, held):
        if self.drag is not None:
            self.card_x = max(4, min(270, pos[0] - self.drag - self.rect.x))
            if self.card_x >= 268:
                took = self.t - self.start_t
                self.drag = None
                if took < 0.45:
                    self.msg = "Too fast. Try again."
                elif took > 1.6:
                    self.msg = "Too slow. Try again."
                else:
                    self.msg = "Accepted. Thank you."
                    self.succeed(1.0)
                    return
                self.assets.play("kill_denied", 0.4)
                self.card_x = 4

    def mouse_up(self, pos):
        if self.drag is not None:
            self.drag = None
            self.msg = "Bad read. Try again."
            self.card_x = 4

    def draw_panel(self, surf):
        r = self.rect
        surf.blit(self.bg, r)
        surf.blit(self.top, r.topleft)
        if self.state != "wallet":
            surf.blit(self.card, self.card_rect)
        surf.blit(self.bottom, self.P(0, 150))
        surf.blit(self.wallet, self.P(11, 330))
        if self.state == "wallet":
            surf.blit(self.card, self.card_rect)
        surf.blit(self.wallet_front, self.P(11, 413))
        ok = self.msg.startswith("Accepted")
        draw_text(surf, self.assets, self.msg, 20, self.P(250, 22), (120, 255, 140) if ok or "swipe" in self.msg
                  or "insert" in self.msg else (255, 120, 120), anchor="midtop", outline=None)


class Simon(Minigame):
    size = (741, 422)
    title = "Start Reactor - repeat the pattern"
    STAGES = 5

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.bg = self.assets.scaled("Tasks/Start Reactor/reactor_base1.PNG", 1.5)
        s = 1.5
        self.cells = [pg.Rect(self.P((50 + (i % 3) * 50) * s, (45 + (i // 3) * 50) * s), (int(48 * s), int(48 * s)))
                      for i in range(9)]
        cx = [305, 372, 438]
        cy = [47, 108, 168]
        self.keys = [self.P(cx[i % 3] * s, cy[i // 3] * s) for i in range(9)]
        self.leds = [self.P(x * s, 228 * s) for x in (57, 89, 122, 155, 188)]
        self.seq = [self.rng.randrange(9) for _ in range(self.STAGES)]
        self.stage = 1
        self.state = "show"
        self.show_t = -0.6
        self.input = []
        self.flash_key = None
        self.flash_until = 0.0
        self.error_until = 0.0

    def update(self, dt):
        super().update(dt)
        if self.state == "show":
            self.show_t += dt
            if self.show_t >= self.stage * 0.6:
                self.state = "input"
                self.input = []
        elif self.state == "next" and self.t >= self.flash_until:
            self.state = "show"
            self.show_t = -0.4

    def lit_cell(self):
        if self.state != "show" or self.show_t < 0:
            return None
        k = int(self.show_t // 0.6)
        if k < self.stage and (self.show_t % 0.6) < 0.42:
            return self.seq[k]
        return None

    def mouse_down(self, pos):
        if self.state != "input":
            return
        for i, c in enumerate(self.keys):
            if math.dist(c, pos) < 40:
                self.flash_key = i
                self.flash_until = self.t + 0.2
                if i == self.seq[len(self.input)]:
                    self.input.append(i)
                    self.assets.play("select", 0.4)
                    if len(self.input) == self.stage:
                        if self.stage == self.STAGES:
                            self.state = "done"
                            self.succeed()
                        else:
                            self.stage += 1
                            self.state = "next"
                            self.flash_until = self.t + 0.5
                else:
                    self.assets.play("kill_denied", 0.5)
                    self.error_until = self.t + 0.6
                    self.stage = 1
                    self.state = "next"
                    self.flash_until = self.t + 0.8
                return

    def draw_panel(self, surf):
        surf.blit(self.bg, self.rect)
        lit = self.lit_cell()
        err = self.t < self.error_until
        for i, c in enumerate(self.cells):
            if err:
                pg.draw.rect(surf, (180, 30, 30), c.inflate(-6, -6))
            elif i == lit:
                pg.draw.rect(surf, (80, 160, 255), c.inflate(-6, -6))
        if self.flash_key is not None and self.t < self.flash_until:
            pg.draw.circle(surf, (120, 200, 255), self.keys[self.flash_key], 40, 5)
        for i, p in enumerate(self.leds):
            done = i < self.stage - 1 or self.done
            pg.draw.circle(surf, GREEN if done else (40, 40, 40), p, 15)
        label = "Watch..." if self.state == "show" else ("Your turn" if self.state == "input" else "")
        draw_text(surf, self.assets, label, 22, (self.rect.x + 190, self.rect.bottom + 8), WHITE, anchor="midtop")


class Scan(Minigame):
    size = (620, 430)
    title = "Submit Scan"
    DURATION = 7.0

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.colour = kw.get("colour", "Red")
        self.name = kw.get("name", "")
        self.progress = 0.0

    def update(self, dt):
        super().update(dt)
        if not self.done:
            self.progress = min(1.0, self.progress + dt / self.DURATION)
            if self.progress >= 1.0:
                self.succeed(1.2)

    def draw_panel(self, surf):
        r = self.rect
        panel(surf, r, (20, 50, 45), border=(140, 200, 190), radius=12, width=6)
        disc = pg.Rect(0, 0, 220, 70)
        disc.center = self.P(170, 340)
        pg.draw.ellipse(surf, (60, 200, 170), disc)
        pg.draw.ellipse(surf, (20, 90, 80), disc, 4)
        img = self.assets.crew(self.colour).big(190)
        surf.blit(img, img.get_rect(midbottom=self.P(170, 345)))
        y = r.y + 60 + (math.sin(self.t * 3) * 0.5 + 0.5) * 270
        pg.draw.line(surf, (120, 255, 220), (r.x + 50, y), (r.x + 290, y), 4)
        info = [f"ID: {self.name[:10].upper()}", "HT: 3' 6\"", "WT: 92lb", f"BT: {self.rng.choice(['O', 'A', 'B'])}-"
                if self.progress > 0.95 else "BT: ...", f"COLOR: {self.colour.upper()}"]
        shown = int(self.progress * (len(info) + 0.99))
        for i, ln in enumerate(info[:shown]):
            draw_text(surf, self.assets, ln, 22, self.P(340, 60 + i * 40), (170, 255, 230), outline=None)
        bar = pg.Rect(self.P(340, 300), (240, 26))
        pg.draw.rect(surf, (10, 30, 25), bar)
        pg.draw.rect(surf, (90, 230, 190), (bar.x, bar.y, int(bar.w * self.progress), bar.h))
        pg.draw.rect(surf, (140, 200, 190), bar, 2)
        draw_text(surf, self.assets, "Scanning..." if not self.done else "Scan complete", 20, self.P(340, 340),
                  WHITE, outline=None)


class Transfer(Minigame):
    size = (620, 380)
    DURATION = 6.0

    def __init__(self, scene, upload=False, **kw):
        super().__init__(scene, **kw)
        self.upload = upload
        self.title = "Upload Data" if upload else "Download Data"
        self.button = pg.Rect(self.P(210, 280), (200, 56))
        self.progress = None

    def mouse_down(self, pos):
        if self.progress is None and self.button.collidepoint(pos):
            self.progress = 0.0
            self.assets.play("select", 0.5)

    def update(self, dt):
        super().update(dt)
        if self.progress is not None and not self.done:
            self.progress = min(1.0, self.progress + dt / self.DURATION)
            if self.progress >= 1.0:
                self.succeed(1.0)

    def draw_panel(self, surf):
        r = self.rect
        panel(surf, r, (210, 214, 224), border=(60, 60, 70), radius=12, width=6)
        for i, x in enumerate((90, 450)):
            f = pg.Rect(self.P(x, 70), (90, 70))
            pg.draw.rect(surf, (240, 200, 90), f, border_radius=6)
            pg.draw.rect(surf, (150, 110, 40), f, 3, border_radius=6)
            label = ("My Tablet" if self.upload else "Station")[:12] if i == 0 else ("Headquarters" if self.upload else "My Tablet")
            draw_text(surf, self.assets, label, 16, (f.centerx, f.bottom + 6), (40, 40, 50), anchor="midtop",
                      outline=None)
        if self.progress is not None:
            for k in range(3):
                frac = ((self.t * 0.8 + k / 3) % 1.0)
                x = self.P(180 + frac * 260, 0)[0]
                y = r.y + 100 - math.sin(frac * math.pi) * 50
                pg.draw.rect(surf, WHITE, (x, y, 22, 28))
                pg.draw.rect(surf, (80, 80, 90), (x, y, 22, 28), 2)
            bar = pg.Rect(self.P(60, 200), (500, 30))
            pg.draw.rect(surf, (60, 60, 70), bar)
            pg.draw.rect(surf, (60, 200, 90), (bar.x, bar.y, int(bar.w * self.progress), bar.h))
            secs = max(0, math.ceil((1 - self.progress) * self.DURATION))
            draw_text(surf, self.assets, f"{int(self.progress * 100)}%   Estimated time: {secs}s", 18,
                      (bar.centerx, bar.bottom + 8), (40, 40, 50), anchor="midtop", outline=None)
        else:
            panel(surf, self.button, (60, 140, 220), radius=10, width=3)
            draw_text(surf, self.assets, "UPLOAD" if self.upload else "DOWNLOAD", 24, self.button.center, WHITE,
                      anchor="center")


class Shields(Minigame):
    size = (520, 520)
    title = "Prime Shields - click the red hexagons"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        c = self.P(260, 260)
        self.cells = [c] + [(c[0] + math.cos(math.radians(60 * i + 30)) * 150,
                             c[1] + math.sin(math.radians(60 * i + 30)) * 150) for i in range(6)]
        n_red = self.rng.randint(3, 5)
        self.red = set(self.rng.sample(range(7), n_red))

    def hexagon(self, c, r=78):
        return [(c[0] + math.cos(math.radians(60 * i)) * r, c[1] + math.sin(math.radians(60 * i)) * r)
                for i in range(6)]

    def mouse_down(self, pos):
        for i, c in enumerate(self.cells):
            if math.dist(c, pos) < 70:
                if i in self.red:
                    self.red.discard(i)
                else:
                    self.red.add(i)
                self.assets.play("select", 0.4)
                if not self.red:
                    self.succeed()
                return

    def draw_panel(self, surf):
        panel(surf, self.rect, (40, 50, 70), border=(120, 140, 170), radius=16, width=6)
        for i, c in enumerate(self.cells):
            col = (220, 60, 60) if i in self.red else (235, 240, 250)
            pts = self.hexagon(c)
            pg.draw.polygon(surf, col, pts)
            pg.draw.polygon(surf, (30, 30, 40), pts, 5)


# ---------------------------------------------------------------------------- sabotage fixes
class Lights(Minigame):
    size = (620, 380)
    title = "Fix Lights - flip every switch up"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.on = [self.rng.random() < 0.5 for _ in range(5)]
        if all(self.on):
            self.on[self.rng.randrange(5)] = False
        self.switches = [pg.Rect(self.P(70 + i * 105, 150), (60, 140)) for i in range(5)]

    def mouse_down(self, pos):
        for i, r in enumerate(self.switches):
            if r.collidepoint(pos):
                self.on[i] = not self.on[i]
                self.assets.play("shock", 0.25)
                if all(self.on):
                    self.succeed()
                return

    def draw_panel(self, surf):
        panel(surf, self.rect, (70, 70, 64), border=(30, 30, 26), radius=10, width=8)
        for i, r in enumerate(self.switches):
            pg.draw.circle(surf, (90, 240, 90) if self.on[i] else (50, 60, 50), (r.centerx, r.y - 50), 18)
            pg.draw.rect(surf, (30, 30, 30), r, border_radius=8)
            knob = pg.Rect(r.x + 8, r.y + 10 if self.on[i] else r.bottom - 60, r.w - 16, 50)
            pg.draw.rect(surf, (220, 220, 210), knob, border_radius=6)


class Comms(Minigame):
    size = (640, 400)
    title = "Fix Communications - turn the dial until the waves match"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.goal = self.rng.uniform(0.2, 0.8)
        self.value = (self.goal + self.rng.choice([-1, 1]) * self.rng.uniform(0.25, 0.4)) % 1.0
        self.dial = self.P(520, 210)
        self.hold = 0.0

    def mouse_down(self, pos):
        if math.dist(pos, self.dial) < 80:
            self.drag = True
            self._set(pos)

    def mouse_move(self, pos, held):
        if self.drag:
            self._set(pos)

    def mouse_up(self, pos):
        self.drag = None

    def _set(self, pos):
        ang = math.atan2(pos[1] - self.dial[1], pos[0] - self.dial[0])
        self.value = (ang / (2 * math.pi)) % 1.0

    def matched(self):
        d = abs(self.value - self.goal)
        return min(d, 1 - d) < 0.035

    def update(self, dt):
        super().update(dt)
        if self.done:
            return
        self.hold = self.hold + dt if self.matched() else 0.0
        if self.hold >= 0.8:
            self.succeed()

    def draw_panel(self, surf):
        panel(surf, self.rect, (30, 40, 34), border=(110, 140, 120), radius=12, width=6)
        scr = pg.Rect(self.P(30, 50), (370, 300))
        pg.draw.rect(surf, (10, 25, 15), scr)
        for wave, col, amp in ((self.goal, (60, 120, 70), 70), (self.value, (120, 255, 140), 60)):
            freq = 1.5 + wave * 8
            pts = [(scr.x + x, scr.centery + math.sin(x / scr.w * freq * 2 * math.pi + self.t * 3) * amp)
                   for x in range(0, scr.w, 4)]
            pg.draw.lines(surf, col, False, pts, 3)
        pg.draw.circle(surf, (90, 90, 90), self.dial, 80)
        pg.draw.circle(surf, (40, 40, 40), self.dial, 80, 6)
        a = self.value * 2 * math.pi
        pg.draw.line(surf, (240, 240, 240), self.dial, (self.dial[0] + math.cos(a) * 70, self.dial[1] + math.sin(a) * 70), 8)
        draw_text(surf, self.assets, "SIGNAL OK" if self.matched() else "NO SIGNAL", 22, self.P(215, 360),
                  (120, 255, 140) if self.matched() else RED, anchor="midtop", outline=None)


class O2Keypad(Minigame):
    size = (545, 544)
    title = "Enter the code to fix O2"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.bg = self.assets.scaled("Tasks/Enter Id Code/enterID_panel.png", 0.9)
        self.code = "".join(str(self.rng.randrange(10)) for _ in range(5))
        s = 0.9
        xs, ys = [233, 300, 367], [75, 135, 195, 255]
        self.keys = {}
        for i, d in enumerate("123456789"):
            self.keys[d] = self.P(xs[i % 3] * s, ys[i // 3] * s)
        self.keys["X"] = self.P(xs[0] * s, ys[3] * s)
        self.keys["0"] = self.P(xs[1] * s, ys[3] * s)
        self.keys["OK"] = self.P(xs[2] * s, ys[3] * s)
        self.typed = ""
        self.error_until = 0.0

    def mouse_down(self, pos):
        for k, c in self.keys.items():
            if math.dist(c, pos) < 26:
                self.press(k)
                return

    def press(self, k):
        self.assets.play("key", 0.5)
        if k == "X":
            self.typed = ""
        elif k == "OK":
            if self.typed == self.code:
                self.succeed()
            else:
                self.typed = ""
                self.error_until = self.t + 0.6
                self.assets.play("kill_denied", 0.5)
        elif len(self.typed) < 5:
            self.typed += k

    def handle(self, e):
        if e.type == pg.KEYDOWN and not self.done:
            if e.unicode and e.unicode.isdigit():
                self.press(e.unicode)
                return True
            if e.key in (pg.K_RETURN, pg.K_KP_ENTER):
                self.press("OK")
                return True
            if e.key == pg.K_BACKSPACE:
                self.typed = self.typed[:-1]
                return True
        return super().handle(e)

    def draw_panel(self, surf):
        surf.blit(self.bg, self.rect)
        disp = pg.Rect(self.P(115 * 0.9, 297 * 0.9), (385 * 0.9, 68 * 0.9))
        col = RED if self.t < self.error_until else (20, 50, 30)
        draw_text(surf, self.assets, " ".join(self.typed) or "", 36, disp.center, col, anchor="center", outline=None)
        note = pg.Rect(self.P(150, 410), (250, 110))
        pg.draw.rect(surf, (250, 240, 140), note)
        pg.draw.rect(surf, (190, 170, 60), note, 3)
        draw_text(surf, self.assets, "today's code:", 18, (note.centerx, note.y + 14), (90, 80, 30), anchor="midtop",
                  outline=None)
        draw_text(surf, self.assets, self.code, 40, (note.centerx, note.y + 44), (40, 30, 10), anchor="midtop",
                  outline=None)


class ReactorScanner(Minigame):
    size = (520, 440)
    title = "Hold to stop the meltdown (needs 2 people!)"

    def __init__(self, scene, panel_id=None, send_hold=None, **kw):
        super().__init__(scene, **kw)
        self.panel_id = panel_id
        self.send_hold = send_hold
        self.pad = pg.Rect(self.P(110, 70), (300, 290))
        self.holding = False

    def mouse_down(self, pos):
        if self.pad.collidepoint(pos) and not self.holding:
            self.holding = True
            if self.send_hold:
                self.send_hold(self.panel_id, True)

    def mouse_up(self, pos):
        self._release()

    def _release(self):
        if self.holding:
            self.holding = False
            if self.send_hold:
                self.send_hold(self.panel_id, False)

    def on_close(self):
        self._release()

    def draw_panel(self, surf):
        panel(surf, self.rect, (120, 124, 130), border=(40, 40, 46), radius=14, width=8)
        pg.draw.rect(surf, (20, 30, 40), self.pad, border_radius=16)
        hand = (90, 200, 255) if self.holding else (60, 90, 110)
        cx, cy = self.pad.centerx, self.pad.centery + 40
        pg.draw.ellipse(surf, hand, (cx - 70, cy - 60, 140, 150), 6)
        for i, (dx, h) in enumerate(((-60, 90), (-25, 125), (12, 130), (48, 110))):
            pg.draw.rect(surf, hand, (cx + dx, cy - 40 - h, 28, h), 6, border_radius=14)
        pg.draw.rect(surf, hand, (cx + 70, cy - 30, 60, 26), 6, border_radius=13)
        if self.holding:
            y = self.pad.y + (self.t * 200) % self.pad.h
            pg.draw.line(surf, (150, 230, 255), (self.pad.x + 10, y), (self.pad.right - 10, y), 3)
        sab = self.scene.sab
        held = len(sab.get("held", [])) if sab else 0
        msg = "Hold your hand here" if not self.holding else (
            "Waiting for second user..." if held < 2 else "Stabilizing!")
        draw_text(surf, self.assets, msg, 22, (self.rect.centerx, self.pad.bottom + 18), WHITE, anchor="midtop")


class EmergencyPanel(Minigame):
    size = (520, 420)
    title = "Emergency Meeting"

    def __init__(self, scene, call=None, **kw):
        super().__init__(scene, **kw)
        self.call = call
        self.button = pg.Rect(self.P(185, 110), (150, 130))

    def mouse_down(self, pos):
        info = self.scene.me_info
        if self.button.collidepoint(pos) and info.get("em", 0) > 0 and info.get("ec", 1) <= 0 and not self.scene.critical():
            if self.call:
                self.call()
            self.close()

    def draw_panel(self, surf):
        panel(surf, self.rect, (40, 44, 60), border=(200, 160, 30), radius=14, width=8)
        icon = self.assets.image("UI/emergency_icon.png", (150, 130))
        info = self.scene.me_info
        ready = info.get("em", 0) > 0 and info.get("ec", 1) <= 0 and not self.scene.critical()
        if not ready:
            icon = icon.copy()
            icon.set_alpha(110)
        surf.blit(icon, self.button)
        left = info.get("em", 0)
        draw_text(surf, self.assets, f"{self.scene.my_name}: {left} emergency meeting(s) left", 20,
                  self.P(260, 270), WHITE, anchor="midtop")
        if self.scene.critical():
            msg = "Can't call a meeting during a crisis!"
        elif left <= 0:
            msg = "You have no emergency meetings left."
        elif info.get("ec", 0) > 0:
            msg = f"Emergency meetings available in {math.ceil(info['ec'])}s"
        else:
            msg = "Click the button to call a meeting"
        draw_text(surf, self.assets, msg, 20, self.P(260, 320), YELLOW if ready else RED, anchor="midtop")


# ---------------------------------------------------------------------------- utilities
class MapView(Minigame):
    """Admin table: player counts per room (no colours, like the real game)."""
    size = (1100, 602)
    title = "Admin - live room occupancy"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.scale = self.size[0] / MAP_W
        self.img = scene.minimap("Maps/mini_map3.png", self.size)

    def to_screen(self, x, y):
        return self.rect.x + x * self.scale, self.rect.y + y * self.scale

    def draw_panel(self, surf):
        panel(surf, self.rect.inflate(16, 16), (20, 30, 40), radius=12, width=4)
        surf.blit(self.img, self.rect)
        counts = {}
        for pid, p in self.scene.positions_for_utilities():
            room = self.scene.room_of(p)
            if room != "Hallway":
                counts[room] = counts.get(room, 0) + 1
        for name, rx, ry, rw, rh in ROOMS:
            n = counts.get(name, 0)
            cx, cy = self.to_screen(rx + rw / 2, ry + rh / 2 + 120)
            for k in range(n):
                pg.draw.circle(surf, (230, 230, 240), (cx - (n - 1) * 9 + k * 18, cy), 8)
                pg.draw.circle(surf, (40, 40, 40), (cx - (n - 1) * 9 + k * 18, cy), 8, 2)

    def handle(self, e):
        if e.type == pg.KEYDOWN and e.key in (pg.K_e, pg.K_SPACE):
            self.close()
            return True
        return super().handle(e)


class Cameras(Minigame):
    size = (1000, 600)
    title = "Security - cameras"

    def __init__(self, scene, **kw):
        super().__init__(scene, **kw)
        self.views = []
        for i, (x, y, rad) in enumerate(CAMERAS):
            r = pg.Rect(self.rect.x + 10 + (i % 2) * 495, self.rect.y + 10 + (i // 2) * 295, 485, 285)
            self.views.append((r, (x, y, rad)))

    def draw_panel(self, surf):
        panel(surf, self.rect, (20, 22, 26), border=(80, 80, 90), radius=10, width=6)
        world = self.scene.map_img
        for r, (x, y, rad) in self.views:
            src = pg.Rect(0, 0, int(rad * 2.3), int(rad * 2.3 * r.h / r.w))
            src.center = (x, y)
            src.clamp_ip(world.get_rect())
            view = pg.transform.scale(world.subsurface(src), r.size)
            sx, sy = r.w / src.w, r.h / src.h
            for pid, p, img in self.scene.visible_sprites_for_cams():
                if src.collidepoint(p[0], p[1]):
                    small = pg.transform.scale(img, (max(1, int(img.get_width() * sx)), max(1, int(img.get_height() * sy))))
                    view.blit(small, small.get_rect(midbottom=((p[0] - src.x) * sx, (p[1] - src.y) * sy + 6)))
            surf.blit(view, r)
            pg.draw.rect(surf, (60, 60, 70), r, 4)
            if int(self.t * 2) % 2 == 0:
                pg.draw.circle(surf, RED, (r.x + 18, r.y + 18), 7)


class MapOverlay:
    """Tab map. Imposters can trigger sabotages from it."""

    def __init__(self, scene, sabotage=False):
        self.scene = scene
        self.assets = scene.assets
        self.sabotage = sabotage
        self.size = (1100, 602)
        self.rect = pg.Rect((SW - self.size[0]) // 2, (SH - self.size[1]) // 2 + 20, *self.size)
        self.scale = self.size[0] / MAP_W
        self.img = scene.minimap("Maps/mini_map.PNG", self.size)
        self.closed = False
        self.t = 0.0
        self.sab_buttons = {}
        if sabotage:
            from ..world import SABOTAGE_ICON_ROOM, room_center
            for kind, room in SABOTAGE_ICON_ROOM.items():
                cx, cy = self.to_screen(*room_center(room))
                self.sab_buttons[kind] = pg.Rect(cx - 32, cy - 32, 64, 64)

    def to_screen(self, x, y):
        return self.rect.x + x * self.scale, self.rect.y + y * self.scale

    def handle(self, e):
        if e.type == pg.KEYDOWN and e.key in (pg.K_ESCAPE, pg.K_TAB, pg.K_m):
            self.closed = True
            return True
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
            for kind, r in self.sab_buttons.items():
                if r.collidepoint(e.pos):
                    self.scene.do_sabotage(kind)
                    self.closed = True
                    return True
            if not self.rect.collidepoint(e.pos):
                self.closed = True
            return True
        return False

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        dim = pg.Surface((SW, SH), pg.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        surf.blit(dim, (0, 0))
        panel(surf, self.rect.inflate(16, 16), (20, 30, 50), radius=12, width=4)
        surf.blit(self.img, self.rect)
        sc = self.scene
        blink = int(self.t * 3) % 2 == 0
        for station in sc.task_marker_stations():
            from ..world import STATIONS
            x, y = self.to_screen(*STATIONS[station]["pos"])
            pg.draw.circle(surf, YELLOW, (x, y), 9)
            draw_text(surf, self.assets, "!", 16, (x, y), BLACK, anchor="center", outline=None)
        if sc.sab:
            from ..world import SABOTAGES, STATIONS
            for panel_id in SABOTAGES[sc.sab["k"]]["panels"]:
                if panel_id in sc.sab.get("done", []):
                    continue
                x, y = self.to_screen(*STATIONS[panel_id]["pos"])
                if blink:
                    pg.draw.circle(surf, RED, (x, y), 14)
                    draw_text(surf, self.assets, "!", 18, (x, y), WHITE, anchor="center", outline=None)
        mx, my = self.to_screen(sc.x, sc.y)
        rgb = COLOURS.get(sc.my_colour, ((255, 255, 255), None))[0]
        pg.draw.circle(surf, rgb, (mx, my), 11)
        pg.draw.circle(surf, WHITE, (mx, my), 11, 3)
        if self.sabotage:
            cd = sc.me_info.get("sc", 0)
            active = sc.sab is not None
            labels = {"lights": "LIGHTS", "comms": "COMMS", "reactor": "REACTOR", "o2": "O2"}
            for kind, r in self.sab_buttons.items():
                ok = cd <= 0 and not active
                pg.draw.circle(surf, (200, 40, 40) if ok else (90, 50, 50), r.center, 32)
                pg.draw.circle(surf, BLACK, r.center, 32, 4)
                draw_text(surf, self.assets, labels[kind], 14, r.center, WHITE, anchor="center")
            if cd > 0:
                draw_text(surf, self.assets, f"Sabotage ready in {math.ceil(cd)}s", 24,
                          (self.rect.centerx, self.rect.bottom - 40), RED, anchor="center")
            elif active:
                draw_text(surf, self.assets, "A sabotage is already active", 24,
                          (self.rect.centerx, self.rect.bottom - 40), RED, anchor="center")
            else:
                draw_text(surf, self.assets, "Click a room to sabotage it", 24,
                          (self.rect.centerx, self.rect.bottom - 40), YELLOW, anchor="center")
        draw_text(surf, self.assets, "Tab / Esc to close", 16, (self.rect.right - 10, self.rect.y + 8), GREY,
                  anchor="topright")


MINIGAMES = {
    "wiring": Wiring, "garbage": Garbage, "wifi": Wifi, "steering": Steering, "divert": Divert, "align": Align,
    "fuel_can": lambda s, **kw: Fuel(s, engine=False, **kw), "fuel_engine": lambda s, **kw: Fuel(s, engine=True, **kw),
    "asteroids": Asteroids, "swipe": Swipe, "simon": Simon, "scan": Scan,
    "download": lambda s, **kw: Transfer(s, upload=False, **kw), "upload": lambda s, **kw: Transfer(s, upload=True, **kw),
    "shields": Shields,
}
FIXES = {"lights": Lights, "comms": Comms, "o2": O2Keypad, "reactor": ReactorScanner}
