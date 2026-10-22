"""V35 : le funding comme élément du graphique (barres sous les bougies, % par 8 heures ou par an) et tes propres onglets de graphiques
vierges dans la barre du Desk."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from engine import subcharts
from server import API_LEVEL, VERSION, App, serve

H = 3_600_000
WEB = Path(__file__).resolve().parent.parent / "web"


class FundingBarsTests(unittest.TestCase):
    ROWS = [(8 * H * k + 3, 0.0001 * k) for k in range(1, 5)]                   # versements à 8 h, 16 h, 24 h, 32 h (+3 ms)

    def test_short_candles_take_the_payment_closing_their_period(self):
        out = subcharts.funding_bars([0, 4 * H, 8 * H, 12 * H, 24 * H], 4 * H, self.ROWS)
        self.assertEqual([round(v, 4) for v in out["funding"]], [0.01, 0.01, 0.02, 0.02, 0.04])
        self.assertIsNone(out["fundEst"])
        self.assertAlmostEqual(out["fundAvg7"], 0.025)

    def test_long_candles_average_their_payments(self):
        out = subcharts.funding_bars([0], 24 * H, self.ROWS)
        self.assertAlmostEqual(out["funding"][0], 0.02)                       # 0,01 + 0,02 + 0,03 : moyenne 0,02 % par 8 h

    def test_current_period_is_the_estimate(self):
        out = subcharts.funding_bars([32 * H, 36 * H], 4 * H, self.ROWS, now_rate=0.0005, now_ms=37 * H)
        self.assertEqual((out["fundEst"], round(out["funding"][1], 4), round(out["fundNow"], 4)), (0, 0.05, 0.05))
        day = subcharts.funding_bars([24 * H], 24 * H, self.ROWS, now_rate=0.0005, now_ms=37 * H)
        self.assertAlmostEqual(day["funding"][0], 0.045)                     # 0,04 versé + 0,05 estimé
        self.assertEqual(day["fundEst"], 0)

    def test_before_history_and_holes(self):
        out = subcharts.funding_bars([-40 * H, 100 * H], 4 * H, self.ROWS)
        self.assertEqual(out["funding"], [None, None])
        self.assertEqual(subcharts.funding_bars([0], H, [])["funding"], [None])

    def test_faster_payments_are_brought_back_to_8_hours(self):
        rows = [(4 * H * k, 0.0001) for k in range(1, 6)]                      # toutes les 4 heures : 0,01 % par 4 h = 0,02 % par 8 h
        out = subcharts.funding_bars([0], 4 * H, rows, now_rate=0.0001)
        self.assertAlmostEqual(out["funding"][0], 0.02)
        self.assertAlmostEqual(out["fundNow"], 0.02)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tempfile.mkdtemp(), port=0, heatmap_days=40), env_path=None)
        cls.app.service.refresh_all()
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=60) as r:
            return json.loads(r.read())

    def test_funding_under_the_chart(self):
        r = self.get("/api/indicators?symbol=SOLUSDT&tf=1h&fund=1")
        self.assertTrue(r["ready"])
        self.assertEqual(len(r["funding"]), len(r["times"]))
        self.assertGreater(sum(1 for v in r["funding"] if v is not None), len(r["times"]) * 0.9)
        self.assertIsNotNone(r["fundEst"])                                    # la bougie en cours : estimation de la période
        self.assertIsNone(r["fundErr"])
        self.assertTrue(all(abs(v) < 1 for v in r["funding"] if v is not None))   # en % par 8 h (pas en fraction ni en % par an)
        self.assertNotIn("funding", self.get("/api/indicators?symbol=SOLUSDT&tf=1h"))   # sans l'élément : rien de demandé à Binance

    def test_funding_history_is_kept_and_extended(self):
        calls = []
        src = self.app.source
        orig = src.funding_history
        src.funding_history = lambda s, a, b: calls.append((a, b)) or orig(s, a, b)
        try:
            self.app._fund.pop("BTCUSDT", None)
            now = src.now_ms()
            rows, err = self.app.funding_rows("BTCUSDT", now - 10 * 86_400_000)
            self.assertIsNone(err)
            self.assertGreater(len(rows), 25)
            self.app.funding_rows("BTCUSDT", now - 5 * 86_400_000)                  # déjà en mémoire : rien de redemandé
            self.assertEqual(len(calls), 1)
            rows2, _ = self.app.funding_rows("BTCUSDT", now - 20 * 86_400_000)       # plus loin : seulement le début manquant
            self.assertEqual(len(calls), 2)
            self.assertLess(calls[1][1], rows[0][0])
            self.assertGreater(len(rows2), len(rows))
            self.assertEqual(rows2, sorted(set(rows2)))
        finally:
            src.funding_history = orig

    def test_funding_error_is_reported(self):
        src = self.app.source
        orig = src.funding_history

        def boom(*a):
            raise OSError("injoignable")
        src.funding_history = boom
        try:
            self.app._fund.pop("SOLUSDT", None)
            rows, err = self.app.funding_rows("SOLUSDT", src.now_ms() - 86_400_000)
            self.assertEqual(rows, [])
            self.assertIn("injoignable", err)
        finally:
            src.funding_history = orig
            self.app._fund.pop("SOLUSDT", None)

    def test_version(self):
        self.assertGreaterEqual(float(VERSION), 35)
        self.assertGreaterEqual(API_LEVEL, 34)


class PageTests(unittest.TestCase):
    DESK = (WEB / "desk.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")
    PAN = (WEB / "panels.js").read_text(encoding="utf-8")
    CSS = (WEB / "style.css").read_text(encoding="utf-8")

    def test_funding_element(self):
        self.assertIn("fund: ['Funding'", self.DESK)
        self.assertIn("'oi', 'fund', 'delta'", self.DESK)                      # dans la liste des éléments passés au dessin
        self.assertIn("data-copt=\"fundMode\"", self.DESK)
        self.assertIn("&fund=1", self.DESK)
        self.assertIn("['oi', 'delta', 'fund'].filter", self.PAN)
        self.assertIn("priceScaleId: 'fd'", self.PAN)
        self.assertIn("fund: false, fundMode: '8h'", self.APP)
        self.assertGreaterEqual(int(re.search(r"NEED_API = (\d+)", self.APP).group(1)), 34)

    def test_user_tabs(self):
        for k in ("data-uadd", "data-uren", "data-udel", "data-unew=\"blank\"", "data-unew=\"copy\"", "function addTab(", "function deleteTab(", "MAX_TABS = 12"):
            self.assertIn(k, self.DESK)
        self.assertIn("utabs: st.utabs", self.APP)                              # gardés d'une session à l'autre
        self.assertIn("Array.isArray(p.utabs)", self.APP)
        self.assertIn("Desk.userTab(st.layout)", self.APP)
        self.assertIn("button.utab", self.CSS)

    @unittest.skipUnless(shutil.which("node"), "node absent : texte du funding non vérifié")
    def test_funding_text(self):
        js = ("const LT = {serverNow: () => 0};\n" + self.PAN + "\nconst I = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
              "console.log(JSON.stringify([Panel.fundText(I, 0, false), Panel.fundText(I, 1, true), Panel.fundText(I, 2, false)]));")
        stub = "const FlowUnder0 = 0;"
        I = {"funding": [0.01, -0.02, None], "fundEst": 1, "fundNext": 3 * H + 5 * 60_000, "fundAvg7": 0.0083}
        out = subprocess.run(["node", "-e", stub + js], input=json.dumps(I), capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        a, b, c = json.loads(out.stdout)
        self.assertIn("Funding +0,0100 % / 8 h (+11,0 % par an)", a)
        self.assertIn("moyenne 7 j +0,0083 %", a)
        self.assertIn("Funding −21,9 % par an (−0,0200 % / 8 h)", b)
        self.assertIn("vendeurs à levier nombreux", b)
        self.assertIn("versement dans 3 h 05", b)
        self.assertIn("pas de versement", c)


if __name__ == "__main__":
    unittest.main()
