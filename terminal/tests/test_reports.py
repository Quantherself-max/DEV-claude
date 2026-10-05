import json
import tempfile
import unittest
from pathlib import Path

from data import reports


def fake_report(label="BTC", aligned=0.15, counter=-0.11, own=False):
    return {"label": label, "computedAt": 1_700_000_000_000, "period": {"start": 1_356_998_400_000, "end": 1_790_000_000_000, "split": 1_640_995_200_000},
            "verdict": {"text": "x"}, "source": "test", "trend": {"aligned": {"expR": aligned, "n": 1303}, "counter": {"expR": counter, "n": 1588}}}


def fake_strategy(label="BTC", oos=0.02):
    return {"kind": "vwap-strategy", "label": label, "computedAt": 1_700_000_000_000, "period": {"start": 1_356_998_400_000, "end": 1_790_000_000_000, "split": 1_640_995_200_000},
            "verdict": {"text": "pas d'avantage", "edge": False}, "source": "test",
            "best": {"name": "VP mois en cours confirmé + tendance", "cfg": "struct|2R|H48", "all": {"n": 900, "expR": 0.05}, "oos": {"n": 300, "expR": oos}}}


class ReportsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shipped, self.own = Path(self.tmp.name) / "reports", Path(self.tmp.name) / "data_local" / "reports"
        self.shipped.mkdir(parents=True)
        self.own.mkdir(parents=True)
        self.dirs = [self.shipped, self.own]

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, d, rep, name=None):
        (d / (name or f"backtest_{rep['label']}.json")).write_text(json.dumps(rep), encoding="utf-8")

    def test_list_and_load(self):
        self.put(self.shipped, fake_report("BTC"))
        self.put(self.own, fake_report("SOL", 0.3, -0.2))
        (self.shipped / "autre.json").write_text("{}", encoding="utf-8")        # ignore : mauvais nom
        (self.shipped / "backtest_ETH.json").write_text("pas du json", encoding="utf-8")   # ignore : illisible
        labels = [r["label"] for r in reports.summaries(self.dirs)]
        self.assertEqual(labels, ["BTC", "SOL"])
        self.assertEqual(reports.load(self.dirs, "sol")["trend"]["aligned"]["expR"], 0.3)
        self.assertIsNone(reports.load(self.dirs, "XRP"))
        self.assertTrue([r for r in reports.summaries(self.dirs) if r["label"] == "SOL"][0]["own"])

    def test_own_report_overrides_the_shipped_one(self):
        self.put(self.shipped, fake_report("BTC", 0.15))
        self.put(self.own, fake_report("BTC", 0.40))
        self.assertEqual(reports.load(self.dirs, "BTC")["trend"]["aligned"]["expR"], 0.40)

    def test_evidence_uses_own_symbol_else_btc_flagged_as_proxy(self):
        self.put(self.shipped, fake_report("BTC"))
        ev = reports.evidence(self.dirs, "BTCUSDT")
        self.assertFalse(ev["proxy"])
        self.assertAlmostEqual(ev["aligned"], 0.15)
        self.assertIn("BTC 2013-2026", ev["label"])
        sol = reports.evidence(self.dirs, "SOLUSDT")
        self.assertTrue(sol["proxy"])
        self.assertIn("pas encore de rapport", sol["label"])
        self.put(self.own, fake_report("SOL", 0.3, -0.2))
        self.assertFalse(reports.evidence(self.dirs, "SOLUSDT")["proxy"])
        self.assertIsNone(reports.evidence([Path(self.tmp.name) / "vide"], "BTCUSDT"))

    def test_strategy_reports_are_a_separate_kind(self):
        self.put(self.shipped, fake_report("BTC"))
        self.put(self.shipped, fake_strategy("BTC"), name="strategy_BTC.json")
        self.put(self.own, fake_strategy("SOL", 0.1), name="strategy_SOL.json")
        lst = reports.summaries(self.dirs)
        self.assertEqual([(r["kind"], r["label"]) for r in lst], [("backtest", "BTC"), ("strategy", "BTC"), ("strategy", "SOL")])
        self.assertEqual(reports.load(self.dirs, "BTC")["trend"]["aligned"]["n"], 1303)        # par defaut : les idees du terminal
        self.assertEqual(reports.load(self.dirs, "BTC", "strategy")["kind"], "vwap-strategy")
        self.assertIsNone(reports.load(self.dirs, "ETH", "strategy"))
        self.assertIsNone(reports.load(self.dirs, "BTC", "../etc"))
        self.assertTrue([r for r in lst if r["label"] == "SOL"][0]["own"])

    def test_strategy_summary_falls_back_to_btc_as_proxy(self):
        self.put(self.shipped, fake_strategy("BTC"), name="strategy_BTC.json")
        s = reports.strategy_summary(self.dirs, "BTCUSDT")
        self.assertFalse(s["proxy"])
        self.assertEqual(s["bestCfg"], "struct|2R|H48")
        self.assertAlmostEqual(s["oos"]["expR"], 0.02)
        sol = reports.strategy_summary(self.dirs, "SOLUSDT")
        self.assertTrue(sol["proxy"])
        self.put(self.own, fake_strategy("SOL", 0.1), name="strategy_SOL.json")
        self.assertFalse(reports.strategy_summary(self.dirs, "SOLUSDT")["proxy"])
        self.assertIsNone(reports.strategy_summary([Path(self.tmp.name) / "vide"], "BTCUSDT"))


if __name__ == "__main__":
    unittest.main()
