import json
import random
import tempfile
import unittest
from pathlib import Path

from engine import fine, liqsweep, pocketrank as pr, pocketstudy

H = 3_600_000
T0 = 1_700_000_000_000 // (24 * H) * (24 * H)


class PocketRankTests(unittest.TestCase):
    def test_group_weights(self):
        self.assertEqual(pr.group_weight("mVWAP")[0], 9.0)
        self.assertEqual(pr.group_weight("wOpen")[0], 7.0)
        self.assertEqual(pr.group_weight("pdVP")[0], 4.0)
        self.assertEqual(pr.group_weight("PWHL")[0], 7.0)
        self.assertEqual(pr.group_weight("yVWAP")[0], 10.0)
        self.assertEqual(pr.group_weight("aVWAP:1700000000000")[0], 7.0)
        self.assertEqual(pr.group_weight("STOPS")[0], pr.CROSS_W)
        self.assertIsNone(pr.group_weight("xVP:abc"))                         # profils de l'unite de temps affichee : ne comptent pas
        self.assertIsNone(pr.group_weight("RAND"))

    def test_confluences_one_per_group_within_tolerance(self):
        lv = [("dVWAP", "dVWAP", 100.2), ("dVWAP+2σ", "dVWAP", 100.1), ("wPOC", "wVP", 99.5), ("mOpen", "mOpen", 103.0), ("PDL", "PDHL", 100.0)]
        cf = pr.confluences(100.0, 100.0, lv, 0.6, skip_groups={"PDHL"})
        self.assertEqual({c["group"] for c in cf}, {"dVWAP", "wVP"})          # mOpen trop loin, PDHL = la poche elle-meme
        self.assertEqual(next(c for c in cf if c["group"] == "dVWAP")["name"], "dVWAP+2σ")   # le plus proche du groupe
        self.assertEqual(cf[0]["group"], "wVP")                               # trie par poids (semaine 7 > jour 4)

    def test_importance_parts_and_caps(self):
        many = [{"w": 10.0}] * 6
        i = pr.importance(1.0, many, 5.0)
        self.assertEqual(i["parts"], {"size": 50.0, "conf": 30.0, "age": 20.0})
        self.assertEqual((i["score"], i["grade"]), (100, "forte"))
        low = pr.importance(0.04, [], None)
        self.assertEqual(low["parts"]["size"], 10.0)                         # racine carree : une petite poche garde un peu de poids
        self.assertEqual(low["parts"]["age"], pr.UNKNOWN_AGE_PTS)
        self.assertEqual(low["grade"], "faible")

    def test_freshness_curve_follows_the_measure(self):
        self.assertEqual(pr.maturity_points(3), 20.0)                        # moins de 24 h : le plus de retournements mesures
        self.assertEqual(pr.maturity_points(24), 20.0)
        self.assertLess(pr.maturity_points(100), 20.0)
        self.assertGreater(pr.maturity_points(100), pr.maturity_points(1000))
        self.assertEqual(pr.maturity_points(5000), 0.0)
        self.assertEqual(pr.maturity_label(3), "toute fraîche")
        self.assertEqual(pr.maturity_label(500), "ancienne")

    def test_rank_per_side(self):
        ps = [{"side": "long", "imp": {"score": 40}}, {"side": "long", "imp": {"score": 70}}, {"side": "short", "imp": {"score": 10}}]
        pr.rank(ps)
        self.assertEqual([p["rank"] for p in ps], [2, 1, 1])


def bars_1h(rows):
    b = fine.Bars(H)
    for k, (o, h, l, c) in enumerate(rows):
        b.append(T0 + k * H, o, h, l, c, 10.0, 0.0)
    return b.build_cum()


