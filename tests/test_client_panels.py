"""Every task panel, sabotage fix, utility and overlay — solved/rendered offline with synthetic input.

    python -m unittest tests.test_client_panels        (screenshots -> tests/_shots/panels)
"""
import os
import sys
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import pygame as pg  # noqa: E402

from amongus import config as C  # noqa: E402
from amongus.client import minigames as MG  # noqa: E402
from amongus.client import overlays as OV  # noqa: E402
from amongus.client.game import GameScene  # noqa: E402
from amongus.world import STATIONS, get_world  # noqa: E402
from client_e2e import Driver, solve  # noqa: E402

SHOTS = os.environ.get("PANEL_SHOTS", os.path.join(ROOT, "tests", "_shots", "panels"))

_driver = None


def driver():
    global _driver
    if _driver is None:
        os.makedirs(SHOTS, exist_ok=True)
        _driver = Driver()
    return _driver


def make_scene(role="crew"):
    d = driver()
    app = d.app
    app.my_id = 1
    players = [{"id": i, "name": f"P{i}", "colour": c} for i, c in enumerate(C.COLOUR_NAMES[:8], start=1)]
    x, y = get_world().spawns[0]
    msg = {"t": "game_start", "round": 1, "role": role, "imposters": [1, 2] if role == "imposter" else [],
           "n_imposters": 2, "players": players, "x": x, "y": y, "ep": 0, "settings": dict(C.DEFAULT_SETTINGS),
           "tasks": [{"id": "wiring", "name": "Fix Wiring", "steps": [["wires_admin", "wiring"]], "step": 0}]}
    scene = GameScene(app, msg)
    app.set_scene(scene)
    scene.net_play({})
    others = {"pl": [[p["id"], x + 60 * i, y, 0, 0, 1, -1] for i, p in enumerate(players)],
              "ph": "play", "bd": [[8, x + 120, y + 40, "Lime"]], "sab": None, "tb": 0.4,
              "me": {"kc": 0, "sc": 0, "em": 1, "ec": 0, "v": None, "ep": 0}}
    scene.on_net(dict(others, t="snap"))
    d.step(n=3)
    return scene


