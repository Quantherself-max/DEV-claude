"""V20 : TPO de haute unite de temps (semaine du lundi, mois calendaire) ; single prints mesurees face a des seances semblables, reaction au
premier retour du prix, elan ; adresses et marques."""
import json
import random
import tempfile
import unittest
from datetime import datetime, timezone

from engine import fine, tpo, tpostudy
from engine import signals as sg
from engine.atr import Candle

H = 3_600_000
DAY = 24 * H


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def synth_h1(days, seed=3, start=None):
    rnd = random.Random(seed)
    b = fine.Bars(H)
    p, t = 20_000.0, start or ms(2019, 1, 7)
    for _ in range(days * 24):
        o = p
        p *= 1 + rnd.gauss(0.00005, 0.006)
        hi, lo = max(o, p) * (1 + abs(rnd.gauss(0, 0.002))), min(o, p) * (1 - abs(rnd.gauss(0, 0.002)))
        b.append(t, o, hi, lo, p, 10 + rnd.random(), rnd.gauss(0, 2))
        t += H
    return b.build_cum()


class CalendarTests(unittest.TestCase):
    def test_week_starts_monday_and_month_is_calendar(self):
        t = ms(2026, 10, 10, 15)                                                   # samedi
        s = tpo.session_start("W", t)
        self.assertEqual(datetime.fromtimestamp(s / 1000, timezone.utc).weekday(), 0)
        self.assertEqual((s, tpo.session_end("W", s)), (ms(2026, 10, 5), ms(2026, 10, 12)))
        self.assertEqual(tpo.session_start("M", t), ms(2026, 10, 1))
        self.assertEqual(tpo.session_end("M", ms(2026, 12, 1)), ms(2027, 1, 1))             # decembre -> janvier
        self.assertEqual(tpo.session_end("M", ms(2024, 2, 1)) - ms(2024, 2, 1), 29 * DAY)   # annee bissextile
        for k in ("W", "M", "D"):
            a = tpo.session_start(k, t)
            b = tpo.session_start(k, a - 1)
            self.assertEqual(tpo.session_index(k, a) - tpo.session_index(k, b), 1)
            self.assertEqual(tpo.session_end(k, b), a)
        self.assertIn("lundi", tpo.type_text("normal", "W"))
        self.assertIn("tout le mois", tpo.type_text("trend", "M"))
        self.assertIn("première heure", tpo.type_text("neutral", "D"))


