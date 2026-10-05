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
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=3)
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

    def test_one_idea_per_symbol_every_twelve_hours_even_on_the_other_side(self):
        self.desk.consider(sigs(idea(side="long", key="l")), MON)
        short = idea(side="short", entry=110.0, stop=112.0, tp1=106.0, tp2=102.0, key="s")
        self.assertEqual(self.desk.consider(sigs(short), MON + H), [])
        self.assertEqual(len(self.desk.consider(sigs(short), MON + 13 * H)), 1)
        both = sigs(idea(sym="SOLUSDT", side="long", entry=50.0, stop=49.0, tp1=52.0, tp2=54.0, key="a"),
                    idea(sym="SOLUSDT", side="short", entry=60.0, stop=61.0, tp1=57.0, tp2=55.0, key="b", score=70.0))
        out = self.desk.consider(both, MON + 20 * H)
        self.assertEqual([t["side"] for t in out], ["long"])                       # un seul : le meilleur score d'abord

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


if __name__ == "__main__":
    unittest.main()
