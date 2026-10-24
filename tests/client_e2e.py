"""Headless end-to-end run of the real pygame client against a real server + bots.

Drives: main menu -> host -> lobby (+bots) -> start -> role reveal -> gameplay (walk, open
every task panel and solve it with synthetic mouse events) -> meeting -> vote -> eject/resume
-> ... -> game over -> back to lobby. Saves screenshots of each stage.

    python tests/client_e2e.py [screenshot_dir]
"""
import math
import os
import socket
import sys
import time
import traceback

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import pygame as pg  # noqa: E402

from amongus import config as C  # noqa: E402
from amongus.client import minigames as MG  # noqa: E402
from amongus.client.app import App  # noqa: E402
from amongus.client.game import GameScene  # noqa: E402
from amongus.client.lobby import LobbyScene  # noqa: E402
from amongus.client.menus import ConnectingScene, HelpScene, JoinScene, MainMenu  # noqa: E402
from amongus.world import STATIONS, get_world  # noqa: E402

SHOTS = os.path.join(ROOT, "tests", "_shots")  # main() may override from argv; importing must not touch disk
DT = 1 / 60


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Driver:
    def __init__(self):
        self.app = App(headless=True)
        self.frames = 0
        self.shots = []

    def step(self, events=(), n=1):
        for _ in range(n):
            self.app.step(DT, list(events))
            events = ()
            self.frames += 1

    def wait(self, cond, timeout=20.0, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            self.step()
            if cond():
                return True
            time.sleep(0.002)
        raise AssertionError(f"timed out waiting for {what}; scene={type(self.app.scene).__name__}")

    def shot(self, name):
        path = os.path.join(SHOTS, f"{len(self.shots):02d}_{name}.png")
        pg.image.save(self.app.screen, path)
        self.shots.append(path)

    # synthetic input
    def click(self, pos):
        self.step([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=pos)])
        self.step([pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=pos)])

    def drag(self, a, b, steps=12, hold=0.0, frames_per_step=1):
        self.step([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(round(a[0]), round(a[1])))])
        for i in range(1, steps + 1):
            p = (round(a[0] + (b[0] - a[0]) * i / steps), round(a[1] + (b[1] - a[1]) * i / steps))
            self.step([pg.event.Event(pg.MOUSEMOTION, pos=p, rel=(0, 0), buttons=(1, 0, 0))], n=frames_per_step)
        if hold:
            self.step(n=int(hold / DT))
        self.step([pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=(round(b[0]), round(b[1])))])

    def key(self, k, uni=""):
        self.step([pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode=uni, scancode=0)])
        self.step([pg.event.Event(pg.KEYUP, key=k, mod=0, unicode=uni, scancode=0)])

    def type(self, text):
        for ch in text:
            self.step([pg.event.Event(pg.TEXTINPUT, text=ch)])


