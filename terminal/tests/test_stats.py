import math, random, unittest

from engine.atr import Candle
from engine.stats import (atr_series, outcome_at, reach_prob, reach_table, reaction_stats, round_step,
                          sweep_outcomes, wilson)

H = 3_600_000
T0 = 1_704_067_200_000      # 2024-01-01


def walk(n, seed, px=85000.0, sd=0.004, reflect=None, tb_bias=0.0):
    """Marche aleatoire sans memoire (bougies 1h). reflect=(bas, haut) : le prix rebondit systematiquement
    sur ces deux niveaux (effet plante, pour verifier que les statistiques le detectent)."""
    r = random.Random(seed)
    out = []
    for k in range(n):
        o = px
        c = o * math.exp(r.gauss(0, sd))
        if reflect is not None:
            lo, hi = reflect
            if c < lo:
                c = lo * (1 + abs(r.gauss(0, sd)) * 2)
            if c > hi:
                c = hi * (1 - abs(r.gauss(0, sd)) * 2)
        h = max(o, c) * (1 + abs(r.gauss(0, sd / 3)))
        l = min(o, c) * (1 - abs(r.gauss(0, sd / 3)))
        if reflect is not None:
            l = max(l, reflect[0] * 0.9995)
            h = min(h, reflect[1] * 1.0005)
        v = r.uniform(50, 150)
        out.append(Candle(T0 + k * H, o, h, l, c, v, v * min(0.95, max(0.05, 0.5 + tb_bias + r.gauss(0, 0.1)))))
        px = c
    return out


class StatsBasics(unittest.TestCase):
    def test_wilson(self):
        p, lo, hi = wilson(50, 100)
        self.assertAlmostEqual(p, 0.5)
        self.assertAlmostEqual(lo, 0.4185, places=3)
        self.assertAlmostEqual(hi, 0.5815, places=3)
        self.assertEqual(wilson(0, 0), (None, None, None))

    def test_atr_series_matches_definition(self):
        cs = walk(100, 1)
        a = atr_series(cs)
        trs = [cs[0].h - cs[0].l] + [max(k.h - k.l, abs(k.h - p.c), abs(k.l - p.c)) for p, k in zip(cs, cs[1:])]
        self.assertAlmostEqual(a[13], sum(trs[:14]) / 14)
        x = sum(trs[:14]) / 14
        for tr in trs[14:]:
            x = (x * 13 + tr) / 14
        self.assertAlmostEqual(a[-1], x)

    def test_round_step(self):
        self.assertEqual(round_step(85000), 5000)
        self.assertEqual(round_step(190), 50)
        self.assertEqual(round_step(3300), 500)

    def test_outcome_definitions(self):
        mk = lambda cl: [Candle(T0 + i * H, c, c + 1, c - 1, c, 1, 0.5) for i, c in enumerate(cl)]
        self.assertEqual(outcome_at(mk([100, 101, 103]), 0, 100, "support", 2.0, 24, 1, 1), "bounce")
        self.assertEqual(outcome_at(mk([100, 99, 97]), 0, 100, "support", 2.0, 24, 1, 1), "break")
        self.assertEqual(outcome_at(mk([100, 100.5, 99.5]), 0, 100, "support", 2.0, 24, 1, 1), "open")
        self.assertEqual(outcome_at(mk([100, 97]), 0, 100, "resistance", 2.0, 24, 1, 1), "bounce")
        self.assertEqual(outcome_at(mk([100, 103]), 0, 100, "resistance", 2.0, 24, 1, 1), "break")


