"""Headless bot player: speaks the real network protocol, walks the real map.

Used for stress tests and to fill small lobbies ("Add bot" in the lobby).
    python -m amongus.bot --host 127.0.0.1 --count 7
"""
import argparse
import math
import random
import select
import socket
import threading
import time

from . import config as C
from .protocol import FrameReader, ProtocolError, encode
from .world import SABOTAGES, STATIONS, get_world

BOT_NAMES = ["Beep", "Boop", "Bolt", "Chip", "Dash", "Echo", "Fizz", "Gizmo", "Jinx", "Kilo", "Nova", "Pixel",
             "Rusty", "Sprocket", "Volt", "Widget", "Zap", "Cog", "Byte", "Servo"]
CHAT_LINES = ["where?", "I was doing tasks", "sus", "it wasn't me", "skip?", "I saw them vent!", "trust me",
              "who called this", "I'm crew", "let's vote", "red sus", "I was in admin"]


class Bot:
    def __init__(self, host="127.0.0.1", port=C.TCP_PORT, name=None, colour=None, seed=None,
                 autostart_at=0, chaos=0.0, chat=True, log=None):
        self.host, self.port = host, port
        self.rng = random.Random(seed)
        self.name = name or self.rng.choice(BOT_NAMES)
        self.want_colour = colour
        self.autostart_at = autostart_at   # host bots start the game when this many players are in the lobby
        self.chaos = chaos                 # probability per second of doing something rude (stress tests)
        self.chat_enabled = chat
        self.log = log or (lambda *a: None)
        self.world = get_world()
        self.sock = None
        self.reader = FrameReader()
        self.stop_event = threading.Event()
        self.connected = False
        self.error = None
        self.stats = {"msgs": 0, "snaps": 0, "games": 0, "kills": 0, "tasks": 0, "reports": 0, "votes": 0,
                      "meetings": 0, "fixes": 0, "rtt": [], "wins": 0, "losses": 0}
        self.reset_state()

    # ------------------------------------------------------------------ state
    def reset_state(self):
        self.id = None
        self.is_host = False
        self.phase = "lobby"
        self.lobby_players = []
        self.role = None
        self.imposters = set()
        self.tasks = []
        self.x = self.y = 0.0
        self.epoch = 0
        self.alive = True
        self.others = {}
        self.bodies = []
        self.sab = None
        self.me = {}
        self.meeting = None
        self.meeting_stage = None
        self.voted = False
        self.vote_at = None
        self.target = None
        self.target_kind = None
        self.work_until = None
        self.holding = None
        self.vent = None
        self.wander = None
        self.last_kill_try = 0.0
        self.last_report = 0.0
        self.colour = None

    # ------------------------------------------------------------------ networking
    def connect(self, timeout=5.0):
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(5.0)
        self.connected = True
        self.send({"t": "hello", "v": C.PROTOCOL_VERSION, "name": self.name, "colour": self.want_colour})

    def send(self, msg):
        if not self.connected:
            return
        try:
            self.sock.sendall(encode(msg))
        except OSError as e:
            self.error = f"send: {e}"
            self.connected = False

    def close(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def pump(self):
        while self.connected:
            r, _, _ = select.select([self.sock], [], [], 0)
            if not r:
                return
            try:
                data = self.sock.recv(65536)
            except OSError as e:
                self.error = f"recv: {e}"
                self.connected = False
                return
            if not data:
                self.connected = False
                return
            try:
                msgs = self.reader.feed(data)
            except ProtocolError as e:
                self.error = f"protocol: {e}"
                self.connected = False
                return
            for m in msgs:
                self.stats["msgs"] += 1
                self.on_msg(m)

    def run(self, duration=None):
        try:
            if not self.connected:
                self.connect()
        except OSError as e:
            self.error = f"connect: {e}"
            return
        end = time.perf_counter() + duration if duration else None
        period = 1.0 / C.CLIENT_SEND_HZ
        last = time.perf_counter()
        next_ping = last
        try:
            while self.connected and not self.stop_event.is_set():
                if end and time.perf_counter() > end:
                    break
                self.pump()
                now = time.perf_counter()
                dt = min(0.1, now - last)
                last = now
                self.think(now, dt)
                if now >= next_ping:
                    self.send({"t": "ping", "c": now})
                    next_ping = now + 1.0
                time.sleep(max(0.0, period - (time.perf_counter() - now)))
        except Exception as e:  # keep the error for the stress report instead of dying silently
            self.error = f"crash: {e!r}"
            raise
        finally:
            self.close()

    # ------------------------------------------------------------------ messages
    def on_msg(self, m):
        t = m["t"]
        if t == "welcome":
            self.id = m["id"]
            self.colour = m["colour"]
            self.is_host = m["host"]
        elif t == "lobby":
            self.lobby_players = m["players"]
            self.is_host = m["host"] == self.id
            if m["phase"] == "lobby":
                self.phase = "lobby"
            if (self.is_host and self.autostart_at and m["phase"] == "lobby"
                    and len(self.lobby_players) >= self.autostart_at):
                self.send({"t": "start"})
        elif t == "error":
            self.error = m.get("msg")
            if m.get("fatal"):
                self.connected = False
        elif t == "game_start":
            keep = (self.id, self.is_host, self.colour, self.lobby_players)
            self.reset_state()
            self.id, self.is_host, self.colour, self.lobby_players = keep
            self.phase = "reveal"
            self.role = m["role"]
            self.imposters = set(m["imposters"])
            self.tasks = m["tasks"]
            self.x, self.y, self.epoch = float(m["x"]), float(m["y"]), m["ep"]
            self.stats["games"] += 1
        elif t == "play" or t == "resume":
            self.phase = "play"
            self.meeting = None
            self.target = None
            self.holding = None
            self.work_until = None
        elif t == "snap":
            self.stats["snaps"] += 1
            self.phase = m["ph"] if m["ph"] != "lobby" else self.phase
            self.others = {p[0]: p for p in m["pl"]}
            self.bodies = m["bd"]
            self.sab = m["sab"]
            self.me = m.get("me", {})
            mine = self.others.get(self.id)
            if mine is not None:
                self.alive = bool(mine[5])
        elif t == "teleport":
            self.x, self.y, self.epoch = float(m["x"]), float(m["y"]), m["ep"]
            self.target = None
        elif t == "task_ok":
            for task in self.tasks:
                if task["id"] == m["task"]:
                    task["step"] = m["step"]
            self.stats["tasks"] += 1
            self.target = None
        elif t == "killed":
            self.alive = False
            self.target = None
            self.holding = None
        elif t == "kill_ok":
            self.stats["kills"] += 1
            self.target = None
        elif t == "vent_state":
            self.vent = m["id"]
        elif t == "meeting":
            self.phase = "meeting"
            self.meeting = m
            self.meeting_stage = "intro"
            self.voted = False
            self.vote_at = None
            self.target = None
            self.holding = None
            self.work_until = None
            self.stats["meetings"] += 1
        elif t == "meeting_stage":
            self.meeting_stage = m["stage"]
            if m["stage"] == "vote":
                self.vote_at = time.perf_counter() + self.rng.uniform(0.5, min(8.0, m["dur"] * 0.6))
        elif t == "vote_result":
            self.meeting_stage = "results"
        elif t == "eject":
            self.phase = "eject"
        elif t == "game_over":
            self.phase = "over"
            mine_imp = self.role == "imposter"
            won = (m["winner"] == "imposter") == mine_imp
            self.stats["wins" if won else "losses"] += 1
        elif t == "to_lobby":
            self.phase = "lobby"
        elif t == "pong":
            if isinstance(m.get("c"), (int, float)):
                self.stats["rtt"].append(time.perf_counter() - m["c"])
        elif t == "kicked":
            self.connected = False

    # ------------------------------------------------------------------ behaviour
    def think(self, now, dt):
        if self.chaos and self.rng.random() < self.chaos * dt:
            self.do_chaos()
        if self.phase == "play":
            self.play(now, dt)
        elif self.phase == "meeting":
            self.in_meeting(now)

    def do_chaos(self):
        r = self.rng.random()
        if r < 0.3:
            self.send({"t": self.rng.choice(["kill", "vote", "fix", "hold", "vent", "task", "report"]),
                       "target": self.rng.randint(-5, 50), "panel": "fix_reactor_a", "on": True, "act": "enter",
                       "id": self.rng.randint(0, 20), "task": "wiring", "step": 9, "body": 3})
        elif r < 0.6:
            self.send({"t": "pos", "x": self.rng.uniform(-1e6, 1e6), "y": float("1e300"), "ep": self.epoch})
        elif r < 0.8:
            self.send({"t": "chat", "text": "x" * 500})
        else:
            self.send({"t": "settings", "settings": {"kill_cooldown": -5}})

    def free_station_spot(self, station):
        return STATIONS[station]["pos"]

    def go_towards(self, xy, radius, dt):
        """Walk along the flow field. Returns True when within radius."""
        if math.hypot(self.x - xy[0], self.y - xy[1]) <= radius:
            return True
        speed = C.PLAYER_SPEED * dt
        ghost = not self.alive
        field = self.world.flow_field(xy, radius)
        wp = self.world.next_waypoint(self.x, self.y, field)
        if wp is None:
            wp = xy
        dx, dy = wp[0] - self.x, wp[1] - self.y
        d = math.hypot(dx, dy) or 1.0
        mx, my = dx / d * min(speed, d), dy / d * min(speed, d)
        if ghost:
            self.x += mx
            self.y += my
        else:
            nx, ny = self.world.collider.move(self.x, self.y, mx, my)
            if (nx, ny) == (self.x, self.y):  # wedged on a corner: nudge to a cell centre
                cell = self.world.nearest_walkable_cell(self.x, self.y)
                if cell:
                    nx, ny = self.world.cell_center(cell)
            self.x, self.y = nx, ny
        direction = (3 if mx > 0 else 2) if abs(mx) > abs(my) else (0 if my > 0 else 1)
        self.send({"t": "pos", "x": round(self.x, 1), "y": round(self.y, 1), "d": direction, "m": 1, "ep": self.epoch})
        return False

    def idle_pos(self):
        self.send({"t": "pos", "x": round(self.x, 1), "y": round(self.y, 1), "d": 0, "m": 0, "ep": self.epoch})

    def play(self, now, dt):
        if self.vent is not None:
            if self.rng.random() < dt * 0.5:
                self.send({"t": "vent", "act": "exit"})
                self.vent = None  # optimistic; teleport follows
            return
        sab = self.sab
        # 1) critical sabotage: everyone alive helps
        if sab and self.alive and self.role != "imposter":
            kind = sab["k"]
            panels = SABOTAGES[kind]["panels"]
            mine = panels[self.id % len(panels)]
            if kind in ("lights", "comms") and self.id % 3:
                mine = None  # not everyone runs to non-critical sabotage
            if mine and mine not in sab.get("done", []):
                if self.go_towards(STATIONS[mine]["pos"], C.USE_RANGE - 30, dt):
                    if kind == "reactor":
                        if self.holding != mine:
                            self.send({"t": "hold", "panel": mine, "on": True})
                            self.holding = mine
                    else:
                        if self.work_until is None:
                            self.work_until = now + self.rng.uniform(1.0, 3.0)
                        elif now >= self.work_until:
                            self.send({"t": "fix", "panel": mine})
                            self.stats["fixes"] += 1
                            self.work_until = None
                    self.idle_pos()
                return
        if self.holding and not (sab and sab["k"] == "reactor"):
            self.holding = None
        # 2) report bodies we stumble on
        if self.alive and self.bodies:
            for b in self.bodies:
                if math.hypot(b[1] - self.x, b[2] - self.y) < 450 and (self.role != "imposter" or self.rng.random() < 0.02):
                    if self.go_towards((b[1], b[2]), C.REPORT_RANGE - 40, dt) and now - self.last_report > 1.0:
                        self.last_report = now
                        self.send({"t": "report", "body": b[0]})
                        self.stats["reports"] += 1
                    return
        # 3) imposters hunt
        if self.role == "imposter" and self.alive:
            if self.hunt(now, dt):
                return
        # 4) tasks (crew and ghosts) / wander (imposters)
        if self.role != "imposter":
            task = next((t for t in self.tasks if t["step"] < len(t["steps"])), None)
            if task:
                station = task["steps"][task["step"]][0]
                if self.go_towards(STATIONS[station]["pos"], C.USE_RANGE - 30, dt):
                    if self.work_until is None:
                        self.work_until = now + self.rng.uniform(1.0, 4.0)
                    elif now >= self.work_until:
                        self.send({"t": "task", "task": task["id"], "step": task["step"]})
                        self.work_until = now + 3.0  # wait for task_ok before retrying
                    self.idle_pos()
                return
        # occasionally call an emergency meeting
        if self.alive and self.me.get("em", 0) > 0 and self.me.get("ec", 1) == 0 and self.rng.random() < dt * 0.01:
            self.wander = STATIONS["emergency"]["pos"]
        if self.wander is None or math.hypot(self.wander[0] - self.x, self.wander[1] - self.y) < 60:
            if self.wander == STATIONS["emergency"]["pos"] and self.alive:
                self.send({"t": "emergency"})
            self.wander = self.world.random_walkable_point(self.rng)
        self.go_towards(self.wander, 50, dt)

    def hunt(self, now, dt):
        me = self.me
        if me.get("sc", 1) == 0 and self.sab is None and self.rng.random() < dt * 0.05:
            self.send({"t": "sabotage", "kind": self.rng.choice(list(SABOTAGES))})
        victims = [p for pid, p in self.others.items()
                   if pid != self.id and pid not in self.imposters and p[5] and p[6] < 0]
        if not victims:
            return False
        v = min(victims, key=lambda p: math.hypot(p[1] - self.x, p[2] - self.y))
        d = math.hypot(v[1] - self.x, v[2] - self.y)
        if me.get("kc", 99) > 0:
            # loiter, sometimes hop in a vent
            if self.rng.random() < dt * 0.02:
                for i, vp in enumerate(self.world.vents):
                    if math.hypot(vp[0] - self.x, vp[1] - self.y) < C.VENT_RANGE:
                        self.send({"t": "vent", "act": "enter", "id": i})
                        return True
            return False
        if d < C.KILL_RANGE - 20:
            if now - self.last_kill_try > 0.5:
                self.send({"t": "kill", "target": v[0]})
                self.last_kill_try = now
            self.idle_pos()
            return True
        if d < 1500:
            self.go_towards((v[1], v[2]), C.KILL_RANGE - 40, dt)
            return True
        return False

    def in_meeting(self, now):
        m = self.meeting
        if not m:
            return
        if self.chat_enabled and self.alive and self.rng.random() < 0.004:
            self.send({"t": "chat", "text": self.rng.choice(CHAT_LINES)})
        if self.meeting_stage == "vote" and not self.voted and self.alive and self.vote_at and now >= self.vote_at:
            alive = [p["id"] for p in m["players"] if p.get("alive") and p["id"] != self.id
                     and self.others.get(p["id"], [0, 0, 0, 0, 0, 1])[5]]
            if self.role == "imposter":
                alive = [a for a in alive if a not in self.imposters]
            target = "skip" if not alive or self.rng.random() < 0.3 else self.rng.choice(alive)
            self.send({"t": "vote", "target": target})
            self.voted = True
            self.stats["votes"] += 1


def spawn_bots(n, host="127.0.0.1", port=C.TCP_PORT, start_delay=0.05, **kw):
    """Start n bots on daemon threads. Returns list of (bot, thread)."""
    out = []
    names = list(BOT_NAMES)
    random.shuffle(names)
    for i in range(n):
        b = Bot(host, port, name=names[i % len(names)], seed=i * 7919 + int(time.time()), **kw)
        t = threading.Thread(target=b.run, name=f"bot-{b.name}", daemon=True)
        t.start()
        out.append((b, t))
        time.sleep(start_delay)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run headless bot players against a server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=C.TCP_PORT)
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--autostart", type=int, default=0, help="first bot starts the game at this many players")
    args = ap.parse_args(argv)
    bots = []
    for i in range(args.count):
        b = Bot(args.host, args.port, name=BOT_NAMES[i % len(BOT_NAMES)], seed=i,
                autostart_at=args.autostart if i == 0 else 0)
        t = threading.Thread(target=b.run, daemon=True)
        t.start()
        bots.append((b, t))
        time.sleep(0.1)
    print(f"{len(bots)} bots running; Ctrl+C to stop")
    try:
        while any(t.is_alive() for _, t in bots):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    for b, _ in bots:
        b.stop_event.set()


if __name__ == "__main__":
    main()
