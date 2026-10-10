"""Bilan macro de la semaine (V18) : donnees FRED, chiffre publie retrouve (et garde-fous), lectures par theme, mesure, archive, adresses, Telegram."""
import json
import random
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from data import fred
from engine import macroweek as mw

DAY = 86_400_000


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def monthly(y0, m0, values):
    out, y, m = [], y0, m0
    for v in values:
        out.append((ms(y, m, 1), v))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class FredTests(unittest.TestCase):
    def test_parse_merge_and_start(self):
        self.assertEqual(fred.parse_csv("observation_date,CPIAUCSL\n2026-08-01,325.1\n2026-09-01,.\n2026-10-01,\n"), [(ms(2026, 8, 1), 325.1)])
        self.assertEqual(fred.parse_csv("DATE,UNRATE\n2026-08-01,4.3\n"), [(ms(2026, 8, 1), 4.3)])                  # ancien en-tete
        self.assertEqual(fred.merge([(1, 1.0), (2, 2.0)], [(2, 2.5), (3, 3.0)]), [(1, 1.0), (2, 2.5), (3, 3.0)])      # revision
        self.assertEqual(fred.start_for([], ms(2026, 10, 1)), fred.START)
        self.assertEqual(fred.start_for([(ms(2016, 1, 1), 1.0)], ms(2026, 10, 10)), "2025-09-05")
        now = ms(2026, 10, 10)
        self.assertEqual(fred.simulated("CPIAUCNS", now)[-1], fred.simulated("CPIAUCNS", now, now - 400 * DAY)[-1])   # meme serie quel que soit le debut


class WeekTests(unittest.TestCase):
    def test_week_bounds(self):
        ws = mw.week_start(ms(2026, 10, 10, 15))                     # samedi
        self.assertEqual(ws, ms(2026, 10, 5))                         # lundi 00 h UTC
        self.assertEqual(mw.week_start(ms(2026, 10, 5)), ms(2026, 10, 5))
        self.assertEqual(mw.week_key(ws), "2026-10-05")
        self.assertEqual(mw.parse_week("2026-10-07"), ws)


