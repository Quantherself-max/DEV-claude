"""V45 : couche d'ingestion (client HTTP, bourses, réseau Bitcoin, WebSocket) et module central. Aucun réseau : le transport est remplacé."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data import cexflow, live, ws
from engine import footprint as fpm
from ingest import binance as ib
from ingest import core, onchain, venues
from ingest.hub import QuantHub
from quant import flow
from quant.num import D, UNIT, units

MIN = 60_000


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Net:
    """Faux transport : `routes` = {morceau d'adresse: réponse ou liste de réponses (jouées dans l'ordre, la dernière reste)}.
    Une réponse = objet JSON, ou (statut, en-têtes, objet)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, list):
                    val = val.pop(0) if len(val) > 1 else val[0]
                if callable(val):
                    val = val(url)
                if isinstance(val, tuple):
                    st, hd, body = val
                else:
                    st, hd, body = 200, {}, val
                return st, hd, (body if isinstance(body, bytes) else json.dumps(body).encode())
        return 404, {}, b'{"msg":"inconnu"}'


def client(routes, clock=None, **kw):
    clock = clock or Clock()
    net = Net(routes)
    c = core.HttpClient("Essai", "https://x.test", transport=net, sleep=clock.sleep, now=clock.now, rnd=lambda: 1.0, **kw)
    c.limiter.now = clock.now
    c.limiter.t = clock.now()
    return c, net, clock


class CoreTest(unittest.TestCase):
    def test_rate_limiter_waits_and_penalty(self):
        ck = Clock()
        rl = core.RateLimiter(2.0, 4.0, now=ck.now, sleep=ck.sleep)
        self.assertEqual([rl.acquire() for _ in range(4)], [0.0] * 4)          # réserve de 4
        self.assertAlmostEqual(rl.acquire(), 0.5)                                # puis 2 par seconde
        rl.penalize(10.0)
        self.assertAlmostEqual(rl.acquire(), 10.0)
        self.assertEqual(rl.paused_for(), 0.0)

    def test_backoff_is_exponential_capped_and_jittered(self):
        self.assertEqual([core.backoff_delay(i, 0.5, 20.0, lambda: 1.0) for i in range(8)], [0.5, 1, 2, 4, 8, 16, 20, 20])
        self.assertEqual(core.backoff_delay(3, 0.5, 20.0, lambda: 0.0), 2.0)     # aléa : entre la moitié et la totalité

    def test_decimal_parse_cache_and_meta(self):
        c, net, ck = client({"/a": {"p": 0.1, "q": "0.2", "n": 3}})
        d = c.get("/a", ttl=10)
        self.assertEqual(d["p"], Decimal("0.1"))                                 # nombre JSON lu en décimal, pas en flottant binaire
        self.assertIsInstance(d["q"], str)
        ck.t += 5
        c.get("/a", ttl=10)
        self.assertEqual((len(net.calls), c.cache_hits, c.meta("/a")["cached"]), (1, 1, True))
        ck.t += 6
        c.get("/a", ttl=10)
        self.assertEqual(len(net.calls), 2)

    def test_retries_then_error_then_stale(self):
        c, net, ck = client({"/a": [{"v": 1}, (500, {}, {"e": 1})]})
        self.assertEqual(c.get("/a")["v"], 1)
        with self.assertRaises(core.IngestError) as e:
            c.get("/a")
        self.assertEqual((e.exception.kind, e.exception.status, len(net.calls), c.retried), ("http", 500, 5, 3))
        self.assertEqual(ck.slept, [0.5, 1.0, 2.0])                              # 0,5 s, 1 s, 2 s entre les quatre essais
        self.assertEqual(c.get("/a", stale_ok=True)["v"], 1)                     # dernière réponse connue, et c'est dit
        self.assertTrue(c.meta("/a")["stale"])
        self.assertEqual(c.status()["stale"], 1)

    def test_blocked_rate_limited_and_banned(self):
        c, net, _ = client({"/geo": (451, {}, {"msg": "restricted"}), "/ban": (418, {"Retry-After": "300"}, {})})
        with self.assertRaises(core.IngestError) as e:
            c.get("/geo")
        self.assertEqual((e.exception.kind, len(net.calls)), ("blocked", 1))     # refus par pays : aucun nouvel essai
        with self.assertRaises(core.IngestError) as e:
            c.get("/ban")
        self.assertEqual((e.exception.kind, round(c.limiter.paused_for())), ("rate", 300))
        c, net, ck = client({"/r": [(429, {"Retry-After": "7"}, {}), {"ok": 1}]})
        self.assertEqual(c.get("/r")["ok"], 1)
        self.assertEqual(ck.slept, [7.0])                                        # l'attente demandée par le serveur est respectée

    def test_binance_weight_header_pauses_before_the_limit(self):
        c, _, ck = client({"/a": (200, {"X-MBX-USED-WEIGHT-1M": "2000"}, {"v": 1})}, weight_limit=2400, weight_header="X-MBX-USED-WEIGHT-1M")
        c.get("/a")
        self.assertEqual(c.used_weight, 2000)
        self.assertGreater(c.limiter.paused_for(), 0)                            # 83 % de la limite : pause jusqu'à la minute suivante
        self.assertLessEqual(c.limiter.paused_for(), 60.5)

    def test_need_never_invents(self):
        self.assertEqual(core.need({"a": [{"b": 2}]}, "a", 0, "b"), 2)
        with self.assertRaises(core.IngestError):
            core.need({"a": 1}, "b")


