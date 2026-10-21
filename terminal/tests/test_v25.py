"""V25 : macro de la semaine (vision d'ensemble : regime, surprises face au consensus, ce que le marche attend de la Fed, estimation du terminal
pour chaque annonce) et macro du mois (Fed, projections, moyen terme, scenarios, rapports des banques). Sources : FRED, site de la Fed, FMI."""
from __future__ import annotations
import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from data import fed, fred, imf
from engine import macromonth as mm
from engine import macroview as mv

DAY = 86_400_000


def ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def monthly(y0, m0, values):
    out, y, m = [], y0, m0
    for v in values:
        out.append((ms(y, m, 1), v))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def index(n, rates, start=100.0):
    """Indice mensuel dont la hausse de chaque mois suit `rates` (en %), le dernier taux se repetant."""
    out, v = [], start
    for k in range(n):
        v *= 1 + rates[min(k, len(rates) - 1)] / 100
        out.append(v)
    return out


def daily(t0, t1, f):
    return [(t, f(t)) for t in range(t0, t1, DAY)]


CAL_HTML = fed.sim_calendar_html(fed.fallback_meetings() + [fed.meeting(2027, 1, 26, 27, False), fed.meeting(2027, 4, 30, 1, True, 5)])


class FedSourceTests(unittest.TestCase):
    def test_meeting_calendar_page(self):
        mts = fed.parse_calendar(CAL_HTML)
        self.assertEqual(len(mts), 10)
        apr = mts[-1]                                                         # « Apr/May 30-1* » : sur deux mois
        self.assertEqual((apr["start"], apr["end"], apr["sep"]), (ms(2027, 4, 30), ms(2027, 5, 1), True))
        nxt = fed.next_meeting(mts, ms(2026, 10, 12))
        self.assertEqual((nxt["end"], nxt["sep"]), (ms(2026, 10, 28), False))
        self.assertEqual(fed.next_meeting(mts, ms(2026, 10, 28, 12))["end"], ms(2026, 10, 28))     # jour de la decision : encore « a venir »
        self.assertEqual(fed.last_meeting(mts, ms(2026, 10, 12))["end"], ms(2026, 9, 16))
        self.assertEqual(fed.parse_calendar("<html>rien</html>"), [])
        self.assertTrue(all(m["sep"] == (m["start"] in (ms(2026, 3, 17), ms(2026, 6, 16), ms(2026, 9, 15), ms(2026, 12, 8))) for m in fed.fallback_meetings()))

    def test_rss_statement_votes_and_what_changed(self):
        xml = fed.sim_rss([{"t": ms(2026, 9, 16, 18), "title": "Federal Reserve issues FOMC statement", "link": fed.FED + "/a.htm"},
                           {"t": ms(2026, 10, 7, 18), "title": "Minutes of the Federal Open Market Committee, September 15-16, 2026", "link": fed.FED + "/m.htm"},
                           {"t": ms(2026, 10, 9, 15), "title": "Waller, The economic outlook", "link": fed.FED + "/s.htm"},
                           {"t": ms(2026, 10, 9, 15), "title": "sans lien", "link": "javascript:alert(1)"}])
        items = fed.parse_rss(xml, "monetary")
        self.assertEqual([i["kind"] for i in items], ["statement", "minutes", "release"])          # le lien non web est ignore
        self.assertEqual(fed.parse_rss(xml, "speeches")[2]["kind"], "speech")
        self.assertEqual(fed.speaker({"title": "Waller, The economic outlook"}), "Waller")
        self.assertEqual(fed.speaker({"title": "Speech by Vice Chair Jefferson on the outlook"}), "Vice Chair Jefferson")
        old = fed.statement_paragraphs(fed.sim_statement_html(fed.SIM_STATEMENTS[0]))
        new = fed.statement_paragraphs(fed.sim_statement_html(fed.SIM_STATEMENTS[1]))
        self.assertEqual(len(new), 4)                                         # ni l'heure de publication, ni la note, ni les contacts presse
        self.assertEqual(fed.decision(old), {"move": "baisse", "by": "1/4", "range": "4-1/4 to 4-1/2"})
        self.assertEqual(fed.decision(new)["move"], "maintien")
        self.assertIn("one Governor", fed.dissents(new)[0])
        d = fed.diff_statements(old, new)
        self.assertIn("The Committee decided to conclude the reduction of its aggregate securities holdings on December 1.", d["added"])
        self.assertTrue(any(s.startswith("Recent indicators") for s in d["removed"]))
        words = [w for ch in d["changed"] for w in ch]
        self.assertIn(("-", "lower"), words)
        self.assertIn(("+", "maintain"), words)
        self.assertGreaterEqual(d["same"], 2)
        self.assertEqual(fed.sentences(["Jerome H. Powell, Chair. The U.S. economy grew. Next"]), ["Jerome H. Powell, Chair.", "The U.S. economy grew.", "Next"])

    def test_tone_ignores_votes(self):
        t = fed.tone("Inflation remains somewhat elevated. The Committee decided to maintain the target range. "
                     "Voting against this action was one Governor, who preferred to lower the target range.")
        self.assertEqual((t["score"], t["label"]), (-1, "plutôt restrictif"))
        self.assertGreater(fed.tone(" ".join(fed.SIM_STATEMENTS[0]))["score"], fed.tone(" ".join(fed.SIM_STATEMENTS[1]))["score"])

    def test_imf_and_new_fred_series(self):
        obj = {"values": {"NGDP_RPCH": {"USA": {"2026": 2.0, "2027": "n/a", "2028": 2.1}, "XYZ": {"2026": 1.0}, "CHN": None}}}
        self.assertEqual(imf.parse(obj, "NGDP_RPCH"), {"USA": {"2026": 2.0, "2028": 2.1}})
        self.assertEqual(imf.parse({}, "LUR"), {})
        self.assertIn("/NGDP_RPCH/USA/EURO/CHN/JPN/WEOWORLD?periods=2025,2026,2027,2028", imf.url(imf.IMF, "NGDP_RPCH", ms(2026, 10, 12)))
        now = ms(2026, 10, 12)
        proj = fred.simulated("FEDTARMD", now)
        self.assertEqual([datetime.fromtimestamp(t / 1000, timezone.utc).year for t, _ in proj], [2026, 2027, 2028, 2029])
        self.assertEqual(fred.simulated("FEDTARMDLR", now)[0][0], ms(2026, 9, 17))
        self.assertTrue(all(k in fred.SERIES for k in fred.PROJECTIONS + ("DGS1", "DGS6MO", "DGS3MO", "DFF", "GDPNOW", "GASREGW", "T10Y3M")))
        self.assertTrue(fred.simulated("GDPNOW", now)[-1][0] <= now)