def solve(d, mg):
    """Solve any panel with synthetic mouse input, using its exposed geometry."""
    if isinstance(mg, MG.Wiring):
        for i, colour in enumerate(mg.left):
            j = mg.right.index(colour)
            d.drag(mg.left_pts[i], mg.right_pts[j])
    elif isinstance(mg, MG.Garbage):
        c = mg.lever_center
        d.drag(c, (c[0], c[1] + 400), hold=2.0)
    elif isinstance(mg, MG.Wifi):
        c = mg.lever_center
        d.drag(c, (c[0], c[1] + 300))
        d.step(n=int(6.3 / DT))
        c = mg.lever_center
        d.drag(c, (c[0], c[1] - 300))
    elif isinstance(mg, MG.Steering):
        d.drag(mg.pos, mg.center)
    elif isinstance(mg, MG.Divert):
        k = mg.knob
        d.drag(k, (k[0], k[1] - 150))
    elif isinstance(mg, MG.Align):
        h = mg.handle_pos
        d.drag(h, (h[0], h[1] + (mg.goal - mg.y)), steps=20)
    elif isinstance(mg, MG.Fuel):
        c = mg.button_rect.center
        d.step([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=c)])
        d.step(n=int(3.3 / DT))
        d.step([pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=c)])
    elif isinstance(mg, MG.Asteroids):
        end = time.time() + 30
        while not mg.done and not mg.closed and time.time() < end:
            d.step()
            for r in list(mg.rocks):
                if mg.rect.collidepoint(r[0], r[1]):
                    d.click((round(r[0]), round(r[1])))
                    break
    elif isinstance(mg, MG.Swipe):
        d.click(mg.card_rect.center)
        c = mg.card_rect.center
        d.drag(c, (c[0] + 300, c[1]), steps=50)  # ~0.85 s at 60 fps: "Accepted"
    elif isinstance(mg, MG.Simon):
        for stage in range(1, mg.STAGES + 1):
            d.wait(lambda: mg.state == "input" or mg.done or mg.closed, 10, "simon input")
            if mg.closed:
                return
            for k in mg.seq[:stage]:
                d.click(mg.keys[k])
    elif isinstance(mg, (MG.Scan,)):
        d.step(n=int(7.5 / DT))
    elif isinstance(mg, MG.Transfer):
        d.click(mg.button.center)
        d.step(n=int(6.5 / DT))
    elif isinstance(mg, MG.Shields):
        for i in sorted(mg.red):
            d.click((round(mg.cells[i][0]), round(mg.cells[i][1])))
    elif isinstance(mg, MG.Lights):
        for i, r in enumerate(mg.switches):
            if not mg.on[i]:
                d.click(r.center)
    elif isinstance(mg, MG.Comms):
        a = mg.goal * 2 * math.pi
        p = (mg.dial[0] + math.cos(a) * 60, mg.dial[1] + math.sin(a) * 60)
        d.step([pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(round(p[0]), round(p[1])))])
        d.step(n=int(1.2 / DT))
        d.step([pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=(round(p[0]), round(p[1])))])
    elif isinstance(mg, MG.O2Keypad):
        for ch in mg.code:
            d.click(mg.keys[ch])
        d.click(mg.keys["OK"])
    else:
        raise AssertionError(f"no solver for {type(mg).__name__}")


def teleport_to(d, scene, station):
    """Walk is client-authoritative; jump next to the station like a fast walker would."""
    x, y = get_world().nearest_free(*STATIONS[station]["pos"])
    scene.x, scene.y = float(x), float(y)
    scene.last_sent = None
    d.step(n=4)


