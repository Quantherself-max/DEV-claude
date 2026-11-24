"""V54 : onglet Quant allégé (« L'essentiel » en grandes cases avec une phrase de lecture, détail rangé dessous), têtes courtes des
fenêtres sous le graphique, unité de temps 3 minutes, onglet Assistant retiré de la page."""
from __future__ import annotations
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from engine.atr import INTERVAL_MS, resample, Candle
from service import TFS

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")


class ThreeMinutesTest(unittest.TestCase):
    def test_tables(self):
        self.assertEqual(TFS[:3], ("1m", "3m", "5m"))
        self.assertEqual(INTERVAL_MS["3m"], 180_000)
        app, mtf = read("app.js"), read("mtf.js")
        self.assertIn("'3m': 180", app)
        self.assertIn("'3m': '3 minutes (les 3 derniers jours)'", app)
        self.assertIn("const TFS = ['1m', '3m', '5m'", mtf)
        from data import store
        self.assertGreaterEqual(store.M1_BARS, 4500)                     # 3 jours de minutes : 1 500 bougies de 3 minutes
        svc = (ROOT / "service.py").read_text(encoding="utf-8")
        self.assertIn('if tf == "3m":', svc)
        self.assertIn("return s.m1[-CHART_DEFAULT:]", svc)               # la 1m reste sur 25 heures

    def test_resample_three_minutes(self):
        m1 = [Candle(t * 60_000, 10 + t, 12 + t, 9 + t, 11 + t, 1.0, 0.6, 10.0, 6.0) for t in range(9)]
        r = resample(m1, INTERVAL_MS["3m"])
        self.assertEqual([k.t for k in r], [0, 180_000, 360_000])
        self.assertEqual((r[0].o, r[0].h, r[0].l, r[0].c, r[0].v), (10, 14, 9, 13, 3.0))
        self.assertAlmostEqual(r[0].tb, 1.8)


class AssistantRemovedTest(unittest.TestCase):
    def test_no_assistant_tab(self):
        html, app, css = read("index.html"), read("app.js"), read("style.css")
        self.assertNotIn('data-layout="chat"', html)
        self.assertNotIn('data-pane="chat"', html)
        for s in ("loadChat", "chatView", "renderSugg", "CHAT_SUGG"):
            self.assertNotIn(s, app, s)
        self.assertNotIn("#desk.lchat", css)
        self.assertIn("$('#chatInstall').onclick", app)                   # réglages de Claude pour Telegram : gardés
        self.assertIn("Pose tes questions sur Telegram (au même bot que les idées) :", html)


class QuantPageTest(unittest.TestCase):
    def test_dashboard(self):
        js = read("quant.js")
        for s in ("function whoLeads(d)", "function regimeKpi(d)", "function cvdKpi(d)", "function leverKpi(d)", "function bookKpi(d)", "function optionsKpi(d)",
                  "function lastSignals(d)", "const READ_SP = {", "const READ_REG = {", "L'essentiel", "qOpen54", "['Fragile', 'amb']", "['Absorption', 'amb']"):
            self.assertIn(s, js, s)
        for code in ("both_buy", "spot_vs_shorts", "spot_buy", "lev_buy_spot_sell", "lev_buy", "both_sell", "spot_sell", "lev_sell", "flat"):
            self.assertIn(code + ":", js)                                  # une phrase pour chaque lecture comptant / perpétuels
        for code in ("cascade_longs", "short_squeeze", "shorts_agressifs", "longs_agressifs", "accumulation_spot", "distribution_spot", "compression", "neutre"):
            self.assertIn(code + ":", js)                                  # et pour chaque régime
        for gone in ("function venuesCard", "function profileCard", "function derivsCard", "function regimeCard", "data-qgo"):
            self.assertNotIn(gone, js, gone)
        self.assertIn("all.slice(0, 6)", js)                               # 6 baleines affichées
        css = read("style.css")
        for s in (".qdash{", ".qk{", ".qkn{", ".qkr{", ".qsig{"):
            self.assertIn(s, css, s)
        self.assertNotIn(".qkv{font-size:28px", css)                      # le style des tableaux clé-valeur (.qkv) n'est pas écrasé

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_syntax(self):
        for f in ("quant.js", "panels.js", "panes.js", "app.js", "desk.js", "mtf.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(WEB / f)]).returncode, 0, f)


class PaneHeadTest(unittest.TestCase):
    def test_short_heads(self):
        p, panes, css = read("panels.js"), read("panes.js"), read("style.css")
        for s in ("paneHead(k, I, idx, Z, zi, G, ok, zok)", "static get HEAD_NAME()", "deltaStrong(I, idx, DV)", "S.head(k, [hd.r1.filter(Boolean)",
                  "'accumulation'", "'distribution'", "chip('neutre')", "noAxis: true}, {v: -0.01 * m"):
            self.assertIn(s, p, s)
        self.assertIn("head(k, rows, tip)", panes)
        self.assertIn('class="pc"', panes)
        self.assertIn(".pwin .phr .pc{", css)


if __name__ == "__main__":
    unittest.main()
