"""V24 : historique des idees compris (journal detaille, recit en clair, statistiques par categorie, trajet du prix)."""
from __future__ import annotations
import copy
import json
import random
import tempfile
import time
import unittest
from pathlib import Path

from alerts import journal
from alerts.trades import MAX_HOLD_H, OPEN, TradeDesk
from config import Config
from data import reports as reports_mod
from tests.test_trades import MON, H, M5, FakeNotifier, idea, sigs

ROOT = Path(__file__).resolve().parent.parent


def bars(prices, start=MON + M5, spread=0.2):
    """Bougies 5 min (t, haut, bas, cloture) : cloture = prix donne, haut / bas a +/- spread."""
    return [(start + k * M5, p + spread, p - spread, p) for k, p in enumerate(prices)]


class DeskBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=20, signal_max_per_symbol=20,
                          signal_direction="both")
        self.n = FakeNotifier()
        self.desk = TradeDesk(self.cfg, self.n)

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, t0=MON, **kw):
        i = idea(**kw)
        i.setdefault("price", kw.get("entry", 100.0) + (1.2 if kw.get("side", "long") == "long" else -1.2))
        self.desk.consider(sigs(i), t0)
        return self.desk.trades[-1]


class JournalFactsTests(DeskBase):
    def test_limit_long_records_key_moments_extremes_and_exit_caps(self):
        tr = self.send()
        # 101 -> execution a 100 (bas 99,7) -> 102,5 -> 99,2 -> objectif 1 (104,5) -> retour a l'entree
        cs = bars([101.0, 100.6, 99.9, 100.8, 101.7, 102.5, 101.0, 99.2, 100.4, 102.0, 103.2, 104.5, 103.0, 101.5, 99.9, 101.0])
        self.desk.track("BTCUSDT", cs, cs[-1][0] + 2 * M5)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "tp1_be"))
        self.assertEqual(tr["filledAt"], cs[2][0])
        self.assertEqual(tr["tp1At"], cs[11][0])
        self.assertEqual(tr["endAt"], cs[14][0])                              # heure de la bougie, pas celle du constat
        self.assertGreater(tr["closedAt"], tr["endAt"])
        self.assertEqual(tr["best"], {"p": 104.7, "t": cs[11][0]})
        self.assertEqual(tr["worst"], {"p": 99.0, "t": cs[7][0]})
        self.assertAlmostEqual(tr["near"]["p"], 99.7)
        self.assertEqual(tr["v"], 2)

    def test_stop_candle_counts_the_stop_price_as_the_worst(self):
        tr = self.send()
        cs = bars([101.0, 99.9, 100.5, 101.2, 99.0, 97.0])                # la derniere bougie descend a 96,8 : au-dela du stop (98)
        self.desk.track("BTCUSDT", cs, cs[-1][0] + M5)
        self.assertEqual(tr["result"], "stop")
        self.assertEqual(tr["worst"]["p"], 98.0)                              # ce qui va au-dela du stop s'est passe apres la sortie
        self.assertAlmostEqual(journal.r_at(tr, tr["worst"]["p"]), -1.0)
        self.assertAlmostEqual(tr["best"]["p"], 101.4)

    def test_take_profit_2_caps_the_best_at_the_target(self):
        tr = self.send()
        cs = bars([101.0, 99.9, 102.0, 104.4, 106.0, 108.5])
        self.desk.track("BTCUSDT", cs, cs[-1][0] + M5)
        self.assertEqual(tr["result"], "tp2")
        self.assertEqual(tr["best"]["p"], 108.0)
        self.assertEqual(tr["tp1At"], cs[3][0])

    def test_unfilled_ideas_keep_the_closest_approach_and_end_time(self):
        tr = self.send()                                                        # ordre a 100, prix 101,2
        cs = bars([101.0, 100.5, 100.4, 101.5, 103.0, 104.3])                  # au plus pres 100,2 puis objectif 1 sans execution
        self.desk.track("BTCUSDT", cs, cs[-1][0] + M5)
        self.assertEqual(tr["result"], "missed")
        self.assertAlmostEqual(tr["near"]["p"], 100.2)
        self.assertEqual(tr["endAt"], cs[5][0])
        self.assertNotIn("best", tr)
        ex = self.send(t0=MON + 13 * H, entry=90.0, stop=88.0, tp1=94.0, tp2=98.0, key="b")
        cs2 = bars([92.0] * 20, start=MON + 13 * H + M5)
        self.desk.track("BTCUSDT", cs2, ex["validUntil"] + M5)
        self.assertEqual(ex["result"], "expired")
        self.assertEqual(ex["endAt"], ex["validUntil"])
        self.assertAlmostEqual(ex["near"]["p"], 91.8)

    def test_seven_day_limit_keeps_the_price_at_that_moment(self):
        tr = self.send(etype="marché")
        cs = bars([101.0 + 0.001 * k for k in range(30)])
        self.desk.track("BTCUSDT", cs, tr["filledAt"] + MAX_HOLD_H * H + M5)
        self.assertEqual(tr["result"], "expired_active")
        self.assertEqual(tr["endAt"], tr["filledAt"] + MAX_HOLD_H * H)
        self.assertAlmostEqual(tr["exitPx"], cs[-1][3])
        self.assertAlmostEqual(journal.latent_r(tr, tr["exitPx"]), (cs[-1][3] - 100.0) / 2.0)

    def test_context_at_send_time_is_recorded(self):
        i = idea()
        i.update(price=101.2, align=-1, tp1Kind="pool", st={"S": 9.4, "n": 6}, warn=["annonce majeure dans 10 h"],
                 comps=[{"label": "Liquidité", "pts": 18.04, "max": 30, "note": "poche dans la zone"}],
                 probs={"fill": {"p24": 0.55}, "plan": {"tp": {"p": 0.41}}})
        i["desc"]["leverage"] = {"lev": 7}
        self.desk.consider(sigs(i), MON)
        tr = self.desk.trades[-1]
        self.assertEqual((tr["px0"], tr["align"], tr["tp1Kind"], tr["zoneS"], tr["zoneN"], tr["lev"], tr["pFill"], tr["pTp"]),
                         (101.2, -1, "pool", 9.4, 6, 7, 0.55, 0.41))
        self.assertEqual(tr["comps"], [{"label": "Liquidité", "pts": 18.0, "max": 30, "note": "poche dans la zone"}])
        self.assertEqual(tr["warn"], ["annonce majeure dans 10 h"])


