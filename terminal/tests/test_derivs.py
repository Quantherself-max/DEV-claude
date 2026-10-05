import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from data import derivs
from data.base import DataError
from data.external import ExternalHub, RealProviders, SimProviders

NOW = int(datetime(2026, 10, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def tag(days):
    d = datetime.fromtimestamp((NOW + days * DAY) / 1000, timezone.utc)
    return f"{d.day}{MON[d.month - 1]}{d.year % 100}"


class PureTests(unittest.TestCase):
    def test_option_names_and_expiry_at_0800_utc(self):
        o = derivs.parse_option("BTC-27JUN25-100000-C")
        self.assertEqual((o["coin"], o["strike"], o["kind"]), ("BTC", 100000.0, "C"))
        self.assertEqual(o["expiry"], int(datetime(2025, 6, 27, 8, tzinfo=timezone.utc).timestamp() * 1000))
        self.assertIsNone(derivs.parse_option("BTC-PERPETUAL"))
        self.assertIsNone(derivs.parse_option("BTC-32XYZ25-1-C"))

    def test_max_pain_minimises_the_payout(self):
        self.assertEqual(derivs.max_pain({90.0: (10, 0), 100.0: (5, 5), 110.0: (0, 10)}), 100.0)
        self.assertIsNone(derivs.max_pain({}))

    def test_options_view(self):
        summ = []
        for days in (3, 10):
            for k in (80000, 85000, 90000):
                for kind in "CP":
                    summ.append({"instrument_name": f"BTC-{tag(days)}-{k}-{kind}", "open_interest": 100.0 if k == 85000 else 40.0, "underlying_price": 85000.0})
        summ.append({"instrument_name": f"BTC-{tag(-2)}-80000-C", "open_interest": 999.0, "underlying_price": 85000.0})   # echue : ignoree
        summ.append({"instrument_name": "BTC-PERPETUAL", "open_interest": 5.0})
        v = derivs.options_view(summ, NOW)
        self.assertEqual(len(v["expiries"]), 2)
        e = v["expiries"][0]
        self.assertAlmostEqual(e["daysLeft"], 2.8333, places=3)
        self.assertEqual(e["maxPain"], 85000.0)
        self.assertAlmostEqual(e["putCall"], 1.0)
        self.assertEqual(e["walls"][0]["strike"], 85000.0)
        self.assertAlmostEqual(v["oiUsd"], 2 * 3 * 2 * 0 + (100 + 40 + 40) * 2 * 2 * 85000.0)
        with self.assertRaises(DataError):
            derivs.options_view([{"instrument_name": "BTC-PERPETUAL"}], NOW)

    def test_basis_is_annualized(self):
        exp = tag(36)
        rows = derivs.futures_basis([{"instrument_name": "BTC-PERPETUAL", "mark_price": 100.1, "estimated_delivery_price": 100.0, "funding_8h": 0.0001, "open_interest": 1},
                                     {"instrument_name": f"BTC-{exp}", "mark_price": 101.0, "estimated_delivery_price": 100.0, "open_interest": 2},
                                     {"instrument_name": f"BTC-{tag(-5)}", "mark_price": 101.0, "estimated_delivery_price": 100.0}], NOW)
        self.assertTrue(rows[0]["perp"])
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[1]["annualized"], 0.01 * 365 / rows[1]["daysLeft"])
        self.assertTrue(0.09 < rows[1]["annualized"] < 0.11)

    def test_dvol_changes(self):
        pts = [[NOW - (200 - i) * 3_600_000, 0, 0, 0, 50 + i * 0.1] for i in range(201)]
        v = derivs.dvol_view(pts)
        self.assertAlmostEqual(v["value"], 70.0)
        self.assertAlmostEqual(v["chg24h"], 70.0 / 67.6 - 1.0, places=4)
        self.assertAlmostEqual(v["rank"], 1.0)
        with self.assertRaises(DataError):
            derivs.dvol_view(pts[:3])

    def test_compare_view_annualizes_by_interval_and_flags_a_crowd(self):
        v = derivs.compare_view([{"ex": "Bybit", "funding": 0.0001, "intervalH": 8.0, "oiUsd": 600.0}, {"ex": "Hyperliquid", "funding": 0.0000125, "intervalH": 1.0, "oiUsd": 400.0}])
        self.assertAlmostEqual(v["rows"][0]["annualized"], 0.1095, places=4)            # 0,01 % par 8 h
        self.assertAlmostEqual(v["rows"][1]["annualized"], 0.1095, places=4)            # 0,00125 % par heure : meme chose
        self.assertAlmostEqual(v["rows"][0]["oiShare"], 0.6)
        self.assertIsNone(v["crowded"])
        hot = derivs.compare_view([{"ex": "A", "funding": 0.0006, "intervalH": 8.0}, {"ex": "B", "funding": 0.0005, "intervalH": 8.0}])
        self.assertEqual(hot["crowded"], "longs")
        cold = derivs.compare_view([{"ex": "A", "funding": -0.0003, "intervalH": 8.0}, {"ex": "B", "funding": -0.0002, "intervalH": 8.0}])
        self.assertEqual(cold["crowded"], "shorts")
        self.assertIsNone(derivs.compare_view([{"ex": "A", "funding": None}])["meanAnnualized"])


class FakeExchanges(BaseHTTPRequestHandler):
    missing: set = set()

    def _send(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        p = self.path
        if "bybit" in self.missing and p.startswith("/v5/"):
            return self._send({}, 500)
        if p.startswith("/v5/market/tickers"):
            return self._send({"retCode": 0, "result": {"list": [{"symbol": "SOLUSDT", "markPrice": "190", "fundingRate": "0.0001", "fundingIntervalHour": "8", "openInterestValue": "123000000"}]}})
        if "okx" in self.missing and p.startswith("/api/v5/"):
            return self._send({}, 500)
        if p.startswith("/api/v5/public/funding-rate"):
            return self._send({"code": "0", "data": [{"fundingRate": "0.00008", "fundingTime": "1000000000000", "nextFundingTime": str(1000000000000 + 8 * 3_600_000)}]})
        if p.startswith("/api/v5/public/open-interest"):
            return self._send({"code": "0", "data": [{"oi": "1", "oiCcy": "700000", "oiUsd": "133000000"}]})
        if p.startswith("/api/v5/public/mark-price"):
            return self._send({"code": "0", "data": [{"markPx": "189.9"}]})
        if p.startswith("/api/v2/public/get_book_summary_by_currency"):
            if "kind=option" in p:
                res = [{"instrument_name": f"BTC-{tag(7)}-{k}-{kd}", "open_interest": 50.0, "underlying_price": 85000.0} for k in (80000, 85000, 90000) for kd in "CP"]
            else:
                res = [{"instrument_name": "BTC-PERPETUAL", "mark_price": 85010.0, "estimated_delivery_price": 85000.0, "funding_8h": 0.0001, "open_interest": 1e9}]
            return self._send({"result": res})
        if p.startswith("/api/v2/public/get_volatility_index_data"):
            return self._send({"result": {"data": [[NOW - (50 - i) * 3_600_000, 0, 0, 0, 50.0 + i * 0.05] for i in range(51)]}})
        self._send({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if "hyper" in self.missing:
            return self._send({}, 500)
        if body.get("type") == "metaAndAssetCtxs":
            return self._send([{"universe": [{"name": "BTC"}, {"name": "SOL"}]}, [{"funding": "0.00001", "openInterest": "1000", "markPx": "85000"}, {"funding": "0.0000125", "openInterest": "1200000", "markPx": "190.2"}]])
        self._send({}, 404)

    def log_message(self, *a):
        pass


class NetworkParsingTests(unittest.TestCase):
    def setUp(self):
        FakeExchanges.missing = set()
        self.srv = HTTPServer(("127.0.0.1", 0), FakeExchanges)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.srv.server_port}"
        self.old = (derivs.DERIBIT, derivs.BYBIT, derivs.OKX, derivs.HYPER)
        derivs.DERIBIT = derivs.BYBIT = derivs.OKX = derivs.HYPER = base
        self.p = RealProviders()

    def tearDown(self):
        derivs.DERIBIT, derivs.BYBIT, derivs.OKX, derivs.HYPER = self.old
        self.srv.shutdown()
        self.srv.server_close()

    def test_three_exchanges_are_normalized(self):
        rows = {r["ex"]: r for r in self.p.perp_others("SOLUSDT")}
        self.assertEqual(set(rows), {"Bybit", "OKX", "Hyperliquid"})
        self.assertAlmostEqual(rows["Bybit"]["oiUsd"], 123e6)
        self.assertEqual(rows["Bybit"]["intervalH"], 8.0)
        self.assertAlmostEqual(rows["OKX"]["oiUsd"], 133e6)
        self.assertAlmostEqual(rows["OKX"]["intervalH"], 8.0)
        self.assertAlmostEqual(rows["Hyperliquid"]["oiUsd"], 1_200_000 * 190.2)
        self.assertEqual(rows["Hyperliquid"]["intervalH"], 1.0)
        v = derivs.compare_view(list(rows.values()))
        self.assertTrue(0.05 < v["meanAnnualized"] < 0.2)

    def test_one_exchange_down_does_not_hide_the_others_and_all_down_is_an_error(self):
        FakeExchanges.missing = {"bybit"}
        self.assertEqual({r["ex"] for r in self.p.perp_others("SOLUSDT")}, {"OKX", "Hyperliquid"})
        FakeExchanges.missing = {"bybit", "okx", "hyper"}
        with self.assertRaises(DataError):
            self.p.perp_others("SOLUSDT")
        FakeExchanges.missing = set()
        with self.assertRaises(DataError):
            self.p.perp_hyperliquid("DOGE")                              # paire absente de la liste

    def test_deribit(self):
        o = self.p.deribit_options("BTC", NOW)
        self.assertEqual(o["expiries"][0]["maxPain"], 85000.0)
        self.assertEqual(self.p.deribit_dvol("BTC", NOW)["value"], 52.5)
        b = self.p.deribit_futures("BTC", NOW)
        self.assertTrue(b[0]["perp"])


class HubTests(unittest.TestCase):
    def test_hub_collects_derivatives_records_history_and_survives_errors(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [NOW]
            hub = ExternalHub(SimProviders(lambda: clock[0]), lambda: clock[0], d, ("SOLUSDT", "BTCUSDT"))
            hub.refresh(force=True)
            snap = hub.snapshot()
            self.assertEqual(set(snap["derivs"]["options"]), {"BTC", "ETH"})
            self.assertEqual(set(snap["derivs"]["perps"]), {"SOLUSDT", "BTCUSDT"})
            self.assertIn("value", snap["derivs"]["dvol"]["BTC"])
            self.assertEqual(snap["errors"].get("perps"), None)
            f = Path(d) / "history" / "derivs" / "BTCUSDT.csv"
            self.assertTrue(f.exists())
            lines = f.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)
            head = lines[0].split(",")
            self.assertIn("meanFundingAnn", head)
            self.assertIn("putCall", head)
            self.assertEqual(len(lines[1].split(",")), len(head))
            hub.refresh(force=True)                                       # moins de 15 min plus tard : pas de doublon
            self.assertEqual(len(f.read_text(encoding="utf-8").strip().split("\n")), 2)
            clock[0] += 16 * 60_000
            hub.refresh(force=True)
            self.assertEqual(len(f.read_text(encoding="utf-8").strip().split("\n")), 3)

    def test_hub_keeps_the_error_when_a_source_fails(self):
        class Broken(SimProviders):
            def perp_others(self, symbol):
                raise DataError("injoignable")
        hub = ExternalHub(Broken(lambda: NOW), lambda: NOW, None, ("SOLUSDT",))
        hub.refresh(force=True)
        self.assertIn("perps", hub.errors)
        self.assertEqual(hub.snapshot()["derivs"]["perps"], {})
        self.assertNotIn("options", hub.errors)


if __name__ == "__main__":
    unittest.main()
