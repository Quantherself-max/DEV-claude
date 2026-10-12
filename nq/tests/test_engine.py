import math
import random
import unittest
from datetime import datetime, timezone

from engine import clock, cvd, footprint, instruments, vp, vwap
from engine.bars import Bar, BarSeries, SideClassifier, Tick, atr, resample

MIN = 60_000


def utc(y, m, d, hh=0, mm=0, ss=0):
    return int(datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp() * 1000)


class ClockTests(unittest.TestCase):
    def test_dst_boundaries_2026(self):
        # Etats-Unis : 8 mars 2026 7 h UTC -> 1er novembre 2026 6 h UTC
        self.assertFalse(clock.us_dst(utc(2026, 3, 8, 6, 59)))
        self.assertTrue(clock.us_dst(utc(2026, 3, 8, 7, 0)))
        self.assertTrue(clock.us_dst(utc(2026, 11, 1, 5, 59)))
        self.assertFalse(clock.us_dst(utc(2026, 11, 1, 6, 0)))
        # Europe : 29 mars 2026 1 h UTC -> 25 octobre 2026 1 h UTC
        self.assertFalse(clock.eu_dst(utc(2026, 3, 29, 0, 59)))
        self.assertTrue(clock.eu_dst(utc(2026, 3, 29, 1, 0)))
        self.assertTrue(clock.eu_dst(utc(2026, 10, 25, 0, 59)))
        self.assertFalse(clock.eu_dst(utc(2026, 10, 25, 1, 0)))

    def test_ny_open_in_paris(self):
        # cas normal (les deux en heure d'ete) : 9 h 30 ET = 15 h 30 a Paris
        t = clock.et_to_utc(2026, 10, 12, 9, 30)
        self.assertEqual(t, utc(2026, 10, 12, 13, 30))
        self.assertEqual(clock.fmt_hm(t, "paris"), "15:30")
        self.assertEqual(clock.fmt_hm(t, "et"), "09:30")
        # decalage de mars : New York est deja a l'heure d'ete, pas Paris -> 14 h 30
        t = clock.et_to_utc(2026, 3, 16, 9, 30)
        self.assertEqual(clock.fmt_hm(t, "paris"), "14:30")
        # hiver : 9 h 30 ET = 15 h 30 a Paris
        t = clock.et_to_utc(2026, 12, 7, 9, 30)
        self.assertEqual(clock.fmt_hm(t, "paris"), "15:30")

    def test_et_roundtrip(self):
        for t in (utc(2026, 1, 15, 14, 30), utc(2026, 7, 15, 13, 30), utc(2026, 3, 9, 13, 30), utc(2026, 11, 2, 14, 30)):
            w = clock.et(t)
            self.assertEqual(clock.et_to_utc(w.year, w.month, w.day, w.hour, w.minute), t)

    def test_open_and_trading_day(self):
        self.assertFalse(clock.is_open(utc(2026, 10, 10, 15)))                     # samedi
        self.assertFalse(clock.is_open(utc(2026, 10, 11, 21, 59)))                 # dimanche 17 h 59 ET
        self.assertTrue(clock.is_open(utc(2026, 10, 11, 22, 0)))                   # dimanche 18 h ET
        self.assertFalse(clock.is_open(utc(2026, 10, 12, 21, 30)))                 # lundi 17 h 30 ET : pause
        self.assertTrue(clock.is_open(utc(2026, 10, 12, 22, 0)))                   # lundi 18 h ET
        self.assertFalse(clock.is_open(utc(2026, 10, 9, 21, 0)))                   # vendredi 17 h ET : ferme
        self.assertEqual(clock.trading_day(utc(2026, 10, 11, 22, 0)), "2026-10-12")  # le dimanche soir appartient au lundi
        self.assertEqual(clock.trading_day(utc(2026, 10, 12, 13, 30)), "2026-10-12")
        self.assertEqual(clock.trading_day(utc(2026, 10, 12, 22, 0)), "2026-10-13")
        self.assertEqual(clock.prev_day("2026-10-12"), "2026-10-09")               # lundi -> vendredi
        self.assertEqual(clock.next_day("2026-10-09"), "2026-10-12")

    def test_windows(self):
        a, b = clock.window("2026-10-12", "rth")
        self.assertEqual((a, b), (utc(2026, 10, 12, 13, 30), utc(2026, 10, 12, 20, 0)))
        a, b = clock.window("2026-10-12", "ib")
        self.assertEqual(b - a, 60 * MIN)
        a, b = clock.window("2026-10-12", "globex")
        self.assertEqual(a, utc(2026, 10, 11, 22, 0))                              # dimanche 18 h ET
        self.assertEqual(b, utc(2026, 10, 12, 21, 0))
        a, b = clock.window("2026-10-13", "on")
        self.assertEqual(a, utc(2026, 10, 12, 22, 0))

    def test_phase_and_marks(self):
        self.assertEqual(clock.phase(utc(2026, 10, 12, 13, 30))["key"], "open")
        self.assertTrue(clock.phase(utc(2026, 10, 12, 13, 30))["rth"])
        self.assertEqual(clock.phase(utc(2026, 10, 12, 16, 0))["key"], "lunch")     # 12 h ET
        self.assertEqual(clock.phase(utc(2026, 10, 12, 6, 0))["key"], "asia")       # 6 h UTC = 2 h ET : encore l'Asie
        self.assertEqual(clock.phase(utc(2026, 10, 12, 8, 0))["key"], "london")     # 4 h ET
        self.assertEqual(clock.phase(utc(2026, 10, 12, 21, 30))["key"], "break")
        self.assertEqual(clock.phase(utc(2026, 10, 10, 12))["key"], "closed")
        marks = clock.next_marks(utc(2026, 10, 12, 13, 0), 3)
        self.assertEqual(marks[0][0], "Ouverture de New York")
        self.assertEqual(marks[0][1], utc(2026, 10, 12, 13, 30))
        self.assertEqual([m[0] for m in marks][:3], ["Ouverture de New York", "Annonces US de 10 h", "Fin de l'initial balance"])


    def test_lucid_forced_flat_mark(self):
        self.assertEqual(clock.forced_flat("2026-10-12"), utc(2026, 10, 12, 20, 45))             # 16 h 45 ET = 20 h 45 UTC = 22 h 45 a Paris
        self.assertEqual(clock.fmt_hm(clock.forced_flat("2026-10-12"), "paris"), "22:45")
        self.assertEqual(clock.fmt_hm(clock.forced_flat("2026-10-27"), "paris"), "21:45")        # semaine du decalage des changements d'heure
        marks = clock.next_marks(utc(2026, 10, 12, 19, 0), 3)                                     # 15 h ET
        self.assertEqual([m[0] for m in marks], ["Clôture de New York", "Fermeture forcée des comptes Lucid (16 h 45 ET)", "Pause quotidienne"])
        self.assertEqual(marks[1][1], utc(2026, 10, 12, 20, 45))