class BackfillTests(DeskBase):
    def legacy(self, tr):
        old = copy.deepcopy(tr)
        for k in ("best", "worst", "near", "tp1At", "endAt", "exitPx", "v"):
            old.pop(k, None)
        return old

    def test_replay_gives_exactly_the_live_facts_without_sending_anything(self):
        rnd = random.Random(5)
        p, cs = 100.0, []
        for k in range(-30, 2500):
            p *= 1 + rnd.gauss(0, 0.004)
            cs.append((MON + k * M5, p * (1 + abs(rnd.gauss(0, 0.002))), p * (1 - abs(rnd.gauss(0, 0.002))), p))
        for j in range(8):
            t0 = MON + j * 25 * H
            px = next(c[3] for c in cs if c[0] >= t0)
            sgn = 1 if j % 2 == 0 else -1
            e = px * (1 - sgn * 0.003) if j % 3 else px
            self.desk.consider(sigs(idea(side="long" if sgn > 0 else "short", entry=e, stop=e * (1 - sgn * 0.01), tp1=e * (1 + sgn * 0.015),
                                         tp2=e * (1 + sgn * 0.03), etype="limite" if j % 3 else "marché", key=f"k{j}")), t0)
            for q in range(1, 100):                                             # suivi en direct, par paquets de 15 minutes
                now = t0 + q * 15 * 60_000
                opens = [x["checked"] for x in self.desk.trades if x["status"] in OPEN]
                if opens:
                    self.desk.track("BTCUSDT", [c for c in cs if min(opens) - M5 <= c[0] <= now - M5], now)
        now = cs[-1][0] + M5
        live = self.desk.trades
        self.assertGreaterEqual(len(live), 5)
        d2 = TradeDesk(self.cfg, FakeNotifier())
        d2.trades = [self.legacy(t) for t in live]
        self.assertEqual(d2.backfill("BTCUSDT", cs, now), len(live))
        self.assertEqual(d2.notifier.sent, [])                                  # aucun message pendant le rejeu
        for a, b in zip(live, d2.trades):
            self.assertEqual(b["replay"], "ok")
            self.assertEqual((a["status"], a["result"], a.get("filledAt")), (b["status"], b["result"], b.get("filledAt")))
            for k in ("best", "worst", "near", "tp1At", "endAt"):
                self.assertEqual(a.get(k), b.get(k), (a["result"], k))
        self.assertEqual(d2.backfill("BTCUSDT", cs, now), 0)                   # une seule fois

    def test_replay_never_changes_a_recorded_result(self):
        tr = self.send()
        cs = bars([101.0, 99.9, 100.5, 101.2, 99.0, 97.0])
        self.desk.track("BTCUSDT", cs, cs[-1][0] + M5)
        old = self.legacy(tr)
        old["result"] = "tp2"                                                   # journal qui ne correspond pas aux bougies
        d2 = TradeDesk(self.cfg, FakeNotifier())
        d2.trades = [old]
        d2.backfill("BTCUSDT", [(MON - M5, 101.2, 100.8, 101.0)] + cs, cs[-1][0] + M5)
        self.assertEqual((old["result"], old["replay"], old["v"]), ("tp2", "different", 2))
        self.assertNotIn("best", old)

    def test_too_old_ideas_are_marked_and_recent_ones_wait_for_their_candles(self):
        tr = self.send()
        cs = bars([101.0, 99.9, 100.5, 101.2, 99.0, 97.0])
        self.desk.track("BTCUSDT", cs, cs[-1][0] + M5)
        recent, ancient = self.legacy(tr), self.legacy(tr)
        d2 = TradeDesk(self.cfg, FakeNotifier())
        d2.trades = [recent]
        later = cs[3:]                                                          # les bougies commencent apres l'envoi
        self.assertEqual(d2.backfill("BTCUSDT", later, MON + 10 * H), 0)
        self.assertNotIn("v", recent)                                           # on attendra les bougies plus anciennes
        d2.trades = [ancient]
        d2.backfill("BTCUSDT", later, MON + 80 * 24 * H)
        self.assertEqual((ancient["v"], ancient["replay"]), (2, "absent"))
        st = journal.story(ancient)
        self.assertTrue(any("70 jours" in x for x in st["facts"]))


