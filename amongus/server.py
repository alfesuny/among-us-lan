"""Single-threaded TCP game server (selectors) with UDP LAN discovery.

Run standalone:   python server.py [--port 4321] [--name "My Game"]
or in-process:    Server(...).start(); threading.Thread(target=srv.run).start()
"""
import argparse
import logging
import selectors
import socket
import threading
import time

from . import config as C
from .discovery import answer, local_ipv4s, make_responder
from .logic import GameLogic
from .protocol import FrameReader, ProtocolError, encode

log = logging.getLogger("amongus.server")


class Conn:
    __slots__ = ("sock", "addr", "reader", "out", "pid", "last_recv", "closed", "want_write")

    def __init__(self, sock, addr, now):
        self.sock = sock
        self.addr = addr
        self.reader = FrameReader()
        self.out = bytearray()
        self.pid = None
        self.last_recv = now
        self.closed = False
        self.want_write = False


class Server:
    def __init__(self, port=C.TCP_PORT, bind="", name=None, discovery=True, logic=None,
                 discovery_port=C.DISCOVERY_PORT):
        self.port = port
        self.bind = bind
        self.name = name or (socket.gethostname()[:20] + "'s game")
        self.discovery = discovery
        self.discovery_port = discovery_port
        self.logic = logic or GameLogic()
        self.sel = selectors.DefaultSelector()
        self.listener = None
        self.udp = None
        self.conns = {}          # sock -> Conn
        self.by_pid = {}         # pid -> Conn
        self.stop_event = threading.Event()
        self.started = threading.Event()
        self.stats = {"ticks": 0, "tick_time_max": 0.0, "tick_time_total": 0.0, "bytes_out": 0,
                      "bytes_in": 0, "msgs_in": 0, "msgs_out": 0, "accepted": 0, "dropped": 0, "errors": 0,
                      "protocol_errors": 0, "handler_errors": 0}
        self.ips = local_ipv4s()
        self.logic.info_extra = {"ips": self.ips, "port": port, "server_name": self.name}

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: refuse to share the port with another server
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind((self.bind, self.port))
        ls.listen(64)
        ls.setblocking(False)
        self.port = ls.getsockname()[1]
        self.logic.info_extra["port"] = self.port
        self.listener = ls
        self.sel.register(ls, selectors.EVENT_READ, "listen")
        if self.discovery:
            self.udp = make_responder(self.discovery_port)
            if self.udp is not None:
                self.sel.register(self.udp, selectors.EVENT_READ, "udp")
            else:
                log.warning("discovery port %s busy; LAN browsing disabled for this server", self.discovery_port)
        self.started.set()
        return self

    def stop(self):
        self.stop_event.set()

    def close(self):
        for c in list(self.conns.values()):
            self._close(c, "server shutdown", notify=False)
        for s in (self.listener, self.udp):
            if s is not None:
                try:
                    self.sel.unregister(s)
                except (KeyError, ValueError):
                    pass
                s.close()
        self.listener = self.udp = None
        self.sel.close()

    def run(self):
        if self.listener is None:
            self.start()
        period = 1.0 / C.SERVER_TICK_HZ
        next_tick = time.perf_counter()
        try:
            while not self.stop_event.is_set():
                now = time.perf_counter()
                self._poll(max(0.0, min(period, next_tick - now)))
                now = time.perf_counter()
                if now >= next_tick:
                    t0 = time.perf_counter()
                    self._tick(now)
                    dt = time.perf_counter() - t0
                    self.stats["ticks"] += 1
                    self.stats["tick_time_total"] += dt
                    self.stats["tick_time_max"] = max(self.stats["tick_time_max"], dt)
                    next_tick += period
                    if now - next_tick > 0.5:  # fell far behind (e.g. machine asleep): don't spiral
                        next_tick = now + period
        finally:
            self.close()

    # ------------------------------------------------------------------ I/O
    def _poll(self, timeout):
        try:
            events = self.sel.select(timeout)
        except OSError:
            events = []
        now = time.perf_counter()
        for key, mask in events:
            if key.data == "listen":
                self._accept(now)
            elif key.data == "udp":
                answer(self.udp, self._discovery_info())
            else:
                conn = key.data
                if mask & selectors.EVENT_READ and not conn.closed:
                    self._read(conn, now)
                if mask & selectors.EVENT_WRITE and not conn.closed:
                    self._flush(conn)

    def _discovery_info(self):
        lg = self.logic
        return {"game": "amongus", "name": self.name, "port": self.port, "players": len(lg.players),
                "max": C.MAX_PLAYERS, "phase": lg.phase, "version": C.GAME_VERSION,
                "protocol": C.PROTOCOL_VERSION, "ips": self.ips}

    def _accept(self, now):
        for _ in range(16):
            try:
                sock, addr = self.listener.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            sock.setblocking(False)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
            c = Conn(sock, addr, now)
            self.conns[sock] = c
            self.sel.register(sock, selectors.EVENT_READ, c)
            self.stats["accepted"] += 1
            log.info("connection from %s:%s", *addr)

    def _read(self, c, now):
        try:
            data = c.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError as e:
            self._close(c, f"recv error: {e}")
            return
        if not data:
            self._close(c, "disconnected")
            return
        c.last_recv = now
        self.stats["bytes_in"] += len(data)
        try:
            msgs = c.reader.feed(data)
        except ProtocolError as e:
            self.stats["protocol_errors"] += 1
            self._close(c, f"protocol error: {e}")
            return
        for msg in msgs:
            self.stats["msgs_in"] += 1
            if c.pid is None:
                if msg.get("t") != "hello":
                    self._close(c, "expected hello")
                    return
                pid, err = self.logic.join(msg, now)
                if err:
                    self._send_raw(c, encode({"t": "error", "msg": err, "fatal": True}))
                    self._flush(c)
                    self._close(c, err, notify=False)
                    return
                c.pid = pid
                self.by_pid[pid] = c
            else:
                try:
                    self.logic.handle(c.pid, msg, now)
                except Exception:  # a rules bug must never take the whole server down
                    self.stats["handler_errors"] += 1
                    log.exception("error handling %s from %s", msg.get("t"), c.pid)
            if c.closed:
                return
        self._dispatch()

    def _send_raw(self, c, data):
        if c.closed:
            return
        c.out += data
        self.stats["bytes_out"] += len(data)
        self.stats["msgs_out"] += 1
        if len(c.out) > C.MAX_OUTBUF_BYTES:
            self._close(c, "client too slow (send buffer overflow)")
            return
        if not c.want_write:
            self._flush(c)

    def _flush(self, c):
        while c.out:
            try:
                n = c.sock.send(c.out)
            except (BlockingIOError, InterruptedError):
                break
            except OSError as e:
                self._close(c, f"send error: {e}")
                return
            if n <= 0:
                break
            del c.out[:n]
        want = bool(c.out)
        if want != c.want_write and not c.closed:
            c.want_write = want
            events = selectors.EVENT_READ | (selectors.EVENT_WRITE if want else 0)
            try:
                self.sel.modify(c.sock, events, c)
            except (KeyError, ValueError, OSError):
                pass

    def _close(self, c, reason, notify=True):
        if c.closed:
            return
        c.closed = True
        try:
            self.sel.unregister(c.sock)
        except (KeyError, ValueError, OSError):
            pass
        try:
            c.sock.close()
        except OSError:
            pass
        self.conns.pop(c.sock, None)
        if c.pid is not None:
            self.by_pid.pop(c.pid, None)
            self.stats["dropped"] += 1
            log.info("player %s left: %s", c.pid, reason)
            self.logic.leave(c.pid, time.perf_counter(), reason)
            if notify:
                self._dispatch()

    # ------------------------------------------------------------------ logic glue
    def _dispatch(self):
        lg = self.logic
        for item in lg.out.drain():
            if item[0] == "close":
                c = self.by_pid.get(item[1])
                if c:
                    self._flush(c)
                    self._close(c, "kicked")
                continue
            pid, msg = item[0], item[1]
            data = encode(msg)
            if pid is not None:
                c = self.by_pid.get(pid)
                if c:
                    self._send_raw(c, data)
            else:
                only = item[2] if len(item) > 2 else None
                for c in list(self.by_pid.values()):
                    if only is None or (c.pid in lg.players and only(lg.players[c.pid])):
                        self._send_raw(c, data)
        if lg.lobby_dirty:
            lg.lobby_dirty = False
            data = encode(lg.lobby_msg())
            for c in list(self.by_pid.values()):
                self._send_raw(c, data)

    def _tick(self, now):
        lg = self.logic
        # drop silent clients (dead TCP connections, frozen games)
        for c in list(self.conns.values()):
            if now - c.last_recv > C.CLIENT_TIMEOUT:
                self._close(c, "timed out", notify=False)
        lg.tick(now)
        self._dispatch()
        snap = lg.snapshot(now)
        if snap is not None:
            for c in list(self.by_pid.values()):
                p = lg.players.get(c.pid)
                if p is None:
                    continue
                snap["me"] = lg.personal(p, now)
                self._send_raw(c, encode(snap))