class HubTests(unittest.TestCase):
    def test_fed_and_imf_are_fetched_kept_and_reloaded(self):
        from data.external import ExternalHub, RealProviders, SimProviders
        from data.base import DataError
        now = ms(2026, 10, 12, 9)
        d = tempfile.mkdtemp()
        h = ExternalHub(SimProviders(lambda: now), lambda: now, d, ("BTCUSDT",))
        h.refresh(force=True)
        self.assertNotIn("fed", h.errors)
        self.assertEqual(h.fed["calSrc"], "page de la Fed")
        self.assertTrue(any(i["kind"] == "statement" for i in h.fed["items"]))
        self.assertGreaterEqual(len(h.fed["statements"]), 2)
        self.assertEqual(set(h.imf) - {"t", "errors"}, set(imf.INDICATORS))
        snap = h.snapshot()
        self.assertIn("fed", snap)
        h2 = ExternalHub(SimProviders(lambda: now), lambda: now, d, ("BTCUSDT",))
        self.assertEqual(len(h2.fed["items"]), len(h.fed["items"]))           # copie locale relue au demarrage
        self.assertEqual(h2.imf["NGDP_RPCH"], h.imf["NGDP_RPCH"])
        with self.assertRaises(DataError):
            RealProviders(fed="http://127.0.0.1:9").fed_text("https://exemple.org/page.htm")          # jamais hors du site de la Fed

    def test_meeting_list_falls_back_when_the_page_is_unreadable(self):
        from data.external import ExternalHub, SimProviders
        now = ms(2026, 10, 12, 9)

        class P(SimProviders):
            def fed_text(self, path):
                if path == fed.CALENDAR:
                    return "<html>page changée</html>"
                return super().fed_text(path)
        h = ExternalHub(P(lambda: now), lambda: now, None, ())
        h.refresh(force=True)
        self.assertEqual(h.fed["calSrc"], "liste intégrée (2026)")
        self.assertTrue(any("calendrier" in e for e in h.fed["errors"]))
        self.assertEqual(fed.next_meeting(h.fed["meetings"], now)["end"], ms(2026, 10, 28))


