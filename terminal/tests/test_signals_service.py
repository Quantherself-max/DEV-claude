import json
import re
import tempfile
import unittest
from unittest import mock

import service as service_mod
from alerts.trades import TradeDesk
from config import Config
from data.simulated import SimulatedSource
from engine import flowstrat
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

    def test_old_replay_is_gone_and_the_reaction_table_is_served(self):
        self.assertIsNone(self.svc.markets["BTCUSDT"].sigval)                      # V31 : l'ancien rejeu de la note de confluence n'est plus calcule
        s = self.svc.signals("BTCUSDT")
        self.assertEqual([r["state"] for r in s["table"]], [flowstrat.skey(st) for st in flowstrat.ORDER])
        self.assertEqual(sum(1 for r in s["table"] if r["side"]), 4)              # intérêt ouvert en hausse : 4 réactions ; en baisse : rien
        self.assertTrue(s["verdict"])

    def test_signals_payload_shape_and_plain_text(self):
        s = self.svc.signals("BTCUSDT")
        self.assertTrue(s["ready"])
        self.assertTrue(s["warm"])
        self.assertTrue(s["ideas"], "le scenario simule doit produire au moins une idee")
        json.dumps(s)                                              # tout est serialisable
        for k in ("ideas", "rejected", "minScore", "maxWeek", "verdict", "validated", "flow", "recent", "table", "price"):
            self.assertIn(k, s)
        i = s["ideas"][0]
        for k in ("side", "kind", "score", "grade", "comps", "entry", "stop", "tp1", "rr1", "desc", "key", "eligible", "hold", "warn", "probs", "st", "state", "place"):
            self.assertIn(k, i)
        self.assertEqual(sum(c["max"] for c in i["comps"]), 100)
        self.assertEqual(i["entryType"], "marché")
        self.assertAlmostEqual(i["rr1"], 3.0, places=2)                           # objectif à 3 fois le risque (sortie mesurée)
        self.assertGreaterEqual(abs(i["entry"] - i["stop"]), i["atr"] - 1e-6)     # au moins 1 ATR de la bougie 4 heures
        self.assertEqual(i["side"], {1: "long", -1: "short"}[flowstrat.reaction(flowstrat.parse_skey(i["state"]))])
        text = sg.to_text(i, i["desc"], 1, 3)
        self.assertIsNone(BANNED.search(text), BANNED.search(text))
        self.assertTrue(all(len(x) < 3900 for x in sg.split_message(text)))
        self.assertIn("PRUDENCE", text)                                       # jamais tronque
        self.assertIn(i["desc"]["headline"], text)
        if i["side"] == "long":
            self.assertLess(i["stop"], i["entry"])
            self.assertLess(i["entry"], i["tp1"])
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

    def test_live_view_of_the_users_strategy(self):
        v = self.svc.strategy("BTCUSDT")
        self.assertTrue(v["ready"])
        json.dumps(v)
        self.assertGreaterEqual(len(v["levels"]), 6)
        names = {l["name"] for l in v["levels"]}
        self.assertIn("VWAP du mois", names)
        self.assertIn("VWAP de la semaine", names)
        for l in v["levels"]:
            self.assertEqual(l["side"], "below" if l["value"] < v["price"] else "above")
            self.assertIn(l["grp"], ("W", "M"))
        self.assertTrue(set(v["bars"]) <= {"1h", "4h"} and "1h" in v["bars"])
        b = v["bars"]["1h"]
        self.assertLessEqual(b["l"], b["h"])
        self.assertEqual(b["t"] % 3_600_000, 0)
        for t in b["triggers"]:
            self.assertTrue(b["l"] <= t["level"] <= b["h"])
            self.assertEqual(t["dir"], 1 if b["c"] > t["level"] else -1)
        for k in ("cw", "pw", "cm", "pm"):
            self.assertIn(k, v["vp"])
        self.assertTrue(all(p["price"] > v["price"] for p in v["pools"]["up"]))
        self.assertTrue(all(p["price"] < v["price"] for p in v["pools"]["dn"]))
        self.assertTrue(all(p["distAtr"] > 0 for p in v["pools"]["up"] + v["pools"]["dn"]))
        sw = v["swing"]
        self.assertEqual(sw["pct"], 0.05)
        for a in sw["anchors"]:
            self.assertIn(a["kind"], ("H", "L"))
            self.assertLessEqual(a["ageD"], 30.01)
            self.assertGreater(a["tc"], a["t"])
            self.assertEqual(a["side"], "below" if a["value"] < v["price"] else "above")
            if a["touch"]:
                self.assertIn(a["touch"]["dir"], (-1, 1))
        self.assertEqual([a["t"] for a in sw["anchors"]], sorted((a["t"] for a in sw["anchors"]), reverse=True))
        with self.assertRaises(KeyError):
            self.svc.strategy("XXX")

    def test_a_pair_without_a_validated_strategy_never_sends(self):
        s = self.svc.signals("BTCUSDT")
        self.assertFalse(s["validated"])                                         # le rapport livre pour le BTC ne valide pas la strategie
        self.assertTrue(s["ideas"])
        for i in s["ideas"]:
            self.assertFalse(i["eligible"])
            self.assertTrue(any("non validée" in g for g in i["gates"]))

    def test_trade_cycle_sends_an_eligible_idea_and_follows_it(self):
        notifier = Fake()
        self.app.desk = TradeDesk(self.app.cfg, notifier)
        self.app.desk.dir = __import__("pathlib").Path(self.tmp.name) / "desk_test"          # journal isole
        self.app.desk.file = self.app.desk.dir / "trades.json"
        self.app.desk.trades = []
        self.svc._sig_cache.clear()
        with mock.patch.object(service_mod.flowstrat, "verdict", lambda rep: {"validated": True, "text": "validée (test)"}):
            self.app.trade_cycle(self.svc, ["BTCUSDT"])
        self.svc._sig_cache.clear()
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
