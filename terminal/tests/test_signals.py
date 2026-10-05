import re
import unittest

from engine import signals as sg
from engine.atr import Candle

H = 3_600_000
NOW = 1_790_000_000_000
BANNED = re.compile(r"\b(ATR|TP|SL|CVD|POC|VAH|VAL|HVN|OI|RR|R:R|AVWAP|nPOC|PDH|PDL|PWH|PWL)\b")


def lv(i, name, price, group, kind, **extra):
    return {"id": i, "name": name, "price": price, "group": group, "kind": kind, **extra}


def zone(zid, members, price, side=None):
    ps = [m["price"] for m in members]
    lo, hi = min(ps), max(ps)
    mid = sum(ps) / len(ps)
    return {"id": zid, "lo": lo, "hi": hi, "mid": mid, "members": [m["id"] for m in members],
            "side": side or ("below" if hi < price else "above" if lo > price else "in"), "groups": sorted({m["group"] for m in members})}


def scene(price=100.0, extra_levels=(), extra_zones=(), pools=(), candles=None, sweeps=(), opts=None):
    """Support solide a ~98 (VWAP du mois, ouverture de la semaine, POC de la semaine derniere, plus bas de la veille)
    et resistance solide a ~106 (VWAP de l'annee, plus haut de la semaine derniere, VAH du mois dernier)."""
    sup = [lv("a", "mVWAP", 98.00, "mVWAP", "vwap"), lv("b", "wOpen", 98.06, "wOpen", "open"),
           lv("c", "pwPOC", 97.96, "pwVP", "vp"), lv("d", "PDL", 98.03, "PDHL", "hl")]
    res = [lv("e", "yVWAP", 106.00, "yVWAP", "vwap"), lv("f", "PWH", 106.05, "PWHL", "hl"), lv("g", "pmVAH", 105.95, "pmVP", "vp")]
    levels = sup + res + list(extra_levels)
    zones = [zone("z1", sup, price), zone("z2", res, price)] + list(extra_zones)
    cs = candles if candles is not None else [Candle(NOW - (12 - k) * H, 100, 100.4, 99.6, 100.0, 10, 5) for k in range(12)]
    return {"symbol": "BTCUSDT", "now": NOW, "price": price, "atr": 1.0, "levels": levels, "zones": zones, "pools": list(pools),
            "candles": cs, "sweeps": list(sweeps), "opts": opts or {}}


