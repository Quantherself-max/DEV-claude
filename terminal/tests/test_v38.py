"""V38 : gamma des options plus precis (Deribit + Bybit + OKX, choix des echeances, strike au plus fort gamma, max pain, mouvement attendu,
flux de couverture, zones) et guide PDF de chaque niveau."""
from __future__ import annotations
import math
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from data.base import DataError
from data.derivs import (DAY, HOUR, MONTHS, YEAR_MS, DerivMixin, SimDerivMixin, bs_gamma, expected_moves, gex_sets, norm_bybit, norm_deribit,
                         norm_okx, options_view, with_gex)
from engine import gamma, lecture
from server import API_LEVEL, VERSION

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
NOW = 1_759_104_000_000                     # lundi 29/09/2025 00:00 UTC
WEB = Path(__file__).resolve().parent.parent / "web"


def tag(days):
    e = datetime.fromtimestamp((NOW + days * DAY) / 1000, timezone.utc)
    return f"{e.day}{list(MONTHS)[e.month - 1]}{e.year % 100}"


def exp_ms(days):
    e = datetime.fromtimestamp((NOW + days * DAY) / 1000, timezone.utc)
    return int(datetime(e.year, e.month, e.day, 8, tzinfo=timezone.utc).timestamp() * 1000)


def row(strike, kind, oi, days=5, iv=0.5, f=100_000.0, ex="Deribit", index=None):
    return {"ex": ex, "strike": float(strike), "kind": kind, "oi": float(oi), "iv": iv, "f": f, "expiry": exp_ms(days), "index": index}


def deribit(strike, kind, oi, days=5, iv=50.0, f=100_000.0):
    return {"instrument_name": f"BTC-{tag(days)}-{int(strike)}-{kind}", "open_interest": oi, "mark_iv": iv, "underlying_price": f}


class ParsingTests(unittest.TestCase):
    def test_bybit_and_okx_rows_have_the_common_shape(self):
        by = norm_bybit([{"symbol": f"BTC-{tag(5)}-100000-C", "openInterest": "12.5", "markIv": "0.52", "underlyingPrice": "100100", "indexPrice": "100000"},
                         {"symbol": f"BTC-{tag(5)}-95000-P-USDT", "openInterest": "3", "markIv": "48", "underlyingPrice": "100100"},     # suffixe et iv en %
                         {"symbol": "BTCUSDT", "openInterest": "1"}, {"symbol": f"BTC-{tag(5)}-90000-P", "openInterest": "0", "markIv": "0.5"}], NOW)
        self.assertEqual([(r["ex"], r["strike"], r["kind"], r["oi"]) for r in by], [("Bybit", 100000.0, "C", 12.5), ("Bybit", 95000.0, "P", 3.0)])
        self.assertAlmostEqual(by[1]["iv"], 0.48)
        self.assertEqual(by[0]["index"], 100000.0)
        self.assertEqual(by[0]["expiry"], exp_ms(5))                     # 08:00 UTC comme Deribit
        e = datetime.fromtimestamp(exp_ms(5) / 1000, timezone.utc)
        inst = f"BTC-USD-{e.year % 100:02d}{e.month:02d}{e.day:02d}-100000-C"
        ok = norm_okx([{"instId": inst, "markVol": "0.5", "fwdPx": "100050"}, {"instId": "BTC-USD-SWAP", "markVol": "0.5"}],
                      [{"instId": inst, "oiCcy": "7.5", "oi": "750"}], NOW)
        self.assertEqual([(r["ex"], r["strike"], r["oi"], r["f"], r["expiry"]) for r in ok], [("OKX", 100000.0, 7.5, 100050.0, exp_ms(5))])
        d = norm_deribit([{**deribit(100_000, "C", 2), "estimated_delivery_price": 99_900}, deribit(100_000, "P", 1, days=-1)], NOW)
        self.assertEqual(len(d), 1)                                       # echeance passee ignoree
        self.assertEqual((d[0]["iv"], d[0]["index"]), (0.5, 99_900))


