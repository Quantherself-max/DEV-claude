import json, math, random, time, unittest

from engine.atr import Candle
from engine.bias import (FEATS, WARMUP, analyse, auc, build_features, fit_logistic, first_passage, plan, train, predict,
                         walk_forward, _sigmoid)
from engine.stats import atr_series

H = 3_600_000


def synth(n, seed=1, signal=0.0, vol=0.006, start=1_700_000_000_000 - 1_700_000_000_000 % H):
    """Marche aleatoire horaire. signal > 0 : le desequilibre acheteur (tb) PREDIT le rendement de l'heure suivante."""
    r = random.Random(seed)
    px, out, hidden = 100.0, [], 0.0
    for i in range(n):
        hidden = 0.7 * hidden + r.gauss(0, 1)
        ret = signal * hidden * vol + r.gauss(0, vol)       # le signal du moment pousse le rendement suivant
        o = px
        px *= math.exp(ret)
        h, l = max(o, px) * (1 + abs(r.gauss(0, vol / 3))), min(o, px) * (1 - abs(r.gauss(0, vol / 3)))
        v = 1000.0
        tb = v * min(0.9, max(0.1, 0.5 + 0.08 * hidden + r.gauss(0, 0.03)))
        out.append(Candle(start + i * H, o, h, l, px, v, tb))
    return out


class FeatureTests(unittest.TestCase):
    def test_shape_and_no_lookahead(self):
        c = synth(600, 3)
        f1 = build_features(c)
        self.assertEqual(len(f1), 600)
        self.assertTrue(all(x is None for x in f1[:WARMUP]))
        self.assertTrue(all(len(x) == len(FEATS) for x in f1[WARMUP:]))
        c2 = synth(600, 3)
        for k in c2[400:]:                                    # on change le FUTUR : le passe ne doit pas bouger
            k.c *= 1.3; k.h *= 1.3; k.tb = k.v
        f2 = build_features(c2)
        for i in range(WARMUP, 400):
            self.assertEqual(f1[i], f2[i], i)
        self.assertNotEqual(f1[450], f2[450])

    def test_funding_is_the_last_known_at_close(self):
        c = synth(400, 5)
        fund = [(c[200].t, 0.0001), (c[300].t + H, 0.0009)]   # le 2e funding tombe a la cloture de la bougie 300
        f = build_features(c, fund)
        j = [n for n, *_ in FEATS].index("funding")
        self.assertAlmostEqual(f[250][j], 0.01)
        self.assertAlmostEqual(f[299][j], 0.01)
        self.assertAlmostEqual(f[300][j], 0.09)


class LogisticTests(unittest.TestCase):
    def test_recovers_planted_coefficients(self):
        r = random.Random(2)
        X = [[r.gauss(0, 1), r.gauss(0, 1), r.gauss(0, 1)] for _ in range(4000)]
        y = [1 if r.random() < _sigmoid(0.3 + 1.2 * a - 0.8 * b) else 0 for a, b, c in X]
        w = fit_logistic(X, y, lam=1e-3)
        self.assertAlmostEqual(w[0], 0.3, delta=0.12)
        self.assertAlmostEqual(w[1], 1.2, delta=0.15)
        self.assertAlmostEqual(w[2], -0.8, delta=0.15)
        self.assertLess(abs(w[3]), 0.12)

    def test_auc_basics(self):
        self.assertEqual(auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]), 1.0)
        self.assertEqual(auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]), 0.0)
        self.assertEqual(auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]), 0.5)


