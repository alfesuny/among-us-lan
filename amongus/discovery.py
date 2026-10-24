"""LAN game discovery over UDP broadcast.

The server answers DISCOVERY_MAGIC datagrams on DISCOVERY_PORT with a JSON
description of the game; clients broadcast the magic on every local subnet.
"""
import json
import socket
import time

from .config import DISCOVERY_MAGIC, DISCOVERY_PORT


def local_ipv4s():
    """Best-effort list of this machine's LAN IPv4 addresses, primary first."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the default route
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    ips = [ip for ip in ips if not ip.startswith("127.") and not ip.startswith("169.254.")]
    return ips


def broadcast_targets():
    targets = {"255.255.255.255", "127.0.0.1"}
    for ip in local_ipv4s():
        parts = ip.split(".")
        targets.add(".".join(parts[:3] + ["255"]))
    return sorted(targets)


def make_responder(port=DISCOVERY_PORT):
    """Non-blocking UDP socket for the server's selector, or None if the port is taken."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", port))
    except OSError:
        s.close()
        return None
    s.setblocking(False)
    return s


def answer(sock, info):
    """Handle pending discovery datagrams on a responder socket."""
    for _ in range(32):
        try:
            data, addr = sock.recvfrom(512)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            return  # e.g. WSAECONNRESET after an ICMP unreachable on Windows
        if data.strip() == DISCOVERY_MAGIC:
            try:
                sock.sendto(json.dumps(info).encode("utf-8"), addr)
            except OSError:
                pass


def discover(timeout=0.8, port=DISCOVERY_PORT):
    """Broadcast a probe and collect replies. Returns {ip: info}."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.1)
        for target in broadcast_targets():
            try:
                s.sendto(DISCOVERY_MAGIC, (target, port))
            except OSError:
                pass
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                continue
            try:
                info = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(info, dict) and info.get("game") == "amongus":
                ip = addr[0]
                # prefer the host's LAN address over loopback when both answer
                if ip.startswith("127.") and info.get("ips"):
                    ip = info["ips"][0]
                found[ip] = info
    finally:
        s.close()
    return found
