"""V25.2 : une idee dans l'autre sens peut arriver pendant une idee en cours ; elle la couvre sans l'annuler (message « COUVERTURE »,
gain ou perte du moment, niveaux qui se genent sur la meme paire, mode couverture de la plateforme). Reglage hedge / never, journal,
et mesure sur l'historique avec BTC et SOL rejoues ensemble."""
import tempfile
import unittest
from pathlib import Path

from alerts.trades import TradeDesk, r_of
from config import Config
from engine import sigtest
from engine.atr import Candle
from tests.test_trades import FakeNotifier, idea, H, M5, MON


def market(px, *ideas):
    """Signaux par paire avec le prix du moment (px : {symbole: prix}, une paire peut n'avoir aucune idee)."""
    out = {s: {"ready": True, "warm": True, "ideas": [], "price": p} for s, p in px.items()}
    for i in ideas:
        out.setdefault(i["symbol"], {"ready": True, "warm": True, "ideas": [], "price": None})["ideas"].append(i)
    return out


def sol(side, entry, stop, tp1, score=75.0, key=None, etype="limite"):
    return idea(sym="SOLUSDT", side=side, score=score, entry=entry, stop=stop, tp1=tp1, tp2=None, key=key or f"{side}{entry}", etype=etype)


class HedgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(source="binance", data_dir=self.tmp.name, signal_min_score=65.0, signal_max_week=5, signal_direction="both")
        self.n = FakeNotifier()
        self.desk = TradeDesk(self.cfg, self.n, log=lambda x: None)

    def tearDown(self):
        self.tmp.cleanup()

    def sol_long_filled(self):
        self.desk.consider(market({"SOLUSDT": 151.0}, sol("long", 150.0, 146.0, 158.0, score=70.0)), MON)
        self.desk.track("SOLUSDT", [(MON + M5, 150.5, 149.9, 150.2)], MON + 2 * M5)
        tr = self.desk.trades[-1]
        self.assertEqual(tr["status"], "active")
        return tr

    def test_same_pair_hedge_header(self):
        long_ = self.sol_long_filled()
        out = self.desk.consider(market({"SOLUSDT": 152.5}, sol("short", 152.5, 155.0, 145.0, etype="marché")), MON + 13 * H)
        self.assertEqual(len(out), 1)
        msg = self.n.sent[-1]
        lines = msg.split("\n")
        self.assertEqual(lines[0], "🛡 COUVERTURE · SOLUSDT VENTE")
        self.assertTrue(lines[1].startswith("Ton achat SOL du "))
        self.assertIn("est toujours en cours : entrée 150,00, stop 146,00 ; en ce moment +1,67 % sur le prix, +16,7 % avec ton levier ×10, +0,62 fois le risque.", lines[1])
        self.assertIn("Cette vente ne l'annule pas : garde-le avec son stop et ses objectifs ; cette idée a les siens. "
                      "Au pire, si tous les stops étaient touchés, la perte totale serait de 2 fois le risque.", msg)
        self.assertIn("Sur SOL, les deux ne peuvent pas gagner ensemble : si le prix va jusqu'à l'objectif 1 de cette vente (145,00), ton achat touche son stop "
                      "(146,00) en route ; s'il va jusqu'à l'objectif 1 de ton achat (158,00), cette vente touche son stop (155,00) en route.", msg)
        self.assertIn("Même paire : pour tenir un achat et une vente en même temps sur SOL, ta plateforme doit être en mode couverture", msg)
        self.assertNotIn("bougent souvent ensemble", msg)
        # rien n'est ferme : l'achat continue sa vie, le journal ne compte rien pour lui
        self.assertEqual((long_["status"], long_["result"], r_of(long_)), ("active", None, None))
        self.assertEqual(self.desk.stats()["switch"], 0)
        self.desk.track("SOLUSDT", [(MON + 13 * H + M5, 158.5, 152.0, 158.0)], MON + 13 * H + 2 * M5)
        self.assertEqual(long_["status"], "tp1")                                                           # l'achat atteint son objectif 1...
        self.assertEqual(out[0]["result"], "stop")                                                          # ... et la vente touche son stop

    def test_levels_that_do_not_conflict_are_not_described(self):
        self.sol_long_filled()
        self.desk.consider(market({"SOLUSDT": 157.0}, sol("short", 157.0, 159.0, 152.0, etype="marché")), MON + 13 * H)
        msg = self.n.sent[-1]
        self.assertNotIn("ne peuvent pas gagner ensemble", msg)                                             # 152 au-dessus du stop 146, 158 sous le stop 159
        self.assertIn("Même paire", msg)

    def test_pending_orders_and_target_one_reached(self):
        self.desk.consider(market({"SOLUSDT": 151.0}, sol("long", 150.0, 146.0, 158.0)), MON)
        self.desk.consider(market({"BTCUSDT": 100.0}, idea(side="short", entry=101.0, stop=103.0, tp1=97.0, tp2=None, key="bs")), MON + H)
        msg = self.n.sent[-1]
        self.assertIn("Ton achat SOL du ", msg)
        self.assertIn("attend toujours son exécution (ordre à 150,00, stop 146,00) : il reste valable.", msg)
        self.assertIn("SOL et BTC bougent souvent ensemble : cette vente BTC compense en partie ton achat SOL.", msg)
        self.desk.trades[1].update(status="tp1", filledAt=MON + 2 * H, tp1At=MON + 3 * H)
        self.desk.consider(market({"SOLUSDT": 154.0, "BTCUSDT": 99.0}, sol("long", 154.0, 152.0, 160.0, key="l2", score=80.0, etype="marché")),
                           MON + 26 * H)
        msg = self.n.sent[-1]
        self.assertIn("Ta vente BTC du ", msg)
        self.assertIn("est toujours en cours (objectif 1 atteint, le reste court) : entrée 101,00, stop 103,00 ; en ce moment +1,98 % sur le prix", msg)
        self.assertIn("+1,50 fois le risque", msg)                                                         # moitie a l'objectif 1 (2) + moitie a 99 (+1)
        self.assertIn("ne l'annule pas : garde-la avec son stop et ses objectifs", msg)

    def test_two_open_ideas_and_unknown_price(self):
        self.desk.consider(market({"SOLUSDT": 151.0}, sol("long", 150.0, 146.0, 158.0)), MON)
        self.desk.trades[-1].update(status="active", filledAt=MON + H)                                     # prix SOL inconnu du bureau
        self.desk.consider(market({"BTCUSDT": 100.0}, idea(side="long", entry=99.0, stop=97.0, tp1=103.0, tp2=None, key="bl")), MON + H)
        out = self.desk.consider(market({"ETHUSDT": 3000.0}, idea(sym="ETHUSDT", side="short", entry=3000.0, stop=3040.0, tp1=2920.0, tp2=None, key="es",
                                                                 etype="marché")), MON + 2 * H)
        self.assertEqual(len(out), 1)
        msg = self.n.sent[-1]
        self.assertIn("Ton achat SOL du ", msg)
        self.assertIn("est toujours en cours : entrée 150,00, stop 146,00.", msg)                          # pas de prix : pas de chiffres inventes
        self.assertIn("Cette vente ne les annule pas : garde-les avec leurs stops et leurs objectifs", msg)
        self.assertIn("la perte totale serait de 3 fois le risque", msg)
        self.assertIn("BTC et SOL et ETH bougent souvent ensemble : cette vente ETH compense en partie tes idées sur BTC et SOL.", msg)
        self.assertEqual(self.desk.week(MON + 3 * H)["sent"], 3)                                           # une couverture compte dans le quota
        self.assertEqual(len(out[0]["hedgeOf"]), 2)

    def test_journal_story_and_category(self):
        self.sol_long_filled()
        self.desk.consider(market({"SOLUSDT": 152.5}, sol("short", 152.5, 155.0, 145.0, etype="marché")), MON + 13 * H)
        h = self.desk.history(MON + 14 * H)
        rows = {r["side"]: r for r in h["trades"]}
        self.assertTrue(any(w.startswith("Couverture : envoyée pendant l’achat SOL le ") for w in rows["short"]["story"]["why"]))
        self.assertIsNotNone(rows["short"]["hedgeOf"])
        g = {x["key"]: x for x in h["summary"]["groups"]}["hedge"]
        self.assertEqual([(r["label"], r["n"]) for r in g["rows"]], [("envoyée seule", 1), ("envoyée en couverture d'une idée en cours", 1)])
        self.assertEqual(self.desk.public(MON + 14 * H)["trades"][0]["hedgeOf"][0]["side"], "long")

    def test_no_hedge_category_without_hedges(self):
        self.sol_long_filled()
        self.assertNotIn("hedge", {x["key"] for x in self.desk.history(MON + H)["summary"]["groups"]})

    def test_expired_message_without_reminder(self):
        self.desk.consider(market({"BTCUSDT": 101.5}, idea(side="long", key="l")), MON)
        self.desk.track("BTCUSDT", [(MON + M5, 101.8, 100.4, 101.5)], MON + 49 * H)
        msg = self.n.sent[-1]
        self.assertTrue(msg.startswith("⌛ Idée expirée · BTCUSDT achat"))
        self.assertTrue(msg.endswith("garde ton stop à 98,00 et ton objectif 1 à 104,00."))


