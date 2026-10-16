import unittest

from engine import sigtest
from engine.atr import Candle
from tests.test_engine import synth_candles, ts


def bars(spec, start=0):
    """spec : [(haut, bas, cloture)] -> bougies 1h."""
    return [Candle(start + i * 3_600_000, c, h, l, c) for i, (h, l, c) in enumerate(spec)]


def flat(n, px=100.0):
    return [(px + 0.1, px - 0.1, px)] * n


class SimulateTests(unittest.TestCase):
    def test_limit_long_filled_then_target(self):
        cs = bars(flat(1) + [(100.5, 99.0, 99.8)] + [(102.0, 99.7, 101.5)] + flat(5, 101.0))
        # entree 99,0 (touchee a la bougie 1), stop 97, objectif 101,5 (touche a la bougie 2)
        st, r, fill = sigtest.simulate(cs, 0, "long", 99.0, 97.0, 101.5, False)
        self.assertEqual((st, fill), ("tp", True))
        self.assertAlmostEqual(r, 1.25)

    def test_stop_and_target_in_the_same_candle_counts_the_stop_first(self):
        cs = bars(flat(1) + [(100.1, 98.9, 99.5)] + [(103.0, 96.0, 100.0)] + flat(3))
        st, r, fill = sigtest.simulate(cs, 0, "long", 99.0, 97.0, 102.0, False)
        self.assertEqual((st, r), ("sl", -1.0))

    def test_filled_and_stopped_in_the_fill_candle_is_a_loss(self):
        cs = bars(flat(1) + [(100.0, 96.0, 99.0)] + flat(3))
        st, r, fill = sigtest.simulate(cs, 0, "long", 99.0, 97.0, 104.0, False)
        self.assertEqual((st, r, fill), ("sl", -1.0, True))

    def test_limit_never_reached_is_nofill(self):
        cs = bars(flat(1) + flat(60))
        st, r, fill = sigtest.simulate(cs, 0, "long", 95.0, 93.0, 99.0, False, valid_h=48)
        self.assertEqual((st, fill), ("nofill", False))

    def test_short_mirrors_long(self):
        cs = bars(flat(1) + [(101.0, 99.5, 100.5)] + [(100.6, 97.5, 98.0)] + flat(3, 98.0))
        st, r, fill = sigtest.simulate(cs, 0, "short", 101.0, 103.0, 98.0, False)
        self.assertEqual((st, fill), ("tp", True))
        self.assertAlmostEqual(r, 1.5)

    def test_market_entry_and_timeout_mark_to_market(self):
        cs = bars(flat(1) + [(100.5, 99.5, 100.0)] * 80)
        st, r, fill = sigtest.simulate(cs, 0, "long", 100.0, 98.0, 104.0, True, hold_h=72)
        self.assertEqual((st, fill), ("timeout", True))
        self.assertAlmostEqual(r, 0.0, places=6)

    def test_unfinished_trades_are_not_counted(self):
        cs = bars(flat(1) + [(100.5, 99.5, 100.0)] * 5)
        st, r, fill = sigtest.simulate(cs, 0, "long", 100.0, 98.0, 104.0, True, hold_h=72)
        self.assertEqual(st, "open")


