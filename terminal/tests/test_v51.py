"""V51 : baleines des options BTC (ordres regroupés, stratégie, prime, delta) et variations de l'intérêt ouvert sur 24 heures ;
onglet Quant rangé en rubriques."""
from __future__ import annotations
import calendar
import json
import os
import tempfile
import unittest

from quant import whales as qw
from ingest.optflow import OptionsFlow, HOUR, DAY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = calendar.timegm((2026, 11, 20, 12, 0, 0)) * 1000


def tr(tid, t, name, direction, amount, price=0.02, index=60000.0, iv=50.0, block=None):
    return {"trade_id": str(tid), "timestamp": t, "instrument_name": name, "direction": direction, "amount": amount, "price": price,
            "index_price": index, "iv": iv, **({"block_trade_id": block} if block else {})}


class NamesAndStrategiesTest(unittest.TestCase):
    def test_parse_name(self):
        m = qw.parse_name("BTC-4DEC26-58000-C")
        self.assertEqual((m["kind"], m["strike"], m["expiry"]), ("C", 58000.0, calendar.timegm((2026, 12, 4, 8, 0, 0)) * 1000))
        self.assertIsNone(qw.parse_name("BTC-PERPETUAL"))
        self.assertIsNone(qw.parse_name("BTC-27XYZ26-60000-P"))

    def legs(self, *spec):
        out = []
        for kind, strike, d, amount, exp in spec:
            out.append({"kind": kind, "strike": strike, "dir": d, "amount": amount, "expiry": exp})
        return sorted(out, key=lambda g: (g["expiry"], g["kind"], g["strike"]))

    def test_classify(self):
        E, F = T0 + 7 * DAY, T0 + 35 * DAY
        cases = [
            (self.legs(("C", 70000, 1, 10, E)), "Achat de call"),
            (self.legs(("P", 50000, -1, 10, E)), "Vente de put"),
            (self.legs(("C", 60000, 1, 10, E), ("C", 70000, -1, 10, E)), "Call spread acheteur"),
            (self.legs(("P", 60000, 1, 10, E), ("P", 50000, -1, 10, E)), "Put spread acheteur"),
            (self.legs(("C", 70000, -1, 10, E), ("P", 50000, -1, 10, E)), "Vente de strangle"),
            (self.legs(("C", 60000, 1, 10, E), ("P", 60000, 1, 10, E)), "Achat de straddle"),
            (self.legs(("C", 70000, 1, 10, E), ("P", 50000, -1, 10, E)), "Risk reversal haussier"),
            (self.legs(("C", 60000, -1, 10, E), ("C", 60000, 1, 10, F)), "Calendrier de calls (report)"),
            (self.legs(("P", 60000, 1, 10, E), ("P", 55000, -1, 10, E), ("P", 52000, -1, 10, E)), "Échelle de puts (put ladder)"),
            (self.legs(("C", 60000, 1, 10, E), ("C", 65000, -1, 20, E), ("C", 70000, 1, 10, E)), "Papillon de calls acheteur"),
            (self.legs(("P", 50000, 1, 10, E), ("P", 55000, -1, 10, E), ("C", 65000, -1, 10, E), ("C", 70000, 1, 10, E)), "Iron condor vendeur"),
        ]
        for legs, name in cases:
            self.assertEqual(qw.classify(legs)["name"], name)

    def test_order_premium_delta_and_generic_reading(self):
        exp = "27NOV26"
        legs = [qw.leg_of(tr(1, T0, f"BTC-{exp}-58000-P", "buy", 150, price=0.025))]
        o = qw.build_order(legs, True)
        self.assertAlmostEqual(o["premium"], 0.025 * 150 * 60000)
        self.assertAlmostEqual(o["notional"], 150 * 60000)
        self.assertLess(o["delta"], 0)                                  # un put acheté est baissier
        self.assertGreater(o["vega"], 0)                                # et achète de la volatilité
        g = [qw.leg_of(tr(2, T0, "BTC-11DEC26-66000-C", "sell", 800)), qw.leg_of(tr(3, T0, "BTC-25DEC26-62000-P", "buy", 800)),
             qw.leg_of(tr(4, T0, "BTC-29JAN27-58000-P", "sell", 800))]
        o = qw.build_order(g, True)
        self.assertTrue(o["name"].startswith("Structure à 3 jambes"))
        self.assertIn("volatilité", o["reading"])