def fake_fred(now, growth_up=True, infl_up=False):
    """Series FRED construites pour un regime connu."""
    n = 30
    y0, m0 = 2024, 4
    pay = [150_000 + sum((100 if k < 20 else (220 if growth_up else 20)) for k in range(i)) for i in range(n)]
    un = [4.2] * 26 + ([4.1, 4.0, 3.9, 3.8] if growth_up else [4.3, 4.5, 4.6, 4.7])
    core = index(n, [0.3] * 24 + ([0.45] if infl_up else [0.12]))
    cpi = index(n, [0.3] * 24 + ([0.5] if infl_up else [0.1]))
    pce = index(n, [0.25] * 24 + ([0.4] if infl_up else [0.1]))
    ppi = index(n, [0.2] * 24 + ([0.5] if infl_up else [0.0]))
    rs = index(n, [0.3] * 24 + ([0.8] if growth_up else [-0.3]))
    ip = index(n, [0.1] * 24 + ([0.5] if growth_up else [-0.4]))
    weeks = list(range(ms(2024, 1, 6), now, 7 * DAY))
    claims = [(t, 220_000 if (not growth_up or t < now - 200 * DAY) else 200_000) if growth_up else (t, 220_000 if t < now - 100 * DAY else 260_000) for t in weeks]
    out = {"PAYEMS": monthly(y0, m0, pay), "UNRATE": monthly(y0, m0, un), "CPILFESL": monthly(y0, m0, core), "CPIAUCSL": monthly(y0, m0, cpi),
           "PCEPILFE": monthly(y0, m0, pce), "PPIFIS": monthly(y0, m0, ppi), "RSAFS": monthly(y0, m0, rs), "INDPRO": monthly(y0, m0, ip), "ICSA": claims,
           "T5YIE": daily(ms(2025, 1, 1), now, lambda t: 2.3 + (0.3 if infl_up else -0.3) * max(0, (t - (now - 91 * DAY))) / (91 * DAY)),
           "DFF": daily(ms(2025, 1, 1), now, lambda t: 4.33), "DFEDTARL": daily(ms(2025, 1, 1), now, lambda t: 4.25),
           "DFEDTARU": daily(ms(2025, 1, 1), now, lambda t: 4.5), "DGS3MO": daily(ms(2025, 1, 1), now, lambda t: 4.2),
           "DGS6MO": daily(ms(2025, 1, 1), now, lambda t: 4.0), "DGS1": daily(ms(2025, 1, 1), now, lambda t: 3.8 if t > now - 7 * DAY else 3.9),
           "DGS2": daily(ms(2025, 1, 1), now, lambda t: 3.7), "FEDTARMD": [(ms(2026, 1, 1), 3.6), (ms(2027, 1, 1), 3.4), (ms(2028, 1, 1), 3.1)],
           "FEDTARRL": [(ms(2026, 1, 1), 3.4), (ms(2027, 1, 1), 2.9)], "FEDTARRH": [(ms(2026, 1, 1), 4.1), (ms(2027, 1, 1), 4.1)],
           "FEDTARMDLR": [(ms(2026, 9, 17), 3.0)]}
    return out