class GexSetTests(unittest.TestCase):
    def test_sources_and_scopes_add_up(self):
        rows = [row(105_000, "C", 300), row(95_000, "P", 200), row(110_000, "C", 500, days=20), row(100_000, "C", 50, ex="Bybit"),
                row(100_000, "P", 80, ex="OKX", days=1)]
        g = gex_sets(rows, NOW)
        a, d = g["all"], g["deribit"]
        one = gex_sets([row(100_000, "C", 50, ex="Bybit")], NOW)["all"]["all"]["total"]
        two = gex_sets([row(100_000, "P", 80, ex="OKX", days=1)], NOW)["all"]["all"]["total"]
        self.assertAlmostEqual(a["all"]["total"], d["all"]["total"] + one + two, places=3)
        self.assertEqual(d["all"]["n"], 3)
        self.assertEqual(a["all"]["n"], 5)
        self.assertEqual([s["ex"] for s in a["all"]["sources"]], ["Deribit", "OKX", "Bybit"])        # du plus gros au plus petit (en BTC)
        self.assertAlmostEqual(sum(s["share"] for s in a["all"]["sources"]), 1.0)
        self.assertEqual(a["front"]["n"], 1)                              # prochaine echeance : seulement l'option a 1 jour (OKX)
        self.assertEqual(a["front"]["frontExpiry"], exp_ms(1))
        self.assertEqual(d["front"]["n"], 2)                              # Deribit seul : sa prochaine echeance est a 5 jours
        self.assertEqual(a["week"]["n"], 4)                               # l'option a 20 jours n'y est pas
        self.assertEqual(d["front"]["frontExpiry"], exp_ms(5))

    def test_front_skips_an_expiry_less_than_two_hours_away(self):
        soon = {**row(100_000, "C", 10), "expiry": NOW + HOUR}
        g = gex_sets([soon, row(100_000, "C", 10, days=2)], NOW)
        self.assertEqual(g["front"], exp_ms(2))
        self.assertEqual(g["all"]["front"]["n"], 1)

    def test_flips_ignore_exact_zeros_and_find_every_crossing(self):
        self.assertEqual(gex_sets([row(100_000, "C", 10)], NOW)["all"]["all"]["flips"], [])
        g = gex_sets([row(90_000, "P", 400), row(100_000, "C", 300), row(110_000, "P", 400)], NOW)["all"]["all"]
        self.assertEqual(len(g["flips"]), 2)                              # puts en dessous ET au-dessus : deux bascules
        self.assertTrue(90_000 < g["flips"][0] < 100_000 < g["flips"][1] < 110_000)
        self.assertEqual(g["flip"], min(g["flips"], key=lambda x: abs(x - g["spot"])))

    def test_absolute_gamma_strike_can_have_zero_net(self):
        g = gex_sets([row(100_000, "C", 500), row(100_000, "P", 500), row(104_000, "C", 300), row(96_000, "P", 300)], NOW)["all"]["all"]
        k = {x["strike"]: x for x in g["strikes"]}
        self.assertAlmostEqual(k[100_000]["net"], 0.0, places=3)
        self.assertEqual(g["absGamma"], 100_000.0)
        self.assertEqual(g["callWall"], 100_000.0)                        # au prix : compte des deux cotes

    def test_hedge_flows_have_the_right_sign_and_size(self):
        calls = gex_sets([row(100_000, "C", 1000)], NOW)["all"]["all"]
        f1 = calls["flows"][0]
        self.assertEqual(f1["pct"], 1.0)
        self.assertLess(f1["up"], 0)                                     # gamma positif : vente dans la hausse
        self.assertGreater(f1["down"], 0)                                # achat dans la baisse
        self.assertAlmostEqual(-f1["up"] / calls["total"], 1.0, delta=0.08)       # 1 % de mouvement ~ le gamma total en dollars par 1 %
        puts = gex_sets([row(100_000, "P", 1000)], NOW)["all"]["all"]["flows"][1]
        self.assertGreater(puts["up"], 0)                                # gamma negatif : achat dans la hausse
        self.assertLess(puts["down"], 0)

    def test_expected_move_reads_the_volatility_between_two_expiries(self):
        one = expected_moves([{**row(100_000, "C", 1), "expiry": NOW + DAY}], NOW, 100_000.0)
        self.assertAlmostEqual(one["day"]["move"], 100_000 * 0.5 * math.sqrt(1 / 365), places=6)
        self.assertAlmostEqual(one["day"]["pct"], 50 / math.sqrt(365), places=6)
        two = [{**row(100_000, "C", 1, iv=0.4), "expiry": NOW + DAY // 2}, {**row(100_000, "C", 1, iv=0.6), "expiry": NOW + 2 * DAY}]
        w = 0.16 * 0.5 + (0.36 * 2 - 0.16 * 0.5) * (1 - 0.5) / (2 - 0.5)              # variance totale interpolee a 1 jour (en jours)
        self.assertAlmostEqual(expected_moves(two, NOW, 100_000.0)["day"]["iv"], math.sqrt(w / 1), places=6)
        self.assertIsNone(expected_moves([{**row(100_000, "C", 1), "expiry": NOW + HOUR}], NOW, 100_000.0))

    def test_reference_price_is_the_index_when_given(self):
        g = gex_sets([row(100_000, "C", 10, f=101_000, index=100_000.0)], NOW)
        self.assertEqual(g["spot"], 100_000.0)
        self.assertEqual(gex_sets([row(100_000, "C", 10, f=101_000)], NOW)["spot"], 101_000.0)

    def test_with_gex_keeps_the_v26_shape_and_reports_other_exchanges(self):
        rows = [deribit(105_000, "C", 300), deribit(95_000, "P", 400)]
        v = with_gex(options_view(rows, NOW), rows, NOW, [row(100_000, "C", 20, ex="Bybit")], "okx: HTTP 403")
        self.assertIn("gex", v)
        self.assertEqual(v["gex"]["n"], 2)                                # gex = Deribit seul, toutes echeances (forme V26)
        self.assertEqual(v["gexSets"]["all"]["all"]["n"], 3)
        self.assertEqual(v["gexOthersError"], "okx: HTTP 403")
        bad = with_gex(options_view(rows, NOW), [], NOW, [row(100_000, "C", 20, ex="Bybit")])
        self.assertNotIn("gex", bad)                                      # sans Deribit : pas de gamma (Deribit reste la reference)
        self.assertIn("Deribit", bad["gexError"])


class FakeNet(DerivMixin):
    deribit, bybit, okx = "D", "B", "O"

    def __init__(self, okx_ok=True):
        self.okx_ok, self.urls = okx_ok, []

    def _get(self, url):
        self.urls.append(url)
        if url.startswith("D/"):
            return {"result": [deribit(105_000, "C", 300), deribit(95_000, "P", 400)]}
        if url.startswith("B/"):
            return {"result": {"list": [{"symbol": f"BTC-{tag(5)}-100000-C", "openInterest": "40", "markIv": "0.5", "underlyingPrice": "100000"}]}}
        if not self.okx_ok:
            raise DataError("HTTP 403 (O/api)")
        e = datetime.fromtimestamp(exp_ms(5) / 1000, timezone.utc)
        inst = f"BTC-USD-{e.year % 100:02d}{e.month:02d}{e.day:02d}-95000-P"
        if "opt-summary" in url:
            return {"data": [{"instId": inst, "markVol": "0.55", "fwdPx": "100000"}]}
        return {"data": [{"instId": inst, "oiCcy": "25"}]}


class NetworkTests(unittest.TestCase):
    def test_btc_options_add_bybit_and_okx(self):
        n = FakeNet()
        v = n.deribit_options("BTC", NOW)
        self.assertEqual([s["ex"] for s in v["gexSets"]["all"]["all"]["sources"]], ["Deribit", "Bybit", "OKX"])
        self.assertNotIn("gexOthersError", v)
        self.assertTrue(any("category=option&baseCoin=BTC" in u for u in n.urls))
        self.assertTrue(any("opt-summary?instFamily=BTC-USD" in u for u in n.urls))
        self.assertTrue(any("instType=OPTION&instFamily=BTC-USD" in u for u in n.urls))
        n2 = FakeNet(okx_ok=False)
        v2 = n2.deribit_options("BTC", NOW)
        self.assertIn("okx", v2["gexOthersError"])
        self.assertEqual([s["ex"] for s in v2["gexSets"]["all"]["all"]["sources"]], ["Deribit", "Bybit"])
        n3 = FakeNet()
        n3.deribit_options("ETH", NOW)
        self.assertTrue(all(u.startswith("D/") for u in n3.urls))         # ETH : Deribit seul, pas de requete en plus

    def test_simulated_market_has_three_exchanges(self):
        class P(SimDerivMixin):
            def now_ms(self):
                return NOW
        v = P().deribit_options("BTC", NOW)
        self.assertEqual(len(v["gexSets"]["all"]["all"]["sources"]), 3)
        self.assertEqual(len(P().deribit_options("ETH", NOW)["gexSets"]["all"]["all"]["sources"]), 1)


class RecorderTests(unittest.TestCase):
    def test_new_gamma_columns_are_recorded_for_later_measurement(self):
        from data.external import ExternalHub, SimProviders
        with tempfile.TemporaryDirectory(**TMP_KW) as d:
            hub = ExternalHub(SimProviders(lambda: NOW), lambda: NOW, d, ("BTCUSDT",), derivs=True)
            hub.sync_opendata = True
            hub.refresh(force=True)
            lines = (Path(d) / "history" / "derivs" / "BTCUSDT.csv").read_text(encoding="utf-8").strip().split("\n")
            head, vals = lines[0].split(","), lines[1].split(",")
            for k in ("gexAllTotal", "gexAllFlip", "gexAbs", "gexFrontCallWall", "gexFrontPutWall", "gexEmDayPct", "gexHedgeUp2", "gexHedgeDn2"):
                self.assertIn(k, head)
                self.assertNotEqual(vals[head.index(k)], "", k)


class BriefTests(unittest.TestCase):
    def snap(self, others=True):
        rows = [deribit(110_000, "C", 500), deribit(105_000, "C", 300), deribit(95_000, "P", 400), deribit(90_000, "P", 700), deribit(100_000, "C", 200),
                deribit(100_000, "P", 200), deribit(104_000, "C", 100, days=1), deribit(96_000, "P", 100, days=1)]
        o = [row(100_000, "C", 60, ex="Bybit")] if others else []
        return {"t": NOW, **with_gex(options_view(rows, NOW), rows, NOW, o)}

    def test_levels_scope_and_fallback(self):
        lv = [{"kind": "vwap", "name": "wVWAP", "price": 105_020.0}]
        b = gamma.brief(self.snap(), lv, 100_000.0, 600.0, NOW)
        kinds = [k["kind"] for k in b["levels"]]
        for kd in ("callwall", "putwall", "flip", "maxpain", "emup", "emdn"):
            self.assertIn(kd, kinds)
        self.assertEqual(kinds.count("strike") + kinds.count("callwall") + kinds.count("putwall") + kinds.count("absgamma"),
                         len({round(k["price"], 2) for k in b["levels"] if k["kind"] in ("strike", "callwall", "putwall", "absgamma")}))
        cw = next(k for k in b["levels"] if k["kind"] == "callwall")
        self.assertAlmostEqual(cw["distPct"], (cw["price"] / 100_000 - 1) * 100)
        self.assertEqual((b["scope"], b["src"]), ("all", "all"))
        self.assertEqual(len(b["sources"]), 2)
        self.assertTrue(b["zones"] and all(z["sign"] in (-1, 0, 1) for z in b["zones"]))
        self.assertEqual(b["zones"][0]["lo"], b["curve"][0][0])
        fr = gamma.brief(self.snap(), [], 100_000.0, 600.0, NOW, "front", "all")
        self.assertEqual(fr["scope"], "front")
        self.assertEqual(fr["frontExpiry"], exp_ms(1))
        self.assertEqual(fr["maxPain"]["expiry"], exp_ms(1))              # max pain de la prochaine echeance quand on la regarde
        only = gamma.brief(self.snap(others=False), [], 100_000.0, 600.0, NOW, "all", "all")
        self.assertEqual(only["src"], "deribit")                         # une seule bourse : on le dit
        self.assertEqual(gamma.brief(self.snap(), [], 100_000.0, 600.0, NOW, "n'importe", "quoi")["scope"], "all")
        old = {"t": NOW, "gex": self.snap()["gex"]}                       # ancien instantane (V26) : marche toujours
        self.assertEqual(gamma.brief(old, [], 100_000.0, 600.0, NOW)["src"], "deribit")

    def test_absolute_gamma_on_a_wall_is_said_on_the_wall(self):
        keys = gamma.key_levels({"callWall": 100.0, "putWall": 90.0, "absGamma": 100.0, "flip": 95.0, "top": [{"strike": 100.0, "net": 1.0}]})
        self.assertEqual([k["kind"] for k in keys], ["callwall", "flip", "putwall"])
        self.assertTrue(keys[0]["alsoAbs"])

    def test_lecture_note_is_plain_french(self):
        b = gamma.brief(self.snap(), [], 100_000.0, 600.0, NOW)
        c = lecture.gamma_chips({"gex": b})[0]
        for s in ("Couverture estimée si le prix monte de 2 %", "Mouvement attendu par les options sur 24 heures", "Strike au plus fort gamma",
                  "Calcul : toutes les échéances, Deribit", "hors score"):
            self.assertIn(s, c["note"])
        self.assertNotRegex(c["note"], r"\d\.\d")                         # virgule decimale


class PageTests(unittest.TestCase):
    def test_version_and_page(self):
        self.assertGreaterEqual(API_LEVEL, 38)                            # versions suivantes : le niveau monte
        self.assertEqual(VERSION, str(API_LEVEL))
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn(f"const NEED_API = {API_LEVEL};", app)
        self.assertIn("gexScope=${mo.gexScope || 'all'}&gexSrc=${mo.gexSrc || 'all'}", app)
        desk = (WEB / "desk.js").read_text(encoding="utf-8")
        for k in ("gexScope", "gexSrc", "gexLevels", "gexZones", "gexBars"):
            self.assertIn(f"sel('{k}'", desk)
            self.assertIn(f"'{k}'", desk.split("data-copt")[-1])            # accepte comme texte dans le gestionnaire de changement
        self.assertIn("/docs/guide_gamma.pdf", desk)
        panels = (WEB / "panels.js").read_text(encoding="utf-8")
        for s in ("static gexLines(g)", "static get GEX_COL()", "g.zones", "lgEl", "mo.gexBars === 'split'"):
            self.assertIn(s, panels)
        srv = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('q.get("gexScope")', srv)

    def test_guide_pdf_is_shipped(self):
        f = WEB / "docs" / "guide_gamma.pdf"
        self.assertTrue(f.exists())
        data = f.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 100_000)

    def test_state_route_passes_the_choice(self):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW as N
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=N), make_hub=lambda c, s: None)
            snap = BriefTests().snap()

            class Hub:
                def snapshot(self):
                    return {"derivs": {"options": {"BTC": snap}}}
            app.service.ext = Hub()
            b = app.service.gex_brief("BTCUSDT", [], 100_000.0, 500.0, "week", "deribit")
            self.assertEqual((b["scope"], b["src"]), ("week", "deribit"))
            self.assertIsNone(app.service.gex_brief("SOLUSDT", [], 190.0, 2.0, "week", "all"))


if __name__ == "__main__":
    unittest.main()
