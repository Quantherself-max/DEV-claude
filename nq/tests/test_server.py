import http.client
import json
import tempfile
import unittest
from datetime import datetime, timezone

from config import Config
from data.simulated import SimulatedSource
from engine.account import Account
from server import App, serve_in_thread
from service import Service, parse_position

NOW = int(datetime(2026, 10, 12, 16, 40, tzinfo=timezone.utc).timestamp() * 1000)


def strict(text):
    def bad(c):
        raise ValueError(f"valeur JSON interdite : {c}")
    return json.loads(text, parse_constant=bad)


class FlakySource(SimulatedSource):
    """Source dont la premiere lecture de l'historique echoue a mi-chemin (fichier supprime pendant la lecture, par exemple)."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = 0

    def history(self, now_ms):
        self.calls += 1
        ticks = super().history(now_ms)
        if self.calls == 1:
            from data.base import DataError

            def broken():
                for i, t in enumerate(ticks):
                    if i == 2000:
                        raise DataError("fichier supprimé pendant la lecture")
                    yield t
            return broken()
        return ticks


class ServiceRecoveryTests(unittest.TestCase):
    def test_retry_after_partial_load_does_not_double_the_volume(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(data_dir=d)
            src = FlakySource(days=2, now_fn=lambda: NOW)
            svc = Service(cfg, source=src, account=Account(f"{d}/c.json"))
            self.assertEqual(svc.load_sync(), 0)
            self.assertEqual(svc.status["state"], "error")
            self.assertIn("supprimé", svc.status["msg"])
            self.assertEqual(svc.market.count, 0)                      # rien de la lecture interrompue ne reste
            n = svc.pump_once()                                        # la reprise recharge tout, une seule fois
            self.assertGreater(n, 50_000)
            self.assertEqual(svc.status["state"], "ready")
            ref = Service(cfg, source=SimulatedSource(days=2, now_fn=lambda: NOW), account=Account(f"{d}/c2.json"))
            ref.load_sync()
            self.assertEqual(svc.market.count, ref.market.count)
            day = svc.market.day()
            self.assertAlmostEqual(svc.market.ladder(day, "gx").volume, ref.market.ladder(day, "gx").volume)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = Config(data_dir=cls.tmp.name, sim_days=3)
        src = SimulatedSource(days=3, now_fn=lambda: NOW)
        svc = Service(cfg, source=src, account=Account(f"{cls.tmp.name}/compte.json", now_ms=lambda: NOW))
        svc.load_sync()
        cls.app = App(cfg, svc)
        cls.httpd, _ = serve_in_thread(cls.app, 0)
        cls.port = cls.httpd.server_address[1]
        cls.token = cls.app.token

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, headers=None, token=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token and method == "POST":
            h["X-NQ-Token"] = self.token
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        try:
            return r.status, (strict(raw) if r.getheader("Content-Type", "").startswith("application/json") else raw)
        except ValueError:
            return r.status, raw

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body, **kw):
        return self.req("POST", path, body, **kw)

    # ---------- lecture ----------
    def test_health_config_state(self):
        st, h = self.get("/api/health")
        self.assertEqual((st, h["ok"]), (200, True))
        st, c = self.get("/api/config")
        self.assertEqual(c["token"], self.token)
        self.assertIn("5m", c["tfs"])
        st, s = self.get("/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(s["status"]["state"], "ready")
        self.assertTrue(s["source"]["simulated"])
        self.assertEqual(s["inst"]["root"], "NQ")
        self.assertEqual(s["inst"]["tickValue"], 5.0)
        self.assertEqual(s["contract"]["code"], "NQZ6")
        self.assertEqual(s["day"], "2026-10-12")
        self.assertEqual(s["clock"]["paris"], "18:40:00")
        self.assertEqual(s["clock"]["et"], "12:40:00")
        self.assertEqual(s["clock"]["phase"]["key"], "lunch")
        self.assertEqual(s["clock"]["marks"][0]["paris"], "19:30")
        self.assertEqual(len(s["tape"]) > 0 and s["tape"][0]["t"] >= s["tape"][-1]["t"], True)      # le ruban : le plus recent d'abord

    def test_bars_full_and_incremental(self):
        st, b = self.get("/api/bars?tf=5m&limit=120")
        self.assertEqual(st, 200)
        self.assertTrue(b["full"])
        n = len(b["bars"])
        self.assertEqual(n, 120)
        for key in ("v", "u1", "l1", "u2", "l2"):
            self.assertEqual(len(b["vwapRth"][key]), n)
            self.assertEqual(len(b["vwapGx"][key]), n)
        self.assertEqual((len(b["cvdRth"]), len(b["cvdGx"])), (n, n))
        r = b["bars"][-1]
        self.assertTrue(r["l"] <= r["o"] <= r["h"] and r["l"] <= r["c"] <= r["h"])
        self.assertGreater(b["vwapGx"]["v"][-1], 20_000)
        self.assertIsNone(b["vwapRth"]["v"][0] if b["bars"][0]["t"] < 1791811800 else None)         # avant 9 h 30 ET : pas de VWAP de seance
        # le dernier VWAP / CVD de seance = ceux du Market
        lad = self.app.service.market.ladder("2026-10-12", "rth")
        self.assertAlmostEqual(b["vwapRth"]["v"][-1], lad.vwap, places=1)
        self.assertAlmostEqual(b["cvdRth"][-1], lad.delta, places=1)
        # incremental : la fin seulement
        since = b["bars"][-3]["t"] * 1000
        st, inc = self.get(f"/api/bars?tf=5m&limit=120&since={since}")
        self.assertFalse(inc["full"])
        self.assertEqual(inc["bars"], b["bars"][-3:])
        self.assertEqual(len(inc["cvdRth"]), len(inc["bars"]))
        self.assertEqual(inc["vwapRth"]["v"], b["vwapRth"]["v"][-3:])

    def test_bars_errors(self):
        self.assertEqual(self.get("/api/bars?tf=7m")[0], 400)
        self.assertEqual(self.get("/api/bars?limit=abc")[0], 400)
        st, b = self.get("/api/bars?tf=1h&limit=5")
        self.assertEqual(len(b["bars"]), 5)

    def test_profile(self):
        st, p = self.get("/api/profile?which=rth")
        self.assertFalse(p["empty"])
        self.assertEqual(p["day"], "2026-10-12")
        self.assertLess(p["val"], p["poc"] + 1e-9)
        self.assertGreater(p["vah"], p["poc"] - 1e-9)
        self.assertAlmostEqual(sum(r["s"] + r["b"] for r in p["rows"]), p["total"], places=3)
        self.assertEqual(sum(1 for r in p["rows"] if r["poc"]), 1)
        st, prev = self.get("/api/profile?which=prev")
        self.assertEqual(prev["day"], "2026-10-09")
        st, gx = self.get("/api/profile?which=gx&rows=20")
        self.assertEqual(gx["rowTicks"], 20)
        self.assertGreater(gx["total"], p["total"])

    def test_footprint(self):
        st, f = self.get("/api/footprint?tf=5m&n=2")
        self.assertEqual(st, 200)
        self.assertEqual(len(f["bars"]), 2)
        b = f["bars"][-1]
        prices = [r[0] for r in b["rows"]]
        self.assertEqual(prices, sorted(prices, reverse=True))
        self.assertAlmostEqual(sum(r[1] + r[2] for r in b["rows"]), b["v"], places=3)
        self.assertAlmostEqual(sum(r[2] - r[1] for r in b["rows"]), b["delta"], places=3)
        self.assertEqual(sum(1 for r in b["rows"] if r[3] & 4), 1)                                 # un seul POC
        self.assertEqual(self.get("/api/footprint?tf=9m")[0], 400)

    def test_levels_context_account(self):
        st, lv = self.get("/api/levels")
        self.assertEqual(st, 200)
        self.assertTrue(any(x["name"] == "VWAP" for x in lv["levels"]))
        self.assertTrue(lv["near"]["above"] and lv["near"]["below"])
        st, ctx = self.get("/api/context")
        self.assertTrue(ctx["ready"])
        self.assertTrue(any(n["tone"] == "warn" and "SIMULÉES" in n["text"] for n in ctx["notes"]))
        st, ac = self.get("/api/account")
        self.assertEqual((ac["start"], ac["floor"], ac["status"]), (25_000, 24_000, "ok"))
        self.assertIsNone(ac["position"])

    def test_position_gives_open_pnl(self):
        price = self.app.service.market.price
        st, ac = self.get(f"/api/account?pos=long,NQ,2,{price - 10}")
        self.assertAlmostEqual(ac["openPnl"], 10 * 20 * 2, places=2)
        self.assertEqual(ac["position"]["qty"], 2)
        self.assertAlmostEqual(ac["equity"], ac["balance"] + 400, places=2)
        st, ac = self.get(f"/api/account?pos=short,MNQ,5,{price - 10}")
        self.assertAlmostEqual(ac["openPnl"], -10 * 2 * 5, places=2)
        st, ac = self.get("/api/account?pos=n-importe-quoi")
        self.assertIsNone(ac["position"])
        self.assertIsNone(parse_position("long,XYZ,1,100"))
        self.assertIsNone(parse_position("up,NQ,1,100"))
        self.assertIsNone(parse_position("long,NQ,0,100"))

    def test_plan(self):
        st, p = self.get("/api/plan?side=long&entry=25000&stop=24990&targets=25020,25030&root=NQ&risk=100")
        self.assertEqual(st, 200)
        self.assertEqual(p["sizes"]["MNQ"]["qty"], 4)
        self.assertEqual(len(p["sizes"]["MNQ"]["targets"]), 2)
        self.assertEqual(self.get("/api/plan?side=long&entry=25000&stop=25010&targets=25020")[0], 400)   # stop du mauvais cote
        self.assertEqual(self.get("/api/plan?side=long&stop=25010")[0], 400)

    # ---------- securite ----------
    def test_foreign_host_refused(self):
        self.assertEqual(self.get("/api/state", host="evil.example.com")[0], 403)
        self.assertEqual(self.post("/api/account/undo", {}, host="evil.example.com")[0], 403)

    def test_post_needs_token(self):
        self.assertEqual(self.post("/api/account/undo", {}, token=False)[0], 403)
        self.assertEqual(self.post("/api/account/undo", {}, token=False, headers={"X-NQ-Token": "faux"})[0], 403)

    def test_static_files_are_served_with_the_right_types(self):
        st, html = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn("NQ", html)
        # chaque script et feuille de style que la page reference doit exister (une faute de frappe = page blanche)
        import re
        refs = re.findall(r'(?:src|href)="([^":]+\.(?:js|css))"', html)
        self.assertGreaterEqual(len(refs), 5)
        for ref in refs:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            c.request("GET", "/" + ref, headers={"Host": f"127.0.0.1:{self.port}"})
            r = c.getresponse()
            body = r.read()
            self.assertEqual(r.status, 200, ref)
            self.assertGreater(len(body), 100, ref)
            ctype = r.getheader("Content-Type")
            self.assertTrue(ctype.startswith("text/javascript" if ref.endswith(".js") else "text/css"), (ref, ctype))
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            c.close()

    def test_unknown_and_traversal(self):
        self.assertEqual(self.get("/api/nimportequoi")[0], 404)
        self.assertEqual(self.post("/api/nimportequoi", {})[0], 404)
        st, _ = self.get("/../server.py")
        self.assertEqual(st, 404)
        self.assertEqual(self.get("/%2e%2e/server.py")[0], 404)

    def test_bad_json(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/account/undo", body=b"{pas du json", headers={"Host": f"127.0.0.1:{self.port}", "X-NQ-Token": self.token})
        self.assertEqual(c.getresponse().status, 400)
        c.close()
        self.assertEqual(self.req("POST", "/api/account/undo", [1, 2])[0], 400)

    def test_rejected_post_does_not_poison_the_connection(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps({"x": "y" * 500}).encode()
        c.request("POST", "/api/account/undo", body=body, headers={"Host": f"127.0.0.1:{self.port}", "X-NQ-Token": "faux"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        c.request("GET", "/api/health", headers={"Host": f"127.0.0.1:{self.port}"})           # meme connexion : doit repondre normalement
        r = c.getresponse()
        self.assertEqual((r.status, strict(r.read().decode())["ok"]), (200, True))
        c.close()

    def test_oversized_post_is_refused(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/api/account/undo", skip_host=True)
        for k, v in (("Host", f"127.0.0.1:{self.port}"), ("X-NQ-Token", self.token), ("Content-Length", str(10 ** 7))):
            c.putheader(k, v)
        c.endheaders()
        self.assertEqual(c.getresponse().status, 413)
        c.close()

    # ---------- ecritures (a la fin : l'ordre alphabetique les place apres les lectures de compte) ----------
    def test_zz_journal_roundtrip(self):
        self.post("/api/account/reset", {"confirm": True})
        st, r = self.post("/api/account/trade", {"inst": "NQ", "side": "long", "qty": 1, "entry": 25000, "exit": 25010, "setup": "vwap"})
        self.assertEqual((st, r["net"]), (200, 196.5))
        st, ac = self.get("/api/account")
        self.assertEqual(ac["todayPnl"], 196.5)
        self.assertEqual(len(ac["records"]), 1)
        self.assertEqual(ac["balance"], 25_196.5)
        st, r2 = self.post("/api/account/trade", {"inst": "MNQ", "side": "long", "qty": 2, "entry": 25000, "exit": 25010, "hold_s": 4})
        self.assertEqual((st, r2["hold_s"]), (200, 4.0))
        st, ac = self.get("/api/account")
        self.assertEqual((ac["micro"]["known"], ac["micro"]["shortWins"]), (1, 40 - 2.0))      # 10 pts x 2 $ x 2 contrats, moins 1,00 $ x 2 de frais
        self.post("/api/account/undo", {})
        st, bad = self.post("/api/account/trade", {"inst": "NQ", "side": "long", "qty": 1.5, "entry": 25000, "exit": 25010})
        self.assertEqual(st, 400)
        self.assertIn("entier", bad["error"])
        st, perf = self.get("/api/account/perf")
        self.assertEqual(perf["all"]["n"], 1)
        self.assertEqual(perf["bySetup"]["vwap"]["n"], 1)
        st, u = self.post("/api/account/undo", {})
        self.assertEqual(u["undone"]["id"], r["id"])
        self.assertEqual(self.get("/api/account")[1]["todayPnl"], 0)

    def test_zz_reset_needs_confirmation_and_profile(self):
        self.post("/api/account/adjust", {"day": "2026-10-08", "net": 300, "note": "reprise"})
        self.assertEqual(self.post("/api/account/reset", {})[0], 400)
        self.assertEqual(self.get("/api/account")[1]["profit"], 300)
        st, p = self.post("/api/account/profile", {"changes": {"risk_per_trade": 80}})
        self.assertEqual((st, p["risk_per_trade"]), (200, 80))
        self.assertEqual(self.post("/api/account/profile", {"changes": {"zzz": 1}})[0], 400)
        self.post("/api/account/profile", {"changes": {"risk_per_trade": 100}})
        self.assertEqual(self.post("/api/account/reset", {"confirm": True})[1]["erased"], 1)

    def test_zz_file_test(self):
        st, r = self.post("/api/test/file", {"path": f"{self.tmp.name}/absent.csv"})
        self.assertEqual(st, 200)
        self.assertFalse(r["ok"])
        self.assertIn("introuvable", r["message"])


if __name__ == "__main__":
    unittest.main()
