"""V25.1 : une seule direction a la fois, sans delai de 24 h ; une idee exceptionnelle dans l'autre sens dit d'abord de fermer
l'idee en cours (gain ou perte chiffre) ; rappel pour un ordre expire qui a pu etre pris quand meme ; journal et mesure sur l'historique."""
import tempfile
import unittest
from pathlib import Path

from alerts import journal
from alerts.trades import TradeDesk, r_of, SWITCH_MIN, SWITCH_EXTRA
from config import Config
from engine import sigtest
from engine.atr import Candle
from tests.test_trades import FakeNotifier, idea, H, M5, MON


def market(px, *ideas, **extra):
    """Signaux par paire avec le prix du moment ; extra : {symbole: prix} pour une paire sans idee."""
    out = {}
    for i in ideas:
        out.setdefault(i["symbol"], {"ready": True, "warm": True, "ideas": [], "price": px.get(i["symbol"])})["ideas"].append(i)
    for s, p in extra.items():
        out.setdefault(s, {"ready": True, "warm": True, "ideas": [], "price": p})
    return out


def short(sym="BTCUSDT", score=90.0, key="s", entry=101.0):
    return idea(sym=sym, side="short", score=score, entry=entry, stop=entry + 2.0, tp1=entry - 4.0, tp2=entry - 8.0, key=key, etype="marché")


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=5, signal_direction="both")
        self.n = FakeNotifier()
        self.desk = TradeDesk(self.cfg, self.n, log=lambda x: None)

    def tearDown(self):
        self.tmp.cleanup()

    def long_filled(self, sym="BTCUSDT", score=70.0, entry=100.0, key="l"):
        self.desk.consider(market({sym: entry + 1.0}, idea(sym=sym, side="long", score=score, entry=entry, stop=entry - 2.0, tp1=entry + 4.0, tp2=entry + 8.0, key=key)), MON)
        tr = self.desk.trades[-1]
        self.desk.track(sym, [(MON + M5, entry + 0.5, entry - 0.1, entry + 0.2)], MON + 2 * M5)          # ordre execute
        self.assertEqual(tr["status"], "active")
        return tr

    def test_constants(self):
        self.assertEqual((SWITCH_MIN, SWITCH_EXTRA), (80.0, 15.0))
        self.assertEqual(Config().signal_switch, "strong")

    def test_exceptional_opposite_idea_says_close_the_long_first_with_its_gain(self):
        old = self.long_filled()
        out = self.desk.consider(market({"BTCUSDT": 101.0}, short(score=90.0)), MON + 13 * H)            # 90 >= max(80, 70 + 15)
        self.assertEqual(len(out), 1)
        msg = self.n.sent[-1]
        self.assertTrue(msg.startswith("🔁 CHANGEMENT DE SENS · BTCUSDT VENTE"), msg[:80])
        self.assertIn("FERME TON ACHAT BTC :", msg)
        self.assertIn("ferme-le maintenant au prix du marché, vers 101,00 : +1,00 % sur le prix (+10,0 % avec ton levier ×10)", msg)
        self.assertIn("soit +0,50 fois le risque au total → clôture en gain", msg)
        self.assertIn("qualité de 90/100, contre 70/100", msg)
        self.assertIn("ne garde jamais les deux en même temps", msg)
        # l'idee en cours est close dans le journal au prix conseille
        self.assertEqual((old["status"], old["result"], old["exitPx"], old["switchTo"], old["switchState"]), ("closed", "switch", 101.0, out[0]["id"], "active"))
        self.assertAlmostEqual(r_of(old), 0.5)
        self.assertEqual(out[0]["switchFrom"][0]["id"], old["id"])
        self.assertAlmostEqual(out[0]["switchFrom"][0]["r"], 0.5)
        st = self.desk.stats()
        self.assertEqual(st["switch"], 1)
        self.assertAlmostEqual(st["r"], 0.5)
        self.assertEqual(self.desk.bias(MON + 14 * H)["side"], "short")
        h = self.desk.history(MON + 14 * H)
        rows = {r["id"]: r for r in h["trades"]}
        ro = rows[old["id"]]
        self.assertEqual((ro["outcome"], ro["resultText"]), ("win", "fermée pour changer de sens"))
        self.assertIn("Fermée au prix du marché, vers 101,00", ro["story"]["events"][-1]["text"])
        self.assertIn("+0,50 fois le risque", ro["story"]["result"][0])
        self.assertTrue(any("Changement de sens" in w for w in rows[out[0]["id"]]["story"]["why"]))
        self.assertEqual((h["summary"]["switched"], h["summary"]["decided"]), (1, 1))

    def test_losing_long_is_closed_at_a_loss(self):
        old = self.long_filled()
        self.desk.consider(market({"BTCUSDT": 99.0}, short(score=90.0, entry=99.0)), MON + 13 * H)
        msg = self.n.sent[-1]
        self.assertIn("soit -0,50 fois le risque au total → clôture en perte", msg)
        self.assertIn("-1,00 % sur le prix", msg)
        self.assertAlmostEqual(r_of(old), -0.5)
        self.assertEqual(journal.outcome(old), "loss")

    def test_pending_order_is_cancelled_not_closed(self):
        self.desk.consider(market({"BTCUSDT": 101.0}, idea(side="long", score=70.0, key="l")), MON)
        old = self.desk.trades[-1]
        self.assertEqual(old["status"], "pending")
        self.desk.consider(market({"BTCUSDT": 101.0}, short(score=90.0)), MON + 13 * H)
        self.assertIn("pas encore exécuté d'après mes données → ANNULE-LE (ni gain ni perte)", self.n.sent[-1])
        self.assertEqual((old["result"], r_of(old), journal.outcome(old)), ("switch_cancel", 0.0, "unfilled"))
        self.assertIn("Résultat : 0 (ordre annulé avant exécution", journal.story(old)["result"][0])

    def test_after_target_one_only_the_rest_is_closed(self):
        old = self.long_filled()
        self.desk.track("BTCUSDT", [(MON + 2 * M5, 104.5, 101.0, 104.0)], MON + 3 * M5)                  # objectif 1 (104)
        self.assertEqual(old["status"], "tp1")
        self.desk.consider(market({"BTCUSDT": 103.0}, short(score=90.0, entry=103.0)), MON + 13 * H)
        self.assertIn("objectif 1 déjà atteint (la moitié encaissée) : ferme le reste", self.n.sent[-1])
        self.assertAlmostEqual(r_of(old), 0.5 * 2.0 + 0.5 * 1.5)                                          # moitie a l'objectif 1 + moitie fermee a 103
        self.assertIn("moitié à l'objectif 1", journal.story(old)["result"][0])

    def test_not_exceptional_enough_waits(self):
        self.long_filled()
        self.assertEqual(self.desk.consider(market({"BTCUSDT": 101.0}, short(score=84.0)), MON + 13 * H), [])
        self.assertIn("sauf une idée exceptionnelle (au moins 85/100 ; celle-ci a 84/100)", self.desk.waiting["why"])
        self.assertEqual(self.desk.trades[0]["status"], "active")

    def test_setting_never_blocks_even_an_exceptional_idea(self):
        self.cfg.signal_switch = "never"
        self.long_filled()
        self.assertEqual(self.desk.consider(market({"BTCUSDT": 101.0}, short(score=99.0)), MON + 13 * H), [])
        self.assertIn("réglage : jamais de changement de sens", self.desk.waiting["why"])
        self.assertIsNone(self.desk.bias(MON + 13 * H)["switchNeed"])

    def test_two_open_longs_on_two_pairs_are_both_closed(self):
        btc = self.long_filled()
        self.desk.consider(market({"SOLUSDT": 51.0}, idea(sym="SOLUSDT", side="long", score=72.0, entry=50.0, stop=49.0, tp1=52.0, tp2=54.0, key="sl")), MON + H)
        sol = self.desk.trades[-1]
        self.desk.track("SOLUSDT", [(MON + H + M5, 50.3, 49.95, 50.1)], MON + H + 2 * M5)
        out = self.desk.consider(market({"SOLUSDT": 50.5}, short(sym="SOLUSDT", score=95.0, entry=50.5), BTCUSDT=99.0), MON + 14 * H)
        self.assertEqual(len(out), 1)
        msg = self.n.sent[-1]
        self.assertIn("FERME TON ACHAT BTC ET TON ACHAT SOL :", msg)
        self.assertIn("qualité de 95/100, contre 72/100", msg)
        self.assertEqual({x["id"] for x in out[0]["switchFrom"]}, {btc["id"], sol["id"]})
        self.assertAlmostEqual(r_of(btc), -0.5)
        self.assertAlmostEqual(r_of(sol), 0.5)
        self.assertEqual(self.desk._opposite_open(short()), [])
        self.assertEqual(self.desk.bias(MON + 15 * H)["open"][0]["symbol"], "SOLUSDT")

    def test_last_known_price_is_used_and_no_switch_without_a_price(self):
        self.long_filled()                                                                                 # derniere cloture 5 min vue : 100,2
        out = self.desk.consider(market({"SOLUSDT": 50.0}, short(sym="SOLUSDT", score=90.0, entry=50.0)), MON + 13 * H)
        self.assertEqual(len(out), 1)                                                                      # pas de prix BTC dans les signaux
        self.assertIn("vers 100,20 : +0,20 % sur le prix", self.n.sent[-1])
        self.assertAlmostEqual(r_of(self.desk.trades[0]), 0.1)

    def test_no_switch_when_the_price_of_the_open_idea_is_unknown(self):
        self.desk.consider(market({"BTCUSDT": 101.0}, idea(side="long", score=70.0, key="l")), MON)
        self.desk.trades[-1].update(status="active", filledAt=MON + H)                                     # aucun prix BTC connu du bureau
        out = self.desk.consider(market({"SOLUSDT": 50.0}, short(sym="SOLUSDT", score=95.0, entry=50.0)), MON + 13 * H)
        self.assertEqual(out, [])
        self.assertIn("prix de BTCUSDT inconnu en ce moment", self.desk.waiting["why"])
        self.assertEqual(self.desk.trades[0]["status"], "active")

    def test_switch_need_is_the_score_of_the_best_open_idea_plus_fifteen(self):
        self.long_filled(score=88.0)
        self.assertEqual(self.desk.bias(MON + H)["switchNeed"], 103.0)                                   # 88 + 15 : impossible en pratique
        self.assertEqual(self.desk.consider(market({"BTCUSDT": 101.0}, short(score=99.0)), MON + 13 * H), [])
        self.assertIn("l'idée en cours (88/100) est trop forte pour être remplacée (celle-ci a 99/100)", self.desk.waiting["why"])


