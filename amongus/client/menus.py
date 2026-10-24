"""Main menu, LAN browser, connecting screen, help and message screens."""
import math
import threading
import time

import pygame as pg

from .. import config as C
from ..discovery import discover
from .app import H, W, Scene, save_prefs
from .net import ConnectError, NetClient
from .ui import (CYAN, GREY, PANEL, RED, WHITE, YELLOW, Button, Starfield, TextInput, draw_text, panel,
                 wrap)


class MenuBase(Scene):
    stars = None

    def __init__(self, app):
        super().__init__(app)
        if MenuBase.stars is None:
            MenuBase.stars = Starfield(W, H)
        self.widgets = []
        self.t = 0.0

    def handle(self, e):
        for w in self.widgets:
            if w.handle(e):
                return True
        return False

    def update(self, dt):
        self.t += dt
        self.app.start_preload()
        self.app.preload_tick()
        MenuBase.stars.update(dt)
        for w in self.widgets:
            w.update(dt)

    def draw_bg(self, surf):
        MenuBase.stars.draw(surf)
        # a couple of crewmates drifting through space
        for i, col in enumerate(("Cyan", "Lime", "Pink")):
            x = (self.t * (30 + i * 12) + i * 500) % (W + 300) - 150
            y = 160 + i * 190 + math.sin(self.t * 0.8 + i) * 30
            img = pg.transform.rotate(self.assets.crew(col).big(70), (self.t * (40 + i * 25)) % 360)
            img.set_alpha(150)
            surf.blit(img, img.get_rect(center=(x, y)))

    def draw_widgets(self, surf):
        for w in self.widgets:
            w.draw(surf, self.assets)


