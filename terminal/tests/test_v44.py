"""V44 : onglet GEX : liquidations BTC (Binance, Bybit, OKX) sur 6, 12, 24 et 48 heures et gros ordres exécutés par bourse (Binance,
Coinbase, Bitstamp, OKX, Bybit) : lecture des messages de chaque bourse, regroupement des morceaux d'un ordre, fenêtres, couverture,
sauvegarde, reprise des 24 heures d'OKX sans doublon, branchement au serveur et à la page."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from data import cexflow as C
from server import API_LEVEL, VERSION

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
WEB = Path(__file__).resolve().parent.parent / "web"
T0 = 1_794_500_000_000 - 1_794_500_000_000 % C.BUCKET          # début d'une tranche de 5 minutes


class Clock:
    def __init__(self, t_ms):
        self.t = t_ms / 1000

    def __call__(self):
        return self.t


def flow_at(t_ms, path=None):
    clk = Clock(t_ms)
    return C.CexFlow(path, now=clk), clk


def order_sums(s, h, venue, from_cls=0):
    c = s["orders"][str(h)]["venues"][venue]["c"][from_cls:]
    return sum(x[0] for x in c), sum(x[1] for x in c), sum(x[2] + x[3] for x in c)


class Helpers(unittest.TestCase):
    def test_classes_and_dates(self):
        self.assertEqual([C.cls_of(x) for x in (0, 99_999, 100_000, 750_000, 1_000_000, 9e6)], [0, 0, 1, 2, 3, 4])
        self.assertEqual(C.iso_ms("2026-11-12T21:49:19.027191Z"), 1794520159027)
        self.assertEqual(C.iso_ms("2026-11-12T21:49:19Z"), 1794520159000)
        self.assertEqual(C.iso_ms("2026-11-12T21:49:19.5+00:00"), 1794520159500)

    def test_okx_liquidations_in_dollars(self):
        item = {"instId": "BTC-USDT-SWAP", "details": [{"bkPx": "70000", "sz": "150", "posSide": "long", "side": "sell", "ts": "5"},
                                                     {"bkPx": "70000", "sz": "10", "posSide": "net", "side": "buy", "ts": "6"}]}
        self.assertEqual(C.okx_liq_events(item), [(5, "long", 105_000.0, 70000.0), (6, "short", 7_000.0, 70000.0)])   # 0,01 BTC par contrat
        inv = {"instId": "BTC-USD-SWAP", "details": [{"bkPx": "70000", "sz": "30", "posSide": "short", "ts": "7"}]}
        self.assertEqual(C.okx_liq_events(inv), [(7, "short", 3_000.0, 70000.0)])                                     # 100 dollars par contrat
        self.assertEqual(C.okx_liq_events({"instId": "ETH-USDT-SWAP", "details": [{"bkPx": "1", "sz": "1", "ts": "1"}]}), [])


class Register(unittest.TestCase):
    def test_pieces_of_one_order_are_joined(self):
        f, clk = flow_at(T0 + 60_000)
        f.fill("binance_perp", T0 + 1000, 1, 5.0, 70000.0)       # un ordre au marché qui traverse deux prix (même milliseconde)
        f.fill("binance_perp", T0 + 1000, 1, 5.0, 70010.0)
        f.fill("binance_perp", T0 + 1000, -1, 0.1, 70000.0)      # autre sens : autre ordre
        clk.t += 2
        s = f.summary()
        buy, sell, n = order_sums(s, 6, "binance_perp", 2)       # 500 000 $ et plus
        self.assertAlmostEqual(buy, 700_050.0, delta=1)
        self.assertEqual((sell, n), (0, 1))
        self.assertEqual(order_sums(s, 6, "binance_perp")[2], 2)
        self.assertEqual(s["recent"][0]["v"], "binance_perp")
        self.assertEqual(s["recent"][0]["n"], 2)
        self.assertAlmostEqual(s["recent"][0]["px"], 70005.0, delta=0.01)
        self.assertEqual(s["orders"]["6"]["top"][0]["usd"], 700050)

    def test_order_ids_join_and_streams_do_not_cut_each_other(self):
        f, clk = flow_at(T0 + 60_000)
        f.fill("okx_perp", T0 + 1, 1, 10.0, 70000.0, stream="okx:BTC-USDT-SWAP")
        f.fill("okx_perp", T0 + 2, -1, 1.0, 70000.0, stream="okx:BTC-USD-SWAP")      # un autre contrat entre deux morceaux
        f.fill("okx_perp", T0 + 1, 1, 10.0, 70001.0, stream="okx:BTC-USDT-SWAP")
        f.fill("coinbase", T0 + 5, 1, 8.0, 70000.0, key=("o", "A"))
        f.fill("coinbase", T0 + 9, 1, 8.0, 70002.0, key=("o", "A"))                   # même numéro d'ordre, autre milliseconde
        clk.t += 2
        s = f.summary()
        self.assertEqual(order_sums(s, 6, "okx_perp", 3)[2], 1)                         # 1,4 M$ en un seul ordre
        self.assertEqual(order_sums(s, 6, "coinbase", 3)[2], 1)

    def test_windows_nest_and_coverage(self):
        now = T0 + 48 * C.H
        f, clk = flow_at(now)
        for hours_ago, usd in ((1, 1e6), (10, 2e6), (20, 4e6), (40, 8e6), (60, 99e6)):
            f.liquidation("bybit", now - hours_ago * C.H, "long", usd, 70000.0)
        f.liquidation("okx", now - 2 * C.H, "short", 5e5, 71000.0)
        f.add_cover("liq:bybit", now - 30 * C.H, now)
        s = f.summary()
        self.assertEqual([s["liq"][str(h)]["ex"]["bybit"]["long"] for h in C.WINDOWS], [1e6, 3e6, 7e6, 15e6])     # 60 h : hors fenêtre
        self.assertEqual(s["liq"]["6"]["short"], 5e5)
        self.assertEqual(s["liq"]["48"]["top"][0]["usd"], 8_000_000)
        self.assertEqual(s["liq"]["24"]["ex"]["bybit"]["cover"], 1.0)
        self.assertAlmostEqual(s["liq"]["48"]["ex"]["bybit"]["cover"], 30 / 48, places=2)
        self.assertEqual(s["liq"]["6"]["ex"]["binance"]["cover"], 0.0)
        f.prune(now)
        self.assertTrue(all(b >= now - C.KEEP_MS - C.BUCKET for b in f.liq))

    def test_mark_extends_and_gaps_split(self):
        f, _ = flow_at(T0)
        f.mark("coinbase", T0)
        f.mark("coinbase", T0 + 30_000)
        f.mark("coinbase", T0 + 60_000)
        f.mark("coinbase", T0 + 600_000)                          # 9 minutes plus tard : trou
        self.assertEqual(f.cover["coinbase"], [[T0, T0 + 60_000], [T0 + 600_000, T0 + 600_000]])
        self.assertTrue(f.in_cover("coinbase", T0 + 30_000))
        self.assertFalse(f.in_cover("coinbase", T0 + 300_000))

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            path = str(Path(tmp) / "cexflow" / "BTC.json")
            f, clk = flow_at(T0 + 3_600_000, path)
            f.fill("bitstamp", T0 + 10, -1, 30.0, 70000.0, key=("o", 9))
            f.liquidation("binance", T0 + 20, "short", 250_000.0, 70500.0)
            f.add_cover("bitstamp", T0, T0 + 3_600_000)
            clk.t += 2
            f.flush()
            self.assertTrue(f.save())
            self.assertFalse(f.save())                            # rien de nouveau : pas d'écriture
            g = C.CexFlow(path, now=clk)
            self.assertGreater(g.load(), 0)
            a, b = f.summary(), g.summary()
            self.assertEqual(a["liq"], b["liq"])
            self.assertEqual(a["orders"], b["orders"])
            self.assertEqual(b["recent"][0]["usd"], 2_100_000)
            Path(path).write_text("pas du json", encoding="utf-8")
            self.assertEqual(C.CexFlow(path, now=clk).load(), 0)


class Messages(unittest.TestCase):
    def setUp(self):
        self.f, self.clk = flow_at(T0 + 60_000)
        self.cx = C.CexFeeds(self.f)

    def done(self):
        self.clk.t += 2
        return self.f.summary()

    def test_binance(self):
        self.cx.on_binance_trade({"e": "aggTrade", "T": T0 + 1, "p": "70000", "q": "20", "m": True}, "perp")   # acheteur affiché : vente au marché
        self.cx.on_binance_spot(json.dumps({"e": "aggTrade", "T": T0 + 2, "p": "70000", "q": "1", "m": False}))
        self.cx.on_binance_liq({"t": T0 + 3, "side": "long", "usd": 1e6, "price": 70000.0})
        s = self.done()
        self.assertEqual(order_sums(s, 6, "binance_perp")[:2], (0, 1_400_000))
        self.assertEqual(order_sums(s, 6, "binance_spot")[:2], (70_000, 0))
        self.assertEqual(s["liq"]["6"]["ex"]["binance"]["long"], 1e6)

    def test_bybit_trades_and_liquidation_side(self):
        trades = {"topic": "publicTrade.BTCUSDT", "type": "snapshot", "data": [
            {"T": T0 + 1, "s": "BTCUSDT", "S": "Sell", "v": "10", "p": "70000", "BT": False},
            {"T": T0 + 1, "s": "BTCUSDT", "S": "Sell", "v": "5", "p": "69990", "BT": False}]}
        self.cx.on_bybit(json.dumps(trades), "perp")
        liq = {"topic": "allLiquidation.BTCUSDT", "type": "snapshot", "data": [
            {"T": T0 + 2, "s": "BTCUSDT", "S": "Buy", "v": "2", "p": "69000"},     # Buy : un LONG liquidé (doc Bybit)
            {"T": T0 + 3, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "71000"}]}
        self.cx.on_bybit(json.dumps(liq), "perp")
        self.cx.on_bybit(json.dumps({"op": "subscribe", "success": False, "ret_msg": "topic inconnu"}), "spot")
        s = self.done()
        self.assertEqual(order_sums(s, 6, "bybit_perp", 3), (0, 1_049_950, 1))
        L = s["liq"]["6"]["ex"]["bybit"]
        self.assertEqual((L["long"], L["short"]), (138_000, 71_000))
        self.assertEqual(self.cx.errors["bybit_spot"], "topic inconnu")

    def test_okx_trades_and_liquidations(self):
        self.cx.on_okx("pong")
        msg = {"arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"}, "data": [
            {"instId": "BTC-USDT-SWAP", "px": "70000", "sz": "1000", "side": "buy", "ts": str(T0 + 1)}]}     # 1 000 contrats = 10 BTC
        self.cx.on_okx(json.dumps(msg))
        self.cx.on_okx(json.dumps({"arg": {"channel": "trades", "instId": "BTC-USD-SWAP"}, "data": [
            {"instId": "BTC-USD-SWAP", "px": "70000", "sz": "3000", "side": "sell", "ts": str(T0 + 2)}]}))   # 3 000 x 100 $
        self.cx.on_okx(json.dumps({"arg": {"channel": "trades", "instId": "BTC-USDT"}, "data": [
            {"instId": "BTC-USDT", "px": "70000", "sz": "2", "side": "sell", "ts": str(T0 + 3)}]}))
        self.cx.on_okx(json.dumps({"arg": {"channel": "liquidation-orders", "instType": "SWAP"}, "data": [
            {"instId": "BTC-USDT-SWAP", "details": [{"bkPx": "70000", "sz": "100", "posSide": "short", "side": "buy", "ts": str(T0 + 4)}]},
            {"instId": "ETH-USDT-SWAP", "details": [{"bkPx": "3000", "sz": "100", "posSide": "long", "ts": str(T0 + 4)}]}]}))
        self.cx.on_okx(json.dumps({"event": "error", "code": "60018", "msg": "mauvais canal"}))
        s = self.done()
        self.assertEqual(order_sums(s, 6, "okx_perp")[:2], (700_000, 300_000))
        self.assertEqual(order_sums(s, 6, "okx_spot")[:2], (0, 140_000))
        self.assertEqual(s["liq"]["6"]["ex"]["okx"]["short"], 70_000)
        self.assertEqual(s["liq"]["6"]["ex"]["okx"]["long"], 0)
        self.assertIn("60018", self.cx.errors["okx"])

    def test_coinbase_side_is_the_resting_order(self):
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp((T0 + 5) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        base = {"type": "match", "product_id": "BTC-USD", "time": iso}
        self.cx.on_coinbase(json.dumps({**base, "side": "sell", "size": "10", "price": "70000", "taker_order_id": "X"}))   # vendeur affiché : achat au marché
        self.cx.on_coinbase(json.dumps({**base, "side": "sell", "size": "5", "price": "70001", "taker_order_id": "X"}))
        self.cx.on_coinbase(json.dumps({**base, "type": "last_match", "side": "buy", "size": "99", "price": "70000"}))     # avant l'abonnement : ignoré
        self.cx.on_coinbase(json.dumps({"type": "error", "message": "Failed to subscribe"}))
        s = self.done()
        buy, sell, n = order_sums(s, 6, "coinbase", 3)
        self.assertEqual((round(buy), sell, n), (1_050_005, 0, 1))
        self.assertEqual(self.cx.errors["coinbase"], "Failed to subscribe")

    def test_bitstamp_type_and_order_ids(self):
        for amount, oid in (("8", 77), ("7", 77)):
            self.cx.on_bitstamp(json.dumps({"event": "trade", "channel": "live_trades_btcusd", "data": {
                "amount": amount, "price": "70000", "type": 1, "microtimestamp": str((T0 + 5) * 1000), "buy_order_id": 1, "sell_order_id": oid}}))
        self.cx.on_bitstamp(json.dumps({"event": "bts:subscription_succeeded", "data": {}}))

        class Cl:
            n = 0

            def reconnect(self):
                Cl.n += 1
        self.cx.clients["bitstamp"] = Cl()
        self.cx.on_bitstamp(json.dumps({"event": "bts:request_reconnect", "data": {}}))
        s = self.done()
        self.assertEqual(order_sums(s, 6, "bitstamp", 3), (0, 1_050_000, 1))
        self.assertEqual(Cl.n, 1)


class History(unittest.TestCase):
    def test_okx_backfill_fills_gaps_only(self):
        now = T0 + 30 * C.H
        f, _ = flow_at(now)
        f.add_cover("liq:okx", now - 5 * C.H, now - 2 * C.H)               # déjà enregistré par le flux en direct
        events = [(now - k * C.H, "long" if k % 2 else "short") for k in range(1, 27)]
        pages = {"BTC-USDT": [events[:10], events[10:]], "BTC-USD": [events[:3]]}
        calls = []

        def http_json(url, timeout=15):
            fam = url.split("instFamily=")[1].split("&")[0]
            calls.append(url)
            k = sum(1 for u in calls if f"instFamily={fam}&" in u) - 1
            batch = pages[fam][k] if k < len(pages[fam]) else []
            inst = "BTC-USDT-SWAP" if fam == "BTC-USDT" else "BTC-USD-SWAP"
            return {"data": [{"instId": inst, "details": [{"bkPx": "70000", "sz": "100", "posSide": s, "ts": str(t)} for t, s in batch]}] if batch else []}
        cx = C.CexFeeds(f, http_json=http_json)
        added = cx.okx_backfill(pause=0)
        skipped = sum(1 for t, _ in events if now - 5 * C.H <= t <= now - 2 * C.H)
        self.assertEqual(added, 26 - skipped + 1)                           # BTC-USD : 1, 2 et 3 h ; 2 et 3 h déjà couvertes
        self.assertIn("after=", calls[1])
        self.assertTrue(f.in_cover("liq:okx", now - 20 * C.H))
        self.assertFalse(f.in_cover("liq:okx", now - 27 * C.H))              # avant la plus ancienne liquidation lue : pas couvert
        again = cx.okx_backfill(pause=0)
        self.assertEqual(again, 0)                                          # deuxième passage : tout est couvert, rien en double
        self.assertEqual(cx.backfill["added"], 0)

    def test_okx_backfill_cut_by_page_limit(self):
        now = T0 + 30 * C.H
        f, _ = flow_at(now)
        def http_json(url, timeout=15):                                     # une liquidation par page, une heure plus tôt à chaque page
            if "BTC-USDT&" not in url:
                return {"data": []}
            t = (int(url.split("after=")[1]) if "after=" in url else now) - C.H
            return {"data": [{"instId": "BTC-USDT-SWAP", "details": [{"bkPx": "70000", "sz": "100", "posSide": "long", "ts": str(t)}]}]}
        cx = C.CexFeeds(f, http_json=http_json)
        self.assertEqual(cx.okx_backfill(pages=2, pause=0), 2)
        self.assertTrue(f.in_cover("liq:okx", now - 2 * C.H))
        self.assertFalse(f.in_cover("liq:okx", now - 3 * C.H))               # deux pages seulement : pas de couverture inventée au-delà

    def test_binance_import_once_with_estimated_cover(self):
        now = T0 + 10 * C.H
        f, _ = flow_at(now)
        cx = C.CexFeeds(f)
        evs = [{"t": now - 3 * C.H + k * 60_000, "side": "long", "usd": 10_000.0, "price": 70000.0} for k in range(30)]
        self.assertEqual(cx.import_binance(evs), 30)
        self.assertEqual(f.summary()["liq"]["6"]["ex"]["binance"]["long"], 300_000)
        self.assertEqual(len(f.cover["liq:binance"]), 1)
        self.assertEqual(cx.import_binance(evs), 0)                          # une seule fois


class SimAndWiring(unittest.TestCase):
    def test_simulated_history_and_live(self):
        now = T0 + 50 * C.H
        f, clk = flow_at(now)
        price = lambda t: 70000.0 * (1 + 0.02 * ((t // C.H) % 7 - 3) / 3)
        sim = C.SimCex(f, prices=lambda: price, last=lambda: 70000.0)
        self.assertTrue(sim.backfill())
        s = f.summary()
        self.assertGreater(s["liq"]["48"]["long"] + s["liq"]["48"]["short"], s["liq"]["6"]["long"] + s["liq"]["6"]["short"])
        self.assertTrue(all(s["orders"]["24"]["venues"][v]["cover"] == 1.0 for v in C.VENUE_IDS))
        for v in C.VENUE_IDS:
            for buy, sell, nb, ns in s["orders"]["24"]["venues"][v]["c"]:
                self.assertEqual(buy > 0, nb > 0, v)                         # pas de montant sans ordre
        clk.t += 120
        sim.step()
        self.assertTrue(sim.status()["simulated"])
        self.assertFalse(C.SimCex(C.CexFlow(None, now=clk), prices=lambda: None).backfill())

    def test_status_alive_rules(self):
        f, clk = flow_at(T0)

        class Cl:
            def __init__(self, on):
                self.connected, self.last_error = on, ""
        cx = C.CexFeeds(f)
        cx.clients = {"coinbase": Cl(True), "okx": Cl(False), "bybit_linear": Cl(True)}
        self.assertFalse(cx.alive("coinbase"))                              # connecté mais muet : pas couvert
        f.fill("coinbase", T0, 1, 1.0, 70000.0)
        self.assertTrue(cx.alive("coinbase"))
        self.assertTrue(cx.alive("liq:bybit"))                              # les liquidations peuvent être rares : la connexion suffit
        self.assertFalse(cx.alive("liq:okx"))
        cx.mark_all()
        self.assertIn("coinbase", f.cover)
        self.assertNotIn("liq:okx", f.cover)
        st = cx.status()["sources"]
        self.assertEqual(set(st), set(C.VENUE_IDS) | {"liq:binance", "liq:bybit", "liq:okx"})
        self.assertEqual(st["binance_perp"]["error"], "pas de connexion")

    def test_live_feed_hands_btc_only(self):
        from data.live import LiveFeed
        got = []

        class Cx:
            def on_binance_trade(self, x, m):
                got.append(("trade", x["s"], m))

            def on_binance_liq(self, ev):
                got.append(("liq", ev["side"]))
        lf = LiveFeed("wss://x", ["BTCUSDT", "SOLUSDT"])
        lf.cex = Cx()
        tr = lambda s: json.dumps({"data": {"e": "aggTrade", "s": s, "p": "1", "q": "1", "m": False, "T": 1, "E": 1}})
        lf.on_trade(tr("BTCUSDT"))
        lf.on_trade(tr("SOLUSDT"))
        lf.on_spot_trade(tr("BTCUSDT"))
        lf.on_liq(json.dumps({"data": {"e": "forceOrder", "E": 5, "o": {"s": "BTCUSDT", "S": "SELL", "q": "2", "z": "2", "ap": "70000", "T": 5}}}))
        self.assertEqual(got, [("trade", "BTCUSDT", "perp"), ("trade", "BTCUSDT", "spot"), ("liq", "long")])

    def test_server_wiring_and_page(self):
        from config import Config, load_config
        from data.simulated import SimulatedSource
        from server import App, default_cex
        from tests.test_data_server import NOW as N
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=N), make_hub=lambda c, s: None)
            self.assertIsInstance(app.cex, C.SimCex)
            r = app.cex_page()
            self.assertTrue(r["ok"], r.get("why"))
            for k in ("liq", "orders", "recent", "venues", "liqEx", "sources", "moves", "windows", "classes"):
                self.assertIn(k, r)
            self.assertTrue(r["simulated"])
            app.cex = None
            self.assertIn("TERMINAL_SYMBOLS", app.cex_page()["why"])
            cfg.cexflow_on = False
            self.assertIsNone(default_cex(cfg, None, None, None))
            self.assertIn("TERMINAL_CEXFLOW=0", app.cex_page()["why"])
            bcfg = Config(source="binance", symbols=("BTCUSDT",), data_dir=tmp, port=0)

            class Feed:
                spot_base, spot_trades, cex = "wss://spot", {"BTCUSDT": object()}, None
            fd = Feed()
            cx = default_cex(bcfg, None, None, fd)
            self.assertIsInstance(cx, C.CexFeeds)
            self.assertIs(fd.cex, cx)
            self.assertFalse(cx.own_spot())                                    # le comptant Binance arrive déjà par LiveFeed
            self.assertNotIn("binance_spot", cx.make_clients())
            fd.spot_trades = {}
            self.assertIn("binance_spot", cx.make_clients())
            self.assertIsNone(default_cex(Config(source="binance", symbols=("SOLUSDT",), data_dir=tmp, port=0), None, None, None))
            env = Path(tmp) / ".env"
            env.write_text("TERMINAL_CEXFLOW=0\n", encoding="utf-8")
            self.assertFalse(load_config(env).cexflow_on)

    def test_page(self):
        self.assertEqual(API_LEVEL, 44)
        self.assertEqual(VERSION, str(API_LEVEL))
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn(f"const NEED_API = {API_LEVEL};", app)
        self.assertIn("cexWin: 24, cexMin: 1000000", app)
        gex = (WEB / "gex.js").read_text(encoding="utf-8")
        for s in ("/api/cexflow", "function liqCard()", "function ordCard()", "data-cxw", 'data-gx="cexMin"', "setInterval(loadCex, 10000)",
                  "Liquidations BTC · perpétuels", "Gros ordres exécutés · BTC", "le plus vendeur", '<div class="gexcx"></div><div class="gexopt"></div>'):
            self.assertIn(s, gex)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".gexcx,.gexopt{display:contents}", css)
        srv = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('u.path == "/api/cexflow"', srv)
        r = subprocess.run(["node", "--check", str(WEB / "gex.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
