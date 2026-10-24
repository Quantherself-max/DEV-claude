"""V41.1 : etude de la cassure de la bascule du gamma (engine/gexflip.py, tools/run_gex_flip_study.py)."""
from __future__ import annotations
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from engine import gexflip as G
from tools import run_gex_flip_study as T

MIN, H = 60_000, 3_600_000


def bars_from(closes, t0=0, wick=0.0):
    t = [t0 + i * MIN for i in range(len(closes))]
    return t, [c * (1 + wick) for c in closes], [c * (1 - wick) for c in closes], list(closes)


class Zone(unittest.TestCase):
    def test_curve_and_flip_only(self):
        s = {"curve": [[90, -5.0], [100, -1.0], [110, 3.0]]}
        self.assertEqual(G.zone(s, 95), -1)
        self.assertEqual(G.zone(s, 108), 1)
        self.assertEqual(G.zone(s, 80), 0)                       # hors de la courbe : inconnu
        self.assertEqual(G.zone({"flip": 100.0}, 101), 1)
        self.assertEqual(G.zone({"flip": 100.0}, 99), -1)
        self.assertEqual(G.zone({"flip": None}, 99), 0)


class Events(unittest.TestCase):
    def test_one_down_break_after_hold_and_no_lookahead(self):
        closes = [101.0] * 120 + [99.0] * 60 + [101.0] * 5 + [99.0] * 60
        bars = bars_from(closes)
        ev = G.events([{"t": 0, "flip": 100.0}], bars, hold=60, cool=24 * H, max_age=10 * H)
        self.assertEqual([(e["i"], e["d"]) for e in ev], [(120, -1), (180, 1)])   # la 2e baisse : moins d'une heure au-dessus, et pause de 24 h
        self.assertEqual(ev[0]["level"], 100.0)
        late = G.events([{"t": 150 * MIN, "flip": 100.0}], bars, hold=0, cool=0)
        self.assertTrue(all(e["i"] > 150 for e in late))          # l'instantane n'est utilise qu'une fois connu

    def test_stale_snapshot_is_ignored(self):
        bars = bars_from([101.0] * 200 + [99.0] * 10)
        self.assertEqual(G.events([{"t": 0, "flip": 100.0}], bars, hold=0, cool=0, max_age=H), [])

    def test_snapshot_change_alone_is_not_a_break(self):
        bars = bars_from([101.0] * 200)
        snaps = [{"t": 0, "flip": 100.0}, {"t": 100 * MIN, "flip": 102.0}]  # le niveau passe au-dessus du prix : pas une cassure du prix
        self.assertEqual(G.events(snaps, bars, hold=0, cool=0), [])


class Measures(unittest.TestCase):
    def test_reversal_move_race_and_back_through(self):
        closes = [100.0, 99.0, 98.0, 97.0, 97.5, 98.5, 96.0]
        bars = bars_from(closes)
        mv, mins = G.reversal_move(bars, 0, -1, 1)
        self.assertAlmostEqual(mv, 3.0)                           # 100 -> 97, puis +1,55 % : retournement
        self.assertEqual(mins, 3)
        self.assertEqual(G.race(bars, 0, -1, 2), 1)
        self.assertEqual(G.race(bars, 0, 1, 2), 0)
        self.assertEqual(G.back_through(bars, 0, -1, 98.2, H), 1)
        self.assertEqual(G.back_through(bars, 0, -1, 99.5, H), 0)
        self.assertIsNone(G.reversal_move(bars_from([100.0, 99.0]), 0, -1, 1))

    def test_study_and_text(self):
        closes = ([101.0] * 90 + [99.5 - 0.01 * k for k in range(200)] + [101.0 + 0.01 * k for k in range(300)]) * 6
        bars = bars_from(closes, wick=0.0005)
        rep = G.study([{"t": 0, "flip": 100.0}], bars, hold=60, cool=H, max_age=10 ** 12)
        self.assertTrue(rep["ok"])
        self.assertGreater(rep["down"]["n"], 0)
        self.assertIn("move1", rep["down"]["chance"])
        self.assertIn("Cassure vers le gamma NÉGATIF", G.text(rep, "Essai"))


class Tool(unittest.TestCase):
    def test_recorded_csv(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "BTCUSDT.csv"
            f.write_text("t,gexFlip,gexAllFlip\n1000,60000,\n2000,61000,61500\n3000,,\n", encoding="utf-8")
            self.assertEqual(T.recorded(f), [{"t": 1000, "flip": 60000.0}, {"t": 2000, "flip": 61500.0}])

    def test_eoh_archive_to_snapshots(self):
        head = "date,hour,symbol,underlying,type,strike,mark_iv,openinterest_contracts,openinterest_usdt"
        lines = [head]
        for k in range(30):
            strike = 25000 + 500 * k
            for kind in ("C", "P"):
                lines.append(f"2023-06-01,05,BTC-230630-{strike}-{kind},BTCUSDT,{kind},230630-{strike},0.5,{10 + k},{(10 + k) * 30000}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", "\n".join(lines) + "\n")
        snaps = T.eoh_snaps(buf.getvalue())
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["t"], 1685577600000 + 6 * H)    # resume de 5 h : connu a 6 h UTC
        self.assertTrue(snaps[0]["curve"])


if __name__ == "__main__":
    unittest.main()
