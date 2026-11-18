"""V49 : le terminal ne reste plus bloqué sur « chargement… ».
- au redémarrage, l'adresse est libérée avant l'arrêt des tâches de fond, et cet arrêt est limité dans le temps ;
- une requête lente est signalée dans la fenêtre du terminal ;
- la page réessaie toute seule et dit ce qui se passe."""
from __future__ import annotations
import os
import threading
import time
import unittest

import run
import server
from prefsync import PrefSync

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StopWithinTest(unittest.TestCase):
    def test_a_stuck_shutdown_does_not_hold_the_restart(self):
        ev = threading.Event()
        t = time.time()
        self.assertFalse(run.stop_within(lambda: ev.wait(30), 0.3))
        self.assertLess(time.time() - t, 2.0)
        ev.set()
        self.assertTrue(run.stop_within(lambda: None, 1.0))

    def test_socket_is_closed_before_the_shutdown(self):
        src = open(os.path.join(ROOT, "run.py"), encoding="utf-8").read()
        i, j = src.index("httpd.server_close()"), src.index("stop_within(app.shutdown, SHUTDOWN_S)")
        self.assertLess(i, j)
        self.assertIn("os._exit(code or 0)", src)


class SlowRequestsTest(unittest.TestCase):
    def test_slow_request_is_reported_once(self):
        clock = [100.0]
        said = []
        sr = server.SlowRequests(limit=15, now=lambda: clock[0], out=lambda *a, **k: said.append(a[0]))
        with sr.track("GET /api/state?symbol=SOLUSDT"):
            with sr.track("GET /api/config"):
                pass
            clock[0] += 16
            self.assertEqual(sr.check(), ["GET /api/state?symbol=SOLUSDT"])
            self.assertEqual(sr.check(), [])                                   # une seule fois
        self.assertEqual(len(sr.live), 0)
        self.assertIn("terminée après 16 s", said[-1])


class PrefsCandidatesTest(unittest.TestCase):
    def test_cloud_folders_are_scanned_at_most_every_ten_minutes(self):
        import tempfile
        from unittest import mock
        d = tempfile.mkdtemp()
        ps = PrefSync(d, os.path.join(d, ".env"))
        with mock.patch("prefsync.cloud_dirs", return_value=[]) as cd:
            ps.status(); ps.status(); ps.status()
            self.assertEqual(cd.call_count, 1)


class PageTest(unittest.TestCase):
    def test_boot_retries_and_explains(self):
        js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
        self.assertIn("async function bootConfig()", js)
        self.assertIn("api('/api/config', undefined, 8000)", js)
        self.assertNotIn("'terminal injoignable'; return;", js)            # avant : message caché et page arrêtée pour de bon
        self.assertIn("new Promise(r => setTimeout(r, 6000))", js)          # la synchronisation des réglages ne bloque plus le démarrage


if __name__ == "__main__":
    unittest.main()
