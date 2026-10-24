"""Stress test: one server + N bot players over real TCP sockets.

    python tests/stress.py --players 10 --duration 180
    python tests/stress.py --players 12 --duration 240 --chaos 0.2 --churn 20 --subprocess

Exits non-zero if the server logged errors, a bot crashed, or no round finished.
"""
import argparse
import os
import random
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from amongus import config as C  # noqa: E402
from amongus.bot import Bot  # noqa: E402
from amongus.logic import GameLogic  # noqa: E402
from amongus.protocol import encode  # noqa: E402
from amongus.server import Server  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def abuse_connections(port, stop, counter):
    """Hostile clients: garbage bytes, giant frames, half-open connections, hello floods."""
    rng = random.Random(3)
    while not stop.is_set():
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=2)
            kind = rng.choice(["garbage", "huge", "idle", "nohello", "badjson", "badversion"])
            if kind == "garbage":
                s.sendall(os.urandom(rng.randint(1, 4000)))
            elif kind == "huge":
                s.sendall((50_000_000).to_bytes(4, "big") + b"x" * 1000)
            elif kind == "nohello":
                s.sendall(encode({"t": "kill", "target": 1}))
            elif kind == "badjson":
                body = b"{not json"
                s.sendall(len(body).to_bytes(4, "big") + body)
            elif kind == "badversion":
                s.sendall(encode({"t": "hello", "v": 0, "name": "old"}))
            time.sleep(rng.uniform(0.05, 0.5))
            s.close()
            counter[kind] += 1
        except OSError:
            counter["refused"] += 1
        time.sleep(rng.uniform(0.2, 1.0))


