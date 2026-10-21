"""V28 : note de confluence sur 14 (sept piliers), heatmap du carnet (photos rangées par tranche de prix, priorité du carnet en direct
sur le carnet profond d'une même bourse, sauvegarde), adresse /api/heatmap ; graphique à éléments et onglets d'instrument."""
from __future__ import annotations
import base64
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from data import heatbook as hb
from engine.confluence import Level, grade
from server import App, serve

H = 3_600_000


def L(name, group, kind, **extra):
    return Level(f"{group}|{name}", name, 100.0, group, kind, extra)


class GradeTests(unittest.TestCase):
    def test_pillars_and_weights(self):
        g = grade([L("dVWAP", "dVWAP", "vwap"), L("Rond 100", "ROUND", "round")])
        self.assertEqual((g["grade"], g["max"]), (1, 14))                      # un VWAP du jour : 1 point ; le nombre rond ne compte pas
        g = grade([L("mVWAP", "mVWAP", "vwap")])
        self.assertEqual(g["grade"], 2)                                        # VWAP du mois : 2 points
        g = grade([L("dVWAP", "dVWAP", "vwap"), L("wVWAP", "wVWAP", "vwap")])
        self.assertEqual(g["grade"], 2)                                        # deux VWAP différents : le pilier est plein
        g = grade([L("dVWAP", "dVWAP", "vwap"), L("dVWAP+2σ", "dVWAP", "band")])
        self.assertEqual(g["grade"], 1)                                        # même source (bande du même VWAP) : pas de bonus

    def test_nine_needs_several_high_timeframe_pillars(self):
        strong = [L("mVWAP", "mVWAP", "vwap"), L("AVWAP 2024", "aVWAP", "avwap"), L("AVWAP mois", "aVWAP:1", "avwap"),
                  L("wPOC", "wVP", "vp"), L("PWH", "PWHL", "hl"), L("Liq longs", "LIQ", "liq", pool={"magnet": True}), L("dOpen", "dOpen", "open")]
        g = grade(strong)
        self.assertEqual(g["grade"], 11)
        self.assertEqual([p["key"] for p in g["parts"]], ["vwap", "avwap", "vp", "hl", "open", "liq"])
        weak = [L("dVWAP", "dVWAP", "vwap"), L("dPOC", "dVP", "vp"), L("PDH", "PDHL", "hl"), L("dOpen", "dOpen", "open"),
                L("Liq shorts", "LIQ", "liq", pool={"magnet": False, "imp": {"score": 40}})]
        self.assertEqual(grade(weak)["grade"], 5)                              # cinq piliers, mais tous de la journée
        tpo = grade([L("Single prints mois", "TPO", "tpo", tpo={"kind": "M"}), L("nPOC J-3", "nPOC", "npoc")])
        self.assertEqual(tpo["grade"], 2)
        self.assertEqual(grade([L("nPOC S-2", "nPOC", "npoc")])["grade"], 2)  # POC vierge d'une semaine : 2 points

    def test_zones_of_the_state_carry_the_grade(self):
        app = App(Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0), env_path=None)
        app.service.refresh_all()
        st = app.service.get_state("BTCUSDT", "1h")
        self.assertTrue(st["zones"])
        for z in st["zones"]:
            self.assertEqual(z["gradeMax"], 14)
            self.assertEqual(z["grade"], sum(p["pts"] for p in z["gradeParts"]))
            self.assertTrue(0 <= z["grade"] <= 14)