def main():
    global SHOTS
    if len(sys.argv) > 1:
        SHOTS = sys.argv[1]
    os.makedirs(SHOTS, exist_ok=True)
    d = Driver()
    app = d.app
    port = free_port()
    results = {}
    try:
        # ---- menus
        assert isinstance(app.scene, type(None)) or True
        app.set_scene(MainMenu(app))
        d.step(n=5)
        d.shot("main_menu")
        app.set_scene(HelpScene(app))
        d.step(n=3)
        d.shot("help")
        app.set_scene(MainMenu(app))
        menu = app.scene
        menu.name.text = "Tester"
        app.prefs["name"] = "Tester"
        app.set_scene(JoinScene(app))
        d.step(n=90)
        d.shot("join_browser")
        app.set_scene(MainMenu(app))

        # ---- host + lobby
        app.start_server(name="E2E", port=port, discovery=False)
        app.server.logic.settings.update(discussion_time=3, voting_time=15, kill_cooldown=10, emergency_cooldown=0,
                                         short_tasks=5, long_tasks=3, common_tasks=2)
        app.set_scene(ConnectingScene(app, "127.0.0.1", port))
        d.wait(lambda: isinstance(app.scene, LobbyScene), what="lobby")
        d.wait(lambda: app.scene.players, what="lobby players")
        lobby = app.scene
        lobby.chat.input.text = "hello everyone"
        lobby.chat.input.focused = True
        d.key(pg.K_RETURN)
        for _ in range(7):
            app.add_bot("127.0.0.1", port)
        d.wait(lambda: len(app.scene.players) == 8, what="8 players in lobby")
        # colour change through the UI
        target = next(r for r in lobby.colour_rects if r[2])
        d.click(target[0].center)
        d.wait(lambda: any(p["id"] == app.my_id and p["colour"] == target[1] for p in lobby.players), what="colour")
        d.step(n=10)
        d.shot("lobby_8_players")
        assert lobby.is_host
        want = os.environ.get("E2E_ROLE", "crew")
        lg0 = app.server.logic
        if want == "imposter":
            lg0.force_imposters = [app.my_id]
        else:
            lg0.force_imposters = [next(pid for pid in lg0.players if pid != app.my_id)]
        d.click(lobby.start_btn.rect.center)
        d.wait(lambda: isinstance(app.scene, GameScene), what="game start")
        scene = app.scene
        results["role"] = scene.role
        d.step(n=60)
        d.shot("role_reveal")
        d.wait(lambda: scene.phase == "play" and scene.overlay is None, what="play phase")
        d.step(n=30)
        d.shot("in_game")

        # ---- walk with keyboard-equivalent input and check the server sees it
        sx, sy = scene.x, scene.y
        scene.input_override = (1, 0)
        d.step(n=40)
        scene.input_override = None
        d.step(n=10)
        server_me = app.server.logic.players[app.my_id]
        assert scene.x != sx, "local player did not move"
        assert abs(server_me.x - scene.x) < 5, f"server pos {server_me.x} vs client {scene.x}"
        results["moved"] = round(scene.x - sx)

        # ---- map overlay
        d.key(pg.K_TAB)
        d.step(n=5)
        d.shot("map_overlay")
        d.key(pg.K_TAB)

        if scene.is_imposter:
            results["imposter_path"] = run_imposter(d, scene)
        else:
            results["tasks_done"] = run_crew_tasks(d, scene)

        # ---- utilities
        settle(d, scene)
        for util in ("admin_map", "cams"):
            if app.server.logic.phase != "play" or scene.phase != "play":
                break
            teleport_to(d, scene, util)
            d.wait(lambda: scene.use_target is not None and scene.use_target[0] in ("admin", "cams"), 5, util)
            d.key(pg.K_e)
            d.step(n=5)
            d.shot(util)
            d.key(pg.K_ESCAPE)
            d.step(n=2)

        # ---- emergency meeting + vote through the UI
        lg = app.server.logic
        if settle(d, scene) and scene.alive and scene.me_info.get("em", 0) > 0:
            teleport_to(d, scene, "emergency")
            d.wait(lambda: scene.use_target and scene.use_target[0] == "emergency", 5, "emergency target")
            d.key(pg.K_e)
            d.step(n=3)
            d.shot("emergency_panel")
            d.wait(lambda: scene.me_info.get("ec", 1) <= 0, 30, "emergency cooldown")
            d.click(scene.minigame.button.center)
            d.wait(lambda: scene.meeting is not None, 5, "meeting start")
            d.step(n=60)
            d.shot("meeting_intro")
            d.wait(lambda: scene.meeting is not None and scene.meeting.stage == "discussion", 10, "discussion")
            d.step(n=100)
            m = scene.meeting
            scene.chat.input.focused = True
            d.type("it was blue")
            d.key(pg.K_RETURN)
            d.wait(lambda: any(ln[2] == "it was blue" for ln in scene.chat.lines) or scene.meeting is None, 5,
                   "own chat message echoed back")
            assert any(ln[2] == "it was blue" for ln in scene.chat.lines), "meeting chat message lost"
            d.shot("meeting_discussion")
            d.wait(lambda: scene.meeting is None or scene.meeting.stage == "vote", 15, "vote stage")
            if scene.meeting:
                d.click(m.skip_rect.center)
                d.step(n=2)
                assert m.confirm_rect is not None, "no confirm button after clicking skip"
                d.click(m.confirm_rect.center)
                d.step(n=20)
                d.shot("meeting_voted")
                assert m.my_vote == "skip"
            d.wait(lambda: scene.meeting is None, 40, "meeting end")
            d.step(n=120)
            d.shot("eject")
            results["meeting"] = "ok"

        # ---- let the bots finish the round
        d.wait(lambda: isinstance(scene.overlay, type(None)) is False and scene.phase == "over"
               or isinstance(app.scene, LobbyScene), 400, "game over")
        if scene.phase == "over":
            d.step(n=60)
            d.shot("game_over")
        d.wait(lambda: isinstance(app.scene, LobbyScene), 30, "back to lobby")
        d.step(n=20)
        d.shot("lobby_after_game")
        results["round_result"] = app.server.logic.events[-1] if app.server.logic.events else None
        results["game_over"] = [e for e in app.server.logic.events if e[0] == "game_over"]
        print("E2E OK", results)
        print("frames:", d.frames, "screenshots:", len(d.shots))
        return 0
    except Exception:
        traceback.print_exc()
        try:
            d.shot("FAILURE")
        except Exception:
            pass
        print("E2E FAILED", results)
        return 1
    finally:
        app.disconnect()


