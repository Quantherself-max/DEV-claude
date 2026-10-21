"""V29 : la heatmap et la carte des liquidations sur tout le graphique (même en 4 heures) : mémoire longue de la heatmap (un quart d'heure
par colonne), archives publiques de Binance (profondeur « bookDepth », intérêt ouvert « metrics »), carte des liquidations rejouée sur
6 mois, adresse /api/liqmap."""
from __future__ import annotations
import base64
import io
import json
import math
import os
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path

from config import Config, load_config
from data import heatbook as hb
from data import oiarchive
from engine.atr import Candle
from engine.liqmap import LiqMap, LiqMapKeeper
from server import App, serve

H = 3_600_000
DAY = 86_400_000
T0 = 1_790_000_000_000 // DAY * DAY                    # minuit UTC
WEB = Path(__file__).resolve().parent.parent / "web"


def depth_rows(t_ms, cum_bid, cum_ask, pcts=(0.2, 1, 2, 3, 4, 5)):
    stamp = hb.time.strftime("%Y-%m-%d %H:%M:%S", hb.time.gmtime(t_ms / 1000))
    rows = []
    for sgn, cum in ((-1, cum_bid), (1, cum_ask)):
        for p, v in zip(pcts, cum):
            rows.append([stamp, f"{sgn * p:.2f}", "1", f"{v:.2f}"])
    return rows


def decode(q):
    return base64.b64decode(q["data"]) if q.get("data") else b""


def zip_csv(name, rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, "\n".join(",".join(map(str, r)) for r in rows))
    return buf.getvalue()


class DepthArchiveTests(unittest.TestCase):
    def test_bands_are_spread_over_their_width_on_each_side(self):
        rows = [["timestamp", "percentage", "depth", "notional"]]
        rows += depth_rows(T0 + 60_000, [10e6, 50e6, 100e6, 120e6, 130e6, 140e6], [10e6, 40e6, 80e6, 90e6, 95e6, 100e6])
        rows += depth_rows(T0 + 90_000, [10e6, 50e6, 100e6, 120e6, 130e6, 140e6], [10e6, 40e6, 80e6, 90e6, 95e6, 100e6])
        cols = hb.depth_columns(rows, lambda t: 100_000.0)
        self.assertEqual(len(cols), 1)                                         # les deux photos du même quart d'heure : une colonne, la moyenne
        w, b0, arr = cols[0]
        self.assertEqual(w, T0)
        price = lambda i: hb.lt_price(b0 + i + 0.5)
        bid = sum(v for i, v in enumerate(arr) if price(i) < 100_000)
        ask = sum(v for i, v in enumerate(arr) if price(i) > 100_000)
        self.assertAlmostEqual(sum(arr) / 1e6, 240, delta=0.01)                # tout l'argent jusqu'à 5 % est là, ni plus ni moins
        self.assertAlmostEqual(bid / 1e6, 140, delta=6)                        # (la tranche qui contient le prix mêle les deux côtés)
        self.assertAlmostEqual(ask / 1e6, 100, delta=6)
        near = sum(v for i, v in enumerate(arr) if 99_800 <= price(i) < 100_000)
        self.assertAlmostEqual(near / 1e6, 10, delta=1.5)                      # 0-0,2 % : 10 M$
        self.assertTrue(all(94_900 < price(i) < 105_100 for i, v in enumerate(arr) if v > 0))

    def test_older_files_without_the_02_level_and_bad_lines(self):
        rows = depth_rows(T0 + 5_000, [50e6, 100e6, 90e6, 130e6, 140e6], [40e6, 80e6, 90e6, 95e6, 100e6], pcts=(1, 2, 3, 4, 5))
        rows.append(["pas une date", "1", "1", "1"])
        cols = hb.depth_columns(rows, lambda t: 100_000.0)
        w, b0, arr = cols[0]
        self.assertAlmostEqual(sum(arr) / 1e6, 240, delta=0.01)                # 3 % plus bas que 2 % (photo abîmée) : rien de négatif
        self.assertTrue(all(v >= 0 for v in arr))
        self.assertEqual(hb.depth_columns(rows, lambda t: None), [])            # pas de prix connu : rien

    def test_fetch_reads_the_zip_and_404(self):
        rows = [["timestamp", "percentage", "depth", "notional"]] + depth_rows(T0, [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6])
        seen = []

        def http(url, timeout=90):
            seen.append(url)
            return zip_csv("BTCUSDT-bookDepth.csv", rows) if "2026" in url or "2025" in url else None
        got = hb.fetch_depth("BTCUSDT", T0, http)
        self.assertEqual(len(got), len(rows))
        self.assertIn("/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-", seen[0])
        self.assertIsNone(hb.fetch_depth("BTCUSDT", 0, http))                   # 1970 : absent


