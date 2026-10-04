import json, threading, time, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from config import Config
from data.base import DataError
from data.binance import BinanceSource
from data.simulated import SimulatedSource
from engine import liquidity
from server import App, make_handler
from service import Service
from http.server import ThreadingHTTPServer

NOW = 1_790_000_000_000          # instant fixe pour des tests deterministes


class FakeBinance(BaseHTTPRequestHandler):
    """Imite les endpoints Binance utilises, d'apres la documentation, avec leurs limites (1500 / 500)."""
    calls = []
    fail_first = {"n": 0}

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        FakeBinance.calls.append((u.path, q))
        if u.path == "/fapi/v1/ping":
            return self._send({})
        if u.path == "/blocked":
            return self._send({"msg": "restricted location"}, 451)
        if u.path == "/fapi/v1/premiumIndex":
            return self._send({"symbol": q["symbol"], "markPrice": "80010.5", "indexPrice": "80000.0",
                               "lastFundingRate": "0.00012", "nextFundingTime": NOW + 3_600_000, "time": NOW})
        if u.path == "/fapi/v1/fundingRate":
            t, rows = int(q["startTime"]) // 28_800_000 * 28_800_000 + 28_800_000, []
            while t <= int(q["endTime"]):
                rows.append({"symbol": q["symbol"], "fundingTime": t, "fundingRate": "0.0001", "markPrice": "80000"})
                t += 28_800_000
            return self._send(rows)
        if u.path in ("/futures/data/globalLongShortAccountRatio", "/futures/data/topLongShortPositionRatio"):
            t, rows = int(q["startTime"]) // 3_600_000 * 3_600_000 + 3_600_000, []
            while t <= min(int(q["endTime"]), NOW) and len(rows) < 500:
                rows.append({"symbol": q["symbol"], "longShortRatio": "1.5000", "longAccount": "0.6000",
                             "shortAccount": "0.4000", "timestamp": t})
                t += 3_600_000
            return self._send(rows)
        if u.path == "/api/v3/ticker/price":
            return self._send({"symbol": q["symbol"], "price": "80005.00"})
        if u.path.startswith("/products/") and u.path.endswith("/ticker"):
            return self._send({"price": "80030.00", "bid": "80029", "ask": "80031"})
        step = {"1h": 3_600_000, "5m": 300_000}[q["interval"] if "interval" in q else q.get("period", "5m")]
        start, end = int(q["startTime"]), int(q["endTime"])
        t0 = (start + step - 1) // step * step
        if u.path == "/fapi/v1/klines":
            lim = min(int(q["limit"]), 1500)
            rows, t = [], t0
            while t <= end and len(rows) < lim and t <= NOW:
                p = 80000 + (t // step) % 1000
                rows.append([t, str(p), str(p + 50), str(p - 50), str(p + 10), "12.5", t + step - 1, "1", 100, "6.0", "1", "0"])
                t += step
            return self._send(rows)
        if u.path == "/futures/data/openInterestHist":
            lim = min(int(q["limit"]), 500)
            if int(q["endTime"]) - int(q["startTime"]) > 30 * 86400_000:
                return self._send({"code": -1130, "msg": "startTime too old"}, 400)
            rows, t = [], t0
            while t <= end and len(rows) < lim and t <= NOW:
                rows.append({"symbol": q["symbol"], "sumOpenInterest": str(50000 + (t // step) % 700), "sumOpenInterestValue": "1", "timestamp": t})
                t += step
            return self._send(rows)
        self._send({}, 404)


class FixedBinance(BinanceSource):
    def now_ms(self):
        return NOW


class BinanceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeBinance)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_parse_kline_row_and_oi_row(self):
        k = BinanceSource.parse_klines([[1700000000000, "100.5", "101", "99", "100", "12.5", 1700003599999, "x", 5, "6.25", "y", "0"]])[0]
        self.assertEqual((k.t, k.o, k.h, k.l, k.c, k.v, k.tb), (1700000000000, 100.5, 101.0, 99.0, 100.0, 12.5, 6.25))
        self.assertEqual(BinanceSource.parse_oi([{"sumOpenInterest": "81234.5", "timestamp": 1700000300000}]), [(1700000300000, 81234.5)])

    def test_pagination_is_contiguous_and_complete(self):
        src = BinanceSource(self.base, pause=0)
        h = 3_600_000
        start = NOW - 4000 * h
        cs = src.candles("BTCUSDT", "1h", start, NOW)            # > 1500 : plusieurs pages
        self.assertGreaterEqual(len(cs), 3999)
        self.assertTrue(all(b.t - a.t == h for a, b in zip(cs, cs[1:])))
        oi = src.open_interest("BTCUSDT", "5m", NOW - 29 * 86_400_000, NOW)       # > 500 : plusieurs pages
        self.assertGreater(len(oi), 8000)
        ts = [t for t, _ in oi]
        self.assertTrue(all(b - a == 300_000 for a, b in zip(ts, ts[1:])))

    def test_selftest_and_errors(self):
        res = FixedBinance(self.base, pause=0, retries=1, spot_base=self.base, coinbase_base=self.base).selftest("BTCUSDT")
        self.assertTrue(all(ok for _, ok, _ in res), res)
        with self.assertRaises(DataError) as cm:
            BinanceSource(self.base, retries=1)._get("/blocked")
        self.assertIn("451", str(cm.exception))
        with self.assertRaises(DataError):
            BinanceSource("http://127.0.0.1:9", retries=1, timeout=1)._get("/x")

    def test_full_pipeline_on_binance_adapter(self):
        """Service complet alimente par l'adaptateur Binance (faux serveur) : meme chaine que sur ton PC."""
        cfg = Config(source="binance", symbols=("BTCUSDT",))
        svc = Service(FixedBinance(self.base, pause=0, spot_base=self.base, coinbase_base=self.base), cfg)
        svc.refresh_all()
        self.assertEqual(svc.errors, {})
        st = svc.get_state("BTCUSDT", "1h")
        self.assertTrue(st["ready"])
        self.assertGreater(len(st["levels"]), 20)
        self.assertGreater(st["liquidity"]["steps"], 8000)
        self.assertGreater(st["liquidity"]["oiPoints"], 8000)
        ctx = st["context"]
        self.assertEqual(ctx["errors"], {})
        self.assertAlmostEqual(ctx["funding"]["now"], 0.012)
        self.assertAlmostEqual(ctx["basis"], (80010.5 / 80000.0 - 1) * 100)
        self.assertAlmostEqual(ctx["ls"]["global"]["now"], 1.5)
        self.assertAlmostEqual(ctx["coinbase"]["premium"], (80030.0 / 80005.0 - 1) * 100)
        n = FakeBinance.calls.__len__()
        svc.refresh_all()                                         # 2e passage : seulement l'increment
        self.assertLess(len(FakeBinance.calls) - n, 8)


class MissingOiTests(unittest.TestCase):
    def test_missing_oi_creates_nothing(self):
        e = liquidity.LiqEngine()
        e.step(1000.0, 86100, 85900, 86000)
        e.step(None, 86100, 85990, 86000, vol=999999.0)         # OI absent + enorme volume : rien ne doit naitre
        self.assertEqual((e.lact, e.sact), ([], []))
        e.step(1100.0, 86100, 85990, 86000)                       # l'OI revient : la variation cumulee est attribuee
        self.assertTrue(e.lact and e.sact)


class ReloadTests(unittest.TestCase):
    def test_source_switch_rebuilds_service(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("TERMINAL_SYMBOLS=BTCUSDT\n", encoding="utf-8")
            made = []

            def mk(c):
                made.append(c.source)
                return SimulatedSource(now_ms=NOW)
            app = App(Config(source="simulated", symbols=("BTCUSDT",), data_dir=d), env_path=env, make_source=mk)
            s0 = app.service
            res = app.save_settings({"source": "binance"})
            self.assertEqual(res["source"], "binance")
            self.assertIsNot(app.service, s0)                    # nouvelle source -> donnees rechargees
            self.assertEqual(made, ["simulated", "binance"])
            self.assertTrue(app.wake.is_set())                   # la boucle de rafraichissement repart tout de suite
            self.assertEqual(app.cfg.data_dir, d)
            app.service.refresh_all()
            self.assertTrue(app.service.markets["BTCUSDT"].ready)


class FakeTelegram(BaseHTTPRequestHandler):
    sent = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        if "/botBAD:" in self.path:
            return self._send({"ok": False, "description": "Unauthorized"}, 401)
        if self.path.endswith("/getUpdates"):
            return self._send({"ok": True, "result": [{"message": {"chat": {"id": 4242, "first_name": "Moi"}}}]})
        if self.path.endswith("/sendMessage"):
            FakeTelegram.sent.append(data)
            return self._send({"ok": True, "result": {}})
        self._send({"ok": False}, 404)

    do_GET = do_POST


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.tmp = tempfile.TemporaryDirectory()
        cls.tg = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.tg.serve_forever, daemon=True).start()
        cls.env = Path(cls.tmp.name) / ".env"
        cls.env.write_text("# mes reglages\nTERMINAL_SOURCE=simulated\nTERMINAL_SYMBOLS=BTCUSDT\n"
                           f"TELEGRAM_API_BASE=http://127.0.0.1:{cls.tg.server_address[1]}\n", encoding="utf-8")
        cls.cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=cls.tmp.name, port=0,
                         telegram_api_base=f"http://127.0.0.1:{cls.tg.server_address[1]}")
        cls.app = App(cls.cfg, env_path=cls.env, make_source=lambda c: SimulatedSource(now_ms=NOW))
        cls.app.service.refresh_all()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tg.shutdown()
        cls.tg.server_close()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def post(self, path, body=None, token=True, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["X-Terminal-Token"] = self.app.token if token is True else token
        req = urllib.request.Request(self.url + path, data=json.dumps(body or {}).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_state_schema(self):
        code, body, _ = self.get("/api/state?symbol=BTCUSDT&tf=1h")
        self.assertEqual(code, 200)
        st = json.loads(body)
        for key in ("price", "atr", "window", "tol", "candles", "levels", "zones", "ladder", "liquidity", "source",
                    "context", "sweeps", "stats"):
            self.assertIn(key, st)
        self.assertEqual(st["source"], "simulated")
        ids = {lv["id"] for lv in st["levels"]}
        self.assertEqual(len(ids), len(st["levels"]))                        # ids uniques
        for z in st["zones"]:
            self.assertGreaterEqual(len(z["groups"]), 2)
            self.assertTrue(set(z["members"]) <= ids)
            self.assertLessEqual(z["hi"] - z["lo"], st["tol"] + 1e-6)
        for zid in st["ladder"]["above"] + st["ladder"]["below"] + st["ladder"]["inside"]:
            self.assertIn(zid, {z["id"] for z in st["zones"]})
        self.assertTrue(all(z["mid"] > st["price"] for z in st["zones"] if z["side"] == "above"))
        self.assertTrue(all(z["mid"] < st["price"] for z in st["zones"] if z["side"] == "below"))
        self.assertTrue(all("reach" in p for p in st["liquidity"]["pools"]))
        self.assertIn("regime", st["context"])

    def test_all_timeframes_and_errors(self):
        for tf in ("5m", "15m", "1h", "4h", "1d"):
            code, body, _ = self.get(f"/api/state?symbol=BTCUSDT&tf={tf}")
            self.assertEqual(code, 200, tf)
            self.assertTrue(json.loads(body)["ready"])
        self.assertEqual(self.get("/api/state?symbol=XXX&tf=1h")[0], 404)
        self.assertEqual(self.get("/api/state?symbol=BTCUSDT&tf=3m")[0], 404)

    def test_static_files_and_no_path_traversal(self):
        code, body, hdr = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Liq Terminal", body)
        self.assertEqual(self.get("/app.js")[0], 200)
        self.assertEqual(self.get("/vendor/lightweight-charts.standalone.production.js")[0], 200)
        self.assertEqual(self.get("/../config.py")[0], 404)
        self.assertEqual(self.get("/%2e%2e/config.py")[0], 404)
        self.assertEqual(self.get("/.env")[0], 404)

    def test_health_config_alerts(self):
        self.assertTrue(json.loads(self.get("/api/health")[1])["ok"])
        cfg = json.loads(self.get("/api/config")[1])
        self.assertEqual(cfg["symbols"], ["BTCUSDT"])
        self.assertFalse(cfg["telegram"])
        self.assertEqual(cfg["csrf"], self.app.token)
        self.assertIn("log", json.loads(self.get("/api/alerts")[1]))

    def test_foreign_host_and_missing_token_are_refused(self):
        # un site pirate qui pointe son nom de domaine vers 127.0.0.1 (DNS rebinding) : Host etranger -> refus
        self.assertEqual(self.get("/api/settings", {"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.post("/api/settings", {"source": "binance"}, token=False)[0], 403)
        self.assertEqual(self.post("/api/settings", {"source": "binance"}, token="faux")[0], 403)
        self.assertEqual(self.post("/api/settings", {"source": "binance"}, headers={"Host": "evil.example"})[0], 403)
        self.assertNotIn("TERMINAL_SOURCE=binance", self.env.read_text())

    def test_settings_roundtrip_and_telegram(self):
        st = json.loads(self.get("/api/settings")[1])
        self.assertEqual(st["source"], "simulated")
        self.assertFalse(st["telegram"]["configured"])
        code, res = self.post("/api/settings", {"telegramToken": "pas-un-token"})
        self.assertEqual(code, 400)
        code, res = self.post("/api/telegram/chatid", {"token": "BAD:x"})
        self.assertEqual(res["chats"], [])
        self.assertIn("refuse", res["detail"])
        code, res = self.post("/api/telegram/chatid", {"token": "123:abc"})
        self.assertEqual(res["chats"], [{"id": "4242", "name": "Moi"}])
        service_before = self.app.service
        code, res = self.post("/api/settings", {"telegramToken": "123:abcdefghijkl", "telegramChatId": "4242",
                                                "alertMinScore": 4, "alertSweep": False})
        self.assertEqual(code, 200, res)
        self.assertTrue(res["telegram"]["configured"])
        self.assertEqual(res["telegram"]["tokenHint"], "...ijkl")                 # le token complet ne ressort jamais
        self.assertNotIn("abcdefghijkl", json.dumps(res))
        self.assertEqual((res["alertMinScore"], res["alertSweep"]), (4, False))
        self.assertIs(self.app.service, service_before)                            # pas de rechargement des donnees
        self.assertTrue(self.app.cfg.telegram_on)
        txt = self.env.read_text()
        self.assertIn("# mes reglages", txt)                                       # le reste du fichier est garde
        self.assertIn("TELEGRAM_BOT_TOKEN=123:abcdefghijkl", txt)
        self.assertIn("TERMINAL_ALERT_MIN_SCORE=4", txt)
        self.assertNotIn("abcdefghijkl", json.dumps(json.loads(self.get("/api/config")[1])))
        code, res = self.post("/api/test/telegram", {})
        self.assertTrue(res["ok"], res)
        self.assertEqual(FakeTelegram.sent[-1]["chat_id"], "4242")


if __name__ == "__main__":
    unittest.main()
