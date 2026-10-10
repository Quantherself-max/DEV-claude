import json, tempfile, threading, time, unittest, urllib.error, urllib.request
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
        if u.path in ("/fapi/v1/ticker/price", "/fapi/v2/ticker/price"):
            if q["symbol"] == "V2ONLY" and "/v1/" in u.path:
                return self._send({"code": -1, "msg": "gone"}, 404)
            return self._send({"symbol": q["symbol"], "price": "80001.50", "time": NOW})
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

    def test_last_price_with_v2_fallback(self):
        src = FixedBinance(self.base, pause=0)
        self.assertEqual(src.last_price("BTCUSDT"), (80001.5, NOW))
        self.assertEqual(src.last_price("V2ONLY"), (80001.5, NOW))          # /fapi/v1 retire -> /fapi/v2

    def test_full_pipeline_on_binance_adapter(self):
        """Service complet alimente par l'adaptateur Binance (faux serveur) : meme chaine que sur ton PC."""
        cfg = Config(source="binance", symbols=("BTCUSDT",), history_years=2, data_dir=tempfile.mkdtemp())
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


class HistoryCacheTests(unittest.TestCase):
    def test_second_start_loads_cache_and_only_fetches_the_missing_part(self):
        import tempfile
        from data.store import DataStore, H1
        with tempfile.TemporaryDirectory() as d:
            src = FixedBinance(self.base, pause=0, spot_base=self.base, coinbase_base=self.base)
            s1 = DataStore(src, "BTCUSDT", NOW - 400 * 86_400_000, 2, d)
            s1.refresh()
            self.assertGreater(len(s1.h1), 3000)
            self.assertTrue((__import__("pathlib").Path(d) / "h1_BTCUSDT.json.gz").exists())
            self.assertTrue(all(b.t - a.t == H1 for a, b in zip(s1.h1, s1.h1[1:])))
            n_calls = len(FakeBinance.calls)
            s2 = DataStore(src, "BTCUSDT", NOW - 400 * 86_400_000, 2, d)                       # redemarrage
            s2.refresh()
            kl = [c for c in FakeBinance.calls[n_calls:] if c[0] == "/fapi/v1/klines" and c[1].get("interval") == "1h"]
            self.assertEqual(len(kl), 1)                                    # une seule page : l'increment, pas tout l'historique
            self.assertEqual(len(s2.closed_h1()), len(s1.closed_h1()))
            self.assertEqual(s2.h1[100].c, s1.h1[100].c)
            s3 = DataStore(src, "BTCUSDT", NOW - 400 * 86_400_000, 2, d + "/vide")              # autre dossier : pas de cache
            s3.refresh()
            self.assertEqual(s3._saved_n, len(s3.closed_h1()))
            # un cache fait avec moins d'historique que demande est ignore
            s4 = DataStore(src, "BTCUSDT", NOW - 400 * 86_400_000, 3, d)
            n_calls = len(FakeBinance.calls)
            s4.refresh()
            kl = [c for c in FakeBinance.calls[n_calls:] if c[0] == "/fapi/v1/klines" and c[1].get("interval") == "1h"]
            self.assertGreater(len(kl), 10)                                 # tout est retelecharge (3 ans > 2 ans en cache)
            self.assertGreater(len(s4.h1), len(s1.h1) + 8000)

    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeBinance)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()


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


