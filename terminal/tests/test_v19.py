"""V19 : profil de volume selon le trajet des bougies, noeuds, POC evolutif ; mesure TPO sur l'historique ; precision des zones ; adresses."""
import json
import random
import tempfile
import unittest

from engine import fine, sessionvp, tpostudy, zoneprec
from engine.atr import Candle

M5 = 5 * 60_000
M15 = 15 * 60_000
DAY = 86_400_000


class SessionVpTests(unittest.TestCase):
    def test_path_distribution_counts_twice_traversed_prices(self):
        k = Candle(0, 100.5, 101.0, 100.0, 100.8, 9.0, 6.0)                       # haussiere : 100,5 -> 100 -> 101 -> 100,8
        vol, buy = [0.0] * 10, [0.0] * 10
        sessionvp.spread(k, 1000, 10, 0.1, vol, buy, path=True)
        self.assertAlmostEqual(sum(vol), 9.0)
        self.assertAlmostEqual(sum(buy), 6.0)
        self.assertGreater(vol[2], vol[6])                                         # 100,2 traverse deux fois, 100,6 une fois
        uni, ub = [0.0] * 10, [0.0] * 10
        sessionvp.spread(k, 1000, 10, 0.1, uni, ub, path=False)
        self.assertAlmostEqual(max(uni) - min(uni), 0.0, places=9)                 # ancienne methode : uniforme
        flat = Candle(0, 100.0, 100.0, 100.0, 100.0, 2.0, 1.0)
        v2, b2 = [0.0] * 3, [0.0] * 3
        sessionvp.spread(flat, 999, 3, 0.1, v2, b2)
        self.assertEqual(v2, [0.0, 2.0, 0.0])                                      # sans amplitude : tout a la cloture

    def test_nodes_developing_and_shape(self):
        bars, t = [], 0
        for _ in range(60):
            bars.append(Candle(t, 100.2, 100.9, 100.1, 100.5, 10, 5)); t += M5
        for _ in range(5):
            bars.append(Candle(t, 101, 104, 101, 104, 2, 1)); t += M5
        for _ in range(60):
            bars.append(Candle(t, 104.3, 104.9, 104.1, 104.5, 10, 5)); t += M5
        r = sessionvp.build(bars, target_rows=60)
        self.assertEqual(len(r["hvn"]), 2)
        self.assertTrue(r["hvn"][0][1] <= 101.0 and r["hvn"][1][0] >= 104.0)
        self.assertEqual(len(r["lvn"]), 1)
        lo, hi, share = r["lvn"][0]
        self.assertTrue(lo <= 101.5 and hi >= 103.5 and share < 0.05)             # tout le creux entre les deux bosses
        self.assertEqual(r["method"], "trajet")
        dev = r["developing"]
        self.assertTrue(2 <= len(dev) <= 130)
        self.assertEqual(dev[-1][1], r["poc"])                                     # le dernier point = le POC final
        self.assertTrue(all(d[3] <= d[1] <= d[2] for d in dev))
        self.assertLess(dev[0][1], 102)                                            # au debut, le POC est dans la premiere bosse
        self.assertEqual(sessionvp.shape([0.0] * 3 + [1.0] * 2 + [9.0] * 5, 7), "P")
        self.assertEqual(sessionvp.shape([9.0] * 5 + [1.0] * 2 + [0.0] * 3, 2), "b")


