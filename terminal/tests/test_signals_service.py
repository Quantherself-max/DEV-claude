import json
import re
import tempfile
import unittest
from unittest import mock

import service as service_mod
from alerts.trades import TradeDesk
from config import Config
from data.simulated import SimulatedSource
from engine import signals as sg
from server import App
from tests.test_data_server import NOW
from tests.test_signals import BANNED


class Fake:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True, "ok"


class ServiceSignalsTests(unittest.TestCase):
    """Chaine complete sur les donnees simulees (instant fixe) : niveaux -> idees -> score -> textes -> suivi."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=cls.tmp.name, port=0, signal_min_struct=4.5, signal_min_score=30.0)
        cls.app = App(cfg, env_path=__import__("pathlib").Path(cls.tmp.name) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW))
        cls.svc = cls.app.service
        cls.svc.refresh_all()
        cls.svc.compute_stats("BTCUSDT")                         # synchrone : probabilites, biais et rejeu historique

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_replay_validation_is_computed_with_the_stats(self):
        m = self.svc.markets["BTCUSDT"]
        self.assertIsNotNone(m.stats)
        v = m.sigval
        self.assertTrue(v["ready"])
        self.assertEqual(v["cap"], 3)
        self.assertEqual(len(v["tiers"]), 3)
        self.assertNotIn("rejeu BTCUSDT", self.svc.errors)

    def test_signals_payload_shape_and_plain_text(self):
        s = self.svc.signals("BTCUSDT")
        self.assertTrue(s["ready"])
        self.assertTrue(s["warm"])
        self.assertTrue(s["ideas"], "le scenario simule doit produire au moins une idee")
        json.dumps(s)                                              # tout est serialisable
        for k in ("ideas", "rejected", "minScore", "maxWeek", "minStruct", "validation", "price", "atr"):
            self.assertIn(k, s)
        i = s["ideas"][0]
        for k in ("side", "kind", "score", "grade", "comps", "entry", "stop", "tp1", "rr1", "desc", "key", "eligible", "hold", "warn", "probs", "st", "news"):
            self.assertIn(k, i)
        self.assertEqual(sum(c["max"] for c in i["comps"]), 100)
        self.assertGreater(i["rr1"], 1.4)
        self.assertGreaterEqual(abs(i["entry"] - i["stop"]), 1.5 * s["atr"] - 1e-9)
        scores = [x["score"] for x in s["ideas"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        text = sg.to_text(i, i["desc"], 1, 3)
        self.assertIsNone(BANNED.search(text), BANNED.search(text))
        self.assertLess(len(text), 3900)
        self.assertIn(i["desc"]["headline"], text)
        if i["side"] == "long":
            self.assertLess(i["stop"], i["entry"] < i["tp1"] and i["entry"])
        else:
            self.assertGreater(i["stop"], i["entry"])

    def test_announcement_in_the_next_hours_puts_the_idea_on_hold(self):
        s = self.svc.signals("BTCUSDT")
        held = [i for i in s["ideas"] if i["hold"]]
        self.assertTrue(held, "une annonce majeure est proche dans le scenario simule")
        self.assertFalse(any(i["eligible"] for i in held))
        self.assertIn("annonce", held[0]["hold"][0])

    def test_trade_cycle_sends_an_eligible_idea_and_follows_it(self):
        notifier = Fake()
        self.app.desk = TradeDesk(self.app.cfg, notifier)
        self.app.desk.dir = __import__("pathlib").Path(self.tmp.name) / "desk_test"          # journal isole
        self.app.desk.file = self.app.desk.dir / "trades.json"
        self.app.desk.trades = []
        orig = sg.score_idea

        def no_hold(idea, c, o=None):
            r = orig(idea, c, o)
            r["hold"], r["gates"] = [], []
            return r
        self.svc._sig_cache.clear()
        with mock.patch.object(service_mod.signals_engine, "score_idea", no_hold):
            self.app.trade_cycle(self.svc, ["BTCUSDT"])
        self.assertEqual(len(self.app.desk.trades), 1)
        self.assertEqual(len(notifier.sent), 1)
        self.assertIn("Idée de trade 1/3", notifier.sent[0])
        tr = self.app.desk.trades[0]
        self.assertIn(tr["status"], ("pending", "active"))
        self.assertLess(self.svc.recent_m5("BTCUSDT", NOW - 3_600_000)[0][0], NOW)
        m5 = self.svc.recent_m5("BTCUSDT", tr["created"])
        self.assertTrue(all(len(c) == 4 for c in m5))
        pub = self.app.desk.public(NOW)
        self.assertEqual(pub["week"]["sent"], 1)
        self.app.desk.trades = []

    def test_disabled_signals_return_not_ready(self):
        self.svc.cfg.signal_on = False
        try:
            self.assertFalse(self.svc.signals("BTCUSDT")["ready"])
        finally:
            self.svc.cfg.signal_on = True

    def test_new_anchored_vwaps_are_levels_with_anchor_and_group(self):
        st = self.svc.get_state("BTCUSDT", "1h")
        av = [l for l in st["levels"] if l["kind"] == "avwap"]
        names = {l["name"] for l in av}
        self.assertTrue(any(n.startswith("AVWAP bas") or n.startswith("AVWAP haut") for n in names), names)
        for l in av:
            self.assertTrue(l["anchor"])
            self.assertTrue(l["group"].startswith("aVWAP"))
        self.assertEqual(len({l["group"] for l in av}), len(av))


if __name__ == "__main__":
    unittest.main()
