import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from engine import risk
from engine.account import Account, AccountError

P = risk.PropProfile()


def utc(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)


class TrailingFloorTests(unittest.TestCase):
    def test_start(self):
        r = risk.trailing_floor([], P)
        self.assertEqual((r["floor"], r["peak"], r["locked"]), (24_000, 25_000, False))

    def test_floor_follows_best_eod_balance_and_never_drops(self):
        self.assertEqual(risk.trailing_floor([500], P)["floor"], 24_500)
        r = risk.trailing_floor([500, -200], P)
        self.assertEqual((r["floor"], r["peak"], r["balance"]), (24_500, 25_500, 25_300))
        self.assertEqual(risk.trailing_floor([-300], P)["floor"], 24_000)        # une perte ne baisse pas le plancher

    def test_floor_locks_at_start_plus_100(self):
        r = risk.trailing_floor([1_200], P)                                       # meilleur solde 26 200 -> 25 200, plafonne a 25 100
        self.assertEqual((r["floor"], r["locked"]), (25_100, True))
        r = risk.trailing_floor([1_200, -800, 300], P)
        self.assertEqual(r["floor"], 25_100)                                      # il ne monte plus, il ne descend pas
        self.assertEqual(risk.trailing_floor([1_100], P)["floor"], 25_100)        # pile au verrou
        self.assertFalse(risk.trailing_floor([1_050], P)["locked"])               # 26 050 - 1 000 = 25 050 : pas encore verrouille

    def test_static_mode_and_no_lock(self):
        s = risk.PropProfile.from_dict({"dd_mode": "static"})
        self.assertEqual(risk.trailing_floor([800, 800], s)["floor"], 24_000)
        nl = risk.PropProfile.from_dict({"lock_offset": None})
        self.assertEqual(risk.trailing_floor([1_500], nl)["floor"], 25_500)       # sans verrou le plancher continue de monter


class ConsistencyTests(unittest.TestCase):
    def test_ok_and_cap(self):
        c = risk.consistency([400, 300, 350], P)
        self.assertTrue(c["ok"])
        self.assertAlmostEqual(c["ratio"], 400 / 1050)
        self.assertEqual(c["needed"], 1_250)
        self.assertAlmostEqual(c["dayCap"], 1_050)                               # a 50 % : on peut gagner autant que ce qu'on a deja

    def test_best_day_too_big_raises_requirement(self):
        c = risk.consistency([700, 600], P)
        self.assertFalse(c["ok"])
        self.assertEqual(c["needed"], 1_400)                                     # 700 / 0.5 : plus que la cible de 1 250

    def test_edges(self):
        self.assertFalse(risk.consistency([], P)["ok"])
        self.assertFalse(risk.consistency([-100, -50], P)["ok"])
        full = risk.PropProfile.from_dict({"consistency_pct": 100})
        self.assertTrue(risk.consistency([100], full)["ok"])
        self.assertIsNone(risk.consistency([100], full)["dayCap"])                   # a 100 % la regle ne plafonne rien
        self.assertFalse(risk.consistency([100, -50], full)["ok"])                   # meilleur jour (100) > profit total (50)
        off = risk.consistency([900], risk.PropProfile.from_dict({"consistency_pct": None}))
        self.assertTrue(off["ok"])
        self.assertFalse(off["rule"])
        self.assertAlmostEqual(risk.consistency([300, 300], risk.PropProfile.from_dict({"consistency_pct": 30}))["dayCap"], 600 * 0.3 / 0.7)


class StateTests(unittest.TestCase):
    def days(self, *v):
        return [(f"2026-10-0{i + 5}", x) for i, x in enumerate(v)]

    def test_passed(self):
        s = risk.state(self.days(600, 400, 300), 0, 0, P)
        self.assertTrue(s["passed"])
        self.assertEqual(s["status"], "passed")
        self.assertEqual(s["targetLeft"], 0)
        self.assertEqual(s["bestDay"], 600)
        self.assertEqual(s["floor"], 25_100)

    def test_target_hit_but_inconsistent(self):
        s = risk.state(self.days(700, 600), 0, 0, P)
        self.assertTrue(s["targetHit"])
        self.assertFalse(s["passed"])
        self.assertEqual(s["consistency"]["needed"], 1_400)
        self.assertEqual(s["status"], "ok")

    def test_today_cap_uses_closed_days_only(self):
        s = risk.state(self.days(400, 300), 250, 0, P)             # total termine 700 : aujourd'hui on peut gagner jusqu'a 700 sans que la journee depasse 50 %
        self.assertAlmostEqual(s["consistency"]["todayCap"], 700)
        self.assertAlmostEqual(s["consistency"]["dayCap"], 950)    # (celui-ci inclut aujourd'hui : c'est le plafond d'une journee SUPPLEMENTAIRE)
        self.assertEqual(risk.state([], 100, 0, P)["consistency"]["todayCap"], 0)     # premier jour : tout gain depasse 50 % du total

    def test_min_days(self):
        p = risk.PropProfile.from_dict({"min_trading_days": 2, "consistency_pct": None})     # consistance coupee : seul le nombre de jours joue
        one = risk.state(self.days(1_300), 0, 0, p)
        self.assertTrue(one["targetHit"])
        self.assertFalse(one["enoughDays"])
        self.assertFalse(one["passed"])
        self.assertTrue(risk.state(self.days(600, 700), 0, 0, p)["passed"])
        self.assertTrue(risk.state(self.days(1_300), 0, 0, P)["passed"] is False)           # (ici c'est la consistance qui bloque : 100 % en un jour)

    def test_breach_and_danger_use_equity(self):
        s = risk.state([], -900, -100, P)                                        # equity 24 000 = plancher
        self.assertTrue(s["breached"])
        self.assertEqual(s["status"], "breached")
        s = risk.state([], -800, 0, P)
        self.assertEqual((s["status"], round(s["buffer"])), ("danger", 200))
        s = risk.state([], -600, 0, P)
        self.assertEqual(s["status"], "warn")
        self.assertEqual(risk.state([], -100, 0, P)["status"], "ok")
        # le latent compte : 150 $ de gain latent ne touchent pas le plancher, 950 $ de perte latente oui presque
        self.assertEqual(round(risk.state([], 0, -950, P)["buffer"]), 50)

    def test_floor_updates_only_at_end_of_day(self):
        # +900 aujourd'hui : le plancher reste a 24 000 jusqu'a la fin de la journee
        s = risk.state([], 900, 0, P)
        self.assertEqual(s["floor"], 24_000)
        self.assertEqual(s["buffer"], 1_900)
        # le lendemain, le solde de la veille a remonte le plancher
        s2 = risk.state([("2026-10-12", 900)], 0, 0, P)
        self.assertEqual(s2["floor"], 25_100 - 200)                              # 25 900 - 1 000 = 24 900

    def test_daily_stop(self):
        s = risk.state([], -350, 0, P)
        self.assertTrue(s["dailyStopHit"])
        self.assertEqual(s["dailyStopLeft"], 0)
        self.assertEqual(risk.state([], -100, 0, P)["dailyStopLeft"], 200)
        self.assertEqual(risk.state([], 150, 0, P)["dailyStopLeft"], 300)

    def test_daily_loss_limit_is_soft(self):
        p = risk.PropProfile.from_dict({"daily_loss_limit": 600})
        s = risk.state([], -650, 0, p)
        self.assertTrue(s["dllHit"])                                  # verrouille jusqu'a la seance suivante...
        self.assertFalse(s["breached"])                               # ... mais le compte survit : seul le plancher le fait echouer
        self.assertFalse(risk.state([], -599, 0, p)["dllHit"])
        self.assertFalse(risk.state([], -650, 0, P)["dllHit"])         # option desactivee par defaut
        self.assertTrue(risk.state([], -900, -100, p)["breached"])     # equity au plancher : echec

    def test_funded_stage_drops_consistency_and_never_passes(self):
        days = [("2026-10-05", 1_300)]                                 # 100 % du profit en un jour : bloquant en evaluation, sans objet une fois finance
        ev = risk.state(days, 0, 0, P)
        self.assertFalse(ev["passed"])
        fu = risk.state(days, 0, 0, P, stage="funded")
        self.assertFalse(fu["consistency"]["rule"])
        self.assertTrue(fu["consistency"]["ok"])
        self.assertFalse(fu["passed"])
        self.assertEqual(fu["stage"], "funded")


