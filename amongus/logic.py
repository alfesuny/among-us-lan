"""Authoritative game rules. No sockets, no clocks: the caller passes `now`.

The Server (server.py) feeds client messages into GameLogic.handle() and calls
tick() at SERVER_TICK_HZ. GameLogic emits messages through an Outbox, so unit
tests can drive the whole game without networking.
"""
import math
import random
import re

from . import config as C
from .world import (SABOTAGES, STATIONS, TASKS, dist, get_world, make_task_steps)

DIRS = ("down", "up", "left", "right")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _clean_text(s, limit):
    if not isinstance(s, str):
        return ""
    return _CTRL.sub("", s).strip()[:limit]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _key(v):
    """Only ints/strings may be used as lookup keys (lists/dicts from a bad client are unhashable)."""
    return v if isinstance(v, (int, str)) and not isinstance(v, bool) else None


class Outbox:
    """Collects outgoing messages: (pid or None for broadcast, msg, filter)."""

    def __init__(self):
        self.items = []

    def send(self, pid, msg):
        self.items.append((pid, msg))

    def broadcast(self, msg, only=None):
        """only: optional predicate(player) restricting recipients."""
        self.items.append((None, msg, only) if only else (None, msg))

    def drain(self):
        items, self.items = self.items, []
        return items


class Player:
    def __init__(self, pid, name, colour, joined):
        self.id = pid
        self.name = name
        self.colour = colour
        self.joined = joined
        self.reset_round()

    def reset_round(self):
        self.in_game = False
        self.role = "crew"
        self.alive = True
        self.x, self.y = 0.0, 0.0
        self.dir = 0
        self.moving = False
        self.vent = None
        self.epoch = 0
        self.tasks = []
        self.kill_ready = 0.0
        self.emergencies = 0
        self.last_chat = -10.0
        self.last_pos = 0.0

    @property
    def imposter(self):
        return self.role == "imposter"

    def public(self):
        return {"id": self.id, "name": self.name, "colour": self.colour}


