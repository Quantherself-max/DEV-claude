"""Tests de la source Tradovate et du client WebSocket stdlib, HORS LIGNE (aucun accès réseau ni compte réel) :
une fausse socket rejoue le protocole de Tradovate (o / autorisation / abonnement / cotations), on vérifie la synthèse des transactions,
le battement de cœur, et les refus (identifiants, accès)."""
import json
import struct
import threading
import time
import unittest

from data.tradovate import TradovateSource, _split_frame, _ts
from data.wsclient import WsClient


class FrameTests(unittest.TestCase):
    def test_split_sockjs_frames(self):
        self.assertEqual(_split_frame("o"), ("o", []))
        self.assertEqual(_split_frame("h"), ("h", []))
        k, items = _split_frame('a[{"s":200,"i":1},{"e":"md","d":{"quotes":[]}}]')
        self.assertEqual((k, len(items)), ("a", 2))
        self.assertEqual(items[0]["s"], 200)
        self.assertEqual(_split_frame("c[1,2]")[0], "c")
        self.assertEqual(_split_frame("")[1], [])
        self.assertEqual(_split_frame("a[not json")[1], [])

    def test_timestamp_parsing(self):
        self.assertEqual(_ts("2026-10-15T13:30:01.250Z"), 1792071001250)
        self.assertEqual(_ts(1792071001250), 1792071001250)
        self.assertEqual(_ts(1792071001.25), 1792071001250)
        self.assertEqual(_ts(None, default_ms=42), 42)

    def test_wsclient_frame_codec_roundtrip(self):
        # une trame serveur (non masquée) se décode ; une longueur sur 2 octets passe
        payload = ("z" * 300).encode()
        frame = struct.pack("!BBH", 0x81, 126, len(payload)) + payload
        (fin, op, data), used = WsClient._parse(frame)
        self.assertEqual((fin, op, used), (True, 0x1, len(frame)))
        self.assertEqual(data, payload)
        self.assertIsNone(WsClient._parse(frame[:5]))         # incomplète : None


