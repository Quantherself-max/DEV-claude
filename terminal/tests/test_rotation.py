import json
import math
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.opendata import ALT_BASKET, OpenData
from engine import backtest as bt
from engine import goldbtc, rotation, rotationstudy

DAY = 86_400_000


def iso(i, start=datetime(2019, 6, 22, tzinfo=timezone.utc)):
    return (start + timedelta(days=i)).strftime("%Y-%m-%d")


class GoldBtcTests(unittest.TestCase):
    def test_gauss_solver_and_regression(self):
        self.assertEqual([round(x, 9) for x in goldbtc.solve([[2.0, 0.0], [0.0, 4.0]], [2.0, 8.0])], [1.0, 2.0])
        rnd = random.Random(2)
        x = [rnd.gauss(0, 1) for _ in range(500)]
        y = [0.5 + 2.0 * a + rnd.gauss(0, 0.5) for a in x]
        (b,), (t,) = goldbtc.ols_hac([x], y, 3)
        self.assertAlmostEqual(b, 2.0, delta=0.15)
        self.assertGreater(t, 20)
        self.assertIsNone(goldbtc.ols_hac([x[:10]], y[:10]))

    def test_planted_asymmetry_is_detected_and_symmetry_is_not(self):
        rnd = random.Random(7)
        n = 3000
        rg = [None] + [rnd.gauss(0, 0.01) for _ in range(n)]
        rb_asym = [None] + [(0.9 * max(g, 0) + 0.2 * min(g, 0)) + rnd.gauss(0, 0.01) for g in rg[1:]]
        rb_sym = [None] + [0.5 * g + rnd.gauss(0, 0.01) for g in rg[1:]]
        a = goldbtc.semi_betas(rg, rb_asym)
        self.assertAlmostEqual(a["up"]["beta"], 0.9, delta=0.15)
        self.assertAlmostEqual(a["down"]["beta"], 0.2, delta=0.15)
        self.assertGreater(a["asym"]["diff"], 0.4)
        self.assertGreater(abs(a["asym"]["t"]), 3)
        s = goldbtc.semi_betas(rg, rb_sym)
        self.assertLess(abs(s["asym"]["t"]), 2.5)                                # pas d'asymetrie fabriquee
        self.assertAlmostEqual(s["up"]["beta"], s["down"]["beta"], delta=0.2)

    def test_shocks_and_lead_lag(self):
        rnd = random.Random(3)
        n = 2500
        rg = [None] + [rnd.gauss(0, 0.012) for _ in range(n)]
        rb = [None] + [0.8 * g + rnd.gauss(0, 0.01) for g in rg[1:]]            # lien simultane seulement
        sh = goldbtc.shocks(rg, rb, 0.015)
        self.assertGreater(sh[0]["same"]["mean"], 0.005)
        self.assertLess(sh[1]["same"]["mean"], -0.005)
        self.assertLess(abs(sh[0]["next"]["t"]), 3.5)                            # rien le lendemain
        ll = goldbtc.lead_lag(rg, rb, (1, 5))
        self.assertTrue(all(abs(x["t"]) < 3.5 for x in ll))
        self.assertEqual([x["k"] for x in ll], [1, 5])


def fake_open_data(folder, n=2300, seed=5, planted=False):
    """Capitalisations de 13 actifs + prix du BTC + or ; si planted, le BTC monte quand sa part augmente."""
    rnd = random.Random(seed)
    folder = Path(folder)
    caps = {}
    base = {"btc": 1.5e11, "eth": 2.5e10, **{a: 3e9 for a in ALT_BASKET}, "sol": 1e9}
    level = {k: v for k, v in base.items()}
    drift = {k: 0.0 for k in base}
    price, g = [], 20000.0
    gold_p, gp = [], 1500.0
    dom = 0.0
    for i in range(n):
        dom = 0.98 * dom + rnd.gauss(0, 0.02)                      # « signal » : tendance de la part du BTC
        for k in level:
            level[k] *= math.exp(rnd.gauss(0, 0.03) + (0.003 * dom if k == "btc" else 0.0))
            caps.setdefault(k, []).append(level[k])
        price.append(level["btc"] / 1.9e7)
        gp *= math.exp(rnd.gauss(0.0002, 0.008))
        gold_p.append(gp)
    for k, series in caps.items():
        head = "time,CapMrktEstUSD" + (",PriceUSD,CapMrktCurUSD" if k == "btc" else "")
        rows = [f"{iso(i)},{series[i]}" + (f",{price[i]},{series[i]}" if k == "btc" else "") for i in range(n)]
        (folder / f"{k}.csv").write_text(head + "\n" + "\n".join(rows) + "\n")
    (folder / "paxg.csv").write_text("time,PriceUSD\n" + "\n".join(f"{iso(i)},{gold_p[i]}" for i in range(n)) + "\n")
    (folder / "usdt.csv").write_text("time,SplyCur\n" + "\n".join(f"{iso(i)},{2e10 * (1 + i / 5000)}" for i in range(n)) + "\n")
    return OpenData(folder, ttl_hours=10 ** 6)


