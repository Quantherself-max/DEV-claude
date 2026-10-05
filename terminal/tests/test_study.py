import random
import unittest

from engine import backtest as bt
from engine import fine, study, trend

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000


def walk_ds(days, seed=3, start=100.0, vol=0.0007, drift=0.0, t0=None):
    t0 = t0 if t0 is not None else bt.ms(2023, 1, 2)
    rnd = random.Random(seed)
    b = fine.Bars(MIN)
    px = start
    for k in range(days * 1440):
        o = px
        c = o * (1 + rnd.gauss(drift, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        v = 5 + rnd.random() * 10
        b.append(t0 + k * MIN, o, h, l, c, v, fine.bar_delta(o, h, l, c, v, o))
        px = c
    return bt.Dataset.from_1m(b.build_cum())


class TrendTests(unittest.TestCase):
    def test_not_ready_without_enough_history(self):
        self.assertFalse(trend.state([100.0] * 100)["ready"])

    def test_regime_signs(self):
        up = [100.0 + 0.01 * k for k in range(24 * 260)]
        dn = [200.0 - 0.01 * k for k in range(24 * 260)]
        self.assertEqual(trend.state(up)["regime"], 1)
        self.assertEqual(trend.state(dn)["regime"], -1)
        flat_then_dip = [100.0] * (24 * 250) + [99.0] * 2 + [101.0]
        self.assertEqual(trend.state(flat_then_dip)["regime"], 1)
        mixed = [100.0 + 0.01 * k for k in range(24 * 250)] + [100.0 + 0.01 * 24 * 250 - 0.5 * k for k in range(1, 400)]
        self.assertIn(trend.state(mixed)["regime"], (-1, 0))

    def test_alignment(self):
        self.assertEqual(trend.alignment(1, "long"), 1)
        self.assertEqual(trend.alignment(1, "short"), -1)
        self.assertEqual(trend.alignment(-1, "short"), 1)
        self.assertEqual(trend.alignment(0, "long"), 0)
        self.assertIsNone(trend.alignment(None, "long"))

    def test_matches_backtest_regime(self):
        """Meme definition en direct et dans le backtest."""
        ds = walk_ds(260, seed=7, drift=0.00003)
        ma = bt.regime_series(ds.b1h)
        closes = list(ds.b1h.c)
        for j in (24 * 210, 24 * 230, 24 * 255):
            T = ds.b1h.t[j] + HOUR                       # bougie j fermee a cet instant
            self.assertEqual(bt.regime_at(ds, ma, T), trend.state(closes[:j + 1])["regime"])


class StudyTests(unittest.TestCase):
    def test_quarters_cover_range(self):
        q = study.quarters(bt.ms(2023, 2, 10), bt.ms(2024, 2, 1))
        self.assertEqual(q[0][0], bt.ms(2023, 2, 10))
        self.assertEqual(q[-1][1], bt.ms(2024, 2, 1))
        for (a, b), (c, d) in zip(q, q[1:]):
            self.assertEqual(b, c)

    def test_event_study_detects_injected_effect_and_not_noise(self):
        """Effet injecte : apres un ecart de -2 sigma au VWAP du jour, le prix remonte nettement. Le banc d'essai doit le voir."""
        P = study.Panel()
        rnd = random.Random(1)
        T0 = bt.ms(2022, 1, 1)
        for k in range(30000):
            t = T0 + k * 900_000
            z = rnd.gauss(0, 1.2)
            f24 = rnd.gauss(0, 0.02) + (0.01 if z <= -2 else 0.0)
            row = {"t": t, "px": 100.0, "atr": 0.5, "zD": z, "zW": rnd.gauss(0, 1), "zM": rnd.gauss(0, 1), "zY": rnd.gauss(0, 1), "hrD": 12.0, "hrW": 100.0,
                   "hrM": 200.0, "dD": rnd.gauss(0, 2), "dW": rnd.gauss(0, 2), "dM": rnd.gauss(0, 2), "dY": rnd.gauss(0, 2), "swL": 0, "swS": 0, "imb1": 0, "imb4": 0,
                   "imb24": 0, "div": 0, "absorb": 0, "ret30": 0.0, "f4": rnd.gauss(0, 0.01), "f24": f24, "fb1": rnd.choice((-1, 1))}
            P.add(row)
        rows = study.event_study(P, T0 + 15000 * 900_000)
        hit = next(r for r in rows if r["name"] == "VWAP jour : −2 σ → long")
        self.assertGreater(hit["all24"]["t"], 4.0)
        self.assertGreater(hit["is24"]["ex"], 0.005)
        self.assertGreater(hit["oos24"]["ex"], 0.005)
        noise = next(r for r in rows if r["name"] == "VWAP semaine : −2 σ → long")
        self.assertLess(abs(noise["all24"]["t"]), 3.5)

    def test_run_small_random_walk_returns_full_report(self):
        ds = walk_ds(40, seed=11)
        a, b = bt.ms(2023, 1, 2) + 8 * DAY, bt.ms(2023, 1, 2) + 38 * DAY
        rep = study.run(ds, "TEST", a, b, a + 15 * DAY, folder=None, workers=1, control_runs=5, source_note="synthetique")
        for k in ("verdict", "terminal", "variants", "events", "touch", "regime", "costSens", "period", "costs"):
            self.assertIn(k, rep)
        self.assertEqual(len(rep["variants"]), len(study.variants()))
        self.assertFalse(rep["verdict"]["edge"])                      # marche aleatoire : aucun avantage a trouver
        import json
        json.dumps(rep)                                              # serialisable


class BacktestRegimeControlTests(unittest.TestCase):
    def test_swing_follows_trend_and_exits_on_break(self):
        ds = walk_ds(260, seed=5, drift=0.00004)
        ma = bt.regime_series(ds.b1h)
        t0 = ds.b1h.t[24 * 220]
        price = ds.b5.c[ds.b5.idx_at(t0)]
        s = bt.simulate_swing(ds, ma, t0, "long", "marché", price, price * 0.9, None, hold_days=15)
        self.assertTrue(s["filled"])
        self.assertIn(s["result"], ("regime", "stop", "timeout"))
        self.assertGreater(s["hours"], 0)


if __name__ == "__main__":
    unittest.main()