class GrouperTest(unittest.TestCase):
    def test_blocks_and_fills_are_grouped_and_completed_in_order(self):
        g = qw.Grouper(1_000_000)
        page1 = [tr(1, T0, "BTC-27NOV26-60000-P", "buy", 10), tr(2, T0, "BTC-27NOV26-60000-P", "buy", 10),      # un ordre en 2 exécutions
                 tr(3, T0 + 5, "BTC-25DEC26-60000-P", "buy", 150, block="B1"), tr(4, T0 + 5, "BTC-25DEC26-52000-P", "sell", 150, block="B1")]
        out = g.feed(page1)
        self.assertEqual(len(out), 1)                                   # le bloc (dernière heure de la page) attend la page suivante
        self.assertEqual((out[0]["contracts"], out[0]["block"]), (20, False))
        page2 = [tr(4, T0 + 5, "BTC-25DEC26-52000-P", "sell", 150, block="B1"),                                 # déjà vue : ignorée
                 tr(5, T0 + 9, "BTC-25DEC26-55000-P", "sell", 150, block="B1"), tr(6, T0 + 9, "BTC-27NOV26-70000-C", "buy", 1)]
        out = g.feed(page2) + g.finish()
        blocks = [o for o in out if o["block"]]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(blocks[0]["legs"]), 3)
        self.assertEqual(blocks[0]["contracts"], 450)
        self.assertFalse([o for o in out if not o["block"]])            # 1 BTC : sous le seuil, pas une baleine


class OiChangesTest(unittest.TestCase):
    def test_changes_exclude_expired(self):
        old = {"BTC-27NOV26-60000-P": 100.0, "BTC-20NOV26-60000-C": 500.0, "BTC-25DEC26-70000-C": 50.0}
        cur = {"BTC-27NOV26-60000-P": 160.0, "BTC-25DEC26-70000-C": 20.0, "BTC-25DEC26-50000-P": 5.0}
        now = calendar.timegm((2026, 11, 20, 9, 0, 0)) * 1000                                   # l'option du 20/11 est échue (08 h UTC)
        r = qw.oi_changes(cur, old, now, 60000.0)
        self.assertEqual([x["name"] for x in r["up"]], ["BTC-27NOV26-60000-P", "BTC-25DEC26-50000-P"])
        self.assertEqual([x["name"] for x in r["down"]], ["BTC-25DEC26-70000-C"])
        self.assertEqual((r["calls"], r["puts"]), (-30.0, 65.0))
        self.assertEqual(r["up"][0]["usd"], 60 * 60000.0)


class FakeDeribit:
    def __init__(self, trades, oi_rows):
        self.trades, self.oi_rows, self.calls = trades, oi_rows, []

    def option_trades(self, cur, start, end, count=1000):
        self.calls.append((start, end))
        sel = [t for t in self.trades if start <= t["timestamp"] <= end]
        return sel[:2], len(sel) > 2                                    # pages de 2 pour vérifier la pagination

    def book_summary(self, cur, kind):
        return self.oi_rows, None