class StoryTests(DeskBase):
    def run_path(self, prices, **kw):
        tr = self.send(**kw)
        cs = bars(prices, start=tr["created"] + M5)
        self.desk.track("BTCUSDT", cs, cs[-1][0] + M5)
        return tr, journal.story(tr, lev=10)

    @staticmethod
    def text(st):
        return " ".join(x if isinstance(x, str) else x["text"] for v in st.values() for x in v)

    def test_tp1_then_breakeven_is_explained_in_plain_words(self):
        tr, st = self.run_path([101.0, 99.9, 102.0, 104.3, 102.0, 99.9])
        self.assertEqual(tr["result"], "tp1_be")
        self.assertEqual([e["kind"] for e in st["events"]], ["sent", "fill", "tp1", "end"])
        self.assertIn("Résultat : +1,00 fois le risque = moitié à l'objectif 1 (½ × 2,00) + moitié à l'entrée (½ × 0).", st["result"])
        self.assertTrue(any("avec un levier de 10, +20,0 % sur la marge engagée" in x for x in st["result"]))
        self.assertTrue(any(x.startswith("Pendant la position : au mieux") for x in st["facts"]))
        self.assertTrue(st["lesson"])
        txt = self.text(st)
        for bad in (" R ", "TP1", "TP2", " SL", "MFE", "MAE", " h ", " min "):     # pas d'abreviation
            self.assertNotIn(bad, txt + " ")
        self.assertNotRegex(txt, r"\d\.\d")                                      # virgule decimale

    def test_stop_lesson_depends_on_how_far_the_price_went_first(self):
        tr, st = self.run_path([101.0, 99.9, 100.2, 99.0, 97.5])
        self.assertEqual(tr["result"], "stop")
        self.assertIn("Résultat : −1 fois le risque (le stop prévu).", st["result"])
        self.assertTrue(any("la zone n'a pas tenu" in x for x in st["lesson"]))
        self.assertTrue(any("moins d'une heure" in x for x in st["lesson"]))
        tr2, st2 = self.run_path([101.0, 99.9, 102.0, 103.4, 101.0, 97.5], t0=MON + 13 * H, key="x2")
        self.assertEqual(tr2["result"], "stop")
        self.assertTrue(any("tout près de l'objectif 1" in x for x in st2["lesson"]))

    def test_missed_expired_open_and_alert_texts(self):
        tr, st = self.run_path([101.0, 100.5, 100.4, 101.5, 103.0, 104.3])
        self.assertEqual(tr["result"], "missed")
        self.assertIn("Résultat : 0 (ordre jamais exécuté, aucune position).", st["result"])
        self.assertTrue(any("sans l'atteindre" in x for x in st["facts"]))
        op = self.send(t0=MON + 13 * H, etype="marché", key="o")
        self.desk.track("BTCUSDT", bars([100.5, 101.0], start=MON + 13 * H + M5), MON + 13 * H + 3 * M5)
        so = journal.story(op, price_now=101.0)
        self.assertEqual(so["events"][-1]["kind"], "now")
        self.assertIn("au prix actuel, +0,50 fois le risque (pas encore compté)", so["result"][0])
        al = {**op, "mode": "alerte", "status": "closed", "result": "stop", "id": "a"}
        sa = journal.story(al)
        self.assertTrue(sa["result"][0].startswith("Alerte fausse"))
        self.assertEqual(sa["lesson"], [])

    def test_history_rows_carry_story_measures_and_summary(self):
        self.run_path([101.0, 99.9, 102.0, 104.3, 102.0, 99.9])
        h = self.desk.history(MON + 2 * H, lev=10, expect={"BTCUSDT": None}, prices={"BTCUSDT": 101.0})
        row = h["trades"][0]
        for k in ("story", "outcome", "rBest", "rWorst", "riskPct", "held", "endAt", "tp1At", "best", "worst", "comps"):
            self.assertIn(k, row)
        self.assertEqual(row["outcome"], "win")
        self.assertAlmostEqual(row["riskPct"], 2.0)
        self.assertEqual(row["held"], row["endAt"] - row["filledAt"])
        s = h["summary"]
        self.assertEqual((s["n"], s["decided"], s["wins"]), (1, 1, 1))
        self.assertIn("trop peu pour juger", s["verdict"])
        json.dumps(h)                                                           # tout est serialisable


