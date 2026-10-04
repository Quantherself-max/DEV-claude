import math, random, unittest

from data.external import ExternalHub, SimProviders, normalize_event
from engine import dominance, macro
from engine.atr import Candle

H = 3_600_000
M = 300_000
NOW = 1_790_000_000_000 - 1_790_000_000_000 % M


def c5(n, step_at=None, jump=0.01, px=100.0, seed=1, end=NOW):
    r = random.Random(seed)
    out, p = [], px
    for i in range(n):
        t = end - (n - i) * M
        if step_at is not None and t == step_at:
            p *= 1 + jump
        p *= 1 + r.gauss(0, 0.0004)
        out.append(Candle(t, p, p * 1.0005, p * 0.9995, p, 100.0, 50.0))
    return out


class ClassifyTests(unittest.TestCase):
    def test_rules(self):
        k = lambda t, c="USD": macro.classify(t, c)
        self.assertEqual((k("CPI m/m")["key"], k("CPI m/m")["sign"]), ("CPI", -1))
        self.assertEqual(k("Core CPI m/m")["key"], "CORE_CPI")                 # « core cpi » est teste avant « cpi »
        self.assertEqual(k("Non-Farm Employment Change")["key"], "NFP")
        self.assertEqual((k("Unemployment Claims")["key"], k("Unemployment Claims")["sign"]), ("CLAIMS", 1))   # + de chomage = accommodant
        self.assertEqual(k("Federal Funds Rate")["key"], "FOMC")
        self.assertEqual(k("FOMC Statement")["key"], "FOMC")
        self.assertEqual(k("FOMC Press Conference")["key"], "FOMC_PC")
        self.assertEqual(k("Crude Oil Inventories")["key"], "OTHER")
        self.assertLess(k("CPI y/y", "EUR")["w"], k("CPI y/y", "USD")["w"])     # hors US : effet indirect

    def test_expectation_text(self):
        ev = normalize_event({"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"})
        ex = macro.expectation(ev, macro.classify("CPI m/m"))
        self.assertEqual(ex["dir"], 1)
        self.assertIn("hausse attendue", ex["text"])
        self.assertIn("restrictif", ex["scen_up"])
        cl = macro.expectation({**ev, "title": "Unemployment Claims", "forecast": "230K", "previous": "227K", "fnum": 230.0, "pnum": 227.0}, macro.classify("Unemployment Claims"))
        self.assertIn("accommodant", cl["scen_up"])                               # plus de chomeurs = accommodant


class ReactionTests(unittest.TestCase):
    def test_crypto_reaction_measures_the_jump(self):
        t_ev = NOW - 3 * H
        c = c5(600, step_at=t_ev + 2 * M, jump=0.012)                             # +1,2 % deux bougies apres l'annonce
        r = macro.crypto_reaction(c, t_ev)
        self.assertGreater(r["r15"], 0.8)
        self.assertLess(r["r15"], 1.6)
        self.assertGreater(r["rng"], 0.5)
        flat = macro.crypto_reaction(c5(600, seed=2), t_ev)
        self.assertLess(abs(flat["r15"]), 0.4)
        self.assertIsNone(macro.crypto_reaction([], t_ev))

    def test_cross_reaction_and_impulse(self):
        t_ev = NOW - 3 * H
        mk = lambda v0, v1: [(t_ev - 600_000, v0), (t_ev - 1000, v0), (t_ev + 600_000, v1), (t_ev + 4_200_000, v1)]
        cr = macro.cross_reaction({"US10Y": mk(4.20, 4.26), "DXY": mk(104.0, 104.25)}, t_ev)
        self.assertAlmostEqual(cr["US10Y"], 6.0, places=6)                         # +6 points de base
        self.assertAlmostEqual(cr["DXY"], 0.2404, places=3)
        self.assertGreater(macro.impulse(cr), 1.6)
        self.assertEqual(macro.impulse_label(macro.impulse(cr)), "restrictive forte")
        dov = macro.cross_reaction({"US10Y": mk(4.20, 4.17), "DXY": mk(104.0, 103.9)}, t_ev)
        self.assertLess(macro.impulse(dov), -0.6)
        self.assertEqual(macro.impulse_label(0.2), "neutre (déjà dans les prix)")
        self.assertEqual(macro.cross_reaction({}, t_ev), {})
        self.assertIsNone(macro.impulse({}))


