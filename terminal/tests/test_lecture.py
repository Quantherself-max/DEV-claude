import json
import unittest

from engine import lecture as L

NOW = 1_790_000_000_000


def base(**kw):
    d = {"symbol": "SOLUSDT", "price": 190.0, "change24": 1.2, "now_ms": NOW,
         "ctx": {"funding": {"now": 0.01}, "oi": {"now": 1_000_000.0, "d24h": 1.5}, "regime": {"code": "flat_flat", "label": "Calme"}, "cvd": {"buy24h": 53.0}, "liqReal": {"24h": {"long": 4e6, "short": 1e6, "n": 30}}},
         "perps": [{"ex": "Bybit", "funding": 0.0001, "intervalH": 8.0, "oiUsd": 1e8}, {"ex": "OKX", "funding": 0.0001, "intervalH": 8.0, "oiUsd": 8e7}],
         "synth": {"label": "Neutre", "score": -7, "validated": False, "base24": 0.53, "levels": [{"side": "above", "mid": 195.0, "distAtr": 2.0, "score": 3, "reach24": 0.5}, {"side": "above", "mid": 200.0, "distAtr": 4.0, "score": 2, "reach24": 0.3},
                                                                                         {"side": "below", "mid": 185.0, "distAtr": 2.5, "score": 4, "reach24": 0.4}, {"side": "in", "mid": 190.0, "distAtr": 0.0, "score": 1}]},
         "macro": {"label": "risk-off", "risk": {"label": "CPI", "t": NOW + 3_600_000, "minutes": 60.0}, "upcoming": []}, "fng": {"value": 15, "label": "Extreme Fear"},
         "dom": {"btc_d": 58.0, "regime": "Hausse portée par le BTC"}, "trend": {"regime": 1, "label": "haussière", "distFast": 5.0, "distSlow": 20.0}, "idea": {"n": 0}}
    d.update(kw)
    return d


class LectureTests(unittest.TestCase):
    def test_french_number_format(self):
        self.assertEqual(L.fr(85000, 0), "85 000")
        self.assertEqual(L.fr(-1.234, 2, True), "−1,23")
        self.assertEqual(L.fr(None), "n/d")
        self.assertEqual(L.usd(2.5e9), "2,50 Md$")
        self.assertEqual(L.usd(3.4e6), "3,4 M$")

    def test_build_is_serializable_and_complete(self):
        out = L.build(base())
        json.dumps(out)
        keys = [c["key"] for c in out["chips"]]
        self.assertEqual(keys[:4], ["funding", "oi", "flow", "liq"])
        self.assertIn("macro", keys)
        self.assertIn("dom", keys)                                  # paire non BTC : dominance affichee
        self.assertEqual(out["head"]["trend"]["evidence"], "valide")
        self.assertEqual([l["mid"] for l in out["watch"]["up"]], [195.0, 200.0])    # du plus proche au plus loin
        self.assertEqual([l["mid"] for l in out["watch"]["dn"]], [185.0])
        self.assertEqual(out["watch"]["next"]["label"], "CPI")
        self.assertFalse(out["optionsOn"])

    def test_every_chip_carries_an_evidence_level_and_only_the_trend_is_validated(self):
        out = L.build(base())
        self.assertTrue(all(c["evidence"] in ("contexte", "indice", "informatif") for c in out["chips"]))
        self.assertTrue(all(c["group"] in ("Positionnement", "Dérivés", "Macro et liquidité") for c in out["chips"]))

    def test_crowded_funding_is_flagged_only_when_every_exchange_agrees(self):
        hot = base(ctx={**base()["ctx"], "funding": {"now": 0.06}}, perps=[{"ex": "Bybit", "funding": 0.0006, "intervalH": 8.0}, {"ex": "OKX", "funding": 0.0005, "intervalH": 8.0}])
        c = next(c for c in L.build(hot)["chips"] if c["key"] == "funding")
        self.assertEqual(c["tone"], "warn")
        self.assertIn("Foule acheteuse", c["note"])
        mixed = base(ctx={**base()["ctx"], "funding": {"now": 0.06}}, perps=[{"ex": "Bybit", "funding": -0.0001, "intervalH": 8.0}])
        c = next(c for c in L.build(mixed)["chips"] if c["key"] == "funding")
        self.assertEqual(c["tone"], "")

    def test_unvalidated_bias_is_not_dressed_up(self):
        out = L.build(base())
        self.assertFalse(out["head"]["bias"]["validated"])

    def test_options_block_and_basis_warning(self):
        opt = {"spot": 85000.0, "oiUsd": 1e9, "expiries": [{"expiry": NOW + 3 * 86_400_000, "daysLeft": 3.0, "maxPain": 84000.0, "putCall": 1.4, "walls": [{"strike": 85000.0, "oi": 10, "calls": 5, "puts": 5}]}]}
        out = L.build(base(options=opt, optionsCoin="BTC", dvol={"value": 55.0, "rank": 0.9, "days": 14.0, "chg24h": 0.05},
                           futures=[{"perp": True, "basis": 0.0001}, {"perp": False, "annualized": 0.2, "daysLeft": 30.0}]))
        by = {c["key"]: c for c in out["chips"]}
        self.assertIn("84 000", by["options"]["value"])
        self.assertIn("puts", by["options"]["note"])
        self.assertIn("haute", by["dvol"]["note"])
        self.assertEqual(by["basis"]["tone"], "warn")
        self.assertTrue(out["optionsOn"])

    def test_indicator_chips_only_for_measured_hints(self):
        reads = {"stable_30d": {"date": NOW - 86_400_000, "value": 0.021, "rank": 0.8, "prev": 0.0}, "puell": {"date": NOW - 86_400_000, "value": 0.1, "rank": 0.4, "prev": 0.0},
                 "mvrv": {"date": NOW, "value": 1.4, "rank": 0.3, "prev": 1.3}}
        out = L.build(base(indicators={"readings": reads}, indicatorLevels={"stable_30d": "indice", "puell": "rien", "mvrv": "rien"}))
        keys = [c["key"] for c in out["chips"]]
        self.assertIn("stable_30d", keys)
        self.assertNotIn("puell", keys)                            # « rien de prouvé » : n'encombre pas l'ecran
        self.assertNotIn("mvrv", keys)
        c = next(c for c in out["chips"] if c["key"] == "stable_30d")
        self.assertEqual(c["evidence"], "indice")
        self.assertIn("80e centile", c["value"])

    def test_btc_has_no_dominance_chip_and_missing_inputs_do_not_crash(self):
        out = L.build(base(symbol="BTCUSDT"))
        self.assertNotIn("dom", [c["key"] for c in out["chips"]])
        bare = L.build({"symbol": "BTCUSDT", "price": 1.0, "now_ms": NOW})
        self.assertEqual(bare["chips"], [])
        self.assertTrue(bare["ready"])


if __name__ == "__main__":
    unittest.main()
