"""Application shell: window, main loop, scene switching, hosting, bots."""
import json
import os
import sys
import threading

import pygame as pg

from .. import config as C
from .assets import Assets

W, H = 1280, 720
PREFS_PATH = os.path.join(os.path.expanduser("~"), ".amongus_lan.json")


def load_prefs():
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(prefs):
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f)
    except OSError:
        pass


class Scene:
    def __init__(self, app):
        self.app = app
        self.assets = app.assets

    def handle(self, e):
        pass

    def on_net(self, msg):
        pass

    def update(self, dt):
        pass

    def draw(self, surf):
        pass

    def leave(self):
        pass


class App:
    def __init__(self, headless=False, size=(W, H)):
        self.headless = headless
        try:
            pg.mixer.pre_init(44100, -16, 2, 512)
        except pg.error:
            pass
        pg.init()
        if not pg.mixer.get_init():
            try:
                pg.mixer.init()
            except pg.error:
                pass
        pg.mixer.set_num_channels(32) if pg.mixer.get_init() else None
        flags = 0 if headless else (pg.SCALED | pg.RESIZABLE)
        try:
            self.screen = pg.display.set_mode(size, flags)
        except pg.error:
            self.screen = pg.display.set_mode(size)
        pg.display.set_caption("Among Us — LAN")
        self.assets = Assets()
        try:
            pg.display.set_icon(self.assets.crew("Red").icon(32))
        except pg.error:
            pass
        pg.key.set_repeat(350, 35)
        self.clock = pg.time.Clock()
        self.prefs = load_prefs()
        self.net = None
        self.server = None
        self.server_thread = None
        self.bots = []
        self.scene = None
        self.running = True
        self.my_id = None
        self.fps = 0.0
        self.toasts = []  # (text, until)
        self.time = 0.0
        self.last_lobby = None
        self.map_img = None
        self.minimaps = {}
        self._raw = {}
        self._preload_thread = None

    # ------------------------------------------------------------------ preloading
    MINIMAPS = ("Maps/mini_map.PNG", "Maps/mini_map3.png")
    MINIMAP_SIZE = (1100, 602)

    def start_preload(self):
        """Decode the big images on a thread while the player sits in the lobby."""
        if self._preload_thread is not None:
            return

        def work():
            try:
                self._raw["map"] = pg.image.load(os.path.join(C.ASSETS, "Maps", "map2.png"))
                for rel in self.MINIMAPS:
                    img = pg.image.load(os.path.join(C.ASSETS, rel))
                    self._raw[rel] = pg.transform.smoothscale(img, self.MINIMAP_SIZE)
            except (pg.error, OSError, ValueError):
                pass  # the game scene falls back to loading synchronously

        self._preload_thread = threading.Thread(target=work, name="preload", daemon=True)
        self._preload_thread.start()

    def preload_tick(self, colours=()):
        """Finish one small piece of preloading on the main thread (display-format conversion)."""
        if "map" in self._raw:
            raw = self._raw.pop("map")
            if self.map_img is None:  # otherwise the game already loaded it itself: drop the duplicate
                from .game import build_map
                self.map_img = build_map(self.assets, raw)
                return
        for rel in self.MINIMAPS:
            if rel in self._raw:
                self.minimaps[(rel, self.MINIMAP_SIZE)] = self._raw.pop(rel).convert_alpha()
                return
        for c in colours:
            if c not in self.assets._crew:
                self.assets.crew(c)
                return
        for i in range(1, 19):
            key = (f"Alerts/kill{i}.png", None)
            if key not in self.assets._img:
                self.assets.image(key[0])
                return

    # ------------------------------------------------------------------ scenes
    def set_scene(self, scene):
        if self.scene is not None:
            self.scene.leave()
        self.scene = scene

    def toast(self, text, secs=3.0):
        self.toasts.append([text, self.time + secs])

    # ------------------------------------------------------------------ hosting / connections
    def start_server(self, name=None, port=C.TCP_PORT, discovery=True, min_players=C.MIN_PLAYERS_TO_START):
        from ..logic import GameLogic
        from ..server import Server
        self.stop_server()
        srv = Server(port=port, name=name, discovery=discovery, logic=GameLogic(min_players=min_players))
        srv.start()  # raises OSError if the port is busy
        self.server = srv
        self.server_thread = threading.Thread(target=srv.run, name="amongus-server", daemon=True)
        self.server_thread.start()
        return srv

    def stop_server(self):
        if self.server is not None:
            self.server.stop()
            if self.server_thread:
                self.server_thread.join(timeout=2.0)
        self.server = None
        self.server_thread = None

    def add_bot(self, host="127.0.0.1", port=C.TCP_PORT):
        from ..bot import BOT_NAMES, Bot
        used = {b.name for b, _ in self.bots}
        name = next((n for n in BOT_NAMES if n not in used), f"Bot{len(self.bots) + 1}")
        b = Bot(host, port, name=name, seed=len(self.bots) * 31 + 7)
        t = threading.Thread(target=b.run, name=f"bot-{name}", daemon=True)
        t.start()
        self.bots.append((b, t))

    def remove_bot(self):
        live = [(b, t) for b, t in self.bots if t.is_alive()]
        if live:
            b, t = live[-1]
            b.stop_event.set()
            self.bots.remove((b, t))

    def stop_bots(self):
        for b, _ in self.bots:
            b.stop_event.set()
        self.bots = []

    def disconnect(self):
        if self.net is not None:
            self.net.close()
        self.net = None
        self.stop_bots()
        self.stop_server()
        self.my_id = None

    def launch_classic(self):
        import subprocess
        try:
            subprocess.Popen([sys.executable, os.path.join(C.ROOT, "classic.py")], cwd=C.ROOT)
        except OSError as e:
            self.toast(f"Could not start classic mode: {e}")

    # ------------------------------------------------------------------ loop
    def step(self, dt, events=None):
        """One frame. Split out so headless tests can drive the app."""
        self.time += dt
        events = pg.event.get() if events is None else events
        for e in events:
            if e.type == pg.QUIT:
                self.running = False
                return
            self.scene.handle(e)
        if self.net is not None:
            self.net.keepalive()
            for msg in self.net.poll():
                if msg["t"] == "_disconnected":
                    from .menus import MessageScene
                    reason = msg.get("reason", "Disconnected.")
                    self.disconnect()
                    self.assets.play("disconnect", 0.6)
                    self.set_scene(MessageScene(self, "Disconnected", reason))
                    break
                self.scene.on_net(msg)
        self.scene.update(dt)
        self.scene.draw(self.screen)
        self._draw_toasts()
        pg.display.flip()

    def _draw_toasts(self):
        from .ui import draw_text, panel
        self.toasts = [t for t in self.toasts if t[1] > self.time]
        y = 118
        for text, _ in self.toasts[-4:]:
            img_w = self.assets.font(20).size(text)[0] + 40
            r = pg.Rect(0, 0, img_w, 40)
            r.midtop = (W // 2, y)
            panel(self.screen, r, (30, 30, 40), radius=10, width=2, alpha=225)
            draw_text(self.screen, self.assets, text, 20, r.center, (255, 255, 255), anchor="center")
            y += 48

    def _log_error(self):
        import time
        import traceback
        try:
            with open(os.path.join(C.ROOT, "amongus_error.log"), "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} scene={type(self.scene).__name__}\n")
                f.write(traceback.format_exc())
        except OSError:
            pass

    def run(self):
        from .menus import MainMenu
        self.set_scene(MainMenu(self))
        streak = 0
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self.fps = self.clock.get_fps()
            try:
                self.step(min(dt, 0.1))
                streak = 0
            except Exception:
                # The host's window also runs the server: one bad frame must not end everyone's game.
                streak += 1
                self._log_error()
                if streak > 120:  # failing every frame for 2 s: give up for real
                    raise
                self.toast("Something went wrong (details in amongus_error.log)", 4)
        self.set_scene(Scene(self))
        self.disconnect()
        save_prefs(self.prefs)
        pg.quit()


def main():
    App().run()
