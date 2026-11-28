"""V56 : l'onglet Quant refait. Quatre verdicts en haut (qui domine entre comptant et perpétuels, levier, stops des perpétuels, options),
six sous-onglets ; serveur : baleines détaillées (calls et puts achetés et vendus, par échéance), max pain de toutes les échéances, DEX par
échéance et par strike, stops estimés des perpétuels et mesures du levier."""
from __future__ import annotations
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from config import Config
from data.liqbars import LiqBars
from quant import options as qo
from quant import whales as qw
from server import App

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")
DAY = 86_400_000
NOW = 1_794_620_167_501


def leg(kind, d, amount, strike=60000.0, expiry=NOW + 7 * DAY, price=0.02, iv=0.5):
    return {"name": f"BTC-X-{int(strike)}-{kind}", "kind": kind, "strike": strike, "expiry": expiry, "dir": d, "amount": amount, "price": price, "iv": iv, "liq": False}


def order(legs, t=NOW - 3_600_000, index=60000.0, delta=0.0):
    return {"t": t, "block": True, "legs": legs, "index": index, "contracts": sum(g["amount"] for g in legs), "notional": sum(g["amount"] for g in legs) * index,
            "premium": 0.0, "delta": delta, "vega": 0.0, "name": "x", "reading": "x", "liq": False}


class WhaleBreakdownTest(unittest.TestCase):
    def test_four_families_and_expiries(self):
        e2 = NOW + 30 * DAY
        orders = [order([leg("P", 1, 100), leg("C", -1, 50)], delta=-60.0),                 # risk reversal baissier
                  order([leg("P", 1, 200, expiry=e2)], delta=-80.0),
                  order([leg("C", 1, 10)], delta=5.0),
                  order([leg("P", -1, 999)], t=NOW - 30 * 3_600_000)]                         # trop ancien : hors des 24 heures
        b = qw.breakdown(orders, NOW, 24)
        self.assertEqual(b["orders"], 3)
        self.assertEqual(b["puts"]["buy"]["contracts"], 300)
        self.assertEqual(b["puts"]["buy"]["n"], 2)
        self.assertEqual(b["calls"]["sell"]["contracts"], 50)
        self.assertEqual(b["calls"]["buy"]["contracts"], 10)
        self.assertEqual(b["puts"]["sell"]["contracts"], 0)
        self.assertAlmostEqual(b["puts"]["buy"]["notional"], 300 * 60000)
        self.assertAlmostEqual(b["puts"]["buy"]["premium"], 300 * 0.02 * 60000)                # prime payée, positive
        self.assertEqual([r["expiry"] for r in b["byExpiry"]], [NOW + 7 * DAY, e2])           # de la plus proche à la plus lointaine
        r0 = b["byExpiry"][0]
        self.assertEqual((r0["putsBuy"], r0["callsSell"], r0["callsBuy"]), (100, 50, 10))
        self.assertLess(r0["delta"], 0)                                                       # puts achetés et calls vendus : baissier
        self.assertAlmostEqual(r0["premium"], (100 * 0.02 - 50 * 0.02 + 10 * 0.02) * 60000)
        self.assertEqual(b["verdict"]["code"], "puts_buy")
        self.assertEqual(b["verdict"]["bias"], -1)

    def test_nothing(self):
        b = qw.breakdown([], NOW)
        self.assertEqual((b["orders"], b["verdict"]["code"], b["byExpiry"]), (0, "none", []))


