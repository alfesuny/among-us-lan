"""In-game scene: world rendering, movement, actions, HUD, and server message handling."""
import math
import os

import pygame as pg

from .. import config as C
from ..world import (MAP_H, MAP_W, SABOTAGES, STATIONS, TASKS, dist, get_world, room_at)
from .app import Scene
from .minigames import (FIXES, MINIGAMES, Cameras, EmergencyPanel, MapOverlay, MapView, ReactorScanner)
from .overlays import EjectOverlay, GameOverOverlay, KillAnimation, MeetingOverlay, RoleReveal
from .vision import Vision
from .ui import (BLACK, CYAN, GREEN, GREY, RED, WHITE, YELLOW, ChatBox, draw_text, panel, pulse,
                 render_text)

SW, SH = 1280, 720
DIRS = ("down", "up", "left", "right")
ANIM_FPS = 28
VISION_BASE = 380
EYE = 40  # eye height above the feet point, for line of sight

# Objects drawn onto the map once (they're separate images in the original art) and
# their highlighted versions, shown when the station is your current use target.
DECOR = [
    ("Items/cafeteria_comp.PNG", (3062, 387)), ("Items/emergency_button.PNG", (3284, 669)),
    ("Items/nav.PNG", (4513, 452)), ("Items/reactor_btn.PNG", (889, 996)),
    ("Items/lower_engine.png", (1127, 2318)), ("Items/upper_engine.png", (1117, 837)),
    ("Items/navigation.PNG", (5610, 1290)), ("Items/generator.png", (2472, 1721)),
    ("Items/admin_control1.PNG", (3815, 1804)), ("Items/admin_control2.PNG", (4068, 1803)),
    ("Items/garbage_liver.PNG", (3940, 321)), ("Items/wifi.png", (3699, 1553)),
    ("Items/electricity_wires.png", (3166, 1846)), ("Items/security_monitor.png", (1756, 1056)),
    ("Items/power_divert.png", (1031, 1213)), ("Items/gas_can.PNG", (3056, 2443)),
    ("Items/fuel_engine.PNG", (1226, 2300)),
]
HIGHLIGHT = {
    "download": ("Items/cafeteria_comp_highlight.png", (3062, 387)),
    "emergency": ("Items/emergency_button_highlight.PNG", (3284, 669)),
    "asteroids": ("Items/nav_highlight.png", (4513, 452)),
    "simon": ("Items/reactor_btn_highlight.PNG", (889, 996)),
    "fix_reactor_a": ("Items/reactor_btn_highlight.PNG", (889, 996)),
    "fuel_lower": ("Items/fuel_engine_highlighted.png", (1226, 2300)),
    "align": ("Items/upper_engine_highlight.png", (1117, 837)),
    "steering": ("Items/navigation_highlight.PNG", (5610, 1290)),
    "fix_lights": ("Items/generator_highlight.png", (2472, 1721)),
    "swipe": ("Items/admin_control1_highlight.png", (3815, 1804)),
    "upload": ("Items/admin_control2_highlight.png", (4068, 1803)),
    "garbage": ("Items/garbage_liver_highlight.PNG", (3940, 321)),
    "wires_admin": ("Items/wifi_highlight.png", (3700, 1554)),
    "wires_storage": ("Items/electricity_wires_highlight.png", (3166, 1846)),
    "cams": ("Items/security_monitor_highlight.png", (1756, 1062)),
    "divert": ("Items/power_divert_highlight.png", (1031, 1213)),
    "gas_can": ("Items/gas_can_highlighted.png", (3056, 2443)),
}


def build_map(assets, raw=None):
    if raw is None:
        raw = pg.image.load(os.path.join(C.ASSETS, "Maps", "map2.png"))
    img = raw.convert()
    for rel, pos in DECOR:
        try:
            img.blit(assets.image(rel), pos)
        except (pg.error, FileNotFoundError):
            pass
    vent = assets.image("Items/ventilation.png", (64, 48))
    for vx, vy in get_world().vents:
        img.blit(vent, vent.get_rect(center=(vx, vy)))
    return img


class Remote:
    __slots__ = ("id", "x", "y", "tx", "ty", "dir", "moving", "alive", "vent", "anim", "face")

    def __init__(self, pid, x, y):
        self.id = pid
        self.x = self.tx = float(x)
        self.y = self.ty = float(y)
        self.dir = 0
        self.moving = False
        self.alive = True
        self.vent = None
        self.anim = 0.0
        self.face = "right"