KL = [1_700_000_040_000, "100.0", "101.5", "99.5", "101.0", "12.500", 1_700_000_099_999, "1256.25000", 42, "7.250", "730.10000", "0"]


class BinanceTest(unittest.TestCase):
    def test_parsers_are_exact(self):
        self.assertEqual(ib.parse_agg_trade({"a": 9, "p": "68000.10", "q": "0.001", "T": 5, "m": True}), (5, units("68000.1"), units("0.001"), -1, 9))
        self.assertEqual(ib.parse_agg_trade({"a": 9, "p": "68000.10", "q": "0.001", "T": 5, "m": False})[3], 1)
        r = ib.kline_row(KL)
        self.assertEqual(r[:5], (1_700_000_040_000, 100 * UNIT, units("101.5"), units("99.5"), 101 * UNIT))
        self.assertEqual((r[5], r[6], r[9]), (units("7.25"), units("5.25"), 42))                 # achats, ventes = volume - achats
        self.assertEqual((r[7], r[8]), (units("730.1") * UNIT, units("526.15") * UNIT))
        t, bids, asks = ib.parse_depth20({"T": 7, "b": [["100.0", "2"], ["99.9", "0"]], "a": [["100.1", "1.5"]]})
        self.assertEqual((t, bids, asks), (7, [(D("100.0"), D("2"))], [(D("100.1"), D("1.5"))]))
        self.assertEqual(ib.stream_depth20("BTCUSDT"), "btcusdt@depth20@100ms")

    def test_client_endpoints(self):
        page1 = [[KL[0] + i * MIN, *KL[1:]] for i in range(1500)]
        page2 = [[KL[0] + (1500 + i) * MIN, *KL[1:]] for i in range(3)]
        routes = {"/fapi/v1/klines": [page1, page2], "/fapi/v1/openInterest": {"openInterest": "81234.567", "symbol": "BTCUSDT", "time": 1_700_000_000_123},
                  "/fapi/v1/fundingRate": [[{"fundingTime": 1_700_000_000_000, "fundingRate": "0.00010000", "markPrice": "68000.5"},
                                            {"fundingTime": 1_699_971_200_000, "fundingRate": "-0.00002000", "markPrice": ""}]],
                  "/futures/data/globalLongShortAccountRatio": [[{"timestamp": "1700000000000", "longShortRatio": "1.5", "longAccount": "0.6", "shortAccount": "0.4"}]],
                  "/futures/data/openInterestHist": [[{"timestamp": 1_700_000_000_000, "sumOpenInterest": "80000.1", "sumOpenInterestValue": "5440006800.5"}]],
                  "/fapi/v1/premiumIndex": {"time": 1_700_000_000_000, "markPrice": "68000.5", "indexPrice": "68010.1", "lastFundingRate": "0.0001", "nextFundingTime": 1_700_028_800_000}}
        c, net, _ = client(routes, rate=1000, burst=1000)
        b = ib.Binance(c, c)
        rows = b.klines_exact("BTCUSDT", "1m", KL[0], KL[0] + 2000 * MIN)
        self.assertEqual((len(rows), len([u for u in net.calls if "klines" in u])), (1503, 2))    # pagination jusqu'à la page incomplète
        self.assertEqual(b.open_interest("BTCUSDT"), (1_700_000_000_123, D("81234.567")))
        f = b.funding_rate("BTCUSDT")
        self.assertEqual([x[1] for x in f], [D("-0.00002"), D("0.0001")])                         # triés, le plus ancien d'abord
        self.assertIsNone(f[0][2])
        self.assertEqual(b.long_short("BTCUSDT")[0][2], D("0.6"))
        self.assertEqual(b.open_interest_hist("BTCUSDT")[0][1], D("80000.1"))
        self.assertEqual(b.premium_index("BTCUSDT")["funding"], D("0.0001"))


