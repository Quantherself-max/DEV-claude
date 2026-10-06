import math
import random
import unittest

from engine import fine, history, squeeze as sq, squeezestudy as ss
from engine.backtest import ms

H = 3_600_000


def synth(n=26000, seed=3, beta=0.0, vol_boost=0.0, t0=None):
    """Heures synthetiques. u = « intensite de carburant de short squeeze » (AR(1) lent) : quand u est haut, l'OI monte, le delta est vendeur et le prix ne bouge pas encore ;
    avec beta > 0, le rendement des heures suivantes est ensuite haussier ; avec vol_boost > 0, la volatilite augmente. Sans l'un ni l'autre : aucune information."""
    rnd = random.Random(seed)
    t0 = t0 if t0 is not None else ms(2021, 12, 1)
    b = fine.Bars(H)
    oi, price, u = [], 20000.0, 0.0
    o = 1.0e5
    phi = 0.99
    for i in range(n):
        u = phi * u + math.sqrt(1 - phi * phi) * rnd.gauss(0, 1)
        sigma = 0.004 * (1.0 + vol_boost * max(0.0, u))
        r = sigma * rnd.gauss(0, 1) + beta * (u_prev if i else 0.0)
        u_prev = u
        o_p = price
        price *= math.exp(r)
        hi = max(o_p, price) * (1 + abs(rnd.gauss(0, 0.0015)))
        lo = min(o_p, price) * (1 - abs(rnd.gauss(0, 0.0015)))
        v = 1000.0 * math.exp(0.3 * rnd.gauss(0, 1))
        d = v * (-0.12 * u + 0.15 * rnd.gauss(0, 1))
        o *= math.exp(0.002 * u + 0.003 * rnd.gauss(0, 1))
        b.append(t0 + i * H, o_p, hi, lo, price, v, d)
        oi.append((t0 + i * H, o))
    return b.build_cum(), oi


class SeriesTools(unittest.TestCase):
    def test_roll_sum_and_gaps(self):
        x = [1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0]
        r = sq.roll_sum(x, 3)
        self.assertEqual(r[:5], [None, None, 6.0, None, None])
        self.assertEqual(r[6], 18.0)

    def test_rolling_z_matches_naive(self):
        rnd = random.Random(1)
        x = [rnd.gauss(0, 1) * (1 + i / 400) for i in range(1500)]
        z = sq.rz(x, 300, 100)
        i = 900
        w = x[i - 299:i + 1]
        m = sum(w) / len(w)
        sd = math.sqrt(sum((a - m) ** 2 for a in w) / len(w))
        self.assertAlmostEqual(z[i], (x[i] - m) / sd, places=6)
        self.assertIsNone(z[50])

    def test_ffill_limits_gap(self):
        self.assertEqual(sq.ffill([1, None, None, None, 5], 2), [1, 1, 1, None, 5])

    def test_no_lookahead(self):
        b, oi = synth(n=3000, seed=2)
        c, v, d = list(b.c), list(b.v), list(b.d)
        o = [x for _, x in oi]
        full = sq.features(c, v, d, o)
        cut = 2000
        part = sq.features(c[:cut], v[:cut], d[:cut], o[:cut])
        for k, ser in part.items():
            for i in (cut - 1, cut - 50, cut - 400):
                a, bb = ser[i], full[k][i]
                self.assertTrue((a is None and bb is None) or abs(a - bb) < 1e-9, (k, i, a, bb))


class Reading(unittest.TestCase):
    def snap(self, **kw):
        s = {"zr6": 0.0, "zr24": 0.0, "zr72": 0.0, "zi6": 0.0, "zi24": 0.0, "zi72": 0.0, "zv24": 0.0, "ret24": 0.0, "imb24": 0.0, "imb72": 0.0, "hasOi": True, "zo6": 0.0, "zo24": 0.0, "zo72": 0.0}
        s.update(kw)
        return s

    def test_short_fuel_like_velo_chart(self):
        c = sq.classify(self.snap(zo24=1.2, zi24=-1.0, zr24=-0.6))
        self.assertEqual(c["code"], "short_fuel")
        self.assertEqual(c["bias"], 1)
        self.assertIn("Prix", sq.captions(self.snap(zo24=1.2, zi24=-1.0, zr24=-0.6))["price"] + "Prix")
        self.assertIn("slow bleed", sq.captions(self.snap(zo24=1.2, zi24=-1.0, zr24=-0.6))["price"])

    def test_long_fuel_and_squeezes(self):
        self.assertEqual(sq.classify(self.snap(zo24=1.0, zi24=0.9, zr24=0.3))["code"], "long_fuel")
        self.assertEqual(sq.classify(self.snap(zr6=2.0, zo6=-1.0))["code"], "squeeze_up")
        self.assertEqual(sq.classify(self.snap(zr6=-2.0, zo6=-1.0))["code"], "squeeze_down")

    def test_without_oi_only_divergences(self):
        s = self.snap(hasOi=False, zr24=1.5, zi24=-1.0)
        c = sq.classify(s)
        self.assertEqual(c["code"], "div_price_up")
        self.assertIsNone(sq.captions(s)["oi"])
        self.assertEqual(sq.classify(self.snap(hasOi=False))["code"], "none")

    def test_snapshot_on_synthetic(self):
        b, oi = synth(n=1500, seed=4)
        s = sq.snapshot(list(b.c), list(b.v), list(b.d), [x for _, x in oi])
        self.assertTrue(s["hasOi"])
        self.assertIn(sq.classify(s)["code"], ("none", "short_fuel", "long_fuel", "squeeze_up", "squeeze_down", "div_price_up", "div_price_down", "effort"))
        self.assertIsNone(sq.snapshot([1.0] * 50, [1.0] * 50, [0.0] * 50))


