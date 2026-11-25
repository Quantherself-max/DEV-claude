"""V54.1 : DEX (exposition delta des options BTC) : calcul, relevé horaire gardé 120 jours (même onglet fermé), résumé pour la page
(dernier relevé, horaire 7 jours, quotidien, rang sur 7, 30 et 90 jours), DEX en direct dans le moteur, carte et historique de l'onglet Quant."""
from __future__ import annotations
import calendar
import json
import math
import tempfile
import unittest
from pathlib import Path

from quant import options as qo
from ingest.optflow import OptionsFlow, DAY, HOUR, EXPO_KEEP

ROOT = Path(__file__).resolve().parent.parent
NOW = calendar.timegm((2026, 11, 25, 12, 0, 0)) * 1000
EXP = calendar.timegm((2026, 12, 25, 8, 0, 0)) * 1000


def row(kind, k, oi, iv=0.5, f=90000.0, exp=EXP):
    return {"strike": float(k), "kind": kind, "expiry": exp, "oi": float(oi), "iv": iv, "f": f}


class ExposuresTest(unittest.TestCase):
    def test_formula(self):
        x = qo.exposures([row("C", 90000, 100), row("P", 90000, 100)], NOW)
        t = (EXP - NOW) / (365 * 86400000)
        d1 = (0.5 * 0.25 * t) / (0.5 * math.sqrt(t))
        self.assertAlmostEqual(x["dex"], 100 * 90000 * (2 * qo.norm_cdf(d1) - 1), places=3)      # delta call + delta put = 2 N(d1) - 1
        self.assertAlmostEqual(x["gex"], 0.0, places=6)                                           # même gamma : calls +, puts -
        self.assertEqual(x["n"], 2)
        p = qo.exposures([row("P", 80000, 300)], NOW)
        self.assertLess(p["dex"], 0)                                                              # des puts seuls : DEX négatif
        self.assertEqual((p["dexCalls"], p["dex"]), (0.0, p["dexPuts"]))
        dead = qo.exposures([row("C", 90000, 50, exp=NOW - 1000), row("C", 90000, 0), row("C", 90000, 10, iv=0)], NOW)
        self.assertEqual((dead["n"], dead["dex"]), (0, 0.0))                                      # échue, sans intérêt ouvert, sans volatilité

    def test_same_gamma_as_gex_by_strike(self):
        rows = [row("C", 95000, 120), row("P", 85000, 300), row("C", 100000, 40, iv=0.6)]
        self.assertAlmostEqual(qo.exposures(rows, NOW)["gex"], qo.gex_by_strike(rows, NOW)["total"], places=4)


class FakeDeribit:
    def __init__(self):
        self.k = 0

    def book_summary(self, cur, kind):
        self.k += 1
        return ([{"instrument_name": "BTC-25DEC26-90000-C", "open_interest": 100 + self.k, "mark_iv": 50, "underlying_price": 90000, "estimated_delivery_price": 89900},
                 {"instrument_name": "BTC-25DEC26-80000-P", "open_interest": 300, "mark_iv": 60, "underlying_price": 90000},
                 {"instrument_name": "BTC-25DEC26-70000-P", "open_interest": 50, "mark_iv": None, "underlying_price": 90000}], None)

    def option_trades(self, *a, **k):
        return [], False


