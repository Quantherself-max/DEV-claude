import tempfile
import unittest

from alerts.trades import TradeDesk
from config import Config
from engine import signals as sg

H = 3_600_000
M5 = 300_000
# lundi 29 septembre 2025 12:00 UTC
MON = 1_759_104_000_000 + 12 * H


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True, "ok"


def idea(sym="BTCUSDT", side="long", score=80.0, entry=100.0, stop=98.0, tp1=104.0, tp2=108.0, key=None, kind="rebond", etype="limite", atr=1.0):
    i = {"symbol": sym, "side": side, "kind": kind, "score": score, "entry": entry, "entryType": etype, "stop": stop, "tp1": tp1, "tp2": tp2,
         "rr1": abs(tp1 - entry) / abs(entry - stop), "rr2": abs(tp2 - entry) / abs(entry - stop) if tp2 else None, "atr": atr,
         "validHours": 48, "zone": {"lo": 99.9, "hi": 100.0, "mid": 99.95, "side": "below"}, "eligible": True, "hold": [],
         "key": key or f"{sym}-{side}-{entry}", "desc": {"headline": f"{sym} : ACHAT", "action": ["a"], "why": ["b"], "context": [], "news": [], "probs": [], "risks": ["c"]}}
    return i


def sigs(*ideas, sym="BTCUSDT"):
    by = {}
    for i in ideas:
        by.setdefault(i["symbol"], []).append(i)
    return {s: {"ready": True, "warm": True, "ideas": v} for s, v in by.items()}


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=3, signal_direction="both")
        self.n = FakeNotifier()
        self.logs = []
        self.desk = TradeDesk(self.cfg, self.n, log=self.logs.append)

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- quota ----------
    def test_new_idea_is_sent_with_week_counter(self):
        out = self.desk.consider(sigs(idea()), MON)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(self.n.sent), 1)
        self.assertIn("1/3", self.n.sent[0])
        self.assertEqual(self.desk.week(MON)["sent"], 1)
        self.assertEqual(self.logs[0]["kind"], "trade")

    def test_long_idea_is_sent_in_several_messages_without_losing_the_caution_section(self):
        i = idea()
        i["desc"]["why"] = [f"  • niveau {k} : " + "texte long " * 12 for k in range(40)]
        i["desc"]["risks"] = ["PRUDENCE-FINALE : ne risque que ce que tu acceptes de perdre."]
        out = self.desk.consider(sigs(i), MON)
        self.assertEqual(len(out), 1)
        self.assertGreaterEqual(len(self.n.sent), 2)
        self.assertTrue(all(len(m) < 4096 for m in self.n.sent))
        self.assertIn("(suite 2/", self.n.sent[1])
        self.assertIn("PRUDENCE-FINALE", self.n.sent[-1])
        self.assertEqual(self.desk.week(MON)["sent"], 1)                 # une seule idee comptee, meme en plusieurs messages
        self.assertTrue(out[0]["sent"])

    def test_one_pair_cannot_take_every_slot_of_the_week(self):
        """BTC et SOL suivis : BTC a de meilleures idees, mais au plus 3 sur 5 pour une meme paire ; SOL passe ensuite."""
        self.cfg.signal_max_week, self.cfg.signal_max_per_symbol = 5, 3
        for k in range(3):
            btc = idea("BTCUSDT", score=90.0, entry=100.0 + 10 * k, stop=98.0 + 10 * k, tp1=104.0 + 10 * k, tp2=108.0 + 10 * k)
            self.assertEqual(len(self.desk.consider(sigs(btc, idea("SOLUSDT", score=40.0, entry=20.0, stop=19.0, tp1=22.0, tp2=24.0)), MON + k * 13 * H)), 1)
            self.desk.trades[-1]["status"] = "closed"                          # (la regle « 2 idees ouvertes par paire » est testee ailleurs)
        self.assertEqual(sum(1 for t in self.desk.trades if t["symbol"] == "BTCUSDT"), 3)
        late = MON + 3 * 13 * H
        btc4 = idea("BTCUSDT", score=95.0, entry=150.0, stop=148.0, tp1=154.0, tp2=158.0)
        sol = idea("SOLUSDT", score=70.0, entry=20.0, stop=19.0, tp1=22.0, tp2=24.0)
        out = self.desk.consider(sigs(btc4, sol), late)
        self.assertEqual([t["symbol"] for t in out], ["SOLUSDT"])
        self.assertEqual(sum(1 for t in self.desk.trades if t["symbol"] == "BTCUSDT"), 3)
        self.assertIn("maximum 3 par paire", self.desk.waiting.get("why", ""))

    def test_per_pair_cap_does_not_apply_to_a_single_pair(self):
        self.cfg.signal_max_week, self.cfg.signal_max_per_symbol = 5, 2
        for k in range(4):
            i = idea("BTCUSDT", score=90.0, entry=100.0 + 10 * k, stop=98.0 + 10 * k, tp1=104.0 + 10 * k, tp2=108.0 + 10 * k)
            self.assertEqual(len(self.desk.consider(sigs(i), MON + k * 13 * H)), 1)
            self.desk.trades[-1]["status"] = "closed"

    def test_below_threshold_or_on_hold_or_not_warm_is_not_sent(self):
        low = idea(score=60.0)
        low["eligible"] = False
        self.assertEqual(self.desk.consider(sigs(low), MON), [])
        s = sigs(idea())
        s["BTCUSDT"]["warm"] = False
        self.assertEqual(self.desk.consider(s, MON), [])
        self.assertEqual(self.n.sent, [])

    def test_at_most_three_per_week_and_last_slot_needs_eight_more_points(self):
        self.desk.consider(sigs(idea(entry=100.0, stop=98.0, tp1=104.0, tp2=108.0, key="a")), MON)
        self.desk.consider(sigs(idea(sym="SOLUSDT", entry=50.0, stop=49.0, tp1=52.0, tp2=54.0, key="b")), MON + H)
        self.assertEqual(self.desk.week(MON + 2 * H)["sent"], 2)
        third_low = idea(sym="ETHUSDT", score=70.0, entry=3000.0, stop=2960.0, tp1=3080.0, tp2=3160.0, key="c")
        self.assertEqual(self.desk.consider(sigs(third_low), MON + 2 * H), [])          # 70 < 65 + 8
        self.assertIn("dernière place", self.desk.waiting["why"])
        third_ok = idea(sym="ETHUSDT", score=75.0, entry=3000.0, stop=2960.0, tp1=3080.0, tp2=3160.0, key="c")
        self.assertEqual(len(self.desk.consider(sigs(third_ok), MON + 2 * H)), 1)
        fourth = idea(sym="XRPUSDT", score=99.0, entry=2.0, stop=1.9, tp1=2.3, tp2=2.5, key="d")
        self.assertEqual(self.desk.consider(sigs(fourth), MON + 3 * H), [])
        self.assertIn("quota", self.desk.waiting["why"])
        self.assertEqual(len(self.n.sent), 3)

    def test_the_quota_resets_on_monday(self):
        for k, s in enumerate(("BTCUSDT", "SOLUSDT", "ETHUSDT")):
            self.desk.consider(sigs(idea(sym=s, score=90.0, entry=100.0 + k, key=str(k))), MON + k * H)
        self.assertEqual(self.desk.week(MON + 4 * H)["remaining"], 0)
        next_monday = sg.week_start(MON) + 7 * 24 * H
        self.assertEqual(self.desk.week(next_monday + H)["sent"], 0)
        self.assertEqual(len(self.desk.consider(sigs(idea(sym="XRPUSDT", entry=2.0, stop=1.9, tp1=2.3, tp2=2.5, key="n")), next_monday + H)), 1)

    def test_best_scores_are_sent_first_across_symbols(self):
        a, b = idea(sym="BTCUSDT", score=70.0, key="a"), idea(sym="SOLUSDT", score=88.0, entry=50.0, stop=49.0, tp1=52.0, tp2=54.0, key="b")
        self.cfg.signal_max_week = 1
        out = self.desk.consider(sigs(a, b), MON)
        self.assertEqual([t["symbol"] for t in out], ["SOLUSDT"])

    def test_one_idea_per_symbol_every_twelve_hours_and_no_opposite_bias_within_24_hours(self):
        self.assertEqual(Config().signal_direction, "both")                                 # par defaut : achats et ventes
        self.assertIsNone(self.desk.bias(MON))
        self.desk.consider(sigs(idea(side="long", key="l")), MON)
        short = idea(side="short", entry=110.0, stop=112.0, tp1=106.0, tp2=102.0, key="s")
        self.assertEqual(self.desk.consider(sigs(short), MON + H), [])
        self.assertEqual(self.desk.consider(sigs(short), MON + 13 * H), [])                 # l'achat est encore ouvert : pas de vente qui le contredit
        self.assertIn("contredirait l'achat BTCUSDT", self.desk.waiting["why"])
        self.assertIn("encore en cours", self.desk.waiting["why"])
        self.desk.trades[-1].update(status="closed", result="stop", closedAt=MON + 14 * H)
        self.assertEqual(self.desk.consider(sigs(short), MON + 20 * H), [])                 # terminee, mais moins de 24 h : toujours pas de vente
        self.assertIn("moins de 24 h", self.desk.waiting["why"])
        b = self.desk.bias(MON + 20 * H)
        self.assertEqual((b["side"], b["symbol"], b["until"], b["open"]), ("long", "BTCUSDT", MON + 24 * H, []))
        self.assertIsNone(self.desk.bias(MON + 25 * H))                                     # plus de 24 h et terminee : plus de biais impose
        weak = idea(side="short", entry=110.0, stop=112.0, tp1=106.0, tp2=102.0, key="s2", score=70.0)
        self.assertEqual(self.desk.consider(sigs(weak), MON + 25 * H), [])                  # entre 24 h et 72 h, changer de sens exige 10 points de plus
        self.assertIn("change de sens", self.desk.waiting["why"])
        out = self.desk.consider(sigs(short), MON + 26 * H)
        self.assertEqual(len(out), 1)
        self.assertTrue(self.n.sent[-1].startswith("⚠️ CHANGEMENT DE SENS sur BTCUSDT"))
        self.assertIn("un achat sur BTCUSDT", self.n.sent[-1])
        self.assertIn("REMPLACE", self.n.sent[-1])
        self.assertIn("stop touché", self.n.sent[-1])
        self.assertEqual((out[0]["flipFrom"]["side"], out[0]["flipFrom"]["symbol"]), ("long", "BTCUSDT"))
        self.assertEqual(self.desk.bias(MON + 27 * H)["side"], "short")

    def test_no_opposite_bias_across_pairs(self):
        self.desk.consider(sigs(idea(sym="BTCUSDT", side="long", key="l")), MON)
        sol_short = idea(sym="SOLUSDT", side="short", entry=60.0, stop=61.0, tp1=57.0, tp2=55.0, key="ss", score=90.0)
        self.assertEqual(self.desk.consider(sigs(sol_short), MON + H), [])                 # BTC et SOL bougent ensemble : pas de vente SOL contre l'achat BTC
        self.assertIn("SOLUSDT vente contredirait l'achat BTCUSDT", self.desk.waiting["why"])
        out = self.desk.consider(sigs(idea(sym="SOLUSDT", side="long", entry=50.0, stop=49.0, tp1=52.0, tp2=54.0, key="sl")), MON + 2 * H)
        self.assertEqual([(t["symbol"], t["side"]) for t in out], [("SOLUSDT", "long")])  # meme sens sur l'autre paire : permis
        b = self.desk.bias(MON + 3 * H)
        self.assertEqual((b["side"], b["symbol"], b["until"]), ("long", "SOLUSDT", MON + 26 * H))
        self.assertEqual({o["symbol"] for o in b["open"]}, {"BTCUSDT", "SOLUSDT"})
        self.assertFalse(b["mixed"])
        self.assertEqual(self.desk.public(MON + 3 * H)["bias"]["side"], "long")
        self.assertEqual(self.desk.history(MON + 3 * H)["bias"]["side"], "long")

    def test_one_cycle_never_sends_two_opposite_ideas(self):
        both = sigs(idea(sym="SOLUSDT", side="long", entry=50.0, stop=49.0, tp1=52.0, tp2=54.0, key="a", score=75.0),
                    idea(sym="BTCUSDT", side="short", entry=110.0, stop=112.0, tp1=106.0, tp2=102.0, key="b", score=85.0))
        out = self.desk.consider(both, MON)
        self.assertEqual([(t["symbol"], t["side"]) for t in out], [("BTCUSDT", "short")])  # la meilleure passe, l'autre sens attend
        self.assertIn("SOLUSDT achat contredirait la vente BTCUSDT", self.desk.waiting["why"])

    # ---------- doublons ----------
    def test_cooldown_duplicates_and_open_limit(self):
        self.desk.consider(sigs(idea(key="a")), MON)
        self.assertEqual(self.desk.consider(sigs(idea(key="a")), MON + H), [])                              # meme idee
        self.assertEqual(self.desk.consider(sigs(idea(entry=100.5, key="z")), MON + 2 * H), [])             # entree voisine, deja ouverte
        self.assertEqual(self.desk.consider(sigs(idea(entry=90.0, stop=88.0, tp1=94.0, tp2=98.0, key="y")), MON + 3 * H), [])   # meme sens < 12 h
        out = self.desk.consider(sigs(idea(entry=90.0, stop=88.0, tp1=94.0, tp2=98.0, key="y")), MON + 13 * H)
        self.assertEqual(len(out), 1)
        self.assertEqual(self.desk.consider(sigs(idea(side="short", entry=110.0, stop=112.0, tp1=106.0, tp2=102.0, key="w")), MON + 30 * H), [])   # 2 idees ouvertes deja

    # ---------- vie de l'idee ----------
    def create(self, **kw):
        return self.desk.consider(sigs(idea(**kw)), MON)[0]

    def candles(self, start, rows):
        return [(start + k * M5, h, l, c) for k, (h, l, c) in enumerate(rows)]

    def test_limit_fill_then_targets(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(101.0, 100.5, 100.8)]), t0 + M5)
        self.assertEqual(tr["status"], "pending")
        self.desk.track("BTCUSDT", self.candles(t0 + M5, [(100.8, 99.9, 100.2)]), t0 + 2 * M5)
        self.assertEqual(tr["status"], "active")
        self.assertIn("exécuté", self.n.sent[-1])
        self.desk.track("BTCUSDT", self.candles(t0 + 2 * M5, [(104.2, 100.0, 104.0)]), t0 + 3 * M5)
        self.assertEqual(tr["status"], "tp1")
        self.assertIn("Objectif 1 atteint", self.n.sent[-1])
        self.assertIn("remonte ton stop", self.n.sent[-1])
        self.desk.track("BTCUSDT", self.candles(t0 + 3 * M5, [(108.5, 104.0, 108.2)]), t0 + 4 * M5)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "tp2"))
        self.assertIn("Objectif 2", self.n.sent[-1])

    def test_stop_after_fill(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(100.5, 99.5, 100.0), (100.2, 99.0, 99.2), (99.0, 97.9, 98.2)]), t0 + 4 * M5)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "stop"))
        self.assertIn("Stop touché", self.n.sent[-1])

    def test_fill_and_stop_in_the_same_candle_is_a_stop(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(100.6, 97.5, 98.0)]), t0 + M5)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "stop"))

    def test_target_in_the_fill_candle_is_ignored(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(105.0, 99.5, 104.5)]), t0 + M5)
        self.assertEqual(tr["status"], "active")                        # execute, mais l'objectif n'est pas compte dans la meme bougie

    def test_breakeven_after_first_target(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(100.4, 99.8, 100.0), (104.5, 100.0, 104.0), (104.0, 99.9, 100.1)]), t0 + 4 * M5)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "tp1_be"))

    def test_missed_when_the_target_is_reached_without_fill(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(101.0, 100.5, 100.8), (104.5, 101.0, 104.0)]), t0 + 3 * M5)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "missed"))
        self.assertIn("Retire ton ordre", self.n.sent[-1])

    def test_expiry_of_a_pending_order(self):
        tr = self.create()
        self.desk.track("BTCUSDT", [], MON + 49 * H)
        self.assertEqual((tr["status"], tr["result"]), ("closed", "expired"))

    def test_candles_before_creation_are_ignored(self):
        tr = self.create()
        self.desk.track("BTCUSDT", self.candles(MON - 6 * M5, [(100.0, 90.0, 95.0)] * 3), MON + M5)
        self.assertEqual(tr["status"], "pending")

    def test_market_entry_is_active_immediately(self):
        tr = self.create(etype="marché", kind="reprise")
        self.assertEqual(tr["status"], "active")
        self.assertEqual(tr["filledAt"], MON)

    def test_short_trade(self):
        tr = self.desk.consider(sigs(idea(side="short", entry=100.0, stop=102.0, tp1=96.0, tp2=92.0)), MON)[0]
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(100.2, 99.0, 99.5), (99.5, 95.5, 96.0)]), t0 + 3 * M5)
        self.assertEqual(tr["status"], "tp1")

    # ---------- persistance et statistiques ----------
    def test_persistence_and_stats(self):
        tr = self.create()
        t0 = MON + M5
        self.desk.track("BTCUSDT", self.candles(t0, [(100.4, 99.8, 100.0), (99.9, 97.5, 98.0)]), t0 + 3 * M5)
        again = TradeDesk(self.cfg, FakeNotifier())
        self.assertEqual(len(again.trades), 1)
        self.assertEqual(again.trades[0]["result"], "stop")
        st = again.stats()
        self.assertEqual((st["ideas"], st["executed"], st["stop"]), (1, 1, 1))
        self.assertAlmostEqual(st["r"], -1.0)
        pub = again.public(MON + H)
        self.assertEqual(pub["week"]["sent"], 1)
        self.assertEqual(pub["trades"][0]["symbol"], "BTCUSDT")
        self.assertNotIn("text", pub["trades"][0])

    def test_simulated_data_uses_its_own_folder(self):
        cfg = Config(source="simulated", data_dir=self.tmp.name)
        d = TradeDesk(cfg, FakeNotifier())
        d.consider(sigs(idea()), MON)
        self.assertTrue((d.dir / "trades.json").exists())
        self.assertEqual(len(TradeDesk(self.cfg, FakeNotifier()).trades), 0)