class LedgerTests(unittest.TestCase):
    def test_payout_snaps_floor_to_the_lock_and_lowers_balance(self):
        led = risk.ledger([("2026-10-05", 600)], [("2026-10-06", 500)], P)
        self.assertEqual((led["balance"], led["floor"], led["peak"], led["paid"], led["locked"]), (25_100, 25_100, 25_600, 500, True))
        # sans retrait le plancher serait reste a 24 600
        self.assertEqual(risk.ledger([("2026-10-05", 600)], [], P)["floor"], 24_600)
        # ensuite il ne bouge plus, meme avec de nouveaux gains
        led = risk.ledger([("2026-10-05", 600), ("2026-10-07", 700)], [("2026-10-06", 500)], P)
        self.assertEqual((led["balance"], led["floor"]), (25_800, 25_100))

    def test_payout_without_lock_or_static_does_not_snap(self):
        self.assertEqual(risk.ledger([("a", 600)], [("b", 500)], risk.PropProfile.from_dict({"dd_mode": "static"}))["floor"], 24_000)
        self.assertEqual(risk.ledger([("a", 600)], [("b", 500)], risk.PropProfile.from_dict({"lock_offset": None}))["floor"], 24_600)

    def test_trailing_floor_wrapper_is_unchanged(self):
        self.assertEqual(risk.trailing_floor([500, -200], P)["floor"], 24_500)

    def test_scaling_tiers(self):
        self.assertEqual(risk.scaling_caps(-300, P), (1, 10, 1_000))
        self.assertEqual(risk.scaling_caps(999.99, P), (1, 10, 1_000))
        self.assertEqual(risk.scaling_caps(1_000, P), (2, 20, None))
        self.assertEqual(risk.scaling_caps(5_000, P), (2, 20, None))


