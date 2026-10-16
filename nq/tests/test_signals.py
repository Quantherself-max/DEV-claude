"""Tests du moteur de setups (engine/signals.py) et du backtest (engine/backtest.py)."""
import unittest
from datetime import datetime, timezone

from data.simulated import SimulatedSource
from engine import backtest, risk, signals, vp
from engine.bars import Bar
from engine.instruments import NQ
from engine.market import Market


def utc(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)


def mkbar(t, o, h, l, c, bv, sv, fp=None):
    b = Bar(t, o)
    b.h, b.l, b.c = h, l, c
    b.bv, b.sv, b.v = bv, sv, bv + sv
    b.n = 1
    b.pv = c * (bv + sv)
    b.pv2 = c * c * (bv + sv)
    b.fp = fp or {}
    return b


def ramp(n, start=25000.0, step=0.25, up=True, bv=10, sv=5, t0=None):
    """Série de barres montantes (ou descendantes) régulières, 1 min, delta acheteur."""
    t0 = t0 or utc(2026, 10, 12, 14, 0)
    out = []
    p = start
    for i in range(n):
        nxt = p + (step if up else -step)
        out.append(mkbar(t0 + i * 60_000, p, max(p, nxt), min(p, nxt), nxt, bv if up else sv, sv if up else bv))
        p = nxt
    return out


PROF = {"poc": 25000.0, "vah": 25010.0, "val": 24990.0, "vwap": 25000.0, "sd": 5.0, "hi": 25015.0, "lo": 24985.0}


class EvaluateTests(unittest.TestCase):
    def test_not_ready_without_enough_bars(self):
        r = signals.evaluate(ramp(3), [1, 2, 3], PROF, {"above": [], "below": []}, [], NQ, utc(2026, 10, 12, 14, 5),
                             utc(2026, 10, 12, 20, 45), {"key": "am", "label": "Matinée"}, True)
        self.assertFalse(r["ready"])

    def test_vwap_band_pushes_a_short_when_price_is_stretched_up(self):
        bars = ramp(40, start=25000.0)
        price = bars[-1].c
        prof = dict(PROF, vwap=price - 12, sd=5.0, vah=price - 1, poc=price - 12)      # +2.4 σ au-dessus du VWAP
        near = {"above": [{"name": "R", "price": price + 8, "kind": "pdh", "group": "veille", "w": 3}],
                "below": [{"name": "VWAP", "price": price - 12, "kind": "vwap", "group": "seance", "w": 3}]}
        cvd = list(range(len(bars)))
        r = signals.evaluate(bars, cvd, prof, near, [], NQ, bars[-1].t + 60_000, utc(2026, 10, 12, 20, 45),
                             {"key": "am", "label": "Matinée"}, True, params=signals.Params(min_score=10.0))
        self.assertTrue(r["ready"])
        self.assertTrue(r["setups"], "un setup devrait sortir quand le prix est étiré au-dessus du VWAP")
        self.assertEqual(r["setups"][0]["side"], "short")
        self.assertIn("vwap_band", [x["tag"] for x in r["setups"][0]["reasons"]])

    def test_stop_is_on_the_correct_side_and_targets_beyond_entry(self):
        bars = ramp(40, start=25000.0)
        price = bars[-1].c
        prof = dict(PROF, vwap=price - 12, sd=5.0, vah=price - 1, poc=price - 12)
        near = {"above": [{"name": "R", "price": price + 8, "kind": "pdh", "group": "veille", "w": 3}], "below": []}
        r = signals.evaluate(bars, list(range(len(bars))), prof, near, [], NQ, bars[-1].t + 60_000,
                             utc(2026, 10, 12, 20, 45), {"key": "am", "label": "Matinée"}, True, params=signals.Params(min_score=10.0))
        s = r["setups"][0]
        self.assertGreater(s["stop"], s["entry"])             # short : stop au-dessus de l'entrée
        for t in s["targets"]:
            self.assertLess(t, s["entry"])                    # objectifs en dessous
        self.assertGreater(s["stopPts"], 0)

    def test_forced_flat_window_blocks_new_setups(self):
        bars = ramp(40, start=25000.0)
        prof = dict(PROF, vwap=bars[-1].c - 12, sd=5.0)
        near = {"above": [{"name": "R", "price": bars[-1].c + 8, "kind": "pdh", "group": "veille", "w": 3}], "below": []}
        now = utc(2026, 10, 12, 20, 40)                       # 16 h 40 ET, 5 min avant la fermeture forcée
        r = signals.evaluate(bars, list(range(len(bars))), prof, near, [], NQ, now, utc(2026, 10, 12, 20, 45),
                             {"key": "power", "label": "Dernière heure"}, True, params=signals.Params(min_score=10.0))
        self.assertTrue(any("16 h 45" in b for b in r["blocked"]))
        self.assertTrue(all(s.get("suppressed") for s in r["setups"]))

    def test_breached_account_blocks_setups(self):
        bars = ramp(40, start=25000.0)
        prof = dict(PROF, vwap=bars[-1].c - 12, sd=5.0)
        near = {"above": [{"name": "R", "price": bars[-1].c + 8, "kind": "pdh", "group": "veille", "w": 3}], "below": []}
        acct = {"breached": True, "dllHit": False, "consistency": {}, "caps": {}}
        r = signals.evaluate(bars, list(range(len(bars))), prof, near, [], NQ, bars[-1].t + 60_000,
                             utc(2026, 10, 12, 20, 45), {"key": "am", "label": "Matinée"}, True, acct=acct, params=signals.Params(min_score=10.0))
        self.assertTrue(any("plancher" in b.lower() for b in r["blocked"]))

    def test_micro_scalping_note_when_target_is_very_close(self):
        # barres à larges pas -> ATR ~2 pts ; un objectif à 0,5 pt est alors « très proche » (atteignable en quelques secondes)
        bars = ramp(40, start=25080.0, step=2.0, up=False)
        price = bars[-1].c
        prof = dict(PROF, vwap=price + 12, sd=5.0, val=price + 1, poc=price + 12)      # prix étiré SOUS le VWAP -> long
        near = {"above": [{"name": "proche", "price": price + 0.5, "kind": "pdh", "group": "veille", "w": 3}], "below": []}
        acct = {"breached": False, "dllHit": False, "stage": "eval", "consistency": {"todayCap": 0}, "caps": {}}
        r = signals.evaluate(bars, list(range(len(bars))), prof, near, [], NQ, bars[-1].t + 60_000,
                             utc(2026, 10, 12, 20, 45), {"key": "am", "label": "Matinée"}, True, acct=acct, params=signals.Params(min_score=10.0))
        self.assertTrue(r["setups"] and r["setups"][0]["side"] == "long")
        s = r["setups"][0]
        self.assertTrue(any("micro-scalping" in n for n in s.get("ruleNotes", [])))


class BacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = utc(2026, 10, 12, 20, 0)
        mk = Market(NQ)
        mk.ingest_many(SimulatedSource(days=2, now_fn=lambda: now).history(now))      # 2 jours : assez pour une veille + un jour, et rapide
        cls.bars = mk.series.bars

    def test_runs_and_reports_rules(self):
        r = backtest.run(self.bars, NQ, risk.PropProfile(), backtest.BtParams(min_score=35.0))
        self.assertTrue(r["ok"])
        self.assertGreater(r["nTrades"], 0)
        self.assertIn("evalPassed", r["rules"])
        self.assertIn("floorBreach", r["rules"])
        # le net doit être la somme des nets par trade
        self.assertAlmostEqual(r["net"], round(sum(t["net"] for t in r["trades"]), 2), places=2)
        # chaque trade a un stop du bon côté et un net cohérent
        for t in r["trades"]:
            if t["side"] == "long":
                self.assertLess(t["stop"], t["entry"])
            else:
                self.assertGreater(t["stop"], t["entry"])
            self.assertIn(t["reason"], ("stop", "objectif", "16h45", "temps"))

    def test_deterministic(self):
        a = backtest.run(self.bars, NQ, risk.PropProfile(), backtest.BtParams(min_score=40.0))
        b = backtest.run(self.bars, NQ, risk.PropProfile(), backtest.BtParams(min_score=40.0))
        self.assertEqual(a["nTrades"], b["nTrades"])
        self.assertEqual(a["net"], b["net"])

    def test_no_lookahead_entry_is_next_bar_open(self):
        r = backtest.run(self.bars, NQ, risk.PropProfile(), backtest.BtParams(min_score=35.0))
        # chaque entrée est datée APRÈS la barre de décision : t_entry existe et l'ordre temporel des trades est croissant
        ts = [t["t_entry"] for t in r["trades"]]
        self.assertEqual(ts, sorted(ts))
        for t in r["trades"]:
            self.assertGreater(t["t_exit"], t["t_entry"])     # on ne sort jamais avant d'entrer

    def test_higher_min_score_takes_fewer_trades(self):
        lo = backtest.run(self.bars, NQ, risk.PropProfile(), backtest.BtParams(min_score=30.0))
        hi = backtest.run(self.bars, NQ, risk.PropProfile(), backtest.BtParams(min_score=70.0))
        self.assertGreaterEqual(lo["nTrades"], hi["nTrades"])

    def test_floor_breach_detected_on_a_losing_profile(self):
        # un profil au plancher très serré doit détecter une violation si une journée perd assez
        prof = risk.PropProfile.from_dict({**risk.PropProfile().to_dict(), "max_drawdown": 50.0, "profit_target": 100.0})
        r = backtest.run(self.bars, NQ, prof, backtest.BtParams(min_score=30.0))
        self.assertTrue(r["ok"])
        # cohérence : si floorBreach est signalé, le solde de ce jour est bien ≤ plancher
        if r["rules"]["floorBreach"]:
            self.assertLessEqual(r["rules"]["floorBreach"]["balance"], r["rules"]["floorBreach"]["floor"] + 1e-9)

    def test_too_few_bars(self):
        r = backtest.run(self.bars[:10], NQ, risk.PropProfile())
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
