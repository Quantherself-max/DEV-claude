"""V45 : backtest. Aucun regard vers l'avenir (décisions identiques quand on coupe les données futures), coûts réalistes, mesures complètes."""
from __future__ import annotations
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import backtest as bt
from engine import fine
from quant import execution

MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
T0 = 1_700_000_000_000 - 1_700_000_000_000 % DAY


def walk(n_min: int, seed: int = 4) -> fine.Bars:
    """Marche au hasard d'une minute (outil de TEST : sert seulement à vérifier la mécanique du moteur, jamais à afficher un prix)."""
    r = random.Random(seed)
    b = fine.Bars(MIN)
    p = 60000.0
    for i in range(n_min):
        o = p
        p = max(1000.0, p * (1 + r.gauss(0, 0.0007) + 0.00002 * math.sin(i / 700)))
        h, l = max(o, p) * (1 + abs(r.gauss(0, 0.0003))), min(o, p) * (1 - abs(r.gauss(0, 0.0003)))
        v = 5 + 20 * r.random()
        b.append(T0 + i * MIN, o, h, l, p, v, v * (2 * r.random() - 1))
    return b.build_cum()


def cut(b: fine.Bars, t_end: int) -> fine.Bars:
    out = fine.Bars(b.step)
    for i in range(len(b.t)):
        if b.t[i] + b.step > t_end:
            break
        out.append(b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i], b.d[i])
    return out.build_cum()


class LookAheadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b1 = walk(26 * 24 * 60)
        cls.ds = bt.Dataset.from_1m(cls.b1)

    def test_decisions_do_not_change_when_the_future_is_removed(self):
        """Le test décisif : on génère les décisions sur 26 jours, puis sur les mêmes données coupées au 22e jour. Toute décision prise
        avant la coupure doit être IDENTIQUE (mêmes prix d'entrée, de stop, d'objectif, même score) : sinon elle dépendait de l'avenir."""
        start, split, end = T0 + 16 * DAY, T0 + 22 * DAY, T0 + 26 * DAY
        full = bt.generate(self.ds, start, end)
        part = bt.generate(bt.Dataset.from_1m(cut(self.b1, split)), start, split)
        key = lambda c: (c["t"], c["side"], c["kind"], c["etype"], round(c["entry"], 6), round(c["stop"], 6), round(c["tp1"], 6), round(c["score"], 6))
        before = [key(c) for c in full if c["t"] < split]
        self.assertGreater(len(before), 5, "trop peu de décisions pour que le test ait un sens")
        self.assertEqual(before, [key(c) for c in part])

    def test_a_trade_is_played_only_on_later_bars(self):
        b = self.b1
        i = 5000
        t0 = b.t[i]
        entry = b.c[i - 1]
        sim = bt.simulate(b, t0, "long", "marché", entry, entry * 0.99, entry * 1.01, entry * 1.02)
        self.assertTrue(sim["filled"])
        self.assertEqual(sim["fill_px"], b.o[i])                              # exécuté à l'ouverture de la bougie SUIVANT la décision
        self.assertGreaterEqual(sim["fill_t"], t0)
        # couper l'avenir après la sortie ne change rien ; le changer AVANT la décision non plus pour l'exécution
        again = bt.simulate(cut(b, sim["exit_t"]), t0, "long", "marché", entry, entry * 0.99, entry * 1.01, entry * 1.02)
        self.assertEqual((again["result"], again["r_gross"], again["exit_t"]), (sim["result"], sim["r_gross"], sim["exit_t"]))
        # l'agitation utilisée pour le glissement ne lit que des bougies fermées avant l'ordre
        want = sum(b.h[k] - b.l[k] for k in range(i - 14, i)) / 14 / b.c[i - 1]
        self.assertAlmostEqual(sim["atr_in"], want)

    def test_stop_first_when_stop_and_target_share_a_bar(self):
        b = fine.Bars(MIN)
        b.append(0, 100, 100, 100, 100, 1, 0)
        b.append(MIN, 100, 100.2, 99.9, 100, 1, 0)
        b.append(2 * MIN, 100, 103, 98, 100, 1, 0)                            # touche le stop (99) ET l'objectif (102) dans la même minute
        b.build_cum()
        sim = bt.simulate(b, MIN, "long", "marché", 100, 99, 102, None)
        self.assertEqual((sim["result"], sim["r_gross"]), ("stop", -1.0))     # hypothèse prudente : le stop d'abord


