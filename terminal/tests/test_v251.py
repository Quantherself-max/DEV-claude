"""V25.1 (remplacee par la V25.2 pour l'envoi des idees) : ce qui en reste. Le journal lit encore les idees fermees ou annulees pour
« changer de sens » (resultats enregistres pendant les quelques heures de la V25.1), et la mesure sur l'historique (engine/sigtest.py :
timeline, switch_study) sert toujours a comparer les facons de gerer une idee dans l'autre sens."""
import unittest

from alerts import journal
from alerts.trades import r_of
from engine import sigtest
from engine.atr import Candle
from tests.test_trades import H, M5, MON


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
