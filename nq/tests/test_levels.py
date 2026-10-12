import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from data.simulated import SimulatedSource
from engine import clock, context, events, levels
from engine.bars import Tick
from engine.market import Market

MIN = 60_000


def utc(y, m, d, hh=0, mm=0, ss=0):
    return int(datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp() * 1000)


NOW = utc(2026, 10, 12, 16, 40)


def sim_market(now=NOW, days=3):
    m = Market()
    m.ingest_many(SimulatedSource(days=days, now_fn=lambda: now).history(now))
    return m


class LevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = sim_market()
        cls.lv = levels.build(cls.m)

    def test_expected_levels_present(self):
        names = {x["name"] for x in self.lv["levels"]}
        for n in ("High veille", "Low veille", "Clôture veille", "POC veille", "VAH veille", "VAL veille", "VWAP", "VWAP +1σ", "VWAP −2σ",
                  "IB High", "IB Low", "Ouverture 9h30", "POC séance", "VAH séance", "VAL séance"):
            self.assertIn(n, names)
        self.assertEqual(self.lv["prevDay"], "2026-10-09")
        self.assertEqual(self.lv["day"], "2026-10-12")

    def test_values_come_from_the_data(self):
        by = {x["name"]: x["price"] for x in self.lv["levels"]}
        prev = self.m.window_ohlc("2026-10-09", "rth")
        self.assertEqual(by["High veille"], prev["h"])
        self.assertEqual(by["Low veille"], prev["l"])
        self.assertEqual(by["Clôture veille"], prev["c"])
        lad = self.m.ladder("2026-10-12", "rth")
        self.assertAlmostEqual(by["VWAP"], lad.vwap, places=3)
        self.assertAlmostEqual(by["VWAP +2σ"] - by["VWAP"], 2 * lad.sd, places=3)
        ib = self.m.window_ohlc("2026-10-12", "ib")
        self.assertEqual((by["IB High"], by["IB Low"]), (ib["h"], ib["l"]))
        self.assertLess(by["VAL séance"], by["POC séance"] + 1e-9)
        self.assertGreater(by["VAH séance"], by["POC séance"] - 1e-9)

    def test_sorted_with_distance(self):
        ps = [x["price"] for x in self.lv["levels"]]
        self.assertEqual(ps, sorted(ps, reverse=True))
        x = self.lv["levels"][0]
        self.assertAlmostEqual(x["dist"], x["price"] - self.lv["price"], places=3)
        self.assertAlmostEqual(x["usdNQ"], abs(x["dist"]) * 20, places=1)
        self.assertAlmostEqual(x["usdMNQ"], abs(x["dist"]) * 2, places=1)

    def test_same_extreme_is_not_a_confluence(self):
        # le plus haut de la nuit est le plus haut de Londres : un seul niveau, pas une « zone »
        by = [x for x in self.lv["levels"] if "High nuit" in x["name"]]
        self.assertEqual(len(by), 1)
        self.assertIn("High Londres", by[0]["name"])
        for z in self.lv["zones"]:
            self.assertGreaterEqual(len(z["names"]), 2)
            self.assertFalse({"High nuit = High Londres", "Low nuit = Low Asie"} >= set(z["names"]))

    def test_merge_same(self):
        lv = [{"name": "A", "price": 100.0, "kind": "onh", "group": "nuit", "w": 2.5}, {"name": "B", "price": 100.0, "kind": "lonh", "group": "nuit", "w": 1.5},
              {"name": "C", "price": 100.0, "kind": "pdh", "group": "veille", "w": 3.0}, {"name": "D", "price": 100.25, "kind": "asih", "group": "nuit", "w": 1.5}]
        out = levels.merge_same(lv, 0.25)
        self.assertEqual(len(out), 3)                       # A=B fusionnes ; C (autre groupe) et D (un tick plus loin) restent
        self.assertEqual([x for x in out if x["group"] == "nuit" and x["price"] == 100.0][0]["name"], "A = B")

    def test_zones(self):
        lv = [{"name": n, "price": p, "kind": "x", "group": g, "w": w} for n, p, g, w in
              (("a", 100.0, "veille", 3.0), ("b", 102.0, "seance", 2.5), ("c", 130.0, "veille", 3.0), ("d", 150.0, "nuit", 1.5), ("e", 152.0, "nuit", 1.0))]
        z = levels.zones(lv, 120.0, zone_pts=6.0, min_score=4.0)
        self.assertEqual(len(z), 1)                          # (a, b) : score 5,5 ; (d, e) : 2,5 sous le seuil ; c est seul
        self.assertEqual((z[0]["lo"], z[0]["hi"], z[0]["score"], z[0]["n"], z[0]["rank"]), (100.0, 102.0, 5.5, 2, 1))
        self.assertAlmostEqual(z[0]["mid"], (100 * 3 + 102 * 2.5) / 5.5, places=3)
        self.assertAlmostEqual(z[0]["dist"], z[0]["mid"] - 120.0, places=3)
        self.assertEqual(levels.zones(lv, 120.0, zone_pts=1.0), [])

    def test_round_numbers_and_nearest(self):
        r = levels._round_levels(25_012.0, 100)
        prices = [p for _, p, _ in r]
        self.assertIn(25_000.0, prices)
        self.assertIn(25_050.0, prices)
        self.assertEqual(dict((p, k) for _, p, k in r)[25_000.0], "r100")
        self.assertEqual(dict((p, k) for _, p, k in r)[25_050.0], "r50")
        near = levels.nearest(self.lv["levels"], self.lv["price"], 2)
        self.assertEqual(len(near["above"]), 2)
        self.assertTrue(all(x["price"] > self.lv["price"] and x["group"] != "rond" for x in near["above"]))
        self.assertTrue(all(x["price"] < self.lv["price"] for x in near["below"]))
        self.assertLess(near["above"][0]["price"], near["above"][1]["price"])

    def test_empty_market(self):
        self.assertEqual(levels.build(Market()), {"price": None, "levels": [], "zones": []})

    def test_before_the_open_uses_globex(self):
        now = utc(2026, 10, 12, 12, 0)                       # 8 h ET : avant l'ouverture de New York
        m = sim_market(now)
        names = {x["name"] for x in levels.build(m)["levels"]}
        self.assertIn("VWAP Globex", names)
        self.assertIn("POC Globex", names)
        self.assertNotIn("IB High", names)
        self.assertNotIn("Ouverture 9h30", names)
        self.assertIn("High nuit", " ".join(names))


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = sim_market()
        cls.lv = levels.build(cls.m)
        cls.src = {"simulated": True}

    def build(self, **kw):
        return context.build(self.m, self.lv, source=kw.pop("source", self.src), **kw)

    def test_structure_and_numbers(self):
        c = self.build()
        self.assertTrue(c["ready"])
        self.assertEqual(c["phase"]["key"], "lunch")
        lad = self.m.ladder("2026-10-12", "rth")
        self.assertAlmostEqual(c["vwap"]["v"], lad.vwap, places=2)
        self.assertAlmostEqual(c["vwap"]["z"], (c["price"] - lad.vwap) / lad.sd, places=1)
        self.assertEqual(c["valueAreaPrev"]["rel"] in ("au-dessus", "dans", "en dessous"), True)
        self.assertTrue(c["ib"]["done"])
        self.assertAlmostEqual(c["ib"]["range"], c["ib"]["hi"] - c["ib"]["lo"], places=2)
        self.assertIn("flow", c)
        self.assertAlmostEqual(c["flow"]["cvd"], lad.delta, places=3)           # le CVD de la seance finit sur le delta de la seance
        self.assertGreater(c["atr1"], 0)
        self.assertGreater(c["atr5"], c["atr1"])
        tones = {n["tone"] for n in c["notes"]}
        self.assertTrue(tones <= {"bull", "bear", "info", "warn"})

    def test_simulated_warning(self):
        self.assertTrue(any("SIMULÉES" in n["text"] for n in self.build()["notes"]))
        self.assertFalse(any("SIMULÉES" in n["text"] for n in self.build(source={"simulated": False})["notes"]))

    def test_marks_use_paris_time(self):
        c = self.build()
        self.assertEqual(c["marks"][0]["paris"], "19:30")               # reprise de l'apres-midi 13 h 30 ET = 19 h 30 a Paris (les deux en heure d'ete)
        self.assertTrue(any("19:30" in n["text"] for n in c["notes"]))

    def test_blackout_note(self):
        ev = events.Event(NOW + MIN, "CPI (inflation US)", 3)
        c = self.build(events=[ev])
        self.assertTrue(any("FENÊTRE À ÉVITER" in n["text"] and "CPI" in n["text"] for n in c["notes"]))
        c = self.build(events=[events.Event(NOW + 600 * MIN, "FOMC", 3)])
        self.assertFalse(any("FENÊTRE" in n["text"] for n in c["notes"]))

    def test_forced_flat_warning_only_near_the_end_of_the_day(self):
        near = sim_market(utc(2026, 10, 12, 20, 25), 2)                                           # 16 h 25 ET : 20 min avant la fermeture forcee
        c = context.build(near, levels.build(near), source={"simulated": False})
        txt = [n["text"] for n in c["notes"] if "Fermeture forcée" in n["text"]]
        self.assertEqual(len(txt), 1)
        self.assertIn("22:45", txt[0])
        self.assertIn("dans 20 min", txt[0])
        self.assertFalse(any("Fermeture forcée" in n["text"] for n in self.build()["notes"]))     # 12 h 40 ET : trop tot pour le dire

    def test_micro_scalping_warning(self):
        mic = {"shareMin": 0.62, "limit": 0.5, "seconds": 5, "known": 10, "unknown": 0}
        c = self.build(acct={"breached": False, "dailyStopHit": False, "dailyStop": 300, "status": "ok", "buffer": 900, "micro": mic})
        self.assertTrue(any("Micro-scalping" in n["text"] and "62 %" in n["text"] for n in c["notes"]))
        mic["shareMin"] = 0.2
        c = self.build(acct={"breached": False, "dailyStopHit": False, "dailyStop": 300, "status": "ok", "buffer": 900, "micro": mic})
        self.assertFalse(any("Micro-scalping" in n["text"] for n in c["notes"]))

    def test_estimated_delta_warning(self):
        m = Market()
        t0 = clock.window("2026-10-12", "rth")[0]
        p = 25_000.0
        for i in range(1200):
            p += 0.25 if i % 7 else -0.5
            m.ingest(Tick(t0 + i * 3000, p, 3, 0))                     # aucun cote fourni
        c = context.build(m, levels.build(m), source={"simulated": False})
        self.assertLess(c["deltaReal"], 0.1)
        self.assertTrue(any("ESTIMÉ" in n["text"] for n in c["notes"]))

    def test_account_notes(self):
        c = self.build(acct={"breached": False, "dailyStopHit": True, "dailyStop": 300, "status": "ok", "buffer": 700})
        self.assertTrue(any("Stop quotidien" in n["text"] for n in c["notes"]))
        c = self.build(acct={"breached": False, "dailyStopHit": False, "dailyStop": 300, "status": "danger", "buffer": 180})
        self.assertTrue(any("Marge avant le plancher" in n["text"] for n in c["notes"]))

    def test_funded_account_notes(self):
        acct = {"breached": False, "dailyStopHit": False, "dllHit": False, "dailyStop": 300, "status": "ok", "buffer": 900, "stage": "funded",
                "caps": {"minis": 1, "micros": 10, "next": 1000},
                "payout": {"eligible": True, "max": {"amount": 550, "net": 495, "balance": 25_550, "floor": 25_100, "cushion": 450}}}
        txt = " | ".join(n["text"] for n in self.build(acct=acct)["notes"])
        self.assertIn("1 mini / 10 micros jusqu'à 1\u202f000 $", txt)
        self.assertIn("Retrait possible : jusqu'à 550 $ (495 $ pour toi", txt)
        self.assertIn("marge 450 $", txt)
        acct["payout"] = {"eligible": False, "max": None}
        acct["caps"] = {"minis": 2, "micros": 20, "next": None}
        txt = " | ".join(n["text"] for n in self.build(acct=acct)["notes"])
        self.assertNotIn("Retrait possible", txt)
        self.assertNotIn("taille limitée", txt)

    def test_soft_daily_loss_limit_note(self):
        acct = {"breached": False, "dailyStopHit": True, "dllHit": True, "dll": 600, "dailyStop": 300, "status": "ok", "buffer": 700}
        txt = " | ".join(n["text"] for n in self.build(acct=acct)["notes"])
        self.assertIn("Limite de perte journalière atteinte (−600 $)", txt)
        self.assertIn("le compte survit", txt)

    def test_empty_and_closed(self):
        self.assertFalse(context.build(Market(), {})["ready"])
        sat = utc(2026, 10, 10, 15)
        m = sim_market(sat, 2)
        c = context.build(m, levels.build(m), source={"simulated": False}, now_ms=sat)
        self.assertFalse(c["phase"]["open"])
        self.assertEqual(c["day"], "2026-10-09")                      # les donnees sont celles du vendredi
        self.assertEqual(c["vwap"]["scope"], "séance")
        self.assertTrue(any("marché est fermé" in n["text"] for n in c["notes"]))

    def test_french_number_format(self):
        self.assertEqual(context.fr(25000.5, 2), "25 000,50")
        self.assertEqual(context.fr(-1.04, 1), "−1,0")


