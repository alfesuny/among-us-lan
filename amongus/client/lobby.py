"""Lobby: player list, colour picker, host settings, chat, start."""
import pygame as pg

from .. import config as C
from .app import H, W, Scene, save_prefs
from .ui import (CYAN, GREEN, GREY, PANEL, RED, WHITE, YELLOW, Button, ChatBox, Starfield, Stepper, Toggle,
                 draw_text, panel)

SETTING_ROWS = [
    # key, label, step, fmt
    ("imposters", "Impostors (0 = auto)", 1, "{}"),
    ("kill_cooldown", "Kill cooldown", 5, "{}s"),
    ("emergency_meetings", "Emergency meetings", 1, "{}"),
    ("emergency_cooldown", "Emergency cooldown", 5, "{}s"),
    ("discussion_time", "Discussion time", 5, "{}s"),
    ("voting_time", "Voting time", 15, "{}s"),
    ("confirm_ejects", "Confirm ejects", None, None),
    ("anonymous_votes", "Anonymous votes", None, None),
    ("common_tasks", "Common tasks", 1, "{}"),
    ("long_tasks", "Long tasks", 1, "{}"),
    ("short_tasks", "Short tasks", 1, "{}"),
    ("crew_vision", "Crewmate vision", 0.25, "{}x"),
    ("imposter_vision", "Impostor vision", 0.25, "{}x"),
    ("player_speed", "Player speed", 0.25, "{}x"),
]


