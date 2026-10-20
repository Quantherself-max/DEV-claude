"""V30 : intérêt ouvert en bougies et delta (avec le CVD) sous le graphique, marques TPO précises et épurées, panneau de droite réduit aux
idées de trade."""
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from engine import subcharts
from engine import tpo as T
from engine.atr import Candle
from server import App, serve

M5 = 300_000
H = 3_600_000
WEB = Path(__file__).resolve().parent.parent / "web"


class SubchartTests(unittest.TestCase):
    def test_open_interest_candles(self):
        pt_t = [M5 * k for k in range(1, 25)]                                 # un relevé toutes les 5 minutes pendant 2 heures
        pt_v = [100.0 + k for k in range(1, 25)]
        pt_v[5] = 90.0                                                         # un creux dans la première heure
        out = subcharts.oi_candles([0, H], H, pt_t, pt_v)
        self.assertEqual(out[0], [101.0, 112.0, 90.0, 112.0])                  # pas de relevé avant : ouverture = premier relevé
        self.assertEqual(out[1][0], 112.0)                                     # ouverture = clôture de la bougie d'avant
        self.assertEqual(out[1][3], 124.0)
        forming = subcharts.oi_candles([2 * H], H, pt_t, pt_v)
        self.assertEqual(forming[0], [124.0, 124.0, 124.0, 124.0])            # bougie en cours sans relevé : la dernière valeur
        self.assertEqual(subcharts.oi_candles([50 * H], H, pt_t, pt_v), [None])

    def test_delta_and_cvd(self):
        cs = [Candle(0, 1, 1, 1, 1, 10.0, 7.0), Candle(H, 1, 1, 1, 1, 10.0, 0.0), Candle(2 * H, 1, 1, 1, 1, 10.0, 2.0)]
        d, cvd = subcharts.deltas(cs)
        self.assertEqual(d, [4.0, None, -6.0])                                # 7 achetés, 3 vendus : +4 ; inconnu : rien
        self.assertEqual(cvd, [4.0, 4.0, -2.0])

    def test_merge_points_prefers_the_live_address(self):
        ts, vs = subcharts.merge_points({0: 5.0}, {M5: 1.0, 2 * M5: 2.0})
        self.assertEqual(ts, [M5, 2 * M5])
        self.assertEqual(vs, [5.0, 2.0])                                       # clé de l'adresse : ouverture de la bougie 5 min


def bars(spec):
    """[(heure de début, haut, bas)] -> bougies de 30 minutes (une par tranche du jour)."""
    return [Candle(t, (h + l) / 2, h, l, (h + l) / 2, 1.0, 0.5) for t, h, l in spec]


