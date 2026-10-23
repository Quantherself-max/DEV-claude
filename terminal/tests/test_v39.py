"""V39 : flux par taille d'ordre (delta en dollars des petits, moyens et gros ordres), perpetuel et spot Binance, comme « Volume By Side
(delta) » d'Aggr : moteur, synchronisation (archives, API, direct), relecture unique des archives sans ce flux, adresse et page."""
from __future__ import annotations
import gzip
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from data import trades as tr
from engine import sizeflow as sfm
from server import API_LEVEL, VERSION
from tests.test_v23 import D0, DAY, Market, make_trades, run_until, zip_day

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
WEB = Path(__file__).resolve().parent.parent / "web"
MIN = 60_000


def brute(trades, t0, t1):
    """Reference : transactions regroupees (meme instant, meme sens), classees par taille en dollars, delta par classe."""
    out = [0.0] * sfm.NCLS
    groups = []
    for a, p, q, m, t in trades:
        if groups and groups[-1][0] == t and groups[-1][1] == m:
            groups[-1][2] += p * q
        else:
            groups.append([t, m, p * q])
    for t, m, usd in groups:
        if t0 <= t < t1:
            out[sfm.cls_of(usd)] += -usd if m else usd
    return out


class EngineTests(unittest.TestCase):
    def test_classes_and_grouping_of_one_order_sweeping_several_prices(self):
        self.assertEqual([sfm.cls_of(x) for x in (999, 1000, 9_999, 50_000, 999_999, 1e6, 5e7)], [0, 1, 1, 2, 3, 4, 4])
        f = sfm.SizeFlow()
        f.add(100.0, 6.0, False, D0)                                  # 600 $ ...
        f.add(101.0, 6.0, False, D0)                                  # ... + 606 $ au meme instant, meme sens : un seul ordre de 1 206 $
        f.add(101.0, 2.0, True, D0)                                   # vente au meme instant : autre ordre (202 $)
        f.add(100.0, 2000.0, True, D0 + 61_000)                       # vente de 200 000 $ la minute suivante
        f.flush()
        b, s = f.totals(D0, D0 + 120_000)
        self.assertEqual((b[1], s[0], s[3]), (1206.0, 202.0, 200_000.0))
        self.assertEqual(sum(b) + sum(s), 1206.0 + 202.0 + 200_000.0)
        f.cover(D0, D0 + 120_000)
        ser = f.series([D0, D0 + MIN, D0 + 2 * MIN], MIN)
        self.assertEqual([ser["delta"][c][0] for c in range(5)], [-202.0, 1206.0, 0.0, 0.0, 0.0])
        self.assertEqual(ser["delta"][3][1], -200_000.0)
        self.assertIsNone(ser["delta"][0][2])                         # minute pas couverte : rien plutot qu'un faux zero
        self.assertEqual(ser["cov"][2], 0.0)

    def test_clear_put_drop_and_values(self):
        f = sfm.SizeFlow()
        f.add(10.0, 1.0, False, D0 + 5)
        f.add(10.0, 1.0, False, D0 + DAY + 5)
        f.flush()
        vals = f.day_values(D0)
        self.assertEqual(len(vals), 1440 * sfm.WIDTH)
        g = sfm.SizeFlow()
        g.put_day(D0, vals)
        self.assertEqual(g.totals(D0, D0 + DAY)[0][0], 10.0)
        f.cover(D0, D0 + 2 * DAY)
        f.clear(D0, D0 + DAY)
        self.assertNotIn(D0, f.days)
        self.assertFalse(f.complete(D0, D0 + DAY))
        self.assertTrue(f.complete(D0 + DAY, D0 + 2 * DAY))
        f.drop_before(D0 + 2 * DAY)
        self.assertEqual(f.days, {})

    def test_simulated_mode_has_every_class(self):
        from engine.atr import Candle
        cs = [Candle(D0 + i * MIN, 100, 101, 99, 100.5, 10, 6, 1000) for i in range(50)]
        sim = sfm.simulated(cs)
        self.assertEqual(len(sim["delta"]), 5)
        self.assertTrue(all(len(x) == 50 and x[10] is not None for x in sim["delta"]))