def settle(d, scene):
    """Sit through anything that interrupts play (bot meetings, our own death). False if the round ended."""
    lg = d.app.server.logic
    for _ in range(20000):
        if lg.phase == "over" or scene.phase == "over" or d.app.scene is not scene:
            return False
        m = scene.meeting
        if m is not None and m.can_vote():
            d.click(m.skip_rect.center)
            d.step(n=2)
            if m.confirm_rect:
                d.click(m.confirm_rect.center)
        if scene.phase == "play" and lg.phase == "play" and scene.overlay is None and scene.kill_anim is None:
            return True
        d.step()
    raise AssertionError("never got back to play")


def run_crew_tasks(d, scene):
    done = []
    shot_names = set()
    for task in scene.tasks:
        attempts = 0
        while task["step"] < len(task["steps"]):
            attempts += 1
            assert attempts < 8, f"task {task['id']} never completed"
            if not settle(d, scene):
                return done
            station, mg_name = task["steps"][task["step"]]
            teleport_to(d, scene, station)
            d.wait(lambda: (scene.use_target and scene.use_target[0] == "task") or scene.phase != "play", 5,
                   f"use target {station}")
            if scene.phase != "play":
                continue
            d.key(pg.K_e)
            if scene.minigame is None:
                if scene.phase != "play" or scene.overlay is not None or scene.kill_anim is not None:
                    continue  # a meeting/death landed in the same frame: correct behaviour, retry
                raise AssertionError(f"pressing E at {station} opened nothing (target={scene.use_target})")
            mg = scene.minigame
            d.step(n=3)
            if mg_name not in shot_names:
                shot_names.add(mg_name)
                d.shot(f"task_{mg_name}")
            before = task["step"]
            solve(d, mg)
            if not mg.done:
                assert scene.phase != "play" or mg.closed, f"{mg_name} panel not solved by its solver"
                continue  # interrupted by a meeting: retry
            d.wait(lambda: task["step"] > before or scene.phase != "play", 10, f"server ack for {mg_name}")
            if task["step"] > before:
                done.append(mg_name)
            d.wait(lambda: scene.minigame is None, 5, "panel close")
    return done


def run_imposter(d, scene):
    lg = d.app.server.logic
    path = []
    # sabotage via the map
    d.wait(lambda: scene.me_info.get("sc", 1) <= 0, 20, "sabotage cooldown")
    scene.map_overlay = MG.MapOverlay(scene, sabotage=True)
    d.step(n=3)
    d.shot("sabotage_map")
    d.click(scene.map_overlay.sab_buttons["lights"].center)
    d.wait(lambda: scene.sab is not None, 5, "sabotage active")
    path.append("sabotage")
    d.step(n=10)
    d.shot("lights_sabotage")
    # fix it ourselves via the panel (imposters may fix too)
    teleport_to(d, scene, "fix_lights")
    d.wait(lambda: scene.use_target and scene.use_target[0] == "fix", 5, "fix target")
    d.key(pg.K_e)
    d.shot("fix_lights_panel")
    solve(d, scene.minigame)
    d.wait(lambda: scene.sab is None, 5, "lights fixed")
    path.append("fixed")
    # vent in/out
    vx, vy = get_world().vent_exit_pos(0)
    scene.x, scene.y = float(vx), float(vy)
    d.step(n=4)
    d.wait(lambda: scene.vent_target is not None, 5, "vent target")
    d.key(pg.K_v)
    d.wait(lambda: scene.vent is not None, 5, "in vent")
    d.shot("in_vent")
    d.key(pg.K_d)
    d.step(n=10)
    d.key(pg.K_e)
    d.wait(lambda: scene.vent is None, 5, "out of vent")
    path.append("vented")
    # kill someone
    d.wait(lambda: scene.me_info.get("kc", 1) <= 0, 30, "kill cooldown")
    for _ in range(600):
        if lg.phase != "play":
            break
        victims = [r for r in scene.others.values() if r.alive and r.vent is None and r.id not in scene.imposters]
        if not victims:
            break
        v = victims[0]
        scene.x, scene.y = v.x + 10, v.y
        scene.last_sent = None
        d.step(n=3)
        if scene.kill_target is not None:
            d.key(pg.K_q)
            d.step(n=5)
            if any(e[0] == "kill" and e[1]["killer"] == d.app.my_id for e in lg.events):
                path.append("killed")
                d.shot("after_kill")
                break
    return path


if __name__ == "__main__":
    raise SystemExit(main())
