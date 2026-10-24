"""Image/sound/font loading with caching. Missing audio never crashes the game."""
import os
import random

import pygame as pg

from ..config import ASSETS, COLOURS

IMG = os.path.join(ASSETS, "Images")
SND = os.path.join(ASSETS, "Sounds")
FONT_PATH = os.path.join(ASSETS, "Fonts", "Rubik-ExtraBold.ttf")

# sprite sheet layout written by tools/gen_colours.py
SHEET_CELL = (76, 97)
SHEET_ROWS = {"down": (0, 18), "up": (1, 17), "left": (2, 17), "right": (3, 17)}
PLAYER_SCALE = 0.85

SOUNDS = {
    "select": "UI/select.wav",
    "click": "UI/selected2.wav",
    "back": "UI/back2.wav",
    "key": "UI/keypress.wav",
    "map": "UI/map_btn_click.wav",
    "roundstart": "General/roundstart.wav",
    "alarm_meeting": "General/alarm_emergencymeeting.wav",
    "body_found": "General/report_Bodyfound.wav",
    "crisis": "General/crises.wav",
    "vent": "General/vent.wav",
    "vent_move": "General/swap.wav",
    "victory_crew": "General/victory_crew.wav",
    "victory_imposter": "General/victory_impostor.wav",
    "disconnect": "General/victory_disconnect.wav",
    "task_done": "General/task_complete.wav",
    "fill": "General/gas_can_fill.wav",
    "pickup": "General/pick_up_gas_can.wav",
    "kill": "Kill/imposter_kill.wav",
    "kill_denied": "Kill/imposter_kill_cooldown.wav",
    "killed": "Kill/imposter_kill_victim.wav",
    "vote_lock": "UI/votescreen_locking.wav",
    "vote_cast": "UI/votescreen_avote.wav",
    "laser": "Clear Asteroids/fire3.mp3",
    "explode": "Clear Asteroids/explosion2.mp3",
    "shock": "Electric Shock/AMB_Electricshock1.wav",
}
FOOTSTEPS = [f"Footsteps/Footstep0{i}.wav" for i in range(1, 9)]
AMBIENCE = {
    "Admin": "Ambience/AMB_Admin.wav", "Cafeteria": "Ambience/AMB_Cafeteria.wav",
    "Navigation": "Ambience/AMB_Cockpit.wav", "Communications": "Ambience/AMB_CommsRoom.wav",
    "MedBay": "Ambience/AMB_MedbayRoom.wav", "Electrical": "Ambience/AMB_ElectricRoom.wav",
    "Upper Engine": "Ambience/AMB_EngineRoom.wav", "Lower Engine": "Ambience/AMB_EngineRoom.wav",
    "Reactor": "Ambience/AMB_ReactorRoom.wav", "Security": "Ambience/AMB_SecurityRoom.wav",
    "Storage": "Ambience/AMB_Storage.wav", "O2": "Ambience/AMB_Oxygen.wav", "Weapons": "Ambience/AMB_Weapons.wav",
    "Shields": "Ambience/AMB_Launchpad.wav", "Hallway": "Ambience/AMB_Main.wav",
}
MENU_MUSIC = "Background/main_menu_music.mp3"


class Crewmate:
    """All frames for one colour, scaled for the world."""

    def __init__(self, sheet, scale=PLAYER_SCALE):
        cw, ch = SHEET_CELL
        size = (round(cw * scale), round(ch * scale))
        self.size = size
        self.walk = {}
        for d, (row, n) in SHEET_ROWS.items():
            self.walk[d] = [pg.transform.smoothscale(sheet.subsurface((i * cw, row * ch, cw, ch)), size)
                            for i in range(n)]
        extras_y = len(SHEET_ROWS) * ch
        self.ghost = {
            "left": pg.transform.smoothscale(sheet.subsurface((0, extras_y, cw, ch)), size),
            "right": pg.transform.smoothscale(sheet.subsurface((cw, extras_y, cw, ch)), size),
        }
        for g in self.ghost.values():
            g.set_alpha(150)
        self.dead = pg.transform.smoothscale(sheet.subsurface((2 * cw, extras_y, cw, ch)), size)
        self.icon_src = sheet.subsurface((0, 0, cw, ch))
        self._icons = {}

    def icon(self, size):
        if size not in self._icons:
            src = self.icon_src
            w, h = src.get_size()
            s = size / max(w, h)
            self._icons[size] = pg.transform.smoothscale(src, (round(w * s), round(h * s)))
        return self._icons[size]

    def big(self, height):
        key = ("big", height)
        if key not in self._icons:
            cw, ch = SHEET_CELL
            self._icons[key] = pg.transform.smoothscale(self.icon_src, (round(cw * height / ch), height))
        return self._icons[key]


class _NullSound:
    def play(self, *a, **k):
        return None

    def stop(self):
        pass

    def fadeout(self, ms):
        pass

    def set_volume(self, v):
        pass

    def get_length(self):
        return 0


class Assets:
    def __init__(self):
        self._img = {}
        self._fonts = {}
        self._snd = {}
        self._crew = {}
        self.audio = pg.mixer.get_init() is not None
        self.volume = 0.7

    # images ------------------------------------------------------------------
    def image(self, rel, size=None, alpha=True):
        key = (rel, size)
        if key not in self._img:
            path = os.path.join(IMG, rel) if not os.path.isabs(rel) else rel
            surf = pg.image.load(path)
            surf = surf.convert_alpha() if alpha else surf.convert()
            if size:
                surf = pg.transform.smoothscale(surf, size)
            self._img[key] = surf
        return self._img[key]

    def scaled(self, rel, scale):
        base = self.image(rel)
        w, h = base.get_size()
        return self.image(rel, (max(1, round(w * scale)), max(1, round(h * scale))))

    def crew(self, colour):
        if colour not in COLOURS:
            colour = "Red"
        if colour not in self._crew:
            sheet = pg.image.load(os.path.join(IMG, "Player", "Sheets", f"{colour}.png")).convert_alpha()
            self._crew[colour] = Crewmate(sheet)
        return self._crew[colour]

    # fonts -------------------------------------------------------------------
    def font(self, size):
        if size not in self._fonts:
            try:
                self._fonts[size] = pg.font.Font(FONT_PATH, size)
            except (OSError, FileNotFoundError):
                self._fonts[size] = pg.font.Font(None, int(size * 1.3))
        return self._fonts[size]

    # sounds ------------------------------------------------------------------
    def sound(self, name):
        if name not in self._snd:
            rel = SOUNDS.get(name) or AMBIENCE.get(name) or name
            snd = _NullSound()
            if self.audio:
                try:
                    snd = pg.mixer.Sound(os.path.join(SND, rel))
                except (pg.error, FileNotFoundError):
                    snd = _NullSound()
            self._snd[name] = snd
        return self._snd[name]

    def play(self, name, volume=1.0, loops=0):
        s = self.sound(name)
        s.set_volume(self.volume * volume)
        return s.play(loops=loops)

    def footstep(self):
        name = random.choice(FOOTSTEPS)
        s = self.sound(name)
        s.set_volume(self.volume * 0.35)
        s.play()

    def music(self, rel, volume=0.5):
        if not self.audio:
            return
        try:
            pg.mixer.music.load(os.path.join(SND, rel))
            pg.mixer.music.set_volume(self.volume * volume)
            pg.mixer.music.play(-1)
        except pg.error:
            pass

    def stop_music(self, fade_ms=500):
        if self.audio:
            pg.mixer.music.fadeout(fade_ms)