class DexDetailTest(unittest.TestCase):
    def test_totals_match_and_strikes_near_price(self):
        rows = [{"expiry": NOW + d * DAY, "strike": float(k), "kind": c, "oi": 10.0 + k / 10000, "iv": 0.5, "f": 60000.0}
                for d in (2, 9, 30) for k in range(40000, 80001, 2000) for c in ("C", "P")]
        x, dd = qo.exposures(rows, NOW), qo.exposures_detail(rows, NOW, 60000.0, strikes=10)
        self.assertAlmostEqual(sum(e["dex"] for e in dd["byExpiry"]), x["dex"], places=2)
        self.assertAlmostEqual(sum(e["gex"] for e in dd["byExpiry"]), x["gex"], places=2)
        self.assertAlmostEqual(sum(e["dexCalls"] + e["dexPuts"] for e in dd["byExpiry"]), x["dex"], places=2)
        self.assertEqual(len(dd["byStrike"]), 10)
        self.assertTrue(all(abs(k[0] - 60000) <= 10000 for k in dd["byStrike"]))
        self.assertTrue(all(k[1] >= 0 and k[2] <= 0 for k in dd["byStrike"]))               # calls : delta positif ; puts : négatif
        self.assertEqual([round(e["days"]) for e in dd["byExpiry"]], [2, 9, 30])

    def test_hub_gives_every_expiry(self):
        from tests.test_v45_ingest import HubTest
        days = (1, 2, 3, 6, 13, 20, 27, 62, 90)
        names, rows = [], []
        for i, dd in enumerate(days):
            exp = (NOW // DAY + dd) * DAY + 8 * 3_600_000
            for k, c in ((60000, "C"), (56000, "P")):
                n = f"BTC-E{i}-{k}-{c}"
                names.append({"instrument_name": n, "expiration_timestamp": exp, "strike": float(k), "option_type": "call" if c == "C" else "put", "contract_size": 1.0})
                rows.append({"instrument_name": n, "open_interest": 10.0 + i, "mark_price": 0.02, "mark_iv": 50.0, "underlying_price": 58000.0, "estimated_delivery_price": 58000.0})
        h = HubTest()
        hub, _, _ = h.make({"get_instruments": {"jsonrpc": "2.0", "result": names},
                            "get_book_summary_by_currency": {"jsonrpc": "2.0", "usOut": NOW * 1000, "result": rows}})
        hub.poll_options()
        o = hub.opt
        self.assertIsNotNone(o, hub.errors)
        self.assertEqual(len(o["maxPain"]), len(days))                                     # avant la V56 : les 6 plus proches seulement
        self.assertEqual(len(o["dex"]["byExpiry"]), len(days))
        self.assertTrue(o["dex"]["byStrike"])
        self.assertAlmostEqual(sum(float(e["dex"]) for e in o["dex"]["byExpiry"]), float(o["dex"]["total"]), places=2)


class LeverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=cls.tmp, port=0, heatmap_days=40), env_path=None)
        cls.app.service.refresh_all()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_stops_and_leverage(self):
        r = self.app.quant_page("BTCUSDT")                                                  # simulé : moteur exact absent, le levier est là quand même
        self.assertFalse(r["ok"])
        L = r["lever"]
        S = L["stops"]
        self.assertGreater(S["price"], 0)
        for side in ("longs", "shorts"):
            self.assertEqual(len(S[side]["bands"]), 6)
            self.assertAlmostEqual(sum(b["usd"] for b in S[side]["bands"]), S[side]["usd"], delta=max(1.0, S[side]["usd"] * 1e-9))
            tops = S[side]["top"]
            for i, a in enumerate(tops):                                                     # des zones distinctes : à plus de 1 % l'une de l'autre
                for b in tops[i + 1:]:
                    self.assertGreater(abs(a["price"] / b["price"] - 1), 0.01)
            self.assertEqual(tops, sorted(tops, key=lambda p: -p["usd"]))
        self.assertTrue(all(p["dist"] < 0 for p in S["longs"]["top"]))                       # stops des longs sous le prix
        self.assertTrue(all(p["dist"] > 0 for p in S["shorts"]["top"]))
        self.assertEqual([t["lev"] for t in S["tiers"]], [100, 50, 25, 10])
        self.assertAlmostEqual(S["tiers"][0]["dist"], 0.006)
        self.assertAlmostEqual(sum(t["weight"] for t in S["tiers"]), 1.0)
        o = L["oi"]
        self.assertGreater(o["coins"], 0)
        self.assertTrue(o["rank30"] is None or 0 <= o["rank30"] <= 100)
        self.assertIn("binance", L["funding"])
        self.assertIn("liq24", L)

    def test_liquidation_totals(self):
        lb = LiqBars(None, now=lambda: NOW / 1000)
        lb.add("SOLUSDT", "binance", NOW - 3_600_000, "long", 100)
        lb.add("SOLUSDT", "bybit", NOW - 60_000, "short", 40)
        lb.add("SOLUSDT", "binance", NOW - 2 * DAY, "long", 999)
        t = lb.totals("SOLUSDT", NOW - DAY)
        self.assertEqual((t["long"], t["short"]), (100.0, 40.0))
        self.assertEqual(t["byEx"], {"Binance": [100.0, 0.0], "Bybit": [0.0, 40.0]})
        self.assertEqual(t["since"], NOW - 2 * DAY - (NOW - 2 * DAY) % 60_000)


class PageTest(unittest.TestCase):
    def test_tabs_and_cards(self):
        js = read("qtab.js")
        for s in ("const TABS = [['sp', 'Comptant / perpétuels'], ['lev', 'Levier et stops'], ['dex', 'DEX et teneurs'], ['wh', 'Baleines et échéances'],",
                  "function summary(d)", "function tabBody(d)", "data-qtab", "qTab56",
                  "function domCard(d)", "function venueSplit(d, k)", "function whoBuysCard(d)", "Les perpétuels échangent",
                  "function leverBanner(L)", "function leverTiles(L)", "function stopsCard(L)", "Distance de liquidation selon le levier",
                  "function hedgeCard(d)", "function dexExpiryCard(d)", "function dexStrikeCard(d)", "function dexMoves(d)",
                  "function whaleBanner(d)", "function flowsCard(d)", "function expiryCard(d)", "Calls achetés", "Calls vendus", "Puts achetés", "Puts vendus", "Max pain"):
            self.assertIn(s, js, s)
        css = read("style.css")
        for s in (".qsum{", ".qsumc{", ".qtabs{", ".qsplit{", ".qbanner{", ".qlad{", ".qquad{", ".qstk{", ".qexp td"):
            self.assertIn(s, css, s)

    def test_syntax(self):
        if not shutil.which("node"):
            self.skipTest("node absent")
        self.assertEqual(subprocess.run(["node", "--check", str(WEB / "qtab.js")]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
