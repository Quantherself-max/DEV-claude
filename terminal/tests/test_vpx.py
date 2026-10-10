import math, random, unittest
from datetime import datetime, timezone

from engine import vpx, vwapx
from engine.atr import Candle

H = 3_600_000
D = 86_400_000


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


class SpecTests(unittest.TestCase):
    def test_normalize_valid_and_dedup(self):
        out = vpx.normalize_specs([{"kind": "auto"}, {"kind": "rolling", "days": "14"}, {"kind": "rolling", "days": 14},
                                   {"kind": "since", "date": "2025-03-01"}, {"kind": "period", "period": "month", "back": 1}])
        self.assertEqual([s["kind"] for s in out], ["auto", "rolling", "since", "period"])
        self.assertEqual(out[1]["days"], 14)

    def test_normalize_rejects_garbage(self):
        bad = [None, [], "x", [{"kind": "rolling", "days": 0}], [{"kind": "rolling", "days": 99999}], [{"kind": "since", "date": "2025-13-40"}],
               [{"kind": "since", "date": "2999-01-01"}], [{"kind": "period", "period": "decade", "back": 0}],
               [{"kind": "period", "period": "month", "back": 99}], [{"kind": "autre"}], ["texte"], [{"kind": "auto"}] * 1 + [{"kind": "rolling", "days": i + 1} for i in range(9)]]
        for b in bad:
            with self.assertRaises(ValueError, msg=str(b)):
                vpx.normalize_specs(b)
        self.assertEqual(vpx.normalize_anchors(["2025-01-01", "2025-01-01", "2025-06-15"]), ["2025-01-01", "2025-06-15"])
        self.assertEqual(vpx.normalize_anchors(None), [])
        with self.assertRaises(ValueError):
            vpx.normalize_anchors(["pas une date"])
        with self.assertRaises(ValueError):
            vpx.normalize_anchors(["2025-01-01"] * 1 + [f"2025-0{i}-01" for i in range(1, 8)])

    def test_period_bounds(self):
        now = ms(2026, 10, 4, 12)                                 # dimanche
        self.assertEqual(vpx.period_bounds("day", 0, now), (ms(2026, 10, 4), ms(2026, 10, 5)))
        self.assertEqual(vpx.period_bounds("week", 0, now), (ms(2026, 9, 28), ms(2026, 10, 5)))
        self.assertEqual(vpx.period_bounds("week", 1, now), (ms(2026, 9, 21), ms(2026, 9, 28)))
        self.assertEqual(vpx.period_bounds("month", 0, now), (ms(2026, 10, 1), ms(2026, 11, 1)))
        self.assertEqual(vpx.period_bounds("month", 1, now), (ms(2026, 9, 1), ms(2026, 10, 1)))
        self.assertEqual(vpx.period_bounds("month", 10, now), (ms(2025, 12, 1), ms(2026, 1, 1)))      # passe l'annee
        self.assertEqual(vpx.period_bounds("quarter", 0, now), (ms(2026, 10, 1), ms(2027, 1, 1)))
        self.assertEqual(vpx.period_bounds("quarter", 1, now), (ms(2026, 7, 1), ms(2026, 10, 1)))
        self.assertEqual(vpx.period_bounds("year", 1, now), (ms(2025, 1, 1), ms(2026, 1, 1)))

    def test_auto_follows_the_timeframe_and_resolve_dedups(self):
        now = ms(2026, 10, 4, 12)
        ids = lambda tf, sp: [w["id"] for w in vpx.resolve(sp, tf, now)]
        self.assertEqual(ids("5m", [{"kind": "auto"}]), ["r3", "r7", "r14"])
        self.assertEqual(ids("1h", [{"kind": "auto"}]), ["r30", "r90", "r180"])
        self.assertEqual(ids("1d", [{"kind": "auto"}]), ["r365", "r730", "r1460"])
        self.assertEqual(ids("1h", [{"kind": "auto"}, {"kind": "rolling", "days": 90}, {"kind": "rolling", "days": 45}]), ["r30", "r90", "r180", "r45"])
        w = vpx.resolve([{"kind": "rolling", "days": 7}], "1h", now + 25 * 60_000)[0]
        self.assertEqual(w["end"], ms(2026, 10, 4, 13))              # fenetre alignee sur l'heure ronde (cache stable)
        self.assertEqual(w["end"] - w["start"], 7 * D + H)
        self.assertEqual(vpx.resolve([{"kind": "period", "period": "month", "back": 1}], "1h", now)[0]["label"], "VP mois -1")
        self.assertEqual(vpx.resolve([{"kind": "since", "date": "2026-09-01"}], "1h", now)[0]["label"], "VP depuis 01/09/26")