class LongMemoryTests(unittest.TestCase):
    def col(self, v=1e6, b0=None):
        b0 = b0 if b0 is not None else hb.lt_band(100_000.0) - 2
        return b0, hb.array.array("f", [v] * 4)

    def test_add_span_count_save_load_prune(self):
        d = tempfile.mkdtemp()
        lng = hb.HeatLong("BTCUSDT", days=10, folder=d)
        for q in range(96):
            lng.add("archive", T0 + q * hb.LT_MS + 7, *self.col())             # rangé au début de son quart d'heure
        lng.add("binance", T0 + 3 * hb.LT_MS, *self.col(2e6))
        self.assertTrue(lng.has("archive", T0 + 5 * hb.LT_MS + 1))
        self.assertEqual(lng.count_day("archive", T0), 96)
        self.assertEqual(len(lng.span("archive", T0, T0 + H)), 4)
        lng.tried["2026-01-01"] = 5
        self.assertEqual(lng.save(), 1)
        self.assertTrue(os.path.exists(os.path.join(d, f"long-{hb.ymd(T0)}.pkl")))
        again = hb.HeatLong("BTCUSDT", days=10, folder=d)
        self.assertEqual(again.load(T0 + DAY), 97)
        self.assertEqual(again.tried["2026-01-01"], 5)
        self.assertEqual(again.since(("binance",)), T0 + 3 * hb.LT_MS)
        self.assertEqual(hb.HeatLong("BTCUSDT", days=10, folder=d).load(T0 + 30 * DAY), 0)     # trop vieux : rien
        again.prune(T0 + 30 * DAY)
        self.assertEqual(again.count(), 0)
        self.assertFalse(any(f.startswith("long-") for f in os.listdir(d)))  # fichiers supprimés aussi

    def test_query_uses_archives_before_photos_and_photos_first(self):
        b = hb.HeatBook("BTCUSDT")
        b.long = hb.HeatLong("BTCUSDT", days=10)
        for q in range(8):                                                     # 2 heures d'archives
            b.long.add("archive", T0 + q * hb.LT_MS, *self.col(1e6))
        t_photo = T0 + 2 * H
        for k in range(0, 1800, 10):                                           # puis 30 minutes de photos Binance
            b.add("binance", t_photo + k * 1000, [(99_990.0, 50.0)], [(100_010.0, 50.0)])
        q = b.query(T0, t_photo + 1800 * 1000, 99_000.0, 101_000.0, cols=50, rows=100)
        data, n = decode(q), q["cols"]
        filled = [c for c in range(n) if any(data[j * n + c] for j in range(q["rows"]))]
        self.assertEqual(filled[0], 0)                                         # tout le graphique a sa heatmap, dès la première colonne
        self.assertGreaterEqual(len(filled), n - 1)
        self.assertIn("archive", q["longUsed"])
        q2 = b.query(T0, T0 + 2 * H, 99_000.0, 101_000.0, cols=20, rows=50, exchanges=("okx",))
        self.assertTrue(q2["empty"])                                           # les archives sont celles de Binance seulement

    def test_own_quarter_summary_replaces_the_archive(self):
        b = hb.HeatBook("BTCUSDT")
        b.long = hb.HeatLong("BTCUSDT", days=10)
        for k in range(0, 900, 10):
            b.add("binance", T0 + k * 1000, [(99_990.0, 10.0)], [(100_010.0, 10.0)])
        col = b.long_column(T0, "binance")
        self.assertIsNotNone(col)
        b0, arr = col
        self.assertAlmostEqual(sum(arr) / 1e6, (99_990 * 10 + 100_010 * 10) / 1e6, delta=0.01)    # la moyenne des minutes
        self.assertIsNone(b.long_column(T0 + H, "binance"))                    # aucune photo dans ce quart d'heure
        rec = hb.HeatRecorder(b, {}, now=lambda: (T0 + 20 * 60_000) / 1000)
        self.assertEqual(rec.summarize(), 1)
        self.assertTrue(b.long.has("binance", T0))
        self.assertEqual(rec.summarize(), 0)                                   # pas deux fois