class OptionsFlowTest(unittest.TestCase):
    def test_backfill_pagination_persistence_and_reference(self):
        clock = [T0 / 1000]
        trades = [tr(1, T0 - 5 * HOUR, "BTC-27NOV26-60000-P", "buy", 100), tr(2, T0 - 4 * HOUR, "BTC-27NOV26-70000-C", "buy", 50),
                  tr(3, T0 - 3 * HOUR, "BTC-27NOV26-65000-C", "sell", 200), tr(4, T0 - 2 * HOUR, "BTC-27NOV26-55000-P", "sell", 300),
                  tr(5, T0 - DAY - HOUR, "BTC-27NOV26-55000-P", "sell", 300)]                       # plus de 24 h : pas relue
        rows = [{"instrument_name": "BTC-27NOV26-60000-P", "open_interest": 100, "estimated_delivery_price": 60000}]
        fake = FakeDeribit(trades, rows)
        d = tempfile.mkdtemp()
        f = OptionsFlow(d, deribit=fake, now=lambda: clock[0], page_pause=0.0)
        f.step(force=True)
        self.assertEqual(len(f.orders), 4)
        self.assertGreaterEqual(len(fake.calls), 2)                     # plusieurs pages
        self.assertEqual(fake.calls[0][0], T0 - DAY)
        s = f.summary(T0, min_usd=5_000_000)
        self.assertEqual([o["contracts"] for o in s["whales"]["biggest"]], [300, 200, 100])  # 50 BTC = 3 M$ : sous 5 M$
        self.assertIsNone(s["oi"])                                      # une seule photo : rien à comparer
        clock[0] += 23.9 * 3600
        fake.oi_rows = [{"instrument_name": "BTC-27NOV26-60000-P", "open_interest": 180, "estimated_delivery_price": 61000}]
        f.snap_oi()
        s = f.summary(int(clock[0] * 1000))
        self.assertAlmostEqual(s["oi"]["gapH"], 23.9, places=6)
        self.assertEqual(s["oi"]["up"][0]["change"], 80.0)
        g = OptionsFlow(d, deribit=fake, now=lambda: clock[0])         # relu depuis le disque
        self.assertEqual((len(g.orders), len(g.snaps), g.last_t), (4, 2, f.last_t))

    def test_close_snapshots_are_not_compared(self):
        clock = [T0 / 1000]
        rows = [{"instrument_name": "BTC-27NOV26-60000-P", "open_interest": 100}]
        f = OptionsFlow(tempfile.mkdtemp(), deribit=FakeDeribit([], rows), now=lambda: clock[0])
        f.snap_oi()
        clock[0] += 600
        f.snap_oi()
        self.assertIsNone(f.summary()["oi"])                           # moins d'une heure d'écart


class HubWiringTest(unittest.TestCase):
    def test_snapshot_carries_whales_for_every_pair(self):
        from tests.test_v45_ingest import HubTest
        rows = [{"instrument_name": "BTC-27NOV26-60000-P", "open_interest": 100}]
        fake = FakeDeribit([tr(1, HubTest.T0, "BTC-27NOV26-60000-P", "buy", 300)], rows)
        h = HubTest()
        f = OptionsFlow(tempfile.mkdtemp(), deribit=fake, now=lambda: HubTest.T0 / 1000 + 60, page_pause=0.0)
        f.step(force=True)
        hub, _, _ = h.make(optflow=f)
        s = hub.snapshot("BTCUSDT", whale_min=1e7)
        self.assertEqual(s["optFlow"]["whales"]["minUsd"], 1e7)
        self.assertEqual(s["optFlow"]["whales"]["sum"]["n"], 1)
        self.assertIn("options", s)
        json.dumps(s)


class PageTest(unittest.TestCase):
    def test_layout_and_new_cards(self):
        with open(os.path.join(ROOT, "web", "qtab.js"), encoding="utf-8") as fh:
            js = fh.read()
        for k in ("function whalesCard", "function oiChangeCard", "function gammaCard", "function volCard", "function section(", "data-qfold",
                  "Principales accumulations", "Principales réductions", "&whale=${wmin}"):
            self.assertIn(k, js)
        self.assertNotIn("function optionsCard", js)
        self.assertNotIn("sourcesCard", js)


if __name__ == "__main__":
    unittest.main()