class ClassifyTests(unittest.TestCase):
    def test_weight_grows_with_timeframe_and_vwap_vp_are_favoured(self):
        w = {k: sg.classify(lv("x", k + "VWAP", 100, k + "VWAP", "vwap"))["w"] for k in "dwmy"}
        self.assertLess(w["d"], w["w"])
        self.assertLess(w["w"], w["m"])
        self.assertLess(w["m"], w["y"])
        self.assertGreater(sg.classify(lv("x", "wVWAP", 100, "wVWAP", "vwap"))["w"], sg.classify(lv("x", "wOpen", 100, "wOpen", "open"))["w"])
        self.assertGreater(sg.classify(lv("x", "pwPOC", 100, "pwVP", "vp"))["w"], sg.classify(lv("x", "PWH", 100, "PWHL", "hl"))["w"])
        self.assertLess(sg.classify(lv("x", "Rond 100", 100, "ROUND", "round"))["w"], 1.0)

    def test_previous_and_current_periods_and_naked_poc(self):
        self.assertEqual(sg.classify(lv("x", "pyPOC", 100, "pyVP", "vp"))["tf"], 4)
        self.assertEqual(sg.classify(lv("x", "PMH", 100, "PMHL", "hl"))["tf"], 3)
        self.assertEqual(sg.classify(lv("x", "nPOC S-3", 100, "nPOC", "npoc"))["tf"], 2)
        self.assertEqual(sg.classify(lv("x", "nPOC J-2", 100, "nPOC", "npoc"))["tf"], 1)

    def test_custom_volume_profiles_and_anchored_vwap_by_span(self):
        self.assertEqual(sg.classify(lv("x", "VP 3j POC", 100, "xVP:r3", "xvp", vpid="r3"), NOW)["tf"], 1)
        self.assertEqual(sg.classify(lv("x", "VP 30j POC", 100, "xVP:r30", "xvp", vpid="r30"), NOW)["tf"], 3)
        self.assertEqual(sg.classify(lv("x", "VP 180j VAH", 100, "xVP:r180", "xvp", vpid="r180"), NOW)["tf"], 4)
        old = NOW - 400 * 24 * H
        self.assertEqual(sg.classify(lv("x", "AVWAP bas 1 an", 100, "aVWAP:1", "avwap", anchor=old), NOW)["tf"], 4)
        self.assertEqual(sg.classify(lv("x", "AVWAP 2026", 100, "aVWAP:2", "avwap", anchor=NOW - 5 * 24 * H), NOW)["tf"], 1)

    def test_texts_are_plain_french_without_abbreviations(self):
        cases = [lv("x", n, 100, g, k, **e) for n, g, k, e in [
            ("dVWAP", "dVWAP", "vwap", {}), ("mVWAP+2σ", "mVWAP", "band", {}), ("yOpen", "yOpen", "open", {}), ("mPOC", "mVP", "vp", {}),
            ("mHVN", "mVP", "vp", {}), ("pwVAH", "pwVP", "vp", {}), ("pdVAL", "pdVP", "vp", {}), ("PYH", "PYHL", "hl", {}), ("PML", "PMHL", "hl", {}),
            ("nPOC S-2", "nPOC", "npoc", {}), ("AVWAP bas 1 an", "aVWAP:1", "avwap", {"anchor": 1}), ("AVWAP année préc.", "aVWAP:2", "avwap", {"anchor": 2}),
            ("VP 90j POC", "xVP:r90", "xvp", {"vpid": "r90"}), ("VP depuis 01/06/25 VAL", "xVP:s2025-06-01", "xvp", {"vpid": "s2025-06-01"}),
            ("VP mois -1 POC", "xVP:month1", "xvp", {"vpid": "month1"}), ("Rond 100", "ROUND", "round", {})]]
        for c in cases:
            t = sg.classify(c, NOW)["text"]
            self.assertTrue(t and "100" in t, t)
            self.assertIsNone(BANNED.search(t), t)

    def test_zone_structure_counts_sources_once_and_ignores_rounds(self):
        ms = [lv("1", "mVWAP", 100, "mVWAP", "vwap"), lv("2", "mVWAP+2σ", 100.1, "mVWAP", "band"), lv("3", "Rond 100", 100, "ROUND", "round"),
              lv("4", "wOpen", 100.05, "wOpen", "open")]
        st = sg.zone_structure(ms, NOW)
        self.assertEqual(st["n"], 2)
        self.assertAlmostEqual(st["S"], 4.8 + 1.6, places=6)                 # VWAP du mois 3 x 1,6 ; ouverture de la semaine 2 x 0,8
        self.assertEqual(st["core"], 1)
        self.assertEqual(st["htf"], 2)

    def test_near_identical_anchored_vwaps_count_once(self):
        a = lv("1", "AVWAP bas 1 an", 100.00, "aVWAP:1", "avwap", anchor=NOW - 300 * 24 * H)
        b = lv("2", "AVWAP année préc.", 100.05, "aVWAP:2", "avwap", anchor=NOW - 200 * 24 * H)
        self.assertEqual(sg.zone_structure([a, b], NOW)["n"], 1)
        c = lv("3", "AVWAP haut 3 mois", 101.0, "aVWAP:3", "avwap", anchor=NOW - 60 * 24 * H)
        self.assertEqual(sg.zone_structure([a, b, c], NOW)["n"], 2)


