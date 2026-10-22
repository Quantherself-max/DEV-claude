"""V37 : intérêt ouvert, delta, CVD et funding plus précis, et leur lecture croisée (qui ouvre, qui ferme) avec des options dans le graphique."""
from __future__ import annotations
import gzip
import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from data.binance import BinanceSource
from data.store import DataStore
from engine import subcharts
from engine.atr import Candle, resample, resample_cal
from server import API_LEVEL, VERSION, App, serve

H = 3_600_000
WEB = Path(__file__).resolve().parent.parent / "web"


def k(t, o, c, v=10.0, tb=6.0, q=None, bq=0.0):
    return Candle(t, o, max(o, c) + 1, min(o, c) - 1, c, v, tb, q if q is not None else v * (o + c) / 2, bq)


class DeltaTests(unittest.TestCase):
    def test_dollar_delta_is_exact_when_binance_gives_it(self):
        cs = [k(0, 100, 101, v=10, tb=6, q=1005, bq=610),                 # 2 x 610 - 1005 = 215 $ exactement
              k(H, 101, 99, v=10, tb=4, q=1000),                           # sans le champ : -2 coin x prix moyen 100 = -200 $
              Candle(2 * H, 99, 100, 98, 99, 0, 0)]
        d, share = subcharts.deltas_usd(cs)
        self.assertEqual(d[:2], [215.0, -200.0])
        self.assertIsNone(d[2])
        self.assertAlmostEqual(share, 0.5)

    def test_spot_delta_aligned_on_chart_candles(self):
        spot = [k(H, 1, 1, v=4, tb=3, q=4, bq=3), k(3 * H, 1, 1, v=2, tb=0.5, q=2, bq=0.5)]
        c, u = subcharts.align_spot([0, H, 2 * H, 3 * H], spot)
        self.assertEqual(c, [None, 2.0, None, -1.0])
        self.assertEqual(u, [None, 2.0, None, -1.0])

    def test_resampling_keeps_dollar_buy_volume(self):
        cs = [k(i * H, 100, 100, bq=10.0) for i in range(8)]
        self.assertEqual(resample(cs, 4 * H)[0].bq, 40.0)
        self.assertEqual(sum(x.bq for x in resample_cal(cs, "1w")), 80.0)

    def test_binance_klines_read_the_dollar_buy_volume(self):
        row = [0, "1", "2", "0.5", "1.5", "10", 0, "15", 3, "6", "9.3", "0"]
        c = BinanceSource.parse_klines([row])[0]
        self.assertEqual((c.tb, c.q, c.bq), (6.0, 15.0, 9.3))
        self.assertEqual(BinanceSource.parse_klines([row[:10]])[0].bq, 0.0)      # ancienne réponse : champ absent


class OpenInterestTests(unittest.TestCase):
    def test_live_reading_extends_the_last_candle(self):
        ts, vs = subcharts.merge_points({0: 5.0}, {}, (400_000, 6.0), 500_000)
        self.assertEqual((ts, vs), ([300_000, 400_000], [5.0, 6.0]))
        oi = subcharts.oi_candles([0, 300_000], 300_000, ts, vs)
        self.assertEqual(oi[1], [5.0, 6.0, 5.0, 6.0])                        # la bougie en cours bouge avec l'OI à l'instant

    def test_stale_or_older_live_reading_is_ignored(self):
        self.assertEqual(subcharts.merge_points({0: 5.0}, {}, (400_000, 6.0), 400_000 + 16 * 60_000)[0], [300_000])
        self.assertEqual(subcharts.merge_points({0: 5.0}, {}, (200_000, 6.0))[0], [300_000])
        self.assertEqual(subcharts.merge_points({0: 5.0}, {}, None)[0], [300_000])


