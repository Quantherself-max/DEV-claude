import json
import tempfile
import unittest
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

    def test_daily_loss_limit_breach_when_configured(self):
        p = risk.PropProfile.from_dict({"daily_loss_limit": 500})
        self.assertTrue(risk.state([], -500, 0, p)["breached"])
        self.assertFalse(risk.state([], -499, 0, p)["breached"])


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
