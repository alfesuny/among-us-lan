"""Full-screen overlays: role reveal, meeting/voting, ejection, game over, kill animation."""
import math

import pygame as pg

from .. import config as C
from .ui import BLACK, CYAN, GREEN, GREY, RED, WHITE, YELLOW, draw_text, panel

SW, SH = 1280, 720


def _stripes(surf, colour_a, colour_b, t, width=60):
    surf.fill(colour_a)
    off = int(t * 120) % (width * 2)
    for x in range(-SH - width * 2, SW + width * 2, width * 2):
        pts = [(x + off, 0), (x + off + width, 0), (x + off + width + SH, SH), (x + off + SH, SH)]
        pg.draw.polygon(surf, colour_b, pts)


class RoleReveal:
    def __init__(self, scene, role, partners, n_imposters):
        self.scene = scene
        self.assets = scene.assets
        self.role = role
        self.partners = partners
        self.n = n_imposters
        self.t = 0.0
        self.closed = False
        self.assets.play("roundstart", 0.7)

    def update(self, dt):
        self.t += dt

    def handle(self, e):
        return False

    def draw(self, surf):
        a = self.assets
        surf.fill(BLACK)
        if self.role == "imposter" and self.t < 1.3:
            img = a.image("Meeting/shhhhhhh.png", (SW, SH), alpha=False)
            surf.blit(img, (0, 0))
            return
        glow = pg.Surface((SW, 360), pg.SRCALPHA)
        col = (200, 30, 30) if self.role == "imposter" else (40, 140, 220)
        for i in range(18):
            pg.draw.ellipse(glow, (*col, 10), pg.Rect(SW // 2 - 600 + i * 20, 40 + i * 6, 1200 - i * 40, 300 - i * 12))
        surf.blit(glow, (0, 300))
        title = "Impostor" if self.role == "imposter" else "Crewmate"
        draw_text(surf, a, title, 96, (SW // 2, 70), RED if self.role == "imposter" else CYAN, anchor="midtop",
                  width=4)
        if self.role == "imposter":
            sub = "Kill the crew. Don't get caught." if not self.partners else \
                "Your fellow Impostor: " + ", ".join(p["name"] for p in self.partners)
        else:
            sub = f"There {'is' if self.n == 1 else 'are'} {self.n} Impostor{'s' if self.n != 1 else ''} among us"
        draw_text(surf, a, sub, 30, (SW // 2, 200), WHITE, anchor="midtop")
        people = [{"colour": self.scene.my_colour, "name": self.scene.my_name}] + self.partners
        if self.role != "imposter":
            people = [{"colour": self.scene.my_colour, "name": self.scene.my_name}] + [
                p for p in self.scene.roster.values() if p["id"] != self.scene.me][:6]
        for i, p in enumerate(people):
            big = 220 if i == 0 else 150
            # me in the centre, everyone else alternating right/left
            x = SW // 2 if i == 0 else SW // 2 + ((i + 1) // 2) * 170 * (1 if i % 2 else -1)
            img = a.crew(p["colour"]).big(big)
            surf.blit(img, img.get_rect(midbottom=(x, 600)))
            draw_text(surf, a, p["name"], 22, (x, 610), RED if self.role == "imposter" else WHITE, anchor="midtop")


class MeetingOverlay:
    def __init__(self, scene, msg):
        self.scene = scene
        self.assets = scene.assets
        self.kind = msg["kind"]
        self.caller = msg["caller"]
        self.caller_colour = msg["caller_colour"]
        self.body = msg.get("body")
        self.players = msg["players"]
        self.anonymous = msg.get("anonymous", False)
        self.stage = "intro"
        self.stage_left = msg["intro"]
        self.voted = set()
        self.my_vote = None
        self.selected = None
        self.results = None
        self.t = 0.0
        self.closed = False
        self.tablet = pg.Rect(40, 24, SW - 80, SH - 48)
        self.cards = {}
        for i, p in enumerate(self.players):
            col, row = i % 2, i // 2
            self.cards[p["id"]] = pg.Rect(self.tablet.x + 30 + col * 375, self.tablet.y + 80 + row * 78, 360, 68)
        self.skip_rect = pg.Rect(self.tablet.x + 30, self.tablet.bottom - 70, 164, 40)
        self.confirm_rect = None
        self.cancel_rect = None
        self.scene.chat.rect = pg.Rect(self.tablet.x + 790, self.tablet.y + 70, 380, self.tablet.h - 100)
        self.scene.chat.input.rect = pg.Rect(self.scene.chat.rect.x, self.scene.chat.rect.bottom - 40,
                                             self.scene.chat.rect.w, 40)
        snd = "body_found" if self.kind == "report" else "alarm_meeting"
        self.assets.play(snd, 0.8)

    @property
    def me_alive(self):
        return self.scene.alive

    def set_stage(self, stage, dur):
        self.stage = stage
        self.stage_left = dur
        self.selected = None
        if stage == "vote":
            self.assets.play("vote_lock", 0.4)

    def on_voted(self, pid):
        self.voted.add(pid)
        self.assets.play("vote_cast", 0.5)

    def on_result(self, msg):
        self.results = msg
        self.stage = "results"
        self.stage_left = C.VOTE_RESULTS_SECONDS
        self.selected = None

    def update(self, dt):
        self.t += dt
        self.stage_left = max(0.0, self.stage_left - dt)
        self.scene.chat.update(dt)

    def can_vote(self):
        return self.stage == "vote" and self.me_alive and self.my_vote is None

    def handle(self, e):
        if self.stage == "intro":
            return True
        if self.scene.chat.handle(e):
            return True
        if e.type == pg.KEYDOWN and e.key in (pg.K_RETURN, pg.K_KP_ENTER):
            self.scene.chat.input.focused = True
            return True
        if e.type != pg.MOUSEBUTTONDOWN or e.button != 1:
            return True
        if self.selected is not None and self.confirm_rect and self.confirm_rect.collidepoint(e.pos):
            self.cast(self.selected)
            return True
        if self.selected is not None and self.cancel_rect and self.cancel_rect.collidepoint(e.pos):
            self.selected = None
            return True
        if not self.can_vote():
            return True
        if self.skip_rect.collidepoint(e.pos):
            self.selected = "skip"
            return True
        for p in self.players:
            if self.cards[p["id"]].collidepoint(e.pos) and p.get("alive"):
                self.selected = p["id"]
                self.assets.play("select", 0.4)
                return True
        return True

    def cast(self, target):
        if not self.can_vote():
            return
        self.my_vote = target
        self.selected = None
        self.scene.send({"t": "vote", "target": target})

    # ------------------------------------------------------------------ drawing
    def draw(self, surf):
        a = self.assets
        if self.stage == "intro":
            self.draw_intro(surf)
            return
        surf.fill((10, 14, 30))
        panel(surf, self.tablet, (176, 196, 222), border=(40, 50, 70), radius=22, width=8)
        draw_text(surf, a, "Who Is The Impostor?", 34, (self.tablet.x + 380, self.tablet.y + 18), WHITE,
                  anchor="midtop", width=3)
        if not self.me_alive:
            draw_text(surf, a, "You are dead - only ghosts can see your messages", 16,
                      (self.tablet.x + 380, self.tablet.y + 58), (90, 40, 40), anchor="midtop", outline=None)
        results = self.results
        votes = {}
        skip = []
        if results:
            votes = {int(k): v for k, v in results["votes"].items()}
            skip = results["skip"]
        self.confirm_rect = self.cancel_rect = None
        for p in self.players:
            r = self.cards[p["id"]]
            alive = p.get("alive")
            hover = r.collidepoint(pg.mouse.get_pos()) and self.can_vote() and alive
            base = (240, 244, 250) if alive else (150, 156, 168)
            if hover:
                base = (255, 255, 220)
            panel(surf, r, base, border=(50, 60, 80), radius=10, width=3)
            icon = a.crew(p["colour"]).icon(52)
            surf.blit(icon, (r.x + 8, r.y + 7))
            if not alive:
                pg.draw.line(surf, RED, (r.x + 10, r.y + 10), (r.x + 56, r.y + 58), 6)
                pg.draw.line(surf, RED, (r.x + 56, r.y + 10), (r.x + 10, r.y + 58), 6)
            name_col = (30, 30, 40)
            if self.scene.is_imposter and p["id"] in self.scene.imposters:
                name_col = (200, 20, 20)
            draw_text(surf, a, p["name"], 22, (r.x + 72, r.y + 8), name_col, outline=None)
            if p["id"] == self.caller:
                draw_text(surf, a, "called meeting" if self.kind == "emergency" else "reported body", 13,
                          (r.x + 72, r.y + 40), (120, 70, 20), outline=None)
            if p["id"] in self.voted and not results:
                sticker = a.image("Meeting/voted_players.PNG")
                surf.blit(sticker, sticker.get_rect(midright=(r.right - 8, r.centery)))
            if results:
                vs = votes.get(p["id"], [])
                self._draw_votes(surf, vs, r.x + 72, r.y + 40)
            if self.selected == p["id"]:
                self._draw_confirm(surf, r)
            if self.my_vote == p["id"]:
                pg.draw.rect(surf, GREEN, r, 4, border_radius=10)
        # skip
        skip_img = a.image("Meeting/skip_vote.png", (self.skip_rect.w, self.skip_rect.h))
        if self.can_vote() or self.my_vote == "skip":
            surf.blit(skip_img, self.skip_rect)
        else:
            dim = skip_img.copy()
            dim.set_alpha(110)
            surf.blit(dim, self.skip_rect)
        if self.selected == "skip":
            self._draw_confirm(surf, self.skip_rect.inflate(140, 20).move(70, 0))
        if results:
            draw_text(surf, a, "Skipped:", 18, (self.skip_rect.right + 14, self.skip_rect.y + 8), (30, 30, 40),
                      outline=None)
            self._draw_votes(surf, skip, self.skip_rect.right + 100, self.skip_rect.y + 6)
        # timer
        if self.stage == "discussion":
            txt = f"Voting begins in: {math.ceil(self.stage_left)}s"
        elif self.stage == "vote":
            txt = f"Voting ends in: {math.ceil(self.stage_left)}s"
            if not self.me_alive:
                txt += "   (ghosts can't vote)"
            elif self.my_vote is None:
                txt += "   - click a player to vote"
        else:
            txt = f"Proceeding in: {math.ceil(self.stage_left)}s"
        draw_text(surf, a, txt, 22, (self.tablet.x + 760, self.tablet.bottom - 52), (30, 30, 40), anchor="topright",
                  outline=None)
        draw_text(surf, a, "Chat", 22, (self.scene.chat.rect.x, self.tablet.y + 30), (30, 30, 40), outline=None)
        self.scene.chat.draw(surf, a)
        if self.stage == "discussion" and self.t < MEETING_SPLASH_END:
            splash = a.image("Meeting/chat.png" if self.me_alive else "Meeting/chat_dead.png", (380, 380))
            s = splash.copy()
            s.set_alpha(int(255 * max(0.0, min(1.0, (MEETING_SPLASH_END - self.t) * 2))))
            surf.blit(s, s.get_rect(center=(SW // 2, SH // 2)))

    def _draw_votes(self, surf, voters, x, y):
        if isinstance(voters, int):  # anonymous: just a count
            for k in range(voters):
                pg.draw.circle(surf, (90, 90, 100), (x + 11 + k * 24, y + 11), 10)
            return
        for k, vid in enumerate(voters):
            colour = self.scene.roster.get(vid, {}).get("colour", "Red")
            surf.blit(self.assets.crew(colour).icon(22), (x + k * 24, y))

    def _draw_confirm(self, surf, r):
        self.confirm_rect = pg.Rect(r.right - 92, r.centery - 20, 40, 40)
        self.cancel_rect = pg.Rect(r.right - 46, r.centery - 20, 40, 40)
        surf.blit(self.assets.image("Meeting/select_vote.png", (40, 40)), self.confirm_rect)
        surf.blit(self.assets.image("Meeting/close.PNG", (40, 40)), self.cancel_rect)

    def draw_intro(self, surf):
        a = self.assets
        _stripes(surf, (120, 10, 10), (150, 25, 25), self.t)
        title = "EMERGENCY MEETING!" if self.kind == "emergency" else "DEAD BODY REPORTED"
        scale = min(1.0, self.t * 4)
        draw_text(surf, a, title, int(30 + 50 * scale), (SW // 2, 120), WHITE, anchor="midtop", width=4)
        img = a.crew(self.caller_colour).big(240)
        surf.blit(img, img.get_rect(midbottom=(SW // 2 - (120 if self.body else 0), 560)))
        if self.body:
            dead = pg.transform.smoothscale(a.crew(self.body).dead, (180, 230))
            surf.blit(dead, dead.get_rect(midbottom=(SW // 2 + 160, 560)))
        caller = self.scene.roster.get(self.caller, {}).get("name", "")
        draw_text(surf, a, f"called by {caller}", 26, (SW // 2, 600), WHITE, anchor="midtop")


MEETING_SPLASH_END = 1.4  # seconds into the discussion screen during which "Discuss!" shows


class EjectOverlay:
    def __init__(self, scene, msg, tie=False):
        self.scene = scene
        self.assets = scene.assets
        self.msg = msg
        self.t = 0.0
        self.closed = False
        if msg.get("id") is None:
            self.lines = ["No one was ejected. (Tie)" if tie else "No one was ejected. (Skipped)"]
        else:
            name = msg["name"]
            if "was_imposter" in msg:
                self.lines = [f"{name} was {'' if msg['was_imposter'] else 'not '}The Impostor."]
            else:
                self.lines = [f"{name} was ejected."]
        if "remaining" in msg:
            n = msg["remaining"]
            self.lines.append(f"{n} Impostor{'s' if n != 1 else ''} remain{'s' if n == 1 else ''}.")

    def handle(self, e):
        return True

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        a = self.assets
        bg = a.image("Alerts/eject.png", (SW, SH), alpha=False)
        off = int(self.t * 60) % SW
        surf.blit(bg, (-off, 0))
        surf.blit(bg, (SW - off, 0))
        if self.msg.get("colour"):
            x = -100 + self.t * 260
            img = pg.transform.rotate(a.crew(self.msg["colour"]).big(130), -self.t * 160)
            surf.blit(img, img.get_rect(center=(x, SH // 2 - 40)))
        full = self.lines[0]
        shown = full[:int(max(0.0, self.t - 0.6) * 22)]
        draw_text(surf, a, shown, 40, (SW // 2, SH // 2 + 110), WHITE, anchor="midtop", width=3)
        if len(self.lines) > 1 and self.t > 0.6 + len(full) / 22 + 0.4:
            draw_text(surf, a, self.lines[1], 28, (SW // 2, SH // 2 + 170), GREY, anchor="midtop")


class GameOverOverlay:
    def __init__(self, scene, msg):
        self.scene = scene
        self.assets = scene.assets
        self.msg = msg
        self.t = 0.0
        self.closed = False
        my_team = "imposter" if scene.is_imposter else "crew"
        self.won = msg["winner"] == my_team
        self.assets.play("victory_crew" if msg["winner"] == "crew" else "victory_imposter", 0.8)
        if msg["winner"] == "crew":
            self.winners = [p for p in msg["players"] if p["role"] == "crew"]
        else:
            self.winners = [p for p in msg["players"] if p["role"] == "imposter"]

    def handle(self, e):
        return True

    def update(self, dt):
        self.t += dt

    def draw(self, surf):
        a = self.assets
        surf.fill(BLACK)
        crew_won = self.msg["winner"] == "crew"
        glow_col = (40, 120, 255) if crew_won else (230, 20, 20)
        glow = pg.Surface((SW, 420), pg.SRCALPHA)
        for i in range(20):
            pg.draw.ellipse(glow, (*glow_col, 12), pg.Rect(SW // 2 - 640 + i * 22, 30 + i * 8, 1280 - i * 44, 360 - i * 16))
        surf.blit(glow, (0, 250))
        draw_text(surf, a, "Victory" if self.won else "Defeat", 96, (SW // 2, 40),
                  (90, 180, 255) if self.won else RED, anchor="midtop", width=4)
        draw_text(surf, a, "Crewmates win" if crew_won else "Impostors win", 32, (SW // 2, 170), WHITE,
                  anchor="midtop")
        n = len(self.winners)
        for i, p in enumerate(self.winners):
            x = SW // 2 + (i - (n - 1) / 2) * min(150, 1100 / max(1, n))
            img = a.crew(p["colour"]).big(150)
            if not p.get("alive"):
                img = img.copy()
                img.set_alpha(120)
            surf.blit(img, img.get_rect(midbottom=(x, 560)))
            draw_text(surf, a, p["name"], 20, (x, 566), WHITE, anchor="midtop")
        draw_text(surf, a, self.msg.get("reason", ""), 28, (SW // 2, 640), WHITE, anchor="midtop")
        imps = ", ".join(p["name"] for p in self.msg.get("imposters", []))
        draw_text(surf, a, f"Impostor{'s' if len(self.msg.get('imposters', [])) != 1 else ''}: {imps}", 20,
                  (SW // 2, 680), (255, 140, 140), anchor="midtop")


class KillAnimation:
    FPS = 15

    def __init__(self, scene, killer_colour):
        self.scene = scene
        self.assets = scene.assets
        self.killer = killer_colour
        self.t = 0.0
        self.closed = False
        self.frames = [self.assets.image(f"Alerts/kill{i}.png") for i in range(1, 19)]
        self.assets.play("killed", 0.8)

    def handle(self, e):
        return True

    def update(self, dt):
        self.t += dt
        if self.t > len(self.frames) / self.FPS + 1.8:
            self.closed = True

    def draw(self, surf):
        surf.fill(BLACK)
        i = min(len(self.frames) - 1, int(self.t * self.FPS))
        img = self.frames[i]
        surf.blit(img, img.get_rect(center=(SW // 2, SH // 2)))
        if self.t > len(self.frames) / self.FPS:
            draw_text(surf, self.assets, "You were killed!", 44, (SW // 2, 60), RED, anchor="midtop", width=3)
            draw_text(surf, self.assets, "You are now a ghost: keep doing your tasks to help the crew.", 22,
                      (SW // 2, SH - 70), WHITE, anchor="midtop")
