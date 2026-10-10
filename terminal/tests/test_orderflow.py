import json
import tempfile
import time
import unittest
from pathlib import Path

from data import orderflow as of
from data.ws import OP_TEXT, FrameReader
from tests.fakews import FakeWSServer


def ev(U, u, pu, b=(), a=(), E=None):
    return {"e": "depthUpdate", "s": "SOLUSDT", "U": U, "u": u, "pu": pu, "b": [list(x) for x in b], "a": [list(x) for x in a], "E": E or 0}


class BinanceBookTests(unittest.TestCase):
    def snap(self, lid=100):
        return {"lastUpdateId": lid, "bids": [["99.9", "5"], ["99.8", "7"]], "asks": [["100.1", "4"], ["100.2", "0"]]}

    def test_sync_drops_old_events_then_applies_in_order(self):
        calls = []
        bk = of.BinanceBook("SOLUSDT", lambda s: calls.append(s) or self.snap(), threaded=False)
        bk.buffer = [ev(80, 95, 79, b=[("99.9", "1")])]                          # plus ancien que la photo : ignore
        bk.loading = False
        bk.on_event(ev(96, 103, 95, b=[("99.9", "6")], a=[("100.3", "2")]))     # couvre lastUpdateId 100 : premier evenement applique
        self.assertTrue(bk.synced)
        self.assertEqual(calls, ["SOLUSDT"])
        bids, asks = bk.levels()
        self.assertEqual(dict(bids), {99.9: 6.0, 99.8: 7.0})
        self.assertEqual(dict(asks), {100.1: 4.0, 100.3: 2.0})                  # 100.2 a 0 dans la photo : absent
        bk.on_event(ev(104, 110, 103, b=[("99.8", "0")]))                       # quantite 0 : niveau retire
        self.assertEqual(dict(bk.levels()[0]), {99.9: 6.0})

    def test_gap_triggers_a_new_snapshot(self):
        n = []
        bk = of.BinanceBook("SOLUSDT", lambda s: n.append(1) or self.snap(), threaded=False)
        bk.on_event(ev(96, 103, 95))
        self.assertTrue(bk.synced)
        bk.on_event(ev(120, 130, 125))                                           # pu != dernier u : trou
        self.assertEqual(len(n), 2)
        self.assertEqual(bk.resyncs, 1)
        self.assertFalse(bk.synced)                                              # la photo (100) est plus vieille que l'evenement (U=120)
        self.assertEqual(bk.levels(), ([], []))

    def test_snapshot_error_is_reported(self):
        def boom(s):
            raise OSError("reseau")
        bk = of.BinanceBook("SOLUSDT", boom, threaded=False)
        bk.on_event(ev(1, 2, 0))
        self.assertFalse(bk.synced)
        self.assertIn("reseau", bk.error)


class OkxBookTests(unittest.TestCase):
    def data(self, bids, asks, seq, prev=-1, checksum=True):
        d = {"bids": bids, "asks": asks, "seqId": seq, "prevSeqId": prev, "ts": "1"}
        if checksum:
            d["checksum"] = of.okx_checksum([(x[0], x[1]) for x in bids], [(x[0], x[1]) for x in asks])
        return d

    def test_snapshot_update_counts_and_checksum(self):
        bk = of.OkxBook("SOL-USDT-SWAP")
        bk.on_data("snapshot", self.data([["99.9", "10", "0", "3"], ["99.8", "5", "0", "1"]], [["100.1", "8", "0", "4"]], 10), 1.0)
        self.assertTrue(bk.synced)
        upd = {"bids": [["99.9", "0", "0", "0"], ["99.7", "2", "0", "2"]], "asks": [], "seqId": 11, "prevSeqId": 10, "ts": "2"}
        b_after = [("99.8", "5"), ("99.7", "2")]
        upd["checksum"] = of.okx_checksum(b_after, [("100.1", "8")])
        bk.on_data("update", upd, 2.0)
        self.assertTrue(bk.synced and not bk.bad)
        bids, asks = bk.levels()
        self.assertEqual(sorted(bids, reverse=True), [(99.8, 5.0, 1), (99.7, 2.0, 2)])
        self.assertEqual(asks, [(100.1, 8.0, 4)])

    def test_sequence_gap_and_bad_checksum_ask_for_resubscription(self):
        bk = of.OkxBook("SOL-USDT-SWAP")
        bk.on_data("snapshot", self.data([["99.9", "10", "0", "3"]], [["100.1", "8", "0", "4"]], 10), 1.0)
        bk.on_data("update", {"bids": [], "asks": [], "seqId": 13, "prevSeqId": 12}, 2.0)
        self.assertTrue(bk.bad)
        bk.on_data("snapshot", self.data([["99.9", "10", "0", "3"]], [["100.1", "8", "0", "4"]], 20), 3.0)
        bk.on_data("update", {"bids": [["99.9", "11", "0", "4"]], "asks": [], "seqId": 21, "prevSeqId": 20, "checksum": 12345}, 4.0)
        self.assertTrue(bk.bad)
        self.assertTrue(bk.check)

    def test_checksum_is_disabled_when_even_fresh_snapshots_never_match(self):
        bk = of.OkxBook("SOL-USDT-SWAP")
        for k in range(3):
            d = self.data([["99.9", "10", "0", "3"]], [["100.1", "8", "0", "4"]], 10 + k)
            d["checksum"] = 1
            bk.on_data("snapshot", d, 1.0)
        self.assertFalse(bk.check)                                               # format different : on cesse de verifier, sans boucle
        self.assertIn("désactivée", bk.error)

    def test_checksum_format(self):
        self.assertEqual(of.okx_checksum([("3366.1", "7")], [("3366.8", "9")]),
                         of._signed(__import__("zlib").crc32(b"3366.1:7:3366.8:9")))