class ExpiredOrderTests(unittest.TestCase):
    """Un ordre expire sans execution (d'apres les donnees du terminal) ne bloque rien, mais la prochaine idee dans l'autre sens rappelle
    de le fermer s'il avait ete pris quand meme et que le prix est encore entre son stop et son objectif 1."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=5, signal_direction="both")
        self.n = FakeNotifier()
        self.desk = TradeDesk(self.cfg, self.n, log=lambda x: None)
        self.desk.consider(market({"BTCUSDT": 101.5}, idea(side="long", score=80.0, key="l")), MON)
        self.old = self.desk.trades[-1]
        self.desk.track("BTCUSDT", [(MON + k * M5, 101.8, 100.4, 101.5) for k in range(1, 4)], MON + 49 * H)   # jamais descendu a 100
        self.assertEqual(self.old["result"], "expired")

    def tearDown(self):
        self.tmp.cleanup()

    def test_expired_message_says_what_to_do_if_entered_anyway(self):
        msg = self.n.sent[-1]
        self.assertTrue(msg.startswith("⌛ Idée expirée · BTCUSDT achat"))
        self.assertIn("Si tu es quand même entré (au marché ou ailleurs), je ne suis plus cette position : garde ton stop à 98,00 et ton objectif 1 à 104,00", msg)

    def test_next_opposite_idea_reminds_to_close_it(self):
        out = self.desk.consider(market({"BTCUSDT": 101.0}, short(score=80.0)), MON + 50 * H)            # qualite normale : pas besoin d'etre exceptionnelle
        self.assertEqual(len(out), 1)
        msg = self.n.sent[-1]
        self.assertTrue(msg.startswith("ℹ️ Rappel : l'ordre d'achat BTC à 100,00"), msg[:80])
        self.assertIn("Si tu étais quand même entré, ferme-le avant de prendre cette idée (en ce moment : +1,00 % sur le prix depuis 100,00)", msg)
        self.assertEqual(out[0]["expiredNote"], [self.old["id"]])
        self.assertEqual(self.old["result"], "expired")                                                  # resultat inchange : 0, aucune position

    def test_no_reminder_once_price_left_the_range_or_after_three_days(self):
        out = self.desk.consider(market({"BTCUSDT": 97.0}, short(score=80.0, entry=97.0)), MON + 50 * H)  # sous le stop : position deja coupee
        self.assertNotIn("Rappel", self.n.sent[-1])
        self.assertNotIn("expiredNote", out[0])
        self.assertEqual(self.desk._expired_opposite(short(), MON + 48 * H + 73 * H, {"BTCUSDT": 101.0}), [])


class JournalSwitchTests(unittest.TestCase):
    T = MON + 20 * H

    def trade(self, **kw):
        t = {"id": "BTCUSDT-1", "symbol": "BTCUSDT", "side": "long", "entry": 100.0, "stop": 98.0, "tp1": 104.0, "tp2": 108.0, "rr1": 2.0, "rr2": 4.0,
             "entryType": "limite", "created": MON, "filledAt": MON + H, "status": "closed", "result": "switch", "rSwitch": 0.5, "exitPx": 101.0,
             "switchState": "active", "endAt": self.T, "closedAt": self.T, "score": 70.0, "validUntil": MON + 48 * H}
        t.update(kw)
        return t

    @staticmethod
    def rows(start, spec):
        return [(start + k * M5, c, h, l, c) for k, (h, l, c) in enumerate(spec, 1)]

    def test_what_happened_after_the_switch(self):
        t = self.trade()
        self.assertIn("fermer a évité la perte complète", journal.after(t, self.rows(self.T, [(101.0, 97.5, 98.0)]), self.T + 2 * H)[0])
        self.assertIn("garder l'idée aurait mieux payé", journal.after(t, self.rows(self.T, [(104.5, 100.5, 104.0)]), self.T + 2 * H)[0])
        self.assertIn("ni le stop ni l'objectif 1", journal.after(t, self.rows(self.T, [(101.5, 100.5, 101.0)]), self.T + 2 * H)[0])
        t1 = self.trade(switchState="tp1", tp1At=MON + 2 * H, rSwitch=1.5)
        self.assertIn("le reste serait sorti à l'équilibre", journal.after(t1, self.rows(self.T, [(101.0, 99.9, 100.0)]), self.T + 2 * H)[0])
        self.assertIn("objectif 2", journal.after(t1, self.rows(self.T, [(108.5, 101.0, 108.0)]), self.T + 2 * H)[0])

    def test_cancelled_order_reads_like_an_unfilled_one(self):
        t = self.trade(result="switch_cancel", filledAt=None, rSwitch=None, exitPx=None, switchState="pending")
        self.assertEqual((journal.outcome(t), r_of(t)), ("unfilled", 0.0))
        self.assertIn("Le prix est revenu à l'entrée", journal.after(t, self.rows(self.T, [(101.0, 99.8, 100.2)]), self.T + 2 * H)[0])
        ev = journal.story(t)["events"][-1]["text"]
        self.assertIn("annulé avant exécution, sur mon conseil", ev)

    def test_price_path_marks_the_closing_price(self):
        t = self.trade()
        rows = [(MON + k * M5, 100.5, 100.8, 99.9, 100.5) for k in range(0, 300)]
        end = [e for e in journal.path(t, rows, M5, self.T + 4 * H)["events"] if e["kind"] == "end"][0]
        self.assertEqual((end["label"], end["p"]), ("fermée (changement de sens)", 101.0))

    def test_calibration_ignores_a_switch_before_target_one(self):
        base = dict(pTp=0.6, pFill=None)
        cut = self.trade(**base)
        self.assertEqual(journal.calibration([cut]), {})                                                  # fermee avant de trancher : laissee de cote
        reached = self.trade(**base, tp1At=MON + 2 * H, switchState="tp1")
        cal = journal.calibration([cut, reached])
        self.assertEqual((cal["tp1"]["n"], cal["tp1"]["real"]), (1, 1.0))

    def test_summary_counts_switches_as_decided(self):
        s = journal.summary([self.trade(), self.trade(id="b", rSwitch=-0.3), self.trade(id="c", result="switch_cancel", filledAt=None, rSwitch=None)])
        self.assertEqual((s["decided"], s["wins"], s["losses"], s["switched"], s["cancelled"]), (2, 1, 1, 2, 1))
        self.assertAlmostEqual(s["r"], 0.2)


class SettingTests(unittest.TestCase):
    def test_env_and_settings(self):
        from config import load_config, write_env
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("TERMINAL_SIGNAL_SWITCH=never\n", encoding="utf-8")
            self.assertEqual(load_config(env).signal_switch, "never")
            write_env(env, {"TERMINAL_SIGNAL_SWITCH": "n'importe quoi"})
            self.assertEqual(load_config(env).signal_switch, "strong")

    def test_save_settings_updates_the_desk(self):
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
            self.assertEqual(app.settings()["signalSwitch"], "strong")
            s = app.save_settings({"signalSwitch": "never"})
            self.assertEqual(s["signalSwitch"], "never")
            self.assertEqual(app.desk.cfg.signal_switch, "never")
            self.assertIn("TERMINAL_SIGNAL_SWITCH=never", (Path(tmp) / ".env").read_text(encoding="utf-8"))


class StudyTests(unittest.TestCase):
    """Mesure V25.1 (engine/sigtest.switch_study) sur des bougies fabriquees : chaque politique fait ce qu'elle dit."""
    T0 = 1_759_104_000_000                                    # lundi 00:00 UTC

    def bars(self, n=260, px=100.0):
        return [Candle(self.T0 + i * H, px, px + 0.1, px - 0.1, px) for i in range(n)]

    def test_timeline(self):
        cs = self.bars()
        cs[5] = Candle(cs[5].t, 100.0, 100.1, 98.9, 99.5)       # execution a 99
        cs[8] = Candle(cs[8].t, 100.0, 103.2, 99.9, 103.0)      # objectif 103
        tl = sigtest.timeline(cs, 2, "long", 99.0, 97.0, 103.0, False)
        self.assertEqual((tl["status"], tl["fill"], tl["end"]), ("tp", 5, 8))
        self.assertAlmostEqual(tl["R"], 2.0)
        self.assertEqual(sigtest.timeline(cs, 2, "long", 90.0, 88.0, 110.0, False)["status"], "nofill")

    def test_policies(self):
        cs = self.bars()
        ideas = [(10, "long", 8.0, 100.0, 98.0, 104.0, True), (30, "short", 10.0, 100.0, 102.0, 96.0, True)]
        st = sigtest.switch_study(cs, ideas, deltas=(0.0, 3.0))
        p = st["policies"]
        self.assertEqual((p["never"]["sent"], p["never"]["switches"]), (1, 0))                            # l'achat est en cours : la vente attend
        self.assertEqual((p["both"]["sent"], p["both"]["switches"]), (2, 0))
        self.assertEqual((p["delta0"]["sent"], p["delta0"]["switches"]), (2, 1))                          # 10 >= 8 : on ferme l'achat
        self.assertEqual((p["delta3"]["sent"], p["delta3"]["switches"]), (1, 0))                          # 10 < 8 + 3

    def test_expired_order_variant(self):
        cs = self.bars()
        ideas = [(10, "long", 8.0, 90.0, 88.0, 110.0, False), (70, "short", 8.0, 100.0, 102.0, 96.0, True)]
        p = sigtest.switch_study(cs, ideas, deltas=(0.0, 3.0))["policies"]
        self.assertEqual((p["never"]["sent"], p["never"]["ghostBlocked"]), (2, 0))                        # l'ordre a expire : rien ne bloque
        self.assertEqual((p["never_exp72"]["sent"], p["never_exp72"]["ghostBlocked"]), (1, 1))            # variante mesuree (non retenue)
        self.assertEqual(p["delta3_exp72"]["sent"], 1)


if __name__ == "__main__":
    unittest.main()