class BuildIdeaTests(unittest.TestCase):
    def test_long_idea_on_support_with_stop_and_targets(self):
        ideas, rej = sg.build_ideas(scene())
        longs = [i for i in ideas if i["side"] == "long"]
        self.assertEqual(len(longs), 1)
        i = longs[0]
        self.assertEqual(i["kind"], "rebond")
        self.assertEqual(i["entryType"], "limite")
        self.assertAlmostEqual(i["entry"], 98.06)                  # bord haut de la zone
        self.assertLess(i["stop"], 97.96)                          # sous la zone
        self.assertGreater(i["tp1"], i["entry"])
        self.assertLess(i["tp1"], 105.95)                          # juste avant la resistance
        self.assertGreaterEqual(i["rr1"], 1.5)
        self.assertAlmostEqual(i["rr1"], (i["tp1"] - i["entry"]) / (i["entry"] - i["stop"]))

    def test_short_idea_on_resistance(self):
        s = scene(price=105.0)
        ideas, _ = sg.build_ideas(s)
        shorts = [i for i in ideas if i["side"] == "short"]
        self.assertEqual(len(shorts), 1)
        self.assertEqual(shorts[0]["entry"], 105.95)
        self.assertGreater(shorts[0]["stop"], 106.05)
        self.assertLess(shorts[0]["tp1"], shorts[0]["entry"])

    def test_too_few_sources_or_low_quality_gives_nothing(self):
        s = scene()
        s["zones"][0] = zone("z1", s["levels"][:2], 100.0)           # 2 sources seulement
        ideas, rej = sg.build_ideas(s)
        self.assertFalse([i for i in ideas if i["zoneId"] == "z1"])
        s2 = scene(opts={"min_struct": 30.0})
        self.assertEqual(sg.build_ideas(s2)[0], [])

    def test_price_too_far_is_rejected_with_reason(self):
        ideas, rej = sg.build_ideas(scene(price=110.0))
        self.assertFalse([i for i in ideas if i["side"] == "long"])
        self.assertTrue(any("trop loin" in r["why"] for r in rej))

    def test_tight_stop_is_widened_to_the_noise_floor_and_a_huge_one_is_rejected(self):
        i = [x for x in sg.build_ideas(scene())[0] if x["side"] == "long"][0]
        self.assertGreaterEqual(i["entry"] - i["stop"], 1.5 - 1e-9)           # plancher : 1,5 amplitude d'heure
        s = scene()
        s["atr"], s["price"] = 0.2, 98.5                                          # amplitude faible : la zone entiere devient un stop enorme
        wide = [lv("a", "mVWAP", 96.0, "mVWAP", "vwap"), lv("b", "wOpen", 98.06, "wOpen", "open"), lv("c", "pwPOC", 97.0, "pwVP", "vp")]
        s["levels"] = wide + [l for l in s["levels"] if l["id"] in ("e", "f", "g")]
        s["zones"] = [zone("z1", wide, 98.5), s["zones"][1]]
        ideas, rej = sg.build_ideas(s)
        self.assertFalse([x for x in ideas if x["side"] == "long"])
        self.assertTrue(any("trop éloigné" in r["why"] for r in rej))

    def test_no_realistic_target_rejects(self):
        s = scene()
        s["levels"] = [l for l in s["levels"] if l["id"] not in ("e", "f", "g")]
        s["zones"] = [s["zones"][0]]
        ideas, rej = sg.build_ideas(s)
        self.assertEqual(ideas, [])
        self.assertTrue(any("objectif" in r["why"] for r in rej))

    def test_big_opposite_pool_can_be_the_target(self):
        pool = {"side": "short", "lo": 103.0, "hi": 103.3, "price": 103.1, "score": 90, "magnet": True, "size": 1.0}
        s = scene(pools=[pool])
        ideas, _ = sg.build_ideas(s)
        i = [x for x in ideas if x["side"] == "long"][0]
        self.assertEqual(i["tp1Kind"], "pool")
        self.assertAlmostEqual(i["tp1"], 103.0 - 0.1)

    def test_second_target_is_further_than_a_full_amplitude(self):
        pool = {"side": "short", "lo": 103.0, "hi": 103.3, "price": 103.1, "score": 90, "magnet": True, "size": 1.0}
        ideas, _ = sg.build_ideas(scene(pools=[pool]))
        i = [x for x in ideas if x["side"] == "long"][0]
        self.assertIsNotNone(i["tp2"])
        self.assertGreaterEqual(i["tp2"] - i["tp1"], 1.0)
        self.assertGreater(i["rr2"], i["rr1"])

    def test_reclaim_after_sweep_of_the_zone(self):
        cs = [Candle(NOW - (12 - k) * H, 99, 99.5, 98.6, 99.0, 10, 5) for k in range(10)]
        cs.append(Candle(NOW - 2 * H, 99, 99.1, 96.5, 97.0, 10, 5))        # meche sous la zone
        cs.append(Candle(NOW - H, 97.0, 98.6, 96.9, 98.4, 10, 5))          # cloture reprise au-dessus de la zone
        ideas, _ = sg.build_ideas(scene(price=98.4, candles=cs))
        i = [x for x in ideas if x["side"] == "long"][0]
        self.assertEqual(i["kind"], "reprise")
        self.assertEqual(i["entryType"], "marché")
        self.assertLess(i["stop"], 96.5)                                    # sous la meche
        self.assertEqual(i["wick"], 96.5)

    def test_recent_liquidity_sweep_triggers_reprise(self):
        e = {"t": NOW - 2 * H, "side": "long", "price": 98.4, "to": 97.3, "frac": 0.3}
        ideas, _ = sg.build_ideas(scene(price=99.0, sweeps=[e]))
        i = [x for x in ideas if x["side"] == "long"][0]
        self.assertEqual(i["kind"], "reprise")
        self.assertIsNotNone(i["sweep"])
        self.assertLess(i["stop"], 97.3)
        old = dict(e, t=NOW - 30 * H)
        self.assertEqual([x for x in sg.build_ideas(scene(price=99.0, sweeps=[old]))[0] if x["side"] == "long"][0]["kind"], "rebond")

    def test_pool_in_zone_widens_the_stop(self):
        pool = {"side": "long", "lo": 97.2, "hi": 97.6, "price": 97.4, "score": 80, "magnet": True, "size": 1.0}
        m = lv("p", "Liq longs", 97.4, "LIQ", "liq", pool=pool)
        s = scene(extra_levels=[m])
        s["zones"][0] = zone("z1", [l for l in s["levels"] if l["id"] in ("a", "b", "c", "d", "p")], 100.0)
        s["pools"] = [pool]
        i = [x for x in sg.build_ideas(s)[0] if x["side"] == "long"][0]
        self.assertLess(i["stop"], 97.2)
        self.assertEqual(len(i["pools"]), 1)

    def test_at_most_two_ideas_per_side_and_no_nested_duplicates(self):
        extra = [lv("h", "mOpen", 98.5, "mOpen", "open"), lv("i", "PMH", 98.45, "PMHL", "hl"), lv("j", "pyPOC", 98.52, "pyVP", "vp")]
        s = scene(extra_levels=extra, extra_zones=[zone("z3", extra, 100.0)])
        longs = [i for i in sg.build_ideas(s)[0] if i["side"] == "long"]
        self.assertLessEqual(len(longs), 2)


