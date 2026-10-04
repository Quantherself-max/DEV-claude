import json, tempfile, threading, time, unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from data.external import ExternalHub, RealProviders, SimProviders, normalize_event, parse_num, CROSS, ALT_PAIRS

NOW = 1_790_000_000_000


class Fake(BaseHTTPRequestHandler):
    fail = set()
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        Fake.hits.append(u.path)
        for f in Fake.fail:
            if f in u.path or f in self.path:
                return self._send({"error": "boom"}, 500 if f != "nextweek" else 404)
        if u.path == "/ff_calendar_thisweek.json":
            return self._send([
                {"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
                {"title": "Bank Holiday", "country": "JPY", "date": "2026-10-12T00:00:00-04:00", "impact": "Holiday", "forecast": "", "previous": ""},
                {"title": "Unemployment Claims", "country": "USD", "date": "2026-10-15T08:30:00-04:00", "impact": "Medium", "forecast": "230K", "previous": "227K"},
                {"title": "bad", "country": "USD", "date": "pas une date", "impact": "High"}])
        if u.path == "/ff_calendar_nextweek.json":
            return self._send([{"title": "FOMC Statement", "country": "USD", "date": "2026-10-28T14:00:00-04:00", "impact": "High", "forecast": "", "previous": "4.00%"}])
        if u.path.startswith("/v8/finance/chart/"):
            n = 10
            return self._send({"chart": {"result": [{"timestamp": [1790000000 + i * 300 for i in range(n)],
                                                      "indicators": {"quote": [{"close": [100.0 + i if i != 3 else None for i in range(n)]}]}}]}})
        if u.path == "/api/v3/global":
            return self._send({"data": {"market_cap_percentage": {"btc": 58.5, "eth": 12.0}, "total_market_cap": {"usd": 3.2e12}, "market_cap_change_percentage_24h_usd": 1.1}})
        if u.path == "/v1/global":
            return self._send({"bitcoin_dominance_percentage": 57.9, "market_cap_usd": 3.1e12, "market_cap_change_24h": -0.5})
        if u.path == "/fng/":
            return self._send({"data": [{"value": "35", "value_classification": "Fear", "timestamp": "1789900000"}, {"value": "40", "value_classification": "Fear", "timestamp": "1789813600"}]})
        if u.path == "/api/v3/klines":
            n = int(q.get("limit", 720))
            return self._send([[NOW - (n - i) * 3600_000, "0.02", "0.02", "0.02", f"{0.02 + i * 1e-6}", "1", 0, "1", 1, "1", "1", "0"] for i in range(n)])
        self._send({}, 404)


class ExternalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.b = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        Fake.fail = set(); Fake.hits = []

    def prov(self):
        return RealProviders(self.b, self.b, self.b, self.b, self.b, self.b)

    def test_parse_and_normalize(self):
        self.assertEqual(parse_num("0.3%"), (0.3, "%"))
        self.assertEqual(parse_num("-0.5%"), (-0.5, "%"))
        self.assertEqual(parse_num("227K"), (227.0, "K"))
        self.assertEqual(parse_num("<0.1%"), (0.1, "%"))
        self.assertEqual(parse_num("2.5|3.2"), (2.5, ""))
        self.assertEqual(parse_num(""), (None, ""))
        e = normalize_event({"title": "CPI m/m", "country": "usd", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"})
        self.assertEqual(e["t"], int(datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc).timestamp() * 1000))      # 08:30 New York = 12:30 UTC
        self.assertEqual((e["country"], e["impact"], e["fnum"], e["pnum"], e["unit"]), ("USD", 3, 0.3, 0.2, "%"))
        self.assertIsNone(normalize_event({"title": "x", "date": "n'importe quoi"}))
        self.assertEqual(normalize_event({"title": "Bank Holiday", "country": "JPY", "date": "2026-10-12T00:00:00-04:00", "impact": "Holiday"})["impact"], 0)

    def test_providers_against_fake_servers(self):
        p = self.prov()
        cal = p.calendar()
        self.assertEqual(sorted(e["title"] for e in cal), ["Bank Holiday", "CPI m/m", "FOMC Statement", "Unemployment Claims"])   # semaine suivante incluse, ligne invalide ignoree
        ch = p.yahoo_chart("^TNX", "5m", "5d")
        self.assertEqual(len(ch), 9)                         # le point nul est ecarte
        self.assertEqual(ch[0], (1790000000_000, 100.0))
        self.assertEqual(p.coingecko_global()["btc_d"], 58.5)
        Fake.fail = {"/api/v3/global"}
        g = p.coingecko_global()                              # CoinGecko en panne -> repli CoinPaprika
        self.assertEqual((g["btc_d"], g["src"]), (57.9, "CoinPaprika"))
        self.assertEqual(p.fear_greed(2)[0][1], 40)           # trie par date croissante
        self.assertEqual(len(p.spot_klines("SOLBTC")), 720)

    def test_spot_history_pages_backwards_and_deduplicates(self):
        p = self.prov()
        h = p.spot_history("SOLBTC", "1d", 3)
        ts = [t for t, _ in h]
        self.assertEqual(ts, sorted(set(ts)))                    # pas de doublon meme si le serveur ignore endTime
        self.assertTrue(any("endTime" in c[1] for c in [(x, {}) for x in Fake.hits]) or len(Fake.hits) >= 2)

    def test_hub_refresh_archive_partial_errors_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            hub = ExternalHub(self.prov(), lambda: NOW, d)
            hub.refresh(force=True)
            snap = hub.snapshot()
            self.assertEqual(snap["errors"], {})
            self.assertEqual(len(snap["calendar"]), 4)
            self.assertEqual(set(snap["cross5"]), set(CROSS))
            self.assertEqual(set(snap["alt"]), set(ALT_PAIRS))
            self.assertEqual(set(snap["altD"]), set(ALT_PAIRS) | {"BTCUSDT"})
            self.assertEqual(len(snap["altD"]["SOLBTC"]), 1000)
            self.assertEqual(snap["cg"]["btc_d"], 58.5)
            self.assertEqual(len(snap["cg_hist"]), 1)
            hub.calendar[next(iter(hub.calendar))]["reaction"] = {"btc15": 0.4}   # une valeur mesuree plus tard...
            hub._due.clear(); hub.refresh(force=True)
            self.assertTrue(any("reaction" in e for e in hub.calendar.values()))   # ... survit au rechargement du flux
            hub.save()
            again = ExternalHub(self.prov(), lambda: NOW, d)                       # redemarrage : archive relue
            self.assertEqual(len(again.calendar), 4)
            self.assertEqual(len(again.cg_hist), 1)
            Fake.fail = {"DX-Y.NYB", "/v1/global"}
            hub._due.clear(); hub.refresh(force=True)
            e = hub.snapshot()["errors"]
            self.assertIn("cross5", e); self.assertIn("DXY", e["cross5"])           # panne partielle signalee
            self.assertIn("US10Y", hub.snapshot()["cross5"])                          # les autres series restent disponibles

    def test_total_failure_is_reported_not_raised(self):
        hub = ExternalHub(RealProviders("http://127.0.0.1:9", "http://127.0.0.1:9", "http://127.0.0.1:9", "http://127.0.0.1:9", "http://127.0.0.1:9", "http://127.0.0.1:9"), lambda: NOW)
        t0 = time.time(); hub.refresh(force=True)
        self.assertEqual(set(hub.snapshot()["errors"]), {"calendar", "cg", "fng", "cross5", "crossD", "alt", "altD"})
        self.assertEqual(hub.snapshot()["calendar"], {})

    def test_simulated_providers_cover_every_item(self):
        hub = ExternalHub(SimProviders(lambda: NOW), lambda: NOW)
        hub.refresh(force=True)
        s = hub.snapshot()
        self.assertEqual(s["errors"], {})
        self.assertTrue(all(len(v) > 100 for v in s["cross5"].values()))
        self.assertTrue(any(e["impact"] == 3 and e["t"] > NOW for e in s["calendar"].values()))
        self.assertTrue(any(e["t"] < NOW for e in s["calendar"].values()))


if __name__ == "__main__":
    unittest.main()
