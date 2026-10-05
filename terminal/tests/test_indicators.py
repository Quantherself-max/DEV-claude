import json
import math
import random
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from data import opendata as od
from engine import backtest as bt
from engine import indicators as ind
from engine import indstudy as ist

DAY = 86_400_000


def iso(t):
    return __import__("datetime").datetime.fromtimestamp(t / 1000, __import__("datetime").timezone.utc).strftime("%Y-%m-%d")


class FakeGithub(BaseHTTPRequestHandler):
    files: dict = {}

    def do_GET(self):
        body = self.files.get(self.path.lstrip("/"))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


class OpenDataTests(unittest.TestCase):
    def test_parsing_helpers(self):
        self.assertEqual(od.day_ms("2024-03-01"), 1709251200000)
        self.assertEqual(od.day_ms("2024-03"), 1709251200000)
        self.assertIsNone(od.day_ms("nope"))
        rows = od.read_csv("time,A\n2024-01-01,1\n2024-01-02,\n2024-01-03,3\n2024-01-03,4\n")
        self.assertEqual(od.column(rows, "time", "A"), [(od.day_ms("2024-01-01"), 1.0), (od.day_ms("2024-01-03"), 4.0)])     # vide ignoree, derniere valeur du jour

    def test_dxy_needs_all_six_currencies_and_matches_the_formula(self):
        rows = []
        for c, v in (("Euro", 0.85), ("Japan", 150.0), ("United Kingdom", 0.75), ("Canada", 1.35), ("Sweden", 10.0), ("Switzerland", 0.9)):
            rows.append({"Date": "2024-05-02", "Country": c, "Exchange rate": str(v)})
        rows.append({"Date": "2024-05-03", "Country": "Japan", "Exchange rate": "151"})              # jour incomplet : ignore
        s = od.dxy_series(rows)
        self.assertEqual(len(s), 1)
        eurusd, gbpusd = 1 / 0.85, 1 / 0.75                            # le jeu de donnees donne des monnaies locales pour 1 USD
        want = 50.14348112 * eurusd ** -0.576 * 150.0 ** 0.136 * gbpusd ** -0.119 * 1.35 ** 0.091 * 10.0 ** 0.042 * 0.9 ** 0.036
        self.assertAlmostEqual(s[0][1], want, places=6)
        self.assertTrue(95 < s[0][1] < 115)                                                           # ordre de grandeur d'un DXY

    def test_refresh_downloads_caches_and_survives_an_outage(self):
        FakeGithub.files = {"coinmetrics/data/master/csv/btc.csv": "time,PriceUSD\n2024-01-01,42000\n2024-01-02,43000\n" + "x" * 60 + "\n"}
        srv = HTTPServer(("127.0.0.1", 0), FakeGithub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            o = od.OpenData(d, base=f"http://127.0.0.1:{srv.server_port}", ttl_hours=1, files={"btc": od.FILES["btc"], "usdt": od.FILES["usdt"]})
            res = o.refresh()
            self.assertEqual(res["btc"], "ok")
            self.assertTrue(res["usdt"].startswith("indisponible"))                                   # 404 : pas de copie, pas d'erreur
            self.assertEqual(o.refresh(["btc"])["btc"], "à jour")                                    # copie recente : pas de nouveau telechargement
            self.assertEqual(o.cm("btc", "PriceUSD")[0], (od.day_ms("2024-01-01"), 42000.0))
            srv.shutdown()
            srv.server_close()
            res = o.refresh(["btc"], force=True, timeout=2)
            self.assertTrue(res["btc"].startswith("copie locale"))                                    # internet coupe : on garde la copie
            self.assertEqual(o.available(), ["btc"])

    def test_stablecoin_supply_sums_available_coins(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "usdt.csv").write_text("time,SplyCur\n2024-01-01,100\n2024-01-02,110\n2024-01-03,120\n")
            Path(d, "usdc.csv").write_text("time,SplyCur\n2024-01-02,50\n2024-01-03,55\n")
            s = od.OpenData(d).stablecoin_supply()
            self.assertEqual([v for _, v in s], [100.0, 160.0, 175.0])


class IndicatorMathTests(unittest.TestCase):
    def test_dense_roll_and_changes(self):
        grid = [i * DAY for i in range(10)]
        x = ind.dense([(grid[0], 1.0), (grid[1], 2.0), (grid[5], 6.0)], grid, max_gap=2)
        self.assertEqual(x, [1.0, 2.0, 2.0, 2.0, None, 6.0, 6.0, 6.0, None, None])
        self.assertEqual(ind.pct_change([1, 2, 4, None, 8], 1), [None, 1.0, 1.0, None, None])
        self.assertEqual(ind.roll_mean([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])
        self.assertEqual(ind.roll_sum([1, 2, None, 4, 5], 2), [None, 3, None, None, 9])
        self.assertEqual(ind.cummax([1, None, 3, 2]), [1, 1, 3, 3])
        self.assertAlmostEqual(ind.realized_vol([100 * 1.01 ** i for i in range(60)], 30)[-1], 0.0, places=9)


class StudyMathTests(unittest.TestCase):
    def test_expanding_rank_uses_only_the_past(self):
        r = ist.expanding_rank([1, 2, 3, 4, 5, 6], min_hist=3)
        self.assertEqual(r[:2], [None, None])
        self.assertAlmostEqual(r[2], 1.0)                      # 3 est la plus haute des 3 premieres
        self.assertAlmostEqual(r[5], 1.0)
        self.assertEqual(ist.expanding_rank([5, 4, 3, 2, 1], min_hist=3)[4], 0.0)
        self.assertEqual(ist.expanding_rank([1, 2, 3, 4, 5, 6], 3)[:5], ist.expanding_rank([1, 2, 3, 4, 5], 3))     # ajouter le futur ne change pas le passe

    def test_forward_returns_lag(self):
        p = [100.0, 110.0, 121.0, 133.1, 146.41]
        f = ist.forward_returns(p, 1, lag=1)
        self.assertAlmostEqual(f[0], math.log(1.1))
        self.assertIsNone(f[3])
        self.assertIsNone(f[4])

    def test_hac_slope_recovers_a_planted_slope_and_rejects_noise(self):
        rnd = random.Random(1)
        x = [rnd.uniform(-1, 1) for _ in range(800)]
        y = [0.5 * a + rnd.gauss(0, 0.5) for a in x]
        b, t, n = ist.hac_slope(x, y, 5)
        self.assertAlmostEqual(b, 0.5, delta=0.1)
        self.assertGreater(t, 5)
        y0 = [rnd.gauss(0, 1) for _ in x]
        self.assertLess(abs(ist.hac_slope(x, y0, 5)[1]), 3.5)


class FullStudyTests(unittest.TestCase):
    def test_planted_signal_is_found_and_noise_is_not(self):
        """Prix synthetique dont le rendement des 14 jours suivants depend d'un indicateur (« stable_30d ») ; un autre indicateur (« vix ») est du bruit."""
        rnd = random.Random(11)
        start = bt.ms(2012, 1, 1)
        n = 365 * 8
        t = [start + i * DAY for i in range(n)]
        S, s_ = [], 0.0
        for _ in range(n):                                       # signal persistant (AR(1)) : l'offre de stablecoins suit exp(0,01 S)
            s_ = 0.97 * s_ + rnd.gauss(0, 1)
            S.append(s_)
        d30 = [(S[i] - S[i - 30]) if i >= 30 else 0.0 for i in range(n)]       # ce que mesure « variation sur 30 jours » (a un facteur pres)
        price, p = [], 1000.0
        for i in range(n):
            p *= math.exp(0.002 * d30[max(0, i - 2)] / 4.5 + rnd.gauss(0, 0.02))      # le signal d'il y a 2 jours oriente le rendement du jour
            price.append(p)
        supply = [1e9 * math.exp(0.01 * v) for v in S]
        with tempfile.TemporaryDirectory() as d:
            Path(d, "btc.csv").write_text("time,PriceUSD,CapMrktCurUSD,CapMVRVCur,FlowInExUSD,FlowOutExUSD,SplyExNtv,SplyCur,HashRate,AdrActCnt,TxCnt,FeeTotNtv,volume_reported_spot_usd_1d,IssTotUSD\n" +
                                          "\n".join(f"{iso(t[i])},{price[i]},{price[i] * 1e7},1.5,100,100,5,20,100,1000,1000,1,1e9,1e6" for i in range(n)) + "\n")
            Path(d, "usdt.csv").write_text("time,SplyCur\n" + "\n".join(f"{iso(t[i])},{supply[i]}" for i in range(n)) + "\n")
            vix = [20 + 5 * rnd.gauss(0, 1) for _ in range(n)]
            Path(d, "vix.csv").write_text("DATE,OPEN,HIGH,LOW,CLOSE\n" + "\n".join(f"{iso(t[i])},1,1,1,{vix[i]}" for i in range(n)) + "\n")
            o = od.OpenData(d)
            rep = ist.run(o, "TEST", bt.ms(2013, 6, 1), start + (n - 1) * DAY, bt.ms(2017, 1, 1), horizons=(7, 14), shifts=10)
        json.dumps(rep)
        rows = {r["key"]: r for r in rep["rows"]}
        self.assertEqual(rep["kind"], "indicators")
        self.assertIn("stable_30d", rows)
        # le signal planté se voit : t eleve et de meme signe sur l'apprentissage et le test, sur au moins un horizon
        h = rows["stable_30d"]["h"]["14"]
        self.assertIsNotNone(h["is"])
        self.assertGreater(h["all"]["t"], 2.5)
        # le bruit n'est pas declare informatif
        self.assertNotEqual(rows["vix"]["level"], "informatif")
        self.assertIn("text", rep["verdict"])
        self.assertIn("p95", rep["null"])
        for r in rep["rows"]:
            self.assertIn(r["level"], ("informatif", "indice", "rien"))


if __name__ == "__main__":
    unittest.main()
