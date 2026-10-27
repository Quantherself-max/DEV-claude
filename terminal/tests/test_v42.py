"""V42 : PUMP (jeton de pump.fun) : premier jour par paire (l'ancien jeton PUMPUSDT d'avril a juin 2025 est exclu), prix sous 0,01 $
partout (formats, grille des profils et des poches, carnet simule), migration unique des paires de .env."""
from __future__ import annotations
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from config import Config, _load_env_file, migrate_env
from data import listing
from data.binance import BinanceSource
from data.orderflow import SimFlow
from data.sizehist import SizeHistory
from data.trades import DAY, TradeSync
from engine import stance
from engine.grid import Grid
from engine.signals import fmt_price
from engine.vp import VP_GRID, Profile, agg_rows, stats

FIRST = int(datetime(2025, 7, 10, tzinfo=timezone.utc).timestamp() * 1000)
SPOT_FIRST = int(datetime(2025, 9, 11, tzinfo=timezone.utc).timestamp() * 1000)


class Listing(unittest.TestCase):
    def test_first_days(self):
        self.assertEqual(listing.first_ms("PUMPUSDT"), FIRST)
        self.assertEqual(listing.first_ms("pumpusdt", "perp"), FIRST)
        self.assertEqual(listing.first_ms("PUMPUSDT", "spot"), SPOT_FIRST)
        self.assertEqual(listing.first_ms("BTCUSDT"), 0)
        self.assertEqual(listing.clamp("PUMPUSDT", FIRST - 90 * DAY), FIRST)
        self.assertEqual(listing.clamp("BTCUSDT", 123), 123)

    def test_api_history_never_starts_before_listing(self):
        calls = []

        class P(BinanceSource):
            def _get(self, path, params=None, host=None, retries=None, **kw):
                calls.append((path, dict(params or {})))
                return []
        p = P(pause=0)
        start = FIRST - 100 * DAY
        p.candles("PUMPUSDT", "1h", start, FIRST + DAY)
        p.spot_candles("PUMPUSDT", "1h", start, SPOT_FIRST + DAY)
        p.funding_history("PUMPUSDT", start, FIRST + DAY)
        p.long_short("PUMPUSDT", "1h", start, FIRST + DAY)
        p.candles("BTCUSDT", "1h", start, FIRST + DAY)
        starts = {path: [] for path, _ in calls}
        for path, prm in calls:
            starts[path].append(prm.get("startTime"))
        self.assertEqual(starts["/fapi/v1/klines"], [FIRST, start])          # PUMP coupe au 10 juillet, BTC inchange
        self.assertEqual(starts["/api/v3/klines"], [SPOT_FIRST])
        self.assertEqual(starts["/fapi/v1/fundingRate"], [FIRST])
        self.assertTrue(all(s >= FIRST for s in starts["/futures/data/globalLongShortAccountRatio"]))

    def test_archive_days_skip_the_old_token(self):
        now = FIRST + 5 * DAY + 3_600_000
        with tempfile.TemporaryDirectory() as d:
            ts = TradeSync("PUMPUSDT", d, 30, get=lambda *a, **k: [], fetch=lambda u: None, now_ms=lambda: now)
            self.assertEqual(len(ts.wanted_days()), 5)
            self.assertTrue(all(x >= FIRST for x in ts.wanted_days()))
            spot = TradeSync("PUMPUSDT", d, 30, get=lambda *a, **k: [], fetch=lambda u: None, now_ms=lambda: now, market="spot")
            self.assertEqual(spot.wanted_days(), [])                               # le spot n'existe pas encore a cette date
            btc = TradeSync("BTCUSDT", d, 30, get=lambda *a, **k: [], fetch=lambda u: None, now_ms=lambda: now)
            self.assertEqual(len(btc.wanted_days()), 30)
            h = SizeHistory("PUMPUSDT", "perp", d, 180, now_ms=lambda: now)
            self.assertEqual(len(h.wanted_days()), 5)


class SmallPrices(unittest.TestCase):
    def test_price_format(self):
        self.assertEqual(fmt_price(84760.4), "84 760")
        self.assertEqual(fmt_price(184.783), "184,78")
        self.assertEqual(fmt_price(0.5123), "0,5123")
        self.assertEqual(fmt_price(0.0042311), "0,004231")
        self.assertEqual(fmt_price(0.00001234), "0,00001234")

    def test_grid_separates_small_prices_and_keeps_btc_edges(self):
        self.assertNotEqual(VP_GRID.idx(0.0042), VP_GRID.idx(0.00421))
        self.assertAlmostEqual(VP_GRID.price(VP_GRID.idx(0.0042), 0.5) / 0.0042, 1.0, delta=0.0003)
        old = Grid(0.03, min_px=0.01)                                              # ancienne grille : memes bords pour BTC
        for px in (84760.4, 184.78, 1.2345):
            self.assertAlmostEqual(old.price(old.idx(px), 0.0), VP_GRID.price(VP_GRID.idx(px), 0.0), places=6)

    def test_volume_profile_poc_near_price(self):
        p = Profile()
        for k in range(200):
            mid = 0.0042 * (1 + 0.01 * math.sin(k / 9))
            p.add(mid * 0.999, mid * 1.001, 1e9 if abs(mid - 0.00425) < 0.00002 else 1e8)
        rows, b0, g = agg_rows(p, 60)
        poc, vah, val = stats(rows, b0, g)
        self.assertTrue(0.0041 < val <= poc <= vah < 0.0044, (poc, vah, val))

    def test_simulated_order_book(self):
        f = SimFlow(["PUMPUSDT"], lambda s: 0.0042, now=lambda: 1_000.0)
        f._last["PUMPUSDT"] = 990.0
        out = f.ladder("PUMPUSDT", 0.000005, 20)
        self.assertTrue(out["ready"])
        self.assertTrue(out["rows"])
        self.assertTrue(all(r[0] > 0.003 for r in out["rows"]))


class PumpBits(unittest.TestCase):
    def test_default_pairs_and_cashtag(self):
        self.assertIn("PUMPUSDT", Config().symbols)
        _, names = stance.asset_names("PUMPUSDT")
        self.assertTrue(stance.mentions("Gros rachat de $PUMP", names))
        self.assertFalse(stance.mentions("ça va pump fort", names))                # « pump » seul n'est pas le jeton

    def test_env_migration_adds_pump_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, data = Path(tmp) / ".env", Path(tmp) / "data"
            env.write_text("TERMINAL_SYMBOLS=BTCUSDT,SOLUSDT\nTERMINAL_SOURCE=binance\n", encoding="utf-8")
            self.assertTrue(migrate_env(env, data))
            self.assertEqual(_load_env_file(env)["TERMINAL_SYMBOLS"], "BTCUSDT,SOLUSDT,PUMPUSDT")
            env.write_text("TERMINAL_SYMBOLS=BTCUSDT,SOLUSDT\n", encoding="utf-8")        # enleve ensuite par l'utilisateur
            self.assertFalse(migrate_env(env, data))
            self.assertEqual(_load_env_file(env)["TERMINAL_SYMBOLS"], "BTCUSDT,SOLUSDT")

    def test_no_env_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(migrate_env(Path(tmp) / ".env", Path(tmp) / "d"))
            self.assertFalse((Path(tmp) / ".env").exists())


if __name__ == "__main__":
    unittest.main()