class LobbyScene(Scene):
    stars = None

    def __init__(self, app, welcome=None, last_lobby=None):
        super().__init__(app)
        if LobbyScene.stars is None:
            LobbyScene.stars = Starfield(W, H, seed=9)
        self.me = app.my_id
        self.players = []
        self.host_id = None
        self.settings = dict(C.DEFAULT_SETTINGS)
        self.ips = []
        self.port = C.TCP_PORT
        self.server_name = ""
        self.phase = "lobby"
        self.spectating = welcome is not None and welcome.get("phase", "lobby") != "lobby"
        self.t = 0.0
        self.error = ""
        self.chat = ChatBox((30, 470, 560, 230), self.send_chat)
        self.colour_rects = []
        self.kick_rects = []
        self.setting_widgets = []
        self.start_btn = Button((W - 330, H - 82, 300, 62), "START", self.start, size=34, colour=(40, 140, 60))
        self.add_bot_btn = Button((620, H - 82, 150, 30), "+ ADD BOT", self.add_bot, size=16)
        self.rm_bot_btn = Button((620, H - 48, 150, 30), "- REMOVE BOT", self.remove_bot, size=16)
        self.leave_btn = Button((790, H - 82, 150, 62), "LEAVE", self.leave_game, size=24, colour=(120, 40, 40),
                                sound="back")
        self.buttons = [self.start_btn, self.add_bot_btn, self.rm_bot_btn, self.leave_btn]
        self._built_for = None
        if last_lobby:
            self.on_net(last_lobby)
        app.assets.music("Background/main_menu_music.mp3", 0.25)

    # ------------------------------------------------------------------ actions
    @property
    def is_host(self):
        return self.host_id == self.me

    def send(self, msg):
        if self.app.net:
            self.app.net.send(msg)

    def send_chat(self, text):
        self.send({"t": "chat", "text": text})

    def start(self):
        self.send({"t": "start"})

    def add_bot(self):
        if len(self.players) >= C.MAX_PLAYERS:
            self.app.toast("Lobby is full")
            return
        host = self.app.net.host if self.app.net else "127.0.0.1"
        self.app.add_bot(host, self.port)

    def remove_bot(self):
        self.app.remove_bot()

    def leave_game(self):
        from .menus import MainMenu
        self.app.disconnect()
        self.app.set_scene(MainMenu(self.app))

    def set_setting(self, key, value):
        self.send({"t": "settings", "settings": {key: value}})

    # ------------------------------------------------------------------ network
    def on_net(self, msg):
        t = msg["t"]
        if t == "lobby":
            self.players = msg["players"]
            self.host_id = msg["host"]
            self.settings = msg["settings"]
            self.ips = msg.get("ips", [])
            self.port = msg.get("port", C.TCP_PORT)
            self.server_name = msg.get("server_name", "")
            self.phase = msg["phase"]
            if self.phase == "lobby":
                self.spectating = False
            me = next((p for p in self.players if p["id"] == self.me), None)
            if me:
                self.app.prefs["colour"] = me["colour"]
            self._build_settings()
            self.app.last_lobby = msg
        elif t == "spectate":
            self.spectating = True
        elif t == "chat":
            rgb = C.COLOURS.get(msg["colour"], ((255, 255, 255), None))[0]
            self.chat.add(msg["name"], rgb, msg["text"], msg.get("dead", False))
            self.assets.play("key", 0.3)
        elif t == "game_start":
            from .game import GameScene
            save_prefs(self.app.prefs)
            self.app.set_scene(GameScene(self.app, msg))
        elif t == "error":
            self.app.toast(msg.get("msg", "Error"))
        elif t == "kicked":
            from .menus import MessageScene
            self.app.disconnect()
            self.app.set_scene(MessageScene(self.app, "Kicked", "The host removed you from the lobby."))

    def _build_settings(self):
        key = (self.is_host, tuple(sorted(self.settings.items())))
        if key == self._built_for:
            return
        self._built_for = key
        self.setting_widgets = []
        x, y, w = 870, 108, 380
        for k, label, step, fmt in SETTING_ROWS:
            v = self.settings.get(k, C.DEFAULT_SETTINGS[k])
            if step is None:
                wdg = Toggle((x, y, w, 26), label, bool(v), lambda val, k=k: self.set_setting(k, val),
                             enabled=self.is_host, size=17)
            else:
                lo, hi = C.SETTING_LIMITS[k]
                wdg = Stepper((x, y, w, 26), label, v, lo, hi, step, lambda val, k=k: self.set_setting(k, val),
                              fmt=fmt, enabled=self.is_host, size=17)
            self.setting_widgets.append(wdg)
            y += 30

    # ------------------------------------------------------------------ input
    def handle(self, e):
        if self.chat.handle(e):
            return True
        for b in self.buttons:
            if b.visible and b.handle(e):
                return True
        for wdg in self.setting_widgets:
            if wdg.handle(e):
                return True
        if e.type == pg.MOUSEBUTTONDOWN and e.button == 1:
            for rect, colour, free in self.colour_rects:
                if rect.collidepoint(e.pos) and free:
                    self.send({"t": "colour", "colour": colour})
                    self.assets.play("select", 0.6)
                    return True
            for rect, pid in self.kick_rects:
                if rect.collidepoint(e.pos):
                    self.send({"t": "kick", "id": pid})
                    return True
        if e.type == pg.KEYDOWN and e.key == pg.K_RETURN and not self.chat.input.focused:
            self.chat.input.focused = True
            return True
        return False

    def update(self, dt):
        self.t += dt
        self.app.start_preload()
        self.app.preload_tick([p["colour"] for p in self.players])
        LobbyScene.stars.update(dt)
        self.chat.update(dt)
        n = len(self.players)
        self.start_btn.visible = self.is_host
        self.start_btn.enabled = n >= C.MIN_PLAYERS_TO_START and self.phase == "lobby"
        self.add_bot_btn.visible = self.rm_bot_btn.visible = self.is_host
        self.add_bot_btn.enabled = n < C.MAX_PLAYERS
        self.rm_bot_btn.enabled = any(t.is_alive() for _, t in self.app.bots)

    # ------------------------------------------------------------------ drawing
    def draw(self, surf):
        LobbyScene.stars.draw(surf)
        a = self.assets
        draw_text(surf, a, "LOBBY", 40, (30, 14), WHITE)
        if self.server_name:
            draw_text(surf, a, self.server_name, 22, (190, 28), GREY)
        # join info: the most important thing for the host to share
        if self.ips:
            txt = "Others join with:  " + "   or   ".join(self.ips[:2])
            if self.port != C.TCP_PORT:
                txt += f"  (port {self.port})"
            r = draw_text(surf, a, txt, 22, (W - 30, 12), YELLOW, anchor="topright")
            draw_text(surf, a, "(or just pick this game from the JOIN list)", 13, (r.right, r.bottom), GREY,
                      anchor="topright")

        # players
        box = pg.Rect(30, 70, 560, 390)
        panel(surf, box, PANEL, alpha=225)
        draw_text(surf, a, f"Players  {len(self.players)}/{C.MAX_PLAYERS}", 24, (box.x + 18, box.y + 12), YELLOW)
        need = C.MIN_PLAYERS_TO_START - len(self.players)
        if need > 0:
            draw_text(surf, a, f"need {need} more to start", 16, (box.right - 18, box.y + 18), GREY, anchor="topright")
        self.kick_rects = []
        for i, p in enumerate(self.players):
            col, row = i % 2, i // 2
            r = pg.Rect(box.x + 14 + col * 272, box.y + 52 + row * 55, 262, 50)
            panel(surf, r, (60, 66, 92) if p["id"] != self.me else (70, 90, 70), radius=8, width=2)
            surf.blit(a.crew(p["colour"]).icon(42), (r.x + 6, r.y + 4))
            name = p["name"] + ("  (you)" if p["id"] == self.me else "")
            draw_text(surf, a, name, 18, (r.x + 54, r.y + 8), WHITE)
            tag = "HOST" if p.get("host") else ("in game" if p.get("in_game") else "")
            if tag:
                draw_text(surf, a, tag, 13, (r.x + 54, r.y + 30), YELLOW if tag == "HOST" else GREY)
            if self.is_host and p["id"] != self.me:
                k = pg.Rect(r.right - 30, r.y + 12, 24, 24)
                pg.draw.rect(surf, (150, 40, 40), k, border_radius=5)
                draw_text(surf, a, "x", 16, k.center, WHITE, anchor="center")
                self.kick_rects.append((k, p["id"]))

        # colours
        cbox = pg.Rect(605, 70, 245, 390)
        panel(surf, cbox, PANEL, alpha=225)
        draw_text(surf, a, "Colour", 24, (cbox.x + 16, cbox.y + 12), YELLOW)
        taken = {p["colour"]: p["id"] for p in self.players}
        my_colour = next((p["colour"] for p in self.players if p["id"] == self.me), None)
        self.colour_rects = []
        for i, colour in enumerate(C.COLOUR_NAMES):
            r = pg.Rect(cbox.x + 16 + (i % 3) * 74, cbox.y + 52 + (i // 3) * 76, 66, 70)
            mine = colour == my_colour
            free = colour not in taken
            pg.draw.rect(surf, (255, 255, 255) if mine else (70, 76, 100), r, 3 if mine else 1, border_radius=8)
            img = a.crew(colour).icon(56)
            if not free and not mine:
                img = img.copy()
                img.set_alpha(70)
            surf.blit(img, img.get_rect(center=r.center))
            self.colour_rects.append((r, colour, free))

        # settings
        sbox = pg.Rect(860, 70, 400, 470)
        panel(surf, sbox, PANEL, alpha=225)
        draw_text(surf, a, "Game settings" + ("" if self.is_host else " (host decides)"), 22,
                  (sbox.x + 14, sbox.y + 10), YELLOW)
        for wdg in self.setting_widgets:
            wdg.draw(surf, a)

        self.chat.draw(surf, a)
        for b in self.buttons:
            b.draw(surf, a)
        if not self.is_host:
            host = next((p["name"] for p in self.players if p.get("host")), "the host")
            draw_text(surf, a, f"Waiting for {host} to start...", 24, (W - 30, H - 50), WHITE, anchor="midright")
        elif not self.start_btn.enabled:
            draw_text(surf, a, f"Need {C.MIN_PLAYERS_TO_START}+ players (add bots to test)", 16,
                      (W - 180, H - 96), GREY, anchor="midbottom")
        if self.spectating:
            r = pg.Rect(0, 0, 760, 70)
            r.center = (W // 2, H // 2)
            panel(surf, r, (90, 30, 30), alpha=235)
            draw_text(surf, a, "A game is in progress - you'll join the next round", 22, r.center, WHITE,
                      anchor="center")
