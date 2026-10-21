"""V25.3 : chaque configuration du moment dit si elle est partie sur Telegram (et quand, niveaux figes) ou la regle exacte qui la
retient (meme logique que l'envoi) ; le message Telegram porte l'heure d'envoi ; le serveur ajoute cet etat sans toucher au cache."""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

from alerts.trades import TradeDesk
from config import Config
from tests.test_trades import FakeNotifier, idea, sigs, H, MON

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}   # Python 3.9 (Mac) : option absente


class SendStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=5, signal_direction="both")
        self.n = FakeNotifier()
        self.desk = TradeDesk(self.cfg, self.n, log=lambda x: None)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, i, now, **kw):
        return self.desk.send_state(i["symbol"], i, now, **kw)

    def test_sent_idea_is_found_with_its_time_and_frozen_levels(self):
        i = idea(key="k1")
        self.assertEqual(self.state(i, MON)["state"], "next")                                            # passe toutes les regles
        self.desk.consider(sigs(i), MON)
        st = self.state(i, MON + H)
        self.assertEqual((st["state"], st["created"], st["n"], st["status"], st["moved"]), ("sent", MON, 1, "pending", False))
        moved = idea(key="k1", entry=100.6, stop=98.6, tp1=104.6, tp2=108.6)                            # meme configuration, niveaux du moment differents
        st = self.state(moved, MON + 2 * H)
        self.assertEqual((st["state"], st["entry"], st["moved"]), ("sent", 100.0, True))                # les niveaux envoyes ne bougent pas
        self.desk.trades[0].update(status="closed", result="stop", closedAt=MON + 5 * H)
        self.assertEqual((self.state(i, MON + 6 * H)["state"], self.state(i, MON + 6 * H)["result"]), ("sent", "stop"))   # terminee : pas renvoyee avant 48 h
        self.assertEqual(self.state(i, MON + 49 * H)["state"], "next")

    def test_telegram_message_carries_the_sending_time(self):
        self.desk.consider(sigs(idea()), MON)
        lines = self.n.sent[0].split("\n")
        self.assertTrue(lines[0].startswith("🎯 Idée de trade 1/5 de la semaine"))
        self.assertTrue(lines[1].startswith("🕒 Envoyée le 29/09 14h00 (heure de Paris) : ces niveaux ne bougeront plus"))

    def test_cooldown_reason_is_the_same_on_screen_and_in_the_desk(self):
        self.desk.consider(sigs(idea(key="a")), MON)
        other = idea(key="b", entry=90.0, stop=88.0, tp1=94.0, tp2=98.0)
        st = self.state(other, MON + 2 * H)
        self.assertEqual((st["state"], st["code"]), ("blocked", "cooldown"))
        self.assertIn("une seule par paire toutes les 12 heures (prochaine possible à partir du 30/09 02h00)", st["text"])
        self.assertEqual(self.desk.consider(sigs(other), MON + 2 * H), [])
        self.assertIn(st["text"], self.desk.waiting["why"])                                               # meme texte que la carte

    def test_two_open_ideas_on_a_pair(self):
        self.desk.consider(sigs(idea(key="a")), MON)
        self.desk.consider(sigs(idea(key="b", entry=90.0, stop=88.0, tp1=94.0, tp2=98.0)), MON + 13 * H)
        third = idea(key="c", entry=80.0, stop=78.0, tp1=84.0, tp2=88.0)
        st = self.state(third, MON + 26 * H)
        self.assertEqual((st["state"], st["code"]), ("blocked", "full"))
        self.assertIn("déjà 2 idées en cours sur BTCUSDT", st["text"])

    def test_quota_last_place_and_one_direction_setting(self):
        self.cfg.signal_max_week = 2
        self.desk.consider(sigs(idea(sym="SOLUSDT", key="s", entry=50.0, stop=49.0, tp1=52.0, tp2=54.0)), MON)
        low = idea(key="l", score=70.0)
        st = self.state(low, MON + H)
        self.assertEqual((st["state"], st["code"]), ("blocked", "last"))
        self.assertIn("dernière place de la semaine : il faut 73/100, celle-ci a 70/100", st["text"])
        self.desk.consider(sigs(idea(key="b2", score=90.0)), MON + H)
        st = self.state(idea(sym="ETHUSDT", key="e", entry=3000.0, stop=2960.0, tp1=3080.0, tp2=3160.0), MON + 2 * H)
        self.assertEqual((st["state"], st["code"]), ("blocked", "quota"))
        self.cfg.signal_max_week, self.cfg.signal_opposite = 5, "never"
        st = self.state(idea(sym="ETHUSDT", side="short", key="e2", entry=3000.0, stop=3040.0, tp1=2920.0, tp2=2840.0), MON + 2 * H)
        self.assertEqual((st["state"], st["code"]), ("blocked", "never"))

    def test_filtered_warming_and_direction(self):
        f = idea(key="f")
        f["eligible"], f["gates"] = False, ["l'idée va contre la tendance de fond : le cours est sous les moyennes"]
        self.assertEqual(self.state(f, MON), {"state": "filtered", "text": f["gates"][0]})
        self.assertEqual(self.state(idea(key="w"), MON, warm=False)["state"], "warming")
        self.cfg.signal_direction = "long"
        st = self.state(idea(side="short", key="s", entry=110.0, stop=112.0, tp1=106.0, tp2=102.0), MON)
        self.assertEqual(st["state"], "alertmode")
        self.assertIn("alerte pour tes longs", st["text"])

    def test_public_rows_have_the_times_for_the_chart(self):
        self.desk.consider(sigs(idea()), MON)
        row = self.desk.public(MON + H)["trades"][0]
        for k in ("created", "endAt", "tp1At", "closedAt", "status", "n", "sent"):
            self.assertIn(k, row)


class ServerStateTests(unittest.TestCase):
    def test_states_are_added_without_touching_the_cache(self):
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        with tempfile.TemporaryDirectory(**TMP_KW) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
            cached = {"ready": True, "warm": True, "symbol": "BTCUSDT", "ideas": [idea(key="x")]}       # ce que le service garde en cache
            app.service.signals = lambda sym: cached
            sg = app.signals_with_state("BTCUSDT")
            self.assertEqual(sg["ideas"][0]["send"]["state"], "next")
            self.assertNotIn("send", cached["ideas"][0])                                                  # le cache du service n'est pas modifie
            cached["warm"] = False
            self.assertEqual(app.signals_with_state("BTCUSDT")["ideas"][0]["send"]["state"], "warming")
            st = app.idea_state("BTCUSDT", {"side": "long", "entry": 1.0, "score": 10.0, "eligible": False, "gates": [], "hold": []})
            self.assertEqual(st["state"], "filtered")
            self.assertEqual(app.idea_state("BTCUSDT", {"side": "long"})["state"], "filtered")             # brief incomplet : pas d'erreur


if __name__ == "__main__":
    unittest.main()