class PublishedTests(unittest.TestCase):
    def setUp(self):
        self.cpi = monthly(2025, 1, [300 * 1.003 ** i for i in range(20)])        # janvier 2025 -> aout 2026, +0,3 % par mois
        self.ev = {"country": "USD", "title": "CPI m/m", "t": ms(2026, 9, 11, 12), "forecast": "0.3%", "previous": "0.3%", "pnum": 0.3, "fnum": 0.3}

    def test_cpi_value_and_period(self):
        p = mw.published(self.ev, {"CPIAUCSL": self.cpi})
        self.assertEqual((p["value"], p["text"], p["period"]), (0.3, "0.3%", "août 2026"))

    def test_guards(self):
        late = {**self.ev, "t": ms(2026, 10, 14, 12)}                 # chiffre de septembre : pas encore dans FRED
        self.assertIsNone(mw.published(late, {"CPIAUCSL": self.cpi}))
        self.assertIsNone(mw.published({**self.ev, "pnum": 0.9}, {"CPIAUCSL": self.cpi}))     # « precedent » incoherent : on n'affiche rien
        self.assertIsNone(mw.published({**self.ev, "country": "EUR"}, {"CPIAUCSL": self.cpi}))
        self.assertIsNone(mw.published({**self.ev, "title": "ISM Services PMI"}, {"CPIAUCSL": self.cpi}))

    def test_other_series(self):
        pay = monthly(2026, 1, [158_000, 158_150, 158_300, 158_400, 158_550, 158_700, 158_820, 158_960, 159_100])  # jusqu'a septembre
        nfp = {"country": "USD", "title": "Non-Farm Employment Change", "t": ms(2026, 10, 2, 12), "forecast": "150K", "previous": "140K", "pnum": 140.0}
        p = mw.published(nfp, {"PAYEMS": pay})
        self.assertEqual((p["text"], p["period"]), ("140K", "septembre 2026"))
        claims = [(ms(2026, 9, 27) + i * 7 * DAY, 220_000 + i * 1000) for i in range(3)]           # samedis 27/09, 04/10, 11/10
        c = mw.published({"country": "USD", "title": "Unemployment Claims", "t": ms(2026, 10, 9, 12), "pnum": 220.0}, {"ICSA": claims})
        self.assertEqual(c["text"], "221K")                                                       # semaine au 4 octobre
        gdp = [(ms(2026, 4, 1), 1.8), (ms(2026, 7, 1), 2.9)]
        g = mw.published({"country": "USD", "title": "Advance GDP q/q", "t": ms(2026, 10, 29, 12), "forecast": "2.5%", "previous": "1.8%"}, {"A191RL1Q225SBEA": gdp})
        self.assertEqual((g["text"], g["period"]), ("2.9%", "3e trimestre 2026"))
        ff = [(ms(2026, 9, 16) + i * DAY, 4.5 if i < 2 else 4.25) for i in range(5)]
        r = mw.published({"country": "USD", "title": "Federal Funds Rate", "t": ms(2026, 9, 17, 18), "forecast": "4.25%", "previous": "4.50%", "pnum": 4.5}, {"DFEDTARU": ff})
        self.assertEqual(r["value"], 4.25)
        cls = mw.macro_engine.classify("Federal Funds Rate")
        self.assertEqual(mw.read_event(cls, r, {"pnum": 4.5})[0], -1)                            # baisse de taux

    def test_reading(self):
        cls = mw.macro_engine.classify("CPI m/m")
        d, txt = mw.read_event(cls, {"value": 0.5, "sid": "CPIAUCSL"}, {"fnum": 0.3, "forecast": "0.3%"})
        self.assertEqual(d, 1)
        self.assertIn("plus forte que prévu", txt)
        self.assertEqual(mw.read_event(cls, {"value": 0.3, "sid": "CPIAUCSL"}, {"fnum": 0.3, "forecast": "0.3%"})[0], 0)
        cl = mw.macro_engine.classify("Unemployment Claims")
        self.assertIn("Moins d'inscriptions", mw.read_event(cl, {"value": 210.0, "sid": "ICSA"}, {"fnum": 230.0, "forecast": "230K"})[1])


class DashboardTests(unittest.TestCase):
    def test_theme_rules(self):
        t = ms(2026, 10, 9)
        core_nsa = monthly(2025, 1, [300 * 1.002 ** i for i in range(20)])
        core_sa = monthly(2025, 1, [300 * 1.002 ** i for i in range(17)] + [300 * 1.002 ** 16 * 1.006 ** k for k in range(1, 4)])   # 3 derniers mois : +0,6 %
        weeks = [t - (60 - i) * 7 * DAY for i in range(61)]
        walcl = [(w, 6_600_000 + i * 20_000) for i, w in enumerate(weeks)]                        # bilan de la Fed en hausse
        tga = [(w, 700_000) for w in weeks]
        days = [t - (120 - i) * DAY for i in range(121)]
        dollar = [(d, 120 * (1 - 0.0005 * i)) for i, d in enumerate(days)]                       # dollar en baisse
        f = {"CPILFENS": core_nsa, "CPILFESL": core_sa, "WALCL": walcl, "WTREGEN": tga, "DTWEXBGS": dollar}
        th = {x["key"]: x for x in mw.dashboard(f, t)}
        self.assertEqual(th["inflation"]["score"], -1.0)
        self.assertIn("RÉACCÉLÈRE", th["inflation"]["read"])
        self.assertEqual(th["liquidite"]["score"], 1.0)
        self.assertEqual(th["dollar"]["score"], 1.0)
        v = mw.verdict(list(th.values()), [])
        self.assertEqual((v["score"], v["label"]), (1.0, "plutôt favorable"))
        lag = {x["key"]: x for x in mw.dashboard(f, t, lagged=True)}                             # semaine passee : chiffres pas encore publies exclus
        self.assertTrue(lag["inflation"]["items"])