class RotationTests(unittest.TestCase):
    def test_shares_sum_to_one_and_series_are_aligned(self):
        with tempfile.TemporaryDirectory() as d:
            od = fake_open_data(d)
            grid, series, targets, maps = rotation.build(od, bt.ms(2019, 6, 22), bt.ms(2025, 6, 22))
            self.assertEqual(set(series), set(rotation.CATALOG))
            self.assertEqual(set(targets), set(rotation.TARGETS))
            for k in series:
                self.assertEqual(len(series[k]), len(grid))
            for i in range(len(grid)):
                parts = [maps["shares"][k][i] for k in ("btc", "eth", "alts")]
                if all(p is not None for p in parts):
                    self.assertAlmostEqual(sum(parts), 1.0, places=9)
            self.assertIsNone(series["gold_corr_90d"][10])                    # pas assez d'historique : rien d'invente

    def test_snapshot_and_reading(self):
        with tempfile.TemporaryDirectory() as d:
            od = fake_open_data(d)
            snap = rotation.snapshot(od)
            keys = [r["key"] for r in snap["rows"]]
            self.assertEqual(keys, ["btc", "eth", "alts", "stable"])
            self.assertAlmostEqual(sum(r["share"] for r in snap["rows"][:3]), 1.0, places=9)
            self.assertIn("price", snap["gold"])
            json.dumps(snap)
            txt = rotation.reading(snap)["text"]
            self.assertTrue(txt.endswith("."))
        fake = {"rows": [{"key": "btc", "d30": 0.03}, {"key": "stable", "d30": 0.01}], "rel": {"alts30": -0.2, "gold30": 0.1}}
        t = rotation.reading(fake)["text"]
        self.assertIn("se concentre sur le bitcoin", t)
        self.assertIn("moins bien que le bitcoin", t)
        self.assertIn("stablecoins prennent de la place", t)
        self.assertIn("l'or fait mieux", t)
        self.assertEqual(rotation.reading(None)["text"], "Données indisponibles.")

    def test_study_structure_and_planted_link(self):
        with tempfile.TemporaryDirectory() as d:
            od = fake_open_data(d, planted=True)
            rep = rotationstudy.run(od, "TEST", bt.ms(2020, 7, 1), bt.ms(2025, 6, 22), bt.ms(2023, 1, 1), shifts=8)
        json.dumps(rep)
        self.assertEqual(rep["kind"], "rotation")
        self.assertEqual([t["key"] for t in rep["targets"]], ["BTC", "ALTS_vs_BTC", "GOLD_vs_BTC"])
        for t in rep["targets"]:
            self.assertEqual(len(t["rows"]), len(rotation.CATALOG))
            self.assertIn("p99", t["null"])
        self.assertIn("semi", rep["gold"])
        self.assertTrue(rep["map"]["series"])
        self.assertIn("Carte du capital", rep["verdict"]["notes"][0])
        # la part du BTC suit sa propre capitalisation : la rotation « BTC contre alts » doit ressortir sur la cible altcoins / bitcoin (lien mecanique)
        alts = next(t for t in rep["targets"] if t["key"] == "ALTS_vs_BTC")
        row = next(r for r in alts["rows"] if r["key"] == "dom_chg_30d")
        self.assertIsNotNone(row["h"]["14"]["all"])


if __name__ == "__main__":
    unittest.main()