class VenuesTest(unittest.TestCase):
    def test_bybit(self):
        msg = {"topic": "publicTrade.BTCUSDT", "data": [{"T": 1794620432648, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "68257.50", "i": "x"},
                                                       {"T": 1794620432649, "S": "Sell", "v": "2", "p": "68257.40", "i": "y"}]}
        self.assertEqual([t[3] for t in venues.parse_public_trade(msg)], [1, -1])                 # S = côté de l'agresseur (message réel du 14/11/2026)
        c, _, _ = client({"/v5/market/open-interest": {"retCode": 0, "result": {"list": [{"openInterest": "50000.5", "timestamp": "1700000300000"},
                                                                                            {"openInterest": "49000", "timestamp": "1700000000000"}]}},
                          "/v5/market/funding/history": {"retCode": 10001, "retMsg": "params error"}})
        y = venues.Bybit(c)
        self.assertEqual(y.open_interest("BTCUSDT"), [(1700000000000, D("49000")), (1700000300000, D("50000.5"))])
        with self.assertRaises(core.IngestError):
            y.funding_history("BTCUSDT")                                                          # code d'erreur : jamais une liste vide silencieuse

    def test_okx(self):
        row = {"instId": "BTC-USDT-SWAP", "tradeId": "3074355735", "px": "68285.5", "sz": "0.61", "side": "sell", "ts": "1794620167380"}
        self.assertEqual(venues.parse_okx_trade(row, "0.01"), (1794620167380, units("68285.5"), units("0.0061"), -1, "3074355735"))
        c, _, _ = client({"/api/v5/public/open-interest": {"code": "0", "data": [{"oi": "3344209.34000001461", "oiCcy": "33442.0934000001461",
                                                                                   "oiUsd": "2283161944.81", "ts": "1794620168536"}]},
                          "/api/v5/public/position-tiers": {"code": "0", "data": [{"maxSz": "5000", "mmr": "0.005", "imr": "0.015", "maxLever": "66.66"},
                                                                                   {"maxSz": "1000", "mmr": "0.004", "imr": "0.01", "maxLever": "100"}]},
                          "/api/v5/market/trades": {"code": "51001", "msg": "Instrument ID does not exist", "data": []}})
        o = venues.Okx(c)
        self.assertEqual(o.open_interest("BTC-USDT-SWAP")["coins"], D("33442.0934000001461"))     # plus de 8 décimales : gardé tel quel en décimal
        tiers = o.position_tiers("BTC-USDT")
        self.assertEqual((venues.okx_mmr("1000", tiers), venues.okx_mmr("1000.01", tiers)), (D("0.004"), D("0.005")))
        with self.assertRaises(core.IngestError):
            o.trades("BTC-USDT-SWAP")
        self.assertEqual(venues.okx_inst("SOLUSDT"), "SOL-USDT-SWAP")

    def test_deribit_chain(self):
        inst = {"jsonrpc": "2.0", "result": [
            {"instrument_name": "BTC-20NOV26-66000-C", "expiration_timestamp": 1795161600000, "strike": 6.6e4, "option_type": "call", "contract_size": 1.0},
            {"instrument_name": "BTC-20NOV26-66000-P", "expiration_timestamp": 1795161600000, "strike": 6.6e4, "option_type": "put", "contract_size": 1.0}]}
        summ = {"jsonrpc": "2.0", "usOut": 1794620167501000, "result": [
            {"instrument_name": "BTC-20NOV26-66000-C", "open_interest": 12.5, "mark_price": 0.04240806, "mark_iv": 41.34, "underlying_price": 68319.17,
             "estimated_delivery_price": 68245.34},
            {"instrument_name": "BTC-20NOV26-66000-P", "open_interest": 0.0, "mark_price": 0.01, "mark_iv": None, "underlying_price": 68319.17},
            {"instrument_name": "BTC-INCONNU", "open_interest": 1.0, "mark_iv": 50.0, "underlying_price": 68000.0}]}
        c, _, _ = client({"get_instruments": inst, "get_book_summary_by_currency": summ, "get_index_price": {"result": {"index_price": 68224.47}},
                          "ticker": {"error": {"message": "not found"}}})
        d = venues.Deribit(c)
        ch = d.option_chain("BTC")
        self.assertEqual((len(ch["rows"]), ch["skipped"], ch["t"], ch["index"]), (1, 2, 1794620167501, 68245.34))
        r = ch["rows"][0]
        self.assertEqual((r["strike"], r["kind"], r["expiry"], r["oi"], r["oiText"], r["iv"]), (66000.0, "C", 1795161600000, 12.5, "12.5", 0.4134))
        self.assertEqual(d.index_price(), D("68224.47"))
        with self.assertRaises(core.IngestError):
            d.ticker("X")


