"""V48 : onglet Quant réorganisé ; comptant contre perpétuels sur 24 et 48 heures (bougies officielles d'une heure) ; plus d'état des sources."""
from __future__ import annotations
import json
import os
import unittest
from fractions import Fraction as F

from ingest import binance as ib, onchain, venues
from ingest.hub import QuantHub, conviction
from tests.test_v45_ingest import Clock, client, kl, MIN

HOUR = 3_600_000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConvictionTest(unittest.TestCase):
    def test_reading_table(self):
        cases = {(F(3, 100), F(2, 100)): ("both_buy", 2), (F(3, 100), F(-2, 100)): ("spot_vs_shorts", 1),
                 (F(3, 100), F(0)): ("spot_buy", 1), (F(-3, 100), F(2, 100)): ("lev_buy_spot_sell", -1),
                 (F(0), F(5, 100)): ("lev_buy", 0), (F(-3, 100), F(-2, 100)): ("both_sell", -2),
                 (F(-3, 100), F(1, 1000)): ("spot_sell", -1), (F(1, 1000), F(-5, 100)): ("lev_sell", -1), (F(0), F(0)): ("flat", 0)}
        for (s, p), (code, bias) in cases.items():
            r = conviction(s, p)
            self.assertEqual((r["code"], r["bias"]), (code, bias), (s, p))
        self.assertEqual(conviction(F(1, 100), F(-1, 100))["code"], "spot_vs_shorts")       # le seuil de 1 % est compris
        self.assertEqual(conviction(None, F(1, 10))["code"], "missing")                      # rien n'est inventé


class SpotPerpTest(unittest.TestCase):
    T0 = 1_700_000_000_000 - 1_700_000_000_000 % HOUR

    def make(self, perp, spot):
        ck = Clock((self.T0 + 48 * HOUR + 600_000) / 1000)
        c, net, _ = client({"/fapi/v1/klines": [perp], "/api/v3/klines": [spot]}, ck, rate=1000, burst=1000, retries=1)
        hub = QuantHub(["BTCUSDT"], binance=ib.Binance(c, c), bybit=venues.Bybit(c), okx=venues.Okx(c), deribit=venues.Deribit(c),
                       onchain=onchain.OnChain(c, c, c), now=ck.now)
        hub.autostart, hub.seed_pause = False, 0.0
        hub.touch("BTCUSDT", start=False)
        return hub, net

    def test_windows_are_exact_dollars_from_official_hourly_candles(self):
        t = [self.T0 + i * HOUR for i in range(48)]
        # perpétuels : les 24 premières heures 6 achetés / 4 vendus à 100 $, les 24 dernières 4 / 6 ; comptant : toujours 3 / 1
        perp = [kl(x, "100", "101", "99", "100", "6" if i < 24 else "4", "4" if i < 24 else "6") for i, x in enumerate(t)]
        spot = [kl(x, "100", "101", "99", "100", "3", "1") for x in t]
        perp[-1][4] = "102"                                                           # clôture de l'heure en cours
        hub, net = self.make(perp, spot)
        hub.poll_flows()
        self.assertTrue(any("interval=1h" in u and "limit=48" in u for u in net.calls))
        s = hub.snapshot("BTCUSDT")["spotPerp"]
        w24, w48 = s["windows"]["24h"], s["windows"]["48h"]
        self.assertEqual((w24["perp"]["buyUsd"], w24["perp"]["sellUsd"], w24["perp"]["deltaUsd"]), (24 * 400.0, 24 * 600.0, -24 * 200.0))
        self.assertEqual((w24["spot"]["deltaUsd"], w24["spot"]["imb"]), (24 * 200.0, 0.5))
        self.assertEqual((w48["perp"]["deltaUsd"], w48["perp"]["imb"], w48["perp"]["hours"]), (0.0, 0.0, 48))
        self.assertEqual(w24["read"]["code"], "spot_vs_shorts")                       # comptant acheteur, perpétuels vendeurs
        self.assertEqual(w48["read"]["code"], "spot_buy")                             # sur 48 heures les perpétuels s'équilibrent
        self.assertAlmostEqual(w24["spotShareVol"], 2 / 7)                             # par heure : 400 $ au comptant sur 1 400 $ en tout
        self.assertAlmostEqual(w24["spotShareBuy"], 3 / 7)                             # achats : 300 $ au comptant sur 700 $
        self.assertAlmostEqual(w24["perp"]["move"], 0.02)
        self.assertEqual(w24["perp"]["close"], 102.0)                                 # prix de repli tant que le flux en direct n'est pas arrivé
        self.assertEqual(len(s["series"]), 48)
        self.assertEqual(s["series"][0], [t[0], 200.0, 200.0])
        json.dumps(s)

    def test_missing_spot_gives_an_error_not_a_number(self):
        t = [self.T0 + i * HOUR for i in range(48)]
        hub, _ = self.make([kl(x, "100", "101", "99", "100", "6", "4") for x in t], [])
        hub.poll_flows()
        w = hub.snapshot("BTCUSDT")["spotPerp"]["windows"]["24h"]
        self.assertIn("error", w["spot"])
        self.assertEqual(w["read"]["code"], "missing")

    def test_nothing_read_yet(self):
        hub, _ = self.make([], [])
        self.assertIn("error", hub.snapshot("BTCUSDT")["spotPerp"])

    def test_flows_task_runs_every_minute(self):
        self.assertIn(("flows", 60.0), QuantHub.TASKS)


class PageTest(unittest.TestCase):
    def test_sources_card_removed_and_new_card_present(self):
        with open(os.path.join(ROOT, "web", "qtab.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertNotIn("sourcesCard", js)
        self.assertNotIn("État des sources", js)
        self.assertIn("spotPerpCard", js)
        self.assertIn("Comptant contre perpétuels", js)


if __name__ == "__main__":
    unittest.main()
