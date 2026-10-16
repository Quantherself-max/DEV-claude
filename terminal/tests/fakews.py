"""Faux serveur WebSocket (tests) : poignee de main RFC 6455, trames scriptees, TLS optionnel."""
import base64
import hashlib
import socket
import ssl
import threading
import time

from data.ws import GUID, OP_PING, OP_TEXT, encode_frame, FrameReader


class FakeWSServer:
    def __init__(self, script, tls_cert=None, tls_key=None):
        """script(path, send, alive) est appele dans un thread par connexion ; send(opcode, payload, fin=True)."""
        self.script, self.paths, self.stop_ev = script, [], threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.ctx = None
        if tls_cert:
            self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ctx.load_cert_chain(tls_cert, tls_key)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stop_ev.is_set():
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(c,), daemon=True).start()

    def _handle(self, c):
        try:
            if self.ctx:
                c = self.ctx.wrap_socket(c, server_side=True)
            req = b""
            while b"\r\n\r\n" not in req:
                d = c.recv(4096)
                if not d:
                    return
                req += d
            lines = req.decode().split("\r\n")
            path = lines[0].split(" ")[1]
            self.paths.append(path)
            key = next(l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("sec-websocket-key"))
            if path.startswith("/refuse"):
                c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
            lock = threading.Lock()

            def send(op, payload=b"", fin=True):
                with lock:
                    c.sendall(encode_frame(op, payload, mask=False, fin=fin))

            self.script(path, send, lambda: not self.stop_ev.is_set(), c)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        self.stop_ev.set()
        try:
            self.sock.close()
        except OSError:
            pass
