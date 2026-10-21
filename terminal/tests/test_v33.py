"""V33 : plus d'historique sur le graphique (tout en journalier, 1 500 bougies ailleurs) et intérêt ouvert sur plusieurs années."""
from __future__ import annotations
import io
import json
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path

from config import Config
from data import oiarchive
from server import App, serve
from service import chart_bars

DAY = 86_400_000
H = 3_600_000


def metrics_zip(day_ms, values):
    """Archive « metrics » d'une journée : un relevé toutes les 5 minutes."""
    import time
    rows = ["create_time,symbol,sum_open_interest,sum_open_interest_value"]
    for k, v in enumerate(values):
        t = day_ms + (k + 1) * 300_000
        rows.append(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t / 1000))},BTCUSDT,{v},{v * 100}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("m.csv", "\n".join(rows))
    return buf.getvalue()


class DeepOiTests(unittest.TestCase):
    def test_hourly_values_cached_and_reused(self):
        d0 = 1_700_006_400_000 // DAY * DAY
        now = lambda: (d0 + 2 * DAY) / 1000
        tmp = tempfile.mkdtemp()
        files = {}

        def http(url, timeout=60):
            files[url] = True
            return metrics_zip(d0 if "-%s" % __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime(d0 / 1000)) in url else d0 + DAY,
                               [100.0 + k for k in range(288)])
        deep = oiarchive.DeepOi("BTCUSDT", tmp, now=now, http_bytes=http)
        deep.arch.days = 2
        deep.fetch()
        pts = deep.points()
        self.assertEqual(len(pts), 48)                                                   # une valeur par heure, deux jours
        self.assertEqual(pts[d0 + H], 111.0)                                             # dernier relevé de la première heure (12e)
        self.assertTrue(all(t % H == 0 for t in pts))
        again = oiarchive.DeepOi("BTCUSDT", tmp, now=now, http_bytes=http)
        again.arch.days = 2
        self.assertEqual(again.points(), pts)                                            # relu depuis le fichier, sans rien rouvrir
        self.assertEqual(again.refresh(), 0)


class ChartHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0, heatmap_days=40), env_path=None)
        cls.app.service.refresh_all()
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=120) as r:
            return json.loads(r.read())

    def test_more_candles_and_the_same_ones_under_the_chart(self):
        self.assertEqual((chart_bars("1d"), chart_bars("4h"), chart_bars("1h")), (3000, 1500, 1500))
        for tf in ("1h", "4h", "1d"):
            st = self.get(f"/api/state?symbol=BTCUSDT&tf={tf}")
            m = self.app.service.markets["BTCUSDT"]
            n = min(chart_bars(tf), len(m.chart_candles(tf)))
            self.assertEqual(len(st["candles"]), n)
            self.assertGreater(n, 400)                                                   # avant : 400 bougies seulement
            ind = self.get(f"/api/indicators?symbol=BTCUSDT&tf={tf}")
            self.assertEqual(ind["times"], [c[0] for c in st["candles"]])                 # intérêt ouvert et delta alignés sur toutes les bougies
            ser = self.get(f"/api/series?symbol=BTCUSDT&tf={tf}")
            self.assertEqual(len(ser["times"]), n)                                       # VWAP sur toute la largeur


if __name__ == "__main__":
    unittest.main()