class ScoreTests(unittest.TestCase):
    def idea(self, **kw):
        i = sg.build_ideas(scene())[0]
        i = [x for x in i if x["side"] == "long"][0]
        i.update(kw)
        return i

    def ctx(self, **kw):
        c = {"price": 100.0, "vwap": {"W": 99.0, "M": 98.0, "Y": 95.0}, "flow": (0.5, [(0.5, "achats agressifs")]), "macro": {"score": 40, "label": "risk-on"},
             "synth": {"direction": "haussier", "score": 40}, "dom": {}, "is_alt": False, "now": NOW}
        c.update(kw)
        return c

    def test_score_is_bounded_and_aligned_context_is_rewarded(self):
        good = sg.score_idea(self.idea(), self.ctx())
        bad = sg.score_idea(self.idea(), self.ctx(flow=(-0.8, [(-0.8, "ventes")]), macro={"score": -80, "label": "risk-off"},
                                                   vwap={"W": 101, "M": 102, "Y": 110}, synth={"direction": "baissier", "score": -60}))
        self.assertLessEqual(good["score"], 100.0)
        self.assertGreater(good["score"], bad["score"] + 15)
        self.assertEqual(sum(c["max"] for c in good["comps"]), 100)
        self.assertTrue(any("contre la tendance" in w for w in bad["warn"]))

    def test_major_announcement_soon_holds_the_idea(self):
        risk = {"minutes": 90, "label": "Inflation (CPI)", "level": "danger"}
        r = sg.score_idea(self.idea(), self.ctx(macro={"score": 10, "label": "neutre", "risk": risk}))
        self.assertTrue(r["hold"])
        self.assertIn("annonce majeure", r["hold"][0])
        far = {"minutes": 600, "label": "Inflation (CPI)", "level": "attention"}
        r2 = sg.score_idea(self.idea(), self.ctx(macro={"score": 10, "label": "neutre", "risk": far}))
        self.assertFalse(r2["hold"])
        self.assertTrue(r2["warn"])
        r3 = sg.score_idea(self.idea(), self.ctx(macro={"score": 10, "label": "neutre", "inWindow": ["x"]}))
        self.assertTrue(r3["hold"])

    def test_liquidity_points_for_pool_sweep_and_reclaim(self):
        base = sg.score_idea(self.idea(), self.ctx())
        pool = {"side": "long", "lo": 97, "hi": 97.5, "price": 97.2, "score": 85, "magnet": True}
        withp = sg.score_idea(self.idea(pools=[pool]), self.ctx())
        withs = sg.score_idea(self.idea(pools=[pool], sweep={"t": NOW, "side": "long", "price": 98, "to": 97, "frac": 0.3}), self.ctx())
        liq = lambda r: [c for c in r["comps"] if c["key"] == "liquidity"][0]["pts"]
        self.assertGreater(liq(withp), liq(base))
        self.assertGreater(liq(withs), liq(withp))
        self.assertLessEqual(liq(withs), 30)

    def test_three_pillars_dominate_the_score_and_comps_sum_to_100(self):
        r = sg.score_idea(self.idea(), self.ctx())
        mx = {c["key"]: c["max"] for c in r["comps"]}
        self.assertEqual(mx, {"liquidity": 30, "structure": 30, "macro": 20, "flow": 8, "trend": 7, "bias": 5})
        self.assertEqual(sum(mx.values()), 100)

    def test_liquidity_gate(self):
        no_liq = sg.score_idea(self.idea(), self.ctx())                                  # simple rebond, ni poche ni balayage ni objectif poche
        self.assertTrue(any("liquidité" in g for g in no_liq["gates"]))
        pool = {"side": "long", "lo": 97, "hi": 97.5, "price": 97.2, "score": 85, "magnet": True}
        self.assertFalse(sg.score_idea(self.idea(pools=[pool]), self.ctx())["gates"])
        self.assertFalse(sg.score_idea(self.idea(kind="reprise", wick=97.0), self.ctx())["gates"])            # zone percee puis reprise = liquidite prise
        self.assertFalse(sg.score_idea(self.idea(tp1Kind="pool"), self.ctx())["gates"])                      # grosse poche en face comme objectif
        weak = {"side": "long", "lo": 97, "hi": 97.5, "price": 97.2, "score": 30, "magnet": False}
        self.assertTrue(sg.score_idea(self.idea(pools=[weak]), self.ctx())["gates"])                          # poche trop petite

    def test_macro_gate_only_when_macro_goes_clearly_against_the_idea(self):
        pool = {"side": "long", "lo": 97, "hi": 97.5, "price": 97.2, "score": 85, "magnet": True}
        against = sg.score_idea(self.idea(pools=[pool]), self.ctx(macro={"score": -80, "label": "risk-off"}))
        self.assertTrue(any("macro" in g for g in against["gates"]))
        self.assertFalse(sg.score_idea(self.idea(pools=[pool]), self.ctx(macro={"score": -20, "label": "neutre"}))["gates"])
        self.assertFalse(sg.score_idea(self.idea(pools=[pool]), self.ctx(macro={"label": "indisponible"}))["gates"])
        short = self.idea(pools=[dict(pool, side="short")], side="short")
        self.assertFalse(sg.score_idea(short, self.ctx(macro={"score": -80, "label": "risk-off"}))["gates"])   # risk-off favorise la vente

    def test_zone_without_any_vwap_or_anchored_vwap_is_not_an_idea(self):
        s = scene()
        sup = [lv("a", "pwPOC", 98.0, "pwVP", "vp"), lv("b", "wOpen", 98.06, "wOpen", "open"), lv("c", "PDL", 98.03, "PDHL", "hl"), lv("d", "PWL", 97.96, "PWHL", "hl")]
        s["levels"] = sup + [l for l in s["levels"] if l["id"] in ("e", "f", "g")]
        s["zones"] = [zone("z1", sup, 100.0), s["zones"][1]]
        self.assertFalse([i for i in sg.build_ideas(s)[0] if i["side"] == "long"])

    def test_news_lines_in_plain_language(self):
        ev = {"label": "Inflation (CPI)", "t": NOW + 20 * H, "impact": 3, "w": 1.0, "exp": {"text": "Consensus 3,1 % contre 3,0 % précédemment : hausse attendue."}}
        past = {"label": "Emplois non agricoles", "t": NOW - 5 * H, "impact": 3, "w": 1.0, "reaction": {"impulse": 1.0, "impulseLabel": "restrictive"}}
        lines = sg.news_lines({"upcoming": [ev], "past": [past]}, NOW)
        self.assertEqual(len(lines), 2)
        self.assertIn("Consensus 3,1 %", lines[0])
        self.assertIn("heure UTC", lines[0])
        self.assertIn("restrictive", lines[1])
        self.assertEqual(sg.news_lines({}, NOW), [])