class BuildTests(unittest.TestCase):
    def candles(self, n=240, center=100.0, seed=1):
        r = random.Random(seed)
        out, t0 = [], ms(2026, 9, 1)
        for i in range(n):
            c = center + r.gauss(0, 1.2)
            out.append(Candle(t0 + i * H, c, c + 0.4, c - 0.4, c, 100.0 + (400.0 if abs(c - center) < 0.5 else 0), 50.0))
        return out

    def test_poc_value_area_and_window(self):
        cs = self.candles()
        p = vpx.build(cs, cs[0].t, cs[-1].t + H)
        self.assertAlmostEqual(p["poc"], 100.0, delta=0.8)
        self.assertLess(p["val"], p["poc"])
        self.assertGreater(p["vah"], p["poc"])
        va = sum(v for lo, hi, v in p["rows"] if p["val"] - 0.2 <= (lo + hi) / 2 <= p["vah"] + 0.2)
        self.assertGreater(va / p["volume"], 0.6)                                   # la zone de valeur contient ~70 % du volume
        self.assertEqual(p["bars"], 240)
        self.assertAlmostEqual(p["volume"], sum(k.v for k in cs), places=3)
        half = vpx.build(cs, cs[120].t, cs[-1].t + H)
        self.assertEqual(half["bars"], 120)                                         # seules les bougies de la fenetre comptent
        self.assertIsNone(vpx.build(cs, cs[0].t, cs[1].t))                          # trop peu de bougies
        self.assertIsNone(vpx.build([], 0, 10))

    def test_profile_follows_where_the_volume_is(self):
        a = self.candles(240, 100.0, 2)
        b = self.candles(240, 120.0, 3)
        for k in b:
            k.t += 240 * H
        pa = vpx.build(a + b, a[0].t, a[-1].t + H)
        pb = vpx.build(a + b, b[0].t, b[-1].t + H)
        pab = vpx.build(a + b, a[0].t, b[-1].t + H)
        self.assertAlmostEqual(pa["poc"], 100.0, delta=1.0)
        self.assertAlmostEqual(pb["poc"], 120.0, delta=1.0)
        self.assertLess(pab["val"], pa["poc"] + 1)                                  # le profil combine couvre les deux zones
        self.assertGreater(pab["vah"], pb["poc"] - 1)


class VwapSeriesTests(unittest.TestCase):
    def h1(self, n=24 * 40, seed=5):
        r = random.Random(seed)
        out, p, t0 = [], 100.0, ms(2026, 8, 20)
        for i in range(n):
            p *= math.exp(r.gauss(0, 0.004))
            out.append(Candle(t0 + i * H, p, p * 1.003, p * 0.997, p, 100.0 + r.random() * 50, 50.0))
        return out

    def brute_day_vwap(self, h1, upto):
        d = h1[upto].t // D
        sel = [k for k in h1[:upto + 1] if k.t // D == d]
        return sum((k.h + k.l + k.c) / 3 * k.v for k in sel) / sum(k.v for k in sel)

    def test_daily_vwap_matches_brute_force_and_breaks_at_reset(self):
        h1 = self.h1()
        times = [k.t for k in h1[-200:]]
        s = vwapx.series(h1, times, H, [])
        dv = s["vwap"]["D"]
        base = len(h1) - 200
        for i in (5, 50, 100, 199):
            if (times[i] // D) == (times[i - 1] // D):
                self.assertAlmostEqual(dv[i], self.brute_day_vwap(h1, base + i), places=9)
        first = [i for i in range(1, 200) if times[i] % D == 0]
        self.assertTrue(first)
        self.assertTrue(all(dv[i] is None for i in first))                         # remise a zero : la ligne est coupee
        self.assertTrue(all(sd >= 0 for sd in s["sd"]["D"] if sd is not None))
        self.assertEqual(set(s["vwap"]), {"D", "W", "M", "Y"})

    def test_periods_not_longer_than_a_bar_are_skipped_and_coarse_tf_samples_the_bar_end(self):
        h1 = self.h1()
        daily_times = sorted({k.t // D * D for k in h1})
        s = vwapx.series(h1, daily_times, D, [])
        self.assertNotIn("D", s["vwap"])                                           # un VWAP jour sur un graphique journalier n'a pas de sens
        self.assertIn("W", s["vwap"])
        day = h1[-60].t // D * D
        s4 = vwapx.series(h1, [day + 4 * H, day + 8 * H, day + 12 * H], 4 * H, [])
        self.assertIsNone(s4["vwap"]["D"][0])                                        # 1re bougie du graphique : pas de segment
        self.assertIsNotNone(s4["vwap"]["D"][2])
        sel = [k for k in h1 if day <= k.t < day + 16 * H]                           # valeur prise a la FIN de la bougie 12h-16h
        want = sum((k.h + k.l + k.c) / 3 * k.v for k in sel) / sum(k.v for k in sel)
        self.assertAlmostEqual(s4["vwap"]["D"][2], want, places=9)

    def test_anchored_vwap_is_cumulative_from_the_anchor(self):
        h1 = self.h1()
        anchor = h1[100].t
        s = vwapx.series(h1, [k.t for k in h1], H, [("AVWAP test", anchor)])
        av = s["avwap"][0]
        self.assertEqual(av["label"], "AVWAP test")
        self.assertIsNone(av["v"][50])                                             # avant l'ancrage : pas de valeur
        sel = h1[100:151]
        want = sum((k.h + k.l + k.c) / 3 * k.v for k in sel) / sum(k.v for k in sel)
        self.assertAlmostEqual(av["v"][150], want, places=9)
        self.assertEqual(vwapx.series(h1, [k.t for k in h1[:50]], H, [("futur", anchor)])["avwap"], [])   # ancrage apres le graphique : ignore

    def test_auto_anchors(self):
        a = vwapx.auto_anchors(ms(2026, 1, 15))
        self.assertEqual([x[1] for x in a], [ms(2025, 1, 1), ms(2025, 12, 1)])


if __name__ == "__main__":
    unittest.main()