class ArchiveRecorderTests(unittest.TestCase):
    def make(self, archive, days=5, today=T0 + 10 * DAY + 3 * H):
        b = hb.HeatBook("BTCUSDT")
        b.long = hb.HeatLong("BTCUSDT", days=days)
        return hb.HeatRecorder(b, {}, now=lambda: today / 1000, archive=archive, prices=lambda: (lambda t: 100_000.0))

    def test_days_newest_first_missing_and_errors(self):
        asked = []

        def archive(day):
            asked.append(day)
            if day == T0 + 8 * DAY:
                return None                                                    # pas publiée
            return [["timestamp", "percentage", "depth", "notional"]] + [r for q in range(96) for r in depth_rows(day + q * hb.LT_MS + 1000, [1e6, 5e6, 9e6, 12e6, 14e6, 15e6], [1e6, 4e6, 8e6, 9e6, 9.5e6, 10e6])]
        rec = self.make(archive)
        self.assertEqual(rec.fetch_archives(), 4)
        self.assertEqual(asked, [T0 + (10 - k) * DAY for k in range(1, 6)])    # d'hier vers le passé ; aujourd'hui n'est pas publié
        self.assertEqual(rec.arch["missing"], 1)
        self.assertEqual(rec.arch["days"], 4)
        asked.clear()
        self.assertEqual(rec.fetch_archives(), 0)
        self.assertEqual(asked, [])                                            # jours faits ; l'absent sera redemandé dans 3 heures

        def down(day):
            raise OSError("réseau coupé")
        rec2 = self.make(down)
        self.assertEqual(rec2.fetch_archives(), 0)
        self.assertIn("réseau coupé", rec2.arch["error"])
        self.assertEqual(rec2.book.long.tried, {})                             # rien n'est marqué : on réessaiera

    def test_days_with_own_photos_are_not_downloaded(self):
        asked = []
        rec = self.make(lambda day: asked.append(day) or [], days=2)
        lng = rec.book.long
        for q in range(96):
            lng.add("binance", T0 + 9 * DAY + q * hb.LT_MS, 0, hb.array.array("f", [1.0]))
        rec.fetch_archives()
        self.assertEqual(asked, [T0 + 8 * DAY])                                # hier est couvert par tes propres photos

    def test_waits_for_the_price_history(self):
        rec = self.make(lambda day: [])
        rec.prices = lambda: None
        self.assertEqual(rec.fetch_archives(), 0)
        self.assertTrue(rec.arch["state"].startswith("en attente"))

    def test_simulated_archives_fill_the_four_hour_chart(self):
        rows = hb.sim_depth_rows("BTCUSDT", T0, lambda t: 85_000.0)
        cols = hb.depth_columns(rows, lambda t: 85_000.0)
        self.assertEqual(len(cols), 96)
        self.assertEqual(hb.sim_depth_rows("BTCUSDT", T0, lambda t: 85_000.0, now_ms=T0 + H)[1:2][0][0][:13], hb.ymd(T0) + " 00")
        self.assertLess(len(hb.sim_depth_rows("BTCUSDT", T0, lambda t: 85_000.0, now_ms=T0 + H)), len(rows))   # rien dans le futur


def bars(n, start=T0, px=100.0, drift=0.0):
    out, p = [], px
    for i in range(n):
        o = p
        p = p * (1 + drift)
        out.append(Candle(start + i * H, o, max(o, p) * 1.002, min(o, p) * 0.998, p, 1000.0, 500.0, 1000.0 * p))
    return out