class NearPoolTests(unittest.TestCase):
    def test_big_pool_just_beyond_the_zone_moves_the_stop_behind_it(self):
        pool = {"side": "long", "lo": 96.8, "hi": 97.4, "price": 97.1, "score": 90, "magnet": True, "size": 1.0}
        i = [x for x in sg.build_ideas(scene(pools=[pool]))[0] if x["side"] == "long"][0]
        self.assertEqual(len(i["nearPools"]), 1)
        self.assertLess(i["stop"], 96.8)
        r = sg.score_idea(i, TextTests.ctx_for(scene()))
        self.assertTrue([c for c in r["comps"] if c["key"] == "liquidity"][0]["pts"] >= 6)
        self.assertFalse(r["gates"])
        small = dict(pool, score=30)
        j = [x for x in sg.build_ideas(scene(pools=[small]))[0] if x["side"] == "long"][0]
        self.assertEqual(j["nearPools"], [])
        far = dict(pool, lo=90.0, hi=90.5, price=90.2)
        self.assertEqual([x for x in sg.build_ideas(scene(pools=[far]))[0] if x["side"] == "long"][0]["nearPools"], [])


class TextTests(unittest.TestCase):
    @staticmethod
    def ctx_for(s):
        return {"price": s["price"], "vwap": {"W": 99, "M": 98, "Y": 95}, "flow": (0.3, [(0.3, "Flux agressif : 56 % d'achats")]),
                "macro": {"score": 30, "label": "risk-on", "upcoming": [], "past": [], "lines": [{"tone": "ok", "text": "Lecture macro : risk-on (+30/100). C'est un contexte."}]},
                "synth": {"direction": "haussier", "score": 30}, "dom": {}, "is_alt": False, "now": NOW}

    def full(self, side="long"):
        pool = {"side": "long" if side == "long" else "short", "lo": 97.2 if side == "long" else 106.4, "hi": 97.6 if side == "long" else 106.8,
                "price": 97.4 if side == "long" else 106.6, "score": 85, "magnet": True, "size": 1.0}
        s = scene(pools=[pool]) if side == "long" else scene(price=105.0, pools=[pool])
        i = [x for x in sg.build_ideas(s)[0] if x["side"] == side][0]
        i = sg.score_idea(i, self.ctx_for(s))
        i.update(price=s["price"], atrPct=1.0, validHours=48, sweepAgeH=None)
        probs = {"fill": {"p24": 0.7, "p72": 0.85}, "plan": {"n": 5000, "neff": 400, "tp": {"p": 0.35, "lo": 0.3, "hi": 0.4}},
                 "bounce": {"p": 0.58, "n": 120}, "baseBounce": {"p": 0.5, "n": 900}}
        d = sg.describe(i, probs, {"text": "Rejeu : mieux que le hasard."}, 10.0, "BTCUSDT")
        return i, d

    def test_message_follows_the_three_pillars_in_order(self):
        i, d = self.full("long")
        text = sg.to_text(i, d, 1, 3)
        order = ["QUOI FAIRE", "POURQUOI ICI", "Liquidités (les ordres d'arrêt", "Prix moyens (VWAP et VWAP ancrés)", "Autres niveaux au même endroit",
                 "CONTEXTE MACRO", "AUTRES CONTEXTES", "PROBABILITÉS", "PRUDENCE"]
        pos = [text.index(k) for k in order]
        self.assertEqual(pos, sorted(pos), dict(zip(order, pos)))
        self.assertIn("Lecture macro : risk-on", text)
        self.assertLess(len(text), 3900)

    def test_text_has_all_sections_and_no_abbreviations(self):
        for side in ("long", "short"):
            i, d = self.full(side)
            text = sg.to_text(i, d, 2, 3)
            for part in ("QUOI FAIRE", "POURQUOI ICI", "PROBABILITÉS", "PRUDENCE", "Stop", "Objectif 1", "Validité", "2/3"):
                self.assertIn(part, text)
            self.assertIsNone(BANNED.search(text), BANNED.search(text))
            self.assertLess(len(text), 3900)
            self.assertIn("ACHAT" if side == "long" else "VENTE", text)

    def test_leverage_warning_when_liquidation_comes_first(self):
        i, d = self.full("long")
        lines, info = sg.leverage_lines(i, 100.0)
        self.assertTrue(any("AVANT ton stop" in x for x in lines))
        lines2, info2 = sg.leverage_lines(i, 3.0)
        self.assertFalse(any("⚠" in x for x in lines2))
        self.assertGreater(info2["levMax"], 1)
        self.assertAlmostEqual(info2["marginLoss"], info2["stopPct"] * 3.0)

    def test_week_start_is_monday_midnight_utc(self):
        ws = sg.week_start(1_759_600_000_000)                       # samedi 4 octobre 2025
        self.assertEqual(ws, 1_759_104_000_000)                      # lundi 29 septembre 2025 00:00 UTC
        self.assertEqual(sg.week_start(ws), ws)
        self.assertEqual(sg.week_start(ws + 7 * 24 * H - 1), ws)
        self.assertEqual(sg.week_start(ws + 7 * 24 * H), ws + 7 * 24 * H)

    def test_formats(self):
        self.assertEqual(sg.fmt_price(84760.4), "84 760")
        self.assertEqual(sg.fmt_price(184.78), "184,78")
        self.assertEqual(sg.fmt_pct(0.5432), "0,54 %")
        self.assertEqual(sg.fmt_pct(-2.0, 1, True), "-2,0 %")