class RecordTest(unittest.TestCase):
    def test_hourly_record_reload_and_summary(self):
        clock = [NOW / 1000]
        d = tempfile.mkdtemp()
        f = OptionsFlow(d, deribit=FakeDeribit(), now=lambda: clock[0])
        for _ in range(50):
            f.snap_oi()
            clock[0] += 3600
        self.assertEqual(len(f.expo), 50)
        t, index, dex, gex, dc, dp = f.expo[-1]
        self.assertEqual(index, 89900.0)
        self.assertAlmostEqual(dex, dc + dp, places=1)
        self.assertGreater(dc, 0)
        self.assertLess(dp, 0)
        g = OptionsFlow(d, deribit=FakeDeribit(), now=lambda: clock[0])                       # relu depuis le disque
        self.assertEqual(g.expo, f.expo)
        s = f.summary(int(clock[0] * 1000))["expo"]
        self.assertEqual((s["n"], len(s["hourly"]), len(s["daily"])), (50, 50, 3))
        self.assertEqual(s["last"]["dex"], dex)
        r7 = s["ranks"]["7"]
        self.assertEqual(r7["n"], 50)
        self.assertAlmostEqual(r7["span"], 49 / 24)
        self.assertEqual(r7["dex"], 98)                                                         # l'intérêt ouvert des calls monte : DEX au plus haut
        json.dumps(s)

    def test_old_points_dropped_and_no_history_yet(self):
        clock = [NOW / 1000]
        f = OptionsFlow(tempfile.mkdtemp(), deribit=FakeDeribit(), now=lambda: clock[0])
        self.assertIsNone(f.summary(NOW)["expo"])                                              # pas encore de relevé : rien d'inventé
        f.expo = [[NOW - EXPO_KEEP - DAY, 1.0, 1.0, 1.0, 1.0, 0.0]]
        f.snap_oi()
        self.assertEqual(len(f.expo), 1)                                                        # le relevé de plus de 120 jours est retiré
        self.assertEqual(EXPO_KEEP, 120 * DAY)


class HubDexTest(unittest.TestCase):
    def test_live_dex_in_options_snapshot(self):
        from tests.test_v45_ingest import HubTest
        inst = {"jsonrpc": "2.0", "result": [
            {"instrument_name": "BTC-20NOV26-66000-C", "expiration_timestamp": 1795161600000, "strike": 6.6e4, "option_type": "call", "contract_size": 1.0},
            {"instrument_name": "BTC-20NOV26-60000-P", "expiration_timestamp": 1795161600000, "strike": 6.0e4, "option_type": "put", "contract_size": 1.0}]}
        summ = {"jsonrpc": "2.0", "usOut": 1794620167501000, "result": [
            {"instrument_name": "BTC-20NOV26-66000-C", "open_interest": 12.5, "mark_price": 0.04, "mark_iv": 41.34, "underlying_price": 68319.17, "estimated_delivery_price": 68245.34},
            {"instrument_name": "BTC-20NOV26-60000-P", "open_interest": 40.0, "mark_price": 0.01, "mark_iv": 55.0, "underlying_price": 68319.17}]}
        h = HubTest()
        hub, _, _ = h.make({"get_instruments": inst, "get_book_summary_by_currency": summ})
        hub.poll_options()
        o = hub.opt
        self.assertIsNotNone(o, hub.errors)
        rows = [{"strike": 66000.0, "kind": "C", "expiry": 1795161600000, "oi": 12.5, "iv": 0.4134, "f": 68319.17},
                {"strike": 60000.0, "kind": "P", "expiry": 1795161600000, "oi": 40.0, "iv": 0.55, "f": 68319.17}]
        x = qo.exposures(rows, 1794620167501)
        self.assertAlmostEqual(o["dex"]["total"], x["dex"], places=4)
        self.assertAlmostEqual(o["dex"]["calls"] + o["dex"]["puts"], o["dex"]["total"], places=4)


class PageTest(unittest.TestCase):
    def test_quant_page(self):
        js = (ROOT / "web" / "qtab.js").read_text(encoding="utf-8")
        for s in ("function dexCard(d)", "function dexChart(E)", "function dexTip(e)", "${dexCard(d)}${lastSignals(d)}", "data-qxw", "data-qxk", "qDexWin", "qDexWhat",
                  "Position delta agrégée du portefeuille d'options. Une exposition structurelle, pas un signal de prix.", "Flux mécanique vendeur", "Flux mécanique acheteur",
                  "Historique DEX &amp; GEX", "extrême bas", "extrême haut", "Deribit ne publie pas l'historique"):
            self.assertIn(s, js, s)
        css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
        for s in (".qdex{", ".qdexv{", ".qdexg{", ".qdexsvg{", ".qdextip{"):
            self.assertIn(s, css, s)


if __name__ == "__main__":
    unittest.main()