class EventsTests(unittest.TestCase):
    def test_parse_is_tolerant(self):
        items = [{"t": "2026-10-14T12:30:00Z", "name": "CPI", "impact": 3}, {"t": 1791985800000, "name": "Ventes", "impact": 9},
                 {"name": "sans heure"}, {"t": "n'importe quoi", "name": "X"}, "pas un dict"]
        ev = events.parse(items)
        self.assertEqual(len(ev), 2)
        self.assertEqual(events.parse.skipped, 3)
        self.assertEqual(ev[0].t, utc(2026, 10, 14, 12, 30) if ev[0].name == "CPI" else ev[0].t)
        self.assertEqual({e.name: e.impact for e in ev}, {"CPI": 3, "Ventes": 3})        # l'impact est borne a 1..3
        self.assertEqual([e.t for e in ev], sorted(e.t for e in ev))

    def test_upcoming_and_blackout(self):
        now = utc(2026, 10, 14, 12, 0)
        ev = events.parse([{"t": "2026-10-14T12:30:00Z", "name": "CPI", "impact": 3}, {"t": "2026-10-14T14:00:00Z", "name": "Petit", "impact": 1},
                             {"t": "2026-10-20T14:00:00Z", "name": "Loin", "impact": 3}])
        self.assertEqual([e.name for e in events.upcoming(ev, now)], ["CPI", "Petit"])
        self.assertEqual([e.name for e in events.upcoming(ev, now, min_impact=3)], ["CPI"])
        self.assertIsNone(events.blackout(ev, now))
        self.assertEqual(events.blackout(ev, utc(2026, 10, 14, 12, 28)).name, "CPI")          # 2 min avant
        self.assertIsNone(events.blackout(ev, utc(2026, 10, 14, 12, 27, 59)))
        self.assertEqual(events.blackout(ev, utc(2026, 10, 14, 12, 33)).name, "CPI")          # 3 min apres
        self.assertIsNone(events.blackout(ev, utc(2026, 10, 14, 12, 33, 1)))
        self.assertIsNone(events.blackout(ev, utc(2026, 10, 14, 14, 0)))                      # impact 1 : pas de pause

    def test_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events.json"
            self.assertEqual(events.load(p), [])
            p.write_text("{pas du json", encoding="utf-8")
            self.assertEqual(events.load(p), [])
            p.write_text(json.dumps([{"t": "2026-10-14T12:30:00Z", "name": "CPI", "impact": 3}]), encoding="utf-8")
            self.assertEqual(events.load(p)[0].to_dict()["paris"], "14:30")


if __name__ == "__main__":
    unittest.main()