class SummaryTests(unittest.TestCase):
    @staticmethod
    def trade(i, result, rr1=2.0, rr2=4.0, side="long", sym="BTCUSDT", score=70.0, align=1, filled=True, **kw):
        t0 = MON + i * 30 * H
        t = {"id": f"t{i}", "symbol": sym, "side": side, "kind": "rebond", "score": score, "entry": 100.0, "stop": 98.0 if side == "long" else 102.0,
             "tp1": 104.0, "tp2": 108.0, "rr1": rr1, "rr2": rr2, "entryType": "limite", "created": t0, "validUntil": t0 + 48 * H,
             "status": "closed" if result else "active", "result": result, "filledAt": t0 + H if filled else None, "endAt": t0 + 5 * H,
             "closedAt": t0 + 5 * H, "align": align, "checked": t0 + 5 * H}
        t.update(kw)
        return t

    def test_totals_drawdown_streaks_and_groups(self):
        res = ["tp2", "stop", "stop", "stop", "tp1_be", "stop", "tp2"]
        ts = [self.trade(i, r, sym="SOLUSDT" if i % 2 else "BTCUSDT", score=62 + 5 * i) for i, r in enumerate(res)]
        ts.append(self.trade(9, "missed", filled=False))
        ts.append(self.trade(10, None))
        s = journal.summary(ts)
        self.assertEqual((s["n"], s["decided"], s["wins"], s["losses"], s["open"], s["missed"]), (9, 7, 3, 4, 1, 1))
        self.assertAlmostEqual(s["r"], 3.0 - 3.0 + 1.0 - 1.0 + 3.0)
        self.assertAlmostEqual(s["maxDrawdown"], 3.0)                          # +3 puis trois stops
        self.assertEqual((s["lossStreak"], s["streak"]), (3, 1))
        self.assertEqual([p["cum"] for p in s["curve"]], [3.0, 2.0, 1.0, 0.0, 1.0, 0.0, 3.0])
        pair = next(g for g in s["groups"] if g["key"] == "pair")["rows"]
        self.assertEqual(sorted((r["label"], r["n"], r["decided"]) for r in pair), [("BTC", 6, 4), ("SOL", 3, 3)])
        score = next(g for g in s["groups"] if g["key"] == "score")["rows"]
        self.assertEqual(score[0]["label"], "90 et plus")                       # du meilleur au moins bon
        month = next(g for g in s["groups"] if g["key"] == "month")["rows"]
        self.assertTrue(all(r["label"].split(" ")[0] in journal.MONTHS for r in month))
        self.assertIn("trop peu pour juger", s["verdict"])

    def test_verdict_after_thirty_ideas_uses_the_interval(self):
        win = [self.trade(i, "tp2" if i % 3 else "stop") for i in range(36)]      # +3 deux fois sur trois
        s = journal.summary(win)
        self.assertGreater(s["avgLo"], 0)
        self.assertIn("Avantage démontré", s["verdict"])
        lose = [self.trade(i, "stop" if i % 4 else "tp1_be", rr1=1.0) for i in range(40)]
        self.assertIn("Perte démontrée", journal.summary(lose)["verdict"])
        mixed = [self.trade(i, "stop" if i % 3 == 0 else "tp1_be", rr1=1.0) for i in range(30)]   # moyenne 0
        self.assertIn("Pas d'avantage démontré", journal.summary(mixed)["verdict"])

    def test_calibration_compares_announced_and_real(self):
        ts = [self.trade(i, "tp2" if i < 2 else "stop", pTp=0.4, pFill=0.5) for i in range(5)]
        ts.append(self.trade(7, "expired", filled=False, pFill=0.5))
        c = journal.summary(ts)["calibration"]
        self.assertEqual(c["tp1"]["n"], 5)
        self.assertAlmostEqual(c["tp1"]["announced"], 0.4)
        self.assertAlmostEqual(c["tp1"]["real"], 0.4)
        self.assertEqual(c["fill"]["n"], 6)
        self.assertAlmostEqual(c["fill"]["real"], 5 / 6)


