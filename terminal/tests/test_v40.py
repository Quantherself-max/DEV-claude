"""V40 : onglet GEX (page a part pour le gamma des options BTC) et V39.1 : zones de gamma coupees par defaut, en bande au bord droit."""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

from server import API_LEVEL, VERSION
from tests.test_v38 import BriefTests

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
WEB = Path(__file__).resolve().parent.parent / "web"


class GexPageTests(unittest.TestCase):
    def make_app(self, tmp, snap):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW as N
        cfg = Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tmp, port=0)
        app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=N), make_hub=lambda c, s: None)

        class Hub:
            def snapshot(self):
                return snap
        app.service.ext = Hub()
        return app

    def test_page_has_everything_for_each_choice(self):
        opt = BriefTests().snap()
        snap = {"derivs": {"options": {"BTC": opt}, "dvol": {"BTC": {"value": 48.5, "chg24h": 0.02, "chg7d": -0.01, "rank": 0.4, "t": 1}}}}
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            app = self.make_app(tmp, snap)
            r = app.service.gex_page()
            self.assertTrue(r["ok"], r.get("why"))
            b = r["brief"]
            for k in ("levels", "strikes", "curve", "flows", "zones", "sources", "em"):
                self.assertIn(k, b)
            self.assertEqual(set(r["compare"]), {"all", "week", "front"})
            self.assertIn("flow2", r["compare"]["all"])
            self.assertEqual(len(r["expiries"]), len(opt["expiries"]))
            self.assertEqual(r["dvol"]["value"], 48.5)
            self.assertIn("hors score", r["note"])
            fr = app.service.gex_page("front", "deribit")
            self.assertEqual((fr["brief"]["scope"], fr["brief"]["src"]), ("front", "deribit"))

    def test_page_says_why_when_nothing_is_there(self):
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            app = self.make_app(tmp, {"derivs": {"options": {}}, "errors": {"options": "Deribit injoignable"}})
            r = app.service.gex_page()
            self.assertFalse(r["ok"])
            self.assertIn("Deribit injoignable", r["why"])
            app.service.ext = None
            self.assertIn("désactivés", app.service.gex_page()["why"])


class PageTests(unittest.TestCase):
    def test_tab_page_and_wiring(self):
        self.assertGreaterEqual(API_LEVEL, 40)
        self.assertEqual(VERSION, str(API_LEVEL))
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-layout="gex"', html)
        self.assertIn('<script src="gex.js"></script>', html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for s in ("gex: [], pair: []", "GEXV.init(window.LT, gg)", "GEXV.show()", "GEXV.onTick(price, live.sym)", "gexView: st.gexView",
                  "gexView: {scope: 'all', src: 'all', range: 10, bars: 'net', curve: true}"):
            self.assertIn(s, app)
        js = (WEB / "gex.js").read_text(encoding="utf-8")
        for s in ("/api/gex?scope=", "Ce que feraient les teneurs de marché", "Selon les échéances prises en compte", "Échéances Deribit", "Bourses",
                  "Mouvement attendu (options)", "/docs/guide_gamma.pdf"):
            self.assertIn(s, js)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn("#desk.lgex{height:auto}", css)
        srv = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('u.path == "/api/gex"', srv)

    def test_gamma_zones_are_off_by_default_and_a_thin_band(self):
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        self.assertIn("gexZones: s.gexZones === 'on'", desk)
        panels = (WEB / "panels.js").read_text(encoding="utf-8")
        self.assertIn("if (mo.gexZones === true)", panels)
        self.assertIn("ctx.fillRect(plotW - 7,", panels)
        self.assertIn("gexZones: false", (WEB / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
