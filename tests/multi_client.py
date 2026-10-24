"""Many real game clients (separate processes, headless) + bots against a dedicated server process.

    python tests/multi_client.py --clients 6 --bots 4 --duration 240

Each client process runs the actual pygame client (App/LobbyScene/GameScene) with an
autopilot: wander around, open the map, chat and vote skip in meetings. Fails if any
client crashes, gets disconnected, or the server logs a traceback.
"""
import argparse
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def worker(port, idx, duration, out_path, expect):
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.chdir(ROOT)
    import pygame as pg
    from amongus.client.app import App
    from amongus.client.game import GameScene
    from amongus.client.lobby import LobbyScene
    from amongus.client.menus import ConnectingScene, MessageScene

    rng = random.Random(idx)
    app = App(headless=True)
    app.prefs = {"name": f"Human{idx}"}
    app.set_scene(ConnectingScene(app, "127.0.0.1", port))
    stats = {"idx": idx, "frames": 0, "games": 0, "meetings": 0, "votes": 0, "chats": 0, "max_frame_ms": 0.0,
             "error": None, "scenes": {}}
    end = time.time() + duration
    last_scene = None
    turn_at = 0.0
    try:
        while time.time() < end:
            t0 = time.perf_counter()
            app.step(1 / 30, [])
            dt_ms = (time.perf_counter() - t0) * 1000
            stats["frames"] += 1
            if stats["frames"] > 60:
                stats["max_frame_ms"] = max(stats["max_frame_ms"], dt_ms)
            sc = app.scene
            name = type(sc).__name__
            stats["scenes"][name] = stats["scenes"].get(name, 0) + 1
            if isinstance(sc, MessageScene):
                stats["error"] = f"{sc.title}: {sc.text}"
                break
            if isinstance(sc, LobbyScene) and sc.is_host and len(sc.players) >= expect and sc.phase == "lobby":
                if time.time() > turn_at:  # host autopilot presses START (again after every round)
                    sc.start()
                    turn_at = time.time() + 3
            if isinstance(sc, GameScene):
                if sc is not last_scene:
                    stats["games"] += 1
                    last_scene = sc
                if time.time() > turn_at:
                    sc.input_override = (rng.choice((-1, 0, 1)), rng.choice((-1, 0, 1)))
                    turn_at = time.time() + rng.uniform(0.5, 2.5)
                    if rng.random() < 0.05:
                        sc.toggle_map()
                m = sc.meeting
                if m is not None:
                    if m.stage == "discussion" and rng.random() < 0.01:
                        sc.send_chat(rng.choice(["hi", "where", "sus", "skip"]))
                        stats["chats"] += 1
                    if m.can_vote() and rng.random() < 0.05:
                        m.cast("skip" if rng.random() < 0.5 else rng.choice(
                            [p["id"] for p in m.players if p.get("alive")]))
                        stats["votes"] += 1
                if m is not None and getattr(sc, "_counted_meeting", None) is not m:
                    sc._counted_meeting = m
                    stats["meetings"] += 1
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - t0)))
    except Exception as e:  # report the crash to the parent
        import traceback
        stats["error"] = "CRASH: " + "".join(traceback.format_exception(e))[-1500:]
    finally:
        stats["final_scene"] = type(app.scene).__name__
        stats["rtt_ms"] = round(app.net.rtt * 1000, 1) if app.net and app.net.rtt else None
        app.disconnect()
        with open(out_path, "w") as f:
            json.dump(stats, f)
        pg.quit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=6)
    ap.add_argument("--bots", type=int, default=4)
    ap.add_argument("--duration", type=float, default=240)
    ap.add_argument("--worker", type=int, default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--expect", type=int, default=0)
    args = ap.parse_args()
    if args.worker is not None:
        worker(args.port, args.worker, args.duration, args.out, args.expect)
        return 0

    port = free_port()
    tmp = os.path.join(ROOT, "tests", "_multi")
    os.makedirs(tmp, exist_ok=True)
    srv = subprocess.Popen([sys.executable, "-u", "server.py", "--port", str(port), "--no-discovery"], cwd=ROOT,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    srv_lines = []
    threading.Thread(target=lambda: [srv_lines.append(ln) for ln in srv.stdout], daemon=True).start()
    time.sleep(1.5)
    procs = []
    for i in range(args.clients):
        out = os.path.join(tmp, f"client{i}.json")
        if os.path.exists(out):
            os.remove(out)
        procs.append((subprocess.Popen([sys.executable, "-W", "ignore", "tests/multi_client.py", "--worker", str(i),
                                        "--port", str(port), "--duration", str(args.duration), "--out", out,
                                        "--expect", str(args.clients + args.bots)],
                                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True), out))
        time.sleep(0.4)
    time.sleep(6)  # humans join first, so human client 0 is the host and starts the game
    from amongus.bot import Bot
    bots = []
    for i in range(args.bots):
        b = Bot("127.0.0.1", port, name=f"Bot{i}", seed=i)
        t = threading.Thread(target=b.run, daemon=True)
        t.start()
        bots.append((b, t))
        time.sleep(0.1)
    ok = True
    for p, out in procs:
        try:
            _, err = p.communicate(timeout=args.duration + 60)
        except subprocess.TimeoutExpired:
            p.kill()
            ok = False
            print("client process hung")
            continue
        if not os.path.exists(out):
            ok = False
            print("client produced no report; stderr tail:\n", (err or "")[-1500:])
            continue
        st = json.load(open(out))
        print(f"client {st['idx']}: frames={st['frames']} games={st['games']} meetings={st['meetings']} "
              f"votes={st['votes']} chats={st['chats']} max_frame={st['max_frame_ms']:.1f}ms rtt={st['rtt_ms']}ms "
              f"final={st['final_scene']} error={st['error']}")
        if st["error"] or st["games"] == 0:
            ok = False
    for b, _ in bots:
        b.stop_event.set()
    srv.terminate()
    time.sleep(1)
    tracebacks = [ln for ln in srv_lines if "Traceback" in ln or "ERROR" in ln]
    print("server log lines:", len(srv_lines), "tracebacks/errors:", len(tracebacks))
    if tracebacks:
        ok = False
        print("".join(srv_lines[-40:]))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