class PathTests(unittest.TestCase):
    def test_bar_size_and_resampling(self):
        self.assertEqual(journal.bar_for(0, 10 * H, 300_000), 300_000)
        self.assertEqual(journal.bar_for(0, 3 * 24 * H, 300_000), 1_800_000)
        self.assertEqual(journal.bar_for(0, 3 * 24 * H, 3_600_000), 3_600_000)
        rows = [(k * M5, 1.0 + k, 2.0 + k, 0.5 + k, 1.5 + k) for k in range(6)]
        self.assertEqual(journal._resample(rows, 900_000), [[0, 1.0, 4.0, 0.5, 3.5], [900_000, 4.0, 7.0, 3.5, 6.5]])

    def test_path_events_and_what_happened_next(self):
        t = SummaryTests.trade(0, "stop", px0=101.0, best={"p": 101.0, "t": MON + 2 * H}, worst={"p": 98.0, "t": MON + 5 * H})
        rows = [(MON - 6 * H + k * M5, 100.0, 100.3, 99.7, 100.0) for k in range(int(11 * H / M5))]
        rows += [(MON + 5 * H + k * M5, 100.0, 104.5 if k == 30 else 100.2, 99.5, 100.0) for k in range(1, 300)]
        p = journal.path(t, rows, 300_000, MON + 40 * H)
        kinds = [e["kind"] for e in p["events"]]
        self.assertEqual(kinds[:3], ["sent", "fill", "end"])
        self.assertIn("best", kinds)
        self.assertTrue(all(b[0] % p["bar"] == 0 for b in p["bars"]))
        self.assertEqual(p["levels"]["stop"], 98.0)
        self.assertIn("Après le stop, le prix a atteint l'objectif 1", p["after"][0])
        self.assertIn("2 heures et 30 minutes plus tard", p["after"][0])
        miss = SummaryTests.trade(1, "missed", filled=False)
        miss["endAt"] = MON + 5 * H
        later = [(MON + 5 * H + k * M5, 100.0, 101.0, 99.9 if k < 10 else 97.0, 100.0) for k in range(1, 40)]
        self.assertIn("ensuite il a touché le stop avant l'objectif 1", journal.after(miss, later, MON + 10 * H)[0])