class CostsTest(unittest.TestCase):
    def sim(self, side="long"):
        b = fine.Bars(MIN)
        px = [100, 100, 100.5, 101, 101.5, 102.2, 102.2]
        for i, p in enumerate(px):
            lo, hi = (p - 0.3, p + 0.3)
            b.append(i * 8 * HOUR // 3, p, hi, lo, p, 1, 0)
        b.step = 8 * HOUR // 3
        b.build_cum()
        return b

    def test_new_model_charges_funding_with_its_sign(self):
        base = {"fill_px": 100.0, "risk": 1.0, "r_gross": 1.0, "entry_kind": "maker", "legs": [("maker", 1.0)], "hours": 24.0, "tp1": False,
                "partial": 0.5, "tp1_t": None, "fill_t": 0, "exit_t": 24 * HOUR, "atr_in": 0.001, "atr_out": 0.001}
        fs = execution.FundingSeries([(k * 8 * HOUR, 0.0003) for k in range(0, 5)])
        new = {**bt.REALISTIC_COSTS, "funding": fs}
        long_, short = bt.net_r({**base, "side": "long"}, new), bt.net_r({**base, "side": "short"}, new)
        # 3 échéances traversées (8 h, 16 h, 24 h) à 0,03 % sur un notionnel de 100 R : 0,09 R payé par le long, reçu par le short
        self.assertAlmostEqual(long_, 1.0 - 0.04 - 0.09)
        self.assertAlmostEqual(short, 1.0 - 0.04 + 0.09)
        # l'ancien modèle comptait le financement comme un coût dans les deux sens : c'était un biais contre les shorts
        old = bt.net_r({**base, "side": "short"}, bt.DEFAULT_COSTS)
        self.assertAlmostEqual(old, 1.0 - 0.04 - 100 * 0.0001 / 8 * 24)
        self.assertLess(old, short)

    def test_slippage_grows_with_volatility(self):
        base = {"fill_px": 100.0, "risk": 1.0, "r_gross": -1.0, "entry_kind": "taker", "legs": [("taker", 1.0)], "hours": 1.0, "tp1": False,
                "partial": 0.5, "tp1_t": None, "fill_t": 0, "exit_t": HOUR, "side": "long"}
        c = {**bt.REALISTIC_COSTS, "funding8h": 0.0}
        calm = bt.net_r({**base, "atr_in": 0.0002, "atr_out": 0.0002}, c)
        wild = bt.net_r({**base, "atr_in": 0.0002, "atr_out": 0.004}, c)       # stop touché dans une cascade
        self.assertAlmostEqual(calm - wild, 100 * 0.10 * (0.004 - 0.0002))
        self.assertLess(wild, calm)


class MetricsTest(unittest.TestCase):
    def test_backtest_metrics_carry_the_new_measures(self):
        r = random.Random(3)
        trades = []
        for i in range(60):
            x = 1.8 if r.random() < 0.45 else -1.0
            trades.append({"exit_t": T0 + (i + 1) * DAY, "r": x, "stop_pct": 0.01, "mae": 0.4 if x > 0 else 1.0, "mfe": 2.0 if x > 0 else 0.5, "hours": 6.0})
        m = bt.metrics(trades, T0, T0 + 70 * DAY, mc=300)
        for k in ("sharpe", "sortino", "calmar", "ddDays", "pf", "expR", "maxDD", "payoff", "maxLossStreak", "excursions", "mc"):
            self.assertIn(k, m)
        self.assertGreater(m["ddDays"], 0)
        self.assertAlmostEqual(m["calmar"], m["cagr"] / m["maxDD"])
        self.assertEqual((m["mc"]["shuffle"]["runs"], m["mc"]["bootstrap"]["runs"]), (300, 300))
        self.assertGreaterEqual(m["mc"]["shuffle"]["dd"]["95"], m["mc"]["shuffle"]["dd"]["50"])
        self.assertAlmostEqual(m["excursions"]["winners"]["maeMean"], 0.4)
        self.assertNotIn("mc", bt.metrics(trades, T0, T0 + 70 * DAY))          # sans demande : pas de Monte Carlo (rapide)


if __name__ == "__main__":
    unittest.main()
