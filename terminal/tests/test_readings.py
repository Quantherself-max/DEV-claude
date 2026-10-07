import json
import tempfile
import unittest
from pathlib import Path

from alerts import readings as R
from config import Config

H = 3_600_000
DAY0 = 1_790_000_000_000 - (1_790_000_000_000 % (24 * H))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ReadingLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name)
        self.clock = Clock()
        self.log = R.ReadingLog(self.cfg, now=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def snap(self, price=100.0, trend=1):
        return {"price": price, "trend": trend, "trendLabel": "haussière" if trend > 0 else "baissière", "bias": "Neutre", "biasValidated": False,
                "squeeze": "Pas de configuration de squeeze", "squeezeCode": "none", "macro": "NEUTRE", "idea": None}

    def test_one_reading_per_day_and_pair(self):
        self.assertTrue(self.log.due("BTCUSDT", DAY0 + H))
        self.log.record("BTCUSDT", DAY0 + H, self.snap())
        self.assertFalse(self.log.due("BTCUSDT", DAY0 + 20 * H))
        self.assertTrue(self.log.due("SOLUSDT", DAY0 + 20 * H))
        self.assertTrue(self.log.due("BTCUSDT", DAY0 + 25 * H))                       # jour suivant
        self.assertIsNone(self.log.record("BTCUSDT", DAY0 + 25 * H, self.snap(price=None)))
        again = R.ReadingLog(self.cfg, now=self.clock)                                 # relu depuis le disque
        self.assertEqual(len(again.rows), 1)

    def test_outcomes_and_trend_score(self):
        self.log.record("BTCUSDT", DAY0, self.snap(100.0, 1))
        self.log.record("SOLUSDT", DAY0, self.snap(50.0, -1))
        prices = {"BTCUSDT": {24: 102.0, 72: 98.0, 168: 110.0}, "SOLUSDT": {24: 49.0, 72: 45.0, 168: 55.0}}
        price_at = lambda sym, t: prices[sym].get((t - DAY0) // H)
        self.assertEqual(self.log.evaluate(price_at, DAY0 + 30 * H), 2)              # seulement 24 h de recul
        self.assertEqual(self.log.evaluate(price_at, DAY0 + 200 * H), 0)             # pas plus d'une evaluation toutes les 10 minutes
        self.clock.t += 601
        self.assertEqual(self.log.evaluate(price_at, DAY0 + 200 * H), 4)
        pub = self.log.public()
        btc = next(r for r in pub["rows"] if r["symbol"] == "BTCUSDT")
        self.assertAlmostEqual(btc["after"]["24"], 2.0)
        self.assertAlmostEqual(btc["after"]["72"], -2.0)
        s72 = pub["trendScore"]["72"]
        self.assertEqual((s72["n"], s72["right"]), (2, 1))                           # BTC haussier mais -2 % ; SOL baissier et -10 %
        self.assertAlmostEqual(s72["avg"], (-2.0 + 10.0) / 2)
        self.assertEqual(pub["trendScore"]["168"]["right"], 1)

    def test_snapshot_from_lecture(self):
        lec = {"head": {"price": 85000.0, "trend": {"regime": 1, "label": "haussière"}, "bias": {"label": "Neutre", "validated": False}},
               "squeeze": {"code": "short_fuel", "label": "Des shorts s'accumulent"}, "chips": [{"key": "macro", "value": "RISK-OFF"}],
               "idea": {"side": "long", "score": 72.0, "eligible": True}}
        s = R.snapshot(lec)
        self.assertEqual((s["price"], s["trend"], s["squeezeCode"], s["macro"], s["idea"]["side"]), (85000.0, 1, "short_fuel", "RISK-OFF", "long"))
        self.assertIsNone(R.snapshot({"head": {"price": 1.0}, "idea": {"n": 0}})["idea"])


class HistoryApiTests(unittest.TestCase):
    def test_history_endpoint_and_reading_cycle_on_simulated_market(self):
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
            app.service.refresh_all()
            app.reading_cycle(app.service, ["BTCUSDT"])
            self.assertNotIn("lectures", app.service.errors)
            rows = app.readings.public()["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "BTCUSDT")
            self.assertIn(rows[0]["trend"], (-1, 0, 1))
            app.reading_cycle(app.service, ["BTCUSDT"])
            self.assertEqual(len(app.readings.public()["rows"]), 1)                   # une seule par jour
            out = {**app.desk.history(NOW), "readings": app.readings.public(), "direction": app.cfg.signal_direction}
            json.dumps(out)
            self.assertEqual(out["direction"], "long")
            settings = app.save_settings({"signalDirection": "both"})
            self.assertEqual(settings["signalDirection"], "both")
            self.assertEqual(app.desk.cfg.signal_direction, "both")


if __name__ == "__main__":
    unittest.main()
