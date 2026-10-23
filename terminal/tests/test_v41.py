"""V40.1 : historique a l'heure du flux par taille d'ordre, pour que les grandes unites de temps aient un cumul sur plusieurs mois."""
from __future__ import annotations
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from data import sizehist as shm
from data import trades as tr
from engine import sizeflow as sfm
from server import API_LEVEL, VERSION
from tests.test_v23 import D0, DAY, make_trades, zip_day
from tests.test_v39 import brute

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
WEB = Path(__file__).resolve().parent.parent / "web"
HOUR = 3_600_000


def flow_of(trades, res):
    f = sfm.SizeFlow(res)
    for _, p, q, m, t in trades:
        f.add(p, q, m, t)
    f.flush()
    return f


class EngineTests(unittest.TestCase):
    def test_hour_resolution_and_hourly_sum_of_minutes_agree(self):
        trades = make_trades(D0, D0 + DAY, every_ms=20_000)
        m, h = flow_of(trades, sfm.MIN), flow_of(trades, HOUR)
        self.assertEqual((m.slots, h.slots), (1440, 24))
        self.assertEqual(len(h.day_values(D0)), 24 * sfm.WIDTH)
        for a, b in ((D0, D0 + DAY), (D0 + 3 * HOUR, D0 + 7 * HOUR)):
            bm, sm = m.totals(a, b)
            bh, sh = h.totals(a, b)
            for c in range(5):
                self.assertAlmostEqual(bm[c], bh[c], places=4)
                self.assertAlmostEqual(sm[c], sh[c], places=4)
        agg = sfm.hourly_of(m, D0)
        self.assertEqual(len(agg), 24 * sfm.WIDTH)
        self.assertAlmostEqual(sum(agg), sum(h.days[D0]), places=4)

    def test_combined_takes_each_day_from_the_first_layer_that_covers_it(self):
        old = make_trades(D0 - 10 * DAY, D0 - 2 * DAY, every_ms=60_000, seed=3)
        new = make_trades(D0 - 2 * DAY, D0 + DAY, every_ms=60_000, seed=4, first_id=900_000)
        h = flow_of(old, HOUR)
        h.cover(D0 - 10 * DAY, D0 - 2 * DAY)
        m = flow_of(new, sfm.MIN)
        m.cover(D0 - 2 * DAY, D0 + DAY)
        times = [D0 - 10 * DAY + k * DAY for k in range(11)]
        ser = sfm.combined(times, DAY, [m, h])
        self.assertTrue(all(c == 1.0 for c in ser["cov"]))
        for k, t in enumerate(times):                                   # chaque jour : le bon flux, exactement
            ref = brute(old + new, t, t + DAY)
            for c in range(5):
                self.assertAlmostEqual(ser["delta"][c][k], ref[c], places=3)
        wk = sfm.combined([D0 - 7 * DAY], 7 * DAY, [m, h])             # une bougie qui chevauche les deux flux
        ref = brute(old + new, D0 - 7 * DAY, D0)
        self.assertAlmostEqual(sum(wk["delta"][c][0] for c in range(5)), sum(ref), places=3)
        q = sfm.combined([D0 - 5 * DAY + 15 * 60_000], 15 * 60_000, [m, h])   # 15 minutes dans l'historique a l'heure : pas d'invention
        self.assertIsNone(q["delta"][0][0])
        self.assertIsNone(sfm.combined([D0 - 20 * DAY], DAY, [m, h])["delta"][0][0])


class FakeMinute:
    def __init__(self, flow, flow_days):
        self.flow, self.flow_days = flow, flow_days


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.trades = make_trades(D0 - 8 * DAY, D0, every_ms=60_000, seed=9)
        self.now = D0 + 6 * HOUR
        self.fetched = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def fetch(self, url):
        assert "/data/spot/daily/aggTrades/" in url
        self.fetched.append(url)
        day = url.rsplit("-aggTrades-", 1)[1][:10]
        d = next((D0 - k * DAY for k in range(1, 9) if tr.ymd(D0 - k * DAY) == day), None)
        if d is None:
            return None
        return zip_day([(a, p, q, m, t * 1000) for a, p, q, m, t in self.trades if d <= t < d + DAY])   # spot : microsecondes

    def test_downloads_old_days_takes_recent_ones_from_minutes_and_keeps_files(self):
        recent = [x for x in self.trades if x[4] >= D0 - 2 * DAY]
        mf = flow_of(recent, sfm.MIN)
        mf.cover(D0 - 2 * DAY, D0)
        h = shm.SizeHistory("TESTUSDT", "spot", self.dir, 6, minute=FakeMinute(mf, 2), fetch=self.fetch, now_ms=lambda: self.now, pause=0)
        while h.step():
            pass
        self.assertEqual(len(h.done), 6)
        self.assertEqual(len(self.fetched), 4)                         # 2 jours recents additionnes depuis la minute, 4 telecharges
        ref = brute(self.trades, D0 - 6 * DAY, D0)
        b, s = h.flow.totals(D0 - 6 * DAY, D0)
        self.assertAlmostEqual(sum(b) - sum(s), sum(ref), delta=60)     # fichiers arrondis au dollar
        self.assertEqual(h.status()["kind"], "hist")
        h2 = shm.SizeHistory("TESTUSDT", "spot", self.dir, 6, fetch=self.fetch, now_ms=lambda: self.now, pause=0)
        h2.load()
        self.assertEqual(h2.done, h.done)
        n = len(self.fetched)
        self.assertFalse(h2.step())                                    # tout est deja la : rien a retelecharger
        self.assertEqual(len(self.fetched), n)

    def test_recent_days_wait_for_the_minute_flow(self):
        mf = sfm.SizeFlow()
        h = shm.SizeHistory("TESTUSDT", "spot", self.dir, 3, minute=FakeMinute(mf, 2), fetch=self.fetch, now_ms=lambda: self.now, pause=0)
        while h.step():
            pass
        self.assertEqual([u.rsplit("-aggTrades-", 1)[1][:10] for u in self.fetched], [tr.ymd(D0 - 3 * DAY)])
        self.assertEqual(h.done, {D0 - 3 * DAY})


class WiringTests(unittest.TestCase):
    def test_trade_list_settings_and_page(self):
        from config import Config
        from server import default_trades

        class Src:
            spot_base = "https://spot"

            def _get(self, *a, **k):
                return []
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            cfg = Config(source="binance", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            self.assertEqual(cfg.sizeflow_history_days, 180)
            out = default_trades(cfg, Src(), None)
            self.assertEqual(out["BTCUSDT:hist:perp"].minute, out["BTCUSDT"])
            self.assertEqual(out["BTCUSDT:hist:spot"].minute, out["BTCUSDT:spot"])
            self.assertEqual(out["BTCUSDT:hist:spot"].days, 180)
            cfg.sizeflow_history_days = 0
            self.assertFalse(any(":hist:" in k for k in default_trades(cfg, Src(), None)))
        self.assertGreaterEqual(API_LEVEL, 41)
        self.assertEqual(VERSION, str(API_LEVEL))
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="sizeHistDays"', html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("sizeHistDays: $('#sizeHistDays')", app)
        self.assertIn("t.kind === 'hist'", app)
        srv = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn("sizeflow.combined(times, step, [ts.flow, h.flow if h else None])", srv)
        self.assertIn('upd["TERMINAL_SIZEFLOW_HISTORY_DAYS"]', srv)


if __name__ == "__main__":
    unittest.main()