class InstrumentTests(unittest.TestCase):
    def test_specs(self):
        nq, mnq = instruments.NQ, instruments.MNQ
        self.assertEqual(nq.tick_value, 5.0)
        self.assertEqual(mnq.tick_value, 0.5)
        self.assertEqual(nq.dollars(10, 2), 400.0)
        self.assertEqual(nq.idx(25000.25), 100001)
        self.assertEqual(nq.price(100001), 25000.25)
        self.assertEqual(nq.snap(25000.1), 25000.0)
        self.assertEqual(nq.snap(25000.13), 25000.25)
        with self.assertRaises(ValueError):
            instruments.get("XYZ")

    def test_front_contract(self):
        self.assertEqual(instruments.third_friday(2026, 12).isoformat(), "2026-12-18")
        self.assertEqual(instruments.third_friday(2026, 9).isoformat(), "2026-09-18")
        self.assertEqual(instruments.front_contract(utc(2026, 10, 12, 15)).code, "NQZ6")
        self.assertEqual(instruments.front_contract(utc(2026, 9, 9, 15)).code, "NQU6")
        self.assertEqual(instruments.front_contract(utc(2026, 9, 10, 12)).code, "NQZ6")   # apres le roll estime (jeudi 10 septembre)
        self.assertEqual(instruments.front_contract(utc(2026, 12, 15, 12), "MNQ").code, "MNQH7")
        self.assertEqual(instruments.front_contract(utc(2026, 10, 12, 15)).code_long, "NQZ26")


