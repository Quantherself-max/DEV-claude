import unittest

from engine.synth import flow_score, structure_score, synthesize


def bias(validated, p24=0.58, p4=0.56, base=0.52):
    h = lambda p: {"validated": validated, "pUp": p if validated else base, "base": base}
    return {"ready": True, "horizons": {"4": h(p4), "24": h(p24)}}


def zone(i, side, mid, dist, reach, bounce_p=0.56):
    return {"id": i, "side": side, "mid": mid, "score": 3, "distAtr": dist,
            "prob": {"reach": {"4": reach / 3, "24": reach, "72": min(1, reach * 1.5)}, "bounce": {"p": bounce_p, "n": 300}}}


CTX_BULL = {"cvd": {"buy4h": 54.0, "buy24h": 53.0}, "funding": {"now": -0.005}, "ls": {"global": {"now": 0.9}},
            "regime": {"code": "up_up", "label": "Hausse alimentée par de nouvelles positions"}}
CTX_BEAR = {"cvd": {"buy4h": 46.0, "buy24h": 47.0}, "funding": {"now": 0.08}, "ls": {"global": {"now": 2.2}},
            "regime": {"code": "down_up", "label": "Baisse avec nouvelles positions"}}
MACRO_ON = {"score": 40.0, "label": "risk-on", "risk": None}
ZONES = [zone("a", "above", 101.0, 1.0, 0.7), zone("b", "below", 98.0, 2.0, 0.4)]


class SynthTests(unittest.TestCase):
    def test_everything_aligned_and_validated_is_bullish_with_confidence(self):
        s = synthesize("SOLUSDT", 100.0, bias(True), MACRO_ON, {"regime": {"name": "Alt season", "score": 0.6}}, CTX_BULL, ZONES, {"a", "b"})
        self.assertEqual(s["direction"], "haussier")
        self.assertGreater(s["score"], 30)
        self.assertIn("biais haussier", s["label"])
        self.assertIn(s["confidence"], ("moyenne", "élevée"))
        self.assertTrue(s["validated"])
        self.assertAlmostEqual(sum(c["weight"] for c in s["components"]), 1.0, places=6)
        self.assertTrue(s["pros"] and s["invalidation"])
        self.assertAlmostEqual(s["pUp24"], 0.58)

    def test_unvalidated_model_gives_no_bias_and_caps_confidence(self):
        s = synthesize("SOLUSDT", 100.0, bias(False), MACRO_ON, None, CTX_BULL, ZONES, {"a", "b"})
        self.assertFalse(s["validated"])
        self.assertNotIn("stat", [c["key"] for c in s["components"]])        # le modele non valide n'oriente rien
        self.assertIn("ne bat pas le hasard", s["statNote"])
        self.assertEqual(s["confidence"], "faible")                           # sans modele valide : confiance faible, quoi qu'il arrive
        self.assertEqual(s["pUp24"], 0.52)                                    # taux de base, pas une prevision

    def test_bearish_mirror(self):
        s = synthesize("SOLUSDT", 100.0, bias(True, 0.42, 0.44), {"score": -40.0, "label": "risk-off", "risk": None}, None, CTX_BEAR, ZONES[::-1], {"a", "b"})
        self.assertEqual(s["direction"], "baissier")
        self.assertLess(s["score"], -30)
        self.assertTrue(any("Reprise" in t for t in s["invalidation"]))

    def test_event_danger_forces_low_confidence(self):
        risk = {"level": "danger", "label": "CPI", "minutes": 40}
        s = synthesize("BTCUSDT", 100.0, bias(True), {**MACRO_ON, "risk": risk}, None, CTX_BULL, ZONES, {"a", "b"})
        self.assertEqual(s["confidence"], "faible")
        self.assertTrue(any("40 min" in t for t in s["invalidation"]))

    def test_mixed_signals_are_neutral(self):
        s = synthesize("BTCUSDT", 100.0, bias(False), {"score": -30.0, "label": "risk-off", "risk": None}, None, CTX_BULL, [], set())
        self.assertEqual(s["direction"], "neutre")
        self.assertEqual(s["confidence"], "faible")

    def test_dominance_only_counts_for_alts(self):
        d = {"regime": {"name": "Saison BTC", "score": -0.5}}
        a = synthesize("SOLUSDT", 100.0, None, None, d, None, [], set())
        b = synthesize("BTCUSDT", 100.0, None, None, d, None, [], set())
        self.assertEqual([c["key"] for c in a["components"]], ["dom"])
        self.assertEqual(b["components"], [])

    def test_flow_and_structure_edge_cases(self):
        self.assertEqual(flow_score(None), (None, []))
        self.assertEqual(flow_score({}), (None, []))
        self.assertEqual(structure_score([], 100.0), (None, None))
        sc, ctx = structure_score(ZONES, 100.0)
        self.assertGreater(sc, 0)                                             # la zone du dessus est plus probable
        self.assertEqual(ctx[2], 0.7)



class SwingFlowTests(unittest.TestCase):
    def test_swing_divergence_and_absorption_enter_the_flow_score(self):
        base = {"cvd": {"buy4h": 50.0, "buy24h": 50.0}}
        s0, n0 = flow_score(base)
        bull = {"cvd": {"buy4h": 50.0, "buy24h": 50.0, "swingDiv": "bull", "swingDivStrength": 0.8, "absorb": "bull"}}
        s1, n1 = flow_score(bull)
        self.assertGreater(s1, s0)
        self.assertTrue(any("Divergence haussière du CVD" in t for _, t in n1))
        self.assertTrue(any("Absorption haussière" in t for _, t in n1))
        bear = {"cvd": {"buy4h": 50.0, "buy24h": 50.0, "swingDiv": "bear", "swingDivStrength": 0.2, "absorb": "bear"}}
        s2, n2 = flow_score(bear)
        self.assertLess(s2, s0)
        self.assertTrue(any("Divergence baissière du CVD" in t for _, t in n2))


if __name__ == "__main__":
    unittest.main()
