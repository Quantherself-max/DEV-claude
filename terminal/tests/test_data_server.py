import json, threading, time, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from config import Config
from data.base import DataError
from data.binance import BinanceSource
from data.simulated import SimulatedSource
from engine import liquidity
from server import App, make_handler
from alerts.rules import AlertEngine
from alerts.notifier import ConsoleNotifier
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
        res = FixedBinance(self.base, pause=0, retries=1).selftest("BTCUSDT")
        self.assertTrue(all(ok for _, ok, _ in res), res)
        with self.assertRaises(DataError) as cm:
            BinanceSource(self.base, retries=1)._get("/blocked")
        self.assertIn("451", str(cm.exception))
        with self.assertRaises(DataError):
            BinanceSource("http://127.0.0.1:9", retries=1, timeout=1)._get("/x")

    def test_full_pipeline_on_binance_adapter(self):
        """Service complet alimente par l'adaptateur Binance (faux serveur) : meme chaine que sur ton PC."""
        cfg = Config(source="binance", symbols=("BTCUSDT",))
        svc = Service(FixedBinance(self.base, pause=0), cfg)
        svc.refresh_all()
        self.assertEqual(svc.errors, {})
        st = svc.get_state("BTCUSDT", "1h")
        self.assertTrue(st["ready"])
        self.assertGreater(len(st["levels"]), 20)
        self.assertGreater(st["liquidity"]["steps"], 8000)
        self.assertGreater(st["liquidity"]["oiPoints"], 8000)
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


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = Config(symbols=("BTCUSDT",), data_dir=cls.tmp.name, port=0)
        src = SimulatedSource(now_ms=NOW)
        cls.svc = Service(src, cls.cfg)
        cls.svc.refresh_all()
        alerts = AlertEngine(cls.cfg, ConsoleNotifier())
        cls.app = App(cls.cfg, cls.svc, alerts, ConsoleNotifier())
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.url + path, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_state_schema(self):
        code, body, _ = self.get("/api/state?symbol=BTCUSDT&tf=1h")
        self.assertEqual(code, 200)
        st = json.loads(body)
        for key in ("price", "atr", "window", "tol", "candles", "levels", "zones", "ladder", "liquidity", "source"):
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
        self.assertIn("log", json.loads(self.get("/api/alerts")[1]))
        self.assertNotIn("token", json.dumps(cfg).lower())                     # aucun secret expose a l'interface


if __name__ == "__main__":
    unittest.main()
