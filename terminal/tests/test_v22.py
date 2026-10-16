"""V22 : mesures refaites sur l'historique Binance (perpetuels BTC et SOL, vrai volume acheteur agressif). Le rapport d'absorptions livre
avec le terminal (outil, de 5 min a 4 h) est utilise quand tu n'as pas lance l'outil toi-meme."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import absorption as ab
from engine.atr import Candle

H = 3_600_000


def synth(N, seed):
    rnd = random.Random(seed)
    out, p = [], 100.0
    for i in range(N):
        o = p
        r = rnd.gauss(0, 0.004)
        p = o * (1 + r)
        v = 100 * (1 + abs(rnd.gauss(0, 0.6)))
        share = 0.5 + 0.1 * (r / 0.004) + rnd.gauss(0, 0.06)
        if rnd.random() < 0.01:
            share = 0.5 - 0.35 * (1 if r > 0 else -1)
        share = min(0.95, max(0.05, share))
        out.append(Candle(i * H, o, max(o, p) * 1.001, min(o, p) * 0.999, p, v, v * share))
    return out


class ShippedAbsorptionReportTests(unittest.TestCase):
    def test_shipped_tool_report_is_used_and_not_hidden(self):
        from config import Config
        from server import App
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None)
        app.service.refresh_all()
        svc = app.service
        m = svc.markets["BTCUSDT"]
        candles = list(m.store.closed_h1())
        svc.source.name = "binance"                                             # comme avec les vraies donnees
        try:
            empty = Path(tempfile.mkdtemp())
            with mock.patch("service.ROOT", empty):                             # aucun rapport livre : le terminal mesure lui-meme et ecrit son rapport
                svc.compute_absorb("BTCUSDT", candles)
            mine = Path(cfg.data_dir) / "reports" / "absorption_BTC.json"
            self.assertTrue(mine.exists())
            self.assertEqual(json.loads(mine.read_text(encoding="utf-8"))["origin"], "terminal")
            self.assertEqual(set(m.absorb_study), {"1h", "4h"})
            shipped = Path(tempfile.mkdtemp())
            st = ab.study(synth(9000, 3))
            rep = ab.report("BTC", {"5m": st, "15m": st, "1h": st, "4h": {"ready": False}}, "Binance Vision (futures)", "outil", 1, 1.0)
            (shipped / "reports").mkdir()
            (shipped / "reports" / "absorption_BTC.json").write_text(json.dumps(rep), encoding="utf-8")
            with mock.patch("service.ROOT", shipped):                           # rapport livre : il l'emporte et ta mesure plus courte s'efface
                svc.compute_absorb("BTCUSDT", candles)
            self.assertEqual(set(m.absorb_study), {"5m", "15m", "1h"})
            self.assertFalse(mine.exists())
            self.assertEqual(m.state("5m")["absorb"]["studyTf"], "5m")
            old = dict(rep, version=ab.VERSION - 1)                             # rapport livre d'une version anterieure : ignore
            (shipped / "reports" / "absorption_BTC.json").write_text(json.dumps(old), encoding="utf-8")
            with mock.patch("service.ROOT", shipped):
                svc.compute_absorb("BTCUSDT", candles)
            self.assertEqual(set(m.absorb_study), {"1h", "4h"})
        finally:
            del svc.source.name


class DeliveredReportsTests(unittest.TestCase):
    """Rapports livres avec le terminal (reports/) : SOL mesure sur le perpetuel Binance, BTC verifie sur les deux historiques."""
    ROOT = Path(__file__).resolve().parent.parent / "reports"

    def load(self, name):
        return json.loads((self.ROOT / name).read_text(encoding="utf-8"))

    def test_sol_has_every_measure_from_binance(self):
        from data import reports as reports_mod
        for kind in ("backtest", "strategy", "avwap", "pockets", "squeeze", "tpo", "absorption"):
            r = self.load(f"{kind}_SOL.json")
            self.assertIn("Binance", json.dumps(r.get("source"), ensure_ascii=False), kind)
            self.assertNotIn("agressif reel", json.dumps(r, ensure_ascii=False), kind)
            self.assertIsNotNone(reports_mod.load([self.ROOT], "SOL", kind), kind)
        sq = self.load("squeeze_SOL.json")
        self.assertTrue(sq["hasOi"] and sq["hasFunding"])                          # interet ouvert et financement reels

    def test_absorption_reports_are_used_by_the_terminal(self):
        for lab in ("SOL", "BTC"):
            r = self.load(f"absorption_{lab}.json")
            self.assertEqual((r["origin"], r["version"]), ("outil", ab.VERSION))   # sinon le terminal l'ignore (version de la mesure)
            self.assertTrue(r["tfs"]["5m"]["ready"] and r["tfs"]["1h"]["ready"])
            self.assertTrue(ab.compact(r["tfs"]["5m"]))

    def test_tpo_reports_feed_the_tpo_view(self):
        from engine import tpostudy
        for lab in ("SOL", "BTC"):
            r = self.load(f"tpo_{lab}.json")
            for kind in ("D", "4h", "1h", "W"):
                self.assertIsNotNone(tpostudy.compact(r, kind), (lab, kind))
        self.assertNotIn("du bitcoin", json.dumps(self.load("tpo_SOL.json"), ensure_ascii=False))

    def test_btc_price_measures_carry_the_binance_check(self):
        for kind in ("backtest", "strategy", "avwap", "pockets"):
            r = self.load(f"{kind}_BTC.json")
            self.assertIn("Bitstamp", r["source"], kind)                            # 13 ans de Bitstamp gardes...
            self.assertTrue(any(n.startswith("Vérification sur le perpétuel Binance") for n in r["verdict"]["notes"]), kind)   # ... verifies sur Binance
        t = self.load("tpo_BTC.json")
        self.assertTrue(any(x.get("key") == "check" and "Binance" in x["text"] for x in t["summary"]))
        sq = self.load("squeeze_BTC.json")
        self.assertTrue(sq["hasOi"] and "Binance" in sq["source"])                  # vrai delta et interet ouvert : la mesure Binance remplace


if __name__ == "__main__":
    unittest.main()
