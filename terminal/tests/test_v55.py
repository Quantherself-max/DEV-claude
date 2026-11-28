"""V55 : l'onglet Option refait comme TradingView. Une fenêtre par donnée sous le graphique (delta perpétuel, delta comptant, CVD dans sa
propre fenêtre, intérêt ouvert en bougies vertes et rouges, liquidations), même hauteur, nom de chaque série sur son étiquette, échelle du
temps tout en bas ; et les liquidations de chaque bougie, enregistrées minute par minute (data/liqbars.py)."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from data.cexflow import CexFlow
from data.liqbars import LiqBars, read_jsonl
from data.live import LiveFeed
from server import API_LEVEL, VERSION, App, serve

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")
H = 3_600_000
NOW = 1_764_000_000_000


def clock():
    return NOW / 1000


class LiqBarsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def test_minutes_summed_into_each_candle(self):
        lb = LiqBars(self.tmp, now=clock)
        lb.add("SOLUSDT", "binance", NOW - H + 5_000, "long", 1000)
        lb.add("SOLUSDT", "binance", NOW - H + 65_000, "short", 500)
        lb.add("SOLUSDT", "bybit", NOW - 60_000, "long", 200)
        lb.add("SOLUSDT", "binance", NOW, "long", 0)                     # montant nul : ignoré
        times = [NOW - 3 * H, NOW - 2 * H, NOW - H, NOW - H + 30 * 60_000]
        b = lb.bars("SOLUSDT", times, NOW)
        self.assertEqual(b["liqLong"], [None, None, 1000.0, 200.0])      # rien avant le premier relevé, zéro ensuite
        self.assertEqual(b["liqShort"], [None, None, 500.0, 0.0])
        self.assertEqual(b["liqSince"], NOW - H)
        self.assertEqual(b["liqEx"], ["Binance", "Bybit"])
        self.assertEqual(lb.bars("BTCUSDT", times, NOW)["liqSince"], None)

    def test_saved_reloaded_and_never_seeded_twice(self):
        lb = LiqBars(self.tmp, now=clock)
        evs = [{"t": NOW - H + 5_000, "side": "long", "usd": 1000.0}, {"t": NOW - 40 * 86_400_000, "side": "long", "usd": 9.0}]
        self.assertEqual(lb.seed_events("SOLUSDT", "binance", evs), 1)   # plus de 30 jours : écarté
        lb.maybe_save(force=True)
        lb2 = LiqBars(self.tmp, now=clock)
        self.assertGreater(lb2.load(["SOLUSDT"]), 0)
        self.assertEqual(lb2.seed_events("SOLUSDT", "binance", evs), 0)  # déjà enregistré
        self.assertEqual(lb2.seed_events("SOLUSDT", "binance", [{"t": NOW + 10_000, "side": "short", "usd": 7.0}]), 1)   # noté après la sauvegarde
        self.assertEqual(lb2.seed_buckets("BTCUSDT", "okx", {NOW - 2 * H: (100.0, 0.0)}), 1)
        self.assertEqual(lb2.seed_buckets("BTCUSDT", "okx", {NOW - 2 * H: (100.0, 0.0), NOW - 3 * H: (1.0, 2.0)}), 1)   # seulement avant
        b = lb2.bars("BTCUSDT", [NOW - 3 * H, NOW - 2 * H], NOW)
        self.assertEqual(b["liqLong"], [1.0, 100.0])
        self.assertEqual(b["liqShort"], [2.0, 0.0])

    def test_old_minutes_pruned(self):
        lb = LiqBars(self.tmp, now=clock, keep_ms=2 * H)
        lb.add("SOLUSDT", "binance", NOW - 3 * H, "long", 5)
        lb.add("SOLUSDT", "binance", NOW - H, "long", 6)
        lb.maybe_save(force=True)
        self.assertEqual(len(lb.m["SOLUSDT"]), 1)
        self.assertEqual(lb.first["SOLUSDT"]["binance"], NOW - H)

    def test_jsonl_reader(self):
        p = Path(self.tmp) / "liqs_SOLUSDT.jsonl"
        p.write_text(json.dumps({"t": NOW, "side": "long", "usd": 3}) + "\nnot json\n" + json.dumps({"t": NOW - 10 * H, "side": "short", "usd": 4}) + "\n", encoding="utf-8")
        self.assertEqual([e["usd"] for e in read_jsonl(p, NOW - H)], [3])
        self.assertEqual(read_jsonl(Path(self.tmp) / "absent.jsonl", 0), [])


class FeedHooksTest(unittest.TestCase):
    def msg(self, sym, side="SELL"):
        return json.dumps({"data": {"e": "forceOrder", "E": NOW, "o": {"s": sym, "S": side, "q": "2", "z": "2", "p": "100", "ap": "100", "T": NOW}}})

    def test_binance_for_every_pair_and_btc_once(self):
        feed = LiveFeed("wss://x", ["BTCUSDT", "SOLUSDT"])
        lb = LiqBars(None, now=clock)
        feed.liqbars = lb
        feed.on_liq(self.msg("SOLUSDT"))                                 # un long liquidé de 200 $
        self.assertEqual(lb.bars("SOLUSDT", [NOW], NOW)["liqLong"], [200.0])

        class Cex:                                                       # le BTC passe par le registre des bourses
            def __init__(self):
                self.flow = CexFlow(None, now=clock)
                self.flow.tap_liq = lambda ex, t, side, usd: lb.add("BTCUSDT", ex, t, side, usd)

            def on_binance_liq(self, ev):
                self.flow.liquidation("binance", int(ev["t"]), ev["side"], float(ev["usd"]), float(ev["price"]))
        feed.cex = Cex()
        feed.on_liq(self.msg("BTCUSDT", "BUY"))                          # un short liquidé : compté une seule fois
        b = lb.bars("BTCUSDT", [NOW], NOW)
        self.assertEqual((b["liqLong"], b["liqShort"]), ([0.0], [200.0]))
        feed.cex.flow.liquidation("okx", NOW, "long", 50.0, 100.0)
        self.assertEqual(lb.bars("BTCUSDT", [NOW], NOW)["liqEx"], ["Binance", "OKX"])


class ServerTest(unittest.TestCase):
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

    def test_version(self):
        self.assertEqual((VERSION, API_LEVEL), ("55", 55))

    def test_liquidations_only_when_asked(self):
        self.assertNotIn("liqLong", self.get("/api/indicators?symbol=SOLUSDT&tf=1h"))
        r = self.get("/api/indicators?symbol=SOLUSDT&tf=1h&liq=1")
        self.assertFalse(r["liqOk"])
        self.assertEqual(len(r["liqLong"]), len(r["times"]))
        t = r["times"][-3] * 1000 + 61_000
        self.app.liqbars.add("SOLUSDT", "binance", t, "long", 1234.0)
        self.app.liqbars.add("SOLUSDT", "binance", t + 1000, "short", 66.0)
        r = self.get("/api/indicators?symbol=SOLUSDT&tf=1h&liq=1")
        self.assertTrue(r["liqOk"])
        self.assertEqual((r["liqLong"][-3], r["liqShort"][-3]), (1234.0, 66.0))
        self.assertIsNone(r["liqLong"][-4])                              # avant le premier relevé
        self.assertEqual(r["liqLong"][-1], 0.0)
        self.assertEqual(r["liqEx"], ["Binance"])

    def test_btc_venues_reach_the_register(self):
        self.assertIsNotNone(self.app.cex)
        self.assertIsNotNone(self.app.cex.flow.tap_liq)
        r0 = self.get("/api/indicators?symbol=BTCUSDT&tf=15m&liq=1")
        t = r0["times"][-2] * 1000 + 30_000
        self.app.cex.flow.liquidation("bybit", t, "short", 900.0, 85_000.0)
        r = self.get("/api/indicators?symbol=BTCUSDT&tf=15m&liq=1")
        self.assertGreaterEqual(r["liqShort"][-2], 900.0)
        self.assertIn("Bybit", r["liqEx"])


class PageTest(unittest.TestCase):
    def test_new_panes_and_order(self):
        desk, panels, panes = read("desk.js"), read("panels.js"), read("panes.js")
        self.assertIn("const PANE_KEYS = ['delta', 'dspot', 'cvd', 'oi', 'liq', 'fund', 'szs', 'szp'];", desk)
        for k in ("dspot: ['Delta comptant'", "cvd: ['CVD'", "liq: ['Liquidations'", "'dspot', 'cvd', 'liq', 'sizes'"):
            self.assertIn(k, desk, k)
        self.assertIn("const ks = ['delta', 'dspot', 'cvd', 'oi', 'liq', 'fund']", panels)
        self.assertIn("static defH(n) { return Math.min(0.2, 0.66 / Math.max(1, n)); }", panes)
        self.assertNotIn('data-pa="bars"', panes)                               # plus de boutons Barres / CVD : le CVD a sa fenêtre
        self.assertIn("${liq ? '&liq=1' : ''}", desk)

    def test_migration_once(self):
        desk = read("desk.js")
        for s in ("function migrate55(s)", "if (!s || s.v55) return s;", "s.paneOrder = ['delta', 'dspot', 'cvd', 'oi', 'liq'];",
                  "if (e.fund === true) e.fund = false;", "return migrate55(u.set);"):
            self.assertIn(s, desk, s)

    def test_tradingview_look(self):
        panels, panes, css = read("panels.js"), read("panes.js"), read("style.css")
        for title in ("tag('dS', 'Perp')", "tag('sdS', 'Comptant')", "tag('cvdS', 'CVD perp')", "tag('oiS', 'OI')", "tag('lqS', 'Shorts')", "tag('lqL', 'Longs')"):
            self.assertIn(title, panels, title)
        self.assertIn("value: -LL[i]", panels)                                  # longs liquidés vers le bas
        self.assertIn("this.p.chart.applyOptions({timeScale: {visible: !last}});", panes)   # échelle du temps sous la dernière fenêtre
        self.assertIn("localization: Panel.LOCAL", panels)
        self.assertIn(".pwin .phb{opacity:0}", css)
        self.assertIn("!PANE_EL.includes(k)", read("desk.js"))
        self.assertIn("const NEED_API = 55;", read("app.js"))

    def test_syntax(self):
        if not shutil.which("node"):
            self.skipTest("node absent")
        for f in ("app.js", "desk.js", "panels.js", "panes.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(WEB / f)]).returncode, 0, f)


if __name__ == "__main__":
    unittest.main()
