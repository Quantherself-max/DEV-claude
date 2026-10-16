import csv
import math
import random
import tempfile
import unittest
from pathlib import Path

from engine import derivstudy as ds

HOUR = 3_600_000
T0 = 1_760_000_000_000 // HOUR * HOUR


def fake_records(days, rnd, plant=True):
    """Enregistrement toutes les 15 minutes ; le prix horaire suit un signal de financement (AR(1)) avec 2 heures de retard."""
    n = days * 24
    sig, s = [], 0.0
    for _ in range(n):
        s = 0.97 * s + rnd.gauss(0, 1)
        sig.append(s)
    price, p = [], 100.0
    for i in range(n):
        p *= math.exp((-0.0012 * sig[max(0, i - 2)] if plant else 0.0) + rnd.gauss(0, 0.004))     # financement haut -> prix qui baisse
        price.append(p)
    recs = []
    for i in range(n):
        for q in range(4):
            recs.append({"t": T0 + i * HOUR + q * 900_000, "meanFundingAnn": 0.1 + 0.05 * sig[i], "spreadAnn": abs(rnd.gauss(0.02, 0.01)), "oiOthersUsd": 1e9 * (1 + 0.01 * rnd.gauss(0, 1)),
                         "putCall": 0.8 + 0.1 * rnd.gauss(0, 1), "dvol": 50 + rnd.gauss(0, 3)})
    return recs, [(T0 + i * HOUR, price[i]) for i in range(n)]


class DerivStudyTests(unittest.TestCase):
    def test_read_and_hourly_grid(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "X.csv"
            with f.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["t", "meanFundingAnn", "putCall"])
                w.writerow([T0, 0.1, ""])
                w.writerow([T0 + 900_000, 0.2, 0.9])
                w.writerow([T0 + 5 * HOUR, 0.3, 1.0])
            recs = ds.read_records(f)
        self.assertEqual(len(recs), 3)
        self.assertIsNone(recs[0]["putCall"])
        grid, cols = ds.hourly(recs)
        self.assertEqual(len(grid), 6)
        self.assertEqual(cols["meanFundingAnn"][0], 0.2)                      # dernier enregistrement de l'heure
        self.assertEqual(cols["meanFundingAnn"][3], 0.2)                      # reporte au plus 3 heures
        self.assertIsNone(cols["meanFundingAnn"][4])
        self.assertEqual(cols["meanFundingAnn"][5], 0.3)

    def test_not_enough_history_is_said_plainly(self):
        recs, closes = fake_records(3, random.Random(1))
        rep = ds.run(recs, closes, "TEST")
        self.assertFalse(rep["usable"])
        self.assertIn("jour", rep["reason"])

    def test_planted_funding_effect_is_found_and_noise_is_not(self):
        recs, closes = fake_records(70, random.Random(5))
        rep = ds.run(recs, closes, "TEST", shifts=12)
        self.assertTrue(rep["usable"])
        rows = {r["key"]: r for r in rep["rows"]}
        f = rows["fund_mean"]["h"]["24"]["all"]
        self.assertLess(f["spread"], 0)                                       # financement haut -> rendement plus bas
        self.assertLess(f["t"], -2.5)
        self.assertNotEqual(rows["put_call"]["level"], "informatif")
        self.assertEqual(rep["horizons"], [4, 24, 72])


if __name__ == "__main__":
    unittest.main()
