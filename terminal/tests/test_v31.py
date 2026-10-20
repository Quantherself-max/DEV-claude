"""V31 : nouvelle stratégie (prix, intérêt ouvert et CVD lus sur la liquidité et les VWAP), qui remplace l'ancienne note de confluence."""
import json
import tempfile
import unittest
from pathlib import Path

from config import Config
from data import reports as reports_mod
from engine import fine
from engine import flowstrat as fs
from engine.atr import Candle
from server import App

H = 3_600_000
ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def bars5(rows, t0=0):
    """[(haut, bas, clôture)] -> bougies 5 minutes."""
    b = fine.Bars(300_000)
    for k, (h, l, c) in enumerate(rows):
        b.append(t0 + k * 300_000, c, h, l, c, 1.0, 0.0)
    return b.build_cum()


class RuleTests(unittest.TestCase):
    def test_flat_thresholds(self):
        self.assertIsNone(fs.flow_state(1, 100.0, 100.4, 50.0, 1000.0))              # intérêt ouvert +0,4 % : plat
        self.assertIsNone(fs.flow_state(1, 100.0, 101.0, 5.0, 1000.0))               # CVD à 0,5 % du volume : plat
        self.assertEqual(fs.flow_state(-1, 100.0, 101.0, -20.0, 1000.0), (-1, 1, -1))
        self.assertIsNone(fs.flow_state(1, None, 101.0, 20.0, 1000.0))

    def test_one_principle_for_the_eight_combinations(self):
        self.assertEqual(len(fs.ORDER), 8)
        self.assertEqual(set(fs.ORDER), set(fs.STATES))
        self.assertEqual(set(fs.ORDER), set(fs.ACTION))
        for st in fs.ORDER:
            d = fs.reaction(st)
            if st[1] > 0:
                self.assertEqual(d, st[2])                                            # argent neuf : on suit le camp agressif
                self.assertTrue(fs.ACTION[st].startswith("ACHAT" if d > 0 else "VENTE"))
                self.assertEqual(fs.react_of(st), "follow" if st[2] == st[0] else "fade")
            else:
                self.assertEqual(d, 0)
                self.assertTrue(fs.ACTION[st].startswith("RIEN"))
        self.assertEqual(fs.parse_skey(fs.skey((1, -1, 1))), (1, -1, 1))
        self.assertNotIn("CVD", fs.words((1, 1, -1)))

    def test_geometry_and_three_r_target(self):
        e = {"price": 100.0, "atr": 2.0, "h": 101.0, "l": 99.5, "up": [104.0], "dn": [95.0], "lvl": 99.8}
        stop, tp, kind = fs.geometry(1, 100.0, 2.0, 101.0, 99.5, [104.0], [])
        self.assertEqual(stop, 98.0)                                                 # moins de 1 ATR sous l'entrée : stop porté à 1 ATR
        etype, entry, stop, tp, kind = fs.plan(e, 1, "marché|3R")
        self.assertEqual((etype, entry, stop, tp, kind), ("marché", 100.0, 98.0, 106.0, "3R"))
        self.assertIsNone(fs.geometry(-1, 100.0, 1.0, 106.0, 99.0, [], []))          # stop à plus de 4 ATR : pas de trade
        etype, entry, *_ = fs.plan(e, 1, "limite|pool")
        self.assertEqual((etype, entry), ("limite", 99.8))

    def test_play_market_and_limit(self):
        b = bars5([(100.5, 99.5, 100.0)] * 2 + [(101.0, 99.0, 100.0), (103.5, 100.0, 103.0), (103.0, 102.0, 102.5)])
        s = fs.play(b, 300_000, 1, "marché", 0, 97.0, 103.0, 0, 72)
        self.assertEqual((s["result"], s["entry_kind"]), ("tp", "taker"))
        s = fs.play(b, 300_000, 1, "limite", 99.0, 97.0, 103.0, 12, 72)
        self.assertEqual((s["result"], s["fill_px"], s["entry_kind"]), ("tp", 99.0, "maker"))
        self.assertAlmostEqual(s["r_gross"], 2.0)
        s = fs.play(b, 300_000, 1, "limite", 98.0, 97.0, 103.0, 12, 72)
        self.assertEqual(s["result"], "missed")                                     # objectif atteint avant l'exécution : annulé

    def test_confirmation_counts_same_side_signals_of_the_last_24_hours(self):
        st_b, st_s, st_0 = (1, 1, 1), (1, 1, -1), (1, -1, 1)
        ev = [{"t": 0, "st": st_b}, {"t": 4 * H, "st": st_s}, {"t": 8 * H, "st": st_0}, {"t": 12 * H, "st": st_b}, {"t": 40 * H, "st": st_b}]
        fs.confirmations(ev)
        self.assertEqual([e["confirm"] for e in ev], [0, 0, 0, 1, 0])

    def test_verdict(self):
        ok = {"label": "SOL", "strategy": {"oos": {"n": 300, "expR": 0.09}, "control": {"pctOos": 0.95}}}
        self.assertTrue(fs.verdict(ok)["validated"])
        bad = {"label": "BTC", "strategy": {"oos": {"n": 300, "expR": 0.05}, "control": {"pctOos": 0.6}}}
        self.assertFalse(fs.verdict(bad)["validated"])


