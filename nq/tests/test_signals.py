"""Tests du moteur de setups (engine/signals.py) et du backtest (engine/backtest.py)."""
import unittest
from datetime import datetime, timezone

from data.simulated import SimulatedSource
from engine import backtest, clock, montecarlo, risk, signals, vp
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
            self.assertIn(t["reason"], ("stop", "objectif", "16h45", "temps", "fin"))

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


def tape_of(bars, tops):
    """Tape synthétique : `tops[i]` = meilleur setup décidé à la clôture de la barre i (ou None)."""
    rows = []
    for b, top in zip(bars, tops):
        now = b.t + 60_000
        day = clock.trading_day(now)
        rows.append((now, day, clock.forced_flat(day), True, False, top))
    return backtest.Tape("1m", 60_000, bars, rows)


class SimulateMechanicsTests(unittest.TestCase):
    T0 = utc(2026, 10, 13, 14, 0)        # 10 h ET, mardi

    def bars(self, spec):
        """spec : liste de (o, h, l, c)."""
        return [mkbar(self.T0 + i * 60_000, o, h, l, c, 5, 5) for i, (o, h, l, c) in enumerate(spec)]

    def long_setup(self, stop, target, score=80.0):
        return {"side": "long", "kind": "reversal", "score": score, "stop": stop, "targets": [target]}

    def test_stop_hit_inside_the_entry_bar_is_seen(self):
        # décision à la clôture de la barre 0, entrée à l'ouverture de la barre 1 (100), qui descend aussitôt sous le stop (97)
        bars = self.bars([(100, 100, 99, 100), (100, 101, 94, 96), (96, 120, 96, 119)])
        r = backtest.simulate(tape_of(bars, [self.long_setup(97.0, 110.0), None, None]), NQ, risk.PropProfile(),
                              backtest.BtParams(min_score=10, slippage_ticks=0))
        self.assertEqual(r["nTrades"], 1)
        t = r["trades"][0]
        self.assertEqual(t["reason"], "stop")
        self.assertTrue(t["sameBar"])
        self.assertLess(t["net"], 0)

    def test_target_must_trade_through_to_fill(self):
        # l'objectif (110) est seulement TOUCHÉ : pas rempli avec 1 tick de dépassement exigé, rempli si on accepte le simple contact
        bars = self.bars([(100, 100, 99, 100), (100, 110, 99.5, 105), (105, 106, 104, 105)])
        tape = tape_of(bars, [self.long_setup(97.0, 110.0), None, None])
        strict = backtest.simulate(tape, NQ, risk.PropProfile(), backtest.BtParams(min_score=10, slippage_ticks=0, limit_through_ticks=1))
        touch = backtest.simulate(tape, NQ, risk.PropProfile(), backtest.BtParams(min_score=10, slippage_ticks=0, limit_through_ticks=0))
        self.assertNotEqual(strict["trades"][0]["reason"], "objectif")
        self.assertEqual(touch["trades"][0]["reason"], "objectif")

    def test_gap_through_stop_fills_at_the_open(self):
        bars = self.bars([(100, 100, 99, 100), (100, 101, 99, 100), (90, 91, 89, 90)])
        r = backtest.simulate(tape_of(bars, [self.long_setup(97.0, 110.0), None, None]), NQ, risk.PropProfile(),
                              backtest.BtParams(min_score=10, slippage_ticks=0))
        self.assertEqual(r["trades"][0]["reason"], "stop")
        self.assertEqual(r["trades"][0]["exit"], 90.0)           # l'ouverture, pas le stop à 97

    def test_open_beyond_stop_skips_the_entry(self):
        bars = self.bars([(100, 100, 99, 100), (94, 95, 93, 94), (94, 95, 93, 94)])
        r = backtest.simulate(tape_of(bars, [self.long_setup(97.0, 110.0), None, None]), NQ, risk.PropProfile(),
                              backtest.BtParams(min_score=10, slippage_ticks=0))
        self.assertEqual(r["nTrades"], 0)

    def test_min_score_filters_from_the_same_tape(self):
        bars = self.bars([(100, 100, 99, 100), (100, 112, 99.5, 111), (111, 112, 110, 111)])
        tape = tape_of(bars, [self.long_setup(97.0, 110.0, score=50.0), None, None])
        self.assertEqual(backtest.simulate(tape, NQ, risk.PropProfile(), backtest.BtParams(min_score=40))["nTrades"], 1)
        self.assertEqual(backtest.simulate(tape, NQ, risk.PropProfile(), backtest.BtParams(min_score=60))["nTrades"], 0)

    def test_open_position_is_closed_at_the_end(self):
        bars = self.bars([(100, 100, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100)])
        r = backtest.simulate(tape_of(bars, [self.long_setup(97.0, 110.0), None, None]), NQ, risk.PropProfile(),
                              backtest.BtParams(min_score=10, slippage_ticks=0))
        self.assertEqual(r["trades"][-1]["reason"], "fin")


    def test_data_gap_past_1645_closes_on_the_positions_own_day(self):
        # barres jusqu'à 16 h 29 ET, puis plus rien avant la séance suivante (18 h ET) : la position est close à 16 h 45, jamais sur la suite
        t0 = utc(2026, 10, 13, 20, 0)                     # 16 h ET
        spec = [mkbar(t0 + k * 60_000, 100, 100.5, 99.5, 100, 5, 5) for k in range(30)]
        t1 = utc(2026, 10, 13, 22, 0)                     # 18 h ET : journée suivante
        spec += [mkbar(t1 + k * 60_000, 125, 126, 124, 125, 5, 5) for k in range(5)]
        tops = [None] * len(spec)
        tops[0] = self.long_setup(97.0, 110.0)
        r = backtest.simulate(tape_of(spec, tops), NQ, risk.PropProfile(),
                              backtest.BtParams(min_score=10, slippage_ticks=0, max_hold_min=600,
                                                signal_params=signals.Params(flat_guard_min=0)))
        t = r["trades"][0]
        self.assertEqual(t["reason"], "16h45")
        self.assertEqual(t["exit"], 100.0)
        self.assertLess(t["t_exit"], t1)

    def test_no_entry_whose_bar_straddles_the_forced_flat(self):
        # 30 min : décision à 16 h, entrée 16 h 00 -> barre jusqu'à 16 h 30 > 16 h 45 - 12 min : refusée
        t0 = utc(2026, 10, 13, 19, 30)
        bars = [mkbar(t0 + k * 1_800_000, 100, 101, 99, 100, 5, 5) for k in range(3)]
        rows = []
        for b, top in zip(bars, [None, self.long_setup(97.0, 110.0), None]):
            now = b.t + 1_800_000
            day = clock.trading_day(now)
            rows.append((now, day, clock.forced_flat(day), True, False, top))
        r = backtest.simulate(backtest.Tape("30m", 1_800_000, bars, rows), NQ, risk.PropProfile(), backtest.BtParams(min_score=10))
        self.assertEqual(r["nTrades"], 0)

    def test_micro_contract_cap_uses_max_micros(self):
        from engine.instruments import MNQ
        self.assertGreater(backtest._size(2.0, MNQ, risk.PropProfile(), 100.0), risk.PropProfile().max_minis)