class GameLogic:
    def __init__(self, rng=None, world=None, min_players=C.MIN_PLAYERS_TO_START):
        self.rng = rng or random.Random()
        self.world = world or get_world()
        self.min_players = min_players
        self.out = Outbox()
        self.players = {}
        self.next_id = 1
        self.host_id = None
        self.settings = dict(C.DEFAULT_SETTINGS)
        self.phase = "lobby"
        self.phase_end = None
        self.round = 0
        self.bodies = []
        self.sabotage = None
        self.sab_ready = 0.0
        self.emergency_ready = 0.0
        self.meeting = None
        self.eject_info = None
        self.result = None
        self.lobby_dirty = True
        self.info_extra = {}
        self.force_imposters = None  # test hook: list of player ids that must be imposters
        self.events = []  # (kind, detail) log, handy for tests and stress reports

    # ------------------------------------------------------------------ helpers
    def log(self, _event, **detail):
        self.events.append((_event, detail))
        if len(self.events) > 5000:
            del self.events[:1000]

    def ingame(self):
        return [p for p in self.players.values() if p.in_game]

    def alive_crew(self):
        return [p for p in self.ingame() if p.alive and not p.imposter]

    def alive_imposters(self):
        return [p for p in self.ingame() if p.alive and p.imposter]

    def free_colours(self, exclude_pid=None):
        used = {p.colour for p in self.players.values() if p.id != exclude_pid}
        return [c for c in C.COLOUR_NAMES if c not in used]

    def task_progress(self):
        total = done = 0
        for p in self.ingame():
            if p.imposter:
                continue
            for t in p.tasks:
                total += len(t["steps"])
                done += t["step"]
        return done, total

    def lobby_msg(self):
        return {
            "t": "lobby",
            "host": self.host_id,
            "phase": self.phase,
            "settings": self.settings,
            "players": [dict(p.public(), host=p.id == self.host_id, in_game=p.in_game)
                        for p in sorted(self.players.values(), key=lambda q: q.joined)],
            **self.info_extra,
        }

    def teleport(self, p, x, y):
        p.x, p.y = float(x), float(y)
        p.epoch += 1
        p.moving = False
        self.out.send(p.id, {"t": "teleport", "x": round(p.x), "y": round(p.y), "ep": p.epoch})

    def near(self, p, xy, rng):
        return dist((p.x, p.y), xy) <= rng + C.POSITION_SLACK

    # ------------------------------------------------------------------ connection lifecycle
    def join(self, hello, now):
        """Returns (pid, None) or (None, error string)."""
        if hello.get("v") != C.PROTOCOL_VERSION:
            return None, f"Version mismatch: server {C.GAME_VERSION} (protocol {C.PROTOCOL_VERSION})"
        if len(self.players) >= C.MAX_PLAYERS:
            return None, "Server is full"
        name = _clean_text(hello.get("name"), C.MAX_NAME_LEN) or "Player"
        taken = {p.name.lower() for p in self.players.values()}
        base, n = name, 2
        while name.lower() in taken:
            suffix = str(n)
            name = base[:C.MAX_NAME_LEN - len(suffix)] + suffix
            n += 1
        free = self.free_colours()
        colour = hello.get("colour") if hello.get("colour") in free else (free[0] if free else "Red")
        pid = self.next_id
        self.next_id += 1
        p = Player(pid, name, colour, now)
        self.players[pid] = p
        if self.host_id is None or self.host_id not in self.players:
            self.host_id = pid
        self.out.send(pid, {"t": "welcome", "id": pid, "name": name, "colour": colour,
                            "host": self.host_id == pid, "phase": self.phase, "version": C.GAME_VERSION})
        self.lobby_dirty = True
        self.log("join", pid=pid, name=name)
        if self.phase != "lobby":
            self.out.send(pid, {"t": "spectate", "phase": self.phase})
        return pid, None

    def leave(self, pid, now, reason="left"):
        p = self.players.pop(pid, None)
        if p is None:
            return
        self.log("leave", pid=pid, name=p.name, reason=reason)
        if self.host_id == pid:
            self.host_id = min(self.players.values(), key=lambda q: q.joined).id if self.players else None
        self.lobby_dirty = True
        if not self.players:
            self.reset_to_lobby(now, announce=False)
            return
        if p.in_game and self.phase != "lobby":
            self.out.broadcast({"t": "left", "id": pid, "name": p.name, "colour": p.colour})
            if self.sabotage:
                self.sabotage["held"] = {k: v for k, v in self.sabotage["held"].items() if v != pid}
            if self.meeting:
                self.meeting["votes"].pop(pid, None)
                if self.meeting.get("caller") == pid:
                    self.meeting["caller_left"] = True
            if self.phase in ("play", "reveal"):
                self.check_win(now)
            elif self.phase == "meeting" and self.meeting and self.meeting["stage"] == "vote":
                self._maybe_close_vote(now)
            if self.phase != "lobby" and not self.ingame():
                self.reset_to_lobby(now)

    # ------------------------------------------------------------------ dispatch
    def handle(self, pid, msg, now):
        p = self.players.get(pid)
        if p is None:
            return
        fn = getattr(self, "on_" + msg.get("t", ""), None)
        if fn is None:
            return
        try:
            fn(p, msg, now)
        except (KeyError, TypeError, ValueError, IndexError) as e:
            self.log("bad_msg", pid=pid, t=msg.get("t"), err=repr(e))

    # ------------------------------------------------------------------ lobby messages
    def on_ping(self, p, msg, now):
        self.out.send(p.id, {"t": "pong", "c": msg.get("c")})

    def on_colour(self, p, msg, now):
        c = _key(msg.get("colour"))
        if self.phase == "lobby" and c in self.free_colours(exclude_pid=p.id):
            p.colour = c
            self.lobby_dirty = True

    def on_settings(self, p, msg, now):
        if p.id != self.host_id or self.phase != "lobby":
            return
        changes = msg.get("settings")
        if not isinstance(changes, dict):
            return
        for k, v in changes.items():
            if k in C.DEFAULT_SETTINGS and (isinstance(v, bool) or _num(v)):
                self.settings[k] = C.clamp_setting(k, v)
        self.lobby_dirty = True

    def on_kick(self, p, msg, now):
        target = _key(msg.get("id"))
        if p.id == self.host_id and target in self.players and target != p.id:
            self.out.send(target, {"t": "kicked"})
            self.log("kick", pid=target)
            self.out.items.append(("close", target))

    def on_start(self, p, msg, now):
        if p.id != self.host_id or self.phase != "lobby":
            return
        n = len(self.players)
        if n < self.min_players:
            self.out.send(p.id, {"t": "error", "msg": f"Need at least {self.min_players} players to start"})
            return
        self.start_game(now)

    def on_chat(self, p, msg, now):
        text = _clean_text(msg.get("text"), C.MAX_CHAT_LEN)
        if not text or now - p.last_chat < 0.4:
            return
        p.last_chat = now
        dead = p.in_game and not p.alive and self.phase not in ("lobby", "over")
        if self.phase in ("play", "reveal", "eject") and not dead:
            return  # living players can only talk in meetings
        out = {"t": "chat", "from": p.id, "name": p.name, "colour": p.colour, "text": text, "dead": dead}
        if dead:
            self.out.broadcast(out, only=lambda q: (q.in_game and not q.alive) or not q.in_game)
        else:
            self.out.broadcast(out)

    # ------------------------------------------------------------------ round setup
    def start_game(self, now):
        plist = sorted(self.players.values(), key=lambda q: q.joined)
        n = len(plist)
        want = self.settings["imposters"] or C.auto_imposters(n)
        n_imp = max(1, min(want, C.max_imposters(n), n - 1))
        forced = [pid for pid in (self.force_imposters or []) if pid in self.players]
        if forced:  # test hook
            others = [q for q in plist if q.id not in forced]
            imps = set(forced[:n_imp]) | set(q.id for q in self.rng.sample(others, max(0, n_imp - len(forced))))
        else:
            imps = set(q.id for q in self.rng.sample(plist, n_imp))
        self.round += 1
        self.bodies = []
        self.sabotage = None
        self.meeting = None
        self.eject_info = None
        self.result = None
        self.sab_ready = now + 10.0
        self.emergency_ready = now + self.settings["emergency_cooldown"]
        common = self._pick("common", self.settings["common_tasks"])
        common_steps = {tid: make_task_steps(tid, self.rng) for tid in common}
        spawns = list(self.world.spawns)
        for i, q in enumerate(plist):
            q.reset_round()
            q.in_game = True
            q.role = "imposter" if q.id in imps else "crew"
            q.x, q.y = spawns[i % len(spawns)]
            q.kill_ready = now + ROLE_AND_FIRST_KILL_DELAY
            q.emergencies = self.settings["emergency_meetings"]
            tasks = [(tid, common_steps[tid]) for tid in common]
            tasks += [(tid, make_task_steps(tid, self.rng)) for tid in self._pick("long", self.settings["long_tasks"])]
            tasks += [(tid, make_task_steps(tid, self.rng)) for tid in self._pick("short", self.settings["short_tasks"])]
            q.tasks = [{"id": tid, "name": TASKS[tid]["name"], "steps": [list(s) for s in steps], "step": 0}
                       for tid, steps in tasks]
        public = [q.public() for q in plist]
        for q in plist:
            self.out.send(q.id, {
                "t": "game_start", "round": self.round, "role": q.role,
                "imposters": sorted(imps) if q.imposter else [],
                "n_imposters": n_imp, "tasks": q.tasks, "players": public,
                "x": round(q.x), "y": round(q.y), "ep": q.epoch, "settings": self.settings,
            })
        self.phase = "reveal"
        self.phase_end = now + C.ROLE_REVEAL_SECONDS
        self.lobby_dirty = True
        self.log("start", round=self.round, players=n, imposters=sorted(imps))

    def _pick(self, kind, count):
        pool = [tid for tid, t in TASKS.items() if t["kind"] == kind]
        return self.rng.sample(pool, min(count, len(pool)))

    def reset_to_lobby(self, now, announce=True):
        self.phase = "lobby"
        self.phase_end = None
        self.bodies = []
        self.sabotage = None
        self.meeting = None
        self.eject_info = None
        for q in self.players.values():
            q.reset_round()
        self.lobby_dirty = True
        if announce:
            self.out.broadcast({"t": "to_lobby"})

    # ------------------------------------------------------------------ gameplay messages
    def on_pos(self, p, msg, now):
        if not p.in_game or self.phase not in ("play", "reveal") or p.vent is not None:
            return
        if msg.get("ep") != p.epoch:
            return  # stale update from before a server teleport
        x, y = msg.get("x"), msg.get("y")
        if not (_num(x) and _num(y)):
            return
        p.x = min(max(float(x), 0.0), 5792.0)
        p.y = min(max(float(y), 0.0), 3168.0)
        d = msg.get("d", 0)
        p.dir = d if d in (0, 1, 2, 3) else 0
        p.moving = bool(msg.get("m"))
        p.last_pos = now
        if self.sabotage and self.sabotage["held"]:
            self._release_far_holds()

    def on_kill(self, p, msg, now):
        t = self.players.get(_key(msg.get("target")))
        if (self.phase != "play" or not p.in_game or not p.imposter or not p.alive or p.vent is not None
                or now < p.kill_ready or t is None or not t.in_game or not t.alive or t.imposter
                or t.vent is not None or dist((p.x, p.y), (t.x, t.y)) > C.KILL_RANGE + C.POSITION_SLACK):
            self.out.send(p.id, {"t": "deny", "what": "kill"})
            return
        t.alive = False
        t.moving = False
        self.bodies.append({"id": t.id, "x": round(t.x), "y": round(t.y), "colour": t.colour})
        p.kill_ready = now + self.settings["kill_cooldown"]
        self.teleport(p, t.x, t.y)
        if self.sabotage:
            self.sabotage["held"] = {k: v for k, v in self.sabotage["held"].items() if v != t.id}
        self.out.send(t.id, {"t": "killed", "by": p.colour})
        self.out.send(p.id, {"t": "kill_ok", "target": t.id})
        self.log("kill", killer=p.id, victim=t.id)
        self.check_win(now)

    def on_report(self, p, msg, now):
        body = next((b for b in self.bodies if b["id"] == _key(msg.get("body"))), None)
        if (self.phase != "play" or not p.in_game or not p.alive or p.vent is not None or body is None
                or not self.near(p, (body["x"], body["y"]), C.REPORT_RANGE)):
            self.out.send(p.id, {"t": "deny", "what": "report"})
            return
        self.start_meeting(p, "report", body, now)

    def on_emergency(self, p, msg, now):
        if (self.phase != "play" or not p.in_game or not p.alive or p.vent is not None or p.emergencies <= 0
                or now < self.emergency_ready or (self.sabotage and SABOTAGES[self.sabotage["kind"]]["critical"])
                or not self.near(p, STATIONS["emergency"]["pos"], C.EMERGENCY_RANGE)):
            self.out.send(p.id, {"t": "deny", "what": "emergency"})
            return
        p.emergencies -= 1
        self.start_meeting(p, "emergency", None, now)

    def on_task(self, p, msg, now):
        tid, step = _key(msg.get("task")), _key(msg.get("step"))
        task = next((t for t in p.tasks if t["id"] == tid), None)
        if self.phase != "play" or not p.in_game or task is None or step != task["step"] or task["step"] >= len(task["steps"]):
            return
        station = task["steps"][step][0]
        if not self.near(p, STATIONS[station]["pos"], C.USE_RANGE):
            self.out.send(p.id, {"t": "deny", "what": "task"})
            return
        if p.imposter:
            return  # fake tasks never count
        task["step"] += 1
        self.out.send(p.id, {"t": "task_ok", "task": tid, "step": task["step"]})
        self.log("task", pid=p.id, task=tid, step=task["step"])
        self.check_win(now)

    def on_sabotage(self, p, msg, now):
        kind = _key(msg.get("kind"))
        if (self.phase != "play" or not p.in_game or not p.imposter or kind not in SABOTAGES
                or self.sabotage is not None or now < self.sab_ready):
            self.out.send(p.id, {"t": "deny", "what": "sabotage"})
            return
        crit = SABOTAGES[kind]["critical"]
        dur = C.REACTOR_SECONDS if kind == "reactor" else C.O2_SECONDS if kind == "o2" else None
        self.sabotage = {"kind": kind, "ends": now + dur if crit else None, "done": [], "held": {}}
        self.out.broadcast({"t": "sabotage", "kind": kind, "dur": dur})
        self.log("sabotage", kind=kind, by=p.id)

    def on_fix(self, p, msg, now):
        sab = self.sabotage
        panel = _key(msg.get("panel"))
        if (sab is None or self.phase != "play" or not p.in_game or not p.alive or sab["kind"] == "reactor"
                or panel not in SABOTAGES[sab["kind"]]["panels"] or panel in sab["done"]
                or not self.near(p, STATIONS[panel]["pos"], C.USE_RANGE)):
            return
        sab["done"].append(panel)
        if len(sab["done"]) >= len(SABOTAGES[sab["kind"]]["panels"]):
            self.end_sabotage(now, fixed_by=p.id)

    def on_hold(self, p, msg, now):
        sab = self.sabotage
        panel = _key(msg.get("panel"))
        if sab is None or sab["kind"] != "reactor" or panel not in SABOTAGES["reactor"]["panels"]:
            return
        if msg.get("on") and p.in_game and p.alive and self.phase == "play" and self.near(p, STATIONS[panel]["pos"], C.USE_RANGE):
            if sab["held"].get(panel) in (None, p.id):
                # one player can't hold both scanners
                sab["held"] = {k: v for k, v in sab["held"].items() if v != p.id}
                sab["held"][panel] = p.id
        elif sab["held"].get(panel) == p.id:
            del sab["held"][panel]
        if len(sab["held"]) >= 2:
            self.end_sabotage(now, fixed_by=p.id)

    def _release_far_holds(self):
        sab = self.sabotage
        for panel, holder in list(sab["held"].items()):
            q = self.players.get(holder)
            if q is None or not q.alive or not self.near(q, STATIONS[panel]["pos"], C.USE_RANGE):
                del sab["held"][panel]

    def end_sabotage(self, now, fixed_by=None):
        kind = self.sabotage["kind"]
        self.sabotage = None
        self.sab_ready = now + C.SABOTAGE_COOLDOWN
        self.out.broadcast({"t": "sabotage_end", "kind": kind})
        self.log("sabotage_fixed", kind=kind, by=fixed_by)

    def on_vent(self, p, msg, now):
        act = msg.get("act")
        if self.phase != "play" or not p.in_game or not p.imposter or not p.alive:
            return
        w = self.world
        if act == "enter" and p.vent is None:
            vid = msg.get("id")
            if isinstance(vid, int) and 0 <= vid < len(w.vents) and self.near(p, w.vents[vid], C.VENT_RANGE):
                p.vent = vid
                p.x, p.y = w.vents[vid]
                p.moving = False
                self.out.send(p.id, {"t": "vent_state", "id": vid})
        elif act == "move" and p.vent is not None:
            to = _key(msg.get("to"))
            if to in w.vent_links[p.vent]:
                p.vent = to
                p.x, p.y = w.vents[to]
                self.out.send(p.id, {"t": "vent_state", "id": to})
        elif act == "exit" and p.vent is not None:
            vid = p.vent
            p.vent = None
            self.teleport(p, *w.vent_exit_pos(vid))
            self.out.send(p.id, {"t": "vent_state", "id": None})

    # ------------------------------------------------------------------ meetings
    def start_meeting(self, caller, kind, body, now):
        if self.sabotage:
            kind_s = self.sabotage["kind"]
            self.sabotage = None
            self.sab_ready = now + C.SABOTAGE_COOLDOWN
            self.out.broadcast({"t": "sabotage_end", "kind": kind_s})
        for q in self.ingame():
            if q.vent is not None:
                q.vent = None
                self.out.send(q.id, {"t": "vent_state", "id": None})
            q.moving = False
        disc = self.settings["discussion_time"]
        vote = self.settings["voting_time"]
        self.meeting = {
            "caller": caller.id, "kind": kind, "body": body["colour"] if body else None,
            "stage": "intro", "stage_end": now + C.MEETING_INTRO_SECONDS,
            "discussion": disc, "voting": vote, "votes": {},
        }
        self.phase = "meeting"
        self.phase_end = None
        self.out.broadcast({
            "t": "meeting", "kind": kind, "caller": caller.id, "caller_colour": caller.colour,
            "body": self.meeting["body"], "intro": C.MEETING_INTRO_SECONDS, "discussion": disc, "voting": vote,
            "players": [dict(q.public(), alive=q.alive) for q in sorted(self.ingame(), key=lambda q: q.joined)],
            "anonymous": self.settings["anonymous_votes"],
        })
        self.log("meeting", kind=kind, caller=caller.id)

    def on_vote(self, p, msg, now):
        m = self.meeting
        target = _key(msg.get("target"))
        if (self.phase != "meeting" or m is None or m["stage"] != "vote" or not p.in_game or not p.alive
                or p.id in m["votes"]):
            return
        if target != "skip":
            t = self.players.get(target)
            if t is None or not t.in_game or not t.alive:
                return
        m["votes"][p.id] = target
        self.out.broadcast({"t": "voted", "id": p.id})
        self._maybe_close_vote(now)

    def _maybe_close_vote(self, now):
        m = self.meeting
        voters = [q.id for q in self.ingame() if q.alive]
        if m and m["stage"] == "vote" and all(v in m["votes"] for v in voters):
            self._tally(now)

    def _tally(self, now):
        m = self.meeting
        counts = {}
        for voter, target in m["votes"].items():
            counts.setdefault(target, []).append(voter)
        skip = counts.pop("skip", [])
        ejected = None
        tie = False
        if counts:
            top = max(len(v) for v in counts.values())
            leaders = [t for t, v in counts.items() if len(v) == top]
            if len(leaders) > 1:
                tie = True
            elif top > len(skip):
                ejected = leaders[0]
        m["stage"] = "results"
        m["stage_end"] = now + C.VOTE_RESULTS_SECONDS
        m["ejected"] = ejected
        anon = self.settings["anonymous_votes"]
        self.out.broadcast({
            "t": "vote_result",
            "votes": {str(t): (len(v) if anon else v) for t, v in counts.items()},
            "skip": len(skip) if anon else skip, "ejected": ejected, "tie": tie,
        })
        self.log("vote_result", ejected=ejected, tie=tie, votes={str(k): v for k, v in counts.items()}, skip=skip)

    def _begin_eject(self, now):
        m = self.meeting
        ej = self.players.get(m.get("ejected"))
        info = {"t": "eject", "id": None, "name": None, "colour": None}
        if ej is not None and ej.in_game:
            ej.alive = False
            info.update(id=ej.id, name=ej.name, colour=ej.colour)
            if self.settings["confirm_ejects"]:
                info["was_imposter"] = ej.imposter
        if self.settings["confirm_ejects"]:
            info["remaining"] = len(self.alive_imposters())
        self.out.broadcast(info)
        self.eject_info = info
        self.meeting = None
        self.phase = "eject"
        self.phase_end = now + C.EJECT_SECONDS

    def _resume_play(self, now):
        self.bodies = []
        self.phase = "play"
        self.phase_end = None
        spawns = self.world.spawns
        for i, q in enumerate(sorted(self.ingame(), key=lambda q: q.joined)):
            if q.alive:
                self.teleport(q, *spawns[i % len(spawns)])
            if q.imposter and C.POST_MEETING_KILL_RESET:
                q.kill_ready = now + self.settings["kill_cooldown"]
        self.emergency_ready = now + self.settings["emergency_cooldown"]
        self.out.broadcast({"t": "resume"})

    # ------------------------------------------------------------------ win conditions
    def check_win(self, now):
        if self.phase in ("lobby", "over"):
            return None
        imps = self.alive_imposters()
        crew = self.alive_crew()
        done, total = self.task_progress()
        winner = reason = None
        if not imps:
            winner, reason = "crew", "All impostors are gone"
        elif len(imps) >= len(crew):
            winner, reason = "imposter", "Impostors outnumber the crew"
        elif total > 0 and done >= total:
            winner, reason = "crew", "All tasks completed"
        if winner:
            self.end_game(winner, reason, now)
        return winner

    def end_game(self, winner, reason, now):
        imps = [q for q in self.ingame() if q.imposter]
        self.result = {"winner": winner, "reason": reason}
        self.phase = "over"
        self.phase_end = now + C.GAME_OVER_SECONDS
        self.meeting = None
        if self.sabotage:
            self.sabotage = None
        self.out.broadcast({
            "t": "game_over", "winner": winner, "reason": reason,
            "imposters": [q.public() for q in imps],
            "players": [dict(q.public(), role=q.role, alive=q.alive) for q in self.ingame()],
        })
        self.log("game_over", winner=winner, reason=reason, round=self.round)

    # ------------------------------------------------------------------ tick
    def tick(self, now):
        ph = self.phase
        if ph == "reveal" and now >= self.phase_end:
            self.phase = "play"
            self.phase_end = None
            self.out.broadcast({"t": "play"})
            self.check_win(now)
        elif ph == "play":
            sab = self.sabotage
            if sab and sab["ends"] is not None and now >= sab["ends"]:
                reason = "Reactor meltdown" if sab["kind"] == "reactor" else "Oxygen depleted"
                self.sabotage = None
                self.end_game("imposter", reason, now)
            elif sab and sab["held"]:
                self._release_far_holds()
        elif ph == "meeting":
            m = self.meeting
            if m["stage"] == "intro" and now >= m["stage_end"]:
                if m["discussion"] > 0:
                    m["stage"], m["stage_end"] = "discussion", now + m["discussion"]
                else:
                    m["stage"], m["stage_end"] = "vote", now + m["voting"]
                self.out.broadcast({"t": "meeting_stage", "stage": m["stage"], "dur": m["stage_end"] - now})
            elif m["stage"] == "discussion" and now >= m["stage_end"]:
                m["stage"], m["stage_end"] = "vote", now + m["voting"]
                self.out.broadcast({"t": "meeting_stage", "stage": "vote", "dur": m["voting"]})
            elif m["stage"] == "vote" and now >= m["stage_end"]:
                self._tally(now)
            elif m["stage"] == "results" and now >= m["stage_end"]:
                self._begin_eject(now)
        elif ph == "eject" and now >= self.phase_end:
            if not self.check_win(now):
                self._resume_play(now)
        elif ph == "over" and now >= self.phase_end:
            self.reset_to_lobby(now)

    def snapshot(self, now):
        """Common in-game state (positions etc.). None in the lobby."""
        if self.phase == "lobby":
            return None
        done, total = self.task_progress()
        sab = None
        if self.sabotage:
            s = self.sabotage
            sab = {"k": s["kind"], "rem": None if s["ends"] is None else round(max(0.0, s["ends"] - now), 2),
                   "done": list(s["done"]), "held": list(s["held"])}
        comms_down = bool(self.sabotage and self.sabotage["kind"] == "comms")
        return {
            "t": "snap", "ph": self.phase,
            "pl": [[q.id, round(q.x), round(q.y), q.dir, int(q.moving), int(q.alive), -1 if q.vent is None else q.vent]
                   for q in self.ingame()],
            "bd": [[b["id"], b["x"], b["y"], b["colour"]] for b in self.bodies],
            "tb": None if comms_down else (round(done / total, 4) if total else 0.0),
            "sab": sab,
            "ms": None if not self.meeting else {"st": self.meeting["stage"],
                                                 "rem": round(max(0.0, self.meeting["stage_end"] - now), 2)},
        }

    def personal(self, p, now):
        return {
            "kc": round(max(0.0, p.kill_ready - now), 1) if p.imposter else 0,
            "sc": round(max(0.0, self.sab_ready - now), 1) if p.imposter else 0,
            "em": p.emergencies,
            "ec": round(max(0.0, self.emergency_ready - now), 1),
            "v": p.vent,
            "ep": p.epoch,
        }


# Among Us gives a short kill cooldown at round start
ROLE_AND_FIRST_KILL_DELAY = C.ROLE_REVEAL_SECONDS + 10.0