class SpotMarket(Market):
    """Fausse bourse spot : adresse /api/v3/aggTrades et archives au temps en MICROSECONDES (depuis 2025)."""

    def get(self, path, params):
        assert path == "/api/v3/aggTrades"
        return Market.get(self, "/fapi/v1/aggTrades", params)

    def fetch(self, url):
        assert "/data/spot/daily/aggTrades/" in url
        day = url.rsplit("-aggTrades-", 1)[1][:10]
        d = next((x for x in self.published if tr.ymd(x) == day), None)
        if d is None:
            return None
        return zip_day([(a, p, q, m, t * 1000) for a, p, q, m, t in self.trades if d <= t < d + DAY])


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.trades = make_trades(D0 - 3 * DAY, D0 + DAY, every_ms=30_000)
        self.now = D0 + 6 * 3_600_000

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def check(self, ts, t0, t1):
        ts.flow.flush()
        b, s = ts.flow.totals(t0, t1)
        ref = brute(self.trades, t0, t1)
        for c in range(5):
            self.assertAlmostEqual(b[c] - s[c], ref[c], places=4)

    def test_spot_archives_in_microseconds_then_api_then_live(self):
        mk = SpotMarket(self.trades, self.now, published=(D0 - DAY, D0 - 2 * DAY))
        ts = tr.TradeSync("TESTUSDT", self.dir, 2, mk.get, mk.fetch, now_ms=lambda: mk.now, rest_pause=0.0, market="spot")
        self.assertTrue(run_until(ts, lambda: ts.head_t is not None and ts.head_t >= self.now - 60_000 and not ts.catching_up and D0 - 2 * DAY in ts.done))
        self.assertTrue(ts.flow.complete(D0 - 2 * DAY, D0))
        self.check(ts, D0 - 2 * DAY, D0)                              # archives (microsecondes converties)
        self.check(ts, D0, D0 + 5 * 3_600_000)                        # rattrapage par l'API
        self.assertEqual(ts.status()["market"], "spot")
        live = [x for x in self.trades if self.now < x[4] <= self.now + 3_600_000]
        mk.now += 3_600_000
        for a, p, q, m, t in live:
            ts.on_live({"a": a, "p": str(p), "q": str(q), "m": m, "T": t})
        run_until(ts, lambda: not ts.q, 5000)
        self.check(ts, D0, live[-1][4] - live[-1][4] % MIN)            # le flux en direct prolonge sans trou ni double compte (minutes entieres)
        ts.flush()
        blob = json.loads(gzip.decompress((Path(self.dir) / "TESTUSDT" / f"{tr.ymd(D0 - DAY)}.json.gz").read_bytes()))
        self.assertEqual(len(blob["flow"]), 1440 * sfm.WIDTH)          # le flux du jour est sauvegarde avec l'empreinte

    def test_perp_days_saved_before_v39_are_read_again_once(self):
        mk = Market(self.trades, self.now, published=(D0 - DAY, D0 - 2 * DAY, D0 - 3 * DAY))
        ts = tr.TradeSync("TESTUSDT", self.dir, 3, mk.get, mk.fetch, now_ms=lambda: mk.now, rest_pause=0.0, flow_days=2)
        self.assertTrue(run_until(ts, lambda: all(d in ts.done for d in (D0 - DAY, D0 - 2 * DAY, D0 - 3 * DAY))))
        ts.flush()
        folder = Path(self.dir) / "TESTUSDT"
        for d in (D0 - DAY, D0 - 2 * DAY, D0 - 3 * DAY):              # fichiers comme avant la V39 : sans le flux par taille
            f = folder / f"{tr.ymd(d)}.json.gz"
            blob = json.loads(gzip.decompress(f.read_bytes()))
            blob.pop("flow", None)
            f.write_bytes(gzip.compress(json.dumps(blob).encode()))
        fetched = []
        orig = mk.fetch
        mk.fetch = lambda url: (fetched.append(url), orig(url))[1]
        ts2 = tr.TradeSync("TESTUSDT", self.dir, 3, mk.get, mk.fetch, now_ms=lambda: mk.now, rest_pause=0.0, flow_days=2)
        ts2.load()
        self.assertIn(D0 - 3 * DAY, ts2.done)                          # plus vieux que 2 jours : garde tel quel, rien a relire
        self.assertNotIn(D0 - DAY, ts2.done)
        self.assertTrue(run_until(ts2, lambda: D0 - DAY in ts2.done and D0 - 2 * DAY in ts2.done))
        self.assertEqual(sorted(u.rsplit("-aggTrades-", 1)[1][:10] for u in fetched), sorted([tr.ymd(D0 - DAY), tr.ymd(D0 - 2 * DAY)]))
        ts2.flow.flush()
        b, s = ts2.flow.totals(D0 - 2 * DAY, D0)
        ref = brute(self.trades, D0 - 2 * DAY, D0)
        self.assertAlmostEqual(sum(b) - sum(s), sum(ref), places=3)