class TrendTests(unittest.TestCase):
    def daily(self, drift, seed, n=140, base=100.0, vol=0.006):
        r = random.Random(seed)
        out, p = [], base
        for i in range(n):
            p *= 1 + drift * (1 if i >= n - 6 else 0) + r.gauss(0, vol)
            out.append((NOW - (n - i) * 86_400_000, p))
        return out

    def test_unusual_move_gets_signed_score(self):
        btc = [(t, 100 * math.exp(0.0 * i)) for i, (t, _) in enumerate(self.daily(0, 1))]
        crossD = {"NDX": self.daily(0.012, 2), "DXY": self.daily(-0.003, 3), "VIX": self.daily(0.0, 4)}
        tr = macro.asset_trends({}, crossD, btc)
        self.assertGreater(tr["NDX"]["z"], 1.0)                                    # hausse inhabituelle du Nasdaq
        score, parts = macro.risk_score(tr)
        self.assertGreater(score, 0)                                               # Nasdaq fort + dollar faible = risk-on
        crossD["NDX"] = self.daily(-0.012, 2)
        crossD["DXY"] = self.daily(0.004, 3)
        score2, _ = macro.risk_score(macro.asset_trends({}, crossD, btc))
        self.assertLess(score2, 0)
        self.assertGreaterEqual(min(score, score2), -100.0)


class AnalyseTests(unittest.TestCase):
    def snap(self):
        hub = ExternalHub(SimProviders(lambda: NOW), lambda: NOW)
        hub.refresh(force=True)
        return hub.snapshot()

    def test_full_analysis_on_simulated_data(self):
        snap = self.snap()
        c = c5(288 * 6)
        btc_daily = [(NOW - (130 - i) * 86_400_000, 100 + i) for i in range(130)]
        st, new = macro.analyse(NOW, snap, c, c, "BTCUSDT", btc_daily)
        self.assertTrue(st["hasCalendar"])
        self.assertEqual(st["risk"]["level"], "attention")                         # PCE core dans 3 h : sous 12 h = attention (danger = sous 90 min)
        self.assertTrue(st["upcoming"] and st["past"])
        past_ids = {e["id"] for e in st["past"]}
        self.assertTrue(set(new) <= past_ids)                                      # reactions mesurees uniquement pour le passe
        self.assertTrue(new)
        for e in st["upcoming"]:
            self.assertGreater(e["t"], NOW)
            self.assertIn("exp", e)
        self.assertTrue(st["lines"])
        self.assertTrue(all("text" in l and "tone" in l for l in st["lines"]))
        self.assertIn(st["label"], ("risk-on", "risk-off", "neutre"))
        # idempotence : une reaction deja archivee n'est pas recalculee
        for k, v in new.items():
            snap["calendar"][k]["reaction"] = v
        st2, new2 = macro.analyse(NOW, snap, c, c, "BTCUSDT", btc_daily)
        self.assertEqual(new2, {})

    def test_danger_level_inside_90_minutes(self):
        ev = normalize_event({"title": "CPI m/m", "country": "USD", "date": "2026-01-01T00:00:00+00:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"})
        ev["t"] = NOW + 45 * 60_000
        snap = {"calendar": {ev["id"]: ev}, "cross5": {}, "crossD": {}, "fng": [], "errors": {}}
        st, _ = macro.analyse(NOW, snap, [], [], "BTCUSDT", [])
        self.assertEqual(st["risk"]["level"], "danger")
        self.assertIn("levier", st["lines"][0]["text"])
        self.assertEqual(st["discount"], 0.5)

    def test_without_any_data_it_degrades_quietly(self):
        st, new = macro.analyse(NOW, {"calendar": {}, "cross5": {}, "crossD": {}, "fng": [], "errors": {"calendar": "x"}}, [], [], "SOLUSDT", [])
        self.assertFalse(st["hasCalendar"])
        self.assertIsNone(st["score"])
        self.assertEqual(new, {})
        self.assertIn("indisponible", st["lines"][0]["text"])