class LiqMapTests(unittest.TestCase):
    def test_levels_appear_then_vanish_when_the_price_touches_them(self):
        mp = LiqMap(days=30)
        bs = bars(48)
        oi = {b.t + H: 1000.0 + (200.0 if i >= 10 else 0.0) for i, b in enumerate(bs)}   # +200 pièces à la 10e heure
        mp.feed(bs, oi.get)
        self.assertEqual(len(mp.snaps), 48)
        q = mp.query(T0, T0 + 48 * H, 80.0, 120.0, cols=48, rows=400, price=100.0)
        self.assertTrue(q["ready"])
        self.assertFalse(q["empty"])
        data, n, rows = decode(q), q["cols"], q["rows"]
        row = lambda p: int((p - q["lo"]) / q["rowsz"])
        lev10 = 100.0 * (1 - 1 / 10 + 0.004)                                   # liquidation des longs à 10x
        lit = lambda c: max(data[j * n + c] for j in range(row(lev10) - 2, row(lev10) + 3))
        self.assertEqual(lit(5), 0)                                            # avant l'ouverture des positions : rien
        self.assertGreater(lit(20), 0)                                         # après : la ligne est là
        # le prix descend jusqu'à la ligne : elle s'éteint
        crash = [Candle(T0 + (48 + i) * H, 100.0, 100.1, 90.0 if i == 0 else 99.0, 99.5, 1000.0, 500.0, 99_500.0) for i in range(4)]
        mp.feed(crash, lambda t: 1200.0)
        q = mp.query(T0, T0 + 52 * H, 80.0, 120.0, cols=52, rows=400, price=99.5)
        data, n = decode(q), q["cols"]
        self.assertEqual(max(data[j * n + 51] for j in range(row(lev10) - 2, row(lev10) + 3)), 0)

    def test_a_gap_in_open_interest_does_not_dump_a_block(self):
        mp = LiqMap(days=30)
        bs = bars(30)
        oi = {b.t + H: (1000.0 if i < 5 else 5000.0) for i, b in enumerate(bs) if not 5 <= i < 15}   # 10 heures sans valeur, puis +4000
        mp.feed(bs, oi.get)
        self.assertEqual(mp.eng.totals(), (0.0, 0.0))                          # le saut d'après le trou n'est pas pris pour des positions

    def test_keeper_builds_extends_and_rebuilds(self):
        class Store:
            def __init__(self):
                self.h1 = bars(72, start=T0 - 72 * H)
                self.oi = {}

        class Market:
            ready = True
            store = Store()

        class Arch:
            n = 0

            def points(self):
                return {b.t + H: 1000.0 + i for i, b in enumerate(Market.store.h1)} if self.n else {}

            def fetch(self, stop_ev=None):
                self.n += 1
                return 3 if self.n == 1 else 0

            def days_count(self):
                return 3 if self.n else 0
        now = [T0 / 1000]
        kp = LiqMapKeeper("BTCUSDT", lambda: Market, Arch(), days=10, now=lambda: now[0])
        self.assertTrue(kp.step())
        self.assertEqual(len(kp.map.snaps), 72)
        self.assertIsNone(kp.map.oi_first)                                     # pas encore d'intérêt ouvert
        self.assertEqual(kp.fetch_archives(), 3)
        self.assertTrue(kp.step())                                             # archives arrivées : reconstruite
        self.assertIsNotNone(kp.map.oi_first)
        Market.store.h1.append(bars(1, start=T0)[0])
        now[0] = (T0 + 2 * H) / 1000
        self.assertTrue(kp.step())
        self.assertEqual(kp.map.fed, T0)
        self.assertFalse(kp.step())
        self.assertEqual(kp.status()["archiveDays"], 3)


