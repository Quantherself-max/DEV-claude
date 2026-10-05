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
        self.assertEqual(v["cap"], 5)
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
        rank = lambda x: (0 if x["eligible"] else 1 if not x["gates"] else 2, -x["score"])
        self.assertEqual([rank(x) for x in s["ideas"]], sorted(rank(x) for x in s["ideas"]))     # celles qui passent les filtres d'abord, puis par score
        text = sg.to_text(i, i["desc"], 1, 3)
        self.assertIsNone(BANNED.search(text), BANNED.search(text))
        self.assertTrue(all(len(x) < 3900 for x in sg.split_message(text)))
        self.assertIn("PRUDENCE", text)                                       # jamais tronque
        self.assertIn(i["desc"]["headline"], text)
        if i["side"] == "long":
            self.assertLess(i["stop"], i["entry"] < i["tp1"] and i["entry"])
        else:
            self.assertGreater(i["stop"], i["entry"])

    def test_price_pools_sweeps_and_detailed_cvd_are_in_the_state(self):
        st = self.svc.get_state("BTCUSDT", "1h")
        pp = st["liquidity"]["pricePools"]
        self.assertTrue(pp, "des poches visibles dans le prix existent toujours (plus haut / plus bas de la veille, creux, sommets)")
        for p in pp:
            self.assertIn(p["side"], ("long", "short"))
            self.assertGreater(p["hi"], p["lo"])
            self.assertTrue(p["src"])
            self.assertFalse(p["magnet"])
        self.assertTrue(any(l["name"].endswith("(prix)") for l in st["levels"]))
        self.assertTrue(all(l["family"] is None for l in st["levels"] if l["name"].endswith("(prix)")))
        cv = st["context"]["cvd"]
        for k in ("swingDiv", "absorb", "imb1", "imb4", "imb24"):
            self.assertIn(k, cv)
        json.dumps(st["context"])
        names = " ".join(p["src"] for p in pp)
        self.assertIsNone(re.search(r"\b(PDL|PDH|PWL|PWH|PML|PMH)\b", names), names)

    def test_period_profiles_use_five_minute_candles_when_they_cover_the_period(self):
        from engine import vpx
        m = self.svc.markets["BTCUSDT"]
        self.assertTrue(m.store.m5_old, "les bougies 5 min plus anciennes (70 jours) sont chargees")
        m5 = m.store.fine_m5()
        self.assertTrue(all(m5[i].t < m5[i + 1].t for i in range(len(m5) - 1)))
        self.assertGreater(m5[-1].t - m5[0].t, 60 * 86_400_000)
        st = self.svc.get_state("BTCUSDT", "1h")
        now = self.svc.source.now_ms()
        ws = sg.week_start(now)
        lv = {l["name"]: l["price"] for l in st["levels"]}
        closed = [k for k in m5 if k.t + 300_000 <= now]
        ref = vpx.build(closed, ws, now + 300_000, rows_cap=160, hvn_n=1)
        self.assertIn("wPOC", lv)
        self.assertAlmostEqual(lv["wPOC"], ref["poc"], places=6)
        pw = vpx.build(closed, ws - 7 * 86_400_000, ws, rows_cap=160, hvn_n=1)
        self.assertIn("pwPOC", lv)
        self.assertAlmostEqual(lv["pwPOC"], pw["poc"], places=6)

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
        self.assertIn(len(notifier.sent), (1, 2))                              # une idee longue part en deux messages au plus, sans rien perdre
        self.assertIn("Idée de trade 1/5", notifier.sent[0])
        self.assertIn("PRUDENCE", "\n".join(notifier.sent))
        self.assertTrue(all(len(m) < 4096 for m in notifier.sent))
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
