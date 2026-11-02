"""Tests V0.6 : GEX (chaîne d'options), intérêt ouvert, bougies de CVD, classement des absorptions, données réelles trouvées seules,
changement de source sans redémarrage."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import config
from config import Config, load_config
from data.options import OptionsFeed, oi_summary, read_oi
from data.simulated import SimulatedSource
from engine import absorption, clock, cvd, gex, vwap
from engine.account import Account
from engine.bars import Bar
from service import Service
from tools.make_sample_options import make

NOW = clock.et_to_utc(2026, 10, 15, 11, 0)


class GexTests(unittest.TestCase):
    def test_parse_symbol(self):
        self.assertEqual(gex.parse_symbol("NDX261120C25000000"), ("NDX", "2026-11-20", "C", 25000.0))
        self.assertEqual(gex.parse_symbol("QQQ261120P00512500"), ("QQQ", "2026-11-20", "P", 512.5))
        self.assertEqual(gex.parse_symbol("NDXP261016C24900000")[0], "NDXP")
        self.assertIsNone(gex.parse_symbol("pas un symbole"))

    def test_bs_gamma_peaks_at_the_money(self):
        g_atm = gex.bs_gamma(100, 100, 0.1, 0.2)
        self.assertGreater(g_atm, gex.bs_gamma(100, 120, 0.1, 0.2))
        self.assertGreater(g_atm, gex.bs_gamma(100, 80, 0.1, 0.2))
        self.assertEqual(gex.bs_gamma(100, 100, 0, 0.2), 0.0)

    def test_walls_and_zero_gamma_on_a_synthetic_chain(self):
        js = make(24950.0, date(2026, 10, 15))
        ch = gex.chain_from_json(js, NOW)
        r = gex.compute(ch)
        self.assertEqual(r["callWall"], 25500.0)                         # mur de calls placé par le générateur (×6 d'intérêt ouvert)
        self.assertGreaterEqual(r["putWall"], 24000.0)
        self.assertIsNotNone(r["zeroGamma"])
        # au zéro gamma, le profil du gamma total change de signe
        below = [g for s, g in r["curve"] if s < r["zeroGamma"]]
        above = [g for s, g in r["curve"] if s > r["zeroGamma"]]
        self.assertTrue(below and above)
        self.assertNotEqual(below[-1] > 0, above[0] > 0)

    def test_signs_calls_positive_puts_negative(self):
        js = {"data": {"current_price": 100.0, "options": [
            {"option": "XYZ261120C00100000", "open_interest": 1000, "iv": 0.2, "gamma": 0.05},
            {"option": "XYZ261120P00090000", "open_interest": 1000, "iv": 0.25, "gamma": 0.04}]}}
        r = gex.compute(gex.chain_from_json(js, NOW), band=0.2)
        by = {a["strike"]: a for a in r["strikes"]}
        self.assertGreater(by[100.0]["net"], 0)
        self.assertLess(by[90.0]["net"], 0)
        self.assertEqual(r["callWall"], 100.0)
        self.assertEqual(r["putWall"], 90.0)

    def test_no_zero_gamma_without_a_real_sign_change(self):
        no_iv = {"data": {"current_price": 100.0, "options": [{"option": "XYZ261120C00100000", "open_interest": 1000, "iv": 0, "gamma": 0.05}]}}
        self.assertIsNone(gex.compute(gex.chain_from_json(no_iv, NOW))["zeroGamma"])
        calls = {"data": {"current_price": 100.0, "options": [{"option": f"XYZ261016C{k * 1000:08d}", "open_interest": 500, "iv": 0.2}
                                                            for k in range(95, 106)]}}
        r = gex.compute(gex.chain_from_json(calls, NOW))
        self.assertIsNone(r["zeroGamma"])                                  # que des calls : gamma total ≥ 0 partout
        self.assertFalse([x for x in gex.to_nq(r, 1.0)["levels"] if x["kind"] == "gzero"])

    def test_expired_options_are_dropped(self):
        evening = clock.et_to_utc(2026, 10, 15, 19, 0)                    # 3 h après l'échéance du jour
        ch = gex.chain_from_json(make(24950.0, date(2026, 10, 15)), evening)
        self.assertFalse([o for o in ch["options"] if o["exp"] == "2026-10-15"])

    def test_unreadable_chain_raises(self):
        with self.assertRaises(ValueError):
            gex.chain_from_json({"data": {"current_price": 100, "options": [{"option": "??"}]}}, NOW)
        with self.assertRaises(ValueError):
            gex.chain_from_json({"data": {"options": [{"option": "XYZ261120C00100000", "open_interest": 1}]}}, NOW)

    def test_to_nq_scales_levels(self):
        r = gex.compute(gex.chain_from_json(make(24950.0, date(2026, 10, 15)), NOW))
        conv = gex.to_nq(r, 1.01)
        cw = next(x for x in conv["levels"] if x["kind"] == "gcall")
        self.assertAlmostEqual(cw["price"], round(r["callWall"] * 1.01 * 4) / 4)


class OptionsFeedTests(unittest.TestCase):
    def test_download_cache_and_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            payload = json.dumps(make(24950.0, date(2026, 10, 15))).encode()
            calls = []
            feed = OptionsFeed("NDX", d, fetch_fn=lambda url: calls.append(url) or payload)
            js, src = feed.load()
            self.assertIn("_NDX", calls[0])
            self.assertTrue(src.startswith("CBOE"))
            self.assertTrue((Path(d) / "options-NDX.json").exists())
            js2, src2 = feed.load()                                         # pas encore l'heure : copie locale, pas de nouveau téléchargement
            self.assertEqual(len(calls), 1)
            self.assertEqual(src2, "copie locale")

            def boom(url):
                raise OSError("réseau coupé")
            feed2 = OptionsFeed("NDX", d, fetch_fn=boom)
            js3, src3 = feed2.load(force=True)
            self.assertEqual(src3, "copie locale")
            self.assertIn("réseau coupé", feed2.error)

    def test_bad_download_keeps_the_last_good_copy(self):
        with tempfile.TemporaryDirectory() as d:
            good = json.dumps(make(24950.0, date(2026, 10, 15))).encode()
            OptionsFeed("NDX", d, fetch_fn=lambda u: good).load(force=True)
            feed = OptionsFeed("NDX", d, fetch_fn=lambda u: b'{"error": "rate limited"}')
            js, src = feed.load(force=True)
            self.assertEqual(src, "copie locale")
            self.assertTrue(js["data"]["options"])
            self.assertIn("sans chaîne", feed.error)

    def test_file_error_clears_once_readable(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "o.json"
            p.write_text("{incomplet", encoding="utf-8")
            feed = OptionsFeed("NDX", d, file_path=str(p))
            self.assertEqual(feed.load(), (None, None))
            self.assertTrue(feed.error)
            p.write_text(json.dumps(make(24950.0, date(2026, 10, 15))), encoding="utf-8")
            js, _ = feed.load()
            self.assertIsNotNone(js)
            self.assertIsNone(feed.error)

    def test_explicit_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "o.json"
            p.write_text(json.dumps(make(24950.0, date(2026, 10, 15))), encoding="utf-8")
            js, src = OptionsFeed("NDX", d, file_path=str(p), fetch_fn=lambda u: (_ for _ in ()).throw(AssertionError("pas de réseau"))).load()
            self.assertIn("o.json", src)


class OpenInterestTests(unittest.TestCase):
    def test_read_and_summarize(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nq-oi.csv"
            t1, t2 = clock.et_to_utc(2026, 10, 14, 8, 0), clock.et_to_utc(2026, 10, 15, 8, 0)
            p.write_text(f"time,oi\n{t1},250000\n{t2},251200\nmauvaise,ligne\n{t2 + 5}", encoding="utf-8")
            rows = read_oi(p)
            self.assertEqual(rows, [(t1, 250000.0), (t2, 251200.0)])
            s = oi_summary(rows)
            self.assertEqual(s["oi"], 251200.0)
            self.assertEqual(s["change"], 1200.0)
            self.assertEqual(len(s["history"]), 2)
        self.assertEqual(read_oi(None), [])
        self.assertIsNone(oi_summary([]))


class CvdOhlcTests(unittest.TestCase):
    def test_candles_open_high_low_close(self):
        a = clock.window("2026-10-13", "globex")[0]
        bars = []
        for i, (bv, sv) in enumerate([(10, 2), (1, 9), (6, 0)]):
            b = Bar(a + i * 60_000, 100.0)
            b.bv, b.sv, b.v = bv, sv, bv + sv
            bars.append(b)
        cum = cvd.cumulative(bars, vwap.key_globex)                        # 8, 0, 6
        chart = [Bar(a, 100.0)]
        o = cvd.ohlc_sample(bars, cum, chart, 5 * 60_000)[0]
        self.assertEqual(o, [0.0, 8.0, 0.0, 6.0])


class RankTests(unittest.TestCase):
    def test_on_a_key_level_and_repeated_rank_higher(self):
        base = {"side": "bull", "price": 100.0, "strength": 0.5, "count": 1, "tests": 0, "kind": "niveau"}
        lv = [{"name": "VAL veille", "price": 100.25, "kind": "pval", "group": "veille"}, {"name": "Rond 200", "price": 200.0, "kind": "r100"}]
        on, off, rep = dict(base), dict(base, price=150.0), dict(base, price=150.0, count=3)
        absorption.rank([on, off, rep], lv, 0.25)
        self.assertEqual(on["level"], "VAL veille")
        self.assertIsNone(off["level"])
        self.assertGreater(on["score"], off["score"])
        self.assertGreater(rep["score"], off["score"])
        self.assertTrue(on["top"])
        self.assertFalse(off["top"])


class RealDataTests(unittest.TestCase):
    def test_logger_file_is_used_when_no_source_is_chosen(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "Documents" / "NQ-Terminal" / "nq-ticks.csv"
            f.parent.mkdir(parents=True)
            f.write_text("time,price,size,side,bid,ask\n" + "1791900000000,25000.25,1,B,25000,25000.25\n" * 3, encoding="utf-8")
            env = Path(d) / ".env"
            with mock.patch.object(config.Path, "home", return_value=Path(d)), mock.patch.dict("os.environ", {}, clear=True):
                c = load_config(env)
                self.assertEqual((c.source, c.csv_path, c.auto_source), ("csv", str(f), True))
                self.assertEqual(c.oi_path, str(f.with_name("nq-oi.csv")))
                env.write_text("NQ_SOURCE=simulated\n", encoding="utf-8")      # un choix explicite l'emporte
                c2 = load_config(env)
                self.assertEqual((c2.source, c2.oi_path), ("simulated", ""))  # pas d'intérêt ouvert réel sur des prix simulés
                env.write_text("NQ_CSV_PATH=/ailleurs/mes_ticks.csv\n", encoding="utf-8")   # un chemin seul : ce fichier, sans détection
                c3 = load_config(env)
                self.assertEqual((c3.source, c3.csv_path, c3.auto_source), ("csv", "/ailleurs/mes_ticks.csv", False))

    def test_switch_source_without_restart(self):
        with tempfile.TemporaryDirectory() as d:
            csvp = Path(d) / "ticks.csv"
            t0 = clock.et_to_utc(2026, 10, 15, 10, 0)
            csvp.write_text("time,price,size,side\n" + "".join(f"{t0 + i * 1000},{25000 + (i % 8) * 0.25},1,{'B' if i % 2 else 'S'}\n" for i in range(400)),
                            encoding="utf-8")
            env = Path(d) / ".env"
            env.write_bytes("# commentaire gardé, écrit au Bloc-notes\nNQ_PORT=8766\n".encode("cp1252"))
            cfg = Config(data_dir=d, sim_days=2, gex="OFF")
            svc = Service(cfg, source=SimulatedSource(days=2, now_fn=lambda: NOW), account=Account(f"{d}/c.json", now_ms=lambda: NOW), env_path=env)
            svc.load_sync()
            with self.assertRaises(ValueError):
                svc.use_source(str(Path(d) / "absent.csv"))
            r = svc.use_source(str(csvp))
            self.assertTrue(r["ok"])
            svc.pump_once()
            self.assertFalse(svc.source.info()["simulated"])
            self.assertEqual(svc.market.count, 400)
            text = env.read_text(encoding="utf-8")
            self.assertIn("# commentaire gardé, écrit au Bloc-notes", text)
            self.assertIn("NQ_PORT=8766", text)
            self.assertIn("NQ_SOURCE=csv", text)
            self.assertIn(f"NQ_CSV_PATH={csvp}", text)
            svc.use_source(None)
            self.assertIn("NQ_SOURCE=simulated", env.read_text(encoding="utf-8"))
            self.assertNotIn("NQ_CSV_PATH", env.read_text(encoding="utf-8"))

    def test_no_gex_for_es(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(data_dir=d, sim_days=2, instrument="ES", gex="NDX")
            now = clock.et_to_utc(2026, 10, 15, 12, 0)
            svc = Service(cfg, source=SimulatedSource(days=2, now_fn=lambda: now), account=Account(f"{d}/c.json", now_ms=lambda: now))
            self.assertIsNone(svc.options)
            self.assertEqual(svc.gex_view()["state"], "off")

    def test_gex_through_the_service(self):
        with tempfile.TemporaryDirectory() as d:
            opt = Path(d) / "o.json"
            opt.write_text(json.dumps(make(24950.0, date(2026, 10, 15))), encoding="utf-8")
            cfg = Config(data_dir=d, sim_days=2, gex="NDX", gex_file=str(opt))
            now = clock.et_to_utc(2026, 10, 15, 12, 0)
            svc = Service(cfg, source=SimulatedSource(days=2, now_fn=lambda: now), account=Account(f"{d}/c.json", now_ms=lambda: now))
            svc.load_sync()
            svc.gex_refresh()
            g = svc.gex_view()
            self.assertEqual(g["state"], "ready")
            self.assertTrue({"gcall", "gput", "gzero"} <= {x["kind"] for x in g["levels"]})
            lv = svc.levels()
            self.assertTrue([x for x in lv["levels"] if x["group"] == "gex"])
            b = svc.bars("1m", 100)
            self.assertEqual(len(b["cvdOhlcGx"]), len(b["bars"]))
            for m in b["absorptions"]:
                self.assertIn("score", m)


if __name__ == "__main__":
    unittest.main()