class StatsCalibration(unittest.TestCase):
    """Sur une marche aleatoire, aucun niveau n'a d'avantage : tout doit tourner autour de 50 %."""

    @classmethod
    def setUpClass(cls):
        cls.cs = walk(9000, seed=21)
        cls.st = reaction_stats(cls.cs)

    def test_no_edge_on_random_walk(self):
        fam = self.st["family"]
        checked = 0
        for name, sides in fam.items():
            s = sides.get("all")
            if s and s["n"] >= 150:
                checked += 1
                self.assertGreater(s["p"], 0.38, (name, s))
                self.assertLess(s["p"], 0.62, (name, s))
        self.assertGreaterEqual(checked, 5)
        base = fam["Hasard (témoin)"]["all"]
        self.assertGreater(base["n"], 200)
        self.assertLess(abs(base["p"] - 0.5), 0.1)

    def test_flow_has_no_edge_once_position_is_accounted_for(self):
        for name in ("avec", "contre"):
            s = self.st["flow"][name]["all"]
            self.assertGreater(s["n"], 100)
            self.assertLess(abs(s["p"] - s["expected"]), 0.06, (name, s))       # pas d'avantage invente

    def test_score_and_flow_buckets_exist(self):
        self.assertTrue(set(self.st["score"]) >= {"1", "2"})
        self.assertTrue(set(self.st["flow"]) >= {"avec", "contre"})
        for b in self.st["score"].values():
            s = b["all"]
            if s["n"] >= 100:
                self.assertLess(abs(s["p"] - 0.5), 0.13)

    def test_reach_table_shape(self):
        tab = reach_table(self.cs)
        for H in ("4", "24", "72"):
            up, dn = tab["up"][H], tab["down"][H]
            self.assertTrue(all(a >= b for a, b in zip(up, up[1:])))          # plus loin = moins probable
            self.assertTrue(all(a >= b for a, b in zip(dn, dn[1:])))
            for a, b in zip(up[:6], dn[:6]):
                self.assertLess(abs(a - b), 0.08)                             # marche symetrique
        for q in range(len(tab["dists"])):
            self.assertLessEqual(tab["up"]["4"][q], tab["up"]["24"][q] + 1e-12)   # plus de temps = plus probable
            self.assertLessEqual(tab["up"]["24"][q], tab["up"]["72"][q] + 1e-12)
        self.assertEqual(reach_prob(tab, 0, "up", 24), 1.0)
        p1, p2 = reach_prob(tab, 1.0, "up", 24), reach_prob(tab, 3.0, "up", 24)
        self.assertGreater(p1, p2)
        self.assertAlmostEqual(reach_prob(tab, 1.0, "up", 24), tab["up"]["24"][3])


class StatsDetectsARealEdge(unittest.TestCase):
    def test_planted_support_is_detected_and_beats_random(self):
        # le prix rebondit systematiquement sur 85 000 (nombre rond) : la famille doit le montrer
        cs = walk(9000, seed=5, px=87000.0, sd=0.003, reflect=(85000.0, 90000.0))
        st = reaction_stats(cs)
        rounds = st["family"]["Nombres ronds"]["all"]
        base = st["family"]["Hasard (témoin)"]["all"]
        self.assertGreater(rounds["n"], 30)
        self.assertGreater(rounds["p"], 0.8)
        self.assertGreater(rounds["lo"], base["hi"])                          # au-dessus du temoin, CI comprises


class SweepOutcomeTests(unittest.TestCase):
    def test_sweep_classification(self):
        mk = lambda cl: [Candle(T0 + i * H, c, c + 1, c - 1, c, 1, 0.5) for i, c in enumerate(cl)]
        cs = mk([100, 99, 98, 101, 104, 104])
        atrs = [2.0] * len(cs)
        summ, res = sweep_outcomes([{"t": T0 + H, "side": "long", "price": 99.0, "frac": 0.2}], cs, atrs)
        self.assertEqual(res[0]["result"], "bounce")
        self.assertEqual(summ["n"], 1)
        summ, res = sweep_outcomes([{"t": T0 + H, "side": "short", "price": 99.0, "frac": 0.2}], cs, atrs)
        self.assertEqual(res[0]["result"], "break")


if __name__ == "__main__":
    unittest.main()
