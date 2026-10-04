"""Client WebSocket minimal (bibliotheque standard uniquement) : handshake, trames texte, fragmentation,
ping/pong, detection d'inactivite et reconnexion automatique avec attente progressive.
Sert a lire les flux publics de Binance (transactions, liquidations) cote serveur ; aucun envoi de donnees."""
import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlparse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 8, 9, 10
MAX_PAYLOAD = 8 * 1024 * 1024


class WSError(Exception):
    pass


def encode_frame(opcode: int, payload: bytes = b"", mask: bool = True, fin: bool = True) -> bytes:
    """Trame WebSocket (RFC 6455). Les trames client sont masquees, celles du serveur ne le sont pas."""
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    m = 0x80 if mask else 0
    if n < 126:
        head += bytes([m | n])
    elif n < 65536:
        head += bytes([m | 126]) + struct.pack(">H", n)
    else:
        head += bytes([m | 127]) + struct.pack(">Q", n)
    if mask:
        key = os.urandom(4)
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        return head + key + payload
    return head + payload


class FrameReader:
    """Decoupe un flux d'octets en trames ; `feed` ajoute des octets, `frames` rend les trames completes."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> None:
        self.buf += data

    def frames(self):
        while True:
            b = self.buf
            if len(b) < 2:
                return
            fin, opcode = bool(b[0] & 0x80), b[0] & 0x0F
            masked, n, pos = bool(b[1] & 0x80), b[1] & 0x7F, 2
            if n == 126:
                if len(b) < 4:
                    return
                n, pos = struct.unpack(">H", bytes(b[2:4]))[0], 4
            elif n == 127:
                if len(b) < 10:
                    return
                n, pos = struct.unpack(">Q", bytes(b[2:10]))[0], 10
            if n > MAX_PAYLOAD:
                raise WSError("trame trop grande")
            key = None
            if masked:
                if len(b) < pos + 4:
                    return
                key, pos = bytes(b[pos:pos + 4]), pos + 4
            if len(b) < pos + n:
                return
            payload = bytes(b[pos:pos + n])
            del b[:pos + n]
            if key:
                payload = bytes(c ^ key[i % 4] for i, c in enumerate(payload))
            yield fin, opcode, payload


class WSClient:
    """Une connexion qui se reconnecte toute seule. on_message(texte) est appele dans le thread du client."""

    def __init__(self, url: str, on_message, name: str = "ws", ssl_context=None, idle_timeout: float = 90.0,
                 on_open=None):
        u = urlparse(url)
        if u.scheme not in ("ws", "wss"):
            raise ValueError(f"URL WebSocket attendue (ws:// ou wss://) : {url}")
        self.url, self.name, self.on_message, self.on_open = url, name, on_message, on_open
        self.host, self.tls = u.hostname, u.scheme == "wss"
        self.port = u.port or (443 if self.tls else 80)
        self.path = (u.path or "/") + (("?" + u.query) if u.query else "")
        self.ctx = ssl_context
        self.idle_timeout = idle_timeout
        self.stop_ev = threading.Event()
        self.connected = False
        self.last_msg = 0.0
        self.last_error = ""
        self.connects = 0
        self.thread = None
        self.sock = None

    # --- une session ---
    def _handshake(self, sock):
        key = base64.b64encode(os.urandom(16)).decode()
        host = self.host if self.port in (80, 443) else f"{self.host}:{self.port}"
        sock.sendall((f"GET {self.path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                      f"User-Agent: liq-terminal/1.0\r\n\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise WSError("connexion fermee pendant la poignee de main")
            data += chunk
            if len(data) > 65536:
                raise WSError("reponse de poignee de main trop longue")
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        if " 101" not in lines[0]:
            raise WSError(f"refuse par le serveur : {lines[0]}")
        hdr = {l.split(":", 1)[0].strip().lower(): l.split(":", 1)[1].strip() for l in lines[1:] if ":" in l}
        want = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if hdr.get("sec-websocket-accept") != want:
            raise WSError("poignee de main invalide (Sec-WebSocket-Accept)")
        return rest

    def _session(self):
        raw = socket.create_connection((self.host, self.port), timeout=10)
        sock = raw
        try:
            if self.tls:
                ctx = self.ctx or ssl.create_default_context()
                sock = ctx.wrap_socket(raw, server_hostname=self.host)
            sock.settimeout(10)
            rest = self._handshake(sock)
            sock.settimeout(1.0)
            self.sock = sock
            self.connected, self.last_msg = True, time.time()
            self.connects += 1
            if self.on_open:
                self.on_open(self)
            rd, text, kind = FrameReader(), bytearray(), None
            rd.feed(rest)
            while not self.stop_ev.is_set():
                for fin, op, payload in rd.frames():
                    if op == OP_PING:
                        sock.sendall(encode_frame(OP_PONG, payload))
                    elif op == OP_CLOSE:
                        try:
                            sock.sendall(encode_frame(OP_CLOSE, payload[:2]))
                        except OSError:
                            pass
                        raise WSError("fermeture demandee par le serveur")
                    elif op in (OP_TEXT, OP_BIN, OP_CONT):
                        if op != OP_CONT:
                            text, kind = bytearray(), op
                        text += payload
                        if fin and kind == OP_TEXT:
                            self.last_msg = time.time()
                            try:
                                self.on_message(text.decode("utf-8", "replace"))
                            except Exception as e:                  # un message mal forme ne coupe pas le flux
                                self.last_error = f"message ignore : {type(e).__name__}: {e}"
                        elif fin:
                            self.last_msg = time.time()
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    if time.time() - self.last_msg > self.idle_timeout:
                        raise WSError(f"aucune donnee depuis {int(self.idle_timeout)} s")
                    continue
                if not chunk:
                    raise WSError("connexion fermee par le serveur")
                rd.feed(chunk)
        finally:
            self.connected = False
            self.sock = None
            try:
                sock.close()
            except OSError:
                pass

    # --- boucle de reconnexion ---
    def run_forever(self):
        wait = 1.0
        while not self.stop_ev.is_set():
            t0 = time.time()
            try:
                self._session()
                self.last_error = ""
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            if self.stop_ev.is_set():
                break
            wait = 1.0 if time.time() - t0 > 60 else min(30.0, wait * 2)      # session stable : on repart vite
            self.stop_ev.wait(wait)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self.run_forever, name=f"ws-{self.name}", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_ev.set()
        s = self.sock
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