class ReportTests(unittest.TestCase):
    def test_shipped_reports(self):
        dirs = [ROOT / "reports"]
        sol, btc, eth = (reports_mod.load(dirs, k, "flow") for k in ("SOL", "BTC", "ETH"))
        self.assertTrue(fs.verdict(sol)["validated"])                                 # validée sur SOL seulement
        self.assertFalse(fs.verdict(btc)["validated"])
        self.assertFalse(fs.verdict(eth)["validated"])                                # contrôle à l'aveugle
        for r in (sol, btc, eth):
            self.assertEqual(len(r["matrix"]), 16)                                    # 8 combinaisons x 2 lieux
            self.assertEqual(r["rules"]["confirmN"], 1)
            self.assertEqual(r["tf"], "4h")
        self.assertEqual(sol["exit"], "marché|3R")                                  # la sortie du direct : choisie sur l'apprentissage de SOL
        self.assertIn("flow", reports_mod.KINDS)
        self.assertTrue(any(x["kind"] == "flow" for x in reports_mod.summaries(dirs)))


class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("SOLUSDT",), data_dir=tempfile.mkdtemp(), port=0, heatmap_days=40), env_path=None)
        cls.app.service.refresh_all()

    def test_live_signals_use_the_same_rules(self):
        s = self.app.service.signals("SOLUSDT")
        json.dumps(s)
        self.assertTrue(s["ready"] and s["warm"])
        self.assertTrue(s["validated"])                                              # rapport SOL livré : validé
        self.assertEqual(s["flow"]["t"] % (4 * H), 0)                                 # lecture à la clôture 4 heures
        self.assertEqual(s["flow"]["next"] - s["flow"]["t"], 4 * H)
        for r in s["recent"]:
            self.assertIn(r["place"], fs.PLACES)
            if r["side"]:
                self.assertEqual({"long": 1, "short": -1}[r["side"]], fs.reaction(fs.parse_skey(r["state"])))
        for i in s["ideas"]:
            self.assertEqual(i["eligible"], i["confirm"] >= fs.CONFIRM_N)

    def test_idea_text_has_no_abbreviation(self):
        from engine import signals as sg
        from tests.test_signals import BANNED
        e = {"t": 8 * H, "tf": "4h", "place": "liq", "st": (-1, 1, -1), "price": 100.0, "atr": 2.0, "h": 101.0, "l": 99.0, "o": 100.5,
             "up": [104.0], "dn": [94.0], "lvl": 99.2, "src": "plus bas de la veille", "oiChg": 0.012, "cvdImb": -0.04, "ageH": 20, "confirm": 1}
        i = fs.idea(e, "SOLUSDT", 100.2, True, "SOL : validée.", 10.0)
        self.assertEqual((i["side"], i["eligible"], i["entryType"]), ("short", True, "marché"))
        self.assertAlmostEqual(i["tp1"], 100.0 - 3 * (i["stop"] - 100.0))
        txt = sg.to_text(i, i["desc"], 1, 5)
        self.assertIsNone(BANNED.search(txt), BANNED.search(txt))
        self.assertIsNone(fs.idea({**e, "st": (-1, -1, -1)}, "SOLUSDT", 100.0, True, None))    # intérêt ouvert en baisse : pas d'idée
        e2 = {**e, "confirm": 0}
        self.assertFalse(fs.idea(e2, "SOLUSDT", 100.0, True, None)["eligible"])                  # pas encore confirmée


class PageTests(unittest.TestCase):
    SIG = (WEB / "signals.js").read_text(encoding="utf-8")
    BT = (WEB / "backtest.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")

    def test_pages(self):
        for k in ("function flowBox(", "function reactTable(", "function recentList("):
            self.assertIn(k, self.SIG)
        self.assertNotIn("function validation(", self.SIG)                           # l'ancien rejeu n'est plus affiché
        for k in ("function flowVerdict(", "function flowMatrix(", "Anciennes mesures"):
            self.assertIn(k, self.BT)
        self.assertIn("NEED_API = 32", self.APP)


if __name__ == "__main__":
    unittest.main()