def synth_bars(days=420, seed=5, step_ms=M15):
    rnd = random.Random(seed)
    b = fine.Bars(step_ms)
    p, t = 10_000.0, 1_600_000_000_000 // DAY * DAY
    for _ in range(days * DAY // step_ms):
        o = p
        p *= 1 + rnd.gauss(0, 0.002)
        h, l = max(o, p) * (1 + abs(rnd.gauss(0, 0.0007))), min(o, p) * (1 - abs(rnd.gauss(0, 0.0007)))
        b.append(t, o, h, l, p, 1.0 + rnd.random(), rnd.gauss(0, 0.3))
        t += step_ms
    return b.build_cum()


class TpoStudyTests(unittest.TestCase):
    def test_run_structure_and_summary(self):
        b = synth_bars()
        r = tpostudy.run(b, "D", int(b.t[0]), int(b.t[-1]))
        self.assertTrue(r["ready"])
        self.assertGreater(r["n"], 380)
        for key in ("singles", "extremes", "poc"):
            self.assertEqual(set(r[key]), {"all", "first", "second"})
            self.assertEqual(set(r[key]["all"]), {str(h) for h in r["horizons"]})
        e = r["extremes"]["all"]["1"]
        self.assertEqual(set(e["raw"]), {"poor", "excess", "other"})
        p = r["poc"]["all"]["5"]["all"]
        self.assertTrue(0 <= p["rate"] <= 1 and 0 <= p["control"] <= 1)
        self.assertIsNotNone(r["ib"])
        self.assertIn("rate", r["eighty"])
        self.assertTrue(0 < r["openSame"]["base"] < 1)
        rep = {"symbol": "TEST", "D": r}
        s = tpostudy.summary(rep)
        self.assertTrue({x["key"] for x in s} >= {"poor", "singles", "poc", "ib"})
        self.assertTrue(all(x["verdict"] in ("net", "contraire", "instable", "faible", "description", "hasard", "insuffisant") for x in s))
        c = tpostudy.compact(rep, "D")
        self.assertEqual(c["singles"]["h"], 5)
        self.assertIsNone(tpostudy.compact(rep, "4h"))
        json.dumps(rep)

    def test_paired_and_verdict(self):
        groups = [[(1, 0)] for _ in range(60)] + [[(0, 0)] for _ in range(40)]
        r = tpostudy.paired(groups)
        self.assertAlmostEqual(r["diff"], 0.6)
        self.assertGreater(r["t"], 5)
        self.assertEqual(tpostudy.paired([[(1, 1)]] * 5)["rate"], None)            # trop peu de cas
        self.assertEqual(tpostudy._verdict(3.0, 0.1, 0.2, 0.15), "net")
        self.assertEqual(tpostudy._verdict(3.0, -0.1, 0.2, 0.15), "instable")
        self.assertEqual(tpostudy._verdict(1.0, 0.1, 0.2, 0.15), "hasard")


class ZonePrecisionTests(unittest.TestCase):
    def test_weighted_key_core_and_traded_peak(self):
        self.assertEqual(zoneprec.wquantile([(100.0, 1.0)], 0.5), 100.0)
        self.assertAlmostEqual(zoneprec.wquantile([(100.0, 1.0), (102.0, 1.0)], 0.5), 101.0)
        self.assertAlmostEqual(zoneprec.wquantile([(100.0, 1.0), (102.0, 3.0)], 0.5), 101.5)  # tire vers le niveau le plus lourd
        bars = [Candle(i * M5, 101.0, 101.3, 100.9, 101.2, 50.0, 25.0) for i in range(50)] + [Candle(9 * DAY, 100.0, 103.0, 99.0, 102.0, 1.0, 0.5)]
        fp = zoneprec.FineProfile(bars, 101.0)
        z = {"lo": 100.0, "hi": 102.0}
        mem = [{"price": 100.0}, {"price": 101.0}, {"price": 101.2}, {"price": 102.0}]
        r = zoneprec.refine(z, mem, [1.0, 4.0, 4.0, 0.0], atr=2.0, fine=fp)
        self.assertTrue(101.0 <= r["key"] <= 101.2)
        self.assertTrue(z["lo"] <= r["core"][0] <= r["core"][1] <= z["hi"])
        self.assertLess(r["core"][1] - r["core"][0], z["hi"] - z["lo"])
        self.assertTrue(100.9 <= r["vpoc"] <= 101.3)                               # la ou le marche a vraiment echange
        self.assertEqual(r["widthAtr"], 1.0)
        self.assertIn(r["precision"], ("fine", "moyenne", "large"))
        two = zoneprec.refine({"lo": 1.0, "hi": 1.5}, [{"price": 1.0}, {"price": 1.5}], [1.0, 1.0], atr=1.0)
        self.assertEqual(two["core"], [1.0, 1.5])
        self.assertNotIn("vpoc", two)


class ServiceV19Tests(unittest.TestCase):
    def test_state_zones_tpo_study_and_reports(self):
        from config import Config
        from data import reports as reports_mod
        from server import App
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None)
        app.service.refresh_all()
        m = app.service.markets["BTCUSDT"]
        st = m.state("1h")
        self.assertIsNone(m.rank_error)
        zs = [z for z in st["zones"] if "key" in z]
        self.assertTrue(zs)
        for z in zs:
            self.assertTrue(z["lo"] - 1e-6 <= z["key"] <= z["hi"] + 1e-6)
            self.assertTrue(z["lo"] - 1e-6 <= z["core"][0] <= z["core"][1] <= z["hi"] + 1e-6)
        D = st["profiles"]["D"]
        self.assertTrue({"hvn", "lvn", "developing", "shape"} <= set(D))
        r = app.service.get_tpo("BTCUSDT", "D")
        self.assertTrue(r["ready"])
        self.assertIn("composite", r)
        self.assertIn("naked", r)
        self.assertTrue(all("ctx" in s for s in r["sessions"]))
        st_ = r["study"]                                                           # rapport livre : reports/tpo_BTC.json
        self.assertIsNotNone(st_)
        self.assertEqual(st_["symbol"], "BTC")
        self.assertTrue(0 < st_["poor"]["rate"] < 1)
        kinds = {x["kind"] for x in reports_mod.summaries(app.service.report_dirs)}
        self.assertIn("tpo", kinds)
        rep = reports_mod.load(app.service.report_dirs, "BTC", "tpo")
        self.assertEqual(set(rep) >= {"D", "4h", "1h", "summary", "period", "verdict"}, True)


if __name__ == "__main__":
    unittest.main()