class OnChainTest(unittest.TestCase):
    def test_snapshot_parts_and_refused_metric(self):
        def cm(url):
            if "FlowOutExNtv" in url:
                return (403, {}, {"error": {"type": "forbidden", "message": "Requested metric 'FlowOutExNtv' with frequency '1d' for asset 'btc' is not available"}})
            return {"data": [{"asset": "btc", "time": "2026-11-12T00:00:00.000000000Z", "AdrActCnt": "675769", "CapMVRVCur": "1.324104337503383202"},
                             {"asset": "btc", "time": "2026-11-11T00:00:00.000000000Z", "AdrActCnt": "645477", "CapMVRVCur": "1.369714083234665797"}]}
        routes = {"/api/v1/fees/recommended": {"fastestFee": 5, "halfHourFee": 4, "hourFee": 1, "economyFee": 1, "minimumFee": 1},
                  "/api/mempool": {"count": 69129, "vsize": 35400371, "total_fee": 9746404},
                  "/api/v1/difficulty-adjustment": {"progressPercent": 99.25, "difficultyChange": -8.86, "estimatedRetargetDate": 1794629233470, "remainingBlocks": 15},
                  "/api/v1/mining/hashrate/3d": {"hashrates": [{"timestamp": 1794441600, "avgHashrate": 982418957655495700000}],
                                                 "currentHashrate": 918518860834575500000, "currentDifficulty": 148364561003867.4},
                  "/api/blocks/tip/height": 975730, "/v4/timeseries/asset-metrics": cm,
                  "/stats": {"timestamp": 1.794619186E12, "hash_rate": 8.334023834011765E11, "total_fees_btc": -35312500000, "n_blocks_total": 975730,
                             "minutes_between_blocks": 11.9911, "difficulty": 148364561003867}}
        c, net, _ = client(routes, rate=1000, burst=1000)
        oc = onchain.OnChain(c, c, c)
        s = oc.snapshot()
        self.assertEqual((s["fees"]["fastest"], s["mempool"]["count"], s["tip"]), (D(5), 69129, 975730))
        self.assertEqual(s["mempool"]["blocksToClear"], D("35.400371"))
        self.assertEqual(s["hashrate"]["hashrateEH"].quantize(D("0.1")), D("918.5"))
        self.assertEqual(s["blockchain"]["hashrateEH"].quantize(D("0.1")), D("833.4"))             # publié en gigahachages par seconde
        self.assertNotIn("total_fees_btc", json.dumps(s, default=str))                             # champ incohérent (négatif) : jamais lu
        cmr = s["coinmetrics"]
        self.assertEqual((cmr["refused"], "FlowOutExNtv" in cmr["metrics"]), (["FlowOutExNtv"], False))
        self.assertEqual([r["t"] for r in cmr["rows"]], [1794355200000, 1794441600000])            # triés, heures ISO en millisecondes
        self.assertEqual(cmr["rows"][-1]["CapMVRVCur"], D("1.324104337503383202"))
        self.assertLess(s["crossCheck"]["difficultyGapPct"], D("0.0001"))

    def test_one_source_down_does_not_hide_the_others(self):
        c, _, _ = client({"/api/v1/fees/recommended": {"fastestFee": 5, "halfHourFee": 4, "hourFee": 1, "economyFee": 1, "minimumFee": 1}}, retries=1)
        s = onchain.OnChain(c, c, c).snapshot()
        self.assertEqual(s["fees"]["hour"], D(1))
        self.assertIn("error", s["mempool"])
        self.assertIn("error", s["coinmetrics"])