class Panels(unittest.TestCase):
    def run_panel(self, scene, mg, name):
        d = driver()
        hits = []
        mg.on_success = lambda: hits.append(1)
        scene.minigame = mg
        d.step(n=3)
        pg.image.save(d.app.screen, os.path.join(SHOTS, f"panel_{name}.png"))
        solve(d, mg)
        d.step(n=5)
        self.assertTrue(mg.done, f"{name} not solved")
        self.assertEqual(hits, [1], f"{name} must report success exactly once")
        d.step(n=90)
        self.assertIsNone(scene.minigame, f"{name} panel should close after success")

    def test_all_task_panels(self):
        scene = make_scene()
        for name, factory in MG.MINIGAMES.items():
            with self.subTest(panel=name):
                self.run_panel(scene, factory(scene, colour="Red", name="Tester"), name)

    def test_sabotage_fix_panels(self):
        scene = make_scene()
        for kind in ("lights", "comms", "o2"):
            with self.subTest(fix=kind):
                scene.sab = {"k": kind, "rem": 30, "done": [], "held": []}
                self.run_panel(scene, MG.FIXES[kind](scene), "fix_" + kind)
        scene.sab = None

    def test_reactor_scanner_sends_hold_and_release(self):
        scene = make_scene()
        d = driver()
        scene.sab = {"k": "reactor", "rem": 30, "done": [], "held": []}
        sent = []
        mg = MG.ReactorScanner(scene, panel_id="fix_reactor_a", send_hold=lambda p, on: sent.append((p, on)))
        scene.minigame = mg
        d.step(n=2)
        d.step([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=mg.pad.center)], n=20)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "panel_fix_reactor.png"))
        d.step([pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=mg.pad.center)])
        self.assertEqual(sent, [("fix_reactor_a", True), ("fix_reactor_a", False)])
        d.step([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=mg.pad.center)])
        d.key(pg.K_ESCAPE)  # closing while holding must release
        self.assertEqual(sent[-1], ("fix_reactor_a", False))
        scene.sab = None

    def test_wrong_inputs_do_not_complete(self):
        scene = make_scene()
        d = driver()
        w = MG.Wiring(scene)
        scene.minigame = w
        wrong = next(j for j, c in enumerate(w.right) if c != w.left[0])
        d.drag(w.left_pts[0], w.right_pts[wrong])
        self.assertEqual(w.connected, {})
        s = MG.Swipe(scene)
        scene.minigame = s
        d.click(s.card_rect.center)
        c = s.card_rect.center
        d.drag(c, (c[0] + 300, c[1]), steps=4)  # far too fast
        self.assertFalse(s.done)
        self.assertIn("fast", s.msg)
        k = MG.O2Keypad(scene)
        scene.minigame = k
        wrong_code = "".join("1" if ch != "1" else "2" for ch in k.code)
        for ch in wrong_code:
            d.click(k.keys[ch])
        d.click(k.keys["OK"])
        self.assertFalse(k.done)
        self.assertEqual(k.typed, "")
        scene.minigame = None

    def test_utilities_and_emergency(self):
        scene = make_scene()
        d = driver()
        for name, mg in (("admin", MG.MapView(scene)), ("cams", MG.Cameras(scene))):
            scene.minigame = mg
            d.step(n=3)
            pg.image.save(d.app.screen, os.path.join(SHOTS, f"util_{name}.png"))
            d.key(pg.K_ESCAPE)
            self.assertIsNone(scene.minigame)
        called = []
        scene.minigame = MG.EmergencyPanel(scene, call=lambda: called.append(1))
        d.step(n=2)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "util_emergency.png"))
        d.click(scene.minigame.button.center)
        self.assertEqual(called, [1])

    def test_imposter_hud_map_and_vent(self):
        scene = make_scene("imposter")
        d = driver()
        d.step(n=3)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "hud_imposter.png"))
        self.assertIsNotNone(scene.kill_target, "a crewmate stands next to us: kill target expected")
        self.assertIn("kill", scene.buttons)
        self.assertIn("sabotage", scene.buttons)
        sent = []
        d.app.net = type("N", (), {"send": lambda self, m: sent.append(m), "rtt": None, "host": "x",
                                   "keepalive": lambda self: None, "poll": lambda self: [], "close": lambda self: None})()
        d.key(pg.K_q)
        self.assertEqual(sent[-1]["t"], "kill")
        d.click(scene.buttons["sabotage"].center)
        self.assertIsNotNone(scene.map_overlay)
        d.step(n=2)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "sabotage_map.png"))
        d.click(scene.map_overlay.sab_buttons["reactor"].center)
        self.assertEqual(sent[-1], {"t": "sabotage", "kind": "reactor"})
        scene.on_net({"t": "vent_state", "id": 3})
        self.assertEqual((scene.x, scene.y), tuple(map(float, get_world().vents[3])), "camera must follow into vent")
        d.step(n=2)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "in_vent.png"))
        d.key(pg.K_d)
        self.assertEqual(sent[-1]["act"], "move")
        self.assertIn(sent[-1]["to"], get_world().vent_links[3])
        d.app.net = None

    def test_sabotage_visuals_and_ghost(self):
        scene = make_scene()
        d = driver()
        for kind in ("lights", "reactor", "comms"):
            scene.on_net({"t": "sabotage", "kind": kind, "dur": 40 if kind == "reactor" else None})
            d.step(n=5)
            pg.image.save(d.app.screen, os.path.join(SHOTS, f"sabotage_{kind}.png"))
            scene.on_net({"t": "sabotage_end", "kind": kind})
        self.assertIsNone(scene.alarm)
        scene.on_net({"t": "killed", "by": "Red"})
        d.step(n=20)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "killed.png"))
        d.step(n=200)
        self.assertIsNone(scene.kill_anim)
        self.assertFalse(scene.alive)
        scene.input_override = (0, -1)
        y0 = scene.y
        d.step(n=60)
        self.assertLess(scene.y, y0 - 100, "ghosts float through walls")
        scene.input_override = None
        pg.image.save(d.app.screen, os.path.join(SHOTS, "ghost.png"))

    def test_overlays_render(self):
        scene = make_scene()
        d = driver()
        roster = [dict(p, alive=(p["id"] != 3)) for p in scene.roster.values()]
        scene.on_net({"t": "meeting", "kind": "report", "caller": 2, "caller_colour": "Blue", "body": "Orange",
                      "intro": 3, "discussion": 5, "voting": 30, "players": roster, "anonymous": False})
        d.step(n=40)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "meeting_intro.png"))
        scene.on_net({"t": "meeting_stage", "stage": "vote", "dur": 30})
        for pid in (2, 4, 5):
            scene.on_net({"t": "voted", "id": pid})
        d.step(n=5)
        m = scene.meeting
        d.click(m.cards[4].center)
        d.step(n=2)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "meeting_vote_confirm.png"))
        scene.on_net({"t": "vote_result", "votes": {"4": [1, 2, 5], "6": [7]}, "skip": [8], "ejected": 4, "tie": False})
        d.step(n=5)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "meeting_results.png"))
        scene.on_net({"t": "eject", "id": 4, "name": "P4", "colour": "Pink", "was_imposter": True, "remaining": 1})
        d.step(n=200)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "eject.png"))
        scene.on_net({"t": "resume"})
        players = [dict(p, role="imposter" if p["id"] in (2, 5) else "crew", alive=True) for p in scene.roster.values()]
        scene.on_net({"t": "game_over", "winner": "crew", "reason": "All tasks completed",
                      "imposters": [p for p in players if p["role"] == "imposter"], "players": players})
        d.step(n=10)
        pg.image.save(d.app.screen, os.path.join(SHOTS, "game_over_victory.png"))
        for role in ("crew", "imposter"):
            s2 = make_scene(role)
            s2.overlay = OV.RoleReveal(s2, role, [s2.roster[2]] if role == "imposter" else [], 2)
            d.step(n=100)
            pg.image.save(d.app.screen, os.path.join(SHOTS, f"reveal_{role}.png"))


if __name__ == "__main__":
    unittest.main()