class ExpectAndServerTests(unittest.TestCase):
    def test_backtest_expectation_per_pair(self):
        dirs = [ROOT / "reports"]
        sol = reports_mod.terminal_expect(dirs, "SOLUSDT")
        self.assertEqual((sol["proxy"], sol["label"][:3]), (False, "SOL"))
        self.assertTrue(0 < sol["winRate"] < 1 and sol["n"] > 100 and sol["recent"]["n"] > 0)
        self.assertTrue(reports_mod.terminal_expect(dirs, "ETHUSDT")["proxy"])
        self.assertIsNone(reports_mod.terminal_expect([ROOT / "nope"], "SOLUSDT"))

    def test_history_endpoints(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from data.simulated import SimulatedSource
        from server import App, make_handler
        now = 1_790_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=None, make_source=lambda c: SimulatedSource(now_ms=now))
            app.service.refresh_all()

            def settle():                                                   # le fil des donnees externes ecrit dans le dossier : attendre qu'il ait fini
                deadline = time.time() + 60
                while app.service._ext_running and time.time() < deadline:
                    time.sleep(0.05)
            settle()
            cs = [(k.t, k.h, k.l, k.c) for k in app.service.markets["BTCUSDT"].store.fine_m5()]
            t0 = cs[-400][0]
            px = cs[-401][3]
            i = idea(entry=px, stop=px * 0.99, tp1=px * 1.015, tp2=px * 1.03, etype="marché", key="srv")
            app.desk._quiet = True
            app.desk._create("BTCUSDT", i, t0, 1)
            app.desk.track("BTCUSDT", [c for c in cs if c[0] >= t0], now)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                with urllib.request.urlopen(url + "/api/history", timeout=20) as r:
                    h = json.loads(r.read())
                self.assertTrue({"trades", "summary", "readings", "stats"} <= set(h))
                tid = h["trades"][0]["id"]
                self.assertIn("story", h["trades"][0])
                with urllib.request.urlopen(url + "/api/history/trade?id=" + tid, timeout=20) as r:
                    d = json.loads(r.read())
                self.assertTrue(d["bars"] and d["bar"] >= 300_000 and d["events"][0]["kind"] == "sent")
                self.assertEqual(d["source"], "5 minutes")
                self.assertTrue(all(d["from"] <= b[0] <= d["to"] for b in d["bars"]))
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(url + "/api/history/trade?id=nope", timeout=20)
                self.assertEqual(e.exception.code, 404)
            finally:
                httpd.shutdown()
                httpd.server_close()
                settle()


if __name__ == "__main__":
    unittest.main()