class WsTest(unittest.TestCase):
    def test_reconnect_wait_grows_then_caps(self):
        self.assertEqual([ws.backoff_wait(n, lambda: 1.0) for n in range(1, 9)], [1, 2, 4, 8, 16, 32, 60, 60])
        self.assertEqual(ws.backoff_wait(4, lambda: 0.0), 4.0)

    def test_proxy_choice(self):
        env = {"HTTPS_PROXY": "http://user:pw@proxy.local:3128", "NO_PROXY": "localhost,.interne.test,direct.test"}
        self.assertEqual(ws.proxy_for("ws.okx.com", True, env)[:2], ("proxy.local", 3128))
        self.assertTrue(ws.proxy_for("ws.okx.com", True, env)[2].startswith("Basic "))
        self.assertIsNone(ws.proxy_for("a.interne.test", True, env))
        self.assertIsNone(ws.proxy_for("direct.test", True, env))
        self.assertIsNone(ws.proxy_for("ws.okx.com", False, env))                                  # pas de proxy pour ws:// si seul HTTPS_PROXY existe
        self.assertIsNone(ws.proxy_for("ws.okx.com", True, {}))

    def test_fallback_port_and_client_fields(self):
        self.assertEqual(ws.port_fallbacks("wss://ws.okx.com:8443/ws/v5/public"), ("wss://ws.okx.com/ws/v5/public",))
        self.assertEqual(ws.port_fallbacks("wss://stream.bybit.com/v5/public/linear"), ())
        c = ws.WSClient("wss://ws.okx.com:8443/ws/v5/public", lambda t: None, fallbacks=ws.port_fallbacks("wss://ws.okx.com:8443/ws/v5/public"))
        self.assertEqual((c.port, len(c.urls), c.failures, list(c.gaps)), (8443, 2, 0, []))
        c._set_url(c.urls[1])
        self.assertEqual((c.port, c.host), (443, "ws.okx.com"))