class RegimeTests(unittest.TestCase):
    NOW = ms(2026, 10, 12)

    def test_four_quadrants(self):
        for g, i, q in ((True, False, "goldilocks"), (True, True, "reflation"), (False, True, "stagflation"), (False, False, "slowdown")):
            r = mv.regime_at(mv.Data(fake_fred(self.NOW, g, i)), self.NOW, lagged=False)
            self.assertEqual(r["quad"], q, (g, i, r["g"], r["i"]))
            self.assertEqual(r["label"], mv.QUADS[q][0])
            self.assertTrue(all(-2 <= x["score"] <= 2 for x in r["growth"] + r["inflation"]))

    def test_lagged_view_ignores_unpublished_figures(self):
        f = fake_fred(self.NOW, True, False)
        D = mv.Data(f)
        last = f["PAYEMS"][-1][0]                                             # septembre 2026, publie debut octobre (delai 31 jours)
        self.assertEqual(D.n("PAYEMS", last + 5 * DAY, lagged=True), len(f["PAYEMS"]) - 1)
        self.assertEqual(D.n("PAYEMS", last + 5 * DAY, lagged=False), len(f["PAYEMS"]))
        trail = mv.regime_trail(D, self.NOW, 12)
        self.assertGreaterEqual(len(trail), 10)
        self.assertEqual(trail[-1]["t"], self.NOW)

    def test_study_by_regime(self):
        n = 128                                                                   # janvier 2016 -> aout 2026, cycles de croissance et d'inflation decales
        pay = [140_000.0]
        for k in range(1, n):
            pay.append(pay[-1] + 150 + 120 * math.sin(2 * math.pi * k / 26))
        f = {"PAYEMS": monthly(2016, 1, pay), "UNRATE": monthly(2016, 1, [4.2 - 0.4 * math.sin(2 * math.pi * k / 26) for k in range(n)]),
             "CPILFESL": monthly(2016, 1, index(n, [0.25 + 0.12 * math.sin(2 * math.pi * k / 33) for k in range(n)])),
             "PCEPILFE": monthly(2016, 1, index(n, [0.22 + 0.1 * math.sin(2 * math.pi * k / 33) for k in range(n)]))}
        px = daily(ms(2019, 1, 1), self.NOW, lambda t: 10000 * math.exp(t / 3e11) * (1 + 0.1 * math.sin(t / 2e9)))
        st = mv.regime_study(mv.Data(f), px, self.NOW)
        self.assertTrue(st["ready"])
        self.assertGreaterEqual(st["n"], 80)
        self.assertEqual({r["quad"] for r in st["rows"]}, set(mv.QUADS))
        self.assertEqual(sum(r["n"] for r in st["rows"]), st["n"])
        self.assertTrue(all(r["n"] > 0 for r in st["rows"]))                    # les quatre regimes sont visites
        self.assertTrue(all(r["verdict"] in ("pas assez de mois", "écart net", "≈ hasard") for r in st["rows"]))
        self.assertFalse(mv.regime_study(mv.Data(f), px[:100], self.NOW)["ready"])


class SurpriseAndFedTests(unittest.TestCase):
    NOW = ms(2026, 10, 12)

    def ev(self, title, t, f, actual, key=None):
        return {"id": title + str(t), "t": t, "country": "USD", "title": title, "impact": 3, "forecast": str(f), "previous": str(f), "fnum": f, "pnum": f,
                "actual": {"value": actual, "text": str(actual), "period": "", "sid": key or ""}}

    def test_surprise_indexes_signs_and_decay(self):
        cal = {}
        for k, (title, f, a) in enumerate([("Core CPI m/m", 0.3, 0.5), ("CPI m/m", 0.3, 0.4), ("Unemployment Rate", 4.3, 4.5),
                                           ("Non-Farm Employment Change", 150, 40), ("Unemployment Claims", 225, 260)]):
            e = self.ev(title, self.NOW - (3 + k) * DAY, f, a)
            cal[e["id"]] = e
        old = self.ev("Core CPI m/m", self.NOW - 50 * DAY, 0.3, 0.0)                # ancien et plus froid : pese moins
        cal[old["id"]] = old
        cal["vieux"] = self.ev("Core CPI m/m", self.NOW - 90 * DAY, 0.3, 0.9)      # hors des 8 semaines
        s = mv.surprises(cal, {}, self.NOW)
        self.assertEqual(s["activity"]["n"], 3)
        self.assertLess(s["activity"]["value"], -1)                               # chomage et inscriptions en hausse = activite plus faible
        self.assertIn("plus faible", s["activity"]["label"])
        self.assertEqual(s["inflation"]["n"], 3)
        self.assertGreater(s["inflation"]["value"], 0.5)
        self.assertIn("plus chaude", s["inflation"]["label"])
        self.assertEqual(s["inflation"]["above"], 2)
        self.assertEqual(mv.surprises({}, {}, self.NOW)["inflation"]["label"], "pas assez de chiffres publiés")

    def test_market_path_cuts_and_fed_projections(self):
        f = fake_fred(self.NOW)
        D = mv.Data(f)
        p = mv._pricing_at(D, self.NOW, False)
        self.assertAlmostEqual(p["in12"], 2 * 3.8 - 4.0)
        self.assertAlmostEqual(p["cuts"], (4.33 - 3.6) / 0.25)
        self.assertEqual([x["m"] for x in p["path"]], [0.0, 1.5, 4.5, 9.0, 18.0])
        v = mv.fed_view(D, self.NOW, fed.fallback_meetings())
        self.assertAlmostEqual(v["cutsChange"], (4.33 - 3.6) / 0.25 - (4.33 - 3.8) / 0.25)
        self.assertEqual([d["year"] for d in v["dots"]], [2026, 2027, 2028])
        self.assertEqual((v["dots"][0]["low"], v["dots"][0]["high"]), (3.4, 4.1))
        self.assertEqual(v["longRun"], 3.0)
        self.assertEqual((v["next"]["days"], v["next"]["sep"]), (16, False))
        txt = " ".join(v["text"])
        for frag in ("Le marché anticipe environ 2,9 baisses de 0,25 point", "Sur la semaine, le marché a ajouté", "3,60 % fin 2026", "28 octobre 2026"):
            self.assertIn(frag, txt)
        self.assertEqual(mv.fed_view(mv.Data({}), self.NOW, [])["dots"], [])
        early = {**f, "FEDTARMDLR": [(self.NOW + 30 * DAY, 3.0)]}                 # projections publiees apres t : pas d'anachronisme
        self.assertEqual(mv.fed_view(mv.Data(early), self.NOW, [])["dots"], [])
        yearly = {**f, "FEDTARMDLR": [(ms(2026, 1, 1), 3.0)]}                     # date seulement annuelle : projections sans date
        v2 = mv.fed_view(mv.Data(yearly), self.NOW, [])
        self.assertEqual((len(v2["dots"]), v2["sepDate"], v2["longRun"]), (3, None, 3.0))