def run_in_thread(port=C.TCP_PORT, name=None, discovery=True):
    """Start a server on a daemon thread (used when hosting from the game)."""
    srv = Server(port=port, name=name, discovery=discovery).start()
    t = threading.Thread(target=srv.run, name="amongus-server", daemon=True)
    t.start()
    return srv, t


def main(argv=None):
    ap = argparse.ArgumentParser(description="Among Us LAN dedicated server")
    ap.add_argument("--port", type=int, default=C.TCP_PORT)
    ap.add_argument("--name", default=None, help="game name shown in the LAN browser")
    ap.add_argument("--no-discovery", action="store_true", help="don't answer LAN browse requests")
    ap.add_argument("--min-players", type=int, default=C.MIN_PLAYERS_TO_START)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    srv = Server(port=args.port, name=args.name, discovery=not args.no_discovery,
                 logic=GameLogic(min_players=args.min_players))
    try:
        srv.start()
    except OSError as e:
        print(f"Could not listen on port {args.port}: {e}\nIs another server already running?")
        return 1
    print("=" * 60)
    print(f" Among Us LAN server '{srv.name}' listening on port {srv.port}")
    for ip in srv.ips or ["127.0.0.1"]:
        print(f"   players can join at:  {ip}")
    print(" (LAN browsing is on: players can also just pick it from the Join list)")
    print(" Press Ctrl+C to stop.")
    print("=" * 60)
    try:
        srv.run()
    except KeyboardInterrupt:
        pass
    print("server stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