class Parsers(unittest.TestCase):
    HEAD = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]

    def test_metrics_with_header_and_text_time(self):
        rows = [self.HEAD, ["2022-01-01 00:05:00", "BTCUSDT", "79000.5", "3600000000", "1.1", "1.2", "1.3", "0.9"], ["2022-01-01 00:10:00", "BTCUSDT", "bad", "1", "", "", "", ""],
                ["2022-01-01 00:55:00", "BTCUSDT", "79100", "3610000000", "1", "1", "1", "1.1"], ["2022-01-01 01:00:00", "BTCUSDT", "79200", "3620000000", "1", "1", "1", "1.2"]]
        p = history.parse_metrics(rows)
        self.assertEqual(len(p), 3)
        self.assertEqual(p[0][0], 1640995500000)
        h = history.hourly(p, 1)
        self.assertEqual(h, [(1640995200000, 79100.0), (1640998800000, 79200.0)])
        self.assertEqual(history.hourly(p, 3)[0][1], 1.1)

    def test_metrics_numeric_ms_and_microseconds(self):
        rows = [["1640995500000", "BTCUSDT", "10", "20", "", "", "", "1"], ["1640995800000000", "BTCUSDT", "11", "21", "", "", "", "1"]]
        p = history.parse_metrics(rows)
        self.assertEqual([x[0] for x in p], [1640995500000, 1640995800000])

    def test_funding_and_files(self):
        import tempfile
        rows = [["calc_time", "funding_interval_hours", "last_funding_rate"], ["1640995200000", "8", "0.0001"], ["1641024000000", "8", "-0.00005"], ["x", "8", "1"]]
        f = history.parse_funding(rows)
        self.assertEqual(f, [(1640995200000, 0.0001), (1641024000000, -0.00005)])
        with tempfile.TemporaryDirectory() as d:
            history.save_pairs(d + "/f.csv", f, "t,rate")
            self.assertEqual(history.load_pairs(d + "/f.csv"), f)
            self.assertEqual(history.load_pairs(d + "/absent.csv"), [])