def kl(t0, o, h, l, c, buy, sell, n=10):
    """Bougie officielle au format de l'API à partir d'achats et de ventes (textes)."""
    v = D(buy) + D(sell)
    return [t0, o, h, l, c, format(v, "f"), t0 + MIN - 1, format(v * D(c), "f"), n, buy, format(D(buy) * D(c), "f"), "0"]


class FakeBook:
    def levels(self):
        bids = [(100.0 - 0.1 * i, 1.0) for i in range(1, 9)]
        asks = [(100.0 + 0.1 * i, 1.0) for i in range(1, 9)]
        bids[4] = (bids[4][0], 60.0)
        return bids, asks


class HubTest(unittest.TestCase):
    T0 = 1_700_000_040_000 - 1_700_000_040_000 % MIN

    def make(self, routes=None, **kw):
        ck = Clock((self.T0 + 5 * MIN + 30_000) / 1000)
        c, net, _ = client(routes or {}, ck, rate=1000, burst=1000, retries=1)
        hub = QuantHub(["BTCUSDT"], binance=ib.Binance(c, c), bybit=venues.Bybit(c), okx=venues.Okx(c), deribit=venues.Deribit(c),
                       onchain=onchain.OnChain(c, c, c), now=ck.now, **kw)
        return hub, net, ck

    def agg(self, t, p, q, maker=False, s="BTCUSDT"):
        return {"e": "aggTrade", "s": s, "T": t, "p": p, "q": q, "m": maker, "a": t}

    def test_ticks_are_checked_against_official_candles_then_replaced(self):
        t = self.T0
        official = [kl(t, "100", "101", "99", "100", "3", "1"), kl(t + MIN, "100", "101", "99", "100", "2.5", "2"),
                    kl(t + 2 * MIN, "100", "101", "99", "101", "1.5", "1"), kl(t + 3 * MIN, "101", "102", "100", "101", "4", "4")]
        hub, _, _ = self.make({"/fapi/v1/klines": [official], "/api/v3/klines": [[]]})
        hub.on_binance_agg(self.agg(t, "100", "3"), "perp")                       # minute 0 : identique à la bougie
        hub.on_binance_agg(self.agg(t + 1000, "100", "1", True), "perp")
        hub.on_binance_agg(self.agg(t + MIN, "100", "3"), "perp")                 # minute 1 : 0,5 de trop (exécution rangée une minute trop tôt)
        hub.on_binance_agg(self.agg(t + MIN + 5, "100", "2", True), "perp")
        hub.on_binance_agg(self.agg(t + 2 * MIN, "101", "1"), "perp")             # minute 2 : 0,5 de moins
        hub.on_binance_agg(self.agg(t + 2 * MIN + 9, "101", "1", True), "perp")
        hub.cvd[("BTCUSDT", "perp")].gap(t + 3 * MIN, t + 3 * MIN + 10)           # minute 3 : coupure du flux
        hub.reconcile()
        st = hub.integrity[("BTCUSDT", "perp")]
        self.assertEqual((st["verified"], st["shifted"], st["repaired"], st["residual"], st["mismatch"]), (1, 2, 1, 0, 0))
        self.assertEqual(st["maxResidual"], units("0.5"))
        bars = hub.cvd[("BTCUSDT", "perp")].bars
        self.assertEqual((bars[t + MIN][flow.BUY], bars[t + 3 * MIN][flow.BUY], bars[t + 3 * MIN][flow.OK]), (units("2.5"), 4 * UNIT, True))
        hub.reconcile()                                                            # une minute n'est contrôlée qu'une fois
        self.assertEqual(hub.integrity[("BTCUSDT", "perp")]["verified"], 1)
        self.assertIn("contrôle spot BTCUSDT", hub.fetched)

    def test_snapshot_with_real_shaped_inputs(self):
        t = self.T0
        official = [kl(t + i * MIN, "100", "101", "99", "100" if i < 4 else "100.5", "6", "4") for i in range(-15, 5)]
        fp = fpm.Footprint(5.0, 0.1)
        for i in range(40):
            fp.add(100.0 + (i % 3) * 5, 0.5, i % 2 == 0, t + i * 1000)
        fp.cover(t - t % 86_400_000, t + 6 * MIN)
        routes = {"/fapi/v1/klines": [official], "/api/v3/klines": [official],
                  "/fapi/v1/openInterest": [{"openInterest": "1000", "time": t}, {"openInterest": "1010", "time": t + 5 * MIN}],
                  "/fapi/v1/premiumIndex": {"time": t, "markPrice": "100.4", "indexPrice": "100.3", "lastFundingRate": "0.0005", "nextFundingTime": t + 8 * 3_600_000}}
        liqs = lambda sym, since: [{"side": "long", "usd": 1000.0}, {"side": "short", "usd": 9000.0}]
        hub, _, ck = self.make(routes, books=lambda s: FakeBook().levels(), footprint=lambda s: fp, liqs=liqs)
        hub.seed()
        hub.poll_fast()
        ck.t += 1
        hub.poll_fast()
        hub.sample_books()
        hub.on_venue_trade("okx_perp", t + 4 * MIN, "100.5", None, 1, "17590.00")                 # contrat en dollars : notionnel exact
        hub.on_venue_trade("coinbase", t + 4 * MIN, "100.6", "0.5", -1)
        hub.on_venue_trade("bybit_perp", t + 4 * MIN, "abc", "1", 1)                               # illisible : erreur notée, rien d'inventé
        s = hub.snapshot("BTCUSDT")
        self.assertTrue(s["ok"])
        w = s["cvd"]["windows"]["5m"]["perp"]
        # la fenêtre de 5 minutes va jusqu'à la minute en cours : 4 minutes fermées sur 5 (aucune transaction en direct dans ce test)
        self.assertEqual((w["buy"], w["sell"], w["delta"], w["imb"], w["cover"]), (24.0, 16.0, 8.0, 0.2, 0.8))
        self.assertEqual(s["integrity"]["perp"]["seeded"], 20)
        self.assertEqual(s["derivs"]["funding"], 0.0005)
        self.assertEqual(s["book"]["walls"]["bid"][0]["price"], 99.5)
        self.assertLess(0, s["book"]["obi"]["0.01"])                                               # le mur acheteur pèse sur le déséquilibre
        self.assertEqual(s["venues"]["5m"]["venues"][0]["id"], "okx_perp")
        self.assertEqual((s["venues"]["5m"]["venues"][0]["buyUsd"], s["venues"]["5m"]["deltaUsd"]), (17590.0, 17590.0 - 50.3))
        self.assertIn("bybit_perp", hub.errors)
        p = s["profile"]["windows"]["day"]
        self.assertEqual((p["poc"], p["volume"], p["cover"] > 0), (100.0, 20.0, True))
        r = s["regime"]["15m"]
        self.assertNotIn("error", r)
        self.assertIn("financement", " ".join(r["notes"]))
        self.assertIn("error", s["options"])                                                       # Deribit absent : une erreur, pas un chiffre
        self.assertEqual(hub.snapshot("ETHUSDT")["ok"], False)
        json.dumps(s)                                                                              # tout est lisible par la page

    def test_everything_down_gives_errors_not_numbers(self):
        hub, _, _ = self.make({})
        hub.seed()
        hub.step(force=True)
        s = hub.snapshot("BTCUSDT")
        self.assertEqual(s["cvd"]["windows"]["1h"]["perp"]["n"], 0)
        self.assertIsNone(s["cvd"]["windows"]["1h"]["perp"]["imb"])
        self.assertIsNone(s["derivs"]["oi"])
        self.assertIn("error", s["regime"]["1h"])
        self.assertIn("error", s["onchain"])
        self.assertTrue(s["sources"]["errors"])

    def test_gaps_from_the_ws_client_mark_minutes_incomplete(self):
        class C:
            connected, connects, last_error, last_msg, url, next_wait = True, 2, "", 0.0, "wss://x", 0.0
            gaps = [(self.T0 + 10_000, self.T0 + 70_000)]
        hub, _, _ = self.make({}, ws_clients=lambda: {"trades": C()})
        hub.on_binance_agg(self.agg(self.T0, "100", "1"), "perp")
        hub._mark_gaps()
        hub._mark_gaps()
        bars = hub.cvd[("BTCUSDT", "perp")].bars
        self.assertEqual((bars[self.T0][flow.OK], bars[self.T0 + MIN][flow.OK]), (False, False))
        self.assertEqual(hub.status()["ws"]["trades"]["gaps"], 1)


