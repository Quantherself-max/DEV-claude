"""Tests V0.5 : absorptions au prix, profils composites semaine / mois, POC vierges, single prints, VWAP semaine / mois."""
import tempfile
import unittest
from datetime import datetime, timezone

from config import Config
from data.simulated import SimulatedSource
from engine import absorption, clock, profiles, vwap
from engine.account import Account
from engine.bars import Bar, Tick
from engine.instruments import NQ
from engine.market import Market
from service import Service

TICK = NQ.tick
MIN = 60_000


def utc(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp() * 1000)


def fpbar(t, o, h, l, c, fp):
    """Barre dont volumes et delta viennent de son footprint {indice de tick: [vendeur, acheteur]}."""
    b = Bar(t, o)
    b.h, b.l, b.c = h, l, c
    b.fp = {k: list(v) for k, v in fp.items()}
    b.sv = sum(v[0] for v in fp.values())
    b.bv = sum(v[1] for v in fp.values())
    b.v = b.sv + b.bv
    b.pv = sum((s + q) * k * TICK for k, (s, q) in fp.items())
    b.pv2 = sum((s + q) * (k * TICK) ** 2 for k, (s, q) in fp.items())
    return b


def calm(n, t0, p=100.0):
    """n barres ordinaires : 4 ticks d'étendue, 5 vendeurs + 5 acheteurs par tick."""
    i0 = int(round(p / TICK))
    return [fpbar(t0 + k * MIN, p, p + 3 * TICK, p, p + TICK, {i0 + j: [5, 5] for j in range(4)}) for k in range(n)]


class AbsorptionTests(unittest.TestCase):
    T0 = utc(2026, 10, 13, 14, 0)

    def test_sellers_absorbed_at_the_low_is_bullish(self):
        bars = calm(60, self.T0)
        i0 = int(round(99.0 / TICK))
        # gros flux vendeur sur les 2 ticks du bas, mais clôture en haut de la barre
        fp = {i0: [40, 2], i0 + 1: [30, 3], i0 + 2: [3, 4], i0 + 3: [2, 5], i0 + 4: [2, 6]}
        bars.append(fpbar(self.T0 + 60 * MIN, 99.5, 100.0, 99.0, 99.9, fp))
        r = absorption.detect(bars, 60, TICK)
        self.assertIsNotNone(r)
        self.assertEqual(r["side"], "bull")
        self.assertTrue(r["kind"].startswith("niveau"))
        self.assertTrue(99.0 <= r["price"] <= 99.25)
        self.assertGreaterEqual(r["qty"], 70)

    def test_buyers_absorbed_at_the_high_is_bearish(self):
        bars = calm(60, self.T0)
        i0 = int(round(100.0 / TICK))
        fp = {i0: [6, 2], i0 + 1: [5, 3], i0 + 2: [4, 3], i0 + 3: [3, 35], i0 + 4: [2, 45]}
        bars.append(fpbar(self.T0 + 60 * MIN, 100.5, 101.0, 100.0, 100.1, fp))
        r = absorption.detect(bars, 60, TICK)
        self.assertEqual(r["side"], "bear")

    def test_no_absorption_when_price_follows_the_flow(self):
        bars = calm(60, self.T0)
        i0 = int(round(99.0 / TICK))
        fp = {i0: [40, 2], i0 + 1: [30, 3], i0 + 2: [3, 4], i0 + 3: [2, 5], i0 + 4: [2, 6]}
        bars.append(fpbar(self.T0 + 60 * MIN, 100.0, 100.0, 99.0, 99.0, fp))         # clôture sur le plus bas : les vendeurs ont gagné
        self.assertIsNone(absorption.detect(bars, 60, TICK))

    def test_not_enough_history(self):
        self.assertIsNone(absorption.detect(calm(10, self.T0), 9, TICK))

    def test_scan_matches_detect_and_cache_is_stable(self):
        mk = Market(NQ)
        now = utc(2026, 10, 13, 20, 0)
        mk.ingest_many(SimulatedSource(days=2, now_fn=lambda: now).history(now))
        bars = mk.series.bars
        known = {}
        a = absorption.scan(bars, TICK, known=known)
        b = absorption.scan(bars, TICK, known=known)
        self.assertEqual(a, b)
        self.assertNotIn(bars[-1].t, known)                          # la barre qui se forme n'est jamais gardée
        self.assertEqual([m["i"] for m in a], [i for i in range(len(bars)) if absorption.detect(bars, i, TICK)])
        self.assertTrue({"bull", "bear"} <= {m["side"] for m in a})

    def test_track_break_tests_and_repeat(self):
        bars = calm(60, self.T0)
        i0 = int(round(99.0 / TICK))
        fp = {i0: [40, 2], i0 + 1: [30, 3], i0 + 2: [3, 4], i0 + 3: [2, 5], i0 + 4: [2, 6]}
        bars.append(fpbar(self.T0 + 60 * MIN, 99.5, 100.0, 99.0, 99.9, fp))            # absorption à 99
        t = self.T0 + 61 * MIN
        bars.append(fpbar(t, 101.0, 102.0, 101.0, 102.0, {int(round(101 / TICK)): [1, 1]}))       # s'éloigne (plus d'1 point)
        bars.append(fpbar(t + MIN, 101.0, 101.0, 99.25, 99.5, {int(round(100 / TICK)): [1, 1]}))  # revient tester, tient
        m = absorption.detect(bars, 60, TICK)
        z = absorption.track([dict(m, i=60)], bars, TICK)[0]
        self.assertEqual(z["status"], "active")
        self.assertEqual(z["tests"], 1)
        bars.append(fpbar(t + 2 * MIN, 99.5, 99.5, 97.0, 97.5, {int(round(98 / TICK)): [1, 1]}))  # traverse de 2 points : cassée
        z = absorption.track([dict(m, i=60)], bars, TICK)[0]
        self.assertEqual(z["status"], "cassée")
        # deux absorptions au même prix tant que la première tient : une seule zone, répétée
        z2 = absorption.track([dict(m, i=60), dict(m, i=62, t=bars[62].t)], bars[:63], TICK)
        self.assertEqual(len(z2), 1)
        self.assertEqual(z2[0]["count"], 2)