class BarTests(unittest.TestCase):
    def test_tick_rule(self):
        c = SideClassifier()
        sides = [c(Tick(0, p, 1)) for p in (100.0, 100.25, 100.25, 100.0, 100.0, 100.5)]
        self.assertEqual(sides, [1, 1, 1, -1, -1, 1])           # 1re = defaut acheteur ; prix inchange = cote precedent
        self.assertEqual(c(Tick(0, 100.5, 1, -1)), -1)           # un cote fourni par la bourse est garde
        self.assertEqual(c.estimated, 6)
        self.assertAlmostEqual(c.real_share, 1 / 7)

    def test_bar_series_and_conservation(self):
        s = BarSeries(MIN, 0.25)
        t0 = utc(2026, 10, 12, 13, 30)
        ticks = [Tick(t0 + 1000, 100.0, 2, 1), Tick(t0 + 2000, 100.5, 3, 1), Tick(t0 + 3000, 99.75, 4, -1),
                 Tick(t0 + MIN + 10, 100.0, 5, -1), Tick(t0 + 3 * MIN, 101.0, 1, 1)]
        for tk in ticks:
            s.add(tk, tk.side)
        self.assertEqual(len(s.bars), 3)                           # pas de barre vide entre deux transactions
        b = s.bars[0]
        self.assertEqual((b.o, b.h, b.l, b.c, b.v, b.bv, b.sv, b.n), (100.0, 100.5, 99.75, 99.75, 9, 5, 4, 3))
        self.assertEqual(b.delta, 1)
        self.assertAlmostEqual(b.pv, 100 * 2 + 100.5 * 3 + 99.75 * 4)
        self.assertEqual(sum(sum(r) for r in b.fp.values()), b.v)   # le footprint garde tout le volume
        # transaction en retard : rangee dans sa barre, sans changer la cloture
        s.add(Tick(t0 + 5000, 100.25, 7, 1), 1)
        self.assertEqual(s.bars[0].v, 16)
        self.assertEqual(s.bars[0].c, 99.75)
        self.assertIsNone(s.add(Tick(t0 + 2 * MIN, 100.0, 1, 1), 1) and None)   # barre inexistante entre deux : ignoree sans erreur

    def test_resample_conserves(self):
        rnd = random.Random(3)
        s = BarSeries(MIN, 0.25)
        t = utc(2026, 10, 12, 13, 30)
        p = 25000.0
        for k in range(600):
            p += rnd.choice((-0.25, 0.0, 0.25))
            tk = Tick(t + k * 7_000, p, rnd.randint(1, 9), rnd.choice((-1, 1)))
            s.add(tk, tk.side)
        r5 = resample(s.bars, 5 * MIN, with_fp=True)
        self.assertEqual(sum(b.v for b in r5), sum(b.v for b in s.bars))
        self.assertEqual(sum(b.bv - b.sv for b in r5), sum(b.bv - b.sv for b in s.bars))
        self.assertEqual(sum(sum(sum(r) for r in b.fp.values()) for b in r5), sum(b.v for b in s.bars))
        self.assertEqual(r5[0].o, s.bars[0].o)
        self.assertEqual(r5[0].t % (5 * MIN), 0)
        self.assertEqual(max(b.h for b in r5), max(b.h for b in s.bars))
        self.assertTrue(atr(r5) > 0)


class FootprintTests(unittest.TestCase):
    def test_imbalances_and_stack(self):
        fp = {100: [10, 2], 101: [3, 30], 102: [2, 40], 103: [1, 35], 104: [5, 5]}
        im = footprint.imbalances(fp, ratio=3.0, min_vol=5)
        self.assertEqual(im["buy"], [101, 102, 103, 104])
        self.assertEqual(im["sell"], [])
        self.assertEqual(im["stacks"], [(1, 101, 104)])
        sell = {100: [40, 1], 101: [35, 2], 102: [30, 3], 103: [1, 1]}
        im = footprint.imbalances(sell, ratio=3.0, min_vol=5)
        self.assertEqual(im["sell"], [100, 101, 102])
        self.assertEqual(im["stacks"], [(-1, 100, 102)])

    def test_poc_and_ladder(self):
        fp = {10: [1, 1], 11: [5, 5], 12: [2, 2]}
        self.assertEqual(footprint.poc_of(fp), 11)
        self.assertEqual(footprint.delta_of({1: [3, 7], 2: [4, 1]}), 1)
        lad = footprint.Ladder(0.25)
        lad.add_rows(fp)
        lad.add_trade(11, 1, 4)
        self.assertEqual(lad.volume, 2 + 10 + 4 + 4)
        self.assertEqual(lad.delta, (1 + 5 + 2 + 4) - (1 + 5 + 2))
        self.assertAlmostEqual(lad.vwap, (10 * 2 + 11 * 14 + 12 * 4) / 20 * 0.25)
        self.assertEqual((lad.lo, lad.hi), (2.5, 3.0))


