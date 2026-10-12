import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from data import filefeed
from data.base import DataError
from data.simulated import SimulatedSource
from engine import clock, cvd
from engine.bars import Tick
from engine.market import Market

MIN = 60_000


def utc(y, m, d, hh=0, mm=0, ss=0):
    return int(datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp() * 1000)


NOW = utc(2026, 10, 12, 16, 40)            # lundi 12 h 40 ET


class SimulatedTests(unittest.TestCase):
    def test_deterministic(self):
        a = SimulatedSource(days=2, now_fn=lambda: NOW).history(NOW)
        b = SimulatedSource(days=2, now_fn=lambda: NOW).history(NOW)
        self.assertEqual(len(a), len(b))
        self.assertEqual(a[:2000], b[:2000])
        self.assertEqual(a[-1], b[-1])

    def test_incremental_equals_batch(self):
        s = SimulatedSource(days=2, now_fn=lambda: NOW)
        hist = s.history(NOW)
        inc = s.poll(NOW + 90_000) + s.poll(NOW + 90_000) + s.poll(NOW + 7 * MIN)
        full = SimulatedSource(days=2, now_fn=lambda: NOW).history(NOW + 7 * MIN)
        self.assertEqual(hist + inc, full)
        self.assertEqual(s.poll(NOW + 7 * MIN), [])                  # rien de nouveau, rien de rejoue

    def test_ticks_are_valid_and_ordered(self):
        ticks = SimulatedSource(days=2, now_fn=lambda: NOW).history(NOW)
        self.assertGreater(len(ticks), 50_000)
        self.assertTrue(all(ticks[i].t <= ticks[i + 1].t for i in range(0, len(ticks) - 1, 997)))
        self.assertTrue(all(abs(t.p / 0.25 - round(t.p / 0.25)) < 1e-9 for t in ticks[::101]))      # sur la grille du tick
        self.assertTrue(all(t.q >= 1 and t.side in (1, -1) for t in ticks[::101]))
        self.assertTrue(all(clock.is_open(t.t) for t in ticks[::53]))                                # jamais pendant la pause
        self.assertTrue(all(ticks[i].p - ticks[i - 1].p < 80 for i in range(1, len(ticks), 211)))    # prix continu
        self.assertLess(ticks[-1].t, NOW + 1)

    def test_weekend_stops_at_friday_close(self):
        sat = utc(2026, 10, 10, 15)
        s = SimulatedSource(now_fn=lambda: sat)
        ticks = s.history(sat)
        self.assertLessEqual(ticks[-1].t, clock.window("2026-10-09", "globex")[1])
        self.assertEqual(s.poll(sat + 5 * MIN), [])

    def test_absorption_episodes_exist(self):
        m = Market()
        m.ingest_many(SimulatedSource(now_fn=lambda: NOW).history(NOW))
        marks = cvd.marks(m.chart_bars(MIN, 0))
        self.assertTrue({"bull", "bear"} <= {s for _, s in marks}, marks)


class MarketTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(MarketTests, "_ticks"):
            MarketTests._ticks = SimulatedSource(days=3, now_fn=lambda: NOW).history(NOW)         # (vendredi, lundi et la veille) genere une seule fois
        self.ticks = MarketTests._ticks
        self.m = Market()
        self.m.ingest_many(self.ticks)

    def test_ladders_match_bars(self):
        day = self.m.day()
        self.assertEqual(day, "2026-10-12")
        a, b = clock.window(day, "rth")
        bars = self.m.slice(a, b)
        lad = self.m.ladder(day, "rth")
        self.assertAlmostEqual(lad.volume, sum(x.v for x in bars))
        self.assertAlmostEqual(lad.delta, sum(x.bv - x.sv for x in bars))
        self.assertAlmostEqual(lad.vwap, sum(x.pv for x in bars) / sum(x.v for x in bars), places=6)
        ga, gb = clock.window(day, "globex")
        self.assertAlmostEqual(self.m.ladder(day, "gx").volume, sum(x.v for x in self.m.slice(ga, gb)))
        self.assertGreater(self.m.ladder(day, "gx").volume, lad.volume)
        self.assertEqual(self.m.count, len(self.ticks))

    def test_prev_day_and_ohlc(self):
        self.assertEqual(self.m.prev_day(), "2026-10-09")            # lundi -> vendredi
        o = self.m.window_ohlc("2026-10-09", "rth")
        self.assertGreater(o["h"], o["l"])
        self.assertTrue(o["l"] <= o["o"] <= o["h"] and o["l"] <= o["c"] <= o["h"])
        self.assertIsNone(self.m.window_ohlc("2026-01-05", "rth"))

    def test_chart_bars_cache_and_resample(self):
        b5 = self.m.chart_bars(5 * MIN, 0)
        self.assertEqual(self.m.chart_bars(5 * MIN, 0)[-1].v, b5[-1].v)
        self.assertEqual(len(self.m.chart_bars(5 * MIN, 10)), 10)
        v = self.m.version
        last = self.m.last
        self.m.ingest(Tick(last.t + 1, last.p, 7, 1))
        self.assertEqual(self.m.version, v + 1)
        self.assertEqual(self.m.chart_bars(5 * MIN, 0)[-1].v, b5[-1].v + 7)                 # le cache a bien ete invalide
        self.assertAlmostEqual(sum(x.v for x in self.m.chart_bars(5 * MIN, 0)), sum(x.v for x in self.m.series.bars))

    def test_ignores_bad_ticks_and_late_ticks(self):
        n = self.m.count
        self.m.ingest(Tick(NOW, 0, 5, 1))
        self.m.ingest(Tick(NOW, 25_000, 0, 1))
        self.assertEqual(self.m.count, n)
        self.m.ingest(Tick(NOW - 5 * MIN - 123, 25_000, 4, -1))                              # en retard mais dans une barre existante
        self.assertEqual(self.m.count, n + 1)
        self.assertGreaterEqual(self.m.last.t, NOW - MIN)

    def test_sunday_evening_belongs_to_monday(self):
        m = Market()
        m.ingest(Tick(utc(2026, 10, 11, 22, 5), 25_000, 3, 1))
        self.assertEqual(m.day(), "2026-10-12")
        self.assertEqual(m.ladder("2026-10-12", "gx").volume, 3)
        self.assertIsNone(m.ladder("2026-10-12", "rth"))

    def test_prune(self):
        m = Market(keep_days=1)                                      # keep_days = journees gardees, la journee en cours comprise
        m.ingest_many(self.ticks)
        self.assertEqual(m.days(), ["2026-10-12"])
        self.assertIsNone(m.prev_day())
        self.assertGreaterEqual(m.series.bars[0].t, clock.window("2026-10-09", "globex")[1])
        full = Market(keep_days=8)
        full.ingest_many(self.ticks)
        self.assertEqual(len(full.days()), 3)                        # rien n'est retire quand tout tient dans la fenetre

    def test_estimated_delta_is_flagged(self):
        m = Market()
        m.ingest_many([Tick(NOW + i * 1000, 25_000 + (i % 3) * 0.25, 2, 0) for i in range(50)])
        self.assertEqual(m.cls.real_share, 0.0)


class FileFeedTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.p = Path(self.dir.name) / "ticks.csv"

    def tearDown(self):
        self.dir.cleanup()

    def test_parse_time_variants(self):
        t = utc(2026, 10, 12, 13, 30, 1)
        self.assertEqual(filefeed.parse_time(str(t)), t)
        self.assertEqual(filefeed.parse_time(str(t // 1000)), t)
        self.assertEqual(filefeed.parse_time(str(t * 1_000_000)), t)
        self.assertEqual(filefeed.parse_time("2026-10-12T13:30:01Z"), t)
        self.assertEqual(filefeed.parse_time("2026-10-12 15:30:01+02:00"), t)
        self.assertEqual(filefeed.parse_time("2026-10-12 09:30:01", "et"), t)
        self.assertEqual(filefeed.parse_time("2026-10-12 15:30:01.250", "paris"), t + 250)
        self.assertEqual(filefeed.parse_time("2026/10/12 13:30:01"), t)
        with self.assertRaises(DataError):
            filefeed.parse_time("pas une heure")

    def test_parse_side_is_explicit(self):
        self.assertEqual([filefeed.parse_side(x) for x in ("B", "buy", "ask", "S", "SELL", "bid", "1", "-1")], [1, 1, 1, -1, -1, -1, 1, -1])
        self.assertEqual([filefeed.parse_side(x) for x in ("A", "", "N", "?")], [0, 0, 0, 0])      # « A » est ambigu : jamais devine
        self.assertEqual(filefeed.parse_side("A", buy_codes=("a",)), 1)
        self.assertEqual(filefeed.parse_side("A", sell_codes=("a",)), -1)

    def test_reads_history_with_header_and_sides(self):
        t = utc(2026, 10, 12, 13, 30)
        self.p.write_text("timestamp,price,size,side\n" + f"{t},25000.25,3,B\n{t + 10},25000.0,2,S\n{t + 20},oops,2,S\n{t + 30},25000.5,0,B\n"
                          + f"{t + 40},25000.5,5,\n", encoding="utf-8")
        src = filefeed.CsvSource(self.p, follow=False)
        ticks = list(src.history(t + MIN))
        self.assertEqual([(x.p, x.q, x.side) for x in ticks], [(25000.25, 3, 1), (25000.0, 2, -1), (25000.5, 5, 0)])
        self.assertEqual(src.parser.bad, 1)                                                   # « oops » refusee ; la quantite 0 est ignoree en silence
        self.assertEqual(src.info()["rows"], 3)

    def test_semicolon_headless_and_bidask(self):
        t = utc(2026, 10, 12, 13, 30)
        self.p.write_text(f"{t};25000.25;3;25000.0;25000.25\n{t + 5};25000.0;2;25000.0;25000.25\n{t + 9};25000.1;1;25000.0;25000.25\n", encoding="utf-8")
        src = filefeed.CsvSource(self.p, columns="time,price,size,bid,ask", follow=False)
        src.parser.delim = ";"
        ticks = list(src.history(t + MIN))
        self.assertEqual([x.side for x in ticks], [1, -1, 0])                                  # a l'ask, au bid, entre les deux

    def test_unrecognised_header(self):
        self.p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        with self.assertRaises(DataError):
            list(filefeed.CsvSource(self.p).history(utc(2026, 10, 12)))
        self.assertFalse(filefeed.selftest_file(self.p)[0])
        self.assertFalse(filefeed.selftest_file(Path(self.dir.name) / "absent.csv")[0])
        with self.assertRaises(DataError):
            list(filefeed.CsvSource(Path(self.dir.name) / "absent.csv").history(0))

    def test_tail_waits_for_complete_lines(self):
        t = utc(2026, 10, 12, 13, 30)
        self.p.write_text(f"time,price,size,side\n{t},25000.25,3,B\n", encoding="utf-8")
        src = filefeed.CsvSource(self.p)
        self.assertEqual(len(list(src.history(t + MIN))), 1)
        self.assertEqual(src.poll(t + MIN), [])
        with open(self.p, "a", encoding="utf-8") as f:
            f.write(f"{t + 1000},25000.5,2,S\n{t + 2000},25000.7")                               # derniere ligne encore incomplete
        got = src.poll(t + MIN)
        self.assertEqual([x.p for x in got], [25000.5])
        with open(self.p, "a", encoding="utf-8") as f:
            f.write("5,4,B\n")                                                                    # la ligne se termine : 25000.75, taille 4
        got = src.poll(t + MIN)
        self.assertEqual([(x.p, x.q) for x in got], [(25000.75, 4)])

    def test_replaced_file_restarts(self):
        t = utc(2026, 10, 12, 13, 30)
        self.p.write_text(f"time,price,size\n{t},25000,1\n{t + 1},25001,1\n{t + 2},25002,1\n", encoding="utf-8")
        src = filefeed.CsvSource(self.p)
        list(src.history(t + MIN))
        self.p.write_text(f"time,price,size\n{t + 9},26000,5\n", encoding="utf-8")             # plus petit que la position lue : repart du debut
        got = src.poll(t + MIN)
        self.assertEqual([x.p for x in got], [26000])

    def test_old_ticks_are_dropped_and_sorted(self):
        now = utc(2026, 10, 12, 16)
        old = now - 20 * clock.DAY
        self.p.write_text(f"time,price,size\n{now - 5000},25001,1\n{old},24000,9\n{now - 9000},25000,1\n", encoding="utf-8")
        ticks = list(filefeed.CsvSource(self.p, follow=False).history(now))
        self.assertEqual([x.p for x in ticks], [25000, 25001])

    def test_history_is_streamed_in_chunks_with_identical_result(self):
        t = utc(2026, 10, 12, 13, 30)
        lines = [f"{t + i * 137},{25000 + (i % 40) * 0.25},{1 + i % 9},{'B' if i % 3 else 'S'}" for i in range(3000)]
        self.p.write_text("time,price,size,side\n" + "\n".join(lines) + "\n", encoding="utf-8")
        whole = list(filefeed.CsvSource(self.p, follow=False, max_days=365).history(t))
        src = filefeed.CsvSource(self.p, follow=False, max_days=365, chunk_bytes=997)          # blocs minuscules : des lignes sont coupees entre deux blocs
        gen = src.history(t)
        self.assertTrue(inspect.isgenerator(gen))                                              # jamais une liste : pas tout le fichier en memoire
        chunked = list(gen)
        self.assertEqual(len(whole), 3000)
        self.assertEqual(chunked, whole)
        self.assertEqual(src.rows, 3000)
        self.assertEqual(src.parser.bad, 0)

    def test_horizon_is_relative_to_the_file_not_the_clock(self):
        old = utc(2020, 1, 6, 15)                                                              # un vieux fichier rejoue : rien n'est jete a cause de l'horloge
        self.p.write_text(f"time,price,size\n{old},25000,1\n{old + 5000},25001,1\n{old - 30 * clock.DAY},24000,1\n", encoding="utf-8")
        ticks = list(filefeed.CsvSource(self.p, follow=False, max_days=6).history(utc(2026, 10, 12)))
        self.assertEqual([x.p for x in ticks], [25000, 25001])                                # 30 jours avant la fin du fichier : jete

    def test_header_only_and_empty_files(self):
        self.p.write_text("time,price,size\n", encoding="utf-8")
        self.assertEqual(list(filefeed.CsvSource(self.p, follow=False).history(utc(2026, 10, 12))), [])
        self.p.write_text("", encoding="utf-8")
        self.assertEqual(list(filefeed.CsvSource(self.p, follow=False).history(utc(2026, 10, 12))), [])

    def test_selftest_message(self):
        t = utc(2026, 10, 12, 13, 30)
        self.p.write_text(f"time,price,size\n{t},25000,1\n{t + 1000},25001,1\n", encoding="utf-8")
        ok, msg = filefeed.selftest_file(self.p)
        self.assertTrue(ok)
        self.assertIn("2 transactions", msg)
        self.assertIn("ESTIMÉ", msg)                                  # sans cote d'agresseur dans le fichier, l'avertissement est explicite


if __name__ == "__main__":
    unittest.main()