class TapeTests(unittest.TestCase):
    def test_speed_big_trades_footprint_and_reset(self):
        clock = [1000.0]
        tp = of.Tape("SOLUSDT", now=lambda: clock[0])
        for i in range(50):
            clock[0] = 1000.0 + i * 0.1
            tp.on_trade(150.0 + (i % 3) * 0.01, 2.0, i % 2 == 0, int(clock[0] * 1000), int(clock[0] * 1000) - 30, clock[0])
        sp = tp.speed()
        self.assertEqual(sp["perSec"], 10.0)                                    # 50 transactions en 5 secondes
        self.assertAlmostEqual(sp["buyShare"], 0.5, delta=0.05)
        self.assertEqual(tp.latency(), 30)
        tp.on_trade(150.0, 1000.0, False, 1_005_000, None, 1005.0)            # 150 000 $ > plancher SOL (50 000 $)
        self.assertEqual(tp.big[-1]["side"], "buy")
        self.assertEqual(tp.big[-1]["usd"], 150000)
        self.assertEqual(len(tp.big), 1)
        self.assertAlmostEqual(tp.foot[150.0][0], 1000.0 + 2.0 * 8)            # achats agressifs a 150,00
        tp.reset()
        self.assertEqual(tp.foot, {})

    def test_threshold_adapts_to_the_market(self):
        tp = of.Tape("XYZUSDT", now=lambda: 1.0)
        for i in range(2000):
            tp.on_trade(10.0, 100.0 + (i % 100) * 50, False, i, None, 1.0)   # 1 000 a 50 500 $
        self.assertGreater(tp.thr, 40000)                                     # 99,7e centile, au-dessus du plancher divise par deux


class LadderTests(unittest.TestCase):
    def test_buckets_around_center(self):
        rows = of.ladder_rows(0.5, 100.2, 4, bids=[(99.9, 2.0), (99.6, 1.0), (98.0, 9.0)], asks=[(100.4, 3.0), (100.9, 1.0)],
                              okx_bids=[(99.9, 1.0, 4)], okx_asks=[(100.6, 1.0, 2)], foot={100.1: [5.0, 1.0]})
        self.assertEqual([r[0] for r in rows], [101.0, 100.5, 100.0, 99.5, 99.0])
        r = {x[0]: x[1:] for x in rows}
        self.assertEqual(r[99.5][0], 3.0)                                      # 99,9 et 99,6 dans la tranche 99,5 - 100
        self.assertEqual(r[100.0][1], 3.0)
        self.assertEqual(r[100.5][1], 1.0)
        self.assertEqual(r[99.5][2], 4)
        self.assertEqual(r[100.5][3], 2)
        self.assertEqual(r[100.0][4:], [5.0, 1.0])
        self.assertNotIn(97.5, r)                                              # hors fenetre


class SimFlowTests(unittest.TestCase):
    def test_simulated_ladder(self):
        clock = [100.0]
        f = of.SimFlow(["SOLUSDT"], lambda s: 150.0, now=lambda: clock[0])
        clock[0] = 103.0
        out = f.ladder("SOLUSDT", 0.05, 40)
        self.assertTrue(out["ready"] and out["simulated"])
        self.assertEqual(len(out["rows"]), 41)
        self.assertTrue(any(r[1] > 0 for r in out["rows"]) and any(r[2] > 0 for r in out["rows"]))
        self.assertGreater(out["tape"]["n60"], 30)