class VolumeProfileTests(unittest.TestCase):
    def triangle(self, centre=100_000, half=40, scale=50):
        lad = footprint.Ladder(0.25)
        for d in range(-half, half + 1):
            v = max(1, scale - abs(d))
            lad.rows[centre + d] = [v / 2, v / 2]
            lad.s0 += v
        lad.bv = lad.sv = lad.s0 / 2
        return lad

    def test_symmetric_profile(self):
        lad = self.triangle()
        st = vp.stats(lad, row_ticks=4)
        self.assertAlmostEqual(st["poc"], 25000.0, delta=0.5)
        self.assertAlmostEqual(st["vah"] - st["poc"], st["poc"] - st["val"], delta=1.5)
        inside = sum(r["s"] + r["b"] for r in st["rows"] if r["va"])
        self.assertGreaterEqual(inside / st["total"], 0.70)
        self.assertLess(inside / st["total"], 0.85)
        self.assertAlmostEqual(sum(r["s"] + r["b"] for r in st["rows"]), st["total"])
        self.assertEqual(sum(1 for r in st["rows"] if r["poc"]), 1)
        self.assertEqual(st["rowPts"], 1.0)

    def test_rows_conserve_and_alignment(self):
        lad = self.triangle(half=60)
        for rt in (1, 2, 4, 8, 20):
            r0, rows = vp.rows_of(lad.rows, rt)
            self.assertAlmostEqual(sum(s + b for s, b in rows), lad.volume)
            self.assertEqual(r0, min(lad.rows) // rt)

    def test_auto_row_ticks_and_empty(self):
        self.assertEqual(vp.auto_row_ticks(100), 1)
        self.assertEqual(vp.auto_row_ticks(600), 8)
        self.assertEqual(vp.auto_row_ticks(10 ** 6), 400)
        self.assertIsNone(vp.stats(footprint.Ladder(0.25)))

    def test_two_peaks_give_hvn_and_lvn(self):
        lad = footprint.Ladder(0.25)
        for d in range(0, 120):
            v = 100 * math.exp(-((d - 25) ** 2) / 60) + 100 * math.exp(-((d - 95) ** 2) / 60) + 1
            lad.rows[100_000 + d] = [v / 2, v / 2]
            lad.s0 += v
        st = vp.stats(lad, row_ticks=2)
        self.assertEqual(len(st["hvn"]), 2)
        self.assertEqual(len(st["lvn"]), 1)
        self.assertTrue(st["hvn"][0] < st["lvn"][0] < st["hvn"][1])

    def test_value_area_edges(self):
        self.assertEqual(vp.value_area([5], 0), (0, 0))
        up, dn = vp.value_area([1, 1, 50, 1, 1], 2, 0.70)
        self.assertEqual((up, dn), (2, 2))                          # le POC porte deja plus de 70 %


class VwapTests(unittest.TestCase):
    def build(self):
        rnd = random.Random(11)
        s = BarSeries(MIN, 0.25)
        lad = footprint.Ladder(0.25)
        t = clock.window("2026-10-12", "rth")[0]
        p, ticks = 25000.0, []
        for k in range(900):
            p = round((p + rnd.choice((-0.5, -0.25, 0.0, 0.25, 0.5))) * 4) / 4
            tk = Tick(t + k * 5_000, p, rnd.randint(1, 20), rnd.choice((-1, 1)))
            ticks.append(tk)
            s.add(tk, tk.side)
            lad.add_trade(int(round(tk.p / 0.25)), tk.side, tk.q)
        return s, lad, ticks

    def test_matches_direct_formula_and_ladder(self):
        s, lad, ticks = self.build()
        vals = vwap.cumulative(s.bars, vwap.key_rth)
        m, sd = vals[-1]
        q = sum(tk.q for tk in ticks)
        mean = sum(tk.p * tk.q for tk in ticks) / q
        var = sum(tk.q * (tk.p - mean) ** 2 for tk in ticks) / q
        self.assertAlmostEqual(m, mean, places=6)
        self.assertAlmostEqual(sd, math.sqrt(var), places=5)
        self.assertAlmostEqual(lad.vwap, mean, places=6)
        self.assertAlmostEqual(lad.sd, math.sqrt(var), places=5)

    def test_reset_and_gaps(self):
        s = BarSeries(MIN, 0.25)
        a = clock.window("2026-10-12", "rth")[0]
        for tk in (Tick(a - 10 * MIN, 100.0, 5, 1), Tick(a + 10, 200.0, 5, 1), Tick(a + MIN + 10, 300.0, 5, 1),
                   Tick(clock.window("2026-10-13", "rth")[0] + 10, 50.0, 5, 1)):
            s.add(tk, tk.side)
        vals = vwap.cumulative(s.bars, vwap.key_rth)
        self.assertEqual(vals[0], (None, None))                       # avant l'ouverture : hors seance
        self.assertAlmostEqual(vals[1][0], 200.0)
        self.assertAlmostEqual(vals[2][0], 250.0)
        self.assertAlmostEqual(vals[3][0], 50.0)                      # nouvelle seance : remise a zero
        anch = vwap.cumulative(s.bars, anchor_ms=a + MIN)
        self.assertEqual(anch[1], (None, None))
        self.assertAlmostEqual(anch[2][0], 300.0)

    def test_sample_and_bands(self):
        s, _, _ = self.build()
        base = vwap.cumulative(s.bars, vwap.key_rth)
        c5 = resample(s.bars, 5 * MIN)
        out = vwap.sample(s.bars, base, c5, 5 * MIN)
        self.assertEqual(len(out), len(c5))
        last_in_first = max(i for i, b in enumerate(s.bars) if b.t < c5[0].t + 5 * MIN)
        self.assertEqual(out[0], base[last_in_first])
        bd = vwap.bands(out)
        self.assertEqual(len(bd["v"]), len(c5))
        i = 2
        self.assertAlmostEqual(bd["u2"][i] - bd["v"][i], bd["v"][i] - bd["l2"][i], places=3)
        self.assertEqual(vwap.bands([None])["u1"], [None])


def mk(t, o, h, l, c, v, bv, sv):
    b = Bar(t, o)
    b.h, b.l, b.c, b.v, b.bv, b.sv = h, l, c, v, bv, sv
    return b


class CvdTests(unittest.TestCase):
    def test_cumulative_reset(self):
        a = clock.window("2026-10-12", "rth")[0]
        bars = [mk(a - MIN, 1, 1, 1, 1, 10, 9, 1), mk(a, 1, 1, 1, 1, 10, 7, 3), mk(a + MIN, 1, 1, 1, 1, 10, 2, 8),
                mk(clock.window("2026-10-13", "rth")[0], 1, 1, 1, 1, 4, 4, 0)]
        out = cvd.cumulative(bars, vwap.key_rth)
        self.assertEqual(out, [None, 4, -2, 4])
        gx = cvd.cumulative(bars[:3], vwap.key_globex)
        self.assertEqual(gx, [8, 12, 6])

    def test_bull_divergence(self):
        lows = [105, 104, 103, 100, 103, 104, 105, 104, 103, 99, 103, 104, 105, 106, 107, 108]
        bars = [mk(i * MIN, l + 1, l + 2, l, l + 1, 10, 5, 5) for i, l in enumerate(lows)]
        cv = [0.0] * len(bars)
        cv[3], cv[9] = -50.0, -30.0
        side, force = cvd.divergence(bars, cv, 15)
        self.assertEqual(side, "bull")
        self.assertEqual(force, 1.0)
        cv[9] = -80.0                                                 # CVD plus bas aussi : pas de divergence
        self.assertEqual(cvd.divergence(bars, cv, 15)[0], None)

    def test_bear_divergence(self):
        highs = [90, 91, 92, 95, 92, 91, 90, 91, 92, 96, 92, 91, 90, 89, 88, 87]
        bars = [mk(i * MIN, h - 1, h, h - 3, h - 1, 10, 5, 5) for i, h in enumerate(highs)]
        cv = [0.0] * len(bars)
        cv[3], cv[9] = 50.0, 20.0
        self.assertEqual(cvd.divergence(bars, cv, 15)[0], "bear")

    def test_absorption(self):
        rnd = random.Random(5)
        bars = [mk(i * MIN, 100, 101, 99, 100, 100, 50 + rnd.randint(-5, 5), 50 + rnd.randint(-5, 5)) for i in range(80)]
        bars[70] = mk(70 * MIN, 100, 101, 98, 100.5, 300, 50, 250)       # enorme delta vendeur mais la barre monte
        self.assertEqual(cvd.absorption(bars, 70), "bull")
        bars[71] = mk(71 * MIN, 100, 102, 99, 99.5, 300, 250, 50)        # enorme delta acheteur mais la barre baisse
        self.assertEqual(cvd.absorption(bars, 71), "bear")
        bars[72] = mk(72 * MIN, 100, 102, 99, 101.5, 300, 250, 50)       # delta et prix vont dans le meme sens : pas d'absorption
        self.assertIsNone(cvd.absorption(bars, 72))
        self.assertIsNone(cvd.absorption(bars, 10))                       # pas assez d'historique
        sides = cvd.marks(bars)
        self.assertIn((70, "bull"), sides)
        self.assertIn((71, "bear"), sides)

    def test_imbalance(self):
        bars = [mk(0, 1, 1, 1, 1, 10, 8, 2), mk(MIN, 1, 1, 1, 1, 10, 2, 8)]
        self.assertEqual(cvd.imbalance(bars, 2), 0.0)
        self.assertAlmostEqual(cvd.imbalance(bars, 1), -0.6)


if __name__ == "__main__":
    unittest.main()
