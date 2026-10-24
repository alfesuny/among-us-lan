"""Client networking: a reader thread feeding a queue; sends are thread-safe."""
import queue
import socket
import threading
import time

from .. import config as C
from ..protocol import FrameReader, ProtocolError, encode


class ConnectError(Exception):
    pass


def friendly_error(e, host):
    if isinstance(e, socket.timeout) or "timed out" in str(e):
        return (f"No answer from {host}. Check the IP, that both PCs are on the same network, "
                f"and that the host allowed the game through Windows Firewall.")
    if isinstance(e, ConnectionRefusedError) or getattr(e, "winerror", None) == 10061:
        return f"{host} refused the connection: no game is being hosted there (or it uses another port)."
    if isinstance(e, socket.gaierror):
        return f"'{host}' is not a valid address."
    return f"Could not connect to {host}: {e}"


class NetClient:
    def __init__(self):
        self.sock = None
        self.inbox = queue.Queue()
        self.lock = threading.Lock()
        self.alive = False
        self.thread = None
        self.host = None
        self.rtt = None
        self._last_ping = 0.0

    def connect(self, host, port, name, colour, timeout=5.0):
        self.host = host
        try:
            s = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            raise ConnectError(friendly_error(e, host)) from None
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(1.0)
        self.sock = s
        self.alive = True
        self.send({"t": "hello", "v": C.PROTOCOL_VERSION, "name": name, "colour": colour})
        self.thread = threading.Thread(target=self._reader, name="net-reader", daemon=True)
        self.thread.start()

    def _reader(self):
        reader = FrameReader()
        reason = "Connection to the host was lost."
        try:
            while self.alive:
                try:
                    data = self.sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    reason = "The host closed the game."
                    break
                try:
                    for m in reader.feed(data):
                        if m["t"] == "pong" and isinstance(m.get("c"), (int, float)):
                            self.rtt = time.perf_counter() - m["c"]
                            continue
                        self.inbox.put(m)
                except ProtocolError as e:
                    reason = f"Bad data from host: {e}"
                    break
        finally:
            was_alive = self.alive
            self.alive = False
            if was_alive:
                self.inbox.put({"t": "_disconnected", "reason": reason})

    def send(self, msg):
        if not self.alive:
            return False
        data = encode(msg)
        try:
            with self.lock:
                self.sock.sendall(data)
            return True
        except OSError:
            self.alive = False
            self.inbox.put({"t": "_disconnected", "reason": "Connection to the host was lost."})
            return False

    def poll(self, limit=2000):
        out = []
        try:
            while len(out) < limit:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            pass
        return out

    def keepalive(self):
        now = time.perf_counter()
        if now - self._last_ping > 1.0:
            self._last_ping = now
            self.send({"t": "ping", "c": now})

    def close(self):
        self.alive = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