class SummaryRulesTests(unittest.TestCase):
    def trade(self, day, net, t):
        return {"day": day, "net": net, "fee": 0.0, "holdS": 60.0, "kind": "reversal", "reason": "stop", "t_exit": t}

    def test_intraday_breach_from_the_realized_low(self):
        # journée qui finit à -200 mais a été à -1 050 en cours de séance : le plancher (24 000) est touché
        tr = [self.trade("2026-10-13", -1050, 1), self.trade("2026-10-13", 850, 2)]
        r = backtest._summary(tr, NQ, risk.PropProfile())
        self.assertTrue(r["rules"]["floorBreach"])
        self.assertTrue(r["rules"]["floorBreach"]["intraday"])

    def test_static_floor_does_not_trail(self):
        prof = risk.PropProfile.from_dict({**risk.PropProfile().to_dict(), "dd_mode": "static"})
        tr = [self.trade("2026-10-13", 900, 1), self.trade("2026-10-14", -1000, 2)]
        self.assertIsNone(backtest._summary(tr, NQ, prof)["rules"]["floorBreach"])          # 25 900 - 1 000 = 24 900 > 24 000
        self.assertTrue(backtest._summary(tr, NQ, risk.PropProfile())["rules"]["floorBreach"])   # suiveur : plancher monté à 25 100

    def test_no_breach_after_the_evaluation_has_passed(self):
        tr = [self.trade(f"2026-10-{13 + i}", 450, i) for i in range(3)] + [self.trade("2026-10-16", -1500, 9)]
        r = backtest._summary(tr, NQ, risk.PropProfile())
        self.assertTrue(r["rules"]["evalPassed"])
        self.assertIsNone(r["rules"]["floorBreach"])

    def test_passed_on_is_the_first_qualifying_day(self):
        tr = [self.trade(f"2026-10-{13 + i}", 450, i) for i in range(4)]
        r = backtest._summary(tr, NQ, risk.PropProfile())
        self.assertEqual(r["rules"]["passedOn"], "2026-10-15")              # 1 350 $ après 3 jours, meilleur jour 33 %
        self.assertTrue(r["rules"]["evalPassed"])