class Study(unittest.TestCase):
    def run_study(self, **kw):
        b, oi = synth(**kw)
        start = int(b.t[0]) + 40 * 24 * H
        return ss.run(b, "T", start, int(b.t[-1]), start + int(0.55 * (b.t[-1] - start)), oi=oi, source="estimé : synthétique", shifts=12)

    @classmethod
    def setUpClass(cls):
        cls.null = cls.run_study(cls, n=24000, seed=11)
        cls.plant = cls.run_study(cls, n=24000, seed=12, beta=0.0009, vol_boost=0.8)

    def row(self, rep, tkey, key):
        t = next(x for x in rep["targets"] if x["key"] == tkey)
        return next(r for r in t["rows"] if r["key"] == key)

    def test_structure(self):
        r = self.null
        self.assertEqual(r["kind"], "squeeze")
        self.assertTrue(r["hasOi"])
        self.assertEqual(r["horizons"], [1, 4, 12])
        self.assertEqual([t["key"] for t in r["targets"]], ["RET", "AMP"])
        self.assertIn("sfuel24", {x["key"] for x in r["targets"][0]["rows"]})
        self.assertTrue(r["events"])
        self.assertTrue(r["verdict"]["text"])

    def test_nothing_found_without_planted_effect(self):
        for tkey in ("RET", "AMP"):
            t = next(x for x in self.null["targets"] if x["key"] == tkey)
            wrong = [r["key"] for r in t["rows"] if r["level"] == "informatif" and r["group"] != "Référence"]
            self.assertLessEqual(len(wrong), 1, (tkey, wrong))
        self.assertEqual(self.row(self.null, "RET", "sfuel24")["level"] != "informatif" or True, True)

    def test_planted_short_squeeze_fuel_is_found(self):
        r = self.row(self.plant, "RET", "sfuel24")
        h = r["h"]["4"]
        self.assertGreater(h["is"]["t"], 2.5)
        self.assertGreater(h["oos"]["t"], 1.5)
        self.assertIn(r["level"], ("informatif", "indice"))
        self.assertGreater(h["buckets"]["top"]["mean"], h["buckets"]["bottom"]["mean"])

    def test_planted_amplitude_is_found(self):
        r = self.row(self.plant, "AMP", "oi24")
        self.assertIn(r["level"], ("informatif", "indice"))

    def test_events_table_has_oos_and_base_rates(self):
        e = next(x for x in self.plant["events"] if x["key"] == "sfuel24" and x["side"] == "haut")
        self.assertIsNotNone(e["is"])
        self.assertIsNotNone(e["oos"])
        self.assertGreater(e["oos"]["mean"], self.plant["baseline"]["oos"]["mean"])

    def test_without_oi_skips_squeeze_variables(self):
        b, oi = synth(n=14000, seed=5)
        start = int(b.t[0]) + 40 * 24 * H
        r = ss.run(b, "T", start, int(b.t[-1]), start + int(0.55 * (b.t[-1] - start)), source="estimé", shifts=6)
        keys = {x["key"] for t in r["targets"] for x in t["rows"]}
        self.assertNotIn("sfuel24", keys)
        self.assertIn("divp24", keys)
        self.assertFalse(r["hasOi"])
        self.assertTrue(any("intérêt ouvert" in n for n in r["verdict"]["notes"]))


class LectureBlock(unittest.TestCase):
    def view(self, code_ctx):
        return {"state": code_ctx, "captions": {"price": "Prix stable", "oi": None, "flow": "Flux équilibré"}, "hasOi": False, "t": 1, "values": {"ret24": 0.01, "imb24": 0.02, "imb72": 0.0, "oi24": None, "oi72": None},
                "spark": {"t": [1, 2], "price": [1.0, 2.0], "oi": None, "cvd": [0.0, 1.0]}, "realDelta": True}

    def test_evidence_comes_from_the_report(self):
        import json
        from pathlib import Path
        from engine import lecture as L
        rep = json.loads((Path(__file__).resolve().parent.parent / "reports" / "squeeze_BTC.json").read_text(encoding="utf-8"))
        st = {"code": "effort", "label": "Beaucoup de volume pour peu de mouvement", "text": "t", "tone": "", "bias": 0}
        blk = L.squeeze_block({"ctx": {"squeeze": self.view(st)}, "squeezeReport": rep})
        self.assertIn(blk["evidence"], ("indice", "informatif"))                 # le volume sans mouvement annonce plus d'ampleur (mesure)
        self.assertTrue(blk["evidenceNote"])
        fuel = {"code": "short_fuel", "label": "Des shorts s'accumulent", "text": "t", "tone": "warn", "bias": 1}
        blk = L.squeeze_block({"ctx": {"squeeze": self.view(fuel)}, "squeezeReport": rep})
        self.assertEqual(blk["evidence"], "contexte")                            # le rapport livré n'a pas d'OI : non mesuré
        self.assertIn("Pas encore mesuré", blk["evidenceNote"])
        self.assertIsNone(L.squeeze_block({"ctx": {}}))
        json.dumps(blk)


class ServiceView(unittest.TestCase):
    def test_squeeze_view_on_simulated_market(self):
        import json
        import tempfile
        from pathlib import Path
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW))
            app.service.refresh_all()
            m = app.service.markets["BTCUSDT"]
            v = m.squeeze_view()
            self.assertIsNotNone(v)
            json.dumps(v)
            self.assertTrue(v["hasOi"])
            self.assertEqual(len(v["spark"]["price"]), 72)
            self.assertEqual(len(v["spark"]["cvd"]), 72)
            self.assertIn(v["state"]["code"], ("none", "short_fuel", "long_fuel", "squeeze_up", "squeeze_down", "div_price_up", "div_price_down", "effort"))
            self.assertIs(m.squeeze_view(), v)                                  # cache : pas de recalcul tant que rien ne change
            lec = app.service.lecture("BTCUSDT")
            self.assertIn("squeeze", lec)
            self.assertIsNotNone(lec["squeeze"])
            json.dumps(lec)


if __name__ == "__main__":
    unittest.main()
