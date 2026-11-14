"""Client WebSocket minimal (bibliotheque standard uniquement) : handshake, trames texte, fragmentation,
ping/pong, detection d'inactivite et reconnexion automatique.
Sert a lire les flux publics des bourses (transactions, liquidations, carnets) cote serveur.
V45 : reconnexion a attente EXPONENTIELLE avec alea (1 s, 2 s, 4 s... jusqu'a 60 s, chaque attente tiree entre la moitie et la totalite de
sa valeur : apres une panne d'une bourse, toutes les connexions ne repartent pas au meme instant) ; retour a 1 s apres une session
stable (plus d'une minute) ; chaque coupure est datee (`gaps`, et `on_gap(debut_ms, fin_ms)`) pour que les calculs sachent quelles
periodes sont incompletes ; passage par un proxy HTTP (variables HTTPS_PROXY / HTTP_PROXY, NO_PROXY respecte) par la methode CONNECT."""
from __future__ import annotations
import base64
import hashlib
import os
import random
import socket
import ssl
import struct
import threading
import time
from collections import deque
from urllib.parse import urlparse

BACKOFF_BASE, BACKOFF_MAX, STABLE_S = 1.0, 60.0, 60.0


def backoff_wait(failures: int, rnd=random.random, base: float = BACKOFF_BASE, cap: float = BACKOFF_MAX) -> float:
    """Attente avant la tentative qui suit `failures` echecs de suite (1 = premier echec)."""
    return min(cap, base * (2 ** max(0, failures - 1))) * (0.5 + 0.5 * rnd())


def proxy_for(host: str, tls: bool, env=None):
    """(hote, port, en-tete d'authentification ou None) du proxy a utiliser pour `host`, ou None (connexion directe)."""
    env = os.environ if env is None else env
    raw = (env.get("HTTPS_PROXY") or env.get("https_proxy")) if tls else (env.get("HTTP_PROXY") or env.get("http_proxy"))
    if not raw:
        return None
    for pat in (env.get("NO_PROXY") or env.get("no_proxy") or "").split(","):
        pat = pat.strip().lstrip("*")
        if pat and (host == pat.lstrip(".") or host.endswith(pat if pat.startswith(".") else "." + pat)):
            return None
    u = urlparse(raw if "://" in raw else "http://" + raw)
    if not u.hostname:
        return None
    auth = None
    if u.username:
        auth = "Basic " + base64.b64encode(f"{u.username}:{u.password or ''}".encode()).decode()
    return u.hostname, u.port or 8080, auth

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
                 on_open=None, on_gap=None, rnd=random.random, fallbacks=()):
        self.name, self.on_message, self.on_open = name, on_message, on_open
        self.urls = [url, *[f for f in fallbacks if f and f != url]]      # V45 : adresses de secours (autre port), essayees a tour de role
        self._set_url(url)
        self.ctx = ssl_context
        self.idle_timeout = idle_timeout
        self.stop_ev = threading.Event()
        self.connected = False
        self.last_msg = 0.0
        self.last_error = ""
        self.connects = 0
        self.thread = None
        self.sock = None
        self.on_gap, self.rnd = on_gap, rnd
        self.failures = 0                    # echecs de suite depuis la derniere session stable
        self.next_wait = 0.0                 # attente en cours avant la prochaine tentative (secondes)
        self.down_since = None               # heure (ms) du dernier message avant la coupure en cours
        self.gaps = deque(maxlen=200)        # [(debut ms, fin ms)] des coupures passees

    def _set_url(self, url: str) -> None:
        u = urlparse(url)
        if u.scheme not in ("ws", "wss"):
            raise ValueError(f"URL WebSocket attendue (ws:// ou wss://) : {url}")
        self.url = url
        self.host, self.tls = u.hostname, u.scheme == "wss"
        self.port = u.port or (443 if self.tls else 80)
        self.path = (u.path or "/") + (("?" + u.query) if u.query else "")

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
        px = proxy_for(self.host, self.tls)
        raw = socket.create_connection((px[0], px[1]) if px else (self.host, self.port), timeout=10)
        sock = raw
        try:
            if px:
                self._tunnel(raw, px[2])
            if self.tls:
                ctx = self.ctx or ssl.create_default_context()
                sock = ctx.wrap_socket(raw, server_hostname=self.host)
            sock.settimeout(10)
            rest = self._handshake(sock)
            sock.settimeout(1.0)
            self.sock = sock
            self.connected, self.last_msg = True, time.time()
            self.connects += 1
            if self.down_since is not None:                              # fin d'une coupure : on la date
                gap = (self.down_since, int(time.time() * 1000))
                self.down_since = None
                self.gaps.append(gap)
                if self.on_gap:
                    try:
                        self.on_gap(*gap)
                    except Exception as e:
                        self.last_error = f"on_gap : {type(e).__name__}: {e}"
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
            if self.connected and self.down_since is None:
                self.down_since = int(self.last_msg * 1000)              # les donnees sont sures jusqu'au dernier message recu
            self.connected = False
            self.sock = None
            try:
                sock.close()
            except OSError:
                pass

    def _tunnel(self, sock, auth) -> None:
        """Ouvre un tunnel vers la bourse a travers le proxy (CONNECT) ; la suite (TLS, poignee de main) passe dedans."""
        req = f"CONNECT {self.host}:{self.port} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
        if auth:
            req += f"Proxy-Authorization: {auth}\r\n"
        sock.sendall((req + "\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise WSError("proxy : connexion fermee")
            data += chunk
            if len(data) > 65536:
                raise WSError("proxy : reponse trop longue")
        line = data.split(b"\r\n", 1)[0].decode("latin-1")
        if " 200" not in line:
            raise WSError(f"proxy : tunnel refuse ({line})")

    def send_text(self, text: str) -> bool:
        """Envoie un message texte (abonnement, ping) ; False si la connexion n'est pas ouverte."""
        s = self.sock
        if s is None or not self.connected:
            return False
        try:
            s.sendall(encode_frame(OP_TEXT, text.encode("utf-8")))
            return True
        except OSError as e:
            self.last_error = f"envoi impossible : {e}"
            return False

    def reconnect(self) -> None:
        """V44 : ferme la session en cours sans arreter le client (il se reconnecte tout seul), quand la bourse le demande."""
        s = self.sock
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    # --- boucle de reconnexion ---
    def run_forever(self):
        while not self.stop_ev.is_set():
            t0, before = time.time(), self.connects
            try:
                self._session()
                self.last_error = ""
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            if self.stop_ev.is_set():
                break
            self.failures = 1 if time.time() - t0 > STABLE_S else self.failures + 1     # session stable : on repart vite
            if self.connects == before and len(self.urls) > 1 and self.failures >= 2:    # jamais ouverte a cette adresse : la suivante
                self._set_url(self.urls[(self.urls.index(self.url) + 1) % len(self.urls)])
            self.next_wait = backoff_wait(self.failures, self.rnd)
            self.stop_ev.wait(self.next_wait)

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


def port_fallbacks(url: str) -> tuple:
    """Adresse de secours d'un flux servi sur un port inhabituel (OKX : 8443) : la meme sur le port 443, que tous les reseaux laissent passer."""
    u = urlparse(url)
    if u.port in (None, 443, 80):
        return ()
    return (url.replace(f"{u.hostname}:{u.port}", u.hostname, 1),)