class PositionTests(unittest.TestCase):
    def test_four_cases_and_flat(self):
        cs = [k(0, 100, 102), k(H, 102, 100), k(2 * H, 100, 102), k(3 * H, 102, 100), k(4 * H, 100, 101)]
        oi = [[10, 12, 10, 12], [12, 14, 12, 14], [14, 14, 12, 12], [12, 12, 10, 10], [10, 10.1, 10, 10.1]]
        d = [5.0, -5.0, -3.0, -5.0, 1.0]
        r = subcharts.positions(cs, oi, d, window=5)
        self.assertEqual(r["pos"], [1, 2, 3, 4, 0])                          # 0,1 coin : moins du quart de la variation habituelle (2)
        self.assertEqual(r["posConf"], [True, True, False, True, None])       # rachat de vendeurs contre le delta : ordres passifs
        s = r["posSum"]
        self.assertEqual((s["longsOpen"], s["shortsOpen"], s["shortsClose"], s["longsClose"], s["bars"]), (2, 2, -2, -2, 5))
        self.assertAlmostEqual(s["oiChg"], 10.1 / 10 - 1)

    def test_tiny_body_takes_the_direction_of_the_delta(self):
        c = Candle(0, 100, 105, 95, 100.2, 10, 2)                            # corps de 0,2 pour 10 d'amplitude : le delta décide
        r = subcharts.positions([c, c], [[10, 12, 10, 12], [12, 12, 10, 10]], [-6.0, -6.0])
        self.assertEqual(r["pos"], [2, 4])

    def test_missing_oi_and_funding_confirmation(self):
        r = subcharts.positions([k(0, 1, 2)], [None], [1.0])
        self.assertEqual((r["pos"], r["posSum"]["dominant"]), ([None], None))
        self.assertIn("squeeze haussier", subcharts.crowding({"dominant": 2}, -0.01))
        self.assertIn("purge", subcharts.crowding({"dominant": 1}, 0.04))
        self.assertIsNone(subcharts.crowding({"dominant": 1}, 0.01))
        self.assertIsNone(subcharts.crowding({"dominant": 2}, None))


class FundingTests(unittest.TestCase):
    def test_long_candle_weights_each_period_by_its_duration(self):
        # 0-8 h : 0,01 % ; puis Binance passe à 4 h : 8-12 h et 12-16 h à 0,01 % par 4 h (= 0,02 % par 8 h) ; 16-24 h : 0,03 %
        rows = [(0, 0.0001), (8 * H, 0.0001), (12 * H, 0.0001), (16 * H, 0.0001), (24 * H, 0.0003)]
        out = subcharts.funding_bars([0], 24 * H, rows)
        self.assertAlmostEqual(out["funding"][0], (8 * 0.01 + 8 * 0.02 + 8 * 0.03) / 24)   # et non la moyenne simple 0,0175
        self.assertAlmostEqual(out["fundCum"][0], 0.06)                     # versé : 0,01 + 0,01 + 0,01 + 0,03

    def test_current_period_uses_the_announced_next_payment(self):
        rows = [(8 * H * i, 0.0001) for i in range(1, 4)]                    # toutes les 8 h jusqu'à 24 h
        out = subcharts.funding_bars([24 * H], H, rows, now_rate=0.0001, now_ms=24 * H + 1, next_ms=28 * H + 5)
        self.assertEqual(out["fundHours"], 4.0)                              # Binance vient de passer à 4 h : 0,01 % par 4 h
        self.assertAlmostEqual(out["fundNow"], 0.02)
        self.assertEqual(out["fundEst"], 0)

    def test_cumulated_funding_starts_with_the_chart(self):
        rows = [(8 * H * i, 0.0001 * i) for i in range(1, 5)]
        out = subcharts.funding_bars([16 * H, 24 * H], 8 * H, rows)
        self.assertEqual([round(x, 4) for x in out["fundCum"]], [0.03, 0.07])  # le versement de 16 h clôt la bougie d'avant le graphique

    def test_aggregate_weighted_by_open_interest(self):
        g = subcharts.aggregate_funding([{"ex": "Binance", "funding": 0.0001, "intervalH": 8, "oiUsd": 3e9},
                                         {"ex": "Hyperliquid", "funding": 0.00002, "intervalH": 1, "oiUsd": 1e9},
                                         {"ex": "OKX", "funding": None, "oiUsd": 1e9}])
        self.assertEqual(g["n"], 2)
        self.assertAlmostEqual(g["rate8h"], 0.75 * 0.01 + 0.25 * 0.016)
        self.assertIsNone(subcharts.aggregate_funding([]))


