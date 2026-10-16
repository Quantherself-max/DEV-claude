import random
import unittest

from engine import backtest as bt
from engine import fine, stratstudy, swingavwap as sw, swingstudy

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = bt.ms(2023, 1, 2)


def hourly(path, vol=10.0, t0=T0):
    """Bougies 1 h a partir d'une liste de (haut, bas, cloture) ; ouverture = cloture precedente."""
    b = fine.Bars(HOUR)
    px = path[0][2]
    for k, (h, l, c) in enumerate(path):
        o = px
        b.append(t0 + k * HOUR, o, max(h, o, c), min(l, o, c), c, vol, 0.0)
        px = c
    return b.build_cum()


def leg(start, end, n):
    """n bougies qui vont lineairement de start a end (haut/bas = +-0,1 %)."""
    out = []
    for k in range(1, n + 1):
        c = start + (end - start) * k / n
        out.append((c * 1.001, c * 0.999, c))
    return out


class ZigzagTests(unittest.TestCase):
    def test_pivots_are_confirmed_only_after_the_reversal(self):
        path = leg(100, 120, 20) + leg(120, 110, 10) + leg(110, 100, 10) + leg(100, 112, 12)
        b = hourly(path)
        piv = sw.zigzag(b, 0.05)
        kinds = [p["kind"] for p in piv]
        self.assertEqual(kinds, ["L", "H", "L"])                               # creux de depart, sommet a 120, creux a 100
        h = piv[1]
        self.assertAlmostEqual(h["px"], 120 * 1.001, places=6)
        self.assertGreater(h["ic"], h["i"])                                    # connu seulement apres la baisse
        self.assertLessEqual(b.l[h["ic"]], h["px"] * 0.95)                    # confirmation = baisse d'au moins 5 %
        for p in piv:
            self.assertGreater(p["ic"], p["i"])

    def test_small_moves_make_no_pivot(self):
        path = leg(100, 103, 10) + leg(103, 100, 10) + leg(100, 104, 10) + leg(104, 101, 10)
        self.assertEqual(sw.zigzag(hourly(path), 0.05), [])

    def test_no_lookahead_prefix_gives_same_confirmed_pivots(self):
        rnd = random.Random(4)
        px, path = 100.0, []
        for _ in range(900):
            px *= 1 + rnd.gauss(0, 0.012)
            path.append((px * 1.002, px * 0.998, px))
        full = sw.zigzag(hourly(path), 0.05)
        for cut in (300, 500, 700):
            part = sw.zigzag(hourly(path[:cut]), 0.05)
            known = [p for p in full if p["ic"] < cut]
            self.assertEqual([(p["kind"], p["i"], p["ic"]) for p in part], [(p["kind"], p["i"], p["ic"]) for p in known])

    def test_alternation(self):
        rnd = random.Random(8)
        px, path = 100.0, []
        for _ in range(1500):
            px *= 1 + rnd.gauss(0, 0.015)
            path.append((px * 1.002, px * 0.998, px))
        piv = sw.zigzag(hourly(path), 0.05)
        self.assertGreater(len(piv), 6)
        for a, b2 in zip(piv, piv[1:]):
            self.assertNotEqual(a["kind"], b2["kind"])


class EventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rnd = random.Random(21)
        b = fine.Bars(MIN)
        px = 100.0
        for k in range(150 * 1440):
            o = px
            drift = 0.00002 * (1 if (k // (6 * 1440)) % 2 == 0 else -1)
            c = o * (1 + drift + rnd.gauss(0, 0.0010))
            b.append(T0 + k * MIN, o, max(o, c) * 1.0004, min(o, c) * 0.9996, c, 5 + rnd.random() * 10, 0.0)
            px = c
        cls.ds = bt.Dataset.from_1m(b.build_cum())
        cls.ev = sw.build_events(cls.ds, T0 + 20 * DAY, T0 + 145 * DAY, pct=0.05)

    def test_events_are_consistent(self):
        ev = self.ev
        self.assertGreater(len(ev), 100)
        b = self.ds.b1h
        for e in ev:
            self.assertEqual(e["t"] % HOUR, 0)
            self.assertTrue(e["l"] <= e["V"] <= e["h"])
            self.assertEqual(e["dir"], 1 if e["c"] > e["V"] else -1)
            self.assertIn(e["anchor"], ("H", "L"))
            self.assertIn(e["sideBefore"], (-1, 1))
            self.assertGreater(e["touchNo"], 0)
            self.assertLessEqual(e["ageD"], sw.MAX_AGE_DAYS + 0.01)
            self.assertGreater(e["atr"], 0)
            self.assertIn(sw.reaction(e), ("tient", "traverse"))
            if e["depth"] is not None:
                self.assertGreaterEqual(e["depth"], 0.05 - 1e-9)
        self.assertEqual([e["t"] for e in ev], sorted(e["t"] for e in ev))

    def test_anchor_value_matches_a_direct_vwap(self):
        b = self.ds.b1h
        e = self.ev[len(self.ev) // 2]
        ia = b.idx(e["anchorT"])
        j = b.idx(e["t"] - HOUR)
        vw, _ = b.vwap(ia, j + 1)
        self.assertAlmostEqual(e["V"], vw, places=6)

    def test_event_uses_only_closed_data_and_comes_after_confirmation(self):
        b = self.ds.b1h
        piv = {(b.t[p["i"]], p["kind"]): p for p in sw.zigzag(b, 0.05)}
        for e in self.ev[:300]:
            p = piv[(e["anchorT"], e["anchor"])]
            self.assertGreater(e["t"], b.t[p["ic"]] + HOUR - 1)               # apres la cloture de la bougie de confirmation

    def test_first_touch_number_is_one_per_anchor(self):
        first = {}
        for e in self.ev:
            first.setdefault((e["anchorT"], e["anchor"]), e["touchNo"])
        self.assertTrue(all(v >= 1 for v in first.values()))

    def test_rules_ignore_the_side_taken(self):
        for e in self.ev[:150]:
            f = {**e, "dir": -e["dir"], "fade": True}
            for name, _, rule in swingstudy.rules():
                self.assertEqual(bool(rule(e)), bool(rule(f)), name)

    def test_reaction_table_and_full_study_run(self):
        a, b, split = T0 + 20 * DAY, T0 + 145 * DAY, T0 + 100 * DAY
        rows = swingstudy.reaction_table(self.ds, self.ev, split, with_prob=True)
        self.assertEqual(len(rows), 12)
        self.assertTrue(any(r.get("f24") for r in rows))
        for r in rows:
            if r.get("p"):
                self.assertTrue(0.0 <= r["p"]["p"] <= 1.0)
        eras = [("a", a, split), ("b", split, b)]
        rep = swingstudy.run(self.ds, {0.05: self.ev}, "TEST", a, b, split, eras, control_runs=3, min_exit=3, min_rule=3)
        import json
        json.dumps(rep)
        self.assertEqual(rep["kind"], "avwap-swing")
        self.assertEqual(len(rep["exits"]), len(swingstudy.CONFIGS))
        self.assertEqual(len(rep["variants"]), len(swingstudy.rules()) * 2 * len(rep["chosenExits"]))
        self.assertIn("Réaction du prix", rep["verdict"]["notes"][0])
        self.assertIn(rep["verdict"]["level"], ("edge", "weak", "none"))
        self.assertNotIn("hedge", rep)
        self.assertEqual(rep["swing"]["sizes"][0]["pct"], 0.05)
        self.assertEqual(stratstudy.cfg_label("atr3|1R|H24"), "stop à 3 ATR · objectif 1 R · 24 h")


if __name__ == "__main__":
    unittest.main()
