"""Client WebSocket minimal (RFC 6455), en bibliothèque STANDARD uniquement (socket + ssl). Pas de dépendance à installer.

Le terminal doit rester « installe Python, double-clique, rien d'autre » : la bibliothèque standard n'a pas de client WebSocket, on en écrit
donc un petit, juste ce qu'il faut pour parler à l'API de données de Tradovate :
  - poignée de main HTTP (Upgrade: websocket), vérification de Sec-WebSocket-Accept ;
  - envoi de trames TEXTE (masquées, comme l'exige la norme côté client) ;
  - lecture des trames entrantes (texte, ping/pong, close), réassemblage des trames fragmentées ;
  - `recv()` bloquant avec délai (timeout) : renvoie None quand il n'y a rien dans le délai imparti, sans fermer la connexion.
Ce n'est pas un client complet : ni extensions, ni compression (permessage-deflate n'est pas demandé), ni trames binaires attendues. Suffisant
pour un flux de cotations en texte JSON."""
import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.parse import urlparse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"          # constante de la norme WebSocket


class WsError(Exception):
    pass


class WsClient:
    def __init__(self, url: str, timeout: float = 30.0, origin: str | None = None):
        self.url = url
        self.timeout = timeout
        self.origin = origin
        self.sock = None
        self._buf = b""                                 # octets reçus pas encore découpés en trames
        self.connected = False

    # ---------- connexion ----------
    def connect(self) -> None:
        u = urlparse(self.url)
        secure = u.scheme == "wss"
        host = u.hostname
        port = u.port or (443 if secure else 80)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        raw = socket.create_connection((host, port), timeout=self.timeout)
        if secure:
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}" if u.port else f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            "User-Agent: NQ-Scalp-Terminal",
        ]
        if self.origin:
            lines.append(f"Origin: {self.origin}")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
        self._handshake(key)
        self.connected = True

    def _handshake(self, key: str) -> None:
        # lit l'en-tête de réponse (jusqu'à la ligne vide) ; le reste des octets est du flux WebSocket, on le garde
        self.sock.settimeout(self.timeout)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WsError("connexion fermée pendant la poignée de main")
            head += chunk
            if len(head) > 65536:
                raise WsError("réponse de poignée de main anormalement longue")
        header, _, rest = head.partition(b"\r\n\r\n")
        self._buf = rest
        status_line = header.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status_line:
            raise WsError(f"le serveur a refusé la connexion WebSocket : {status_line}")
        accept = None
        for line in header.split(b"\r\n")[1:]:
            name, _, value = line.decode("latin-1").partition(":")
            if name.strip().lower() == "sec-websocket-accept":
                accept = value.strip()
        expect = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
        if accept != expect:
            raise WsError("clé de poignée de main WebSocket invalide")

    # ---------- envoi ----------
    def send(self, text: str) -> None:
        if not self.sock:
            raise WsError("non connecté")
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        fin_op = 0x80 | opcode
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", fin_op, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", fin_op, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", fin_op, 0x80 | 127, n)
        mask = os.urandom(4)                            # le client DOIT masquer ses trames
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _pong(self, payload: bytes) -> None:
        self._send_frame(0xA, payload)

    # ---------- réception ----------
    def recv(self, timeout: float | None = None):
        """Prochain message TEXTE complet (str), ou None si rien n'arrive dans le délai. Répond aux ping et gère le close tout seul."""
        deadline_set = timeout is not None
        self.sock.settimeout(timeout if deadline_set else self.timeout)
        while True:
            frame = self._next_frame(deadline_set)
            if frame is None:
                return None
            fin, opcode, payload = frame
            if opcode == 0x8:                           # close
                try:
                    self._send_frame(0x8, payload[:2])
                except OSError:
                    pass
                self.connected = False
                raise WsError("le serveur a fermé la connexion")
            if opcode == 0x9:                           # ping -> pong
                self._pong(payload)
                continue
            if opcode == 0xA:                           # pong : ignoré
                continue
            if opcode in (0x1, 0x2, 0x0):               # données (texte / binaire / continuation)
                data = payload
                while not fin:                          # trame fragmentée : on lit la suite
                    nxt = self._next_frame(False)
                    if nxt is None:
                        raise WsError("trame fragmentée interrompue")
                    c_fin, c_op, more = nxt
                    if c_op == 0x9:                     # la norme autorise un contrôle ENTRE deux fragments : on y répond, sans le mêler
                        self._pong(more)
                        continue
                    if c_op == 0xA:
                        continue
                    if c_op == 0x8:
                        self.connected = False
                        raise WsError("le serveur a fermé la connexion")
                    if c_op != 0x0:
                        raise WsError("trame de continuation attendue")
                    fin = c_fin
                    data += more
                return data.decode("utf-8", "replace")
            # opcode inconnu : on l'ignore

    def _next_frame(self, may_time_out: bool):
        """Décode UNE trame depuis le tampon, en lisant le réseau au besoin. None seulement si `may_time_out` et plus rien n'arrive à temps."""
        while True:
            parsed = self._parse(self._buf)
            if parsed is not None:
                frame, used = parsed
                self._buf = self._buf[used:]
                return frame
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                if may_time_out:
                    return None
                raise WsError("délai dépassé en attendant des données")
            if not chunk:
                self.connected = False
                raise WsError("connexion fermée")
            self._buf += chunk

    @staticmethod
    def _parse(buf: bytes):
        """(trame, octets consommés) si une trame complète est disponible au début de `buf`, sinon None. La trame = (fin, opcode, payload)."""
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)                        # le serveur ne masque pas, mais on respecte le champ
        length = b1 & 0x7F
        i = 2
        if length == 126:
            if len(buf) < i + 2:
                return None
            length = struct.unpack_from("!H", buf, i)[0]
            i += 2
        elif length == 127:
            if len(buf) < i + 8:
                return None
            length = struct.unpack_from("!Q", buf, i)[0]
            i += 8
        mask = b""
        if masked:
            if len(buf) < i + 4:
                return None
            mask = buf[i:i + 4]
            i += 4
        if len(buf) < i + length:
            return None
        payload = buf[i:i + length]
        if masked:
            payload = bytes(c ^ mask[j & 3] for j, c in enumerate(payload))
        return (fin, opcode, payload), i + length

    def close(self) -> None:
        self.connected = False
        if self.sock:
            try:
                self._send_frame(0x8, b"")
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