class DominanceTests(unittest.TestCase):
    def pairs(self, alt_drift, n=720, seed=1, step=H, vol=0.004):
        r = random.Random(seed)
        out = {}
        for j, p in enumerate(("ETHBTC", "SOLBTC", "BNBBTC", "XRPBTC", "ADABTC", "DOGEBTC", "AVAXBTC", "LINKBTC")):
            v, s = 0.02, []
            for i in range(n):
                v *= math.exp(alt_drift + r.gauss(0, vol))
                s.append((NOW - (n - i) * step, v))
            out[p] = s
        return out

    def test_basket_direction_and_regimes(self):
        up = dominance._align(self.pairs(0.001))
        dn = dominance._align(self.pairs(-0.001))
        self.assertGreater(up[-1][1], 130)
        self.assertLess(dn[-1][1], 80)
        self.assertEqual(up[0][1], 100.0)
        btc = [type("K", (), {"t": NOW - (800 - i) * H, "c": 100.0 + 0.05 * i})() for i in range(800)]
        snap = {"alt": self.pairs(0.001), "altD": {}, "cg": {"btc_d": 58.0, "eth_d": 12.0, "total": 3e12, "chg24": 1.0, "src": "t", "t": NOW},
                "cg_hist": [(NOW - 7 * 86_400_000, 56.0, 3e12), (NOW - 25 * H, 57.5, 3e12), (NOW, 58.0, 3e12)], "errors": {}}
        o = dominance.analyse(snap, btc, btc, "SOLUSDT")
        self.assertEqual(o["regime"]["key"], "up|up")                              # BTC monte, panier monte
        self.assertAlmostEqual(o["cg"]["d24"], 0.5, places=6)
        self.assertAlmostEqual(o["cg"]["d7"], 2.0, places=6)
        snap["alt"] = self.pairs(-0.001)
        self.assertEqual(dominance.analyse(snap, btc, btc, "SOLUSDT")["regime"]["key"], "up|dn")   # saison BTC

    def test_beta_recovers_leverage_to_btc(self):
        r = random.Random(5)
        px, py, b, s = 100.0, 20.0, [], []
        for i in range(800):
            x = r.gauss(0, 0.004)
            px *= math.exp(x); py *= math.exp(1.5 * x + r.gauss(0, 0.002))
            b.append(type("K", (), {"t": i * H, "c": px})())
            s.append(type("K", (), {"t": i * H, "c": py})())
        o = dominance.beta(s, b)
        self.assertAlmostEqual(o["beta"], 1.5, delta=0.1)
        self.assertGreater(o["corr"], 0.85)

    def test_regime_stats_detect_planted_persistence(self):
        def daily(persist, seed):
            r = random.Random(seed)
            n, out = 900, {}
            mom = 0.0
            ix = [1.0]
            for i in range(n):
                mom = persist * mom + r.gauss(0, 0.02)
                ix.append(ix[-1] * math.exp(mom * 0.5))
            btc = [(NOW - (n - i) * 86_400_000, 50000 * math.exp(0.001 * i + r.gauss(0, 0.01))) for i in range(n)]
            alts = {}
            for p in ("ETHBTC", "SOLBTC", "BNBBTC", "XRPBTC", "ADABTC", "DOGEBTC", "AVAXBTC", "LINKBTC"):
                alts[p] = [(NOW - (n - i) * 86_400_000, 0.02 * ix[i] * math.exp(r.gauss(0, 0.002))) for i in range(n)]
            alts["BTCUSDT"] = btc
            return alts
        persistent = dominance.regime_stats(daily(0.85, 1))
        random_ = dominance.regime_stats(daily(0.0, 2))
        def spread(rs):
            vals = [v["p1"] for v in rs["table"].values() if v["n"] > 40]
            return max(vals) - min(vals)
        self.assertGreater(spread(persistent), spread(random_) + 0.1)               # la persistance plantee ressort
        self.assertTrue(random_["table"])


if __name__ == "__main__":
    unittest.main()
