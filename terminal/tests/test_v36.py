"""V36 : unités de temps 1 minute, semaine et mois ; mêmes réglages sur tous tes ordinateurs (prefsync.py)."""
from __future__ import annotations
import json
import re
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import prefsync
from config import Config
from engine.atr import Candle, bar_start, resample_cal
from server import API_LEVEL, VERSION, App, serve
from service import ALERT_TFS, TFS

H = 3_600_000
DAY = 24 * H
WEB = Path(__file__).resolve().parent.parent / "web"
ms = lambda *a: int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


class CalendarTests(unittest.TestCase):
    def test_bar_start(self):
        self.assertEqual(bar_start(ms(2026, 10, 22, 15, 7), "1w"), ms(2026, 10, 19))          # jeudi -> lundi 00 h UTC
        self.assertEqual(bar_start(ms(2026, 10, 19), "1w"), ms(2026, 10, 19))
        self.assertEqual(bar_start(ms(2026, 10, 18, 23, 59), "1w"), ms(2026, 10, 12))
        self.assertEqual(bar_start(ms(2026, 2, 28, 12), "1M"), ms(2026, 2, 1))
        self.assertEqual(bar_start(ms(2026, 10, 22, 15, 7, 30), "1m"), ms(2026, 10, 22, 15, 7))

    def test_weeks_and_months(self):
        t0 = ms(2026, 1, 26)                                                    # lundi 26 janvier : 40 jours de bougies 1 h
        cs = [Candle(t0 + i * H, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1.0, 0.6, 100.0) for i in range(40 * 24)]
        w = resample_cal(cs, "1w")
        self.assertEqual([c.t for c in w[:3]], [ms(2026, 1, 26), ms(2026, 2, 2), ms(2026, 2, 9)])
        self.assertEqual(w[0].v, 7 * 24)
        self.assertEqual((w[0].o, w[0].c, w[0].l), (cs[0].o, cs[7 * 24 - 1].c, cs[0].l))
        m = resample_cal(cs, "1M")
        self.assertEqual([c.t for c in m], [ms(2026, 1, 1), ms(2026, 2, 1), ms(2026, 3, 1)])
        self.assertEqual(m[0].v, 6 * 24)                                         # 26 au 31 janvier
        self.assertEqual(m[1].v, 28 * 24)                                        # février 2026 : 28 jours
        self.assertAlmostEqual(sum(c.v for c in m), len(cs))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cloud = self.root / "cloud"
        self.cloud.mkdir()

    def machine(self, name, env_lines=""):
        d = self.root / name
        (d / "data").mkdir(parents=True)
        (d / "data" / "device.txt").write_text(name, encoding="utf-8")
        env = d / ".env"
        env.write_text(env_lines, encoding="utf-8")
        return prefsync.PrefSync(d / "data", env, str(self.cloud))

    def test_newest_wins_and_reaches_the_other_machine(self):
        pc, mac = self.machine("PC"), self.machine("Mac")
        pc.put("ui", {"liqPrefs": "{\"a\":1}"}, 1000)
        self.assertEqual(mac.newest("ui")["data"], {"liqPrefs": "{\"a\":1}"})       # par le dossier synchronisé
        self.assertEqual(mac.newest("ui")["from"], "PC")
        mac.put("ui", {"liqPrefs": "{\"a\":2}"}, 2000)
        self.assertEqual(pc.newest("ui")["data"]["liqPrefs"], "{\"a\":2}")
        old = pc.put("ui", {"liqPrefs": "{\"a\":0}"}, 1500)                     # plus ancien : refusé, la version récente revient
        self.assertEqual(old["t"], 2000)
        self.assertTrue((self.root / "PC" / "data" / "prefs.json").exists())       # copie sur le disque de chaque ordinateur
        self.assertEqual(json.loads((self.cloud / "LiqTerminal" / "reglages.json").read_text())["ui"]["from"], "Mac")

    def test_secrets_never_leave_the_machine(self):
        pc = self.machine("PC", "TELEGRAM_BOT_TOKEN=123:abc\nTELEGRAM_CHAT_ID=42\nTERMINAL_ANTHROPIC_API_KEY=sk-x\nTERMINAL_GITHUB_TOKEN=ghp_x\n"
                                "TERMINAL_X_BEARER_TOKEN=b\nTERMINAL_DATA_DIR=/x\nTERMINAL_SYNC_DIR=/y\nTERMINAL_ALERT_TF=4h\nTERMINAL_SIGNAL_LEVERAGE=10\n")
        pc.push_env()
        raw = (self.cloud / "LiqTerminal" / "reglages.json").read_text()
        self.assertEqual(json.loads(raw)["env"]["data"], {"TERMINAL_ALERT_TF": "4h", "TERMINAL_SIGNAL_LEVERAGE": "10"})
        for s in ("123:abc", "sk-x", "ghp_x", "TELEGRAM", "/x"):
            self.assertNotIn(s, raw)

    def test_settings_from_the_other_machine(self):
        pc = self.machine("PC", "TERMINAL_ALERT_TF=4h\n")
        mac = self.machine("Mac", "TERMINAL_ALERT_TF=1h\nTELEGRAM_BOT_TOKEN=999:zz\n")
        self.assertIsNone(mac.env_to_apply())
        pc.push_env()
        self.assertEqual(mac.env_to_apply(), {"TERMINAL_ALERT_TF": "4h"})
        self.assertIsNone(pc.env_to_apply())                                   # ses propres réglages : rien à reprendre

    def test_align_copies_local_to_a_new_cloud_folder(self):
        pc = prefsync.PrefSync(self.root / "solo", self.root / "solo.env", "")
        pc.put("ui", {"k": "v"}, 5)
        self.assertFalse((self.cloud / "LiqTerminal").exists())
        pc.sync_dir = str(self.cloud)
        pc.align()
        self.assertEqual(json.loads((self.cloud / "LiqTerminal" / "reglages.json").read_text())["ui"]["data"], {"k": "v"})

    def test_cloud_folders_found(self):
        home = self.root / "home"
        for p in ("Library/Mobile Documents/com~apple~CloudDocs", "Library/CloudStorage/GoogleDrive-moi@x/My Drive", "Dropbox", "iCloudDrive"):
            (home / p).mkdir(parents=True)
        one = self.root / "od"
        one.mkdir()
        labels = [c["label"] for c in prefsync.cloud_dirs(home, {"OneDrive": str(one)})]
        self.assertEqual(sorted(set(labels)), ["Dropbox", "Google Drive", "OneDrive", "iCloud Drive"])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        cls.env = cls.root / ".env"
        cls.env.write_text("TERMINAL_ALERT_TF=1h\n", encoding="utf-8")
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=str(cls.root / "data"), port=0, heatmap_days=40), env_path=cls.env)
        cls.app.service.refresh_all()
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers={"Content-Type": "application/json", "X-Terminal-Token": self.app.token})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def test_new_timeframes(self):
        self.assertEqual(TFS, ("1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(self.call("/api/config")["alertTfs"], list(ALERT_TFS))
        for tf, step in (("1m", 60), ("1w", 7 * 86400)):
            cs = self.call(f"/api/state?symbol=SOLUSDT&tf={tf}")["candles"]
            self.assertGreater(len(cs), 20)
            self.assertTrue(all(b[0] - a[0] == step for a, b in zip(cs, cs[1:])))
        w = self.call("/api/state?symbol=BTCUSDT&tf=1w")["candles"]
        self.assertTrue(all(datetime.fromtimestamp(c[0], timezone.utc).weekday() == 0 for c in w))   # lundis
        mo = self.call("/api/state?symbol=BTCUSDT&tf=1M")["candles"]
        self.assertTrue(all(datetime.fromtimestamp(c[0], timezone.utc).day == 1 for c in mo))
        for tf in ("1m", "1w", "1M"):
            r = self.call(f"/api/indicators?symbol=SOLUSDT&tf={tf}&fund=1")
            self.assertEqual(len(r["funding"]), len(r["times"]))
            self.assertTrue(self.call(f"/api/series?symbol=SOLUSDT&tf={tf}").get("ready"))
            self.assertTrue(self.call(f"/api/mtf?symbol=SOLUSDT&tf={tf}").get("ready"))

    def test_prefs_round_trip(self):
        r = self.call("/api/prefs", {"data": {"liqPrefs": json.dumps({"tf": "1w", "big": "x" * 30000})}, "t": 10**13})
        self.assertTrue(r["mine"])                                                # plus de 20 Ko accepté
        st = self.call("/api/prefs")
        self.assertEqual(json.loads(st["uiData"]["liqPrefs"])["tf"], "1w")
        self.assertEqual(st["syncDir"], "")
        cloud = self.root / "cloud"
        cloud.mkdir()
        st = self.call("/api/prefs/syncdir", {"dir": str(cloud)})
        self.assertTrue(st["syncOk"])
        self.assertTrue((cloud / "LiqTerminal" / "reglages.json").exists())
        self.assertIn("TERMINAL_SYNC_DIR=", self.env.read_text())
        with self.assertRaises(urllib.error.HTTPError):
            self.call("/api/prefs/syncdir", {"dir": str(self.root / "absent")})
        doc = self.call("/api/prefs/export")
        self.assertIn("ui", doc)
        self.assertNotIn("TERMINAL_SYNC_DIR", doc["env"])
        doc["env"]["TERMINAL_ALERT_TF"] = "4h"
        doc["env"]["TELEGRAM_BOT_TOKEN"] = "1:pirate"                            # jamais repris d'un fichier
        self.call("/api/prefs/import", {"doc": doc})
        self.assertIn("TERMINAL_ALERT_TF=4h", self.env.read_text())
        self.assertNotIn("pirate", self.env.read_text())
        self.call("/api/prefs/syncdir", {"dir": ""})

    def test_version(self):
        self.assertGreaterEqual(float(VERSION), 36)
        self.assertGreaterEqual(API_LEVEL, 35)


class PageTests(unittest.TestCase):
    APP = (WEB / "app.js").read_text(encoding="utf-8")
    MTF = (WEB / "mtf.js").read_text(encoding="utf-8")
    HTML = (WEB / "index.html").read_text(encoding="utf-8")

    def test_pages(self):
        for k in ("function barStart(", "function barEnd(", "'1w': 604800", "TF_LABEL", "function syncPull(", "function syncPush(",
                  "await syncPull(true);", "'/api/prefs/syncdir'", "'/api/prefs/import'", "visibilitychange"):
            self.assertIn(k, self.APP)
        self.assertGreaterEqual(int(re.search(r"NEED_API = (\d+)", self.APP).group(1)), 35)
        self.assertIn("'1M'", self.MTF)
        self.assertIn("LT.barStart(", self.MTF)
        for k in ('id="syncSec"', 'id="syncPick"', 'id="syncExport"', 'id="syncImport"'):
            self.assertIn(k, self.HTML)


if __name__ == "__main__":
    unittest.main()