class OiArchiveTests(unittest.TestCase):
    def test_download_parse_and_missing_days(self):
        d = tempfile.mkdtemp()
        today = T0 + 5 * DAY
        calls = []

        def http(url, timeout=60):
            calls.append(url)
            day = url.rsplit("-metrics-", 1)[1][:10]
            if day == hb.ymd(T0 + 2 * DAY):
                return None
            t = hb.calendar.timegm(tuple(int(x) for x in day.split("-")) + (0, 0, 0, 0, 0, 0)) * 1000
            rows = [["create_time", "symbol", "sum_open_interest", "sum_open_interest_value"]]
            rows += [[hb.time.strftime("%Y-%m-%d %H:%M:%S", hb.time.gmtime((t + k * 300_000) / 1000)), "BTCUSDT", 1000 + k, 1e8] for k in range(288)]
            return zip_csv("m.csv", rows)
        arch = oiarchive.OiArchive("BTCUSDT", d, days=4, now=lambda: today / 1000, http_bytes=http, workers=2)
        self.assertEqual(arch.fetch(), 3)
        self.assertEqual(len(calls), 4)
        self.assertIn("/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-", calls[0])
        pts = arch.points()
        self.assertEqual(len(pts), 3 * 288)
        self.assertEqual(pts[T0 + 1 * DAY + H], 1012)
        calls.clear()
        self.assertEqual(arch.fetch(), 0)
        self.assertEqual(calls, [])                                            # rien à redemander tout de suite (l'absent : demain)
        self.assertEqual(arch.days_count(), 3)

    def test_simulated_open_interest_joins_the_source(self):
        a = oiarchive.SimOiArchive("BTCUSDT", lambda: (T0, 80_000.0), days=3, now=lambda: T0 / 1000)
        pts = a.points()
        self.assertEqual(len(pts), 3 * 288)
        self.assertAlmostEqual(pts[max(pts)], 80_000.0, delta=80_000 * 0.01)  # raccordé à la première valeur de la source


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tempfile.mkdtemp(), port=0, heatmap_days=20), env_path=None)
        cls.app.service.refresh_all()
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=60) as r:
            return json.loads(r.read())

    def test_liquidation_map_on_the_whole_four_hour_chart(self):
        cfg = self.get("/api/config")
        self.assertGreaterEqual(float(cfg["version"]), 29)
        self.assertEqual(cfg["liqmapSymbols"], ["BTCUSDT", "SOLUSDT"])
        self.assertEqual(cfg["heatmapDays"], 20)
        self.assertFalse(self.get("/api/liqmap?symbol=BTCUSDT&t0=1&t1=2&lo=1&hi=2")["ready"])   # pas encore construite
        kp = self.app.liqmaps["SOLUSDT"]
        self.assertTrue(kp.step())
        now = self.app.source.now_ms()
        px = self.app.service.last_price("SOLUSDT")
        r = self.get(f"/api/liqmap?symbol=SOLUSDT&t0={now - 18 * DAY}&t1={now}&lo={px * 0.8}&hi={px * 1.2}&cols=108&rows=120")
        self.assertTrue(r["ready"])
        self.assertFalse(r["empty"])
        self.assertEqual(r["unit"], "SOL")
        data, n = decode(r), r["cols"]
        filled = sum(1 for c in range(n) if any(data[j * n + c] for j in range(r["rows"])))
        self.assertGreater(filled, n * 0.8)                                    # presque tout le graphique (le début se remplit au fil des jours)
        self.assertTrue(self.get("/api/liqmap?symbol=ETHUSDT&t0=1&t1=2&lo=1&hi=2")["off"])

    def test_heatmap_reaches_back_with_simulated_archives(self):
        rec = self.app.heat["BTCUSDT"]
        self.assertGreater(rec.fetch_archives(), 15)
        now = self.app.source.now_ms()
        px = self.app.service.last_price("BTCUSDT")
        r = self.get(f"/api/heatmap?symbol=BTCUSDT&t0={now - 15 * DAY}&t1={now - 2 * DAY}&lo={px * 0.8}&hi={px * 1.2}&cols=78&rows=100")
        self.assertTrue(r["ready"])
        self.assertFalse(r["empty"])
        self.assertEqual(r["longUsed"], ["archive"])
        self.assertTrue(r["long"]["on"])
        self.assertIsNotNone(r["long"]["archiveSince"])
        self.assertIsNone(rec.book.long.folder)                                # mode simulé : rien n'est écrit sur le disque


class SettingsTests(unittest.TestCase):
    def test_days_setting(self):
        d = Path(tempfile.mkdtemp())
        (d / ".env").write_text("TERMINAL_HEATMAP_DAYS=0\n", encoding="utf-8")
        self.assertEqual(load_config(d / ".env").heatmap_days, 0)
        (d / ".env").write_text("TERMINAL_HEATMAP_DAYS=99999\n", encoding="utf-8")
        self.assertEqual(load_config(d / ".env").heatmap_days, 1100)
        self.assertEqual(Config().heatmap_days, 180)
        app = App(Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0, heatmap_days=0), env_path=None)
        self.assertEqual(app.liqmaps, {})
        self.assertIsNone(app.heat["BTCUSDT"].book.long)                       # 0 : seulement les 24 dernières heures, comme en V28


class PageTests(unittest.TestCase):
    DESK = (WEB / "desk.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")
    PANELS = (WEB / "panels.js").read_text(encoding="utf-8")

    def test_liquidation_map_element_and_layers(self):
        self.assertIn("liqmap: ['Carte des liquidations'", self.DESK)
        self.assertIn("heat: {heat: true, liqmap: false, big: true, vol: true, plan: true}", self.DESK)
        self.assertIn("if (!('liqmap' in w.sets.heat.els)) w.sets.heat.els.liqmap = false;", self.DESK)   # anciens réglages : ajoutée, masquée
        self.assertIn("/api/liqmap?symbol=", self.DESK)
        self.assertIn("if (st.mainOpts.liqmap) this.drawHeatImage(L, h, st.liqMap);", self.PANELS)
        self.assertGreaterEqual(int(__import__("re").search(r"NEED_API = (\d+)", self.APP).group(1)), 30)
        self.assertIn("liqmap: false,", self.APP)


if __name__ == "__main__":
    unittest.main()