class TpoTests(unittest.TestCase):
    def test_exact_edges_of_single_prints(self):
        br = [(0, 100.0, 95.0, 0, 0), (1, 112.0, 99.0, 0, 0), (2, 118.0, 111.5, 0, 0)]
        self.assertEqual(T.exact_single(br, 101.0, 111.0), [100.0, 111.5])    # du plus haut de la tranche du dessous au plus bas de celle du dessus
        self.assertEqual(T.unfilled(100.0, 110.0, 105.0, 120.0), [[100.0, 105.0]])     # seule la partie non retraversée reste
        self.assertEqual(T.unfilled(100.0, 110.0, 90.0, 120.0), [])
        self.assertEqual(T.unfilled(100.0, 110.0, float("inf"), -float("inf")), [[100.0, 110.0]])

    def test_chart_marks_drop_noise(self):
        p = {"step": 1.0, "high": 200.0, "low": 100.0, "singles": [[120.0, 121.0], [140.0, 160.0]], "singlesX": [[120.0, 121.0], [140.0, 160.0]],
             "poorHigh": True, "poorLow": True, "poorHighN": 3, "poorLowN": 2}
        m = T.chart_marks(p, 150.0, 199.0, False, "D")
        self.assertEqual(m["singles"], [[140.0, 150.0, False]])               # la petite zone (1 % de l'amplitude) part ; la grande est coupée là où le prix est repassé
        self.assertEqual((m["poorHigh"]["price"], m["poorHigh"]["n"]), (200.0, 3))
        self.assertEqual(m["poorLow"]["n"], 2)
        self.assertIsNone(T.chart_marks(p, 99.0, 199.0, False, "D")["poorLow"])   # plus bas dépassé depuis : réparé, plus dessiné
        self.assertEqual(T.chart_marks(p, 0, 0, True, "D"), {"singles": [], "poorHigh": None, "poorLow": None})   # journée en cours : rien
        self.assertTrue(T.chart_marks(p, float("inf"), -float("inf"), True, "W")["singles"])                       # semaine en cours : oui

    def test_sessions_carry_chart_marks(self):
        day = 86_400_000 * 20000
        spec = [(day + i * 1_800_000, 100.0 + i, 99.0 + i) for i in range(10)] + [(day + 10 * 1_800_000, 150.0, 149.0)]
        out = T.sessions(bars(spec), "D", day + 86_400_000 + 1)
        s = out["sessions"][-1]
        self.assertIn("chart", s["marks"])
        self.assertIn("singlesX", s)


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

    def test_indicators_cover_the_whole_four_hour_chart(self):
        r = self.get("/api/indicators?symbol=SOLUSDT&tf=4h")
        self.assertTrue(r["ready"])
        self.assertEqual(len(r["times"]), len(r["oi"]))
        self.assertEqual(len(r["times"]), 400)                               # les 400 bougies du graphique
        self.assertGreater(sum(1 for x in r["oi"] if x), 200)                 # 40 jours d'intérêt ouvert archivé : 240 bougies de 4 heures
        self.assertTrue(r["realDelta"])
        self.assertEqual(r["unit"], "SOL")
        st = self.get("/api/state?symbol=SOLUSDT&tf=4h")
        self.assertEqual(r["times"][-1], st["candles"][-1][0])               # les mêmes bougies que le graphique
        self.assertGreaterEqual(int(self.get("/api/config")["version"]), 30)

    def test_tpo_marks_on_the_chart_are_the_clean_ones(self):
        st = self.get("/api/state?symbol=BTCUSDT&tf=1h")
        for kd, sess in st["tpo"].items():
            for ss in sess:
                self.assertEqual(set(ss) >= {"start", "end", "current", "singles", "poorHigh", "poorLow"}, True)
                if ss["current"] and kd not in ("W", "M"):
                    self.assertEqual((ss["singles"], ss["poorHigh"], ss["poorLow"]), ([], None, None))
                for a, b, filled in ss["singles"]:
                    self.assertFalse(filled)
                    self.assertGreater(b, a)


class PageTests(unittest.TestCase):
    HTML = (WEB / "index.html").read_text(encoding="utf-8")
    DESK = (WEB / "desk.js").read_text(encoding="utf-8")
    PANELS = (WEB / "panels.js").read_text(encoding="utf-8")
    SIG = (WEB / "signals.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")

    def test_right_panel_shows_only_trade_ideas(self):
        side = self.HTML[self.HTML.index('<aside id="side">'):self.HTML.index('</aside>', self.HTML.index('<aside id="side">'))]
        self.assertIn('id="sideIdeas"', side)
        self.assertIn('<div class="sidelegacy" hidden>', side)                # l'ancien contenu n'est plus affiché
        self.assertLess(side.index('id="sideIdeas"'), side.index('class="sidelegacy"'))
        self.assertIn("side = document.getElementById('sideIdeas')", self.SIG)
        self.assertIn("if (st.page === 'signals' || st.page === 'desk') Signals.render(r);", self.APP)

    def test_open_interest_and_delta_elements(self):
        self.assertIn("oi: ['Intérêt ouvert'", self.DESK)
        self.assertIn("delta: ['Delta'", self.DESK)
        self.assertIn("/api/indicators?symbol=", self.DESK)
        self.assertIn("this.oiS = this.chart.addCandlestickSeries(", self.PANELS)        # intérêt ouvert en bougies
        self.assertIn("this.dS = this.chart.addHistogramSeries(", self.PANELS)           # delta en barres
        self.assertGreaterEqual(int(__import__("re").search(r"NEED_API = (\d+)", self.APP).group(1)), 31)


if __name__ == "__main__":
    unittest.main()