class VerdictTests(unittest.TestCase):
    def agg(self, tp, sl):
        return sigtest._agg([("tp", 2.0, True)] * tp + [("sl", -1.0, True)] * sl)

    def test_verdicts(self):
        self.assertEqual(sigtest.verdict(self.agg(70, 130), self.agg(40, 160)), "edge")
        self.assertEqual(sigtest.verdict(self.agg(40, 160), self.agg(70, 130)), "worse")
        self.assertEqual(sigtest.verdict(self.agg(50, 150), self.agg(52, 148)), "none")
        self.assertEqual(sigtest.verdict(self.agg(5, 10), self.agg(40, 160)), "thin")

    def test_aggregate_rates(self):
        a = sigtest._agg([("tp", 2.0, True), ("sl", -1.0, True), ("sl", -1.0, True), ("nofill", 0.0, False), ("open", 0.0, False)])
        self.assertEqual((a["n"], a["filled"], a["tp"], a["sl"]), (4, 3, 1, 2))
        self.assertAlmostEqual(a["fillRate"], 0.75)
        self.assertAlmostEqual(a["expR"], 0.0)
        self.assertAlmostEqual(a["win"]["p"], 1 / 3)


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cs = synth_candles(ts(2022, 1, 1), 24 * 420, seed=21)
        cls.res = sigtest.replay(cls.cs)

    def test_structure_and_ranges(self):
        r = self.res
        self.assertTrue(r["ready"])
        self.assertEqual(r["bars"], len(self.cs))
        self.assertGreater(r["ideas"], 20)
        self.assertEqual([t["minS"] for t in r["tiers"]], list(sigtest.TIERS))
        for t in r["tiers"]:
            for k in ("real", "ctrl"):
                self.assertGreaterEqual(t[k]["fillRate"], 0.3)
                self.assertLessEqual(t[k]["fillRate"], 1.0)
                self.assertEqual(t[k]["tp"] + t[k]["sl"] + t[k]["timeout"], t[k]["filled"])
            self.assertLessEqual(t["perWeek"]["mean"], r["cap"])
            self.assertIn(t["verdict"], ("edge", "none", "worse", "thin"))
        self.assertGreaterEqual(r["tiers"][0]["real"]["n"], r["tiers"][-1]["real"]["n"])        # un seuil plus haut garde moins d'idees
        self.assertIn("long", r["sides"])

    def test_cap_per_week_is_respected(self):
        r = sigtest.replay(self.cs, max_week=1)
        self.assertLessEqual(r["tiers"][0]["perWeek"]["mean"], 1.0 + 1e-9)
        self.assertEqual(r["tiers"][0]["perWeek"]["p90"], 1)

    def test_deterministic(self):
        again = sigtest.replay(self.cs)
        self.assertEqual(again["tiers"], self.res["tiers"])

    def test_trend_split_with_same_trend_controls(self):
        """420 jours d'historique : la tendance de fond (200 j) existe pour la derniere partie ; les idees sont ventilees dans le sens / contre / indecise."""
        r = self.res
        self.assertEqual(sorted(r["trend"]), ["aligned", "counter", "neutral"])
        n = sum(r["trend"][k]["real"]["n"] for k in r["trend"])
        self.assertGreater(n, 0)
        for k in r["trend"]:
            self.assertIn(r["trend"][k]["verdict"], ("edge", "none", "worse", "thin"))
        self.assertEqual(r["version"], sigtest.VERSION)
        self.assertGreaterEqual(sigtest.VERSION, 2)

    def test_validation_text_mentions_trend_when_enough_cases(self):
        fake = {"ready": True, "from": 1_600_000_000_000, "tiers": [{"minS": 7.0, "verdict": "none", "real": {"n": 50, "filled": 40, "tp": 15, "sl": 20, "win": {"p": 0.43, "lo": 0.3, "hi": 0.56}},
                                                                        "ctrl": {"win": {"p": 0.4, "lo": 0.3, "hi": 0.5}}}],
                "trend": {"aligned": {"real": {"n": 30, "tp": 12, "sl": 12, "win": {"p": 0.5, "lo": 0.3, "hi": 0.7}}, "ctrl": {"win": {"p": 0.42, "lo": 0.3, "hi": 0.5}}}}}
        t = sigtest.validation_text(fake, 8.0)
        self.assertIn("Dans le sens de la tendance de fond", t)
        self.assertIn("50 %", t)

    def test_too_short_history_is_not_ready(self):
        self.assertFalse(sigtest.replay(self.cs[:500])["ready"])

    def test_validation_text_and_tier_lookup(self):
        r = self.res
        self.assertIsNone(sigtest.tier_for(r, 3.0))
        self.assertEqual(sigtest.tier_for(r, 7.5)["minS"], 7.0)
        self.assertEqual(sigtest.tier_for(r, 9.5)["minS"], 9.0)
        self.assertEqual(sigtest.tier_for(r, 40.0)["minS"], 11.0)
        t = sigtest.validation_text(r, 8.0)
        self.assertIn("hasard", t)
        self.assertIn("Rejeu", t)
        self.assertIsNone(sigtest.validation_text(None, 8.0))


if __name__ == "__main__":
    unittest.main()