if __name__ == "__main__":
    unittest.main()


class TrendGateTests(unittest.TestCase):
    """Filtre de tendance de fond (moyennes 50 j / 200 j) : seul filtre valide par le backtest."""

    def idea(self, side="long"):
        return ScoreTests.idea(ScoreTests(), side=side)

    def ctx(self, regime, **kw):
        c = {"price": 100.0, "vwap": {"W": 99.0, "M": 98.0, "Y": 95.0}, "flow": (0.5, [(0.5, "achats agressifs")]), "macro": {"score": 40, "label": "risk-on"},
             "synth": {}, "dom": {}, "is_alt": False, "now": NOW, "regime": regime,
             "evidence": {"label": "BTC 2013-2026", "aligned": 0.15, "counter": -0.11, "n": 1303}}
        c.update(kw)
        return c

    @staticmethod
    def rg(code):
        return {"ready": True, "regime": code, "label": {1: "haussière", -1: "baissière", 0: "indécise"}[code], "price": 100.0, "fast": 98.0, "slow": 90.0,
                "distFast": 2.0, "distSlow": 11.0, "fastDays": 50, "slowDays": 200}

    def test_aligned_idea_passes_and_counter_trend_is_filtered(self):
        long_up = sg.score_idea(self.idea("long"), self.ctx(self.rg(1)))
        self.assertEqual(long_up["align"], 1)
        self.assertFalse(any("tendance" in g for g in long_up["gates"]))
        long_down = sg.score_idea(self.idea("long"), self.ctx(self.rg(-1)))
        self.assertEqual(long_down["align"], -1)
        self.assertTrue(any("contre la tendance de fond" in g for g in long_down["gates"]))
        self.assertIn("0,15", " ".join(long_down["gates"]))                 # les chiffres mesures sont cites
        short_down = sg.score_idea(self.idea("short"), self.ctx(self.rg(-1)))
        self.assertEqual(short_down["align"], 1)
        self.assertFalse(any("tendance" in g for g in short_down["gates"]))

    def test_undecided_trend_is_filtered_and_gate_can_be_turned_off(self):
        und = sg.score_idea(self.idea("long"), self.ctx(self.rg(0)))
        self.assertTrue(any("indécise" in g for g in und["gates"]))
        off = sg.score_idea(self.idea("long"), self.ctx(self.rg(-1)), {"trend_gate": False})
        self.assertFalse(any("tendance" in g for g in off["gates"]))
        self.assertEqual(off["align"], -1)                                  # l'information reste affichee

    def test_without_regime_the_old_trend_component_is_used(self):
        r = sg.score_idea(self.idea("long"), self.ctx(None))
        self.assertIsNone(r["align"])
        self.assertFalse(any("tendance" in g for g in r["gates"]))
        self.assertEqual(sum(c["max"] for c in r["comps"]), 100)

    def test_trend_component_points(self):
        pts = lambda code, side="long": [c for c in sg.score_idea(self.idea(side), self.ctx(self.rg(code)))["comps"] if c["key"] == "trend"][0]["pts"]
        self.assertEqual(pts(1), 7.0)
        self.assertEqual(pts(0), 3.5)
        self.assertEqual(pts(-1), 0.0)
        self.assertEqual(pts(-1, "short"), 7.0)

    def test_message_has_a_plain_trend_section(self):
        i = sg.score_idea(self.idea("long"), self.ctx(self.rg(1)))
        i.update(symbol="BTCUSDT", atr=1.0, atrPct=1.0, validHours=48, price=100.0)
        d = sg.describe(i, None, None, 10.0, "BTCUSDT")
        self.assertTrue(d["trend"])
        text = sg.to_text(i, d, 1, 5)
        self.assertIn("TENDANCE DE FOND", text)
        self.assertIn("DANS LE SENS", text)
        self.assertIn("BTC 2013-2026", text)
        self.assertIsNone(BANNED.search(text), BANNED.search(text))
        counter = sg.score_idea(self.idea("long"), self.ctx(self.rg(-1)))
        counter.update(symbol="BTCUSDT", atr=1.0, atrPct=1.0, validHours=48, price=100.0)
        self.assertIn("À CONTRE-COURANT", sg.to_text(counter, sg.describe(counter, None, None, 10.0, "BTCUSDT"), 1, 5))