class LiveFeedTests(unittest.TestCase):
    def test_spot_messages_go_to_the_spot_sync(self):
        from data.live import LiveFeed
        got = []

        class TS:
            def on_live(self, x):
                got.append(x["a"])
        f = LiveFeed("wss://x", ["BTCUSDT"], None, spot_ws="wss://spot")
        f.spot_trades = {"BTCUSDT": TS()}
        f.on_spot_trade(json.dumps({"stream": "btcusdt@aggTrade", "data": {"e": "aggTrade", "s": "BTCUSDT", "a": 5, "p": "1", "q": "1", "T": 1, "m": False}}))
        self.assertEqual(got, [5])
        self.assertEqual(f.price, {})                                 # le prix du terminal reste celui du perpetuel


class ServerTests(unittest.TestCase):
    def test_endpoint_in_simulated_mode_and_trade_lists(self):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App, default_trades
        from tests.test_data_server import NOW
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
            app.service.refresh_all()
            r = app.size_flow("BTCUSDT", "15m")
            self.assertTrue(r["ready"])
            self.assertEqual(r["edges"], [1000.0, 10000.0, 100000.0, 1000000.0])
            self.assertEqual([g[0] for g in r["groups"]], ["petits", "moyens", "gros"])
            for m in ("perp", "spot"):
                self.assertTrue(r[m]["ok"] and r[m]["simulated"])
                self.assertEqual(len(r[m]["delta"]), 5)
                self.assertEqual(len(r[m]["delta"][0]), len(r["times"]))
            with self.assertRaises(KeyError):
                app.size_flow("XXXUSDT", "15m")

            class Src:
                spot_base = "https://spot"

                def _get(self, *a, **k):
                    return []
            bcfg = Config(source="binance", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tmp, port=0)
            out = default_trades(bcfg, Src(), None)
            self.assertEqual(sorted(out), ["BTCUSDT", "BTCUSDT:spot", "SOLUSDT", "SOLUSDT:spot"])
            self.assertEqual(out["BTCUSDT:spot"].market, "spot")
            self.assertEqual(out["BTCUSDT:spot"].days, bcfg.sizeflow_days)
            self.assertEqual(out["BTCUSDT"].flow_days, bcfg.sizeflow_days)
            bcfg.sizeflow_days = 0
            self.assertEqual(sorted(default_trades(bcfg, Src(), None)), ["BTCUSDT", "SOLUSDT"])


class PageTests(unittest.TestCase):
    def test_version_element_options_and_panes(self):
        self.assertEqual((VERSION, API_LEVEL), ("39", 39))
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("const NEED_API = 39;", app)
        self.assertIn("sizes: false, sizeMkt: 'both', sizeGroups: '3'", app)
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn("sizes: ['Flux par taille d\\'ordre'", desk)
        for k in ("sizeMkt", "sizeGroups", "sizeReset", "sizeScale"):
            self.assertIn(f"sel('{k}'", desk)
        self.assertIn("/api/sizeflow?symbol=", desk)
        self.assertIn("'sizes', 'dom'", desk)
        panels = (WEB / "panels.js").read_text(encoding="utf-8")
        for s in ("static sizeSets(Z, m)", "static sizeCum(Z, vals)", "static sizeLines(k, Z, idx)", "paneP()", "['szs', 'szp']",
                  "les gros achètent, les petits vendent : accumulation"):
            self.assertIn(s, panels)
        self.assertNotIn("Panel.PANE, H", panels)                    # la hauteur des fenêtres s'adapte à leur nombre


if __name__ == "__main__":
    unittest.main()