class EstimateTests(unittest.TestCase):
    NOW = ms(2026, 10, 12)

    def series(self):
        core = monthly(2016, 1, index(128, [0.3]))                                 # janvier 2016 -> aout 2026 : +0,3 % par mois
        food = monthly(2016, 1, index(128, [0.2]))
        headline = monthly(2016, 1, index(128, [0.25]))
        gas = []
        for t in range(ms(2016, 1, 4), ms(2026, 10, 5), 7 * DAY):
            d = datetime.fromtimestamp(t / 1000, timezone.utc)
            gas.append((t, 3.0 * (1.05 if (d.year, d.month) == (2026, 9) else 1.0)))   # essence : +5 % en septembre 2026
        pay = monthly(2016, 1, [140_000 + 150 * k for k in range(128)])
        un = monthly(2016, 1, [4.0 + 0.01 * k for k in range(128)])
        claims = [(t, 230_000.0) for t in range(ms(2024, 1, 6), self.NOW - 3 * DAY, 7 * DAY)]
        return {"CPILFESL": core, "CPIUFDSL": food, "CPIAUCSL": headline, "GASREGW": gas, "PAYEMS": pay, "UNRATE": un, "ICSA": claims,
                "GDPNOW": [(ms(2026, 7, 1), 2.6)]}

    def ev(self, title, t, f):
        return {"id": title, "country": "USD", "title": title, "t": t, "forecast": f"{f}%", "previous": f"{f}%", "fnum": f, "pnum": f}

    def test_estimates(self):
        f = self.series()
        D = mv.Data(f)
        core = mv.estimate(self.ev("Core CPI m/m", ms(2026, 10, 14, 12), 0.3), f, self.NOW, D)
        self.assertAlmostEqual(core["value"], 0.3, places=6)
        head = mv.estimate(self.ev("CPI m/m", ms(2026, 10, 14, 12), 0.3), f, self.NOW, D)
        self.assertGreater(head["value"], 0.3)                                    # l'essence a monte de 5 % en septembre
        self.assertIn("essence", head["how"])
        yoy = mv.estimate(self.ev("Core CPI y/y", ms(2026, 10, 14, 12), 3.7), f, self.NOW, D)
        self.assertAlmostEqual(yoy["value"], (1.003 ** 12 - 1) * 100, places=4)
        nfp = mv.estimate(self.ev("Non-Farm Employment Change", ms(2026, 11, 6, 12), 150), f, self.NOW, D)
        self.assertAlmostEqual(nfp["value"], 150.0)
        ur = mv.estimate(self.ev("Unemployment Rate", ms(2026, 11, 6, 12), 5.3), f, self.NOW, D)
        self.assertAlmostEqual(ur["value"], 5.27 + 0.01, places=6)
        cl = mv.estimate(self.ev("Unemployment Claims", ms(2026, 10, 15, 12), 225), f, self.NOW, D)
        self.assertAlmostEqual(cl["value"], 230.0)
        gdp = mv.estimate(self.ev("Advance GDP q/q", ms(2026, 10, 29, 12), 2.0), f, self.NOW, D)
        self.assertEqual((gdp["value"], gdp["sid"]), (2.6, "GDPNOW"))
        self.assertIsNone(mv.estimate({**self.ev("CPI m/m", ms(2026, 10, 14), 0.3), "country": "EUR"}, f, self.NOW, D))
        err = mv.estimate_error(f, "CPILFESL", "mom", self.NOW, D)
        self.assertLess(err["mae"], 1e-6)                                         # serie parfaitement reguliere : aucune erreur
        self.assertGreaterEqual(err["n"], 40)
        cls = mv.macro_engine.classify("Core CPI m/m")
        e = self.ev("Core CPI m/m", 0, 0.3)
        self.assertEqual(mv.lean(e, {"value": 0.32}, {"mae": 0.08}, cls)["dir"], 0)                 # moins d'une demi-erreur : pas de signal
        hot = mv.lean(e, {"value": 0.42}, {"mae": 0.08}, cls)
        self.assertEqual(hot["dir"], 1)
        self.assertIn("CHAUD", hot["text"])

    def test_upcoming_list(self):
        f = self.series()
        f["CPILFESL"] = monthly(2016, 1, index(128, [0.28 if k % 2 else 0.32 for k in range(128)]))     # un peu de bruit : erreur habituelle non nulle
        cal = {"a": self.ev("Core CPI m/m", ms(2026, 10, 14, 12), 0.2), "b": {**self.ev("ECB Press Conference", ms(2026, 10, 16, 12), 0), "country": "EUR",
                                                                               "impact": 3, "forecast": "", "fnum": None},
               "c": self.ev("Core CPI m/m", ms(2026, 11, 14, 12), 0.2)}
        cal["a"]["impact"] = 3
        up = mv.upcoming(cal, f, self.NOW, self.NOW + 7 * DAY)
        self.assertEqual([e["title"] for e in up], ["Core CPI m/m", "ECB Press Conference"])        # la publication de novembre est trop loin
        self.assertAlmostEqual(up[0]["estimate"], 0.3, delta=0.02)
        self.assertTrue(up[0]["estimateText"].endswith(" %"))
        self.assertTrue(up[0]["errorText"].startswith("± 0,0"))
        self.assertEqual(up[0]["lean"], 1)                                        # tendance 0,3 % contre un consensus de 0,2 %
        self.assertEqual(up[1]["estimate"], None)