class LiveServerTests(unittest.TestCase):
    def test_server_uses_websocket_price_and_serves_real_liquidations(self):
        from data.live import LiveFeed
        from data.ws import OP_TEXT
        from tests.fakews import FakeWSServer

        def script(path, send, alive, conn):
            ms = int(time.time() * 1000)
            if "aggTrade" in path:
                while alive():
                    send(OP_TEXT, json.dumps({"data": {"e": "aggTrade", "s": "BTCUSDT", "p": "91234.50", "q": "1", "T": int(time.time() * 1000)}}).encode())
                    time.sleep(0.05)
            else:
                send(OP_TEXT, json.dumps({"data": {"e": "forceOrder", "o": {"s": "BTCUSDT", "S": "SELL", "q": "2", "p": "90000", "ap": "90100", "z": "2", "T": ms - 1000}}}).encode())
                time.sleep(2)

        srv = FakeWSServer(script)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=d, port=0)
            app = App(cfg, env_path=__import__("pathlib").Path(d) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW),
                      make_feed=lambda c: LiveFeed(f"ws://127.0.0.1:{srv.port}/market", c.symbols, d))
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                app.service.refresh_all()
                app.start_background()
                deadline = time.time() + 8
                while time.time() < deadline and not (app.feed.last_price("BTCUSDT") and app.feed.recent_liqs("BTCUSDT")):
                    time.sleep(0.05)
                r = json.loads(urllib.request.urlopen(base + "/api/price?symbol=BTCUSDT", timeout=5).read())
                self.assertEqual((r["price"], r["via"]), (91234.5, "ws"))
                lq = json.loads(urllib.request.urlopen(base + "/api/liqs?symbol=BTCUSDT", timeout=5).read())
                self.assertEqual([(e["side"], round(e["usd"])) for e in lq["events"]], [("long", 180200)])
                self.assertEqual(round(lq["summary"]["1h"]["long"]), 180200)
                st = app.service.get_state("BTCUSDT", "1h")
                self.assertEqual(st["price"], 91234.5)                       # le prix du serveur suit le flux
                self.assertEqual(round(st["context"]["liqReal"]["1h"]["long"]), 180200)
                h = json.loads(urllib.request.urlopen(base + "/api/health", timeout=5).read())
                self.assertTrue(h["feed"]["trades"]["connected"])
            finally:
                app.shutdown(); httpd.shutdown(); httpd.server_close(); srv.close()


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

    def test_importance_essential_and_pool_birth(self):
        st = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=1h")[1])
        ess = st["ladder"]["essential"]
        zones = {z["id"]: z for z in st["zones"]}
        self.assertTrue(set(ess) <= set(zones))
        for side in ("above", "below"):
            self.assertLessEqual(sum(1 for i in ess if zones[i]["side"] == side), 2)       # au plus 2 zones par cote
        for z in st["zones"]:
            self.assertIn("imp", z)
        pools = st["liquidity"]["pools"]
        self.assertTrue(pools)
        for p in pools:
            self.assertTrue(p["born"] is None or p["born"] <= st["now"])
        ages = [p["born"] for p in pools if p["born"]]
        self.assertTrue(ages)                                                              # l'age des poches est connu

    def test_analysis_and_plan_endpoints(self):
        from engine import bias as be
        from tests.test_bias import synth
        m = self.app.service.markets["BTCUSDT"]
        deadline = time.time() + 40
        while time.time() < deadline and not (m.stats and m.reach):
            time.sleep(0.2)
        m.bias = be.analyse(synth(24 * 330, 21, signal=0.35))        # modele valide (signal plante), injecte pour le test
        r = json.loads(self.get("/api/analysis?symbol=BTCUSDT")[1])
        self.assertTrue(r["ready"])
        for k in ("synth", "bias", "macro", "dom", "sources"):
            self.assertIn(k, r)
        json.dumps(r)                                                  # serialisable : aucune donnee d'entrainement ne fuit
        self.assertNotIn("_model", json.dumps(r))
        self.assertIn(r["synth"]["direction"], ("haussier", "baissier", "neutre"))
        self.assertTrue(r["macro"]["hasCalendar"])
        self.assertTrue(r["macro"]["upcoming"])
        self.assertIn("horizons", r["bias"])
        self.assertEqual(self.get("/api/analysis?symbol=XXX")[0], 404)
        p = json.loads(self.get("/api/plan?symbol=BTCUSDT&side=long&tp=2&sl=1&lev=10&h=24")[1])
        self.assertTrue(p["ready"])
        pl = p["plan"]
        self.assertAlmostEqual(pl["tp"]["p"] + pl["sl"]["p"] + pl["none"]["p"], 1.0, places=6)
        self.assertAlmostEqual(p["liqPct"], 9.6)                       # 100/10 - 0,4
        self.assertLess(p["liqPrice"], p["price"])
        self.assertFalse(p["slBeyondLiq"])
        self.assertIsNotNone(p["liqTouch"]["24"])
        s = json.loads(self.get("/api/plan?symbol=BTCUSDT&side=short&tp=2&sl=12&lev=10&h=24")[1])
        self.assertTrue(s["slBeyondLiq"])                              # stop au-dela de la liquidation : signale
        self.assertGreater(s["liqPrice"], s["price"])
        self.assertEqual(self.get("/api/plan?symbol=BTCUSDT&side=up&tp=2&sl=1&lev=10&h=24")[0], 400)
        self.assertEqual(self.get("/api/plan?symbol=BTCUSDT&side=long&tp=2&sl=1&lev=10&h=5")[0], 400)

    def test_volume_profiles_series_and_specs(self):
        st = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=1h")[1])
        self.assertTrue(st["vp"])
        self.assertEqual([p["id"] for p in st["vp"]], ["r30", "r90", "r180"])                 # « auto » suit la timeframe
        st1d = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=1d")[1])                   # fenetre large : les niveaux VP y sont tous
        xv = [l for l in st1d["levels"] if l["kind"] == "xvp"]
        self.assertTrue(xv)
        self.assertTrue(all(l["group"].startswith("xVP:") for l in xv))
        self.assertTrue(all(l["name"].split()[-1] in ("POC", "VAH", "VAL", "HVN") and l["name"].startswith("VP ") for l in xv))
        st5 = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=5m")[1])
        self.assertEqual([p["id"] for p in st5["vp"]], ["r3", "r7", "r14"])
        d = json.loads(self.get("/api/vp?symbol=BTCUSDT&tf=1d")[1])
        self.assertTrue(d["ready"])
        p0 = d["profiles"][0]
        self.assertGreater(len(p0["rows"]), 20)
        self.assertLessEqual(len(p0["rows"]), 100)
        self.assertTrue(p0["val"] < p0["poc"] < p0["vah"])
        # un profil personnalise : enregistre, applique, persiste, et rejete s'il est invalide
        code, res = self.post("/api/vps", {"specs": [{"kind": "rolling", "days": 21}, {"kind": "period", "period": "month", "back": 1}]})
        self.assertEqual(code, 200, res)
        self.assertEqual([s["kind"] for s in res["specs"]], ["rolling", "period"])
        st2 = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=1h")[1])
        self.assertEqual([p["id"] for p in st2["vp"]], ["r21", "month1"])
        self.assertTrue(__import__("os").path.exists(__import__("os").path.join(self.cfg.data_dir, "vps.json")))
        self.assertEqual(json.loads(self.get("/api/vps")[1])["specs"][0]["days"], 21)
        self.assertEqual(self.post("/api/vps", {"specs": [{"kind": "rolling", "days": 0}]})[0], 400)
        self.assertEqual(self.post("/api/vps", {"specs": [{"kind": "rolling", "days": 5}]}, token=False)[0], 403)   # jeton requis
        self.assertEqual(self.post("/api/vps", {"specs": [{"kind": "auto"}], "anchors": ["2025-06-01"]})[0], 200)
        # series VWAP / AVWAP
        sr = json.loads(self.get("/api/series?symbol=BTCUSDT&tf=1h")[1])
        self.assertTrue(sr["ready"])
        n = len(sr["times"])
        self.assertEqual(n, 400)
        self.assertTrue(all(len(v) == n for v in sr["vwap"].values()))
        self.assertTrue(any(v is not None for v in sr["vwap"]["W"]))
        labels = [a["label"] for a in sr["avwap"]]
        self.assertIn("AVWAP 2025-06-01", labels)                                              # l'ancrage ajoute est present
        self.assertTrue(any(l.startswith("AVWAP 2024") for l in labels))                      # + celui de la configuration
        s1d = json.loads(self.get("/api/series?symbol=BTCUSDT&tf=1d")[1])
        self.assertNotIn("D", s1d["vwap"])
        self.assertEqual(self.get("/api/series?symbol=BTCUSDT&tf=3m")[0], 404)
        self.assertEqual(self.get("/api/vp?symbol=XXX&tf=1h")[0], 404)
        self.post("/api/vps", {"specs": [{"kind": "auto"}], "anchors": []})                    # remet les valeurs par defaut

    def test_overview_endpoint(self):
        code, body, _ = self.get("/api/overview")
        self.assertIn("bias", json.loads(body))                                          # biais du terminal (None tant qu'aucune idee)
        self.assertEqual(code, 200)
        o = json.loads(body)
        for k in ("symbols", "macro", "dom", "fng", "alerts", "feed", "errors"):
            self.assertIn(k, o)
        ready = [s for s in o["symbols"] if s["ready"]]
        self.assertTrue(ready)
        s = ready[0]
        for k in ("price", "change24", "spark", "synth", "regime", "history"):
            self.assertIn(k, s)
        self.assertIn(s["synth"]["confidence"], ("faible", "moyenne", "élevée", "elevee", "haute"))
        self.assertIn("score", o["macro"])
        self.assertLessEqual(len(o["alerts"]), 6)

    def test_mtf_endpoint(self):
        for tf in ("5m", "4h", "1d"):
            code, body, _ = self.get(f"/api/mtf?symbol=BTCUSDT&tf={tf}")
            self.assertEqual(code, 200)
            r = json.loads(body)
            self.assertTrue(r["ready"])
            self.assertEqual(r["tf"], tf)
            self.assertTrue(0 < len(r["candles"]) <= 400)
            self.assertEqual([c[0] for c in r["candles"]], r["times"])                # VWAP alignee bougie par bougie
            if tf == "1d":
                self.assertIsNone(r["vwapD"])                                           # une bougie = un jour : pas de VWAP du jour
                self.assertEqual(len(r["vwapW"]), len(r["candles"]))
            else:
                self.assertEqual(len(r["vwapD"]), len(r["candles"]))
            self.assertTrue(r["session"]["rows"])
            self.assertTrue({l["name"] for l in r["levels"]} >= {"haut veille", "bas veille"})
        self.assertEqual(self.get("/api/mtf?symbol=BTCUSDT&tf=2m")[0], 404)
        self.assertEqual(self.get("/api/mtf?symbol=NOPEUSDT&tf=1h")[0], 404)

    def test_macroweek_endpoints(self):
        code, body, _ = self.get("/api/macroweek")
        self.assertEqual(code, 200)
        r = json.loads(body)
        self.assertTrue({"week", "events", "themes", "verdict", "markets", "crypto", "next", "summary", "sources"} <= set(r))
        code, body, _ = self.get("/api/macroweeks")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["current"], r["week"])
        self.assertEqual(self.get("/api/macroweek?week=pas-une-date")[0], 400)
        code, res = self.post("/api/macroweek/comment", {"week": r["week"]})
        self.assertEqual(code, 200)
        self.assertFalse(res["ok"])                                                       # pas de cle API Claude : message lisible
        self.assertIn("Clé API", res["answer"])

    def test_version_and_code_watch(self):
        from unittest import mock
        import server as server_mod
        code, body, h = self.get("/api/config")
        c = json.loads(body)
        self.assertEqual((c["api"], c["version"], c["stale"]), (server_mod.API_LEVEL, server_mod.VERSION, False))
        self.assertIsNone(h.get("X-Terminal-Stale"))
        hl = json.loads(self.get("/api/health")[1])
        self.assertEqual(hl["root"], str(server_mod.ROOT))
        app = self.app
        app.code_sig = "a"
        try:
            with mock.patch.object(server_mod, "code_signature", return_value="b"):
                self.assertEqual(app.code_check("a"), "b")                               # premiere fois : copie peut-etre en cours, on attend
                self.assertFalse(app.code_stale)
                with app.upd_lock:
                    app.code_check("b")                                                  # installation par updater.py : il relance lui-meme
                self.assertFalse(app.code_stale)
                app.code_check("b")                                                      # meme empreinte nouvelle deux fois : nouvelle version
                self.assertTrue(app.code_stale)
                self.assertFalse(app.restart_requested)                                  # lance sans run.py : pas de relance, un bandeau
            self.assertEqual(self.get("/api/config")[2].get("X-Terminal-Stale"), "1")
            with mock.patch.object(server_mod, "code_signature", return_value="a"):
                app.code_stale = False
                app.code_check("a")                                                      # rien n'a change
                self.assertFalse(app.code_stale)
        finally:
            app.code_stale, app.code_sig = False, None
        self.assertTrue(len(server_mod.code_signature()) == 40)

    def test_tpo_endpoint_profiles_and_confluences(self):
        for kind in ("D", "4h", "1h"):
            code, body, _ = self.get(f"/api/tpo?symbol=BTCUSDT&kind={kind}&rows=30")
            self.assertEqual(code, 200)
            r = json.loads(body)
            self.assertTrue(r["ready"])
            self.assertEqual(r["kind"], kind)
            self.assertTrue(r["sessions"] and r["sessions"][-1]["marks"]["current"])
            for s in r["sessions"]:
                self.assertTrue(s["low"] - s["step"] <= s["val"] <= s["poc"] <= s["vah"] <= s["high"] + s["step"])   # bornes arrondies a la ligne
                self.assertTrue(all(len(row) == 5 and row[1] == len(row[2]) for row in s["rows"]))       # prix, lettres (nombre, liste), volume, delta
        self.assertEqual(self.get("/api/tpo?symbol=BTCUSDT&kind=2h")[0], 404)
        self.assertEqual(self.get("/api/tpo?symbol=NOPEUSDT&kind=D")[0], 404)
        st = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=1h")[1])
        self.assertEqual(set(st["profiles"]), {"D", "W", "M"})                         # profils jour, semaine, mois au choix sur le graphique
        for k in ("W", "M"):
            if st["profiles"][k]:
                self.assertEqual(st["profiles"][k]["kind"], k)
        self.assertEqual(set(st["tpo"]), {"D", "4h", "1h"})
        names = {l["name"] for l in st["levels"] if l["kind"] == "tpo"}
        self.assertTrue(all(n.startswith(("Single prints", "Poor high", "Poor low")) for n in names))
        self.assertFalse(any(n.endswith("1 h") for n in names))                       # seances d'1 h : trop de marques pour les confluences
        m = self.app.service.markets["BTCUSDT"]
        with self.app.service.lock:
            plain = m.state("1h", tpo=False)                                         # ce que voient les idees de trade : sans TPO
        self.assertFalse([l for l in plain["levels"] if l["kind"] == "tpo"])
        self.assertIsNone(plain["tpo"])

    def test_flow_endpoint_and_session_profile(self):
        code, body, _ = self.get("/api/flow?symbol=BTCUSDT&step=50&rows=20")
        self.assertEqual(code, 200)
        f = json.loads(body)
        self.assertTrue(f["ready"] and f["simulated"])
        self.assertEqual(len(f["rows"]), 21)
        self.assertTrue({"tape", "latency", "big", "threshold", "book", "orders"} <= set(f))
        code, r = self.post("/api/flow/reset", {"symbol": "BTCUSDT"})
        self.assertEqual((code, r["ok"]), (200, True))
        self.assertEqual(self.get("/api/flow?symbol=NOPEUSDT&step=1")[0], 404)
        st = json.loads(self.get("/api/state?symbol=BTCUSDT&tf=5m")[1])
        se = st["session"]
        self.assertTrue(se["rows"] and se["val"] <= se["poc"] <= se["vah"])
        self.assertAlmostEqual(sum(r[1] for r in se["rows"]), se["volume"], places=6)

    def test_signals_endpoint_and_settings(self):
        code, body, _ = self.get("/api/signals?symbol=BTCUSDT")
        self.assertEqual(code, 200)
        r = json.loads(body)
        self.assertEqual(set(r), {"symbols", "desk", "on", "direction"})
        self.assertEqual(r["direction"], "both")                                       # par defaut : achats et ventes (V13.1)
        code, body, _ = self.get("/api/history")
        self.assertEqual(code, 200)
        h = json.loads(body)
        self.assertTrue({"trades", "stats", "week", "readings", "direction", "since", "bias"} <= set(h))
        self.assertEqual(set(r["desk"]), {"week", "waiting", "stats", "trades", "bias"})
        self.assertEqual(r["desk"]["week"]["cap"], 5)
        sg = r["symbols"]["BTCUSDT"]
        self.assertTrue(sg["ready"])
        for k in ("ideas", "rejected", "minScore", "maxWeek", "minStruct", "validation", "warm"):
            self.assertIn(k, sg)
        self.assertEqual(self.get("/api/signals?symbol=XXX")[0], 404)
        self.assertEqual(list(json.loads(self.get("/api/signals")[1])["symbols"]), ["BTCUSDT"])
        code, res = self.post("/api/settings", {"signalMinScore": 72, "signalMaxWeek": 2, "signalLeverage": 5, "signalOn": True})
        self.assertEqual(code, 200, res)
        self.assertEqual((res["signalMinScore"], res["signalMaxWeek"], res["signalLeverage"], res["signalOn"]), (72.0, 2, 5.0, True))
        self.assertEqual(self.app.cfg.signal_max_week, 2)
        self.assertEqual(self.app.desk.week(NOW)["cap"], 2)
        self.assertIn("TERMINAL_SIGNAL_MAX_WEEK=2", self.env.read_text())
        self.post("/api/settings", {"signalMinScore": 60, "signalMaxWeek": 5, "signalLeverage": 10})        # valeurs par defaut

    def test_per_pair_cap_setting(self):
        code, res = self.post("/api/settings", {"signalMaxPerSymbol": 2})
        self.assertEqual(code, 200, res)
        self.assertEqual(res["signalMaxPerSymbol"], 2)
        self.assertEqual(self.app.cfg.signal_max_per_symbol, 2)
        self.assertIn("TERMINAL_SIGNAL_MAX_PER_SYMBOL=2", self.env.read_text())
        self.post("/api/settings", {"signalMaxPerSymbol": 3})

    def test_trend_gate_setting_and_signal_fields(self):
        code, res = self.post("/api/settings", {"signalTrendGate": False})
        self.assertEqual(code, 200, res)
        self.assertFalse(res["signalTrendGate"])
        self.assertFalse(self.app.cfg.signal_trend_gate)
        self.assertIn("TERMINAL_SIGNAL_TREND_GATE=0", self.env.read_text())
        code, res = self.post("/api/settings", {"signalTrendGate": True})
        self.assertTrue(res["signalTrendGate"])
        sg = json.loads(self.get("/api/signals?symbol=BTCUSDT")[1])["symbols"]["BTCUSDT"]
        self.assertIn("regime", sg)
        self.assertTrue(sg["trendGate"])
        for i in sg["ideas"]:
            self.assertIn("align", i)
            if i["align"] is not None and i["align"] <= 0:
                self.assertFalse(i["eligible"], "une idee a contre-courant ou en tendance indecise n'est jamais envoyee")

    def test_backtest_endpoint(self):
        code, body, _ = self.get("/api/backtest")
        self.assertEqual(code, 200)
        lst = json.loads(body)["reports"]
        self.assertTrue(any(r["label"] == "BTC" for r in lst), "le rapport BTC est livre avec le terminal")
        code, body, _ = self.get("/api/backtest?label=BTC")
        rep = json.loads(body)
        for k in ("verdict", "terminal", "variants", "events", "trend", "period"):
            self.assertIn(k, rep)
        self.assertEqual(self.get("/api/backtest?label=XXX")[0], 404)
        self.assertTrue(any(r["kind"] == "strategy" and r["label"] == "BTC" for r in lst), "le rapport de la strategie est livre avec le terminal")
        code, body, _ = self.get("/api/backtest?label=BTC&kind=strategy")
        self.assertEqual(code, 200)
        rep = json.loads(body)
        self.assertEqual(rep["kind"], "vwap-strategy")
        for k in ("verdict", "best", "literal", "exits", "variants", "ranking", "hedge", "counts", "period", "eras"):
            self.assertIn(k, rep)
        self.assertIn(rep["verdict"]["level"], ("edge", "weak", "none"))
        self.assertEqual(len(rep["exits"]), 48)
        code, body, _ = self.get("/api/backtest?label=BTC&kind=avwap")
        self.assertEqual(code, 200)
        av = json.loads(body)
        self.assertEqual(av["kind"], "avwap-swing")
        for k in ("verdict", "best", "literal", "exits", "variants", "swing", "counts"):
            self.assertIn(k, av)
        self.assertEqual(len(av["exits"]), 12)
        self.assertTrue(av["swing"]["sizes"][0]["reaction"])
        self.assertEqual(self.get("/api/backtest?label=BTC&kind=autre")[0], 400)
        self.assertEqual(self.get("/api/backtest?label=XXX&kind=strategy")[0], 404)

    def test_strategy_endpoint(self):
        code, body, _ = self.get("/api/strategy?symbol=BTCUSDT")
        self.assertEqual(code, 200)
        v = json.loads(body)
        self.assertTrue(v["ready"])
        self.assertIn("levels", v)
        self.assertIn("report", v)
        self.assertEqual(v["report"]["label"], "BTC")
        self.assertEqual(v["avwapReport"]["label"], "BTC")
        self.assertIn("anchors", v["swing"])
        self.assertFalse(v["report"]["proxy"])
        sol = json.loads(self.get("/api/strategy?symbol=SOLUSDT")[1])
        if sol.get("ready"):
            self.assertTrue(sol["report"]["proxy"])
        self.assertEqual(self.app.cfg.signal_max_week, 5)
        code, res = self.post("/api/settings", {"signalOn": False})
        self.assertFalse(res["signalOn"])
        self.assertFalse(json.loads(self.get("/api/signals?symbol=BTCUSDT")[1])["symbols"]["BTCUSDT"]["ready"])
        self.post("/api/settings", {"signalOn": True})

    def test_influencers_settings_endpoint_and_token_never_leaks(self):
        from tests.test_social import FakeX
        x = HTTPServer(("127.0.0.1", 0), FakeX)
        threading.Thread(target=x.serve_forever, daemon=True).start()
        try:
            off = json.loads(self.get("/api/influencers?symbol=BTCUSDT&side=long")[1])
            self.assertEqual(off, {"on": False, "configured": False})
            self.assertFalse(self.app.settings()["x"]["configured"])
            self.env.write_text(self.env.read_text() + f"TERMINAL_X_API_BASE=http://127.0.0.1:{x.server_address[1]}\n")
            tok = "good-secret-1234567"
            code, res = self.post("/api/settings", {"xToken": tok, "xAccounts": "@alice, bob, bad-handle", "xPosts": 5, "xOn": True})
            self.assertEqual(code, 200, res)
            self.assertEqual(res["x"], {"on": True, "configured": True, "tokenHint": "...4567", "accounts": ["alice", "bob"], "posts": 5})
            self.assertNotIn(tok, json.dumps(res))
            self.assertNotIn(tok, self.get("/api/config")[1].decode())
            self.assertNotIn(tok, self.get("/api/settings")[1].decode())
            self.assertIn(f"TERMINAL_X_BEARER_TOKEN={tok}", self.env.read_text())
            on = json.loads(self.get("/api/influencers?symbol=BTCUSDT&side=short")[1])
            self.assertTrue(on["on"])
            self.assertEqual([a["handle"] for a in on["accounts"]], ["alice", "bob"])
            self.assertEqual(set(on["summary"]), {"agree", "disagree", "neutral", "none", "total", "errors"})
            self.assertTrue(self.post("/api/test/x", {})[1]["ok"])
            self.assertFalse(self.post("/api/test/x", {"token": "bad"})[1]["ok"])
            self.assertEqual(self.get("/api/influencers?symbol=XXX&side=long")[0], 404)
            self.assertEqual(self.get("/api/influencers?symbol=BTCUSDT&side=up")[0], 400)
            self.assertEqual(self.post("/api/test/x", {}, token=False)[0], 403)              # sans jeton de session
            self.assertEqual(self.post("/api/settings", {"xToken": "a b"})[0], 400)
        finally:
            self.post("/api/settings", {"xClearToken": True, "xAccounts": "", "xOn": False})
            self.assertFalse(self.app.settings()["x"]["configured"])
            x.shutdown()
            x.server_close()

    def test_overview_has_ideas_and_week(self):
        o = json.loads(self.get("/api/overview")[1])
        for k in ("week", "tradeStats", "openTrades"):
            self.assertIn(k, o)
        self.assertIn("idea", o["symbols"][0])

    def test_heat_payload_and_gzip(self):
        import base64, gzip as gz
        req = urllib.request.Request(self.url + "/api/heat?symbol=BTCUSDT", headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=20) as r:
            self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
            h = json.loads(gz.decompress(r.read()))
        self.assertTrue(h["ready"])
        n, m = h["n"], h["m"]
        self.assertGreater(n, 400)
        self.assertEqual(len(base64.b64decode(h["long"])), n * m)
        self.assertEqual(len(base64.b64decode(h["short"])), n * m)
        self.assertGreater(sum(1 for b in base64.b64decode(h["long"]) if b), 100)             # des cellules allumees
        lo = h["b0"] * h["step"]
        import math
        self.assertLess(math.exp(lo), h["price"])
        self.assertGreater(math.exp((h["b0"] + m) * h["step"]), h["price"])                    # la fenetre contient le prix
        self.assertEqual(self.get("/api/heat?symbol=XXX")[0], 404)

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

    def test_live_price_fallback_endpoint(self):
        code, body, _ = self.get("/api/price?symbol=BTCUSDT")
        self.assertEqual(code, 200)
        r = json.loads(body)
        self.assertGreater(r["price"], 0)
        self.assertEqual(r["t"], NOW)
        self.assertEqual(self.get("/api/price?symbol=XXX")[0], 404)
        self.assertEqual(json.loads(self.get("/api/config")[1])["wsBase"], "")   # simule : pas de flux Binance

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
        self.assertEqual(st["alertMode"], "ideas")                                    # par defaut : seulement les idees de trade
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
        code, res = self.post("/api/settings", {"alertMode": "all"})
        self.assertEqual(res["alertMode"], "all")
        self.assertIn("TERMINAL_ALERT_MODE=all", self.env.read_text())
        self.post("/api/settings", {"alertMode": "ideas"})
        self.assertEqual(self.app.cfg.alert_mode, "ideas")
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