class LongOnlyTests(unittest.TestCase):
    """Tu ne trades qu'a l'achat : les configurations de vente deviennent des alertes de prudence, hors quota, suivies pour l'historique."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=3, signal_direction="long")
        self.n = FakeNotifier()
        self.desk = TradeDesk(self.cfg, self.n)

    def tearDown(self):
        self.tmp.cleanup()

    def short(self, **kw):
        return idea(**{"side": "short", "entry": 110.0, "stop": 112.0, "tp1": 106.0, "tp2": 102.0, "key": "s", **kw})

    def test_sell_setup_becomes_an_alert_outside_the_quota(self):
        self.desk.consider(sigs(idea(side="long", key="l")), MON)
        out = self.desk.consider(sigs(self.short()), MON + H)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["mode"], "alerte")
        msg = self.n.sent[-1]
        self.assertTrue(msg.startswith("🛡 Alerte pour tes longs · BTCUSDT"))
        self.assertIn("ce n'est pas une idée de vente", msg)
        self.assertIn("repasse au-dessus de 112,00", msg)
        self.assertIn("Ton idée d'achat du", msg)
        self.assertEqual(self.desk.week(MON + H)["sent"], 1)                     # l'alerte ne compte pas dans les 5 idees de la semaine
        self.assertEqual(self.desk.consider(sigs(self.short(key="s3", entry=111.0)), MON + 5 * H), [])     # une alerte par paire et par 24 h
        self.assertEqual(len(self.desk.consider(sigs(self.short(key="s4", entry=111.0)), MON + 26 * H)), 1)
        self.assertEqual(self.desk.stats()["ideas"], 1)
        self.assertEqual(self.desk.stats()["alerts"]["n"], 2)

    def test_long_ideas_are_unchanged_and_low_score_alerts_are_skipped(self):
        self.assertEqual(self.desk.consider(sigs(self.short(score=50.0)), MON), [])
        out = self.desk.consider(sigs(idea(side="long")), MON + H)
        self.assertEqual(out[0]["side"], "long")
        self.assertNotIn("mode", out[0])

    def test_alert_outcome_is_tracked_silently(self):
        tr = self.desk.consider(sigs(self.short(etype="marché")), MON)[0]
        before = len(self.n.sent)
        self.desk.track("BTCUSDT", [(MON + M5, 110.5, 105.5, 106.0)], MON + 2 * M5)
        self.assertEqual(len(self.n.sent), before)                              # pas de message de suivi pour une alerte
        h = self.desk.history(MON + 3 * M5)
        row = next(r for r in h["trades"] if r["id"] == tr["id"])
        self.assertTrue(row["verdict"])                                         # le prix a baisse jusqu'au premier objectif : l'alerte avait raison
        self.assertIsNone(row["r"])
        self.assertEqual(h["stats"]["alerts"]["right"], 1)

    def test_history_rows_have_results(self):
        tr = self.desk.consider(sigs(idea(side="long", etype="marché")), MON)[0]
        self.desk.track("BTCUSDT", [(MON + M5, 101.0, 97.5, 98.0)], MON + 2 * M5)
        row = self.desk.history(MON + 3 * M5)["trades"][0]
        self.assertEqual(row["id"], tr["id"])
        self.assertEqual(row["r"], -1.0)
        self.assertEqual(row["resultText"], "stop touché")
        self.assertIn("Idée de trade", row["text"])


if __name__ == "__main__":
    unittest.main()