class WeekVisionTests(unittest.TestCase):
    def test_build_and_text(self):
        now = ms(2026, 10, 12)
        f = fake_fred(now, False, False)
        v = mv.build(now, f, {}, {"meetings": fed.fallback_meetings(), "items": fed.sim_items(now, fed.fallback_meetings())},
                     {"BTC": daily(ms(2026, 1, 1), now, lambda t: 1e5 * (1 + 0.01 * math.sin(t / 3e8))),
                      "SOL": daily(ms(2026, 1, 1), now, lambda t: 150 * (1 + 0.02 * math.sin(t / 3e8)))},
                     verdict={"score": -2.0, "label": "défavorable"})
        json.dumps(v)
        self.assertEqual(v["regime"]["quad"], "slowdown")
        titles = [p["title"] for p in v["lines"]]
        self.assertEqual(titles[:2], ["Où en est l'économie américaine", "Ce que le marché attend de la Fed"])
        self.assertIn("Ce que cela veut dire pour le bitcoin et solana", titles)
        self.assertIn("Ce que la Fed a publié cette semaine", titles)
        self.assertEqual(v["label"], mv.tone_label(v["score"]))
        self.assertTrue(v["solBeta"]["beta"] > 1.5)                               # solana amplifie le bitcoin dans ces series
        self.assertIn("Solana amplifie", v["lines"][-1]["text"])
        txt = "\n".join(mv.summary_lines(v))
        self.assertIn("Vision de la semaine", txt)