class StudyTests(unittest.TestCase):
    def test_driver_that_matters_and_one_that_does_not(self):
        rnd = random.Random(7)
        start = ms(2018, 1, 1)
        days = [start + i * DAY for i in range(8 * 365)]
        weeks = [d for d in days if (d // DAY + 3) % 7 == 2]                                       # samedis
        lvl, walcl = 4_000_000.0, []
        for w in weeks:
            lvl += rnd.choice((-1, 1)) * 30_000
            walcl.append((w, lvl))
        tga = [(w, 500_000) for w in weeks]
        px, p = [], 10_000.0
        for d in days:                                                                              # le bitcoin monte quand la liquidite a monte
            a, b = mw.at(walcl, d - 2 * DAY), mw.at(walcl, d - 30 * DAY)
            drift = 0.004 if (a and b and a > b) else -0.004
            p *= 1 + drift + rnd.gauss(0, 0.01)
            px.append((d, p))
        dollar = [(d, 100 + rnd.gauss(0, 1)) for d in days]
        st = mw.drivers_study({"WALCL": walcl, "WTREGEN": tga, "DTWEXBGS": dollar}, px, days[-1])
        rows = {r["key"]: r for r in st["rows"]}
        self.assertTrue(st["ready"])
        self.assertIn("écart net", rows["liquidite"]["verdict"])
        self.assertGreater(rows["liquidite"]["fav1"], rows["liquidite"]["unf1"])
        self.assertIn("hasard", rows["dollar"]["verdict"])
        self.assertFalse(mw.drivers_study({}, [], days[-1])["ready"])


class BuildAndServerTests(unittest.TestCase):
    SAT = ms(2026, 10, 10, 9)                                                                       # samedi 9 h UTC

    def make_app(self):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None, make_source=lambda c: SimulatedSource(now_ms=self.SAT))
        app.service.ext.refresh(force=True)
        return app

    def test_build_archive_and_telegram(self):
        app = self.make_app()
        svc = app.service
        r = svc.macro_week()
        self.assertEqual(r["week"], "2026-10-05")
        self.assertTrue(r["current"] and r["hasFred"])
        self.assertEqual({t["key"] for t in r["themes"]}, {"inflation", "emploi", "croissance", "taux", "dollar", "liquidite", "risque", "energie"})
        self.assertIn("Bilan macro de la semaine du 05/10", r["summary"])
        json.dumps(r)
        self.assertIn("2026-10-05", svc.mw_archive)
        lst = svc.macro_weeks()
        self.assertEqual(lst["current"], "2026-10-05")
        self.assertEqual(len(lst["weeks"]), svc.MW_BACK + 1)
        prev = svc.macro_week("2026-09-28")
        self.assertTrue(prev["reconstructed"] and not prev["current"])
        with self.assertRaises(ValueError):
            svc.macro_week("2026-10-12")                                                            # semaine a venir
        with self.assertRaises(KeyError):
            svc.macro_week("2025-01-06")                                                            # trop ancienne, jamais archivee
        sent = []

        class N:
            def send(self, text):
                sent.append(text)
        app.notifier = N()
        app.macro_week_tick(force=True)
        self.assertEqual(sent, [])                                                                  # option desactivee par defaut
        app.cfg.macro_week_telegram, app.cfg.telegram_token, app.cfg.telegram_chat_id = True, "1:x", "1"
        app.macro_week_tick(force=True)
        self.assertTrue(sent and sent[0].startswith("Bilan macro de la semaine"))
        n = len(sent)
        app.macro_week_tick(force=True)
        self.assertEqual(len(sent), n)                                                              # une seule fois par semaine
        with mock.patch.object(app.assistant, "ask", return_value={"ok": True, "answer": "Commentaire.", "usd": 0.02, "model": "m"}) as ask:
            res = app.macro_week_comment(None)
        self.assertTrue(res["ok"])
        self.assertEqual(ask.call_args.kwargs["src"], "bilan")
        self.assertIn("Bilan macro", ask.call_args.kwargs["context"])
        self.assertEqual(svc.macro_week()["comment"]["text"], "Commentaire.")
        lec = svc.lecture("BTCUSDT") if svc.markets["BTCUSDT"].ready else None
        if lec:
            self.assertTrue(any(c["key"] == "macroweek" for c in lec["chips"]))


if __name__ == "__main__":
    unittest.main()