class MainMenu(MenuBase):
    def __init__(self, app):
        super().__init__(app)
        prefs = app.prefs
        self.name = TextInput((W // 2 - 170, 250, 340, 50), prefs.get("name", ""), "Enter your name",
                              C.MAX_NAME_LEN, size=28, focused=not prefs.get("name"))
        bx = W // 2 - 170
        self.widgets = [
            self.name,
            Button((bx, 320, 340, 58), "HOST GAME", self.host, size=30, colour=(40, 120, 60)),
            Button((bx, 388, 340, 58), "JOIN GAME", self.join, size=30, colour=(40, 80, 150)),
            Button((bx, 456, 340, 50), "PRACTICE WITH BOTS", self.practice, size=24),
            Button((bx, 516, 165, 46), "HOW TO PLAY", self.help, size=18),
            Button((bx + 175, 516, 165, 46), "CLASSIC MODE", self.app.launch_classic, size=18),
            Button((bx, 572, 340, 46), "QUIT", self.quit, size=22, colour=(120, 40, 40), sound="back"),
        ]
        self.error = ""
        if not app.assets.audio:
            self.error = "No audio device found - playing without sound."
        app.assets.music("Background/main_menu_music.mp3", 0.35)

    def _name_ok(self):
        name = self.name.text.strip()
        if not name:
            self.error = "Type a name first."
            self.name.focused = True
            return None
        self.app.prefs["name"] = name
        save_prefs(self.app.prefs)
        return name

    def host(self, practice=False):
        name = self._name_ok()
        if not name:
            return
        try:
            self.app.start_server(name=f"{name}'s game")
        except OSError as e:
            self.error = (f"Can't host on port {C.TCP_PORT} ({e.strerror or e}). "
                          "Is another game or server.py already running on this PC?")
            return
        self.app.set_scene(ConnectingScene(self.app, "127.0.0.1", C.TCP_PORT, practice_bots=7 if practice else 0))

    def practice(self):
        self.host(practice=True)

    def join(self):
        if self._name_ok():
            self.app.set_scene(JoinScene(self.app))

    def help(self):
        self.app.set_scene(HelpScene(self.app))

    def quit(self):
        self.app.running = False

    def handle(self, e):
        if super().handle(e):
            return True
        if e.type == pg.KEYDOWN and e.key in (pg.K_RETURN, pg.K_KP_ENTER) and self.name.text.strip():
            self.host()
            return True
        return False

    def draw(self, surf):
        self.draw_bg(surf)
        title = self.assets.image("menu/title.png")
        surf.blit(title, title.get_rect(midtop=(W // 2, 40)))
        draw_text(surf, self.assets, "LAN EDITION", 26, (W // 2, 175), CYAN, anchor="midtop")
        draw_text(surf, self.assets, "Your name", 20, (W // 2 - 170, 222), GREY)
        self.draw_widgets(surf)
        if self.error:
            draw_text(surf, self.assets, self.error, 18, (W // 2, 640), RED, anchor="midtop")
        draw_text(surf, self.assets, f"v{C.GAME_VERSION}  -  up to {C.MAX_PLAYERS} players on your local network",
                  16, (W // 2, H - 14), GREY, anchor="midbottom")


class JoinScene(MenuBase):
    def __init__(self, app):
        super().__init__(app)
        self.games = {}
        self.searching = True
        self.ip = TextInput((W // 2 - 300, 560, 380, 50), app.prefs.get("last_ip", ""), "Host IP, e.g. 192.168.1.20",
                            40, on_submit=lambda t: self.connect_manual(), size=24,
                            allowed="0123456789.:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-")
        self.widgets = [
            self.ip,
            Button((W // 2 + 95, 560, 205, 50), "JOIN IP", self.connect_manual, size=24, colour=(40, 80, 150)),
            Button((40, H - 80, 160, 50), "BACK", self.back, size=22, sound="back"),
        ]
        self.rows = []
        self.stop = threading.Event()
        self.lock = threading.Lock()
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        while not self.stop.is_set():
            try:
                found = discover(timeout=1.0)
            except OSError:
                found = {}
            with self.lock:
                self.games = found
                self.searching = False
            self.stop.wait(1.0)

    def leave(self):
        self.stop.set()

    def back(self):
        self.app.set_scene(MainMenu(self.app))

    def connect_manual(self):
        text = self.ip.text.strip()
        if not text:
            self.ip.focused = True
            return
        host, port = text, C.TCP_PORT
        if text.count(":") == 1:
            host, p = text.split(":")
            port = int(p) if p.isdigit() else C.TCP_PORT
        self.app.prefs["last_ip"] = text
        save_prefs(self.app.prefs)
        self.app.set_scene(ConnectingScene(self.app, host, port))

    def handle(self, e):
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
            for rect, ip, info in self.rows:
                if rect.collidepoint(e.pos):
                    self.assets.play("click", 0.6)
                    self.app.set_scene(ConnectingScene(self.app, ip, info.get("port", C.TCP_PORT)))
                    return True
        if e.type == pg.KEYDOWN and e.key == pg.K_ESCAPE and not self.ip.focused:
            self.back()
            return True
        return super().handle(e)

    def draw(self, surf):
        self.draw_bg(surf)
        draw_text(surf, self.assets, "JOIN A GAME", 44, (W // 2, 30), WHITE, anchor="midtop")
        box = pg.Rect(W // 2 - 400, 110, 800, 400)
        panel(surf, box, PANEL, alpha=230)
        draw_text(surf, self.assets, "Games on your network", 24, (box.x + 20, box.y + 14), YELLOW)
        with self.lock:
            games = dict(self.games)
            searching = self.searching
        self.rows = []
        y = box.y + 60
        mouse = pg.mouse.get_pos()
        for ip, info in sorted(games.items()):
            r = pg.Rect(box.x + 20, y, box.w - 40, 56)
            hover = r.collidepoint(mouse)
            panel(surf, r, (70, 90, 130) if hover else (50, 56, 80), radius=10, width=2)
            draw_text(surf, self.assets, str(info.get("name", "Game"))[:28], 24, (r.x + 16, r.centery), WHITE,
                      anchor="midleft")
            status = "In lobby" if info.get("phase") == "lobby" else "Game in progress"
            ok_ver = info.get("protocol") == C.PROTOCOL_VERSION
            draw_text(surf, self.assets, f"{info.get('players', 0)}/{info.get('max', C.MAX_PLAYERS)}  {status}"
                      + ("" if ok_ver else "  (different version!)"), 18, (r.right - 220, r.centery),
                      (200, 255, 200) if ok_ver else RED, anchor="midleft")
            draw_text(surf, self.assets, ip, 16, (r.x + 420, r.centery), GREY, anchor="midleft")
            self.rows.append((r, ip, info))
            y += 66
            if y > box.bottom - 60:
                break
        if not games:
            msg = "Searching..." if searching else "No games found yet. Searching..."
            dots = "." * (int(self.t * 2) % 4)
            draw_text(surf, self.assets, msg.rstrip(".") + dots, 24, (box.centerx, box.y + 150), GREY,
                      anchor="center")
            for i, ln in enumerate(["If the host's game doesn't appear, type their IP below.",
                                    "The host sees their IP in the lobby.",
                                    "Both PCs must be on the same Wi-Fi/LAN and the host must allow",
                                    "Python through Windows Firewall (Private networks)."]):
                draw_text(surf, self.assets, ln, 18, (box.centerx, box.y + 210 + i * 30), (190, 190, 200),
                          anchor="center")
        draw_text(surf, self.assets, "Or join by IP address:", 20, (W // 2 - 300, 530), WHITE)
        self.draw_widgets(surf)


class ConnectingScene(MenuBase):
    def __init__(self, app, host, port, practice_bots=0):
        super().__init__(app)
        self.host, self.port = host, port
        self.practice_bots = practice_bots
        self.error = None
        self.net = NetClient()
        self.started = time.monotonic()
        self.widgets = [Button((W // 2 - 100, 520, 200, 52), "BACK", self.back, size=24, sound="back")]
        self.done = False
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        try:
            self.net.connect(self.host, self.port, self.app.prefs.get("name", "Player"),
                             self.app.prefs.get("colour"))
        except ConnectError as e:
            self.error = str(e)
            return
        self.done = True

    def back(self):
        self.net.close()
        self.app.disconnect()
        self.app.set_scene(JoinScene(self.app) if self.host != "127.0.0.1" else MainMenu(self.app))

    def update(self, dt):
        super().update(dt)
        if self.error or not self.done:
            if not self.error and time.monotonic() - self.started > 8:
                self.error = "Timed out connecting."
            return
        # consume one message at a time: everything after "welcome" must stay queued for the lobby
        while True:
            msgs = self.net.poll(limit=1)
            if not msgs:
                break
            msg = msgs[0]
            if msg["t"] == "welcome":
                from .lobby import LobbyScene
                self.app.net = self.net
                self.app.my_id = msg["id"]
                self.app.prefs["colour"] = msg["colour"]
                self.app.set_scene(LobbyScene(self.app, msg))
                for _ in range(self.practice_bots):
                    self.app.add_bot(self.host, self.port)
                return
            if msg["t"] in ("error", "_disconnected"):
                self.error = msg.get("msg") or msg.get("reason")
                self.net.close()
                return
        if time.monotonic() - self.started > 8:
            self.error = "The host didn't answer. Is it really an Among Us LAN game?"
            self.net.close()

    def draw(self, surf):
        self.draw_bg(surf)
        box = pg.Rect(W // 2 - 380, 200, 760, 290)
        panel(surf, box, PANEL, alpha=235)
        if self.error:
            draw_text(surf, self.assets, "Couldn't join", 36, (box.centerx, box.y + 30), RED, anchor="midtop")
            for i, ln in enumerate(wrap(self.assets, self.error, 20, box.w - 60)[:6]):
                draw_text(surf, self.assets, ln, 20, (box.centerx, box.y + 100 + i * 30), WHITE, anchor="midtop")
        else:
            dots = "." * (int(self.t * 3) % 4)
            draw_text(surf, self.assets, f"Connecting to {self.host}{dots}", 32, box.center, WHITE, anchor="center")
            img = pg.transform.rotate(self.assets.crew("Red").big(80), self.t * 120)
            surf.blit(img, img.get_rect(center=(box.centerx, box.bottom - 60)))
        self.draw_widgets(surf)


class MessageScene(MenuBase):
    def __init__(self, app, title, text):
        super().__init__(app)
        self.title, self.text = title, text
        self.widgets = [Button((W // 2 - 100, 470, 200, 52), "OK", self.ok, size=24, hotkey=(pg.K_RETURN, pg.K_ESCAPE))]

    def ok(self):
        self.app.set_scene(MainMenu(self.app))

    def draw(self, surf):
        self.draw_bg(surf)
        box = pg.Rect(W // 2 - 380, 220, 760, 220)
        panel(surf, box, PANEL, alpha=235)
        draw_text(surf, self.assets, self.title, 36, (box.centerx, box.y + 25), RED, anchor="midtop")
        for i, ln in enumerate(wrap(self.assets, self.text, 22, box.w - 60)[:4]):
            draw_text(surf, self.assets, ln, 22, (box.centerx, box.y + 95 + i * 32), WHITE, anchor="midtop")
        self.draw_widgets(surf)


HELP = [
    ("GOAL", [
        "Crewmates: finish all tasks, or find and vote out every Impostor.",
        "Impostors: kill crewmates until you equal them, or let Reactor/O2 sabotage run out.",
    ]),
    ("CONTROLS", [
        "WASD / Arrow keys - move          E or Space - use / do task / fix sabotage",
        "Q - kill (Impostor)       R - report a body       V - vent (Impostor)",
        "Tab - map (Impostors: sabotage from the map)        Esc - close a window",
        "In a vent: A/D or Left/Right to switch vent, E or V to climb out",
        "In meetings: click a player to vote, or Skip Vote. Type in the chat box to talk.",
    ]),
    ("HOW TO PLAY ON LAN", [
        "One player clicks HOST GAME. Everyone else on the same network clicks JOIN GAME",
        "and picks the game from the list (or types the IP shown in the host's lobby).",
        "The host presses START when everyone is in. Roles and tasks are assigned automatically.",
        "Windows may ask the host to allow Python through the firewall: tick Private networks.",
    ]),
    ("TIPS", [
        "Dead players become ghosts: they can still do tasks and chat with other ghosts.",
        "Reactor needs two people holding both hand scanners at the same time!",
        "O2 needs the code entered in both O2 and Admin.",
    ]),
]


class HelpScene(MenuBase):
    def __init__(self, app):
        super().__init__(app)
        self.widgets = [Button((W // 2 - 100, H - 70, 200, 50), "BACK", self.back, size=22, sound="back",
                               hotkey=pg.K_ESCAPE)]

    def back(self):
        self.app.set_scene(MainMenu(self.app))

    def draw(self, surf):
        self.draw_bg(surf)
        box = pg.Rect(60, 30, W - 120, H - 115)
        panel(surf, box, PANEL, alpha=235)
        y = box.y + 18
        for title, lines in HELP:
            draw_text(surf, self.assets, title, 26, (box.x + 30, y), YELLOW)
            y += 38
            for ln in lines:
                draw_text(surf, self.assets, ln, 18, (box.x + 40, y), WHITE, outline=None)
                y += 27
            y += 10
        self.draw_widgets(surf)