def tick_at(t, p, q=1, side=1):
    return Tick(t, p, q, side)


def session(mk, day, path, q=5):
    """Une séance régulière : `path` = liste de (minute après 9 h 30, prix) ; un tick acheteur et un vendeur par point."""
    a = clock.window(day, "rth")[0]
    for m, p in path:
        mk.ingest(tick_at(a + m * MIN, p, q, 1))
        mk.ingest(tick_at(a + m * MIN + 1000, p, q, -1))


class ProfileStructureTests(unittest.TestCase):
    def test_week_and_month_composites(self):
        mk = Market(NQ, keep_days=40)
        for d in ("2026-09-29", "2026-09-30", "2026-10-05", "2026-10-06", "2026-10-07"):
            session(mk, d, [(k, 100.0 + (k % 7)) for k in range(0, 300, 5)])
        comp = profiles.Composer()
        lad, label, days = comp.composite(mk, "week", "2026-10-07")
        self.assertEqual(days, ["2026-10-05", "2026-10-06", "2026-10-07"])
        self.assertAlmostEqual(lad.volume, sum(mk.gx[d].volume for d in days))
        _, _, pdays = comp.composite(mk, "pweek", "2026-10-07")
        self.assertEqual(pdays, ["2026-09-29", "2026-09-30"])
        _, _, mdays = comp.composite(mk, "month", "2026-10-07")
        self.assertEqual(mdays, ["2026-10-05", "2026-10-06", "2026-10-07"])
        _, _, pm = comp.composite(mk, "pmonth", "2026-10-07")
        self.assertEqual(pm, ["2026-09-29", "2026-09-30"])
        # le cache des journées passées ne fausse rien quand la journée en cours grossit
        session(mk, "2026-10-07", [(301, 120.0)])
        lad2, _, _ = comp.composite(mk, "week", "2026-10-07")
        self.assertAlmostEqual(lad2.volume, lad.volume + 10)

    def test_naked_poc(self):
        mk = Market(NQ)
        # J1 : POC à 100 ; J2 traite au-dessus de 105 seulement -> le POC de J1 reste vierge ; J3 redescend à 99 -> retouché
        session(mk, "2026-10-12", [(k, 100.0) for k in range(0, 200)] + [(k, 102.0) for k in range(200, 260)])
        session(mk, "2026-10-13", [(k, 106.0 + (k % 3)) for k in range(0, 300)])
        mk.ingest(tick_at(clock.window("2026-10-14", "rth")[0], 107.0, 1, 1))
        n = profiles.naked_pocs(mk, weekly=False)
        self.assertIn(100.0, [x["price"] for x in n])
        session(mk, "2026-10-14", [(5, 99.0)])
        n = profiles.naked_pocs(mk, weekly=False)
        self.assertNotIn(100.0, [x["price"] for x in n])

    def test_single_prints_and_tails(self):
        mk = Market(NQ)
        day = "2026-10-13"
        # 1re demi-heure : 100 -> 110 d'un trait (une seule période), puis 3 h entre 110 et 113 ; retour de 2 points sous 113.. pas sous 110
        path = [(k, 100.0 + k * 0.5) for k in range(0, 21)] + [(k, 110.0 + (k % 4)) for k in range(30, 210)]
        session(mk, day, path)
        mk.ingest(tick_at(clock.window(day, "rth")[0] + 220 * MIN, 111.0))
        sp = profiles.single_prints(mk, day)
        tails = [z for z in sp if z["kind"] == "queue basse"]
        self.assertTrue(tails, sp)
        self.assertLessEqual(tails[0]["lo"], 100.0)
        self.assertGreaterEqual(tails[0]["hi"], 105.0)
        self.assertTrue(tails[0]["current"])

    def test_past_single_print_fill(self):
        mk = Market(NQ)
        day = "2026-10-13"
        # séance : en bas 100–103 longtemps, saut rapide à 110 (single print 104–109), puis 110–113 longtemps
        path = [(k, 100.0 + (k % 4)) for k in range(0, 90)] + [(k, 104.0 + (k - 90) * 1.0) for k in range(90, 96)] \
            + [(k, 110.0 + (k % 4)) for k in range(120, 390)]
        session(mk, day, path)
        session(mk, "2026-10-14", [(0, 112.0), (1, 108.0)])               # le lendemain redescend à 108 : comblé en partie
        sp = [z for z in profiles.single_prints(mk, day) if z["kind"] == "single"]
        self.assertTrue(sp, profiles.single_prints(mk, day))
        self.assertFalse(sp[0]["current"])
        self.assertTrue(0 < sp[0]["filled"] < 1, sp[0])