class MonteCarloTests(unittest.TestCase):
    def test_always_winning_days_always_pass(self):
        mc = montecarlo.simulate_eval([(300.0, 0.0)], risk.PropProfile(), n_paths=200)
        self.assertEqual(mc["pPass"], 1.0)
        self.assertEqual(mc["daysToPass"]["median"], 5)                 # 5 × 300 = 1 500 ≥ 1 250, chaque jour à 20 %

    def test_always_losing_days_always_breach(self):
        mc = montecarlo.simulate_eval([(-300.0, -300.0)], risk.PropProfile(), n_paths=200)
        self.assertEqual(mc["pBreach"], 1.0)

    def test_consistency_delays_validation(self):
        # un jour à +1 300 puis des jours à +100 : la cible est atteinte tout de suite mais la consistance 50 % impose d'attendre 2 600 $
        mc = montecarlo.simulate_eval([(1300.0, 0.0), (100.0, 0.0)], risk.PropProfile(), n_paths=500, horizon=200)
        self.assertGreater(mc["consistencyDelayed"], 0.0)

    def test_intraday_low_can_breach(self):
        mc = montecarlo.simulate_eval([(100.0, -1200.0)], risk.PropProfile(), n_paths=50)
        self.assertEqual(mc["pBreach"], 1.0)

    def test_deterministic_and_cost_per_pass(self):
        s = [(400.0, -100.0), (-250.0, -300.0), (0.0, 0.0)]
        a = montecarlo.simulate_eval(s, risk.PropProfile(), eval_fee=100.0)
        b = montecarlo.simulate_eval(s, risk.PropProfile(), eval_fee=100.0)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["pPass"] + a["pBreach"] + a["pTimeout"], 1.0, places=2)
        if a["pPass"]:
            self.assertAlmostEqual(a["costPerPass"], round(100.0 / a["pPass"], 2), delta=1.0)


class SweepTests(unittest.TestCase):
    def test_sweep_splits_in_and_out_of_sample(self):
        now = utc(2026, 10, 12, 20, 0)
        mk = Market(NQ)
        mk.ingest_many(SimulatedSource(days=3, now_fn=lambda: now).history(now))
        tape = backtest.prepare(mk.series.bars, NQ)
        r = backtest.sweep(tape, NQ, risk.PropProfile(), scores=(30, 60), slippages=(1, 2))
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["grid"]), 4)
        for g in r["grid"]:
            self.assertEqual(g["inN"] + g["outN"], g["nTrades"])
        self.assertGreaterEqual(r["outDays"], 1)


if __name__ == "__main__":
    unittest.main()
