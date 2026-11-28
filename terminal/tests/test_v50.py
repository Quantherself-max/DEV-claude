"""V50 : profils de volume longs (trimestre, mois précédent, année, année précédente, tout l'historique) et colonne delta en face de chaque
profil (acheteurs agressifs moins vendeurs agressifs à chaque prix)."""
from __future__ import annotations
import json
import os
import tempfile
import unittest

from config import Config
from data.simulated import SimulatedSource
import server
from engine import vpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86_400_000


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class LongProfilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        cls.app = server.App(cfg, make_source=lambda c: SimulatedSource())
        cls.app.service.refresh_all()
        cls.m = cls.app.service.markets["BTCUSDT"]

    def test_periods_and_delta(self):
        r = self.app.service.get_profiles("BTCUSDT", ["Q", "PM", "Y", "PY", "A", "inconnu", "Y"])
        self.assertTrue(r["ready"])
        self.assertEqual(list(r["profiles"]), ["Q", "PM", "Y", "PY", "A"])          # inconnu ignoré, doublon retiré
        now = self.m.source.now_ms()
        h1 = self.m.store.h1
        for k, (per, back) in {"Q": ("quarter", 0), "PM": ("month", 1), "Y": ("year", 0), "PY": ("year", 1)}.items():
            p = r["profiles"][k]
            s, e = vpx.period_bounds(per, back, now)
            sel = [c for c in h1 if s <= c.t < e and c.v > 0]
            self.assertEqual((p["start"], p["bars"]), (s, len(sel)), k)
            self.assertAlmostEqual(sum(2 * b - v for _, v, b in p["rows"]), sum(2 * c.tb - c.v for c in sel), delta=1e-6 * sum(c.v for c in sel))
            self.assertAlmostEqual(p["delta"], sum(2 * c.tb - c.v for c in sel), delta=1e-6 * sum(c.v for c in sel))
            self.assertLessEqual(p["val"], p["poc"])
            self.assertLessEqual(p["poc"], p["vah"])
            self.assertNotIn("developing", p)                                          # profils longs : rien d'inutile dans la réponse
        a = r["profiles"]["A"]
        self.assertEqual((a["start"], a["bars"]), (h1[0].t, sum(1 for c in h1 if c.v > 0)))
        self.assertIn("depuis le", a["label"])

    def test_cached_until_the_candles_change(self):
        a = self.m.extra_profile("Y")
        self.assertIs(self.m.extra_profile("Y"), a)

    def test_route_is_light_and_valid(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.request
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profiles?symbol=BTCUSDT&kinds=Y,A") as resp:
                d = json.loads(resp.read())
            self.assertEqual(sorted(d["profiles"]), ["A", "Y"])
            self.assertTrue(all(len(r) == 3 for r in d["profiles"]["Y"]["rows"]))
        finally:
            httpd.shutdown()
            httpd.server_close()


class PageTest(unittest.TestCase):
    def test_elements_option_and_drawing(self):
        desk, panels, app, mtf = read("web", "desk.js"), read("web", "panels.js"), read("web", "app.js"), read("web", "mtf.js")
        for k in ("sessQ", "sessPM", "sessY", "sessPY", "sessA"):
            self.assertIn(f"    {k}: [", desk)
            self.assertIn(f"{k}: false", app)
        self.assertIn("data-copt=\"${key}\"", desk)
        self.assertIn("sel('vpDelta'", desk)
        self.assertIn("'vpDelta', 'heatContrast', 'heatScale'].includes(t.dataset.copt)", desk)
        self.assertIn("static longKinds(o)", panels)
        self.assertIn("delta === 'side'", panels)
        self.assertIn("/api/profiles?symbol=", app)
        self.assertIn("filter(k => ['D', 'W', 'M'].includes(k))", mtf)           # la grille multi-unités garde ses trois profils


if __name__ == "__main__":
    unittest.main()