class WiringTest(unittest.TestCase):
    def test_exchange_handlers_pass_exact_text(self):
        f = cexflow.CexFeeds(cexflow.CexFlow())
        got = []
        f.tap = lambda *a: got.append(a)
        f.on_okx(json.dumps({"arg": {"channel": "trades", "instId": "BTC-USD-SWAP"}, "data": [{"instId": "BTC-USD-SWAP", "px": "68231.1", "sz": "7", "side": "buy", "ts": "1794620485398"}]}))
        f.on_okx(json.dumps({"arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"}, "data": [{"instId": "BTC-USDT-SWAP", "px": "68299", "sz": "0.21", "side": "sell", "ts": "1794620484219"}]}))
        f.on_bitstamp(json.dumps({"event": "trade", "data": {"amount": 0.00007406, "amount_str": "0.00007406", "price": 68219.44, "price_str": "68219.44",
                                                             "type": 1, "microtimestamp": "1794620446309000", "sell_order_id": 5}}))
        f.on_coinbase(json.dumps({"type": "match", "side": "buy", "size": "0.00047264", "price": "68213.8", "time": "2026-11-14T01:53:52.104000Z"}))
        self.assertEqual(got[0], ("okx_perp", 1794620485398, "68231.1", None, 1, "700.0"))
        self.assertEqual(got[1], ("okx_perp", 1794620484219, "68299", "0.0021", -1, None))
        self.assertEqual(got[2], ("bitstamp", 1794620446309, "68219.44", "0.00007406", -1, None))
        self.assertEqual(got[3][:1] + got[3][2:], ("coinbase", "68213.8", "0.00047264", -1, None))

    def test_live_feed_feeds_the_hub_for_every_pair(self):
        lf = live.LiveFeed("wss://x", ["BTCUSDT", "SOLUSDT"])
        seen = []

        class Q:
            def on_binance_agg(self, x, market):
                seen.append((x["s"], market))
        lf.quant = Q()
        lf.on_trade(json.dumps({"data": {"e": "aggTrade", "s": "SOLUSDT", "p": "150.1", "q": "2", "T": 1, "m": False, "a": 1}}))
        lf.on_spot_trade(json.dumps({"data": {"e": "aggTrade", "s": "BTCUSDT", "p": "68000", "q": "1", "T": 1, "m": True, "a": 1}}))
        self.assertEqual(seen, [("SOLUSDT", "perp"), ("BTCUSDT", "spot")])

    def test_server_and_page(self):
        import server
        self.assertEqual((server.VERSION, server.API_LEVEL), ("45", 45))
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        for needle in ('"/api/quant"', "def default_quant", "def quant_page", "self.quant.start()", "cex.tap = hub.on_venue_trade"):
            self.assertIn(needle, src)
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-layout="quant"', html)
        self.assertIn('<script src="quant.js"></script>', html)
        self.assertNotIn('value="simulated"', html)                                                # plus de données simulées dans les réglages
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("const NEED_API = 45;", app)
        self.assertIn("QUANTV.init(window.LT, qg)", app)
        for f in ("quant.js", "app.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(ROOT / "web" / f)], capture_output=True).returncode, 0, f)


if __name__ == "__main__":
    unittest.main()
