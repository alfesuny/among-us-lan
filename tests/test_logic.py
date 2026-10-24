"""Rules tests: drive GameLogic directly with a fake clock (no sockets)."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amongus import config as C  # noqa: E402
from amongus.logic import GameLogic, ROLE_AND_FIRST_KILL_DELAY  # noqa: E402
from amongus.world import STATIONS, SABOTAGES, get_world  # noqa: E402


class Harness:
    def __init__(self, n, seed=1, **settings):
        self.lg = GameLogic(rng=random.Random(seed))
        self.lg.settings.update(settings)
        self.now = 100.0
        self.ids = []
        for i in range(n):
            pid, err = self.lg.join({"t": "hello", "v": C.PROTOCOL_VERSION, "name": f"P{i}"}, self.now)
            assert err is None, err
            self.ids.append(pid)
        self.sent = []

    def msg(self, pid, **m):
        self.lg.handle(pid, m, self.now)
        self.collect()

    def collect(self):
        self.sent.extend(self.lg.out.drain())

    def advance(self, secs, step=0.1):
        end = self.now + secs
        while self.now < end:
            self.now = min(end, self.now + step)
            self.lg.tick(self.now)
            self.collect()

    def start(self):
        self.msg(self.lg.host_id, t="start")
        assert self.lg.phase == "reveal"
        self.advance(C.ROLE_REVEAL_SECONDS + 0.2)
        assert self.lg.phase == "play"

    def p(self, pid):
        return self.lg.players[pid]

    def imps(self):
        return [q for q in self.lg.ingame() if q.imposter]

    def crew(self):
        return [q for q in self.lg.ingame() if not q.imposter]

    def place(self, pid, xy):
        q = self.p(pid)
        self.msg(pid, t="pos", x=xy[0], y=xy[1], ep=q.epoch, d=0, m=0)

    def ready_kill(self):
        self.advance(ROLE_AND_FIRST_KILL_DELAY + 0.5, step=0.5)

    def sent_types(self, pid=None):
        return [it[1]["t"] for it in self.sent if it[0] in (pid, None) or pid is None]

    def last(self, t, pid=None):
        for it in reversed(self.sent):
            if it[0] != "close" and it[1]["t"] == t and (pid is None or it[0] in (pid, None)):
                return it[1]
        return None


class JoinTests(unittest.TestCase):
    def test_names_colours_host(self):
        lg = GameLogic()
        a, _ = lg.join({"v": C.PROTOCOL_VERSION, "name": "Bob", "colour": "Lime"}, 0)
        b, _ = lg.join({"v": C.PROTOCOL_VERSION, "name": "bob", "colour": "Lime"}, 1)
        self.assertEqual(lg.players[a].colour, "Lime")
        self.assertNotEqual(lg.players[b].colour, "Lime")
        self.assertEqual(lg.players[b].name, "bob2")
        self.assertEqual(lg.host_id, a)
        lg.leave(a, 2)
        self.assertEqual(lg.host_id, b)

    def test_version_and_full(self):
        lg = GameLogic()
        _, err = lg.join({"v": -1, "name": "x"}, 0)
        self.assertIn("Version", err)
        for i in range(C.MAX_PLAYERS):
            pid, err = lg.join({"v": C.PROTOCOL_VERSION, "name": f"n{i}"}, i)
            self.assertIsNone(err)
        self.assertEqual(len({p.colour for p in lg.players.values()}), C.MAX_PLAYERS)
        _, err = lg.join({"v": C.PROTOCOL_VERSION, "name": "late"}, 99)
        self.assertEqual(err, "Server is full")

    def test_name_sanitising(self):
        lg = GameLogic()
        pid, _ = lg.join({"v": C.PROTOCOL_VERSION, "name": "\x00\x1b[31m  " + "x" * 50}, 0)
        name = lg.players[pid].name
        self.assertLessEqual(len(name), C.MAX_NAME_LEN)
        self.assertNotIn("\x1b", name)

    def test_settings_host_only_and_clamped(self):
        h = Harness(4)
        other = h.ids[1]
        h.msg(other, t="settings", settings={"kill_cooldown": 11})
        self.assertEqual(h.lg.settings["kill_cooldown"], C.DEFAULT_SETTINGS["kill_cooldown"])
        h.msg(h.lg.host_id, t="settings", settings={"kill_cooldown": 9999, "bogus": 1, "confirm_ejects": False})
        self.assertEqual(h.lg.settings["kill_cooldown"], 60)
        self.assertFalse(h.lg.settings["confirm_ejects"])
        self.assertNotIn("bogus", h.lg.settings)

    def test_colour_change(self):
        h = Harness(2)
        taken = h.p(h.ids[1]).colour
        h.msg(h.ids[0], t="colour", colour=taken)
        self.assertNotEqual(h.p(h.ids[0]).colour, taken)
        h.msg(h.ids[0], t="colour", colour="Cyan")
        self.assertEqual(h.p(h.ids[0]).colour, "Cyan")


class StartTests(unittest.TestCase):
    def test_min_players(self):
        h = Harness(2)
        h.msg(h.lg.host_id, t="start")
        self.assertEqual(h.lg.phase, "lobby")
        self.assertIsNotNone(h.last("error"))

    def test_only_host_starts(self):
        h = Harness(4)
        h.msg(h.ids[2], t="start")
        self.assertEqual(h.lg.phase, "lobby")

    def test_auto_imposter_counts(self):
        for n in range(3, C.MAX_PLAYERS + 1):
            h = Harness(n, seed=n)
            h.start()
            self.assertEqual(len(h.imps()), 1 if n <= 6 else 2, n)

    def test_manual_imposters_clamped(self):
        h = Harness(5, imposters=3)
        h.start()
        self.assertEqual(len(h.imps()), 1)
        h = Harness(10, imposters=3)
        h.start()
        self.assertEqual(len(h.imps()), 3)

    def test_roles_only_revealed_to_imposters(self):
        h = Harness(8)
        h.start()
        for it in h.sent:
            if it[0] != "close" and it[1]["t"] == "game_start":
                pid, m = it[0], it[1]
                if h.p(pid).imposter:
                    self.assertEqual(len(m["imposters"]), 2)
                    self.assertEqual(m["role"], "imposter")
                else:
                    self.assertEqual(m["imposters"], [])
                    self.assertEqual(m["role"], "crew")

    def test_task_assignment(self):
        h = Harness(6, common_tasks=1, long_tasks=1, short_tasks=3)
        h.start()
        commons = set()
        for q in h.lg.ingame():
            self.assertEqual(len(q.tasks), 5)
            commons.add(q.tasks[0]["id"])
            for t in q.tasks:
                for station, _mg in t["steps"]:
                    self.assertIn(station, STATIONS)
        self.assertEqual(len(commons), 1)

    def test_spawns_unique_and_free(self):
        h = Harness(12)
        h.start()
        pos = {(round(q.x), round(q.y)) for q in h.lg.ingame()}
        self.assertEqual(len(pos), 12)
        w = get_world()
        for x, y in pos:
            self.assertFalse(w.collider.blocked(x, y))


class KillTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(5)
        self.h.start()
        self.imp = self.h.imps()[0]
        self.crew = self.h.crew()

    def test_cooldown_and_range(self):
        h, imp, v = self.h, self.imp, self.crew[0]
        h.place(v.id, (3320, 600))
        h.place(imp.id, (3340, 600))
        h.msg(imp.id, t="kill", target=v.id)
        self.assertTrue(v.alive, "kill before first cooldown must fail")
        h.ready_kill()
        h.place(v.id, (3320, 600))
        h.place(imp.id, (3320 + C.KILL_RANGE + C.POSITION_SLACK + 50, 600))
        h.msg(imp.id, t="kill", target=v.id)
        self.assertTrue(v.alive, "out-of-range kill must fail")
        h.place(imp.id, (3340, 600))
        h.msg(imp.id, t="kill", target=v.id)
        self.assertFalse(v.alive)
        self.assertEqual(len(h.lg.bodies), 1)
        self.assertEqual(h.last("killed", v.id)["by"], imp.colour)
        # imposter snapped onto the body and got a fresh cooldown
        self.assertEqual((round(imp.x), round(imp.y)), (3320, 600))
        v2 = self.crew[1]
        h.place(v2.id, (3320, 610))
        h.msg(imp.id, t="kill", target=v2.id)
        self.assertTrue(v2.alive, "second kill inside cooldown must fail")

    def test_crew_cannot_kill_and_imposter_cannot_kill_imposter(self):
        h = Harness(8, seed=3)
        h.start()
        h.ready_kill()
        imps, crew = h.imps(), h.crew()
        for q in h.lg.ingame():
            h.place(q.id, (3320, 600))
        h.msg(crew[0].id, t="kill", target=crew[1].id)
        self.assertTrue(crew[1].alive)
        h.msg(imps[0].id, t="kill", target=imps[1].id)
        self.assertTrue(imps[1].alive)

    def test_stale_position_ignored_after_teleport(self):
        h, imp = self.h, self.imp
        old_ep = imp.epoch
        h.lg.teleport(imp, 3000, 600)
        h.msg(imp.id, t="pos", x=1, y=1, ep=old_ep)
        self.assertEqual((imp.x, imp.y), (3000, 600))

    def test_imposter_parity_wins(self):
        h, imp = self.h, self.imp
        h.ready_kill()
        victims = self.crew[:3]
        for v in victims:
            h.place(v.id, (3320, 600))
            h.place(imp.id, (3330, 600))
            h.msg(imp.id, t="kill", target=v.id)
            self.assertFalse(v.alive)
            if h.lg.phase == "over":
                break
            h.advance(h.lg.settings["kill_cooldown"] + 0.5, step=0.5)
        self.assertEqual(h.lg.phase, "over")
        self.assertEqual(h.lg.result["winner"], "imposter")


class MeetingTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(6, discussion_time=5, voting_time=20)
        self.h.start()
        self.imp = self.h.imps()[0]
        self.crew = self.h.crew()

    def call_emergency(self, who):
        h = self.h
        h.advance(h.lg.settings["emergency_cooldown"] + 0.5, step=0.5)
        h.place(who.id, STATIONS["emergency"]["pos"])
        h.msg(who.id, t="emergency")
        self.assertEqual(h.lg.phase, "meeting")
        h.advance(C.MEETING_INTRO_SECONDS + 5 + 0.2)
        self.assertEqual(h.lg.meeting["stage"], "vote")

    def test_majority_ejects_imposter_and_crew_wins(self):
        h = self.h
        self.call_emergency(self.crew[0])
        for q in h.lg.ingame():
            h.msg(q.id, t="vote", target=self.imp.id if q is not self.imp else self.crew[0].id)
        self.assertEqual(h.lg.meeting["stage"], "results", "all votes in should close voting early")
        h.advance(C.VOTE_RESULTS_SECONDS + 0.2)
        self.assertEqual(h.lg.phase, "eject")
        ej = h.last("eject")
        self.assertEqual(ej["id"], self.imp.id)
        self.assertTrue(ej["was_imposter"])
        self.assertEqual(ej["remaining"], 0)
        h.advance(C.EJECT_SECONDS + 0.2)
        self.assertEqual(h.lg.phase, "over")
        self.assertEqual(h.lg.result["winner"], "crew")

    def test_tie_and_skip(self):
        h = self.h
        self.call_emergency(self.crew[0])
        a, b = self.crew[0], self.crew[1]
        ingame = h.lg.ingame()
        for i, q in enumerate(ingame):
            h.msg(q.id, t="vote", target=(a.id if i % 2 == 0 else b.id))
        res = h.last("vote_result")
        self.assertTrue(res["tie"])
        self.assertIsNone(res["ejected"])
        h.advance(C.VOTE_RESULTS_SECONDS + C.EJECT_SECONDS + 0.5)
        self.assertEqual(h.lg.phase, "play")
        self.assertTrue(all(q.alive for q in ingame))
        # skip majority
        self.call_emergency(self.crew[2])
        for i, q in enumerate(h.lg.ingame()):
            h.msg(q.id, t="vote", target="skip" if i < 4 else a.id)
        self.assertIsNone(h.last("vote_result")["ejected"])

    def test_vote_timeout_and_double_vote(self):
        h = self.h
        self.call_emergency(self.crew[0])
        h.msg(self.crew[0].id, t="vote", target=self.crew[1].id)
        h.msg(self.crew[0].id, t="vote", target=self.crew[2].id)  # ignored
        self.assertEqual(h.lg.meeting["votes"][self.crew[0].id], self.crew[1].id)
        h.advance(20.5)
        res = h.last("vote_result")
        self.assertEqual(res["ejected"], self.crew[1].id)

    def test_dead_cannot_vote_or_be_voted(self):
        h = self.h
        h.ready_kill()
        v = self.crew[0]
        h.place(v.id, (3320, 600))
        h.place(self.imp.id, (3325, 600))
        h.msg(self.imp.id, t="kill", target=v.id)
        self.assertFalse(v.alive)
        reporter = self.crew[1]
        h.place(reporter.id, (3330, 640))
        h.msg(reporter.id, t="report", body=v.id)
        self.assertEqual(h.lg.phase, "meeting")
        self.assertEqual(h.last("meeting")["body"], v.colour)
        h.advance(C.MEETING_INTRO_SECONDS + 5.2)
        h.msg(v.id, t="vote", target="skip")
        self.assertNotIn(v.id, h.lg.meeting["votes"])
        h.msg(reporter.id, t="vote", target=v.id)
        self.assertNotIn(reporter.id, h.lg.meeting["votes"])

    def test_emergency_limits(self):
        h = self.h
        c = self.crew[0]
        h.place(c.id, STATIONS["emergency"]["pos"])
        h.msg(c.id, t="emergency")
        self.assertEqual(h.lg.phase, "play", "emergency cooldown at round start")
        self.call_emergency(c)
        h.advance(C.MEETING_INTRO_SECONDS + 5 + 20 + C.VOTE_RESULTS_SECONDS + C.EJECT_SECONDS + 1)
        self.assertEqual(h.lg.phase, "play")
        h.advance(h.lg.settings["emergency_cooldown"] + 1)
        h.place(c.id, STATIONS["emergency"]["pos"])
        h.msg(c.id, t="emergency")
        self.assertEqual(h.lg.phase, "play", "only one emergency per player by default")
        self.assertEqual(h.last("deny", c.id)["what"], "emergency")

    def test_after_meeting_everyone_teleported_and_bodies_cleared(self):
        h = self.h
        h.lg.bodies.append({"id": 999, "x": 1, "y": 1, "colour": "Red"})
        self.call_emergency(self.crew[0])
        h.advance(20 + C.VOTE_RESULTS_SECONDS + C.EJECT_SECONDS + 1)
        self.assertEqual(h.lg.phase, "play")
        self.assertEqual(h.lg.bodies, [])
        spawns = set(get_world().spawns)
        for q in h.lg.ingame():
            self.assertIn((round(q.x), round(q.y)), spawns)


class TaskTests(unittest.TestCase):
    def test_tasks_complete_wins(self):
        h = Harness(4, common_tasks=1, long_tasks=1, short_tasks=1)
        h.start()
        for q in h.crew():
            for t in q.tasks:
                for i, (station, _mg) in enumerate(t["steps"]):
                    h.msg(q.id, t="task", task=t["id"], step=i)  # too far away: denied
                    self.assertEqual(t["step"], i)
                    h.place(q.id, h.lg.world.nearest_free(*STATIONS[station]["pos"]))
                    h.msg(q.id, t="task", task=t["id"], step=i + 1)  # wrong step number: ignored
                    h.msg(q.id, t="task", task=t["id"], step=i)
                    self.assertEqual(t["step"], i + 1)
        self.assertEqual(h.lg.phase, "over")
        self.assertEqual(h.lg.result["reason"], "All tasks completed")

    def test_imposter_fake_tasks_do_not_count(self):
        h = Harness(4)
        h.start()
        imp = h.imps()[0]
        t = imp.tasks[0]
        h.place(imp.id, h.lg.world.nearest_free(*STATIONS[t["steps"][0][0]]["pos"]))
        h.msg(imp.id, t="task", task=t["id"], step=0)
        self.assertEqual(t["step"], 0)

    def test_ghost_tasks_count(self):
        h = Harness(5, short_tasks=1, long_tasks=0, common_tasks=0)
        h.start()
        h.ready_kill()
        imp, v = h.imps()[0], h.crew()[0]
        h.place(v.id, (3320, 600))
        h.place(imp.id, (3320, 600))
        h.msg(imp.id, t="kill", target=v.id)
        t = v.tasks[0]
        h.place(v.id, h.lg.world.nearest_free(*STATIONS[t["steps"][0][0]]["pos"]))
        h.msg(v.id, t="task", task=t["id"], step=0)
        self.assertEqual(t["step"], 1)


class SabotageTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(6)
        self.h.start()
        self.imp = self.h.imps()[0]
        self.crew = self.h.crew()
        self.h.advance(10.5, step=0.5)

    def test_lights_fix_and_cooldown(self):
        h = self.h
        self.h.msg(self.crew[0].id, t="sabotage", kind="lights")
        self.assertIsNone(h.lg.sabotage)
        h.msg(self.imp.id, t="sabotage", kind="lights")
        self.assertEqual(h.lg.sabotage["kind"], "lights")
        h.msg(self.imp.id, t="sabotage", kind="o2")  # one at a time
        self.assertEqual(h.lg.sabotage["kind"], "lights")
        fixer = self.crew[0]
        h.place(fixer.id, h.lg.world.nearest_free(*STATIONS["fix_lights"]["pos"]))
        h.msg(fixer.id, t="fix", panel="fix_lights")
        self.assertIsNone(h.lg.sabotage)
        h.msg(self.imp.id, t="sabotage", kind="comms")
        self.assertIsNone(h.lg.sabotage, "sabotage cooldown")
        h.advance(C.SABOTAGE_COOLDOWN + 0.5, step=0.5)
        h.msg(self.imp.id, t="sabotage", kind="comms")
        self.assertEqual(h.lg.sabotage["kind"], "comms")
        snap = h.lg.snapshot(h.now)
        self.assertIsNone(snap["tb"], "comms hides the task bar")

    def test_o2_needs_both_panels(self):
        h = self.h
        h.msg(self.imp.id, t="sabotage", kind="o2")
        a, b = self.crew[0], self.crew[1]
        h.place(a.id, h.lg.world.nearest_free(*STATIONS["fix_o2_a"]["pos"]))
        h.msg(a.id, t="fix", panel="fix_o2_a")
        self.assertIsNotNone(h.lg.sabotage)
        h.msg(a.id, t="fix", panel="fix_o2_b")  # too far
        self.assertIsNotNone(h.lg.sabotage)
        h.place(b.id, h.lg.world.nearest_free(*STATIONS["fix_o2_b"]["pos"]))
        h.msg(b.id, t="fix", panel="fix_o2_b")
        self.assertIsNone(h.lg.sabotage)

    def test_reactor_needs_two_people_simultaneously(self):
        h = self.h
        h.msg(self.imp.id, t="sabotage", kind="reactor")
        a, b = self.crew[0], self.crew[1]
        pa = h.lg.world.nearest_free(*STATIONS["fix_reactor_a"]["pos"])
        pb = h.lg.world.nearest_free(*STATIONS["fix_reactor_b"]["pos"])
        h.place(a.id, pa)
        h.msg(a.id, t="hold", panel="fix_reactor_a", on=True)
        h.msg(a.id, t="hold", panel="fix_reactor_b", on=True)  # can't hold both
        self.assertEqual(h.lg.sabotage["held"], {"fix_reactor_a": a.id})
        h.msg(a.id, t="hold", panel="fix_reactor_a", on=False)
        h.place(b.id, pb)
        h.msg(b.id, t="hold", panel="fix_reactor_b", on=True)
        self.assertIsNotNone(h.lg.sabotage, "not simultaneous")
        h.msg(a.id, t="hold", panel="fix_reactor_a", on=True)
        self.assertIsNone(h.lg.sabotage)

    def test_reactor_hold_released_when_walking_away(self):
        h = self.h
        h.msg(self.imp.id, t="sabotage", kind="reactor")
        a = self.crew[0]
        h.place(a.id, h.lg.world.nearest_free(*STATIONS["fix_reactor_a"]["pos"]))
        h.msg(a.id, t="hold", panel="fix_reactor_a", on=True)
        h.place(a.id, (3320, 600))
        self.assertEqual(h.lg.sabotage["held"], {})

    def test_critical_timeout_imposter_wins(self):
        h = self.h
        h.msg(self.imp.id, t="sabotage", kind="reactor")
        h.advance(C.REACTOR_SECONDS + 0.5, step=0.5)
        self.assertEqual(h.lg.phase, "over")
        self.assertEqual(h.lg.result, {"winner": "imposter", "reason": "Reactor meltdown"})

    def test_meeting_clears_sabotage_and_report_allowed_during_critical(self):
        h = self.h
        h.ready_kill()
        v, r = self.crew[0], self.crew[1]
        h.place(v.id, (3320, 600))
        h.place(self.imp.id, (3320, 600))
        h.msg(self.imp.id, t="kill", target=v.id)
        h.msg(self.imp.id, t="sabotage", kind="o2")
        self.assertIsNotNone(h.lg.sabotage)
        h.place(r.id, STATIONS["emergency"]["pos"])
        h.msg(r.id, t="emergency")
        self.assertEqual(h.lg.phase, "play", "no emergency button during critical sabotage")
        h.place(r.id, (3330, 620))
        h.msg(r.id, t="report", body=v.id)
        self.assertEqual(h.lg.phase, "meeting")
        self.assertIsNone(h.lg.sabotage)


class VentTests(unittest.TestCase):
    def test_vent_cycle(self):
        h = Harness(4)
        h.start()
        imp, crew = h.imps()[0], h.crew()[0]
        w = get_world()
        h.place(imp.id, w.vent_exit_pos(0))
        h.msg(crew.id, t="vent", act="enter", id=0)
        self.assertIsNone(crew.vent)
        h.msg(imp.id, t="vent", act="enter", id=0)
        self.assertEqual(imp.vent, 0)
        h.msg(imp.id, t="pos", x=10, y=10, ep=imp.epoch)  # moving is ignored in a vent
        self.assertEqual((imp.x, imp.y), w.vents[0])
        nxt = w.vent_links[0][0]
        h.msg(imp.id, t="vent", act="move", to=nxt)
        self.assertEqual(imp.vent, nxt)
        bad = next(i for i in range(len(w.vents)) if i not in w.vent_links[nxt] and i != nxt)
        h.msg(imp.id, t="vent", act="move", to=bad)
        self.assertEqual(imp.vent, nxt)
        h.msg(imp.id, t="vent", act="exit")
        self.assertIsNone(imp.vent)
        self.assertFalse(w.collider.blocked(imp.x, imp.y))

    def test_all_vents_linked_both_ways(self):
        w = get_world()
        for a, links in w.vent_links.items():
            self.assertTrue(links)
            for b in links:
                self.assertIn(a, w.vent_links[b])


class WorldTests(unittest.TestCase):
    """Every station, vent exit and spawn must be usable on the real map."""

    def test_stations_reachable_on_foot(self):
        from amongus.world import room_at
        w = get_world()
        start = w.nearest_walkable_cell(*w.spawns[0])
        for sid, s in STATIONS.items():
            rng = C.EMERGENCY_RANGE if sid == "emergency" else C.USE_RANGE
            field = w.flow_field(s["pos"], rng - 20)
            self.assertGreaterEqual(field[start[0]][start[1]], 0, f"station {sid} unreachable")
            self.assertEqual(room_at(*s["pos"]), s["label"], f"station {sid} label/room mismatch")

    def test_vent_exits_and_spawns(self):
        w = get_world()
        start = w.nearest_walkable_cell(*w.spawns[0])
        for i in range(len(w.vents)):
            ex = w.vent_exit_pos(i)
            self.assertFalse(w.collider.blocked(*ex), f"vent {i} exit inside a wall")
            self.assertGreaterEqual(w.flow_field(ex, 40)[start[0]][start[1]], 0, f"vent {i} exit unreachable")
        self.assertEqual(len(set(w.spawns)), len(w.spawns))
        for s in w.spawns:
            self.assertFalse(w.collider.blocked(*s))

    def test_every_task_and_sabotage_uses_known_stations(self):
        from amongus.world import TASKS, WIRING_PANELS
        for tid, t in TASKS.items():
            for station, _mg in (t["steps"] or [(p, "wiring") for p in WIRING_PANELS]):
                self.assertIn(station, STATIONS, tid)
        for kind, s in SABOTAGES.items():
            for p in s["panels"]:
                self.assertIn(p, STATIONS, kind)


class DisconnectTests(unittest.TestCase):
    def test_imposter_leaving_gives_crew_win(self):
        h = Harness(5)
        h.start()
        imp = h.imps()[0]
        h.lg.leave(imp.id, h.now)
        h.collect()
        self.assertEqual(h.lg.result["winner"], "crew")

    def test_leaving_mid_vote_closes_vote(self):
        h = Harness(6, discussion_time=0)
        h.start()
        h.advance(h.lg.settings["emergency_cooldown"] + 1)
        crew = h.crew()
        h.place(crew[0].id, STATIONS["emergency"]["pos"])
        h.msg(crew[0].id, t="emergency")
        h.advance(C.MEETING_INTRO_SECONDS + 0.2)
        everyone = h.lg.ingame()
        laggard = crew[-1]
        for q in everyone:
            if q is not laggard:
                h.msg(q.id, t="vote", target="skip")
        self.assertEqual(h.lg.meeting["stage"], "vote")
        h.lg.leave(laggard.id, h.now)
        self.assertEqual(h.lg.meeting["stage"], "results")

    def test_everyone_leaving_resets(self):
        h = Harness(3)
        h.start()
        for pid in list(h.ids):
            h.lg.leave(pid, h.now)
        self.assertEqual(h.lg.phase, "lobby")
        self.assertIsNone(h.lg.host_id)

    def test_join_mid_game_spectates_then_plays_next_round(self):
        h = Harness(4)
        h.start()
        late, _ = h.lg.join({"v": C.PROTOCOL_VERSION, "name": "late"}, h.now)
        h.collect()
        self.assertFalse(h.p(late).in_game)
        self.assertEqual(h.last("spectate", late)["phase"], "play")
        h.lg.end_game("crew", "test", h.now)
        h.advance(C.GAME_OVER_SECONDS + 0.2)
        self.assertEqual(h.lg.phase, "lobby")
        h.msg(h.lg.host_id, t="start")
        self.assertTrue(h.p(late).in_game)


class ChatTests(unittest.TestCase):
    def test_chat_routing(self):
        h = Harness(5)
        h.msg(h.ids[0], t="chat", text="hello lobby")
        self.assertEqual(h.last("chat")["text"], "hello lobby")
        h.start()
        h.sent.clear()
        alive = h.crew()[0]
        h.msg(alive.id, t="chat", text="no talking")
        self.assertIsNone(h.last("chat"), "living players can't chat during play")
        h.ready_kill()
        imp, v = h.imps()[0], h.crew()[1]
        h.place(v.id, (3320, 600))
        h.place(imp.id, (3320, 600))
        h.msg(imp.id, t="kill", target=v.id)
        h.now += 1
        h.msg(v.id, t="chat", text="boo")
        item = next(it for it in h.sent if it[0] is None and it[1]["t"] == "chat")
        self.assertTrue(item[1]["dead"])
        only = item[2]
        self.assertTrue(only(v))
        self.assertFalse(only(alive))

    def test_chat_rate_limit(self):
        h = Harness(3)
        for i in range(5):
            h.msg(h.ids[0], t="chat", text=f"m{i}")
        self.assertEqual(sum(1 for it in h.sent if it[1]["t"] == "chat"), 1)


class GameOverTests(unittest.TestCase):
    def test_returns_to_lobby(self):
        h = Harness(4)
        h.start()
        h.lg.end_game("crew", "test", h.now)
        h.collect()
        self.assertEqual(h.last("game_over")["winner"], "crew")
        h.advance(C.GAME_OVER_SECONDS + 0.2)
        self.assertEqual(h.lg.phase, "lobby")
        self.assertTrue(all(not q.in_game for q in h.lg.players.values()))
        h.start()  # can play again


class FuzzTests(unittest.TestCase):
    def test_random_garbage_never_raises(self):
        rng = random.Random(7)
        h = Harness(8)
        values = [None, 0, -1, 1.5, float("nan"), float("inf"), "x", "skip", [], {}, [1, 2], {"a": 1}, True,
                  10 ** 30, "fix_lights", "fix_reactor_a", "reactor", 1]
        types = ["pos", "kill", "report", "emergency", "vote", "task", "sabotage", "fix", "hold", "vent", "chat",
                 "colour", "settings", "start", "kick", "ping", "nonsense", ""]
        phases = set()
        for i in range(40000):
            pid = rng.choice(h.ids + [12345])
            m = {"t": rng.choice(types)}
            for k in ("x", "y", "target", "body", "task", "step", "kind", "panel", "on", "act", "id", "to",
                      "text", "colour", "settings", "ep", "d", "m"):
                if rng.random() < 0.3:
                    m[k] = rng.choice(values + h.ids)
            if m["t"] == "pos" and rng.random() < 0.5:  # keep players clustered so kills/reports happen
                q = h.lg.players.get(pid)
                m.update(x=3320 + rng.uniform(-60, 60), y=600 + rng.uniform(-60, 60), ep=q.epoch if q else 0)
            h.lg.handle(pid, m, h.now)
            if i % 20 == 0:
                h.now += 0.5
                h.lg.tick(h.now)
            h.lg.out.drain()
            phases.add(h.lg.phase)
            if h.lg.phase == "lobby":
                h.lg.handle(h.lg.host_id, {"t": "start"}, h.now)
        bad = [e for e in h.lg.events if e[0] == "bad_msg"]
        self.assertEqual(bad, [])
        self.assertTrue({"lobby", "play", "meeting"} <= phases, phases)


if __name__ == "__main__":
    unittest.main()