class FormedAtTests(unittest.TestCase):
    def test_last_time_price_traded_at_the_level(self):
        rows = [(100, 101, 99, 100)] * 5 + [(100, 100.5, 95, 99)] + [(99, 101, 97, 100)] * 10
        b = bars_1h(rows)
        pl = liqsweep.PriceLiquidity(b)
        now = T0 + len(rows) * H
        self.assertEqual(pl.formed_at(95.0, "low", now), T0 + 5 * H)                  # le creux s'est forme a la 6e bougie
        self.assertEqual(pl.formed_at(101.0, "high", now), T0 + 15 * H)                # le prix y etait encore a la derniere bougie
        self.assertIsNone(pl.formed_at(90.0, "low", now))                              # jamais atteint dans l'historique

        class K:
            t, h, l = now, 99.0, 94.0
        self.assertEqual(pl.formed_at(95.0, "low", now, forming=K), now)               # nouveau plus bas dans la bougie en cours : toute fraiche


def walk_1h(days, seed, bounce=0.0):
    """Marche au hasard horaire ; avec `bounce` > 0, le prix repart vers le haut apres avoir perce le plus bas de la veille (effet plante)."""
    rnd = random.Random(seed)
    b = fine.Bars(H)
    px, prev_low, cur_low, boost, used = 100.0, None, None, 0, set()
    for k in range(days * 24):
        if k % 24 == 0:
            prev_low, cur_low = cur_low, None
        o = px
        drift = bounce if boost > 0 else 0.0
        boost = max(0, boost - 1)
        c = o * (1 + rnd.gauss(drift, 0.006))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.002)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.002)))
        if bounce and prev_low is not None and lo <= prev_low and prev_low not in used:
            used.add(prev_low)
            c = max(c, prev_low * 1.002)                                       # la bougie de contact se referme au-dessus
            h = max(h, c)
            boost = 6
        b.append(T0 + k * H, o, h, lo, c, 10.0, 0.0)
        cur_low = lo if cur_low is None else min(cur_low, lo)
        px = c
    return b.build_cum()


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.null = pocketstudy.run(walk_1h(420, seed=5), T0 + 40 * 24 * H, T0 + 250 * 24 * H)
        cls.plant = pocketstudy.run(walk_1h(420, seed=6, bounce=0.004), T0 + 40 * 24 * H, T0 + 250 * 24 * H)

    @staticmethod
    def row(rows, dim, name):
        return next(r for r in rows if r["dim"] == dim and r["name"] == name)

    def test_structure(self):
        r = self.null
        self.assertEqual(r["kind"], "pockets")
        self.assertGreater(r["stats"]["touches"], 200)
        self.assertGreater(r["stats"]["samples"], 500)
        for key in ("attraction", "reaction"):
            names = {(x["dim"], x["name"]) for x in r[key]}
            self.assertIn(("all", "toutes les poches"), names)
            self.assertIn(("all", "niveaux au hasard (témoin)"), names)
            for x in r[key]:
                self.assertIn(x["verdict"], ("effet +", "effet −", "indice +", "indice −", "≈ hasard", "trop peu"))
        self.assertTrue(r["summary"]["lines"])
        json.dumps(r)

    def test_nothing_on_a_random_walk(self):
        for key in ("attraction", "reaction"):
            x = self.row(self.null[key], "all", "toutes les poches")
            self.assertLess(abs(x["ex"]), 0.06, key)
            self.assertNotIn("effet", x["verdict"], key)

    def test_planted_bounce_is_found_on_the_right_pockets(self):
        x = self.row(self.plant["reaction"], "type", "veille")
        self.assertGreater(x["ex"], 0.08)                                     # les plus bas de la veille rebondissent : la mesure le voit
        self.assertTrue(x["verdict"].startswith(("effet +", "indice +")))
        rnd = self.row(self.plant["reaction"], "all", "niveaux au hasard (témoin)")
        self.assertLess(rnd["ex"], x["ex"] - 0.05)                           # le temoin, lui, ne rebondit pas autant