def latency_probe(port, stop, samples, delay):
    """Spectator connection that only pings: measures true server round-trip, free of bot-loop lag."""
    from amongus.protocol import FrameReader
    time.sleep(delay)
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
    except OSError:
        return
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.sendall(encode({"t": "hello", "v": C.PROTOCOL_VERSION, "name": "probe"}))
    reader = FrameReader()
    s.settimeout(0.05)
    next_ping = 0.0
    while not stop.is_set():
        now = time.perf_counter()
        if now >= next_ping:
            s.sendall(encode({"t": "ping", "c": now}))
            next_ping = now + 0.25
        try:
            data = s.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            return
        if not data:
            return
        for m in reader.feed(data):
            if m["t"] == "pong":
                samples.append(time.perf_counter() - m["c"])
    s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--duration", type=float, default=120)
    ap.add_argument("--chaos", type=float, default=0.0, help="per-bot rude actions per second")
    ap.add_argument("--churn", type=float, default=0.0, help="seconds between random bot disconnect/rejoins (0=off)")
    ap.add_argument("--abuse", action="store_true", help="also run hostile raw-socket clients")
    ap.add_argument("--subprocess", action="store_true", help="run the server as a separate process")
    ap.add_argument("--kill-cooldown", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    port = free_port()
    srv = proc = None
    if args.subprocess:
        proc = subprocess.Popen([sys.executable, "-m", "amongus.server", "--port", str(port), "--no-discovery"],
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(1.5)
    else:
        srv = Server(port=port, bind="127.0.0.1", discovery=False, logic=GameLogic(rng=random.Random(args.seed)))
        srv.logic.settings.update(kill_cooldown=args.kill_cooldown, discussion_time=5, voting_time=20)
        srv.start()
        threading.Thread(target=srv.run, daemon=True).start()

    bots = []

    def add_bot(i, autostart=0):
        b = Bot("127.0.0.1", port, name=f"Bot{i}", seed=args.seed * 1000 + i, autostart_at=autostart,
                chaos=args.chaos)
        t = threading.Thread(target=b.run, daemon=True)
        t.start()
        bots.append((b, t))
        return b

    host = add_bot(0, autostart=args.players)
    time.sleep(0.3)
    if args.subprocess:
        # configure through the protocol like a real host would
        host.send({"t": "settings", "settings": {"kill_cooldown": args.kill_cooldown, "discussion_time": 5,
                                                 "voting_time": 20}})
    for i in range(1, args.players):
        add_bot(i)
        time.sleep(0.05)

    stop = threading.Event()
    probe_rtts = []
    threading.Thread(target=latency_probe, args=(port, stop, probe_rtts, 8.0), daemon=True).start()
    abuse_counter = Counter()
    if args.abuse:
        threading.Thread(target=abuse_connections, args=(port, stop, abuse_counter), daemon=True).start()

    t0 = time.time()
    next_churn = t0 + args.churn if args.churn else None
    churned = 0
    rng = random.Random(args.seed)
    last_report = t0
    while time.time() - t0 < args.duration:
        time.sleep(0.5)
        now = time.time()
        if next_churn and now >= next_churn:
            live = [(b, t) for b, t in bots if t.is_alive() and b is not host]
            if live:
                b, t = rng.choice(live)
                b.stop_event.set()  # abrupt disconnect (socket closed mid-game)
                churned += 1
                add_bot(100 + churned)
            next_churn = now + args.churn
        if now - last_report > 15 and srv:
            lg = srv.logic
            st = srv.stats
            avg = st["tick_time_total"] / max(1, st["ticks"]) * 1000
            print(f"[{now - t0:5.0f}s] phase={lg.phase:8s} round={lg.round} players={len(lg.players)} "
                  f"tick avg={avg:.2f}ms max={st['tick_time_max'] * 1000:.1f}ms out={st['bytes_out'] / 1e6:.1f}MB "
                  f"in={st['bytes_in'] / 1e6:.1f}MB handler_errors={st['handler_errors']} "
                  f"protocol_rejects={st['protocol_errors']}", flush=True)
            last_report = now

    stop.set()
    for b, _ in bots:
        b.stop_event.set()
    time.sleep(1.0)

    ok = True
    print("\n===== STRESS REPORT =====")
    print(f"players={args.players} duration={args.duration}s chaos={args.chaos} churn={args.churn} "
          f"abuse={args.abuse} subprocess={args.subprocess}")
    crashed = [b for b, _ in bots if b.error and b.error.startswith("crash")]
    rtts = [r for b, _ in bots for r in b.stats["rtt"]]
    totals = Counter()
    for b, _ in bots:
        for k in ("games", "kills", "tasks", "reports", "votes", "meetings", "fixes", "wins", "losses", "snaps"):
            totals[k] += b.stats[k]
    print("bot totals:", dict(totals))
    if probe_rtts:
        pr = sorted(probe_rtts)
        print(f"SERVER RTT (dedicated probe) ms: median={statistics.median(pr) * 1000:.2f} "
              f"p95={pr[int(len(pr) * 0.95)] * 1000:.2f} p99={pr[int(len(pr) * 0.99)] * 1000:.2f} "
              f"max={pr[-1] * 1000:.1f} (n={len(pr)})")
    if rtts:
        rtts.sort()
        print(f"bot-side RTT (includes bot loop lag) ms: median={statistics.median(rtts) * 1000:.1f} p95={rtts[int(len(rtts) * 0.95)] * 1000:.1f} "
              f"max={rtts[-1] * 1000:.1f} (n={len(rtts)})")
    errs = Counter(b.error.split(":")[0] for b, _ in bots if b.error)
    print("bot connection outcomes:", dict(errs) or "none")
    if crashed:
        ok = False
        print("BOT CRASHES:", [b.error for b in crashed])
    if args.abuse:
        print("abusive connections made:", dict(abuse_counter))
    if srv:
        lg, st = srv.logic, srv.stats
        ev = Counter(e[0] for e in lg.events)
        overs = [e[1] for e in lg.events if e[0] == "game_over"]
        print("server events:", dict(ev))
        print("round outcomes:", Counter((o["winner"], o["reason"]) for o in overs))
        avg = st["tick_time_total"] / max(1, st["ticks"]) * 1000
        print(f"server ticks={st['ticks']} avg={avg:.2f}ms max={st['tick_time_max'] * 1000:.1f}ms "
              f"bytes out={st['bytes_out'] / 1e6:.1f}MB in={st['bytes_in'] / 1e6:.1f}MB "
              f"msgs in={st['msgs_in']} out={st['msgs_out']} accepted={st['accepted']} dropped={st['dropped']} "
              f"protocol_rejects={st['protocol_errors']} handler_errors={st['handler_errors']}")
        bad = [e for e in lg.events if e[0] == "bad_msg"]
        if bad:
            ok = False
            print("BAD MESSAGES (unvalidated input reached the rules):", bad[:5])
        if st["handler_errors"]:
            ok = False
            print("SERVER HANDLER EXCEPTIONS:", st["handler_errors"])
        if st["protocol_errors"] and not args.abuse:
            ok = False
            print("UNEXPECTED PROTOCOL ERRORS:", st["protocol_errors"])
        if not overs:
            ok = False
            print("NO ROUND FINISHED")
        srv.stop()
    if proc:
        proc.terminate()
        out = proc.communicate(timeout=10)[0]
        tb = [ln for ln in out.splitlines() if "Traceback" in ln or "ERROR" in ln]
        reasons = Counter(ln.split(" left: ", 1)[1].strip() for ln in out.splitlines() if " left: " in ln)
        print("server-side disconnect reasons:", dict(reasons))
        print("server process log lines:", len(out.splitlines()), "errors:", len(tb))
        if tb:
            ok = False
            print("\n".join(out.splitlines()[-40:]))
        if totals["games"] == 0:
            ok = False
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
