import random
import unittest

from engine import backtest as bt
from engine import cvd, fine, liqsweep

MIN = 60_000
HOUR = 3_600_000
T0 = 1_700_000_000_000 // HOUR * HOUR


def walk(n, seed=1, start=100.0, step=MIN, vol=0.0008):
    """Marche aleatoire : n bougies de `step` ms, volume et delta synthetiques."""
    rnd = random.Random(seed)
    b = fine.Bars(step)
    px = start
    for k in range(n):
        o = px
        c = o * (1 + rnd.gauss(0, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        v = 5 + rnd.random() * 10
        b.append(T0 + k * step, o, h, l, c, v, fine.bar_delta(o, h, l, c, v, o))
        px = c
    return b.build_cum()


class BarsTests(unittest.TestCase):
    def test_vwap_by_prefix_sums_matches_direct(self):
        b = walk(500)
        vw, sd = b.vwap(100, 300)
        num = den = 0.0
        for i in range(100, 300):
            tp = (b.h[i] + b.l[i] + b.c[i]) / 3
            num += tp * b.v[i]
            den += b.v[i]
        self.assertAlmostEqual(vw, num / den, places=6)
        self.assertGreater(sd, 0)
        self.assertEqual(b.vwap(5, 5), (None, None))

    def test_resample_keeps_totals_and_extremes(self):
        b = walk(600)
        h = fine.resample(b, HOUR)
        self.assertEqual(len(h), 10)
        self.assertAlmostEqual(h.volume(0, len(h)), b.volume(0, len(b)), places=6)
        self.assertAlmostEqual(h.delta(0, len(h)), b.delta(0, len(b)), places=6)
        self.assertEqual(h.h[0], max(b.h[:60]))
        self.assertEqual(h.l[3], min(b.l[180:240]))
        self.assertEqual(h.o[2], b.o[120])
        self.assertEqual(h.c[2], b.c[179])

    def test_idx_and_idx_at(self):
        b = walk(100)
        self.assertEqual(b.idx(T0 + 5 * MIN), 5)
        self.assertEqual(b.idx_at(T0 + 5 * MIN + 1), 5)
        self.assertEqual(b.idx_at(T0 - 1), -1)

    def test_save_load_roundtrip(self):
        import os
        import tempfile
        b = walk(50)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            b.save(p)
            c = fine.Bars.load(p).build_cum()
        self.assertEqual(len(c), 50)
        self.assertEqual(list(c.c), list(b.c))
        self.assertAlmostEqual(c.cd[-1], b.cd[-1], places=9)

    def test_delta_proxy_signs(self):
        self.assertGreater(fine.bar_delta(100, 101, 99, 101, 10, None), 0)        # cloture en haut
        self.assertLess(fine.bar_delta(100, 101, 99, 99, 10, None), 0)            # cloture en bas
        self.assertEqual(fine.bar_delta(100, 100, 100, 100, 10, 100), 0.0)
        self.assertEqual(fine.bar_delta(100, 100, 100, 100, 10, 99), 10)          # regle du tick

    def test_real_taker_volume_gives_real_delta(self):
        from engine.atr import Candle
        k = Candle(T0, 100, 101, 99, 100.5, 10, 7)                                # 7 achats agressifs sur 10
        b = fine.from_candles([k], HOUR)
        self.assertAlmostEqual(b.d[0], 4.0)


class CvdTests(unittest.TestCase):
    def test_imbalance_in_range(self):
        b = walk(300)
        self.assertTrue(-1 <= cvd.imbalance(b, 0, 300) <= 1)

    def test_flow_buyers_vs_sellers(self):
        b = fine.Bars(15 * MIN)
        for k in range(120):
            b.append(T0 + k * 15 * MIN, 100, 100.2, 99.9, 100.1, 10, 4)             # acheteurs dominants
        b.build_cum()
        s, notes = cvd.flow(cvd.analyse(b, 119))
        self.assertGreater(s, 0.3)
        self.assertTrue(notes)
        b2 = fine.Bars(15 * MIN)
        for k in range(120):
            b2.append(T0 + k * 15 * MIN, 100, 100.2, 99.9, 99.95, 10, -4)
        b2.build_cum()
        s2, _ = cvd.flow(cvd.analyse(b2, 119))
        self.assertLess(s2, -0.3)

    def test_bull_divergence(self):
        """Prix : plus bas plus bas ; CVD : plus bas plus haut."""
        b = fine.Bars(15 * MIN)
        lows = {10: 99.0, 30: 98.0}
        for k in range(60):
            lo = lows.get(k, 100.0)
            d = -8 if k == 10 else (-2 if k == 30 else (10 if k == 20 else 0))
            b.append(T0 + k * 15 * MIN, 100, 101, lo, 100.0, 10, d)
        b.build_cum()
        name, strength = cvd.divergence(b, 59, look=60)
        self.assertEqual(name, "bull")
        self.assertGreater(strength, 0)

    def test_absorption_needs_volume_and_opposite_delta(self):
        b = fine.Bars(15 * MIN)
        for k in range(80):
            b.append(T0 + k * 15 * MIN, 100, 100.3, 99.7, 100.0, 10, 0)
        for k in range(80, 84):                                                   # gros volume vendeur, prix qui tient
            b.append(T0 + k * 15 * MIN, 100, 100.3, 99.7, 100.05, 40, -20)
        b.build_cum()
        self.assertEqual(cvd.absorption(b, 83, k=4, base=48), "bull")


class LiquidityTests(unittest.TestCase):
    def _bars(self):
        b = fine.Bars(HOUR)
        px = [100, 101, 103, 105, 103, 102, 101, 100.5, 101, 102, 103, 104.9, 104.2, 103, 102]
        for k, p in enumerate(px * 3):
            b.append(T0 + k * HOUR, p, p + 0.4, p - 0.4, p + 0.1, 10, 1)
        return b.build_cum()

    def test_swing_points_are_confirmed_late(self):
        b = self._bars()
        hi, lo = liqsweep.swing_points(b, 2)
        self.assertTrue(hi and lo)
        for conf, tp, _ in hi + lo:
            self.assertGreater(conf, tp)                                         # connu seulement apres coup

    def test_equal_highs_merge_into_stronger_pool(self):
        pl = liqsweep.PriceLiquidity(self._bars(), 2)
        now = T0 + 40 * HOUR
        ext = [("PWH", 108.0, "high", 85, now), ("dH", 108.1, "high", 55, now)]
        pools = pl.pools(100.0, 1.0, now, ext)
        near = [p for p in pools if p["side"] == "short" and 107.5 < p["price"] < 108.5]
        self.assertEqual(len(near), 1)
        self.assertGreaterEqual(near[0]["score"], 85 + 12)
        self.assertIn("égaux", near[0]["src"])

    def test_sweep_and_reclaim(self):
        b = fine.Bars(15 * MIN)
        for k in range(20):
            b.append(T0 + k * 15 * MIN, 100, 100.5, 99.6, 100.1, 10, 0)
        b.append(T0 + 20 * 15 * MIN, 100, 100.1, 98.9, 99.8, 30, -5)           # meche sous 99.5, cloture dessous
        b.append(T0 + 21 * 15 * MIN, 99.8, 100.6, 99.7, 100.4, 25, 8)          # reprise
        b.build_cum()
        pools = [{"side": "long", "price": 99.5, "lo": 99.25, "hi": 99.5, "score": 80, "src": "PDL"}]
        ev = liqsweep.detect_sweeps(pools, b, 21, T0 + 22 * 15 * MIN, hours=8)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["side"], "long")
        self.assertAlmostEqual(ev[0]["to"], 98.9)
        self.assertAlmostEqual(ev[0]["frac"], 0.4)
        # pas de reprise : aucun evenement
        b2 = fine.Bars(15 * MIN)
        for k in range(20):
            b2.append(T0 + k * 15 * MIN, 100, 100.5, 99.6, 100.1, 10, 0)
        b2.append(T0 + 20 * 15 * MIN, 100, 100.1, 98.9, 99.0, 30, -5)
        b2.build_cum()
        self.assertEqual(liqsweep.detect_sweeps(pools, b2, 20, T0 + 21 * 15 * MIN), [])


class SimulateTests(unittest.TestCase):
    def _flat(self, path):
        """Bougies 1 minute qui suivent `path` (liste de (haut, bas, cloture))."""
        b = fine.Bars(MIN)
        px = 100.0
        for k, (h, l, c) in enumerate(path):
            b.append(T0 + k * MIN, px, h, l, c, 1, 0)
            px = c
        return b.build_cum()

    def test_long_limit_fill_tp1_then_tp2(self):
        path = [(100.2, 99.8, 100.0)] * 3 + [(100.1, 98.9, 99.2)] + [(101.5, 99.3, 101.2)] + [(103.2, 101.0, 103.1)]
        b = self._flat(path)
        s = bt.simulate(b, T0, "long", "limite", 99.0, 98.0, 101.0, 103.0, valid_h=1, hold_h=1)
        self.assertTrue(s["filled"])
        self.assertEqual(s["result"], "tp2")
        self.assertAlmostEqual(s["r_gross"], 0.5 * 2.0 + 0.5 * 4.0, places=6)    # moitie a +2 R, moitie a +4 R

    def test_stop_first_when_same_minute(self):
        path = [(100.2, 99.8, 100.0)] + [(103.0, 97.5, 100.0)] * 2
        b = self._flat(path)
        s = bt.simulate(b, T0, "long", "marché", 100.0, 98.0, 102.0, None, hold_h=1)
        self.assertEqual(s["result"], "stop")
        self.assertAlmostEqual(s["r_gross"], -1.0, places=6)

    def test_stop_moves_to_entry_after_tp1(self):
        path = [(100.2, 99.8, 100.0)] + [(102.5, 100.1, 102.0)] + [(102.1, 99.9, 100.0)] + [(100.5, 99.9, 100.0)] * 3
        b = self._flat(path)
        s = bt.simulate(b, T0, "long", "marché", 100.0, 98.0, 102.0, 106.0, hold_h=1)
        self.assertEqual(s["result"], "tp1_be")
        self.assertAlmostEqual(s["r_gross"], 0.5, places=6)                      # moitie a +1 R, moitie a 0

    def test_short_symmetry(self):
        path = [(100.2, 99.8, 100.0)] + [(99.9, 97.5, 98.0)] + [(98.5, 95.9, 96.0)]
        b = self._flat(path)
        s = bt.simulate(b, T0, "short", "marché", 100.0, 102.0, 98.0, 96.0, hold_h=1)
        self.assertEqual(s["result"], "tp2")
        self.assertAlmostEqual(s["r_gross"], 0.5 * 1.0 + 0.5 * 2.0, places=6)

    def test_missed_and_nofill(self):
        path = [(100.2, 99.8, 100.0)] * 2 + [(104.0, 100.0, 103.5)]
        b = self._flat(path)
        s = bt.simulate(b, T0, "long", "limite", 99.0, 98.0, 103.0, None, valid_h=1)
        self.assertEqual(s["result"], "missed")                                   # l'objectif est touche avant l'execution
        b2 = self._flat([(100.2, 99.8, 100.0)] * 200)
        self.assertEqual(bt.simulate(b2, T0, "long", "limite", 90.0, 89.0, 105.0, None, valid_h=1)["result"], "nofill")

    def test_costs_in_r(self):
        sim = {"fill_px": 100.0, "risk": 2.0, "legs": [("maker", 0.5), ("maker", 0.5)], "entry_kind": "maker", "hours": 0.0, "tp1": True, "r_gross": 3.0}
        c = {"maker": 0.0002, "taker": 0.0005, "slip": 0.0002, "funding8h": 0.0001}
        # notionnel = 50 x le risque : entree + sorties = 2 x 0,02 % x 50 = 0,02 R
        self.assertAlmostEqual(bt.net_r(sim, c), 3.0 - 2 * 0.0002 * 50, places=9)


class MetricsTests(unittest.TestCase):
    def _trades(self, rs):
        return [{"t": bt.ms(2023) + k * 86_400_000, "exit_t": bt.ms(2023) + k * 86_400_000 + 3_600_000, "r": r, "mae": max(0.0, -r), "mfe": max(0.0, r),
                 "stop_pct": 0.01, "hours": 1.0} for k, r in enumerate(rs)]

    def test_metrics_basic(self):
        m = bt.metrics(self._trades([2, -1, 2, -1, -1, 2]), bt.ms(2023), bt.ms(2023, 2))
        self.assertEqual(m["n"], 6)
        self.assertAlmostEqual(m["winRate"], 0.5)
        self.assertAlmostEqual(m["expR"], 0.5)
        self.assertAlmostEqual(m["pf"], 2.0)
        self.assertGreater(m["ret"], 0)
        self.assertGreater(m["maxDD"], 0)

    def test_empty(self):
        m = bt.metrics([], bt.ms(2023), bt.ms(2024))
        self.assertEqual(m["n"], 0)

    def test_select_respects_quota_and_single_position(self):
        day = 86_400_000
        base = bt.ms(2023, 1, 2)                                                  # un lundi
        cands = []
        for k in range(8):
            cands.append({"t": base + k * 4 * 3_600_000, "side": "long", "kind": "rebond", "etype": "limite", "key": f"k{k}", "score": 70, "S": 9,
                          "sim": {"result": "tp2", "filled": True, "fill_t": base + k * 4 * 3_600_000, "exit_t": base + k * 4 * 3_600_000 + 1_000, "fill_px": 100.0,
                                  "risk": 2.0, "r_gross": 2.0, "entry_kind": "maker", "legs": [("maker", 1.0)], "hours": 0.0, "tp1": True, "mae": 0.1, "mfe": 2.0}})
        tr = bt.select(cands, lambda r: True, bt.DEFAULT_COSTS, max_week=5)
        self.assertEqual(len(tr), 5)
        # une meme zone ne revient pas avant 48 h
        for c in cands:
            c["key"] = "same"
        tr2 = bt.select(cands, lambda r: True, bt.DEFAULT_COSTS, max_week=5)
        self.assertEqual(len(tr2), 1)

    def test_percentile_of(self):
        self.assertAlmostEqual(bt.percentile_of([0.1, 0.2, 0.3, 0.4], 0.25), 0.5)


class GenerateTests(unittest.TestCase):
    def test_generate_runs_without_future_leak_on_random_walk(self):
        """Marche aleatoire sur ~12 jours : le generateur tourne, ne produit que des candidates datees dans la fenetre
        et dont le stop est du bon cote."""
        b1 = walk(12 * 1440, seed=5, start=30000.0, vol=0.0006)
        ds = bt.Dataset.from_1m(b1)
        a, b = T0 + 8 * 86_400_000, T0 + 12 * 86_400_000 - HOUR
        c = bt.generate(ds, a, b)
        for r in c:
            self.assertTrue(a <= r["t"] < b)
            sg = 1 if r["side"] == "long" else -1
            self.assertGreater((r["entry"] - r["stop"]) * sg, 0)
            self.assertGreater((r["tp1"] - r["entry"]) * sg, 0)
        bt.attach_outcomes(c, ds)
        self.assertTrue(all("sim" in r for r in c))


if __name__ == "__main__":
    unittest.main()
