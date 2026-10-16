"""V26 : gamma des options BTC (calcul sur le carnet Deribit deja lu), niveaux et confluences avec les VWAP / VWAP ancres, Lecture."""
import math
import unittest
from datetime import datetime, timezone

from data.derivs import bs_gamma, gex_view, with_gex, options_view, MONTHS, DAY
from engine import gamma, lecture

NOW = 1_759_104_000_000                     # lundi 29/09/2025 00:00 UTC


def name(strike, kind, days):
    e = datetime.fromtimestamp((NOW + days * DAY) / 1000, timezone.utc)
    return f"BTC-{e.day}{list(MONTHS)[e.month - 1]}{e.year % 100}-{int(strike)}-{kind}"


def opt(strike, kind, oi, days=5, iv=50.0, f=100_000.0):
    return {"instrument_name": name(strike, kind, days), "open_interest": oi, "mark_iv": iv, "underlying_price": f}


class BlackGammaTests(unittest.TestCase):
    def test_known_value(self):
        # F = K = 100, vol 50 %, 1 an : d1 = 0,25 ; gamma = n(0,25) / (100 x 0,5)
        self.assertAlmostEqual(bs_gamma(100.0, 100.0, 0.5, 1.0), math.exp(-0.5 * 0.0625) / math.sqrt(2 * math.pi) / 50.0, places=10)
        self.assertEqual(bs_gamma(100.0, 100.0, 0.0, 1.0), 0.0)
        self.assertGreater(bs_gamma(100.0, 100.0, 0.5, 0.01), bs_gamma(100.0, 100.0, 0.5, 1.0))       # plus pres de l'echeance, plus de gamma


class GexTests(unittest.TestCase):
    def test_signs_walls_and_flip(self):
        rows = [opt(110_000, "C", 500), opt(105_000, "C", 300), opt(95_000, "P", 400), opt(90_000, "P", 700), opt(100_000, "C", 50)]
        g = gex_view(rows, NOW)
        self.assertEqual(g["callWall"], 105_000.0)                       # plus fort gamma des calls AU-DESSUS du prix
        self.assertEqual(g["putWall"], 95_000.0)                         # plus fort gamma des puts EN DESSOUS
        self.assertGreater(g["calls"], 0)
        self.assertLess(g["puts"], 0)
        self.assertIsNotNone(g["flip"])
        tot_at = dict((round(p), v) for p, v in g["curve"])
        lo, hi = min(tot_at), max(tot_at)
        self.assertLess(tot_at[lo], 0)                                   # bas de la fourchette : les puts dominent
        self.assertGreater(tot_at[hi], 0)                                # haut : les calls dominent
        self.assertTrue(90_000 < g["flip"] < 110_000)
        self.assertEqual(g["nearShare"], 1.0)                            # tout expire dans les 7 jours (5 jours et 8 heures)
        # 1 BTC de call au strike, prix 100 000, vol 50 %, echeance a 08:00 UTC dans 5 jours : gamma x 1 x prix^2 x 1 %
        one = gex_view([opt(100_000, "C", 1)], NOW)
        t = (5 * DAY + 8 * 3_600_000) / (365.0 * DAY)
        self.assertAlmostEqual(one["total"], bs_gamma(1e5, 1e5, 0.5, t) * 1e10 * 0.01, places=4)

    def test_only_calls_have_no_flip_and_missing_iv_is_an_error(self):
        self.assertIsNone(gex_view([opt(100_000, "C", 10)], NOW)["flip"])
        bad = [{**opt(100_000, "C", 10), "mark_iv": None}]
        view = with_gex(options_view(bad, NOW), bad, NOW)
        self.assertNotIn("gex", view)
        self.assertIn("gamma : aucune option exploitable", view["gexError"])
        self.assertIn("expiries", view)                                  # le resume des options reste


class BriefTests(unittest.TestCase):
    LEVELS = [{"kind": "vwap", "name": "mVWAP", "price": 104_950.0}, {"kind": "avwap", "name": "AVWAP bas 1 an", "price": 95_100.0},
              {"kind": "vp", "name": "POC", "price": 95_000.0}, {"kind": "vwap", "name": "dVWAP", "price": 99_000.0}]

    def opt_snapshot(self):
        rows = [opt(110_000, "C", 500), opt(105_000, "C", 300), opt(95_000, "P", 400), opt(90_000, "P", 700)]
        return {"t": NOW, **with_gex(options_view(rows, NOW), rows, NOW)}

    def test_confluences_with_vwap_and_anchored_vwap(self):
        b = gamma.brief(self.opt_snapshot(), self.LEVELS, 100_000.0, 600.0, NOW + 60_000)
        by = {k["kind"]: k for k in b["levels"]}
        self.assertEqual([v["name"] for v in by["callwall"]["vwap"]], ["VWAP du mois"])         # 104 950 a 50 $ du mur de calls
        self.assertEqual([v["name"] for v in by["putwall"]["vwap"]], ["VWAP ancré bas 1 an"])  # le POC n'est pas un VWAP
        self.assertFalse(b["stale"])
        self.assertTrue(gamma.brief(self.opt_snapshot(), [], 100_000.0, 600.0, NOW + 40 * 60_000)["stale"])
        self.assertEqual(gamma.brief({"gexError": "x"}, [], 1.0, 1.0, NOW), {"error": "x"})
        self.assertIsNone(gamma.brief(None, [], 1.0, 1.0, NOW))

    def test_lecture_chip(self):
        b = gamma.brief(self.opt_snapshot(), self.LEVELS, 100_000.0, 600.0, NOW)
        ch = lecture.gamma_chips({"gex": b})
        self.assertEqual(len(ch), 1)
        c = ch[0]
        self.assertEqual((c["key"], c["evidence"]), ("gamma", "contexte"))
        self.assertIn("mur de calls 105 000 ≈ VWAP du mois", c["note"])
        self.assertIn("hors score", c["note"])
        self.assertIn("bascule", c["value"])
        self.assertEqual(lecture.gamma_chips({}), [])
        self.assertEqual(lecture.gamma_chips({"gex": {"error": "Deribit injoignable"}})[0]["value"], "indisponible")


class ServiceTests(unittest.TestCase):
    def test_btc_only(self):
        import tempfile
        from pathlib import Path
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW as N
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=N), make_hub=lambda c, s: None)

            class Hub:
                def snapshot(self):
                    rows = [opt(110_000, "C", 500), opt(95_000, "P", 400)]
                    return {"derivs": {"options": {"BTC": {"t": N, **with_gex(options_view(rows, NOW), rows, NOW)}}}}
            app.service.ext = Hub()
            self.assertIsNone(app.service.gex_brief("SOLUSDT", [], 190.0, 2.0))
            b = app.service.gex_brief("BTCUSDT", [], 100_000.0, 500.0)
            self.assertEqual(b["callWall"], 110_000.0)


if __name__ == "__main__":
    unittest.main()