class LiveSocketsTests(unittest.TestCase):
    """De bout en bout avec de faux serveurs : profondeur Binance (route /public) et carnet OKX (abonnement, ping)."""

    def test_binance_depth_and_okx_books(self):
        got = []

        def binance(path, send, alive, conn):
            got.append(path)
            for k, (U, u, pu) in enumerate([(96, 103, 95), (104, 110, 103)]):
                send(OP_TEXT, json.dumps({"stream": "solusdt@depth@100ms", "data": ev(U, u, pu, b=[("99.9", str(6 + k))], E=int(time.time() * 1000))}).encode())
            while alive():
                time.sleep(0.05)

        subs = []

        def okx(path, send, alive, conn):
            rd = FrameReader()
            conn.settimeout(0.2)
            snap = {"arg": {"channel": "books", "instId": "SOL-USDT-SWAP"}, "action": "snapshot",
                    "data": [{"bids": [["99.9", "10", "0", "3"]], "asks": [["100.1", "8", "0", "4"]], "seqId": 1, "prevSeqId": -1}]}
            snap["data"][0]["checksum"] = of.okx_checksum([("99.9", "10")], [("100.1", "8")])
            sent = False
            while alive():
                try:
                    data = conn.recv(4096)
                except OSError:
                    data = b""
                if data:
                    rd.feed(data)
                    for _fin, op, payload in rd.frames():
                        subs.append(payload.decode())
                if subs and not sent:
                    send(OP_TEXT, json.dumps(snap).encode())
                    sent = True
                time.sleep(0.02)

        s1, s2 = FakeWSServer(binance), FakeWSServer(okx)
        try:
            flow = of.OrderFlow(["SOLUSDT"], f"ws://127.0.0.1:{s1.port}/public", f"ws://127.0.0.1:{s2.port}/ws/v5/public",
                                lambda s: {"lastUpdateId": 100, "bids": [["99.8", "7"]], "asks": [["100.1", "4"]]})
            flow.start()
            t0 = time.time()
            while time.time() - t0 < 6:
                lad = flow.ladder("SOLUSDT", 0.1, 10)
                if lad["book"]["synced"] and lad["orders"]["synced"] and dict(flow.books["SOLUSDT"].levels()[0]).get(99.9) == 7.0:
                    break
                time.sleep(0.05)
            flow.stop()
            self.assertEqual(got[0], "/public/stream?streams=solusdt@depth@100ms")
            self.assertTrue(lad["book"]["synced"])
            self.assertEqual(dict(flow.books["SOLUSDT"].levels()[0]), {99.8: 7.0, 99.9: 7.0})
            self.assertTrue(lad["orders"]["synced"])
            self.assertIn('"op": "subscribe"', subs[0])
            self.assertIn("SOL-USDT-SWAP", subs[0])
            r = {x[0]: x for x in lad["rows"]}
            self.assertEqual(r[99.9][3], 3)                                     # nombre d'ordres OKX a 99,9
        finally:
            s1.close()
            s2.close()


class FlowEndpointTests(unittest.TestCase):
    def test_api_flow_in_simulated_mode(self):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=1_759_104_000_000), make_hub=lambda c, s: None)
            app.service.refresh_all()
            self.assertIsInstance(app.flow, of.SimFlow)
            out = app.flow.ladder("BTCUSDT", 10.0, 30)
            self.assertTrue(out["ready"])
            json.dumps(out)
            cfg2 = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0, orderflow_on=False)
            app2 = App(cfg2, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=1_759_104_000_000), make_hub=lambda c, s: None)
            self.assertIsNone(app2.flow)



class SessionProfileTests(unittest.TestCase):
    def test_volume_spread_buyers_value_area_and_marks(self):
        from engine import sessionvp
        from engine.atr import Candle
        bars = [Candle(0, 100, 101, 99, 100.5, 10.0, 8.0), Candle(1, 100.5, 100.6, 100.4, 100.5, 30.0, 6.0), Candle(2, 100, 100.2, 99.8, 100, 5.0, 2.5)]
        r = sessionvp.build(bars, target_rows=20)
        self.assertEqual(r["step"], 0.1)
        self.assertAlmostEqual(sum(x[1] for x in r["rows"]), 45.0)
        self.assertAlmostEqual(sum(x[2] for x in r["rows"]), 16.5)
        self.assertTrue(100.4 <= r["poc"] <= 100.6)                           # la bougie de 30 de volume sur 100,4 - 100,6
        self.assertTrue(r["val"] <= r["poc"] <= r["vah"])
        self.assertTrue(r["marks"] and all(dv < 0 for _, dv in r["marks"]))  # la ou les vendeurs dominent (6 achats sur 30)
        self.assertAlmostEqual(r["buyShare"], 16.5 / 45)
        self.assertIsNone(sessionvp.build([Candle(0, 1, 1, 1, 1, 0.0, 0.0)]))
        self.assertEqual(sessionvp.nice_step(0.037), 0.05)
        self.assertEqual(sessionvp.nice_step(230), 250)


if __name__ == "__main__":
    unittest.main()