class SettingTests(unittest.TestCase):
    def test_env(self):
        from config import load_config, write_env
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("TERMINAL_SIGNAL_OPPOSITE=never\n", encoding="utf-8")
            self.assertEqual(load_config(env).signal_opposite, "never")
            write_env(env, {"TERMINAL_SIGNAL_OPPOSITE": "hedge"})
            self.assertEqual(load_config(env).signal_opposite, "hedge")
            env.write_text("TERMINAL_SIGNAL_SWITCH=never\n", encoding="utf-8")                           # reglage de la V25.1 : ignore
            self.assertEqual(load_config(env).signal_opposite, "hedge")

    def test_save_settings_and_bot_status(self):
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tmp, port=0)
            app = App(cfg, env_path=Path(tmp) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
            self.assertEqual(app.settings()["signalOpposite"], "hedge")
            self.assertIn("Idées en cours : aucune", app.bot_status())
            s = app.save_settings({"signalOpposite": "never"})
            self.assertEqual((s["signalOpposite"], app.desk.cfg.signal_opposite), ("never", "never"))
            self.assertIn("TERMINAL_SIGNAL_OPPOSITE=never", (Path(tmp) / ".env").read_text(encoding="utf-8"))


class HedgeStudyTests(unittest.TestCase):
    T0 = 1_759_104_000_000                                     # lundi 00:00 UTC

    def bars(self, n=260, px=100.0):
        return [Candle(self.T0 + i * H, px, px + 0.1, px - 0.1, px) for i in range(n)]

    def test_policies_on_two_pairs(self):
        a, b = self.bars(), self.bars(px=50.0)
        series = {"AAA": (a, [(10, "long", 8.0, 100.0, 98.0, 104.0, True, 1)]),
                  "BBB": (b, [(30, "short", 8.0, 50.0, 51.0, 48.0, True, -1)])}
        st = sigtest.hedge_study(series)
        self.assertEqual((st["never"]["n"], st["hedge"]["n"]), (1, 2))                                      # la vente BBB arrive pendant l'achat AAA
        self.assertEqual((st["hedge"]["hedge"]["n"], st["hedge"]["otherPair"]["n"], st["hedge"]["samePair"]["n"]), (1, 1, 0))
        gated = sigtest.hedge_study(series, gate=True)                                                      # BBB va contre sa tendance : filtree
        self.assertEqual((gated["ideas"], gated["hedge"]["n"]), (1, 1))

    def test_same_pair_and_two_open_ideas_per_pair(self):
        a = self.bars()
        series = {"AAA": (a, [(10, "long", 8.0, 100.0, 98.0, 104.0, True, 1), (30, "short", 8.0, 100.0, 102.0, 96.0, True, 1),
                              (50, "long", 8.0, 100.0, 99.0, 102.0, True, 1)])}
        h = sigtest.hedge_study(series)["hedge"]
        self.assertEqual((h["n"], h["samePair"]["n"]), (2, 1))                                             # la 3e : deja 2 idees ouvertes sur la paire


if __name__ == "__main__":
    unittest.main()