class CacheTests(unittest.TestCase):
    def test_old_cache_rows_without_dollar_buy_volume(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        class Src:
            def now_ms(self):
                return 1_700_000_000_000
        st = DataStore(Src(), "BTCUSDT", 0, cache_dir=tmp)
        rows = [[1, 1, 2, 0.5, 1.5, 10, 6, 15], [2, 1, 2, 0.5, 1.5, 10, 6, 15, 9.0]]
        from data import store as store_mod
        with gzip.open(st.cache, "wt", encoding="utf-8") as f:
            json.dump({"v": store_mod.CACHE_VERSION, "symbol": "BTCUSDT", "start": st.history_start, "rows": rows}, f)
        st._load_cache()
        self.assertEqual([c.bq for c in st.h1], [0.0, 9.0])
        self.assertGreaterEqual(store_mod.CACHE_VERSION, 3)                   # ancien cache sans le champ : retéléchargé une fois


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=cls.tmp, port=0, heatmap_days=40), env_path=None)
        cls.app.service.refresh_all()
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, True)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=60) as r:
            return json.loads(r.read())

    def test_indicators_carry_the_new_readings(self):
        r = self.get("/api/indicators?symbol=SOLUSDT&tf=1h&fund=1&spot=1")
        n = len(r["times"])
        for key in ("deltaUsd", "pos", "posConf", "close", "spotDelta", "spotDeltaUsd", "fundCum"):
            self.assertEqual(len(r[key]), n, key)
        self.assertTrue(r["oiLive"])
        self.assertTrue(r["spotOk"])
        self.assertEqual(r["deltaExact"], 1.0)
        self.assertEqual(r["posSum"]["bars"], 24)
        self.assertEqual(r["fundAgg"]["rows"][0]["ex"], "Binance")                 # + Bybit, OKX, Hyperliquid une fois leurs relevés arrivés
        self.assertIn("posNote", r)

    def test_spot_only_when_asked_and_every_unit(self):
        r = self.get("/api/indicators?symbol=BTCUSDT&tf=4h")
        self.assertNotIn("spotDelta", r)
        for tf in ("1m", "1w", "1M"):
            r = self.get(f"/api/indicators?symbol=BTCUSDT&tf={tf}&fund=1&spot=1")
            self.assertTrue(r["ready"])
            self.assertTrue(any(x is not None for x in r["spotDelta"]), tf)

    def test_version(self):
        self.assertGreaterEqual(float(VERSION), 37)
        self.assertGreaterEqual(API_LEVEL, 37)


class PageTests(unittest.TestCase):
    DESK = (WEB / "desk.js").read_text(encoding="utf-8")
    PANELS = (WEB / "panels.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")

    def test_options_in_the_elements_menu(self):
        for key in ("oiMode", "oiColor", "deltaUnit", "cvdMode", "cvdReset", "fundMode"):
            self.assertIn(f"sel('{key}'", self.DESK)
        self.assertIn("&spot=1", self.DESK)
        self.assertIn("['cum', 'cumulé']", self.DESK)

    def test_drawing(self):
        for name in ("static cvdLine", "static get POS_COL", "static fundAggText", "paneLines(", "this.spS", "this.oiH", "this.fdC"):
            self.assertIn(name, self.PANELS)
        self.assertGreaterEqual(int(re.search(r"NEED_API = (\d+)", self.APP).group(1)), 37)


if __name__ == "__main__":
    unittest.main()