class GameScene(Scene):
    def __init__(self, app, msg):
        super().__init__(app)
        self.world = get_world()
        self.me = app.my_id
        self.role = msg["role"]
        self.imposters = set(msg["imposters"])
        self.n_imposters = msg["n_imposters"]
        self.tasks = msg["tasks"]
        self.settings = msg["settings"]
        self.roster = {p["id"]: p for p in msg["players"]}
        mine = self.roster.get(self.me, {"name": "?", "colour": "Red"})
        self.my_name, self.my_colour = mine["name"], mine["colour"]
        self.x, self.y, self.epoch = float(msg["x"]), float(msg["y"]), msg["ep"]
        self.dir, self.moving, self.anim, self.face = 0, False, 0.0, "right"
        self.alive = True
        self.vent = None
        self.others = {}
        self.bodies = []
        self.sab = None
        self.me_info = {"kc": 99, "sc": 99, "em": self.settings.get("emergency_meetings", 1), "ec": 99}
        self.taskbar = 0.0
        self.phase = "reveal"
        self.t = 0.0
        self.send_t = 0.0
        self.last_sent = None
        self.step_t = 0.0
        self.minigame = None
        self.map_overlay = None
        self.meeting = None
        self.last_tie = False
        partners = [self.roster[i] for i in self.imposters if i != self.me and i in self.roster]
        self.overlay = RoleReveal(self, self.role, partners, self.n_imposters)
        self.kill_anim = None
        self.chat = ChatBox((20, SH - 330, 420, 300), self.send_chat)
        self.ghost_chat_open = False
        self.use_target = self.report_target = self.kill_target = self.vent_target = None
        self.show_tasks = True
        self.input_override = None  # (dx, dy) for headless tests
        self.ambience = None
        self.ambience_room = None
        self.alarm = None
        self.buttons = {}
        self._fog_cache = {}
        if getattr(app, "vision", None) is None:
            app.vision = Vision()
        self.vision = app.vision
        self._light = pg.Surface((SW, SH))
        self._polymask = pg.Surface((SW, SH))
        self._fogsurf = pg.Surface((SW, SH))
        self._lightmasks = {}
        # first-use work done during the 5 s role reveal instead of mid-round (one item per frame)
        a = self.assets
        self._preload = [
            lambda: self.minimap("Maps/mini_map.PNG", (1100, 602)),
            lambda: self.minimap("Maps/mini_map3.png", (1100, 602)),
            lambda: self._lightmask(int(VISION_BASE * self.settings.get("crew_vision", 1.0))),
            lambda: self._lightmask(int(VISION_BASE * self.settings.get("crew_vision", 1.0) * 0.32)),
            lambda: self._lightmask(int(VISION_BASE * self.settings.get("imposter_vision", 1.5))),
            lambda: a.image("Alerts/eject.png", (SW, SH), alpha=False),
            lambda: a.image("Meeting/chat.png", (380, 380)),
            lambda: a.image("Meeting/chat_dead.png", (380, 380)),
            lambda: a.image("Meeting/skip_vote.png", (164, 40)),
            lambda: a.image("Meeting/voted_players.PNG"),
        ] + [lambda c=c: a.crew(c) for c in {p["colour"] for p in msg["players"]}]
        if app.map_img is None:  # preload didn't finish (e.g. game started instantly)
            raw = app._raw.pop("map", None)
            app.map_img = build_map(self.assets, raw)
        self.map_img = app.map_img
        self.assets.stop_music(800)
        pg.key.set_repeat()  # held Tab/Q must not toggle the map or spam kills

    # ------------------------------------------------------------------ properties / helpers
    @property
    def is_imposter(self):
        return self.role == "imposter"

    def critical(self):
        return bool(self.sab and SABOTAGES[self.sab["k"]]["critical"])

    def send(self, msg):
        if self.app.net:
            self.app.net.send(msg)

    def send_chat(self, text):
        self.send({"t": "chat", "text": text})

    def minimap(self, rel, size):
        key = (rel, size)
        if key not in self.app.minimaps:
            raw = self.app._raw.pop(rel, None) if size == self.app.MINIMAP_SIZE else None
            if raw is None:
                raw = pg.transform.smoothscale(pg.image.load(os.path.join(C.ASSETS, rel)), size)
            self.app.minimaps[key] = raw.convert_alpha()
        return self.app.minimaps[key]

    def room_of(self, p):
        return room_at(p[0], p[1])

    def positions_for_utilities(self):
        """Living, visible-to-cameras people (bodies too) for Admin."""
        out = []
        if self.alive and self.vent is None:
            out.append((self.me, (self.x, self.y)))
        for r in self.others.values():
            if r.alive and r.vent is None:
                out.append((r.id, (r.x, r.y)))
        for b in self.bodies:
            out.append((b[0], (b[1], b[2])))
        return out

    def visible_sprites_for_cams(self):
        out = []
        if self.alive and self.vent is None:
            out.append((self.me, (self.x, self.y), self.sprite_for(self.my_colour, self.dir, self.moving, self.anim, True, self.face)))
        for r in self.others.values():
            if r.alive and r.vent is None:
                out.append((r.id, (r.x, r.y), self.sprite_for(self.colour_of(r.id), r.dir, r.moving, r.anim, True, r.face)))
        for b in self.bodies:
            out.append((b[0], (b[1], b[2]), self.assets.crew(b[3]).dead))
        return out

    def colour_of(self, pid):
        return self.roster.get(pid, {}).get("colour", "Red")

    def name_of(self, pid):
        return self.roster.get(pid, {}).get("name", "?")

    def current_steps(self):
        """[(task, step_index, station, minigame)] for unfinished tasks."""
        out = []
        for t in self.tasks:
            if t["step"] < len(t["steps"]):
                station, mg = t["steps"][t["step"]]
                out.append((t, t["step"], station, mg))
        return out

    def task_marker_stations(self):
        if self.sab and self.sab["k"] == "comms" and not self.is_imposter:
            return []
        return [s for _, _, s, _ in self.current_steps()]

    def vision_radius(self):
        if not self.alive:
            return None
        mult = self.settings.get("imposter_vision" if self.is_imposter else "crew_vision", 1.0)
        r = VISION_BASE * mult
        if self.sab and self.sab["k"] == "lights" and not self.is_imposter:
            r *= 0.32
        return r

    def can_see(self, x, y):
        r = self.vision_radius()
        if r is None:
            return True
        if math.hypot(x - self.x, y - self.y) > r + 40:
            return False
        return not self.vision.enabled or self.vision.line_of_sight(self.x, self.y - EYE, x, y - EYE)

    def sprite_for(self, colour, d, moving, anim, alive, face):
        crew = self.assets.crew(colour)
        if not alive:
            return crew.ghost[face]
        frames = crew.walk[DIRS[d]]
        return frames[int(anim * ANIM_FPS) % len(frames)] if moving else frames[0]

    # ------------------------------------------------------------------ network
    def on_net(self, m):
        t = m["t"]
        h = getattr(self, "net_" + t, None)
        if h:
            h(m)

    def net_snap(self, m):
        self.phase = m["ph"]
        if self.phase == "play" and isinstance(self.overlay, RoleReveal):
            self.overlay = None
        seen = set()
        for pid, x, y, d, moving, alive, vent in m["pl"]:
            seen.add(pid)
            if pid == self.me:
                if not alive and self.alive:
                    self._became_dead(None)
                continue
            r = self.others.get(pid)
            if r is None:
                r = self.others[pid] = Remote(pid, x, y)
            if abs(x - r.tx) > 0.5:
                r.face = "right" if x > r.tx else "left"
            r.tx, r.ty = float(x), float(y)
            r.dir, r.moving, r.alive = d, bool(moving), bool(alive)
            r.vent = None if vent < 0 else vent
        for pid in list(self.others):
            if pid not in seen:
                del self.others[pid]
        self.bodies = m["bd"]
        old = self.sab
        self.sab = m["sab"]
        if old and not self.sab:
            self._sabotage_over()
        self.taskbar = m["tb"]
        me = m.get("me")
        if me:
            self.me_info = me

    def net_play(self, m):
        self.phase = "play"
        if isinstance(self.overlay, RoleReveal):
            self.overlay = None

    def net_teleport(self, m):
        self.x, self.y, self.epoch = float(m["x"]), float(m["y"]), m["ep"]
        self.last_sent = None

    def net_killed(self, m):
        self._became_dead(m.get("by"))

    def _became_dead(self, by):
        if not self.alive:
            return
        self.alive = False
        self.vent = None
        self._close_minigame()
        self.map_overlay = None
        if self.meeting is None and self.phase == "play":
            self.kill_anim = KillAnimation(self, by)

    def net_kill_ok(self, m):
        self.assets.play("kill", 0.8)

    def net_deny(self, m):
        what = m.get("what")
        self.assets.play("kill_denied", 0.5)
        if what == "emergency":
            self.app.toast("Can't call a meeting right now")
        elif what in ("report", "task"):
            self.app.toast("Too far away")

    def net_task_ok(self, m):
        for t in self.tasks:
            if t["id"] == m["task"]:
                t["step"] = m["step"]
                if t["step"] < len(t["steps"]):
                    nxt = STATIONS[t["steps"][t["step"]][0]]["label"]
                    self.app.toast(f"{t['name']}: next step in {nxt}")
        if all(t["step"] >= len(t["steps"]) for t in self.tasks):
            self.app.toast("All your tasks are done!")

    def net_vent_state(self, m):
        was = self.vent
        self.vent = m["id"]
        if self.vent is not None:  # the server moved us into the vent: camera follows
            self.x, self.y = map(float, self.world.vents[self.vent])
        if (was is None) != (self.vent is None):
            self.assets.play("vent", 0.6)
        elif self.vent is not None:
            self.assets.play("vent_move", 0.5)

    def net_sabotage(self, m):
        kind = m["kind"]
        self.sab = {"k": kind, "rem": m.get("dur"), "done": [], "held": []}
        if SABOTAGES[kind]["critical"]:
            self.alarm = self.assets.play("crisis", 0.5, loops=-1)
        self.app.toast(SABOTAGES[kind]["name"] + "!" if kind in ("reactor", "o2") else
                       ("Lights sabotaged!" if kind == "lights" else "Communications sabotaged!"))

    def net_sabotage_end(self, m):
        self.sab = None
        self._sabotage_over()

    def _sabotage_over(self):
        if self.alarm is not None:
            self.alarm.stop()
            self.alarm = None
        if self.minigame is not None and getattr(self.minigame, "is_fix", False):
            self._close_minigame()

    def net_meeting(self, m):
        self._close_minigame()
        self.map_overlay = None
        self.kill_anim = None
        self.vent = None
        self.ghost_chat_open = False
        self.chat.input.focused = False
        self.meeting = MeetingOverlay(self, m)
        self.overlay = self.meeting
        self.phase = "meeting"
        if self.alarm is not None:
            self.alarm.stop()
            self.alarm = None

    def net_meeting_stage(self, m):
        if self.meeting:
            self.meeting.set_stage(m["stage"], m["dur"])

    def net_voted(self, m):
        if self.meeting:
            self.meeting.on_voted(m["id"])

    def net_vote_result(self, m):
        self.last_tie = m.get("tie", False)
        if self.meeting:
            self.meeting.on_result(m)

    def net_eject(self, m):
        self.meeting = None
        self.overlay = EjectOverlay(self, m, tie=self.last_tie)
        self.phase = "eject"
        if m.get("id") == self.me:
            self.alive = False

    def net_resume(self, m):
        self.overlay = None
        self.meeting = None
        self.phase = "play"
        self.vent = None
        self.chat.rect = pg.Rect(20, SH - 330, 420, 300)
        self.chat.input.rect = pg.Rect(20, SH - 66, 420, 36)

    def net_chat(self, m):
        rgb = C.COLOURS.get(m["colour"], ((255, 255, 255), None))[0]
        self.chat.add(m["name"], rgb, m["text"], m.get("dead", False))
        if self.meeting is None:
            self.assets.play("key", 0.3)

    def net_left(self, m):
        self.app.toast(f"{m['name']} left the game")
        self.others.pop(m["id"], None)

    def net_game_over(self, m):
        self._close_minigame()
        self.map_overlay = None
        self.meeting = None
        self.kill_anim = None
        if self.alarm is not None:
            self.alarm.stop()
            self.alarm = None
        self.overlay = GameOverOverlay(self, m)
        self.phase = "over"
        self.app.toasts.clear()

    def net_to_lobby(self, m):
        from .lobby import LobbyScene
        self.app.set_scene(LobbyScene(self.app, last_lobby=getattr(self.app, "last_lobby", None)))

    def net_lobby(self, m):
        self.app.last_lobby = m

    def net_error(self, m):
        self.app.toast(m.get("msg", "Error"))

    def net_kicked(self, m):
        from .menus import MessageScene
        self.app.disconnect()
        self.app.set_scene(MessageScene(self.app, "Kicked", "The host removed you from the game."))

    # ------------------------------------------------------------------ actions
    def open_minigame(self, mg):
        self.minigame = mg
        self.assets.play("click", 0.5)

    def _close_minigame(self):
        if self.minigame is not None:
            if not self.minigame.closed:
                self.minigame.close()
            self.minigame = None

    def act_use(self):
        if self.phase != "play":
            return
        if self.vent is not None:
            self.send({"t": "vent", "act": "exit"})
            return
        tgt = self.use_target
        if tgt is None:
            if self.vent_target is not None:
                self.act_vent()
            return
        kind, data = tgt
        if kind == "task":
            task, step, station, mg = data
            tid = task["id"]
            cls = MINIGAMES[mg]
            game = cls(self, on_success=lambda tid=tid, step=step: self.send({"t": "task", "task": tid, "step": step}),
                       colour=self.my_colour, name=self.my_name)
            self.open_minigame(game)
        elif kind == "fix":
            panel_id = data
            sk = self.sab["k"]
            if sk == "reactor":
                game = ReactorScanner(self, panel_id=panel_id,
                                      send_hold=lambda p, on: self.send({"t": "hold", "panel": p, "on": on}))
            else:
                game = FIXES[sk](self, on_success=lambda p=panel_id: self.send({"t": "fix", "panel": p}))
            game.is_fix = True
            self.open_minigame(game)
        elif kind == "emergency":
            self.open_minigame(EmergencyPanel(self, call=lambda: self.send({"t": "emergency"})))
        elif kind == "admin":
            self.open_minigame(MapView(self))
        elif kind == "cams":
            self.open_minigame(Cameras(self))

    def act_kill(self):
        if self.phase != "play" or not self.is_imposter or not self.alive or self.vent is not None:
            return
        if self.kill_target is None:
            return
        if self.me_info.get("kc", 1) > 0:
            self.assets.play("kill_denied", 0.5)
            return
        self.send({"t": "kill", "target": self.kill_target})

    def act_report(self):
        if self.phase == "play" and self.report_target is not None and self.alive:
            self.send({"t": "report", "body": self.report_target})

    def act_vent(self):
        if self.phase != "play" or not self.is_imposter or not self.alive:
            return
        if self.vent is not None:
            self.send({"t": "vent", "act": "exit"})
        elif self.vent_target is not None:
            self.send({"t": "vent", "act": "enter", "id": self.vent_target})

    def vent_move(self, step):
        if self.vent is None:
            return
        links = self.world.vent_links[self.vent]
        if links:
            # right/D goes to the eastern-most linked vent, left/A to the western-most
            ordered = sorted(links, key=lambda i: self.world.vents[i][0])
            self.send({"t": "vent", "act": "move", "to": ordered[-1] if step > 0 else ordered[0]})

    def do_sabotage(self, kind):
        self.send({"t": "sabotage", "kind": kind})

    def toggle_map(self):
        if self.map_overlay:
            self.map_overlay = None
        else:
            self.map_overlay = MapOverlay(self, sabotage=self.is_imposter)
            self.assets.play("map", 0.5)

    # ------------------------------------------------------------------ input
    def handle(self, e):
        if self.kill_anim is not None:
            return True
        if self.overlay is not None:
            if self.overlay.handle(e):
                return True
        if self.overlay is not None:
            return True
        if self.minigame is not None:
            self.minigame.handle(e)
            return True
        if self.map_overlay is not None:
            if self.map_overlay.handle(e):
                return True
        if not self.alive and self.ghost_chat_open:
            if self.chat.handle(e):
                return True
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
            for name, r in self.buttons.items():
                if r.collidepoint(e.pos):
                    self._button(name)
                    return True
        if e.type == pg.KEYDOWN:
            k = e.key
            if self.vent is not None and k in (pg.K_a, pg.K_LEFT, pg.K_d, pg.K_RIGHT):
                self.vent_move(-1 if k in (pg.K_a, pg.K_LEFT) else 1)
                return True
            if k in (pg.K_e, pg.K_SPACE):
                self.act_use()
            elif k == pg.K_q:
                self.act_kill()
            elif k == pg.K_r:
                self.act_report()
            elif k == pg.K_v:
                self.act_vent()
            elif k in (pg.K_TAB, pg.K_m):
                self.toggle_map()
            elif k == pg.K_t:
                self.show_tasks = not self.show_tasks
            elif k == pg.K_RETURN and not self.alive:
                self.ghost_chat_open = True
                self.chat.input.focused = True
            elif k == pg.K_ESCAPE and self.ghost_chat_open:
                self.ghost_chat_open = False
        return False

    def _button(self, name):
        if name == "use":
            self.act_use()
        elif name == "report":
            self.act_report()
        elif name == "kill":
            self.act_kill()
        elif name == "sabotage":
            self.map_overlay = MapOverlay(self, sabotage=True)
        elif name == "vent":
            self.act_vent()
        elif name == "map":
            self.toggle_map()
        elif name == "chat":
            self.ghost_chat_open = not self.ghost_chat_open
            self.chat.input.focused = self.ghost_chat_open
        elif name.startswith("ventto"):
            self.send({"t": "vent", "act": "move", "to": int(name[6:])})

    # ------------------------------------------------------------------ update
    def update(self, dt):
        self.t += dt
        if self._preload and self.overlay is not None:
            self._preload.pop(0)()
        if self.overlay is not None:
            self.overlay.update(dt)
        if self.kill_anim is not None:
            self.kill_anim.update(dt)
            if self.kill_anim.closed:
                self.kill_anim = None
        if self.minigame is not None:
            self.minigame.update(dt)
            if self.minigame.closed:
                self.minigame = None
        if self.map_overlay is not None:
            self.map_overlay.update(dt)
            if self.map_overlay.closed:
                self.map_overlay = None
        self.chat.update(dt)
        if self.sab and self.sab.get("rem") is not None:
            self.sab["rem"] = max(0.0, self.sab["rem"] - dt)
        for key in ("kc", "sc", "ec"):
            if isinstance(self.me_info.get(key), (int, float)):
                self.me_info[key] = max(0.0, self.me_info[key] - dt)
        if self.phase == "play":
            self.move_local(dt)
            self.send_position(dt)
            self.find_targets()
        for r in self.others.values():
            k = min(1.0, dt * 14)
            if math.hypot(r.tx - r.x, r.ty - r.y) > 400:
                r.x, r.y = r.tx, r.ty
            else:
                r.x += (r.tx - r.x) * k
                r.y += (r.ty - r.y) * k
            r.anim = r.anim + dt if r.moving else 0.0
        self.update_ambience()

    def move_local(self, dt):
        blocked = (self.minigame is not None or self.overlay is not None or self.kill_anim is not None
                   or self.vent is not None or (self.ghost_chat_open and self.chat.input.focused))
        dx = dy = 0
        if not blocked:
            if self.input_override is not None:
                dx, dy = self.input_override
            else:
                keys = pg.key.get_pressed()
                dx = (keys[pg.K_d] or keys[pg.K_RIGHT]) - (keys[pg.K_a] or keys[pg.K_LEFT])
                dy = (keys[pg.K_s] or keys[pg.K_DOWN]) - (keys[pg.K_w] or keys[pg.K_UP])
        self.moving = bool(dx or dy)
        if not self.moving:
            self.anim = 0.0
            return
        speed = C.PLAYER_SPEED * self.settings.get("player_speed", 1.0)
        n = math.hypot(dx, dy)
        mx, my = dx / n * speed * dt, dy / n * speed * dt
        if self.alive:
            self.x, self.y = self.world.collider.move(self.x, self.y, mx, my)
        else:  # ghosts float through walls
            self.x = min(max(self.x + mx, 20), MAP_W - 20)
            self.y = min(max(self.y + my, 40), MAP_H - 10)
        if dx > 0:
            self.dir, self.face = 3, "right"
        elif dx < 0:
            self.dir, self.face = 2, "left"
        elif dy > 0:
            self.dir = 0
        else:
            self.dir = 1
        self.anim += dt
        self.step_t -= dt
        if self.alive and self.step_t <= 0:
            self.step_t = 0.28
            self.assets.footstep()

    def send_position(self, dt):
        self.send_t -= dt
        state = (round(self.x, 1), round(self.y, 1), self.dir, int(self.moving), self.epoch)
        if self.send_t <= 0 and (state != self.last_sent or self.send_t < -0.5):
            self.send_t = 1.0 / C.CLIENT_SEND_HZ
            self.last_sent = state
            self.send({"t": "pos", "x": state[0], "y": state[1], "d": self.dir, "m": state[3], "ep": self.epoch})

    def find_targets(self):
        me = (self.x, self.y)
        self.use_target = self.report_target = self.kill_target = self.vent_target = None
        if self.vent is not None:
            return
        best = None  # (priority, distance, target)
        if self.sab and self.alive:
            for p in SABOTAGES[self.sab["k"]]["panels"]:
                if p not in self.sab.get("done", []):
                    d = dist(me, STATIONS[p]["pos"])
                    if d <= C.USE_RANGE:
                        cand = (0, d, ("fix", p))
                        best = min(best, cand) if best else cand
        if not self.is_imposter:
            for task, step, station, mg in self.current_steps():
                d = dist(me, STATIONS[station]["pos"])
                if d <= C.USE_RANGE:
                    cand = (1, d, ("task", (task, step, station, mg)))
                    best = min(best, cand, key=lambda c: c[:2]) if best else cand
        if self.alive:
            d = dist(me, STATIONS["emergency"]["pos"])
            if d <= C.EMERGENCY_RANGE:
                cand = (2, d, ("emergency", None))
                best = min(best, cand, key=lambda c: c[:2]) if best else cand
        for util, kind in (("admin_map", "admin"), ("cams", "cams")):
            d = dist(me, STATIONS[util]["pos"])
            if d <= C.USE_RANGE:
                cand = (3, d, (kind, None))
                best = min(best, cand, key=lambda c: c[:2]) if best else cand
        self.use_target = best[2] if best else None
        if self.alive:
            near = [(dist(me, (b[1], b[2])), b[0]) for b in self.bodies if self.can_see(b[1], b[2])]
            near = [n for n in near if n[0] <= C.REPORT_RANGE]
            if near:
                self.report_target = min(near)[1]
        if self.is_imposter and self.alive:
            cands = [(dist(me, (r.x, r.y)), r.id) for r in self.others.values()
                     if r.alive and r.vent is None and r.id not in self.imposters and self.can_see(r.x, r.y)]
            cands = [c for c in cands if c[0] <= C.KILL_RANGE]
            if cands:
                self.kill_target = min(cands)[1]
            vents = [(dist(me, v), i) for i, v in enumerate(self.world.vents)]
            vents = [v for v in vents if v[0] <= C.VENT_RANGE]
            if vents:
                self.vent_target = min(vents)[1]

    def update_ambience(self):
        room = room_at(self.x, self.y) if self.phase == "play" else None
        if room == self.ambience_room:
            return
        if self.ambience is not None:
            self.ambience.fadeout(800)
            self.ambience = None
        self.ambience_room = room
        if room:
            snd = self.assets.sound(room)
            snd.set_volume(self.assets.volume * 0.25)
            self.ambience = snd.play(loops=-1, fade_ms=800)

    def leave(self):
        pg.key.set_repeat(350, 35)
        self._close_minigame()
        if self.ambience is not None:
            self.ambience.fadeout(300)
        if self.alarm is not None:
            self.alarm.stop()

    # ------------------------------------------------------------------ drawing
    def camera(self):
        cx = min(max(self.x - SW / 2, 0), MAP_W - SW)
        cy = min(max(self.y - SH / 2 - 30, 0), MAP_H - SH)
        return cx, cy

    def draw(self, surf):
        if self.kill_anim is not None:
            self.kill_anim.draw(surf)
            return
        if self.overlay is not None:  # every overlay is full-screen
            self.overlay.draw(surf)
            return
        self.draw_world(surf)
        self.draw_hud(surf)
        if self.map_overlay is not None:
            self.map_overlay.draw(surf)
        if self.minigame is not None:
            self.minigame.draw(surf)

    def draw_world(self, surf):
        cx, cy = self.camera()
        surf.blit(self.map_img, (0, 0), pg.Rect(int(cx), int(cy), SW, SH))
        a = self.assets

        def S(x, y):
            return x - cx, y - cy

        # highlights for the current use target and my task stations
        glow = pulse(self.t, 5, 0.3, 1.0)
        targets = set(self.task_marker_stations())
        if self.sab:
            targets |= {p for p in SABOTAGES[self.sab["k"]]["panels"] if p not in self.sab.get("done", [])}
        use_station = None
        if self.use_target:
            kind, data = self.use_target
            use_station = {"task": lambda: data[2], "fix": lambda: data, "emergency": lambda: "emergency",
                           "admin": lambda: "admin_map", "cams": lambda: "cams"}[kind]()
        for st in targets | ({use_station} if use_station else set()):
            sx, sy = S(*STATIONS[st]["pos"])
            if -100 < sx < SW + 100 and -100 < sy < SH + 100:
                if st == use_station and st in HIGHLIGHT:
                    rel, pos = HIGHLIGHT[st]
                    surf.blit(a.image(rel), S(*pos))
                col = (255, 60, 60) if st.startswith("fix_") else (255, 230, 60)
                pg.draw.circle(surf, col, (sx, sy), int(26 + 8 * glow), 3)

        # bodies
        for pid, bx, by, colour in self.bodies:
            if self.can_see(bx, by):
                img = a.crew(colour).dead
                r = img.get_rect(midbottom=S(bx, by + 8))
                if pid == self.report_target:
                    pg.draw.ellipse(surf, YELLOW, r.inflate(16, 4).move(0, 20), 3)
                surf.blit(img, r)

        # players, sorted by y for overlap
        draws = []
        if self.vent is None:
            draws.append((self.y, self.me, self.x, self.y, self.my_colour, self.dir, self.moving, self.anim, self.alive, self.face))
        for r in self.others.values():
            if r.vent is not None:
                continue
            if not r.alive and self.alive:
                continue  # living can't see ghosts
            if r.alive and not self.can_see(r.x, r.y):
                continue
            draws.append((r.y, r.id, r.x, r.y, self.colour_of(r.id), r.dir, r.moving, r.anim, r.alive, r.face))
        draws.sort()
        for _, pid, x, y, colour, d, moving, anim, alive, face in draws:
            img = self.sprite_for(colour, d, moving, anim, alive, face)
            bob = math.sin(self.t * 3 + pid) * 6 if not alive else 0
            r = img.get_rect(midbottom=S(x, y + 6 + bob))
            if pid == self.kill_target:
                outline = pg.mask.from_surface(img).outline()
                if outline:
                    pg.draw.lines(surf, RED, True, [(r.x + px, r.y + py) for px, py in outline], 4)
            surf.blit(img, r)
            name_col = RED if (self.is_imposter and pid in self.imposters) else WHITE
            tag = render_text(a, self.name_of(pid), 16, name_col)
            surf.blit(tag, tag.get_rect(midbottom=(r.centerx, r.y - 2)))

        # vision fog
        rad = self.vision_radius()
        if rad is not None:
            lights_out = self.sab and self.sab["k"] == "lights" and not self.is_imposter
            night = (14, 14, 22) if lights_out else (62, 62, 78)
            px, py = S(self.x, self.y - EYE)
            poly = self.vision.polygon(self.x, self.y - EYE, rad) if self.vision.enabled else None
            if poly is None:
                fog = self._fog(int(rad), night)
                surf.blit(fog, (px - fog.get_width() // 2, py - fog.get_height() // 2), special_flags=pg.BLEND_MULT)
            else:
                # light = radial gradient restricted to the visibility polygon; fog = max(night, light)
                self._light.fill(BLACK)
                m = self._lightmask(int(rad))
                self._light.blit(m, m.get_rect(center=(px, py)))
                self._polymask.fill(BLACK)
                pg.draw.polygon(self._polymask, WHITE, [(x - cx, y - cy) for x, y in poly])
                self._light.blit(self._polymask, (0, 0), special_flags=pg.BLEND_MULT)
                self._fogsurf.fill(night)
                self._fogsurf.blit(self._light, (0, 0), special_flags=pg.BLEND_MAX)
                surf.blit(self._fogsurf, (0, 0), special_flags=pg.BLEND_MULT)
        if self.sab and self.sab["k"] == "reactor":
            red = pg.Surface((SW, SH))
            v = int(170 + 85 * pulse(self.t, 4, 0, 1))
            red.fill((255, v, v))
            surf.blit(red, (0, 0), special_flags=pg.BLEND_MULT)

    def _lightmask(self, radius):
        if radius not in self._lightmasks:
            if len(self._lightmasks) > 6:
                self._lightmasks.clear()
            mask = self.assets.image("Environment/light_350_med.png")
            self._lightmasks[radius] = pg.transform.smoothscale(mask, (radius * 2 + 120, radius * 2 + 120))
        return self._lightmasks[radius]

    def _fog(self, radius, night):
        """A screen-covering multiply mask: white (clear) disc fading to `night` outside."""
        key = (radius, night)
        if key not in self._fog_cache:
            if len(self._fog_cache) > 6:
                self._fog_cache.clear()
            size = (SW * 2 + radius, SH * 2 + radius)
            fog = pg.Surface(size)
            fog.fill(night)
            mask = self.assets.image("Environment/light_350_med.png")
            m = pg.transform.smoothscale(mask, (radius * 2 + 120, radius * 2 + 120))
            fog.blit(m, m.get_rect(center=(size[0] // 2, size[1] // 2)))
            self._fog_cache[key] = fog
        return self._fog_cache[key]

    def draw_hud(self, surf):
        a = self.assets
        self.buttons = {}
        # total task bar
        bar = pg.Rect(18, 12, 420, 32)
        pg.draw.rect(surf, (30, 30, 30), bar.inflate(6, 6), border_radius=4)
        if self.taskbar is None:
            pg.draw.rect(surf, (70, 70, 70), bar)
            draw_text(surf, a, "COMMS SABOTAGED", 16, bar.center, (230, 120, 120), anchor="center")
        else:
            pg.draw.rect(surf, (50, 70, 50), bar)
            pg.draw.rect(surf, (68, 216, 68), (bar.x, bar.y, int(bar.w * self.taskbar), bar.h))
            draw_text(surf, a, "TOTAL TASKS COMPLETED", 15, bar.center, WHITE, anchor="center")
        # task list
        if self.show_tasks:
            lines = []
            if self.sab:
                s = self.sab
                name = SABOTAGES[s["k"]]["name"]
                extra = ""
                if s.get("rem") is not None:
                    extra = f" {math.ceil(s['rem'])}s"
                if s["k"] == "o2":
                    extra += f" ({len(s.get('done', []))}/2)"
                if s["k"] == "reactor":
                    extra += f" ({len(s.get('held', []))}/2 holding)"
                lines.append((name + extra, RED if int(self.t * 3) % 2 else (255, 150, 150)))
            if self.is_imposter:
                lines.append(("Sabotage and kill everyone.", (255, 90, 90)))
                lines.append(("Fake Tasks:", (255, 90, 90)))
            if self.sab and self.sab["k"] == "comms" and not self.is_imposter:
                lines.append(("Comms Sabotaged - tasks hidden", (230, 120, 120)))
            else:
                for t in self.tasks:
                    n = len(t["steps"])
                    done = t["step"] >= n
                    station = t["steps"][min(t["step"], n - 1)][0]
                    txt = f"{STATIONS[station]['label']}: {t['name']}" + (f" ({t['step']}/{n})" if n > 1 else "")
                    col = GREEN if done else (YELLOW if t["step"] > 0 else WHITE)
                    lines.append((txt, col))
            if not self.alive:
                lines.append(("You're dead: finish tasks as a ghost", CYAN))
            h = 14 + len(lines) * 24
            box = pg.Rect(18, 54, 420, h)
            panel(surf, box, (20, 20, 30), radius=8, width=0, alpha=170)
            for i, (txt, col) in enumerate(lines):
                draw_text(surf, a, txt, 16, (box.x + 10, box.y + 8 + i * 24), col)
        # map button (+ ghost chat)
        mr = pg.Rect(SW - 76, 12, 60, 60)
        surf.blit(a.image("UI/map_button.png", (60, 60)), mr)
        self.buttons["map"] = mr
        if not self.alive:
            cr = pg.Rect(SW - 150, 16, 64, 52)
            panel(surf, cr, (60, 70, 100), radius=10, width=3)
            draw_text(surf, a, "CHAT", 16, cr.center, WHITE, anchor="center")
            self.buttons["chat"] = cr
        rtt = self.app.net.rtt if self.app.net else None
        info = f"{self.app.fps:.0f} fps" + (f"  {rtt * 1000:.0f} ms" if rtt is not None else "")
        draw_text(surf, a, info, 13, (SW - 16, 78), GREY, anchor="topright")
        # action buttons
        self._action_buttons(surf)
        # critical sabotage banner
        if self.critical():
            pg.draw.rect(surf, (255, 0, 0), surf.get_rect(), int(6 + 6 * pulse(self.t, 6, 0, 1)))
            name = SABOTAGES[self.sab["k"]]["name"]
            rem = self.sab.get("rem")
            draw_text(surf, a, f"{name}! {math.ceil(rem) if rem is not None else ''}", 30, (SW // 2, 60), RED,
                      anchor="midtop", width=3)
        if self.vent is not None:
            self._vent_ui(surf)
        if not self.alive and self.ghost_chat_open:
            self.chat.draw(surf, a)
            draw_text(surf, a, "Ghost chat (only the dead can read this)", 15,
                      (self.chat.rect.x, self.chat.rect.y - 20), CYAN)

    def _action_button(self, surf, name, rect, label, enabled, icon=None, colour=(70, 80, 110), sub=None, key=None):
        a = self.assets
        if icon is not None:
            img = a.image(icon, (rect.w, rect.h))
            if not enabled:
                img = img.copy()
                img.set_alpha(90)
            surf.blit(img, rect)
        else:
            s = pg.Surface(rect.size, pg.SRCALPHA)
            col = colour if enabled else (60, 60, 66)
            pg.draw.rect(s, (*col, 230 if enabled else 130), s.get_rect(), border_radius=18)
            pg.draw.rect(s, (15, 15, 20), s.get_rect(), 4, border_radius=18)
            surf.blit(s, rect)
            draw_text(surf, a, label, 22, rect.center, WHITE if enabled else GREY, anchor="center")
        if sub:
            draw_text(surf, a, sub, 34, rect.center, WHITE, anchor="center", width=3)
        if key:
            draw_text(surf, a, key, 13, (rect.right - 8, rect.bottom - 6), (220, 220, 220), anchor="bottomright")
        self.buttons[name] = rect

    def _action_buttons(self, surf):
        if self.phase != "play":
            return
        use_label = "USE"
        if self.use_target:
            use_label = {"task": "USE", "fix": "FIX", "emergency": "CALL", "admin": "ADMIN", "cams": "CAMS"}[self.use_target[0]]
        if self.vent is not None:
            use_label = "EXIT"
        if self.is_imposter and self.use_target is None and self.vent_target is not None and self.vent is None:
            use_label = "VENT"
        size = 104
        x0, y0 = SW - size - 16, SH - size - 16
        enabled = bool(self.use_target) or self.vent is not None or (self.is_imposter and self.vent_target is not None and self.alive)
        self._action_button(surf, "use", pg.Rect(x0, y0, size, size), use_label, enabled, colour=(60, 120, 200),
                            key="E")
        if self.alive:
            self._action_button(surf, "report", pg.Rect(x0, y0 - size - 12, size, size), "REPORT",
                                self.report_target is not None, colour=(190, 50, 40), key="R")
        if self.is_imposter:
            kc = self.me_info.get("kc", 0)
            if self.alive:
                self._action_button(surf, "kill", pg.Rect(x0 - size - 12, y0, size, size), "KILL",
                                    self.kill_target is not None and kc <= 0, icon="UI/kill_icon.png",
                                    sub=str(math.ceil(kc)) if kc > 0 else None, key="Q")
                self._action_button(surf, "vent", pg.Rect(x0 - size - 12, y0 - size - 12, size, size),
                                    "VENT", self.vent_target is not None or self.vent is not None,
                                    colour=(90, 90, 110), key="V")
            sc = self.me_info.get("sc", 0)
            self._action_button(surf, "sabotage", pg.Rect(x0 - 2 * (size + 12), y0, size, size), "SABOTAGE",
                                sc <= 0 and self.sab is None, icon="UI/sabotage_icon.png",
                                sub=str(math.ceil(sc)) if sc > 0 else None, key="Tab")

    def _vent_ui(self, surf):
        cx, cy = self.camera()
        vx, vy = self.world.vents[self.vent]
        sx, sy = vx - cx, vy - cy
        for to in self.world.vent_links[self.vent]:
            tx, ty = self.world.vents[to]
            ang = math.atan2(ty - vy, tx - vx)
            ax, ay = sx + math.cos(ang) * 120, sy + math.sin(ang) * 120
            pts = [(ax + math.cos(ang) * 26, ay + math.sin(ang) * 26),
                   (ax + math.cos(ang + 2.5) * 22, ay + math.sin(ang + 2.5) * 22),
                   (ax + math.cos(ang - 2.5) * 22, ay + math.sin(ang - 2.5) * 22)]
            pg.draw.polygon(surf, (250, 60, 60), pts)
            pg.draw.polygon(surf, BLACK, pts, 3)
            self.buttons[f"ventto{to}"] = pg.Rect(ax - 30, ay - 30, 60, 60)
            draw_text(surf, self.assets, room_at(tx, ty), 14, (ax, ay + 30), WHITE, anchor="midtop")
        draw_text(surf, self.assets, "In vent: click an arrow (or A/D) to move, E to climb out", 18,
                  (SW // 2, SH - 40), WHITE, anchor="midbottom")