class PayoutTests(unittest.TestCase):
    def cycle(self, *v):
        return [(f"2026-10-0{i + 1}", x) for i, x in enumerate(v)]

    def test_eligible_and_cushion_after_payout(self):
        st = risk.payout_status(self.cycle(150, 200, 300, 250, 200), 26_100, 25_100, 0, P)       # 5 jours >= 100, profit 1 100
        self.assertTrue(st["eligible"])
        self.assertEqual(st["cap"], 550)                                                           # 50 % de 1 100
        self.assertEqual(st["max"]["amount"], 550)
        self.assertAlmostEqual(st["max"]["net"], 495)                                              # 90 %
        self.assertEqual((st["max"]["balance"], st["max"]["floor"], st["max"]["cushion"]), (25_550, 25_100, 450))
        self.assertEqual(st["min"]["cushion"], 26_100 - 500 - 25_100)

    def test_cap_is_1000_and_needs_2000_of_profit(self):
        st = risk.payout_status(self.cycle(400, 400, 400, 400, 400), 27_000, 25_100, 0, P)
        self.assertEqual(st["cap"], 1_000)
        self.assertEqual(risk.payout_status(self.cycle(400, 400, 400, 400, 400), 26_500, 25_100, 0, P)["cap"], 750)
        self.assertEqual(st["profitForMin"], 1_000)

    def test_five_hundred_profit_from_five_days_is_not_enough(self):
        st = risk.payout_status(self.cycle(100, 100, 100, 100, 100), 25_500, 25_100, 0, P)
        self.assertFalse(st["eligible"])                                                           # 5 jours valides mais plafond 250 $ < minimum 500 $
        self.assertTrue(any("plafond" in w and "1000" in w.replace("\u202f", "") for w in st["why"]), st["why"])
        self.assertIsNone(st["max"])
        self.assertIsNone(st["min"])

    def test_each_reason(self):
        four = risk.payout_status(self.cycle(300, 300, 300, 300, 99), 26_300, 25_100, 0, P)
        self.assertFalse(four["eligible"])
        self.assertTrue(any("manque 1 jour" in w for w in four["why"]))                            # un jour a 99 $ ne compte pas
        self.assertEqual(len(four["daysOk"]), 4)
        neg = risk.payout_status(self.cycle(300, 300, 300, 300, 300, -2_000), 25_500, 25_100, 0, P)
        self.assertTrue(any("pas positif" in w for w in neg["why"]))
        done = risk.payout_status(self.cycle(400, 400, 400, 400, 400), 27_000, 25_100, 5, P)
        self.assertFalse(done["eligible"])
        self.assertTrue(any("5 retraits" in w for w in done["why"]))

    def test_funded_state_end_to_end(self):
        days = [("2026-10-05", 150), ("2026-10-06", 200), ("2026-10-07", 300), ("2026-10-08", 250), ("2026-10-09", 200)]
        s = risk.state(days, 0, 0, P, "funded", [], "2026-10-12")
        self.assertEqual((s["balance"], s["floor"], s["locked"]), (26_100, 25_100, True))
        self.assertTrue(s["payout"]["eligible"])
        self.assertEqual(s["payout"]["max"]["amount"], 550)
        self.assertEqual((s["caps"]["minis"], s["caps"]["micros"]), (2, 20))                       # profit 1 100 : palier haut
        # le retrait est demande aujourd'hui : solde en baisse, plancher verrouille, cycle vide
        s2 = risk.state(days, 0, 0, P, "funded", [("2026-10-12", 550)], "2026-10-12")
        self.assertEqual((s2["balance"], s2["floor"], s2["buffer"], s2["paid"]), (25_550, 25_100, 450, 550))
        self.assertFalse(s2["payout"]["eligible"])
        self.assertEqual(s2["payout"]["done"], 1)
        self.assertEqual(s2["payout"]["left"], 4)
        self.assertEqual(s2["payout"]["daysOk"], [])
        # le palier ne bouge qu'en FIN de seance : le jour du retrait il reste a 2 / 20, le lendemain il redescend avec le solde (25 550 -> profit 550)
        self.assertEqual((s2["caps"]["minis"], s2["caps"]["micros"], s2["caps"]["next"]), (2, 20, None))
        s3 = risk.state(days, 0, 0, P, "funded", [("2026-10-12", 550)], "2026-10-13")
        self.assertEqual((s3["caps"]["minis"], s3["caps"]["micros"], s3["caps"]["next"]), (1, 10, 1_000))

    def test_cycle_restarts_after_a_payout(self):
        days = [("2026-10-05", 300), ("2026-10-06", 300), ("2026-10-07", 300), ("2026-10-08", 300), ("2026-10-09", 300), ("2026-10-13", 120)]
        s = risk.state(days, 0, 0, P, "funded", [("2026-10-12", 500)], "2026-10-14")
        self.assertEqual(s["payout"]["daysOk"], ["2026-10-13"])                                    # seuls les jours APRES le retrait comptent
        self.assertEqual(s["payout"]["cycleProfit"], 120)

    def test_payout_entered_after_the_days_trades_closes_that_days_cycle(self):
        days = [("2026-10-05", 250), ("2026-10-06", 250), ("2026-10-07", 250), ("2026-10-08", 250), ("2026-10-09", 250)]
        # retrait demande le vendredi APRES les trades : le vendredi appartient au cycle clos, le nouveau commence lundi
        after = risk.state(days, 0, 0, P, "funded", [("2026-10-09", 625, True)], "2026-10-12")
        self.assertEqual((after["payout"]["daysOk"], after["payout"]["cycleProfit"]), ([], 0))
        grown = days + [("2026-10-12", 250), ("2026-10-13", 250), ("2026-10-14", 250), ("2026-10-15", 250)]
        four = risk.state(grown, 0, 0, P, "funded", [("2026-10-09", 625, True)], "2026-10-16")
        self.assertEqual(len(four["payout"]["daysOk"]), 4)
        self.assertFalse(four["payout"]["eligible"])                                              # 4 jours neufs : il en manque un
        # saisi AVANT les trades du jour (ex. a l'ouverture), le meme jour ouvre le nouveau cycle
        before = risk.state(grown, 0, 0, P, "funded", [("2026-10-09", 625, False)], "2026-10-16")
        self.assertEqual(len(before["payout"]["daysOk"]), 5)
        self.assertTrue(before["payout"]["eligible"])
        # le solde et le plancher ne dependent pas de cet ordre
        self.assertEqual((four["balance"], four["floor"]), (before["balance"], before["floor"]))

    def test_payout_room_uses_the_live_balance(self):
        days = [(f"2026-10-0{i}", 400) for i in range(5, 10)]
        ok = risk.state(days, 0, 0, P, "funded", [], "2026-10-12")
        self.assertTrue(ok["payout"]["eligible"])
        self.assertEqual(ok["payout"]["max"]["amount"], 1_000)
        hurt = risk.state(days, -1_000, 0, P, "funded", [], "2026-10-12")                        # solde du moment 26 000 : 1 000 $ de retrait le ramenerait a 25 000, sous le plancher
        self.assertTrue(hurt["payout"]["eligible"])
        self.assertEqual(hurt["payout"]["max"]["amount"], 899)                                   # marge 900 $ -> au plus 899 $, 1 $ au-dessus du plancher
        self.assertEqual(hurt["payout"]["max"]["cushion"], 1)
        self.assertEqual(hurt["payout"]["max"]["balance"], hurt["balance"] - hurt["payout"]["max"]["amount"])
        gone = risk.state(days, 0, -1_900, P, "funded", [], "2026-10-12")                        # equity au plancher : plus de retrait
        self.assertTrue(gone["breached"])
        self.assertFalse(gone["payout"]["eligible"])
        self.assertTrue(any("marge" in w for w in gone["payout"]["why"]))

    def test_float_noise_does_not_hide_a_threshold(self):
        parts = [12.21, 143.14, 619.17, 475.48]                                                   # somme exacte 1 250,00 $, mais 1249,99999... en virgule flottante
        ev = risk.state([(f"2026-10-0{i + 5}", x) for i, x in enumerate(parts)], 0, 0, P, "eval", [], "2026-10-12")
        self.assertTrue(ev["targetHit"])
        self.assertTrue(ev["passed"])
        fd = risk.state([(f"2026-10-0{i + 5}", x) for i, x in enumerate([271.62, 391.17, 337.21])], 0, 0, P, "funded", [], "2026-10-12")
        self.assertEqual((fd["profit"], fd["caps"]["minis"], fd["caps"]["next"]), (1_000.0, 2, None))

    def test_duplicate_day_entries_count_once(self):
        five = [("2026-10-05", 120)] * 5
        s = risk.state(five, 0, 0, P, "funded", [], "2026-10-12")
        self.assertEqual(s["payout"]["daysOk"], ["2026-10-05"])
        self.assertFalse(s["payout"]["eligible"])
        self.assertEqual(s["balance"], 25_000 + 600)

    def test_soft_daily_loss_limit_is_flagged_not_fatal(self):
        q = replace(P, daily_loss_limit=600)
        s = risk.state([], -650, 0, q, "funded", [], "2026-10-12")
        self.assertTrue(s["dllHit"])
        self.assertFalse(s["breached"])
        r = risk.plan("long", 25_000, 24_995, [25_010], "NQ", q, acct=s, risk_usd=100)
        self.assertTrue(any("limite de perte journalière" in w for w in r["warnings"]))
        self.assertFalse(risk.state([], -100, 0, q, "funded", [], "2026-10-12")["dllHit"])

    def test_scaling_limits_the_plan_when_funded(self):
        low = risk.state([("2026-10-05", 300)], 0, 0, P, "funded", [], "2026-10-12")
        r = risk.plan("short", 25_000, 25_005, [24_990], "NQ", P, acct=low, risk_usd=500)
        self.assertEqual(r["sizes"]["NQ"]["qty"], 1)                                               # 2 minis en evaluation, 1 seul sous 1 000 $ de profit
        self.assertTrue(r["sizes"]["NQ"]["capped"])
        self.assertTrue(any("palier" in w for w in r["warnings"]))
        ev = risk.state([("2026-10-05", 300)], 0, 0, P, "eval", [], "2026-10-12")
        self.assertEqual(risk.plan("short", 25_000, 25_005, [24_990], "NQ", P, acct=ev, risk_usd=500)["sizes"]["NQ"]["qty"], 2)
        self.assertEqual(risk.max_qty("MNQ", P, None, (1, 10)), 10)