class HtfSessionsTests(unittest.TestCase):
    def test_week_and_month_profiles_on_hourly_bars(self):
        b = synth_h1(200)
        bars = b.candles(0, len(b))
        now = int(b.t[-1]) + H - 1
        w = tpo.sessions(bars, "W", now, n=8)
        self.assertEqual(len(w["sessions"]), 8)
        self.assertEqual((w["ibName"], w["bracketMs"]), ("lundi", 4 * H))
        done = [s for s in w["sessions"] if not s["marks"]["current"]]
        self.assertTrue(all(s["brackets"] == 42 for s in done))                   # 7 jours x 6 tranches de 4 heures
        self.assertTrue(all(s["ibMs"] == DAY for s in done))                       # « premiere heure » = le lundi
        for s in done:
            self.assertEqual(datetime.fromtimestamp(s["start"] / 1000, timezone.utc).weekday(), 0)
            self.assertEqual(s["end"] - s["start"], 7 * DAY)
        m = tpo.sessions(bars, "M", now, n=5)
        full = [s for s in m["sessions"] if not s["marks"]["current"] and s["start"] >= int(b.t[0])]
        self.assertTrue(full)
        for s in full:
            d = datetime.fromtimestamp(s["start"] / 1000, timezone.utc)
            self.assertEqual(d.day, 1)
            self.assertEqual(s["brackets"], (tpo.session_end("M", s["start"]) - s["start"]) // DAY)   # une lettre par jour
        self.assertTrue(m["sessions"][-1]["marks"]["current"])


class StudyToolsTests(unittest.TestCase):
    def test_path_index_matches_brute_force(self):
        rnd = random.Random(1)
        h = [100 + rnd.gauss(0, 3) for _ in range(500)]
        lo = [x - abs(rnd.gauss(0, 1)) for x in h]
        P = tpostudy.PathIndex(h, lo, 300)
        for _ in range(400):
            p, x, lim = rnd.randrange(0, 500), 100 + rnd.gauss(0, 5), rnd.randrange(1, 300)
            ge = next((i for i in range(p, min(500, p + lim)) if h[i] >= x), None)
            le = next((i for i in range(p, min(500, p + lim)) if lo[i] <= x), None)
            self.assertEqual(P.first_ge(p, x, lim), ge)
            self.assertEqual(P.first_le(p, x, lim), le)

    def test_reaction_bounce_traverse_and_none(self):
        hi = [99, 100.6, 100.2, 99.4, 99.0, 101.5]
        lo = [98, 99.6, 99.5, 98.6, 98.0, 100.5]
        P = tpostudy.PathIndex(hi, lo, 10)
        self.assertEqual(tpostudy.reaction(P, 0, 100.5, 101.0, 98.5, 10), 1)   # touche 100,5, repart sous 100,0 avant 101 : la zone tient
        self.assertEqual(tpostudy.reaction(P, 0, 100.1, 100.4, 98.5, 10), 0)   # traversee dans la bougie du contact
        self.assertIsNone(tpostudy.reaction(P, 0, 102.0, 103.0, 98.5, 10))     # jamais touchee
        self.assertIsNone(tpostudy.reaction(P, 0, 98.0, 99.0, 98.5, 10))       # la bande contient le prix

    def test_future_table_matches_future(self):
        b = synth_h1(400)
        ss = tpostudy.build_sessions(b, "W", int(b.t[0]), int(b.t[-1]))
        del ss[20]                                                                 # un trou dans l'historique
        t = tpostudy._future_table(ss, (1, 4))
        for h in (1, 4):
            for k in range(len(ss)):
                f = tpostudy._future(ss, k, h)
                self.assertEqual(None if f is None else tuple(f), None if t[h][0][k] is None else (t[h][0][k], t[h][1][k]))

    def test_week_study_structure_and_summary(self):
        b = synth_h1(560)
        r = tpostudy.run(b, "W", int(b.t[0]) + 15 * DAY, int(b.t[-1]))
        self.assertTrue(r["ready"])
        self.assertEqual(r["horizons"], [1, 2, 4, 8, 13])
        self.assertEqual(set(r["singles"]), {"all", "first", "second"})
        self.assertTrue({"fill", "touch", "matched"} <= set(r["singles"]["all"]["1"]))
        self.assertEqual(set(r["singlesReaction"]["all"]), {"matched", "mirror"})
        self.assertIn("rate", r["singlesElan"]["all"])
        self.assertIsNotNone(r["eighty"])                                          # regle des 80 % aussi sur la semaine
        rep = {"symbol": "TEST", "W": r}
        s = tpostudy.summary(rep)
        self.assertTrue(any(x["kind"] == "W" and x["key"] == "singles" for x in s))
        self.assertTrue(any("semaine suivante" in x["text"] for x in s))
        c = tpostudy.compact(rep, "W")
        self.assertEqual(c["units"]["next"], "la semaine suivante")
        self.assertEqual((c["singles"]["h"], c["singles"]["h2"]), (1, 4))
        json.dumps(rep)

    def test_shipped_report_has_week_and_month(self):
        from config import ROOT
        rep = json.loads((ROOT / "reports" / "tpo_BTC.json").read_text(encoding="utf-8"))
        for k in ("W", "M", "D", "4h", "1h"):
            self.assertTrue(rep[k]["ready"], k)
            self.assertIn("matched", rep[k]["singles"]["all"][str(rep[k]["horizons"][0])])
        self.assertGreater(rep["W"]["n"], 700)                                     # semaines depuis 2012
        self.assertGreater(rep["M"]["n"], 150)
        kinds = {x["kind"] for x in rep["summary"] if x["key"] == "singles"}
        self.assertEqual(kinds, {"W", "M", "D", "4h", "1h"})
        c = tpostudy.compact(rep, "M")
        self.assertEqual(c["units"]["next"], "le mois suivant")
        self.assertIn(c["singles"]["verdict"], ("net", "contraire", "instable", "hasard", "insuffisant"))


class ServiceV20Tests(unittest.TestCase):
    def test_week_month_endpoints_marks_and_weights(self):
        from config import Config
        from server import App
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None)
        app.service.refresh_all()
        for k, lab in (("W", "1 semaine"), ("M", "1 mois")):
            r = app.service.get_tpo("BTCUSDT", k, 6)
            self.assertTrue(r["ready"])
            self.assertEqual((r["label"], len(r["sessions"])), (lab, 6))
            self.assertTrue(r["sessions"][-1]["marks"]["current"])
            self.assertIsNotNone(r["study"])                                       # mesure du rapport livre
            self.assertIn(r["study"]["units"]["next"], ("la semaine suivante", "le mois suivant"))
        m = app.service.markets["BTCUSDT"]
        mk = m.tpo_marks()
        self.assertEqual(set(mk), {"D", "4h", "1h", "W", "M"})
        self.assertIs(m.tpo_marks(), mk)                                           # gardees tant que rien ne change
        w = lambda kd: sg.classify({"id": f"TPO|{kd}|S1|0", "name": "Single prints", "group": "TPO", "kind": "tpo", "price": 100.0})
        self.assertEqual([w(k)["tf"] for k in ("D", "4h", "W", "M")], [1, 1, 2, 3])
        self.assertGreater(w("M")["w"], w("W")["w"])
        self.assertGreater(w("W")["w"], w("D")["w"])


if __name__ == "__main__":
    unittest.main()
