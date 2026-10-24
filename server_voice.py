#!/usr/bin/python3

import socket
import threading

class Server:
    def __init__(self):
            from amongus.discovery import local_ipv4s
            self.ip = ", ".join(local_ipv4s()) or "127.0.0.1"
            self.port = 4322
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.s.bind(("", self.port))  # all interfaces, not just whichever adapter gethostname picks
            except OSError as e:
                raise SystemExit(f"Couldn't bind voice port {self.port}: {e}")

            self.connections = []
            self.accept_connections()

    def accept_connections(self):
        self.s.listen(100)

        print('Running on IP: '+self.ip)
        print('Running on port: '+str(self.port))
        
        while True:
            c, addr = self.s.accept()

            self.connections.append(c)

            threading.Thread(target=self.handle_client,args=(c,addr,)).start()
        
    def broadcast(self, sock, data):
        for client in self.connections:
            if client != self.s and client != sock:
                try:
                    client.send(data)
                except:
                    pass

    def handle_client(self,c,addr):
        while 1:
            try:
                data = c.recv(1024)
            except socket.error:
                data = b""
            if not data:
                # client left: stop serving it instead of spinning on a dead socket
                if c in self.connections:
                    self.connections.remove(c)
                c.close()
                return
            self.broadcast(c, data)

server = Server()
