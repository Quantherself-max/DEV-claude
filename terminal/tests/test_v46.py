"""V46 : chargements plus rapides. Le réseau hors du verrou du service, les requêtes Binance à leur juste taille, et la page qui ne
redemande ni ne redessine ce qu'elle a déjà."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server
from config import Config
from data.binance import BinanceSource, page_limit
from data.simulated import SimulatedSource
from data.store import DataStore
from service import Service

NOW = 1_790_000_000_000


class PageLimitTest(unittest.TestCase):
    def test_only_what_is_needed(self):
        h = 3_600_000
        self.assertEqual(page_limit(NOW - h, NOW, h, 1500), 99)                 # deux bougies à lire : poids 1 chez Binance (10 pour 1 500)
        self.assertEqual(page_limit(NOW - 97 * h, NOW, h, 1500), 99)
        self.assertEqual(page_limit(NOW - 98 * h, NOW, h, 1500), 499)
        self.assertEqual(page_limit(NOW - 600 * h, NOW, h, 1500), 1000)
        self.assertEqual(page_limit(NOW - 5000 * h, NOW, h, 1500), 1500)
        self.assertEqual(page_limit(NOW - 5000 * h, NOW, h, 1000), 1000)        # comptant : jamais plus de 1 000

    def test_candles_ask_for_a_small_page_and_stop(self):
        calls = []

        class Src(BinanceSource):
            def _get(self, path, params=None, **kw):
                calls.append(dict(params))
                t, step, out = params["startTime"], 3_600_000, []
                while t <= params["endTime"] and len(out) < params["limit"]:
                    out.append([t, "100", "101", "99", "100", "5", t + step - 1, "500", 10, "2", "200", "0"])
                    t += step
                return out
        s = Src(pause=0)
        ks = s.candles("BTCUSDT", "1h", NOW - 2 * 3_600_000, NOW)
        self.assertEqual((len(ks), [c["limit"] for c in calls]), (3, [99]))
        calls.clear()
        ks = s.candles("BTCUSDT", "1h", NOW - 2000 * 3_600_000, NOW)             # un long historique reste paginé par 1 500
        self.assertEqual((len(ks), [c["limit"] for c in calls]), (2001, [1500, 1000]))


class RateLimitTest(unittest.TestCase):
    def test_a_429_stops_all_calls_for_the_time_asked(self):
        import io
        import urllib.error
        import urllib.request
        from unittest import mock
        from data.base import DataError
        calls = []

        def fake(req, timeout=None):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "90"}, io.BytesIO(b'{"code":-1003}'))
        s = BinanceSource(pause=0)
        with mock.patch.object(urllib.request, "urlopen", fake):
            with self.assertRaises(DataError) as e:
                s._get("/fapi/v1/klines", {"symbol": "BTCUSDT"})
            self.assertIn("pause de 90 s", str(e.exception))
            self.assertEqual(len(calls), 1)                                      # aucun nouvel essai immédiat (il aggravait le blocage)
            with self.assertRaises(DataError) as e:
                s._get("/fapi/v1/openInterest", {"symbol": "BTCUSDT"})
            self.assertIn("reprise dans", str(e.exception))
            self.assertEqual(len(calls), 1)                                      # plus aucun appel à ce serveur pendant la pause
            with self.assertRaises(DataError):
                s._get("/api/v3/ticker/price", {"symbol": "BTCUSDT"}, host=s.spot_base)
            self.assertEqual(len(calls), 2)                                      # l'autre serveur (comptant) n'est pas concerné
        s.cool_until.clear()


class LockTest(unittest.TestCase):
    def test_network_is_done_without_the_service_lock(self):
        """Le cœur de la V46 : pendant les requêtes vers Binance, le verrou du service est LIBRE (les graphiques peuvent se charger) ;
        il n'est pris que pour ranger les données en mémoire."""
        seen = {"net": [], "apply": []}

        class Src(SimulatedSource):
            lock = None

            def candles(self, *a, **k):
                seen["net"].append(self.lock.locked())
                return super().candles(*a, **k)

            def premium_index(self, *a, **k):
                seen["net"].append(self.lock.locked())
                return super().premium_index(*a, **k)

        src = Src(now_ms=NOW)
        svc = Service(src, Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp()))
        src.lock = svc.lock
        m = svc.markets["BTCUSDT"]
        real_apply = m.store.apply
        m.store.apply = lambda d: (seen["apply"].append(svc.lock.locked()), real_apply(d))[1]
        svc.refresh_all()
        self.assertEqual(svc.errors, {})
        self.assertTrue(seen["net"] and not any(seen["net"]))                    # jamais sous le verrou
        self.assertEqual(seen["apply"], [True])                                  # la mise en mémoire, elle, est protégée
        self.assertTrue(m.ready)

    def test_fetch_changes_nothing_until_apply(self):
        st = DataStore(SimulatedSource(now_ms=NOW), "BTCUSDT", NOW - 400 * 86_400_000, history_years=1)
        d = st.fetch()
        self.assertEqual((st.h1, st.m5, st.m1, st.oi, st.last_refresh), ([], [], [], {}, 0))
        self.assertGreater(len(d["h1"]), 1000)
        st.apply(d)
        self.assertEqual((len(st.h1), len(st.m5), st.last_refresh), (len(d["h1"]), len(d["m5"]), d["now"]))
        n = len(st.h1)
        st.refresh()                                                             # ancien point d'entrée : toujours valable
        self.assertEqual(len(st.h1), n)

    def test_a_chart_request_is_served_while_binance_is_slow(self):
        gate, started = threading.Event(), threading.Event()

        class Slow(SimulatedSource):
            slow = False

            def candles(self, *a, **k):
                if self.slow:
                    started.set()
                    gate.wait(20)                                                # Binance ne répond pas
                return super().candles(*a, **k)

        src = Slow(now_ms=NOW)
        svc = Service(src, Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp()))
        svc.refresh_all()
        src.slow = True
        t = threading.Thread(target=svc.refresh_all, daemon=True)
        t.start()
        self.assertTrue(started.wait(10))
        got = {}
        r = threading.Thread(target=lambda: got.update(st=svc.get_state("BTCUSDT", "1h")), daemon=True)
        r.start()
        r.join(15)
        self.assertTrue(got.get("st", {}).get("ready"), "le graphique attend encore la fin des requêtes réseau")
        gate.set()
        t.join(30)


class StatePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        cls.app = server.App(cls.cfg, make_source=lambda c: SimulatedSource(now_ms=NOW))
        cls.app.service.refresh_all()

    def test_same_tail_and_cache(self):
        app = self.app
        full = app.state_page("BTCUSDT", "1h")
        self.assertTrue(full["ready"] and full["v"] and len(full["candles"]) > 1000 and "tail" not in full)
        self.assertIs(app.state_page("BTCUSDT", "1h"), full)                     # deuxième demande : pas de recalcul
        same = app.state_page("BTCUSDT", "1h", have=full["v"])
        self.assertEqual((same["same"], same["v"]), (True, full["v"]))
        self.assertLess(len(json.dumps(same)), 300)                              # quelques octets au lieu de 300 Ko
        app.service.refresh_all()                                                # du neuf : seulement les dernières bougies
        tail = app.state_page("BTCUSDT", "1h", have=full["v"])
        self.assertEqual((tail["tail"], len(tail["candles"]), tail["candles"][-1][0]), (True, app.STATE_TAIL, full["candles"][-1][0]))
        self.assertNotEqual(tail["v"], full["v"])
        self.assertGreater(len(tail["levels"]), 10)                              # le reste de l'état est complet
        self.assertLess(len(json.dumps(tail)), 0.75 * len(json.dumps(full)))
        other = app.state_page("BTCUSDT", "4h", have="")                         # autre unité de temps : état complet
        self.assertNotIn("tail", other)

    def test_a_setting_change_invalidates_the_kept_state(self):
        app = self.app
        full = app.state_page("BTCUSDT", "1h")
        s = app.series_page("BTCUSDT", "1h")
        app.forget_states()                                                      # appelé par chaque enregistrement de réglage
        again = app.state_page("BTCUSDT", "1h", have=full["v"])
        self.assertNotIn("same", again)                                          # la page n'a plus la bonne version : elle reçoit l'état
        self.assertNotEqual(again["v"], full["v"])
        self.assertIsNot(app.state_page("BTCUSDT", "1h"), full)
        self.assertNotIn("same", app.series_page("BTCUSDT", "1h", have=s["v"]))
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('if path != "/api/prefs":', src)

    def test_series_is_slim_and_skipped_when_unchanged(self):
        app = self.app
        s = app.series_page("BTCUSDT", "1h")
        self.assertTrue(s["ready"] and s["v"])
        raw = app.service.get_series("BTCUSDT", "1h")
        self.assertLess(len(json.dumps(s)), 0.75 * len(json.dumps(raw)))         # 8 chiffres significatifs : bien plus léger
        a, b = [x for x in s["vwap"]["D"] if x is not None][-1], [x for x in raw["vwap"]["D"] if x is not None][-1]
        self.assertAlmostEqual(a / b, 1.0, places=6)
        self.assertEqual(app.series_page("BTCUSDT", "1h", have=s["v"]), {"same": True, "ready": True, "v": s["v"]})
        self.assertEqual(server._slim({"a": [1.23456789012, None, "x", 3]}), {"a": [1.2345679, None, "x", 3]})

    def test_page_code(self):
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        for needle in ("function mergeTail(prev, tail)", "if (d.same) {", "if (d.tail) {", "'&v=' + have.v", "st.seriesKey = sk", f"const NEED_API = {server.API_LEVEL};"):
            self.assertIn(needle, app)
        self.assertEqual(subprocess.run(["node", "--check", str(ROOT / "web" / "app.js")], capture_output=True).returncode, 0)
        js = """
        const src = require('fs').readFileSync(process.argv[1], 'utf8');
        const m = src.match(/function mergeTail\\(prev, tail\\) \\{[\\s\\S]*?\\n\\}/)[0];
        const mergeTail = eval('(' + m + ')');
        const prev = [[1, 'a'], [2, 'b'], [3, 'c']];
        const out = [mergeTail(prev, [[3, 'C'], [4, 'd']]), mergeTail(prev, [[5, 'e']]), mergeTail(prev, [[2, 'B'], [3, 'C']]), mergeTail([], [[1, 'a']])];
        console.log(JSON.stringify(out));
        """
        r = subprocess.run(["node", "-e", js, str(ROOT / "web" / "app.js")], capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), [[[1, "a"], [2, "b"], [3, "C"], [4, "d"]], None, [[1, "a"], [2, "B"], [3, "C"]], None], r.stderr)

    def test_defaults_carry_less_history(self):
        from config import load_config, migrate_env
        c = Config()
        self.assertEqual((c.heatmap_days, c.sizeflow_history_days), (90, 90))
        with tempfile.TemporaryDirectory() as tmp:                              # un ancien .env à 180 jours passe à 90, une seule fois
            env = Path(tmp) / ".env"
            env.write_text("TERMINAL_HEATMAP_DAYS=180\nTERMINAL_SIZEFLOW_HISTORY_DAYS=180\nTERMINAL_FOOTPRINT_DAYS=62\n", encoding="utf-8")
            self.assertTrue(migrate_env(env, tmp))
            c = load_config(env)
            self.assertEqual((c.heatmap_days, c.sizeflow_history_days, c.footprint_days), (90, 90, 62))
            env.write_text("TERMINAL_HEATMAP_DAYS=180\n", encoding="utf-8")       # remis à 180 par choix : on n'y touche plus
            self.assertFalse(migrate_env(env, tmp))
            self.assertEqual(load_config(env).heatmap_days, 180)


if __name__ == "__main__":
    unittest.main()