class MonthTests(unittest.TestCase):
    NOW = ms(2026, 10, 12, 9)

    def test_months_recession_curve_and_banks(self):
        self.assertEqual(mm.month_key(mm.month_start(self.NOW)), "2026-10")
        self.assertEqual(mm.next_month(ms(2026, 12, 1)), ms(2027, 1, 1))
        self.assertEqual(mm.parse_month("2026-02"), ms(2026, 2, 1))
        self.assertEqual(mm.month_label(ms(2026, 8, 1)), "août 2026")
        self.assertAlmostEqual(mm.recession_prob(0.0), 29.68, places=1)          # modele de la Fed de New York
        self.assertGreater(mm.recession_prob(-1.0), 50)
        D = mv.Data({"DGS2": daily(ms(2026, 1, 1), self.NOW, lambda t: 4.0 if t < self.NOW - 91 * DAY else 3.5),
                     "DGS10": daily(ms(2026, 1, 1), self.NOW, lambda t: 4.2 if t < self.NOW - 91 * DAY else 4.0)})
        self.assertEqual(mm.curve_move(D, self.NOW)["kind"], "bull_steep")      # le 2 ans baisse plus que le 10 ans
        txt, rows = mm.parse_banks("Analyse.\n<banques>\nbanque | date | baisses | taux | 10 ans | récession | S&P | dollar | crypto | source\n"
                                   "|---|---|\nGoldman Sachs | 2026-10-03 | 2 | 3,25 | 4,10 | 30 % | 7000 | baisse | prudent | https://exemple.org/gs\n"
                                   "JPMorgan | 2026-10-01 | ? | ? | 4,25 | 35 % | ? | stable | ? | pas une adresse\n</banques>\nFin.")
        self.assertEqual(txt, "Analyse.\n\nFin.")
        self.assertEqual([r["bank"] for r in rows], ["Goldman Sachs", "JPMorgan"])
        self.assertEqual((rows[0]["cuts"], rows[0]["source"], rows[1]["cuts"], rows[1]["source"]), ("2", "https://exemple.org/gs", "", ""))
        self.assertEqual(mm.parse_banks("rien"), ("rien", []))

    def test_build_month(self):
        f = fake_fred(self.NOW, True, False)
        f["SAHMREALTIME"] = monthly(2026, 1, [0.2] * 9)
        f["T10Y3M"] = daily(ms(2024, 6, 1), self.NOW, lambda t: -0.2)
        st = {fed.FED + "/a.htm": {"t": ms(2026, 7, 29, 18), "pars": list(fed.SIM_STATEMENTS[0])},
              fed.FED + "/b.htm": {"t": ms(2026, 9, 16, 18), "pars": list(fed.SIM_STATEMENTS[1])}}
        fd = {"meetings": fed.fallback_meetings(), "items": fed.sim_items(self.NOW, fed.fallback_meetings()), "statements": st}
        im = {k: imf.simulated(k, self.NOW) for k in imf.INDICATORS}
        r = mm.build(mm.month_start(self.NOW), self.NOW, f, {}, fd, im, {}, {})
        json.dumps(r)
        self.assertTrue(r["current"] and not r["final"])
        self.assertEqual(r["statement"]["decision"]["move"], "maintien")
        self.assertIn("plus restrictif", r["statement"]["toneText"])
        self.assertTrue(r["statement"]["diff"]["added"])
        self.assertEqual(r["sep"]["years"], ["2026", "2027", "2028"])
        self.assertEqual(r["sep"]["longRun"], 3.0)
        names = [x["name"] for x in r["consensus"]]
        self.assertIn("Croissance des États-Unis en 2026", names)
        self.assertIn("Taux de la Fed fin 2026", names)
        self.assertEqual(next(x for x in r["consensus"] if x["name"] == "Croissance des États-Unis en 2026")["cols"]["imf"], 1.9)
        self.assertEqual([s["key"] for s in r["scenarios"]], ["central", "favorable", "inflation", "recession"])
        self.assertTrue(any("règle de Sahm" in t for t in r["scenarios"][3]["triggers"]))
        self.assertAlmostEqual(r["medium"]["recession"][-1]["prob"], round(mm.recession_prob(-0.2), 1))
        self.assertIn("Depuis le début du mois", " ".join(r["fed"]["text"]))
        self.assertIn("Analyse macro du mois : octobre 2026 (en cours)", r["summary"])
        self.assertIn("Scénarios et déclencheurs", r["summary"])
        past = mm.build(ms(2026, 8, 1), self.NOW, f, {}, fd, im, {}, {})
        self.assertTrue(past["reconstructed"] and past["final"])
        self.assertEqual(past["statement"]["t"], ms(2026, 7, 29, 18))             # le communique connu fin aout


