import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from engine import backtest as bt
from engine import fine, history

MIN = 60_000
T0 = bt.ms(2024, 3, 1)


def row(t, o=100.0, h=101.0, l=99.0, c=100.5, v=10.0, tb=6.0):
    return [str(t), str(o), str(h), str(l), str(c), str(v), str(t + 59_999), "1000", "50", str(tb), "600", "0"]


def zip_of(rows, header=False):
    buf = io.StringIO()
    if header:
        buf.write("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n")
    for r in rows:
        buf.write(",".join(r) + "\n")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("SOLUSDT-1m-2024-03.csv", buf.getvalue())
    return out.getvalue()


class HistoryTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(history.vision_url("SOLUSDT", "futures", 2024, 3), "https://data.binance.vision/data/futures/um/monthly/klines/SOLUSDT/1m/SOLUSDT-1m-2024-03.zip")
        self.assertEqual(history.vision_url("BTCUSDT", "spot", 2025, 1, 7), "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2025-01-07.zip")

    def test_months(self):
        self.assertEqual(history.months(bt.ms(2023, 11), bt.ms(2024, 2, 15)), [(2023, 11), (2023, 12), (2024, 1), (2024, 2)])

    def test_parse_rows_header_and_microseconds(self):
        rows = [["open_time", "open"], row(T0), row(T0 * 1000 + MIN * 1000, o=7.0), ["x"], row(T0 + 2 * MIN)]
        got = list(history.parse_rows(rows))
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0][0], T0)
        self.assertEqual(got[1][0], T0 + MIN)                                  # microsecondes -> millisecondes
        self.assertEqual(got[1][1], 7.0)
        self.assertEqual(got[2][6], 6.0)

    def test_zip_roundtrip_and_real_delta(self):
        data = zip_of([row(T0), row(T0 + MIN, v=10.0, tb=7.0)], header=True)
        parsed = list(history.parse_rows(history.read_zip_rows(data)))
        b, st = fine.Bars(MIN), {}
        history.append_rows(b, parsed, st)
        self.assertEqual(len(b), 2)
        self.assertAlmostEqual(b.d[0], 2 * 6.0 - 10.0)                        # delta reel = 2 x achats agressifs - volume
        self.assertAlmostEqual(b.d[1], 4.0)

    def test_gaps_are_filled_flat_long_gaps_skipped_duplicates_ignored(self):
        b, st = fine.Bars(MIN), {}
        history.append_rows(b, history.parse_rows([row(T0, c=100.0), row(T0 + 4 * MIN, o=100.0, c=101.0), row(T0 + 4 * MIN, c=555.0)]), st)
        self.assertEqual(len(b), 5)                                            # 3 minutes de trou comblees
        self.assertEqual((b.v[1], b.v[2], b.v[3]), (0.0, 0.0, 0.0))
        self.assertEqual(b.c[2], 100.0)
        self.assertEqual(b.c[4], 101.0)                                        # le doublon (555) est ignore
        history.append_rows(b, history.parse_rows([row(T0 + 10 * 86_400_000)]), st)
        self.assertEqual(len(b), 6)                                            # trou de 10 jours : on saute, on ne fabrique pas 14 000 bougies
        self.assertTrue(all(b.t[i + 1] > b.t[i] for i in range(len(b) - 1)))

    def test_build_folder_loads_as_dataset(self):
        b, st = fine.Bars(MIN), {}
        history.append_rows(b, history.parse_rows([row(T0 + k * MIN, c=100.0 + k * 0.01) for k in range(300)]), st)
        with tempfile.TemporaryDirectory() as d:
            info = history.build_folder(b, d, {"symbol": "TEST"})
            self.assertEqual(info["bars"]["b1m"], 300)
            self.assertEqual(info["bars"]["b5m"], 60)
            self.assertEqual(json.loads((Path(d) / "meta.json").read_text())["symbol"], "TEST")
            ds = bt.Dataset.load(d)
            self.assertEqual(len(ds.b1), 300)
            self.assertAlmostEqual(ds.b15.volume(0, len(ds.b15)), b.volume(0, len(b)), places=6)


class CliTests(unittest.TestCase):
    def test_auto_periods_cut_at_new_year_and_leave_warmup(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools import run_study
        first, last = bt.ms(2020, 9, 14), bt.ms(2026, 10, 5)
        start, eras, split = run_study.auto_periods(first, last)
        self.assertGreaterEqual(start, first + 220 * 86_400_000)
        self.assertGreaterEqual(len(eras), 2)
        for (l1, a1, b1), (l2, a2, b2) in zip(eras, eras[1:]):
            self.assertEqual(b1, a2)
        self.assertEqual(eras[0][1], start)
        self.assertEqual(eras[-1][2], last)
        self.assertEqual(split, eras[-1][1])
        s2, e2, sp2 = run_study.auto_periods(bt.ms(2024, 1, 1), bt.ms(2025, 6, 1))
        self.assertEqual(len(e2), 1)


if __name__ == "__main__":
    unittest.main()