class VwapAnchorTests(unittest.TestCase):
    def test_offsets_continue_a_week_started_before_the_window(self):
        mk = Market(NQ)
        session(mk, "2026-10-12", [(k, 100.0) for k in range(0, 100)])
        session(mk, "2026-10-13", [(k, 110.0) for k in range(0, 100)])
        bars13 = mk.slice(*clock.window("2026-10-13", "globex"))
        off = {profiles.week_key("2026-10-13"): vwap.ladder_sums([mk.gx["2026-10-12"]], TICK)}
        v = vwap.cumulative(bars13, vwap.key_week, offsets=off)
        self.assertAlmostEqual(v[-1][0], 105.0)                             # même volume les deux jours : moyenne des deux
        v_day = vwap.cumulative(bars13, vwap.key_globex)
        self.assertAlmostEqual(v_day[-1][0], 110.0)

    def test_trading_day_cache_is_exact_around_dst_and_18h(self):
        for t in (utc(2026, 3, 8, 21, 59), utc(2026, 3, 8, 22, 0), utc(2026, 11, 1, 22, 59), utc(2026, 11, 1, 23, 0)):
            w = clock.et(t)
            ref = (w.date() + (__import__("datetime").timedelta(days=1) if w.hour >= 18 else __import__("datetime").timedelta(0))).isoformat()
            self.assertEqual(clock.trading_day(t), ref)


class ServiceStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        now = utc(2026, 10, 15, 18, 30)
        cfg = Config(data_dir=cls.tmp.name, sim_days=8, history_days=10)
        cls.svc = Service(cfg, source=SimulatedSource(days=8, now_fn=lambda: now),
                          account=Account(f"{cls.tmp.name}/c.json", now_ms=lambda: now))
        cls.svc.load_sync()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_bars_carry_week_month_vwap_and_absorption_zones(self):
        b = self.svc.bars("5m", 300)
        n = len(b["bars"])
        self.assertEqual(len(b["vwapWeek"]["v"]), n)
        self.assertEqual(len(b["vwapMonth"]["u1"]), n)
        self.assertIsNotNone(b["vwapWeek"]["v"][-1])
        for z in b["absorptions"]:
            self.assertIn(z["status"], ("active", "cassée", "expirée"))
            self.assertLessEqual(z["lo"], z["price"] + 1e-9)
            self.assertGreaterEqual(z["hi"], z["price"] - 1e-9)
        inc = self.svc.bars("5m", 300, since=b["bars"][-3]["t"] * 1000)
        self.assertEqual(len(inc["vwapWeek"]["v"]), len(inc["bars"]))

    def test_composite_profiles_and_structure_levels(self):
        for w in ("week", "pweek", "month"):
            p = self.svc.profile(w)
            self.assertFalse(p["empty"], w)
            self.assertTrue(p["val"] <= p["poc"] <= p["vah"])
        lv = self.svc.levels()
        names = " | ".join(x["name"] for x in lv["levels"] if x["group"] == "profil")      # deux niveaux au même prix fusionnent leurs noms
        for n in ("POC sem.", "POC sem. préc.", "High sem. préc.", "Low sem. préc.", "VWAP sem."):
            self.assertIn(n, names)
        self.assertIn("singles", lv)

    def test_market_keeps_configured_history(self):
        self.assertGreaterEqual(len(self.svc.market.days()), 8)


if __name__ == "__main__":
    unittest.main()