class ValidationTests(unittest.TestCase):
    def test_random_walk_is_not_validated(self):
        c = synth(24 * 330, 7, signal=0.0)
        t0 = time.time()
        a = analyse(c)
        self.assertTrue(a["ready"])
        print(f"\n   [analyse 330 j : {time.time() - t0:.1f} s]", end="")
        for h in ("4", "24"):
            r = a["horizons"][h]
            self.assertFalse(r["validated"], (h, r["auc"], r["aucCI"], r["skill"]))     # aucun avantage sur un marche sans memoire
            self.assertEqual(r["pUp"], r["base"])                                          # on affiche alors le taux de base
            self.assertLess(abs(r["pCal"] - 0.5), 0.15)
            self.assertLess(r["aucCI"][0], 0.55)

    def test_planted_signal_is_detected_out_of_sample(self):
        c = synth(24 * 330, 9, signal=0.35)
        a = analyse(c)
        r = a["horizons"]["4"]
        self.assertTrue(r["validated"], (r["auc"], r["aucCI"], r["skill"], r["platt"]))
        self.assertGreater(r["aucCI"][0], 0.5)
        self.assertGreater(r["skill"], 0)
        top = r["contrib"][0]["key"]
        self.assertIn(top, ("cvd4", "cvd24", "mom4"))                                     # il s'appuie sur le bon signal
        self.assertGreater(len(r["calibration"]), 3)
        cal = r["calibration"]
        self.assertGreater(cal[-1]["freq"], cal[0]["freq"])                               # plus de confiance = plus de hausses reelles

    def test_short_history_is_refused(self):
        a = analyse(synth(500))
        self.assertFalse(a["ready"])

    def test_walk_forward_never_trains_on_the_future(self):
        c = synth(24 * 250, 4)
        f = build_features(c)
        idx = list(range(WARMUP, len(c) - 4))
        X = [f[i] for i in idx]
        ys = [1 if c[i + 4].c > c[i].c else 0 for i in idx]
        preds, labs, ts, folds = walk_forward(X, ys, idx, 4)
        self.assertGreater(folds, 2)
        self.assertEqual(len(preds), len(ts))
        self.assertGreaterEqual(ts[0], idx[0] + 24 * 100)                                  # pas de test avant 100 jours d'entrainement


class PlanTests(unittest.TestCase):
    def test_first_passage_matches_gambler_ruin_on_random_walk(self):
        c = synth(24 * 700, 12, vol=0.004)
        atrs = atr_series(c)
        u, d, z = first_passage(c, atrs, 2.0, 1.0, 72)
        self.assertGreater(u + d + z, 10000)
        # marche sans derive : P(+2 avant -1) ~ 1/3 (ruine du joueur), un peu moins avec les meches et le depassement
        p = u / (u + d)
        self.assertAlmostEqual(p, 1 / 3, delta=0.07)

    def test_plan_long_short_are_mirrors_and_ev_sign(self):
        c = synth(24 * 400, 13, vol=0.004)
        atrs = atr_series(c)
        px, atr = c[-1].c, atrs[-1]
        lg = plan(c, atrs, "long", 2.0, 1.0, 24, px, atr)
        sh = plan(c, atrs, "short", 2.0, 1.0, 24, px, atr)
        self.assertAlmostEqual(lg["tp"]["p"] + lg["sl"]["p"] + lg["none"]["p"], 1.0, places=6)
        self.assertLess(abs(lg["tp"]["p"] - sh["tp"]["p"]), 0.06)                          # marche symetrique
        self.assertLess(lg["ev"], 0.05)                                                     # pas d'esperance miraculeuse sur du hasard
        self.assertEqual(lg["rr"], 2.0)


class PersistenceTests(unittest.TestCase):
    def test_save_load_roundtrip_then_repredict_rebuilds_training_sets(self):
        import os, tempfile
        from engine import bias as B
        c = synth(24 * 330, 31, signal=0.35)
        res = B.analyse(c)
        self.assertEqual((res["since"], res["version"]), (c[0].t, B.VERSION))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bias_X.json")
            B.save(res, path)
            self.assertLess(os.path.getsize(path), 300_000)                          # pas de jeu d'apprentissage sur le disque
            back = B.load(path)
            self.assertIsNotNone(back)
            self.assertNotIn("_X", back["horizons"]["24"])
            self.assertEqual(back["horizons"]["24"]["validated"], res["horizons"]["24"]["validated"])
            more = c + synth(30, 32, start=c[-1].t + 3_600_000)[:30]
            r2 = B.repredict(back, more[:len(c) + 5], None)
            self.assertEqual(r2["t"], more[len(c) + 4].t)
            self.assertIn("tables", r2["horizons"]["24"])
            self.assertTrue(r2["horizons"]["24"]["tables"])
            pub = B.public(r2)
            json.dumps(pub)
            self.assertNotIn("_X", json.dumps(pub))
            open(path, "w").write("{pas du json")
            self.assertIsNone(B.load(path))
            self.assertIsNone(B.load(os.path.join(d, "absent.json")))

    def test_rolling_training_window_and_longer_folds_on_long_history(self):
        from engine import bias as B
        n = 24 * 1200
        idx = list(range(B.WARMUP, n - 24))
        X = [[(i % 7) / 7.0 - 0.5] * len(B.FEATS) for i in idx]
        ys = [i % 2 for i in idx]
        preds, labs, ts, folds = B.walk_forward(X[::3], ys[::3], idx[::3], 24, stride=3, max_train_h=24 * 365)
        self.assertGreater(folds, 5)
        self.assertLess(folds, 20)                                                     # plis de 90 j sur un historique long
        self.assertEqual(len(preds), len(ts))


if __name__ == "__main__":
    unittest.main()
