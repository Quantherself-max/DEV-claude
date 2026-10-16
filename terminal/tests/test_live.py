import json, os, subprocess, tempfile, threading, time, unittest

from data.live import LiveFeed
from data.ws import FrameReader, OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, WSClient, encode_frame
from tests.fakews import FakeWSServer


def wait_for(cond, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


class FrameTests(unittest.TestCase):
    def test_roundtrip_all_sizes_masked_and_not(self):
        for n in (0, 5, 125, 126, 300, 65535, 65536, 70000):
            for mask in (False, True):
                data = bytes((i * 7) % 251 for i in range(n))
                rd = FrameReader()
                raw = encode_frame(OP_TEXT, data, mask=mask)
                for i in range(0, len(raw), 1000):              # arrivee par morceaux
                    rd.feed(raw[i:i + 1000])
                out = list(rd.frames())
                self.assertEqual(out, [(True, OP_TEXT, data)], (n, mask))

    def test_partial_frame_waits(self):
        rd = FrameReader()
        raw = encode_frame(OP_TEXT, b"hello", mask=False)
        rd.feed(raw[:3])
        self.assertEqual(list(rd.frames()), [])
        rd.feed(raw[3:])
        self.assertEqual([p for _, _, p in rd.frames()], [b"hello"])


class ClientTests(unittest.TestCase):
    def test_messages_fragments_ping_and_reconnect(self):
        got, pongs = [], []

        def script(path, send, alive, conn):
            send(OP_TEXT, b"un")
            send(OP_TEXT, b"deu", fin=False)                         # message fragmente
            send(0, b"x")
            send(OP_PING, b"abc")
            conn.settimeout(2)
            rd = FrameReader()
            try:
                rd.feed(conn.recv(4096))
                pongs.extend(p for _, op, p in rd.frames() if op == OP_PONG)
            except OSError:
                pass
            send(OP_TEXT, "é".encode() * 70000)                       # gros message (> 64 Ko)
            send(OP_CLOSE, b"\x03\xe8")                                # le serveur coupe : reconnexion attendue

        srv = FakeWSServer(script)
        c = WSClient(f"ws://127.0.0.1:{srv.port}/stream?streams=a", got.append, "t")
        try:
            c.start()
            self.assertTrue(wait_for(lambda: len(got) >= 3 and c.connects >= 2), (got[:3], c.connects, c.last_error))
            self.assertEqual(got[:2], ["un", "deux"])
            self.assertEqual(len(got[2]), 70000)
            self.assertEqual(pongs[:1], [b"abc"])                      # ping -> pong avec la meme charge
            self.assertIn("/stream?streams=a", srv.paths[0])
        finally:
            c.stop(); srv.close()

    def test_refused_handshake_is_reported_and_retried(self):
        srv = FakeWSServer(lambda *a: None)
        c = WSClient(f"ws://127.0.0.1:{srv.port}/refuse", lambda t: None, "t")
        try:
            c.start()
            self.assertTrue(wait_for(lambda: "403" in c.last_error), c.last_error)
            self.assertFalse(c.connected)
        finally:
            c.stop(); srv.close()

    def test_tls_with_self_signed_certificate(self):
        d = tempfile.mkdtemp()
        crt, key = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
        r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                            "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                           capture_output=True)
        if r.returncode:
            self.skipTest("openssl indisponible")
        import ssl
        ctx = ssl.create_default_context(cafile=crt)
        got = []
        srv = FakeWSServer(lambda p, send, alive, conn: (send(OP_TEXT, b"secure"), time.sleep(1)), crt, key)
        c = WSClient(f"wss://localhost:{srv.port}/x", got.append, "t", ssl_context=ctx)
        try:
            c.start()
            self.assertTrue(wait_for(lambda: got == ["secure"]), c.last_error)
        finally:
            c.stop(); srv.close()


class LiveFeedTests(unittest.TestCase):
    def test_price_and_real_liquidations(self):
        def script(path, send, alive, conn):
            if "aggTrade" in path:
                for i in range(3):
                    send(OP_TEXT, json.dumps({"stream": "solusdt@aggTrade", "data": {"e": "aggTrade", "s": "SOLUSDT", "p": f"{190 + i}.50", "q": "1", "T": 1_790_000_000_000 + i}}).encode())
                    send(OP_TEXT, json.dumps({"stream": "btcusdt@aggTrade", "data": {"e": "aggTrade", "s": "BTCUSDT", "p": "85000.10", "q": "1", "T": 1_790_000_000_000}}).encode())
            else:
                liq = {"stream": "solusdt@forceOrder", "data": {"e": "forceOrder", "E": 1, "o": {"s": "SOLUSDT", "S": "SELL", "q": "100", "p": "189", "ap": "190", "z": "100", "T": 1_790_000_000_500}}}
                send(OP_TEXT, json.dumps(liq).encode())
                send(OP_TEXT, json.dumps(liq).encode())                 # doublon : ignore
                liq["data"]["o"].update(S="BUY", T=1_790_000_001_000, ap="191", z="50")
                send(OP_TEXT, json.dumps(liq).encode())
            time.sleep(1)

        srv = FakeWSServer(script)
        with tempfile.TemporaryDirectory() as d:
            f = LiveFeed(f"ws://127.0.0.1:{srv.port}/market", ["SOLUSDT", "BTCUSDT"], d)
            try:
                f.start()
                self.assertTrue(wait_for(lambda: f.last_price("SOLUSDT") and f.last_price("SOLUSDT")[0] == 192.5 and len(f.liqs["SOLUSDT"]) == 2), (f.price, f.status()))
                self.assertEqual(f.last_price("BTCUSDT")[0], 85000.10)
                evs = f.recent_liqs("SOLUSDT")
                self.assertEqual([(e["side"], e["usd"]) for e in evs], [("long", 19000.0), ("short", 9550.0)])
                s = f.liq_summary("SOLUSDT", 1_790_000_002_000)
                self.assertEqual((s["1h"]["long"], s["1h"]["short"], s["24h"]["n"]), (19000.0, 9550.0, 2))
                self.assertTrue(any("/market/stream?streams=solusdt@forceOrder/btcusdt@forceOrder" in p for p in srv.paths))
            finally:
                f.stop(); srv.close()
            g = LiveFeed("ws://127.0.0.1:1/market", ["SOLUSDT"], d)         # relance : le journal est relu depuis le fichier
            g.liqs["SOLUSDT"].clear(); g._load_liqs()
            self.assertEqual(len(g.liqs["SOLUSDT"]), 0)                       # trop ancien (> 48 h) : ignore
        f2 = LiveFeed("ws://127.0.0.1:1/market", ["SOLUSDT"])
        f2.price["SOLUSDT"] = (1.0, 1, time.time() - 100)
        self.assertIsNone(f2.last_price("SOLUSDT"))                           # prix perime : pas de faux prix


if __name__ == "__main__":
    unittest.main()