class ServiceTests(unittest.TestCase):
    FIRST = ms(2026, 11, 1, 9)                                                    # 1er novembre, 9 h UTC

    def make_app(self, now):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None, make_source=lambda c: SimulatedSource(now_ms=now))
        app.service.ext.refresh(force=True)
        return app

    def test_week_month_archive_telegram_and_research(self):
        app = self.make_app(self.FIRST)
        svc = app.service
        w = svc.macro_week()
        self.assertTrue(w.get("view") and w["view"]["lines"])
        self.assertIn("Vision de la semaine", w["summary"])
        m = svc.macro_month()
        self.assertEqual((m["month"], m["current"]), ("2026-11", True))
        prev = svc.macro_month("2026-10")
        self.assertFalse(prev["current"])
        lst = svc.macro_months()
        self.assertEqual(lst["current"], "2026-11")
        self.assertEqual([x["month"] for x in lst["months"]][:2], ["2026-11", "2026-10"])
        with self.assertRaises(ValueError):
            svc.macro_month("2026-12")
        with self.assertRaises(KeyError):
            svc.macro_month("2025-01")
        sent = []

        class N:
            def send(self, text):
                sent.append(text)
        app.notifier = N()
        app.macro_month_tick(force=True)
        self.assertEqual(sent, [])                                                # desactive par defaut
        app.cfg.macro_month_telegram, app.cfg.telegram_token, app.cfg.telegram_chat_id = True, "1:x", "1"
        app.macro_month_tick(force=True)
        self.assertTrue(sent and sent[0].startswith("Analyse macro du mois : octobre 2026"))
        n = len(sent)
        app.macro_month_tick(force=True)
        self.assertEqual(len(sent), n)                                            # une seule fois
        answer = "Le mois.\n<banques>\nGoldman Sachs | 2026-10-20 | 2 | 3,25 | 4,1 | 25 % | 7200 | baisse | positif | https://exemple.org/gs\n</banques>"
        with mock.patch.object(app.assistant, "ask", return_value={"ok": True, "answer": answer, "usd": 0.31, "model": "m"}) as ask:
            res = app.macro_month_research(None)
        self.assertTrue(res["ok"])
        self.assertEqual(ask.call_args.kwargs["src"], "mois")
        self.assertEqual(ask.call_args.kwargs["web_uses"], 10)
        self.assertIn("Analyse macro du mois", ask.call_args.kwargs["context"])
        b = svc.macro_month()["banks"]
        self.assertEqual((b["text"], b["rows"][0]["bank"]), ("Le mois.", "Goldman Sachs"))
        self.assertIn("Rapports des banques", svc.macro_month()["summary"])
        self.assertTrue(svc.macro_months()["months"][0]["banks"])
        lec = svc.lecture("BTCUSDT") if svc.markets["BTCUSDT"].ready else None
        if lec:
            chip = next(c for c in lec["chips"] if c["key"] == "macroweek")
            self.assertEqual(chip["title"], "Vision macro de la semaine")

    def test_http_endpoints(self):
        import urllib.request
        from server import serve
        app = self.make_app(self.FIRST)
        app.service.refresh_all()
        httpd = serve(app)
        import threading
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=60).read())
            self.assertEqual(get("/api/macromonth?month=2026-11")["month"], "2026-11")
            self.assertEqual(get("/api/macromonths")["current"], "2026-11")
            self.assertTrue(get("/api/macroweek").get("view"))
            cfg = get("/api/config")
            self.assertGreaterEqual(cfg["api"], 24)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + "/api/macromonth?month=2020-01", timeout=30)
            self.assertEqual(e.exception.code, 404)
            st = get("/api/settings")
            self.assertFalse(st["macroMonthTelegram"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