class PlanTests(unittest.TestCase):
    def test_long_sizes_and_rr(self):
        r = risk.plan("long", 25_000, 24_990, [25_020], "NQ", P)
        nq, mnq = r["sizes"]["NQ"], r["sizes"]["MNQ"]
        self.assertEqual(r["stopPts"], 10)
        self.assertEqual(r["stopTicks"], 40)
        self.assertEqual(nq["qty"], 0)                                           # 10 pts x 20 $ + frais = 204,5 $ > 100 $
        self.assertEqual(mnq["qty"], 4)                                          # 10 x 2 + 1,0 = 21,0 $ -> 4 contrats
        t = mnq["targets"][0]
        self.assertAlmostEqual(t["net"], 20 * 2 * 4 - 1.0 * 4)                          # frais Lucid : 1,00 $ l'aller-retour par MNQ
        self.assertAlmostEqual(t["r"], t["net"] / (4 * 21.0))
        self.assertTrue(any("MNQ" in w for w in r["warnings"]))

    def test_cap_and_short(self):
        r = risk.plan("short", 25_000, 25_005, [24_990], "NQ", P, risk_usd=500)
        self.assertEqual(r["sizes"]["NQ"]["wanted"], 4)
        self.assertEqual(r["sizes"]["NQ"]["qty"], 2)
        self.assertTrue(r["sizes"]["NQ"]["capped"])
        self.assertGreater(r["sizes"]["NQ"]["targets"][0]["net"], 0)
        self.assertTrue(any("Plafond" in w for w in r["warnings"]))
        self.assertTrue(any("au-dessus de ta limite" in w for w in r["warnings"]))

    def test_wrong_side_stop(self):
        with self.assertRaises(ValueError):
            risk.plan("long", 25_000, 25_005, [25_010], "NQ", P)
        with self.assertRaises(ValueError):
            risk.plan("short", 25_000, 24_995, [], "NQ", P)
        with self.assertRaises(ValueError):
            risk.plan("up", 25_000, 24_995, [], "NQ", P)

    def test_minis_and_micros_share_the_cap(self):
        self.assertEqual(risk.max_qty("NQ", P, {"NQ": 1}), 1)
        self.assertEqual(risk.max_qty("MNQ", P, {"NQ": 1}), 10)
        self.assertEqual(risk.max_qty("MNQ", P, {"MNQ": 20}), 0)
        self.assertEqual(risk.max_qty("NQ", P, {"MNQ": 15}), 0)                  # 1,5 mini equivalent : pas de place pour un mini de plus
        self.assertEqual(risk.max_qty("NQ", P, {"MNQ": 10}), 1)
        self.assertAlmostEqual(risk.mini_equiv({"NQ": 1, "MNQ": 5}), 1.5)

    def test_account_warnings(self):
        acct = risk.state([], -220, 0, P)                                           # 8 MNQ x 5 pts = 92 $ de risque : −312 $ > stop quotidien
        r = risk.plan("long", 25_000, 24_995, [25_010], "MNQ", P, acct=acct, risk_usd=100)
        self.assertTrue(any("stop quotidien" in w for w in r["warnings"]))
        low = risk.state([], -800, 0, P)
        r = risk.plan("long", 25_000, 24_995, [25_010], "MNQ", P, acct=low, risk_usd=100)
        self.assertTrue(any("marge restante" in w for w in r["warnings"]))

    def test_fee_eats_target(self):
        r = risk.plan("long", 25_000, 24_990, [25_000.5], "MNQ", P, risk_usd=100)
        self.assertTrue(any("frais" in w for w in r["warnings"]))


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "compte.json"
        self.now = utc(2026, 10, 12, 15)
        self.acc = Account(self.path, now_ms=lambda: self.now)

    def tearDown(self):
        self.dir.cleanup()

    def test_trade_pnl_and_persistence(self):
        r = self.acc.add_trade("NQ", "long", 1, 25_000, 25_010, t=self.now)
        self.assertEqual((r["gross"], r["fees"], r["net"], r["day"]), (200.0, 3.5, 196.5, "2026-10-12"))
        r2 = self.acc.add_trade("mnq", "short", 5, 25_010, 25_000.13, t=self.now)      # prix aligne sur le tick, MNQ en minuscules
        self.assertEqual(r2["exit"], 25_000.25)
        self.assertEqual(r2["gross"], round(9.75 * 2 * 5, 2))
        again = Account(self.path, now_ms=lambda: self.now)
        self.assertEqual(again.records, self.acc.records)
        self.assertEqual(again.next_id, 3)

    def test_snapshot_splits_today_from_closed_days(self):
        self.acc.add_trade("NQ", "long", 1, 25_000, 25_030, t=utc(2026, 10, 9, 15), fees=0)      # vendredi
        self.acc.add_trade("NQ", "long", 1, 25_000, 24_990, t=self.now, fees=0)                  # lundi
        s = self.acc.snapshot("2026-10-12", open_pnl=50)
        self.assertEqual(s["todayPnl"], -200)
        self.assertEqual(s["balance"], 25_000 + 600 - 200)
        self.assertEqual(s["floor"], 24_000 + 600)                                      # plancher remonte avec la veille
        self.assertEqual(s["equity"], s["balance"] + 50)
        self.assertEqual(len(s["records"]), 1)
        self.assertEqual([d["day"] for d in s["days"]], ["2026-10-09", "2026-10-12"])

    def test_day_boundary_uses_trading_day(self):
        r = self.acc.add_trade("NQ", "long", 1, 25_000, 25_001, t=utc(2026, 10, 11, 22, 30), fees=0)    # dimanche 18 h 30 ET
        self.assertEqual(r["day"], "2026-10-12")

    def _fund(self, start=(2026, 10, 5)):
        self.acc.start_funded(t=utc(*start, 12))
        for d in range(5, 10):
            self.acc.add_adjust(f"2026-10-{d:02d}", 300, "jour")

    def test_non_finite_and_absurd_numbers_are_refused(self):
        nan, inf = float("nan"), float("inf")
        for args in [("NQ", "long", nan, 25_000, 25_010), ("NQ", "long", inf, 25_000, 25_010), ("NQ", "long", 1, nan, 25_010),
                     ("NQ", "long", 1, 25_000, inf), ("NQ", "long", True, 25_000, 25_010), ("NQ", "long", 0, 25_000, 25_010),
                     ("NQ", "long", 1e9, 25_000, 25_010)]:
            with self.assertRaises(AccountError, msg=str(args)):
                self.acc.add_trade(*args)
        for kw in ({"fees": nan}, {"fees": -1}, {"hold_s": nan}, {"hold_s": -2}, {"t": nan}, {"t": inf}, {"t": 1_791_823_200}, {"t": utc(2030, 1, 1)}):
            with self.assertRaises(AccountError, msg=str(kw)):
                self.acc.add_trade("NQ", "long", 1, 25_000, 25_010, **kw)
        for net in (nan, inf, -inf, "x", None, True, 1e12):
            with self.assertRaises(AccountError, msg=str(net)):
                self.acc.add_adjust("2026-10-08", net)
        for day in ("20261005", "2026-W41-1", "2026-13-01", "", None, "2026-10-5"):
            with self.assertRaises(AccountError, msg=str(day)):
                self.acc.add_adjust(day, 10)
        self.assertEqual(self.acc.records, [])
        self.assertFalse(self.path.exists())

    def test_payout_amount_validation(self):
        self._fund()
        for amount in (float("nan"), float("inf"), 1e308, True, 0, -5, 0.001, "abc", None):
            with self.assertRaises(AccountError, msg=str(amount)):
                self.acc.add_payout(amount, t=self.now)
        with self.assertRaises(AccountError):
            self.acc.add_payout(400, t=self.now)                                       # sous le minimum de 500 $
        with self.assertRaises(AccountError):
            self.acc.add_payout(1_500, t=self.now)                                     # au-dessus du plafond de 1 000 $
        with self.assertRaises(AccountError):
            self.acc.add_payout(500, t=utc(2026, 10, 1, 15))                           # daté avant le passage en compte financé
        r = self.acc.add_payout(750, t=self.now)
        self.assertEqual((r["amount"], r["warnings"]), (750.0, []))
        with self.assertRaises(AccountError):                                          # le second du même jour : plus de jours dans le cycle, mais surtout pas sous le plancher
            self.acc.add_payout(1_000, t=self.now)
        self.assertEqual(self.acc.snapshot("2026-10-12")["balance"], 25_000 + 1_500 - 750)

    def test_payout_on_a_fresh_funded_account_is_impossible(self):
        self.acc.start_funded(t=self.now)
        with self.assertRaises(AccountError) as e:
            self.acc.add_payout(500, t=self.now)                                       # 24 500 $ serait sous le plancher verrouillé (25 100 $)
        self.assertIn("plancher", str(e.exception))

    def test_payout_below_the_modelled_cap_only_warns(self):
        self.acc.start_funded(t=utc(2026, 10, 5, 12))
        self.acc.add_adjust("2026-10-05", 1_100, "un seul gros jour")
        r = self.acc.add_payout(550, t=self.now)                                       # Lucid peut avoir une autre lecture : on enregistre et on prévient
        self.assertTrue(any("manque 4 jour(s)" in w for w in r["warnings"]))

    def test_payout_entered_after_the_session_closes_that_days_cycle(self):
        self.now = utc(2026, 10, 16, 20)
        self.acc.start_funded(t=utc(2026, 10, 5, 12))
        for d in range(5, 10):
            self.acc.add_trade("NQ", "long", 1, 25_000, 25_012.5, t=utc(2026, 10, d, 15), fees=0)            # 5 x +250
        evening = self.acc.add_payout(625, t=utc(2026, 10, 9, 21, 5))                                         # vendredi 17 h 05 ET
        self.assertEqual(evening["day"], "2026-10-09")
        self.assertEqual(evening["warnings"], [])                                                             # la journée de vendredi compte dans ce cycle-là
        self.assertEqual(self.acc.snapshot("2026-10-12")["payout"]["daysOk"], [])
        for d in (12, 13, 14, 15):
            self.acc.add_trade("NQ", "long", 1, 25_000, 25_012.5, t=utc(2026, 10, d, 15), fees=0)
        po = self.acc.snapshot("2026-10-16")["payout"]
        self.assertEqual((po["eligible"], len(po["daysOk"])), (False, 4))
        # à l'ouverture (avant les trades du jour) le même jour ouvre le nouveau cycle
        acc2 = Account(Path(self.dir.name) / "b.json", now_ms=lambda: self.now)
        acc2.start_funded(t=utc(2026, 10, 5, 12))
        for d in range(5, 9):
            acc2.add_adjust(f"2026-10-{d:02d}", 250)
        acc2.add_payout(500, t=utc(2026, 10, 9, 13))                                   # vendredi 9 h ET, avant le moindre trade du jour
        acc2.add_trade("NQ", "long", 1, 25_000, 25_012.5, t=utc(2026, 10, 9, 15), fees=0)
        self.assertEqual(acc2.snapshot("2026-10-12")["payout"]["daysOk"], ["2026-10-09"])

    def test_stage_marker_cannot_be_deleted_from_the_middle(self):
        self.acc.add_adjust("2026-10-02", 200, "évaluation")
        mark = self.acc.start_funded(t=utc(2026, 10, 5, 12))
        self.acc.add_adjust("2026-10-06", 100, "financé")
        with self.assertRaises(AccountError):
            self.acc.delete(mark["id"])
        self.assertEqual(self.acc.snapshot("2026-10-12")["stage"], "funded")
        self.assertEqual(self.acc.snapshot("2026-10-12")["profit"], 100)
        self.acc.undo()
        self.assertTrue(self.acc.delete(mark["id"]))                                   # dernier du journal : équivaut à annuler
        self.assertEqual(self.acc.snapshot("2026-10-12")["stage"], "eval")

    def test_evaluation_entries_made_after_the_marker_do_not_enter_the_funded_account(self):
        self.acc.start_funded(t=utc(2026, 10, 7, 12))
        self.acc.add_adjust("2026-10-05", 500, "évaluation rattrapée")
        self.acc.add_adjust("2026-10-08", 100, "financé")
        s = self.acc.snapshot("2026-10-12")
        self.assertEqual((s["profit"], [d["day"] for d in s["days"]]), (100, ["2026-10-08"]))
        self.assertEqual(len(self.acc.records), 3)                                     # rien n'est perdu dans le journal

    def test_micro_share_counts_the_current_account_only(self):
        self.acc.add_trade("NQ", "long", 1, 25_000, 25_010, t=utc(2026, 10, 6, 15), fees=0, hold_s=2)
        self.assertEqual(self.acc.micro()["shortWins"], 200)
        self.acc.start_funded(t=utc(2026, 10, 8, 15))
        self.assertEqual((self.acc.micro()["trades"], self.acc.micro()["shareMin"]), (0, None))

    def test_failed_write_rolls_back_the_entry(self):
        (Path(self.dir.name) / "compte.json.tmp").mkdir()                              # l'écriture du fichier temporaire va échouer
        with self.assertRaises(AccountError) as e:
            self.acc.add_adjust("2026-10-08", 100)
        self.assertIn("impossible", str(e.exception))
        self.assertEqual((self.acc.records, self.acc.next_id), ([], 1))
        (Path(self.dir.name) / "compte.json.tmp").rmdir()
        self.assertEqual(self.acc.add_adjust("2026-10-08", 100)["id"], 1)              # le nouvel essai ne double pas la saisie
        self.assertEqual(len(self.acc.records), 1)

    def test_profile_validation(self):
        bad = [{"scaling": []}, {"scaling": [[0, 1]]}, {"scaling": "x"}, {"scaling": [[0, 0, 10]]}, {"scaling": [[0, 1, 10], [0, 2, 20]]},
               {"payout_cap_pct": 0}, {"payout_cap_pct": 1.5}, {"payout_split": 0}, {"max_payouts": "abc"}, {"payout_min": 0}, {"payout_cap": 100},
               {"daily_loss_limit": -50}, {"max_minis": 0}, {"start_balance": float("nan")}, {"fee_rt": {"NQ": -1}}, {"dd_mode": "x"}, {"risk_per_trade": True}]
        for ch in bad:
            with self.assertRaises(AccountError, msg=str(ch)):
                self.acc.set_profile(ch)
        self.assertEqual(self.acc.overrides, {})
        self.acc.start_funded(t=self.now)
        self.assertEqual(self.acc.snapshot("2026-10-12")["stage"], "funded")           # un profil refusé ne laisse aucune trace qui ferait planter le compte
        p = self.acc.set_profile({"scaling": [[1000, 2, 20], [0, 1, 10]], "daily_loss_limit": 0})
        self.assertEqual(p.scaling, ((0.0, 1, 10), (1_000.0, 2, 20)))                  # triés
        self.assertIsNone(p.daily_loss_limit)                                          # 0 = pas de limite, pas une limite à 0 $
        self.assertEqual(self.acc.snapshot("2026-10-12")["caps"]["minis"], 1)

    def test_corrupt_or_poisoned_journal_is_set_aside(self):
        for bad in ('{"records":[{"id":1,"kind":"adjust","t":1,"day":"2026-10-08","net":NaN}]}',
                    '{"records":[{"id":1,"kind":"payout","t":1,"day":"2026-10-08","amount":Infinity}]}',
                    '{"records":[{"id":1,"kind":"adjust","t":1,"day":"20261008","net":5}]}',
                    '{"records":[{"id":1,"kind":"adjust","t":1}]}', '{"records":[null]}', '{"records":[{"kind":"zz"}]}'):
            self.path.write_text(bad, encoding="utf-8")
            acc = Account(self.path, now_ms=lambda: self.now)
            self.assertEqual(acc.records, [], bad)
            self.assertTrue(list(Path(self.dir.name).glob("compte.json.corrompu-*")))
            for f in Path(self.dir.name).glob("compte.json.corrompu-*"):
                f.unlink()

    def test_old_journal_and_bad_profile_overrides_keep_the_records(self):
        old = {"version": 1, "next_id": 2, "profile": {"scaling": [], "payout_cap_pct": 0, "risk_per_trade": 80},
               "records": [{"id": 1, "kind": "trade", "t": utc(2026, 10, 12, 15), "day": "2026-10-12", "inst": "NQ", "side": "long", "qty": 1, "entry": 25_000.0,
                            "exit": 25_010.0, "gross": 200.0, "fees": 3.5, "net": 196.5, "pts": 10.0, "setup": "", "note": ""}]}
        self.path.write_text(json.dumps(old), encoding="utf-8")
        acc = Account(self.path, now_ms=lambda: self.now)
        self.assertEqual(len(acc.records), 1)                                          # le journal reste, seuls les réglages abîmés sont écartés
        self.assertEqual(acc.snapshot("2026-10-12")["todayPnl"], 196.5)
        self.assertEqual(acc.profile.risk_per_trade, 80.0)                             # le réglage sain est gardé
        self.assertEqual(sorted(acc.profile_dropped), ["payout_cap_pct", "scaling"])
        self.assertEqual(sorted(acc.snapshot("2026-10-12")["profileDropped"]), ["payout_cap_pct", "scaling"])
        self.assertTrue(list(Path(self.dir.name).glob("compte.json.avant-reglages-*")))       # l'original reste lisible à côté
        acc.add_adjust("2026-10-13", 5)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["profile"], {"risk_per_trade": 80})

    def test_old_profile_with_consistency_zero_is_kept(self):
        old = {"version": 1, "next_id": 1, "profile": {"consistency_pct": 0, "fee_rt": {"NQ": 4.5, "MNQ": 1.25}, "max_minis": 1, "max_micros": 10, "daily_stop": 450},
               "records": []}
        self.path.write_text(json.dumps(old), encoding="utf-8")
        acc = Account(self.path, now_ms=lambda: self.now)
        self.assertEqual((acc.profile.fee_rt["NQ"], acc.profile.max_minis, acc.profile.daily_stop, acc.profile.consistency_pct), (4.5, 1, 450.0, None))
        self.assertEqual(acc.profile_dropped, [])

    def test_sixth_payout_is_refused_even_when_backdated(self):
        self.now = utc(2026, 11, 30, 20)
        self.acc.start_funded(t=utc(2026, 10, 5, 12))
        d = 5
        while d < 30:
            for _ in range(5):
                self.acc.add_adjust(f"2026-10-{d:02d}", 400)
                d += 1
            d += 0
            if d >= 30:
                break
        for k in range(1, 4):                                                          # des jours gagnants en novembre, pour que le solde soit large
            self.acc.add_adjust(f"2026-11-{k:02d}", 1_000)
        for day in ("2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09"):
            self.acc.add_payout(500, t=utc(*[int(x) for x in day.split("-")], 21, 5))
        self.assertEqual(len(self.acc.snapshot("2026-11-30")["payouts"]), 5)
        with self.assertRaises(AccountError) as e:
            self.acc.add_payout(500, t=utc(2026, 10, 7, 21, 5))                        # antidaté avant tous les autres
        self.assertIn("5 retraits", str(e.exception))
        self.assertEqual(len(self.acc.snapshot("2026-11-30")["payouts"]), 5)

    def test_backdated_payout_cannot_sink_the_final_balance(self):
        self.now = utc(2026, 10, 20, 20)
        self.acc.start_funded(t=utc(2026, 10, 5, 12))
        for d in range(5, 10):
            self.acc.add_adjust(f"2026-10-{d:02d}", 300)                                 # 26 500 $
        self.acc.add_adjust("2026-10-12", -1_300)                                        # 25 200 $
        with self.assertRaises(AccountError) as e:
            self.acc.add_payout(500, t=utc(2026, 10, 9, 21, 5))                          # 25 200 - 500 = 24 700 < 25 100 une fois les saisies suivantes rejouées
        self.assertIn("plancher", str(e.exception))
        self.assertEqual(self.acc.snapshot("2026-10-20")["payouts"], [])

    def test_warnings_use_the_same_cycle_as_the_stored_payout(self):
        self.now = utc(2026, 10, 16, 20)
        self.acc.start_funded(t=utc(2026, 10, 5, 12))
        for d in range(5, 9):
            self.acc.add_trade("NQ", "long", 1, 25_000, 25_012.5, t=utc(2026, 10, d, 15), fees=0)      # 4 x +250
        self.acc.add_trade("NQ", "long", 1, 25_000, 25_020, t=utc(2026, 10, 9, 18), fees=0)             # +400 le vendredi à 14 h ET
        r = self.acc.add_payout(650, t=utc(2026, 10, 9, 19, 30))                                        # 15 h 30 ET : après le dernier trade, avant 16 h 45
        self.assertEqual(r["warnings"], [])                                                             # le vendredi compte dans le cycle que ce retrait clôt

    def test_payouts_are_ordered_by_time_not_by_entry_order(self):
        self.now = utc(2026, 10, 16, 20)
        self.acc.start_funded(t=utc(2026, 10, 5, 12))
        for d in range(5, 9):
            self.acc.add_adjust(f"2026-10-{d:02d}", 300)
        self.acc.add_trade("NQ", "long", 1, 25_000, 25_020, t=utc(2026, 10, 9, 15), fees=0)             # +400 vendredi 11 h ET
        self.acc.add_payout(500, t=utc(2026, 10, 9, 21, 5))                                             # 17 h 05 ET : clôt le vendredi
        self.acc.add_payout(500, t=utc(2026, 10, 9, 13, 0))                                             # 9 h ET, saisi après : ne doit pas rouvrir le vendredi
        self.assertEqual(self.acc.snapshot("2026-10-12")["payout"]["daysOk"], [])

    def test_text_and_number_edge_cases_never_escape_as_exceptions(self):
        with self.assertRaises(AccountError):
            self.acc.add_trade("NQ", "long", 10 ** 400, 25_000, 25_010)
        with self.assertRaises(AccountError):
            self.acc.add_adjust("2026-10-08", 10 ** 400)
        with self.assertRaises(AccountError):
            self.acc.set_profile({"payout_min": 10 ** 400})
        r = self.acc.add_adjust("2026-10-08", 5, note="a\ud800b")                        # substitut isolé : impossible à écrire en UTF-8
        self.assertEqual(Account(self.path, now_ms=lambda: self.now).records[0]["id"], r["id"])
        with self.assertRaises(AccountError):
            self.acc.set_profile({"name": 123})
        with self.assertRaises(AccountError):
            self.acc.set_profile({"to_verify": "abc"})

    def test_journal_types_are_strict_at_load(self):
        good = {"id": 1, "kind": "adjust", "t": 1, "day": "2026-10-08", "net": 5.0, "note": ""}
        trade = {"id": 1, "kind": "trade", "t": 1, "day": "2026-10-08", "inst": "NQ", "side": "long", "qty": 1, "entry": 1.0, "exit": 2.0, "gross": 1.0,
                 "fees": 0.0, "net": 1.0, "pts": 1.0, "setup": "", "note": ""}
        bads = [dict(good, net="12.5"), dict(good, id="1"), dict(good, id=True), dict(trade, hold_s="3"), dict(trade, setup=["x"]), dict(trade, fees="0"),
                dict(trade, qty="1"), {"id": 1, "kind": "payout", "t": 1, "day": "2026-10-08", "amount": "500"}]
        for rec in bads:
            self.path.write_text(json.dumps({"records": [rec]}), encoding="utf-8")
            self.assertEqual(Account(self.path, now_ms=lambda: self.now).records, [], rec)
            for f in Path(self.dir.name).glob("compte.json.corrompu-*"):
                f.unlink()
        for text in ('{"next_id": 1' + '0' * 400 + ', "records": []}', "[" * 5000, '{"records": []' + "," * 3 + "}"):
            self.path.write_text(text, encoding="utf-8")
            self.assertEqual(Account(self.path, now_ms=lambda: self.now).records, [])         # jamais d'exception au démarrage
            for f in Path(self.dir.name).glob("compte.json.corrompu-*"):
                f.unlink()
        self.path.write_text(json.dumps({"records": [good, trade]}), encoding="utf-8")
        self.assertEqual(len(Account(self.path, now_ms=lambda: self.now).records), 2)

    def test_dll_latch_is_not_touched_by_refused_operations(self):
        self.acc.set_profile({"daily_loss_limit": 600})
        self.acc.start_funded(t=utc(2026, 10, 12, 13))
        self.assertTrue(self.acc.snapshot("2026-10-12", open_pnl=-650)["dllHit"])
        with self.assertRaises(AccountError):
            self.acc.add_payout(500, t=utc(2026, 10, 12, 17))                             # refusé : pas de jours, solde au plancher
        self.assertTrue(self.acc.snapshot("2026-10-12", open_pnl=-100)["dllHit"])          # le verrou du jour courant est resté
        self.acc.set_profile({"risk_per_trade": 90})                                       # enregistrer d'autres règles ne rouvre pas la séance
        self.assertTrue(self.acc.snapshot("2026-10-12", open_pnl=-100)["dllHit"])
        self.acc.set_profile({"daily_loss_limit": 700})                                    # changer la limite oui
        self.assertFalse(self.acc.snapshot("2026-10-12", open_pnl=-100)["dllHit"])

    def test_backdated_payout_is_checked_on_its_own_day_not_with_the_next_days_gains(self):
        self.now = utc(2026, 5, 6, 16)
        self.acc.start_funded(t=utc(2026, 4, 27, 13))
        self.acc.add_adjust("2026-04-27", 400)                                       # clôture du lundi : 25 400 $
        self.acc.add_adjust("2026-04-28", 1_000)                                     # déjà au journal quand le retrait est saisi
        with self.assertRaises(AccountError) as e:
            self.acc.add_payout(500, t=utc(2026, 4, 27, 21))                         # lundi 17 h ET : 25 400 - 500 = 24 900 < plancher 25 100
        self.assertIn("plancher", str(e.exception))
        self.assertEqual(self.acc.snapshot("2026-05-06")["payouts"], [])

    def test_salvage_keeps_settings_that_are_only_valid_together(self):
        old = {"version": 1, "next_id": 1, "profile": {"payout_min": 2_000, "payout_cap": 3_000, "bogus_numbers": "x", "scaling": []}, "records": []}
        self.path.write_text(json.dumps(old), encoding="utf-8")
        acc = Account(self.path, now_ms=lambda: self.now)
        self.assertEqual((acc.profile.payout_min, acc.profile.payout_cap), (2_000, 3_000))     # l'ordre des clés dans le fichier ne compte pas
        self.assertEqual(acc.profile_dropped, ["scaling"])

    def test_json_floats_that_overflow_are_quarantined_and_writes_never_raise_bare_errors(self):
        self.path.write_text('{"records": [], "profile": {"risk_per_trade": 1e999}}', encoding="utf-8")
        acc = Account(self.path, now_ms=lambda: self.now)
        self.assertEqual(acc.records, [])
        self.assertTrue(list(Path(self.dir.name).glob("compte.json.corrompu-*")))
        self.acc.overrides["junk"] = float("inf")                                    # même si une valeur non finie se glissait en mémoire
        with self.assertRaises(AccountError):
            self.acc.add_adjust("2026-10-08", 5)
        self.assertEqual(self.acc.records, [])

    def test_far_future_days_are_refused_and_do_not_break_payouts(self):
        with self.assertRaises(AccountError):
            self.acc.add_adjust("9999-12-31", 5)
        with self.assertRaises(AccountError):
            self.acc.add_adjust("1999-12-31", 5)

    def test_failed_set_profile_keeps_the_dropped_settings_warning(self):
        self.path.write_text(json.dumps({"version": 1, "next_id": 1, "profile": {"scaling": [], "risk_per_trade": 80}, "records": []}), encoding="utf-8")
        acc = Account(self.path, now_ms=lambda: self.now)
        self.assertEqual(acc.profile_dropped, ["scaling"])
        (Path(self.dir.name) / "compte.json.tmp").mkdir()
        with self.assertRaises(AccountError):
            acc.set_profile({"daily_stop": 250})
        self.assertEqual(acc.profile_dropped, ["scaling"])

    def test_fees_merge_per_contract_and_profile_bounds(self):
        self.acc.set_profile({"fee_rt": {"ES": 5.0, "MES": 1.5}})
        self.acc.set_profile({"fee_rt": {"NQ": 4.0, "mnq": 1.25}})                   # le formulaire n'envoie que NQ / MNQ : ES / MES restent
        self.assertEqual(self.acc.profile.fee_rt, {"NQ": 4.0, "MNQ": 1.25, "ES": 5.0, "MES": 1.5})
        for bad in ({"payout_cap_pct": 1e-320}, {"payout_cap_pct": 0.0001}, {"payout_days": 5_000_000_000}, {"payout_days": 61}):
            with self.assertRaises(AccountError, msg=str(bad)):
                self.acc.set_profile(bad)
        self.assertEqual(self.acc.set_profile({"payout_days": 3, "payout_cap_pct": 0.4, "payout_split": 0.8}).payout_days, 3)

    def test_failed_reset_keeps_the_journal_file(self):
        self.acc.add_adjust("2026-10-08", 100)
        (Path(self.dir.name) / "compte.json.tmp").mkdir()
        with self.assertRaises(AccountError):
            self.acc.reset()
        self.assertTrue(self.path.is_file())                                              # le fichier n'a pas été déplacé
        (Path(self.dir.name) / "compte.json.tmp").rmdir()
        self.assertEqual(len(Account(self.path, now_ms=lambda: self.now).records), 1)
        self.assertEqual(len(self.acc.records), 1)

    def test_daily_loss_limit_stays_locked_when_the_open_pnl_recovers(self):
        self.acc.set_profile({"daily_loss_limit": 600})
        self.assertTrue(self.acc.snapshot("2026-10-12", open_pnl=-650)["dllHit"])
        self.assertTrue(self.acc.snapshot("2026-10-12", open_pnl=-100)["dllHit"])      # le latent remonte : la séance reste verrouillée
        self.assertFalse(self.acc.snapshot("2026-10-13", open_pnl=-100)["dllHit"])     # séance suivante : rouverte
        self.acc.set_profile({"daily_loss_limit": 800})
        self.assertFalse(self.acc.snapshot("2026-10-12", open_pnl=-100)["dllHit"])

    def test_adjust_undo_delete_reset(self):
        self.acc.add_adjust("2026-10-08", 450, "depart")
        a = self.acc.add_trade("NQ", "long", 1, 25_000, 25_010, t=self.now)
        self.assertEqual(self.acc.snapshot("2026-10-12")["start"] + 450 + 196.5, self.acc.snapshot("2026-10-12")["balance"])
        self.assertEqual(self.acc.undo()["id"], a["id"])
        self.assertEqual(len(self.acc.records), 1)
        self.assertTrue(self.acc.delete(1))
        self.assertFalse(self.acc.delete(99))
        self.acc.add_adjust("2026-10-08", 10)
        self.assertEqual(self.acc.reset(), 1)
        self.assertEqual(self.acc.records, [])
        self.assertTrue(any("avant-reset" in p.name for p in self.path.parent.iterdir()))
        self.assertIsNone(self.acc.undo())

    def test_validation(self):
        bad = [("XYZ", "long", 1, 1, 1), ("NQ", "up", 1, 25_000, 25_001), ("NQ", "long", 0, 25_000, 25_001), ("NQ", "long", 1.5, 25_000, 25_001),
               ("NQ", "long", 1, -5, 25_001), ("NQ", "long", "a", 25_000, 25_001)]
        for args in bad:
            with self.assertRaises(AccountError, msg=str(args)):
                self.acc.add_trade(*args)
        with self.assertRaises(AccountError):
            self.acc.add_adjust("pas-un-jour", 10)
        self.assertEqual(self.acc.records, [])

    def test_profile_changes_persist(self):
        self.acc.set_profile({"profit_target": 1_500, "risk_per_trade": 80, "fee_rt": {"NQ": 3.0}, "consistency_pct": None})
        again = Account(self.path)
        self.assertEqual(again.profile.profit_target, 1_500)
        self.assertEqual(again.profile.fee_rt["NQ"], 3.0)
        self.assertEqual(again.profile.fee_rt["MNQ"], 1.0)                          # les autres frais gardent leur valeur
        self.assertIsNone(again.profile.consistency_pct)
        with self.assertRaises(AccountError):
            self.acc.set_profile({"nimportequoi": 1})
        with self.assertRaises(AccountError):
            self.acc.set_profile({"max_drawdown": -5})
        self.assertEqual(self.acc.profile.max_drawdown, 1_000)                       # un refus ne change rien

    def test_corrupt_file_is_set_aside(self):
        self.path.write_text("{pas du json", encoding="utf-8")
        acc = Account(self.path)
        self.assertEqual(acc.records, [])
        self.assertTrue(any("corrompu" in p.name for p in self.path.parent.iterdir()))
        acc.add_adjust("2026-10-12", 5)
        self.assertEqual(json.loads(self.path.read_text())["records"][0]["net"], 5)

    def test_funded_stage_restarts_the_account(self):
        self.acc.add_trade("NQ", "long", 1, 25_000, 25_070, t=utc(2026, 10, 8, 15), fees=0)       # 1 400 $ : l'evaluation est validee
        self.assertEqual(self.acc.snapshot("2026-10-12")["stage"], "eval")
        rec = self.acc.start_funded(t=self.now)
        self.assertEqual(rec["stage"], "funded")
        s = self.acc.snapshot("2026-10-12")
        self.assertEqual((s["stage"], s["balance"], s["floor"], s["days"]), ("funded", 25_000, 24_000, []))   # nouveau compte : solde et plancher de depart
        self.assertEqual(s["stageSince"], "2026-10-12")
        self.assertEqual((s["caps"]["minis"], s["caps"]["micros"]), (1, 10))                         # palier de depart
        with self.assertRaises(AccountError):
            self.acc.start_funded()                                                                  # deja finance
        self.acc.add_trade("NQ", "long", 1, 25_000, 25_010, t=self.now, fees=0)
        self.assertEqual(self.acc.snapshot("2026-10-12")["balance"], 25_200)                         # l'ancien profit de l'evaluation ne compte plus
        self.assertEqual(self.acc.perf()["all"]["n"], 2)                                             # mais les statistiques gardent tous les trades
        self.acc.undo()
        self.acc.undo()                                                                              # on annule le trade puis le passage
        self.assertEqual(self.acc.snapshot("2026-10-12")["stage"], "eval")
        self.assertEqual(self.acc.snapshot("2026-10-12")["profit"], 1_400)

    def test_payout_flow_and_validation(self):
        with self.assertRaises(AccountError):
            self.acc.add_payout(500)                                                                 # pas de retrait en evaluation
        self.acc.start_funded(t=utc(2026, 10, 5, 15))
        for day, out in ((5, 25_030), (6, 25_040), (7, 25_050), (8, 25_040), (9, 25_050)):           # 5 jours : 600, 800, 1 000, 800, 1 000 $
            self.acc.add_trade("NQ", "long", 1, 25_000, out, t=utc(2026, 10, day, 15), fees=0)
        s = self.acc.snapshot("2026-10-12")
        self.assertEqual(s["balance"], 25_000 + 600 + 800 + 1_000 + 800 + 1_000)
        self.assertTrue(s["payout"]["eligible"])
        for bad in (0, -5, "abc", None):
            with self.assertRaises(AccountError):
                self.acc.add_payout(bad)
        rec = self.acc.add_payout(1_000, t=self.now, note="premier retrait")
        self.assertEqual((rec["kind"], rec["amount"], rec["day"]), ("payout", 1_000.0, "2026-10-12"))
        s = self.acc.snapshot("2026-10-12")
        self.assertEqual((s["balance"], s["floor"], s["paid"]), (29_200 - 1_000, 25_100, 1_000))      # 4 200 $ de profit, 1 000 $ retires
        self.assertEqual(s["payout"]["done"], 1)
        self.assertEqual(len(s["payouts"]), 1)
        self.assertEqual([r["kind"] for r in s["records"]], ["payout"])                              # le retrait du jour apparait dans le journal du jour
        self.assertEqual(Account(self.path, now_ms=lambda: self.now).snapshot("2026-10-12")["balance"], 28_200)   # relu depuis le fichier
        self.assertEqual(self.acc.day_pnls(), {"2026-10-05": 600.0, "2026-10-06": 800.0, "2026-10-07": 1000.0, "2026-10-08": 800.0, "2026-10-09": 1000.0})   # un retrait n'est pas un P&L

    def test_default_fees_are_lucids_table(self):
        self.assertEqual((P.fee_rt["NQ"], P.fee_rt["MNQ"]), (3.50, 1.00))                        # 1,75 $ et 0,50 $ par cote

    def test_micro_scalping_share(self):
        for out, hold in ((25_010, 3), (25_020, 120), (24_995, 2), (25_005, None)):               # gains : 20 $ en 3 s, 40 $ en 120 s, 5 $ sans duree ; une perte
            self.acc.add_trade("MNQ", "long", 1, 25_000, out, t=self.now, fees=0, hold_s=hold)
        m = self.acc.micro()
        self.assertEqual((m["trades"], m["known"], m["unknown"]), (4, 3, 1))
        self.assertEqual(m["wins"], 20 + 40 + 10)
        self.assertEqual(m["shortWins"], 20)                                                      # seul le trade gagnant de 3 s compte
        self.assertAlmostEqual(m["shareMin"], 20 / 70)
        self.assertEqual(self.acc.snapshot("2026-10-12")["micro"]["known"], 3)
        self.assertEqual(self.acc.records[0]["hold_s"], 3.0)
        self.assertIsNone(self.acc.records[3]["hold_s"])
        self.assertEqual(Account(Path(self.dir.name) / "vide2.json").micro()["shareMin"], None)

    def test_hold_seconds_are_validated(self):
        for bad in ("abc", -1):
            with self.assertRaises(AccountError):
                self.acc.add_trade("NQ", "long", 1, 25_000, 25_001, hold_s=bad)
        self.assertEqual(self.acc.records, [])
        self.assertEqual(self.acc.add_trade("NQ", "long", 1, 25_000, 25_001, t=self.now, hold_s="")["hold_s"], None)
        self.assertEqual(self.acc.add_trade("NQ", "long", 1, 25_000, 25_001, t=self.now, hold_s="7,5".replace(",", "."))["hold_s"], 7.5)

    def test_perf(self):
        for out, setup in ((25_010, "vwap"), (24_995, "vwap"), (25_020, "ib"), (24_990, "ib")):
            self.acc.add_trade("MNQ", "long", 2, 25_000, out, t=self.now, setup=setup, fees=0)
        p = self.acc.perf()
        self.assertEqual(p["all"]["n"], 4)
        self.assertAlmostEqual(p["all"]["winRate"], 0.5)
        self.assertEqual(p["bySetup"]["vwap"]["n"], 2)
        self.assertAlmostEqual(p["bySetup"]["vwap"]["expectancy"], (40 - 20) / 2)
        self.assertEqual(Account(Path(self.dir.name) / "vide.json").perf()["all"], {"n": 0})


if __name__ == "__main__":
    unittest.main()