class ShippedReportTests(unittest.TestCase):
    def test_btc_report_is_listed_and_loads(self):
        from data import reports as R
        d = [Path(__file__).resolve().parent.parent / "reports"]
        rep = R.load(d, "BTC", "pockets")
        self.assertEqual(rep["kind"], "pockets")
        self.assertTrue(rep["verdict"]["text"])
        self.assertIn(("pockets", "BTC"), {(x["kind"], x["label"]) for x in R.summaries(d)})


class LiveRankTests(unittest.TestCase):
    """En direct (donnees simulees) : chaque poche a un score, un age et un rang, identiques quelle que soit l'unite de temps."""

    @classmethod
    def setUpClass(cls):
        from config import Config
        from data.simulated import SimulatedSource
        from server import App
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=cls.tmp.name, port=0)
        cls.app = App(cfg, env_path=Path(cls.tmp.name) / ".env", make_source=lambda c: SimulatedSource(now_ms=1_759_104_000_000), make_hub=lambda c, s: None)
        cls.app.service.refresh_all()
        m = cls.app.service.markets["BTCUSDT"]
        cls.s15, cls.s1h, cls.s4h = m.state("15m"), m.state("1h"), m.state("4h")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_pool_has_importance_and_age(self):
        L = self.s1h["liquidity"]
        self.assertTrue(L["pools"] and L["pricePools"])
        for p in L["pools"] + L["pricePools"]:
            i = p["imp"]
            self.assertTrue(0 <= i["score"] <= 100)
            self.assertAlmostEqual(i["score"], round(sum(i["parts"].values())), delta=1)
            self.assertIn("nConf", i)
        self.assertTrue(all(p.get("rank") for p in L["pricePools"]))
        prev = [p for p in L["pricePools"] if "veille" in p["src"] or "semaine dernière" in p["src"]]
        self.assertTrue(all(p["imp"]["ageH"] is None or p["imp"]["ageH"] > 0.5 for p in prev))   # plus « formee a l'instant »

    def test_same_score_and_rank_on_every_timeframe(self):
        key = lambda p: (p["side"], p["lo"], p["hi"])
        h1 = {key(p): p for p in self.s1h["liquidity"]["pools"]}
        common = [p for p in self.s15["liquidity"]["pools"] if key(p) in h1]
        self.assertTrue(common)
        for p in common:
            q = h1[key(p)]
            self.assertEqual((p["imp"]["score"], p["rank"]), (q["imp"]["score"], q["rank"]))
        pp = {(p["side"], p["price"]): p["imp"]["score"] for p in self.s1h["liquidity"]["pricePools"]}
        for p in self.s4h["liquidity"]["pricePools"]:
            if (p["side"], p["price"]) in pp:
                self.assertEqual(p["imp"]["score"], pp[(p["side"], p["price"])])

    def test_a_ranking_error_does_not_break_the_state(self):
        m = self.app.service.markets["BTCUSDT"]
        orig = m._rank_pools
        m._rank_pools = lambda *a, **k: (_ for _ in ()).throw(ValueError("panne simulée"))
        try:
            st = m.state("1h")
        finally:
            m._rank_pools = orig
        self.assertTrue(st["liquidity"]["pools"])
        self.assertIn("panne simulée", st["liquidity"]["rankError"])
        self.assertIsNone(m.state("1h")["liquidity"]["rankError"])

    def test_top_ranked_pools_are_always_shown(self):
        for s in (self.s15, self.s1h, self.s4h):
            L = s["liquidity"]
            shown = L["pools"] + L["extraPools"]
            for side in ("long", "short"):
                ranks = {p.get("rank") for p in shown if p["side"] == side}
                if any(p["side"] == side for p in shown if p.get("rank")):
                    self.assertIn(1, ranks)
            self.assertTrue(all(p["extra"] and p["rank"] <= 2 for p in L["extraPools"]))
            ids = {(p["side"], p["lo"], p["hi"]) for p in L["pools"]}
            self.assertFalse(any((p["side"], p["lo"], p["hi"]) in ids for p in L["extraPools"]))


if __name__ == "__main__":
    unittest.main()