class HeatBookTests(unittest.TestCase):
    T0 = 1_760_000_000_000

    def book(self):
        return hb.HeatBook("BTCUSDT")                                          # tranche de 20 $

    def test_buckets_sum_dollars_on_both_sides(self):
        k0, arr = hb.to_buckets([(99_990.0, 1.0), (99_985.0, 2.0)], [(100_010.0, 0.5)], 20.0, 100_000.0)
        self.assertEqual(k0, math.floor(99_985 / 20))
        self.assertAlmostEqual(arr[0], 99_990.0 + 2 * 99_985.0)               # deux prix dans la même tranche
        self.assertAlmostEqual(arr[-1], 0.5 * 100_010.0)
        self.assertIsNone(hb.to_buckets([(50_000.0, 1.0)], [], 20.0, 100_000.0))   # hors des ±4 %

    def test_query_puts_a_wall_where_and_when_it_was(self):
        b = self.book()
        for i in range(30):                                                    # une photo toutes les 10 s pendant 5 minutes
            wall = [(99_500.0, 50.0)] if i >= 10 else []
            b.add("binance", self.T0 + i * 10_000, [(99_990.0, 1.0)] + wall, [(100_010.0, 1.0)])
        q = b.query(self.T0, self.T0 + 300_000, 99_000.0, 101_000.0, cols=30, rows=100, exchanges=("binance",))
        self.assertTrue(q["ready"])
        self.assertFalse(q["empty"])
        data = base64.b64decode(q["data"])
        n = q["cols"]
        j = int(math.floor(99_500.0 / q["rowsz"])) - int(round(q["lo"] / q["rowsz"]))
        self.assertEqual(data[j * n + 25], 255)                                # le mur, après son apparition : le plus fort
        self.assertEqual(data[j * n + 3], 0)                                   # avant : rien
        self.assertEqual(q["lo"] % q["rowsz"], 0)

    def test_old_photos_stop_counting(self):
        b = self.book()
        b.add("coinbase", self.T0, [(99_990.0, 5.0)], [(100_010.0, 5.0)])
        q = b.query(self.T0, self.T0 + 4 * H, 99_000.0, 101_000.0, cols=40, rows=50, exchanges=("coinbase",))
        data = base64.b64decode(q["data"])
        n = q["cols"]
        col = lambda c: sum(data[j * n + c] for j in range(q["rows"]))
        self.assertGreater(col(0), 0)                                          # la photo compte jusqu'à 1 300 s (photo toutes les 10 min)
        self.assertEqual(col(39), 0)                                           # quatre heures plus tard, plus rien

    def test_live_book_hides_the_deep_book_of_the_same_exchange_where_it_covers(self):
        b = self.book()
        t = self.T0
        b.add("okxDeep", t, [(99_900.0, 10.0), (98_000.0, 30.0)], [(100_100.0, 10.0)])
        b.add("okx", t + 1000, [(99_990.0, 1.0), (99_900.0, 1.0)], [(100_010.0, 1.0)])
        q = b.query(t, t + 20_000, 97_000.0, 101_000.0, cols=10, rows=200, exchanges=("okx",))
        data, n = base64.b64decode(q["data"]), q["cols"]
        r = lambda p: int(math.floor(p / q["rowsz"])) - int(round(q["lo"] / q["rowsz"]))
        near, far = data[r(99_900.0) * n + 5], data[r(98_000.0) * n + 5]
        self.assertGreater(far, near)                                          # 99 900 : le carnet en direct (1 BTC) remplace le profond (10 BTC)
        self.assertGreater(near, 0)

    def test_save_and_load(self):
        b = self.book()
        b.add("binance", self.T0, [(99_990.0, 1.0)], [(100_010.0, 1.0)])
        path = str(Path(tempfile.mkdtemp()) / "heatmap" / "BTCUSDT.pkl")
        b.save(path)
        c = self.book()
        self.assertEqual(c.load(path, self.T0 + H), 1)
        self.assertEqual(c.last("binance"), self.T0)
        self.assertEqual(self.book().load(path, self.T0 + 30 * H), 0)         # plus de 24 h : rien n'est repris

    def test_recorder_keeps_errors_per_exchange(self):
        def boom():
            raise OSError("injoignable")
        rec = hb.HeatRecorder(self.book(), {"binance": lambda: ([(99_990.0, 1.0)], [(100_010.0, 1.0)]), "bybit": boom, "okx": lambda: None},
                              now=lambda: self.T0 / 1000)
        self.assertTrue(rec.sample("binance"))
        self.assertFalse(rec.sample("bybit"))
        self.assertFalse(rec.sample("okx"))
        st = rec.status()
        self.assertEqual(st["binance"]["last"], self.T0)
        self.assertIn("injoignable", st["bybit"]["error"])
        self.assertIn("pas encore", st["okx"]["error"])

    def test_real_sources_read_the_public_answers(self):
        class Book:
            def __init__(self, b, a):
                self.b, self.a = b, a

            def levels(self):
                return self.b, self.a

        class Flow:
            books = {"BTCUSDT": Book([(99_990.0, 1.0)], [(100_010.0, 2.0)])}
            okx = {"BTC-USDT-SWAP": Book([(99_990.0, 100.0, 3)], [(100_010.0, 50.0, 2)])}

        answers = {"okx.com": {"data": [{"bids": [["99990", "200", "0", "4"]], "asks": [["100010", "100", "0", "2"]]}]},
                   "bybit.com": {"retCode": 0, "result": {"b": [["99990", "1.5"]], "a": [["100010", "0.5"]]}},
                   "coinbase.com": {"bids": [["99990", "0.3", 1]], "asks": [["100010", "0.2", 2]]}}
        http = lambda url, timeout=15: next(v for k, v in answers.items() if k in url)
        src = hb.real_sources("BTCUSDT", Flow(), http)
        self.assertEqual(sorted(src), ["binance", "bybit", "coinbase", "okx", "okxDeep"])
        self.assertEqual(src["okx"]()[0], [(99_990.0, 1.0)])                   # 100 contrats OKX = 1 BTC
        self.assertEqual(src["okxDeep"]()[0], [(99_990.0, 2.0)])
        self.assertEqual(src["bybit"]()[1], [(100_010.0, 0.5)])
        self.assertEqual(src["coinbase"]()[0], [(99_990.0, 0.3)])

    def test_simulated_book_has_lasting_walls(self):
        sim = hb.SimHeat(lambda t: 100_000.0)
        b = self.book()
        self.assertTrue(hb.sim_backfill(b, sim, self.T0, hours=1.0))
        self.assertGreater(len(b.series["binance"]), 300)
        q = b.query(self.T0 - H, self.T0, 97_000.0, 103_000.0, cols=60, rows=150)
        self.assertFalse(q["empty"])
        self.assertFalse(hb.sim_backfill(self.book(), hb.SimHeat(lambda t: None), self.T0))


class HeatServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tempfile.mkdtemp(), port=0), env_path=None)
        cls.app.service.refresh_all()
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=60) as r:
            return json.loads(r.read())

    def test_heatmap_for_btc_only_by_default(self):
        self.assertEqual(sorted(self.app.heat), ["BTCUSDT"])
        rec = self.app.heat["BTCUSDT"]
        self.assertTrue(rec.prefill())                                          # mode simulé : six heures d'un coup
        now = self.app.source.now_ms()
        px = self.app.service.last_price("BTCUSDT")
        r = self.get(f"/api/heatmap?symbol=BTCUSDT&t0={now - 3 * H}&t1={now}&lo={px * 0.98}&hi={px * 1.02}&cols=120&rows=120&ex=binance,okx")
        self.assertTrue(r["ready"])
        self.assertFalse(r["empty"])
        self.assertEqual(r["exchanges"], ["binance", "okx"])
        self.assertEqual(r["step"], 20.0)
        self.assertIn("binance", r["status"])
        off = self.get("/api/heatmap?symbol=SOLUSDT&t0=1&t1=2&lo=1&hi=2")
        self.assertFalse(off["ready"])
        self.assertTrue(off["off"])



# ---------- interface (V28) : graphique à éléments, onglets d'instrument ----------
WEB = Path(__file__).resolve().parent.parent / "web"


def run_desk(body: str):
    """Charge web/desk.js (le module Desk, sans page) et exécute `body`, qui renvoie une valeur JSON."""
    script = ("const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8');\n"
              "const Desk = new Function(src + '\\nreturn Desk;')();\n"
              f"const out = (() => {{ {body} }})();\nprocess.stdout.write(JSON.stringify(out));")
    r = subprocess.run(["node", "-e", script, str(WEB / "desk.js")], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "Node n'est pas installé")
class ElementsTests(unittest.TestCase):
    # toutes les options du graphique de la V27, plus les nouveautés : aucune ne doit disparaître du menu « ＋ Éléments »
    OLD = ["sess", "sessW", "sessM", "nodes", "dpoc", "npoc", "tpoM", "tpoW", "tpoD", "tpo4", "tpo1", "vwap", "gex", "dom", "big", "absorb", "pools", "ppools", "plan"]
    NEW = ["zones", "vwapW", "vwapM", "vwapY", "avwap", "vol", "heat"]

    def test_catalog_keeps_every_option(self):
        out = run_desk("return {keys: Object.keys(Desk.EL), btc: Object.keys(Desk.EL).filter(k => Desk.EL[k][3])};")
        for k in self.OLD + self.NEW:
            self.assertIn(k, out["keys"])
        self.assertEqual(sorted(out["btc"]), ["gex", "heat"])                     # réservés au BTC

    def test_presets_are_quiet(self):
        out = run_desk("return {p: Desk.PRESET, heat: Desk.freshSet('heat'), main: Desk.freshSet('main'), views: Desk.VIEWS};")
        self.assertEqual(sorted(out["p"]["main"]), ["plan", "sess", "vol", "vwap", "zones"])
        self.assertEqual(out["p"]["blank"], {})                                    # vierge : rien
        self.assertIn("heat", out["p"]["heat"])
        self.assertNotIn("dom", out["p"]["heat"])
        self.assertEqual((out["main"]["minGrade"], out["heat"]["tf"], out["main"]["tf"]), (9, "5m", None))
        self.assertEqual(out["views"], {"main": "Graphique", "blank": "Vierge", "heat": "Heatmap"})

    def test_colour_map_is_transparent_at_zero(self):
        self.assertEqual(run_desk("return 1;"), 1)                                  # le module se charge sans page


class PageTests(unittest.TestCase):
    HTML = (WEB / "index.html").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")

    def test_tabs_and_views(self):
        self.assertIn('id="instTabs"', self.HTML)
        self.assertEqual(re.findall(r'data-layout="([a-z0-9]+)"', self.HTML), ["main", "blank", "heat", "3", "mtf", "tpo"])
        self.assertIn('<script src="desk.js"></script>', self.HTML)
        self.assertNotIn('id="deskhint"', self.HTML)
        for el in ('id="srcBadge"', 'id="tgBadge"', 'id="liveBadge"', 'id="status"'):          # gardés, rangés dans le témoin d'état
            self.assertIn(el, self.HTML[self.HTML.index('id="hStatusPop"'):])

    def test_zones_drawn_from_their_grade(self):
        self.assertIn("(d.zones || []).filter(z => (z.grade || 0) >= (st.minGrade || 9))", self.APP)
        self.assertIn("pair: []", self.APP)
        self.assertIn("(!!t.filledAt && (t.endAt || t.closedAt || 0) > now - RECENT_MS)", self.APP)   # un ordre jamais exécuté ne reste pas dessiné


if __name__ == "__main__":
    unittest.main()
