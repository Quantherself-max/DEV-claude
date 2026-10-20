"""V32 : seulement les divergences prix / intérêt ouvert / CVD, en journalier, 4 heures et 1 heure."""
import json
import tempfile
import unittest
from pathlib import Path

from config import Config
from data import reports as reports_mod
from engine import fine
from engine import flowstrat as fs
from server import App

H = 3_600_000
ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


class _DS:
    def __init__(self, b1h):
        self.b1h = b1h


def hours(rows, t0=0):
    """[(haut, bas, clôture, delta)] -> bougies 1 heure (volume 100)."""
    b = fine.Bars(H)
    for k, (h, l, c, d) in enumerate(rows):
        b.append(t0 + k * H, c, h, l, c, 100.0, d)
    return b.build_cum()


class DivergenceTests(unittest.TestCase):
    def test_a_new_high_is_compared_with_the_previous_confirmed_high(self):
        rows = [(100.0, 99.0, 99.5, 0.0)] * 4 + [(101.0, 99.5, 100.5, 10.0), (105.0, 100.0, 104.0, 10.0), (103.0, 101.0, 102.0, -10.0)]
        rows += [(102.0, 100.0, 101.0, -10.0)] * 3 + [(106.0, 101.0, 105.5, -30.0)]             # nouveau plus haut, vendeurs agressifs
        b = hours(rows)
        oi = [1000.0] * 5 + [1000.0] * 5 + [1020.0]                                             # intérêt ouvert +2 % depuis le sommet
        ev = fs.build_divergences(_DS(b), oi, 0, 10 ** 15, "1h")
        self.assertEqual(len(ev), 1)
        e = ev[0]
        self.assertEqual((e["lvl"], e["st"], e["src"]), (105.0, (1, 1, -1), "sommet 1 heure"))
        self.assertEqual(e["t"], 11 * H)                                                         # connu à la clôture, rien du futur
        self.assertAlmostEqual(e["oiChg"], 0.02)
        self.assertLess(e["cvdImb"], 0)
        self.assertEqual(fs.reaction(e["st"]), -1)                                               # argent neuf, vendeurs agressifs : vente

    def test_a_high_is_only_known_once_confirmed(self):
        rows = [(100.0, 99.0, 99.5, 0.0)] * 4 + [(105.0, 100.0, 104.0, 10.0), (103.0, 101.0, 102.0, 0.0), (106.0, 102.0, 105.0, 10.0)]
        ev = fs.build_divergences(_DS(hours(rows)), [1000.0] * 7, 0, 10 ** 15, "1h")
        self.assertEqual(ev, [])                                                                 # le sommet n'était pas encore confirmé

    def test_levels(self):
        self.assertEqual(fs.div_level({"expR": 0.2}, {"expR": 0.1}, 0.95), "validé")
        self.assertEqual(fs.div_level({"expR": 0.2}, {"expR": 0.1}, 0.78), "prometteur")
        self.assertEqual(fs.div_level({"expR": 0.08}, {"expR": 0.02}, 0.9), "non validé")
        self.assertEqual(fs.div_level({"expR": -0.05}, {"expR": 0.2}, 0.99), "non validé")
        self.assertEqual(fs.DIV_TFS, ("1d", "4h", "1h"))                                         # rien en dessous de l'heure


class ReportTests(unittest.TestCase):
    def test_shipped_report(self):
        rep = reports_mod.load([ROOT / "reports"], "ALL", "div")
        self.assertEqual(rep["kind"], "divergences")
        self.assertEqual(set(rep["assets"]), {"SOL", "BTC", "ETH"})
        self.assertEqual(set(rep["tfs"]), {"1d", "4h", "1h"})
        lv = {tf: fs.tf_status(rep, tf)["level"] for tf in fs.DIV_TFS}
        self.assertEqual(lv, {"1d": "prometteur", "4h": "non validé", "1h": "non validé"})
        for tf, r in rep["tfs"].items():
            self.assertEqual(len(r["matrix"]), 8)
            self.assertIn(r["exit"], fs.DIV_EXITS)
        self.assertLess(rep["tfs"]["1h"]["strategy"]["oos"]["expR"], 0)                          # en 1 heure : trop de bruit, perd après frais
        self.assertEqual(fs.tf_status(None, "1d")["send"], False)


class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("SOLUSDT",), data_dir=tempfile.mkdtemp(), port=0, heatmap_days=40), env_path=None)
        cls.app.service.refresh_all()

    def test_live_divergences_on_three_timeframes(self):
        s = self.app.service.signals("SOLUSDT")
        json.dumps(s)
        self.assertTrue(s["ready"] and s["warm"])
        self.assertEqual(set(s["tfs"]), {"1d", "4h", "1h"})
        for tf, v in s["tfs"].items():
            step = fs.TF_H[tf] * H
            self.assertEqual(v["t"] % step, 0)
            self.assertEqual(v["next"] - v["t"], step)
        for r in s["recent"]:
            self.assertIn(r["tf"], fs.DIV_TFS)
            if r["side"]:
                self.assertEqual({"long": 1, "short": -1}[r["side"]], fs.reaction(fs.parse_skey(r["state"])))
        for i in s["ideas"]:
            self.assertEqual(i["eligible"], s["status"][i["tf"]]["send"])

    def test_idea_text_has_no_abbreviation(self):
        from engine import signals as sg
        from tests.test_signals import BANNED
        e = {"t": 24 * H, "tf": "1d", "place": "div", "st": (-1, 1, -1), "price": 100.0, "atr": 4.0, "h": 103.0, "l": 98.0, "o": 102.0,
             "up": [110.0], "dn": [90.0], "lvl": 99.0, "src": "creux journalier", "oiChg": 0.05, "cvdImb": -0.03, "ageH": 240}
        status = {"level": "prometteur", "send": True, "exit": "marché|3R", "text": "Journalier : prometteur."}
        i = fs.idea(e, "SOLUSDT", 100.2, status, 10.0)
        self.assertEqual((i["side"], i["eligible"], i["tf"], i["validHours"]), ("short", True, "1d", 24))
        self.assertAlmostEqual(i["tp1"], 100.0 - 3 * (i["stop"] - 100.0))
        txt = sg.to_text(i, i["desc"], 1, 5)
        self.assertIsNone(BANNED.search(txt), BANNED.search(txt))
        self.assertIn("10 jours", txt)
        self.assertIn("bougie journalière", txt)
        self.assertNotIn("VWAP", txt)
        self.assertIsNone(fs.idea({**e, "st": (-1, -1, -1)}, "SOLUSDT", 100.0, status))               # intérêt ouvert en baisse : pas d'idée
        off = {**status, "level": "non validé", "send": False}
        self.assertFalse(fs.idea({**e, "tf": "1h"}, "SOLUSDT", 100.0, off)["eligible"])


class PageTests(unittest.TestCase):
    SIG = (WEB / "signals.js").read_text(encoding="utf-8")
    BT = (WEB / "backtest.js").read_text(encoding="utf-8")
    APP = (WEB / "app.js").read_text(encoding="utf-8")

    def test_pages(self):
        for k in ("function divBox(", "function reactTable(", "function recentList("):
            self.assertIn(k, self.SIG)
        self.assertNotIn("function flowBox(", self.SIG)
        for k in ("function divVerdict(", "function divTf(", "Anciennes mesures", "r.kind === 'div'"):
            self.assertIn(k, self.BT)
        self.assertIn("NEED_API = 33", self.APP)
        self.assertIn("div", reports_mod.KINDS)


if __name__ == "__main__":
    unittest.main()