class WsLoopbackTests(unittest.TestCase):
    def test_ping_between_fragments_is_not_spliced(self):
        import base64
        import hashlib
        import socket
        from data.wsclient import GUID

        def frame(fin, op, p):
            return struct.pack("!BB", (0x80 if fin else 0) | op, len(p)) + p

        def server(sock, got):
            conn, _ = sock.accept()
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            key = [ln.split(":", 1)[1].strip() for ln in data.decode().split("\r\n") if ln.lower().startswith("sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            conn.sendall(f"HTTP/1.1 101 OK\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode())
            conn.sendall(frame(False, 0x1, b"AB") + frame(True, 0x9, b"zz") + frame(True, 0x0, b"CD") + frame(True, 0x1, b"next"))
            conn.settimeout(2)
            try:
                hdr = conn.recv(2)
                got.append(hdr[0] & 0x0F)               # le pong du client
            except OSError:
                pass
            time.sleep(0.3)
            conn.close()

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        got = []
        th = threading.Thread(target=server, args=(srv, got), daemon=True)
        th.start()
        c = WsClient(f"ws://127.0.0.1:{srv.getsockname()[1]}/")
        c.connect()
        self.assertEqual(c.recv(2), "ABCD")
        self.assertEqual(c.recv(2), "next")                   # le flux n'est pas désynchronisé
        c.close()
        th.join(2)
        srv.close()
        self.assertIn(0xA, got)


class FakeWs:
    """Rejoue le serveur de données Tradovate. `script` : messages poussés vers le client après l'autorisation. Enregistre ce que le client envoie."""
    def __init__(self, md_events, deny_auth=False, deny_sub=False):
        self.sent = []
        self.inbox = []                                       # (type, texte) à livrer au client
        self.md_events = md_events
        self.deny_auth = deny_auth
        self.deny_sub = deny_sub
        self.connected = False
        self.lock = threading.Lock()
        self._opened = False

    def connect(self):
        self.connected = True
        with self.lock:
            self.inbox.append("o")                            # la socket s'ouvre

    def send(self, text):
        with self.lock:
            self.sent.append(text)
        if text == "[]":                                      # battement de cœur
            return
        endpoint = text.split("\n", 1)[0]
        rid = text.split("\n")[1] if "\n" in text else "1"
        with self.lock:
            if endpoint == "authorize":
                if self.deny_auth:
                    self.inbox.append(f'a[{{"s":401,"i":{rid},"d":{{"errorText":"Access is denied"}}}}]')
                else:
                    self.inbox.append(f'a[{{"s":200,"i":{rid}}}]')
            elif endpoint == "md/subscribeQuote":
                if self.deny_sub:
                    self.inbox.append(f'a[{{"s":403,"i":{rid},"d":{{"errorText":"not entitled"}}}}]')
                else:
                    self.inbox.append(f'a[{{"s":200,"i":{rid}}}]')
                    for ev in self.md_events:
                        self.inbox.append("a" + json.dumps([{"e": "md", "d": ev}]))

    def recv(self, timeout=None):
        with self.lock:
            if self.inbox:
                return self.inbox.pop(0)
        time.sleep(0.005)
        return None                                           # rien pour l'instant

    def close(self):
        self.connected = False


def quote(bid, ask, trade, cum_vol, ts="2026-10-15T13:30:00Z"):
    ent = {}
    if bid is not None:
        ent["Bid"] = {"price": bid}
    if ask is not None:
        ent["Offer"] = {"price": ask}
    if trade is not None:
        ent["Trade"] = {"price": trade}
    if cum_vol is not None:
        ent["TotalTradeVolume"] = {"size": cum_vol}
    return {"quotes": [{"symbol": "NQZ6", "timestamp": ts, "entries": ent}]}


AUTH_OK = {"accessToken": "ACCESS", "mdAccessToken": "MD", "name": "trader", "expirationTime": "2099-01-01T00:00:00Z"}


def source(events, auth=AUTH_OK, deny_auth=False, deny_sub=False, http_err=None):
    fake = FakeWs(events, deny_auth=deny_auth, deny_sub=deny_sub)

    def http(url, body):
        if http_err:
            raise http_err
        return auth
    src = TradovateSource("user", "pass", "", "", ws_factory=lambda url: fake, http_fn=http)
    src.heartbeat_s = 0.0                                     # force un battement de cœur à chaque tour (test)
    return src, fake


def drain(src, tries=200):
    """Laisse le fil de fond tourner et récupère les transactions."""
    out = []
    for _ in range(tries):
        out += src.poll(0)
        time.sleep(0.01)
        if len(out) >= 3:
            break
    return out


class SynthesisTests(unittest.TestCase):
    def test_quotes_become_trades_with_aggressor_side(self):
        events = [
            quote(25000.0, 25000.25, 25000.25, 100),          # 1re valeur : cale la base (pas d'émission)
            quote(25000.0, 25000.25, 25000.25, 105),          # +5 au prix de l'ask -> acheteur
            quote(25000.0, 25000.25, 25000.0, 108),           # +3 au prix du bid -> vendeur
        ]
        src, fake = source(events)
        trades = drain(src)
        src.shutdown()
        self.assertGreaterEqual(len(trades), 2)
        self.assertEqual((trades[0].q, trades[0].side), (5.0, 1))
        self.assertEqual((trades[1].q, trades[1].side), (3.0, -1))
        self.assertEqual(trades[0].p, 25000.25)
        self.assertTrue(any(f == "[]" for f in fake.sent))    # un battement de cœur a été envoyé
        self.assertTrue(any(f.startswith("authorize") for f in fake.sent))
        self.assertTrue(any(f.startswith("md/subscribeQuote") for f in fake.sent))

    def test_volume_reset_does_not_emit_negative(self):
        events = [quote(1, 1.25, 1.25, 500), quote(1, 1.25, 1.25, 3), quote(1, 1.25, 1.25, 8)]
        src, _ = source(events)
        trades = drain(src)
        src.shutdown()
        self.assertTrue(all(t.q > 0 for t in trades))
        self.assertIn(5.0, [t.q for t in trades])             # après remise à zéro, +5 est émis

    def test_authorizes_with_md_token(self):
        src, fake = source([quote(1, 1.25, 1.25, 10), quote(1, 1.25, 1.25, 12)])
        drain(src)
        src.shutdown()
        auth_frame = next(f for f in fake.sent if f.startswith("authorize"))
        self.assertTrue(auth_frame.endswith("MD"))            # jeton de DONNÉES, pas le jeton d'accès général


class ErrorTests(unittest.TestCase):
    def test_denied_authorization_is_fatal(self):
        src, _ = source([], deny_auth=True)
        err = None
        for _ in range(200):
            try:
                src.poll(0)
            except Exception as e:
                err = e
                break
            time.sleep(0.01)
            if src.status == "refusé":
                break
        src.shutdown()
        self.assertEqual(src.status, "refusé")
        self.assertIn("refus", (src.error or "").lower())

    def test_transient_refused_connection_is_not_fatal(self):
        import urllib.error
        src, _ = source([], http_err=urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")))
        src.history(0)                                        # démarre le fil de fond
        for _ in range(100):
            if src.status == "reconnexion":
                break
            time.sleep(0.01)
        src.shutdown()
        self.assertEqual(src.status, "reconnexion")
        self.assertEqual(src.poll(0), [])                     # ne remonte PAS d'erreur fatale au terminal

    def test_data_subscription_denied_is_fatal(self):
        src, _ = source([], deny_sub=True)
        src.history(0)
        for _ in range(200):
            if src.status == "refusé":
                break
            time.sleep(0.01)
        src.shutdown()
        self.assertEqual(src.status, "refusé")
        from data.base import DataError
        with self.assertRaises(DataError):
            src.poll(0)

    def test_missing_credentials(self):
        from data.base import DataError
        with self.assertRaises(DataError):
            TradovateSource("", "", "", "")

    def test_info_reports_state(self):
        src, _ = source([quote(1, 1.25, 1.25, 10)])
        info = src.info()
        self.assertEqual(info["name"], "tradovate")
        self.assertFalse(info["simulated"])
        self.assertIn("env", info)
        src.shutdown()


if __name__ == "__main__":
    unittest.main()


class LoginFormTests(unittest.TestCase):
    """Formulaire de connexion (service.tradovate_login / logout), avec un faux Tradovate : rien ne sort sur le réseau."""
    def setUp(self):
        import tempfile
        from unittest import mock

        import data.tradovate as tv
        from config import Config
        from data.simulated import SimulatedSource
        from engine.account import Account
        from service import Service
        self.tmp = tempfile.TemporaryDirectory()
        self.env = __import__("pathlib").Path(self.tmp.name) / ".env"
        self.env.write_text("NQ_PORT=8766\n", encoding="utf-8")
        self.http_result = dict(AUTH_OK)
        self.http_error = None
        events = [quote(25000.0, 25000.25, 25000.25, 100), quote(25000.0, 25000.25, 25000.25, 104)]

        def http(url, body):
            self.last_body = body
            if self.http_error:
                raise self.http_error
            return self.http_result
        self.patches = [mock.patch.object(tv, "_http_post", http),
                        mock.patch.object(tv, "WsClient", lambda url, timeout=30.0: FakeWs(events)),
                        mock.patch("config.find_logger_file", lambda: None)]
        for p in self.patches:
            p.start()
        now = 1792071001250
        self.svc = Service(Config(data_dir=self.tmp.name, sim_days=2, gex="OFF"), source=SimulatedSource(days=2, now_fn=lambda: now),
                           account=Account(f"{self.tmp.name}/c.json", now_ms=lambda: now), env_path=self.env)

    def tearDown(self):
        self.svc.shutdown()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_login_switches_to_live_feed_without_writing_the_password(self):
        r = self.svc.tradovate_login("moi", "s3cret!", remember=False)
        self.assertTrue(r["ok"])
        self.assertFalse(r["remembered"])
        self.assertEqual(self.svc.cfg.source, "tradovate")
        self.assertEqual(self.last_body["name"], "moi")
        self.assertNotIn("s3cret!", self.env.read_text(encoding="utf-8"))
        view = json.dumps(self.svc.source_view()) + json.dumps(r)
        self.assertNotIn("s3cret!", view)                                  # le mot de passe ne ressort jamais par l'API
        self.assertIn("moi", view)
        for _ in range(200):
            self.svc.pump_once()
            if self.svc.market.count:
                break
            time.sleep(0.01)
        self.assertGreater(self.svc.market.count, 0)                        # le flux alimente le marché

    def test_remember_writes_env_and_logout_erases_it(self):
        r = self.svc.tradovate_login("moi", "s3cret!", cid="12", sec="abc", env="demo", remember=True)
        self.assertTrue(r["remembered"])
        text = self.env.read_text(encoding="utf-8")
        for line in ("NQ_SOURCE=tradovate", "TRADOVATE_USERNAME=moi", "TRADOVATE_PASSWORD=s3cret!", "TRADOVATE_ENV=demo", "NQ_PORT=8766"):
            self.assertIn(line, text)
        out = self.svc.tradovate_logout()
        self.assertEqual(out["source"], "simulated")
        text = self.env.read_text(encoding="utf-8")
        self.assertNotIn("TRADOVATE", text)
        self.assertNotIn("NQ_SOURCE", text)
        self.assertIn("NQ_PORT=8766", text)
        self.assertEqual(self.svc.cfg.tv_password, "")

    def test_refused_login_changes_nothing(self):
        import urllib.error
        self.http_error = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        with self.assertRaises(ValueError) as cm:
            self.svc.tradovate_login("moi", "mauvais", remember=True)
        self.assertIn("refusée", str(cm.exception))
        self.assertNotIn("mauvais", str(cm.exception))
        self.assertEqual(self.svc.cfg.source, "simulated")
        self.assertNotIn("TRADOVATE", self.env.read_text(encoding="utf-8"))

    def test_empty_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.tradovate_login("", "x")
        with self.assertRaises(ValueError):
            self.svc.tradovate_login("moi", "")
