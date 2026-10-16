import json
import random
import unittest

from engine import backtest as bt
from engine import fine, hedge, stratstudy, vwapstrat as vs

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = bt.ms(2023, 1, 2)                       # un lundi


def b5_from(path, vol=10.0, step=300_000, t0=T0):
    """Bougies 5 min suivant `path` : liste de (haut, bas, cloture), ouverture = cloture precedente."""
    b = fine.Bars(step)
    px = path[0][2]
    for k, (h, l, c) in enumerate(path):
        v = vol[k] if isinstance(vol, list) else vol
        b.append(t0 + k * step, px, h, l, c, v, 0.0)
        px = c
    return b.build_cum()


def flat(n, px=100.0, vol=10.0):
    return [(px + 0.05, px - 0.05, px)] * n


class SimulateTests(unittest.TestCase):
    def test_long_target_reached(self):
        b = b5_from(flat(3) + [(101.2, 99.9, 101.0)] + flat(4, 101.0))
        s = vs.simulate_v(b, T0, 1, 98.0, 101.0, None, 1.0, 24)
        self.assertEqual(s["result"], "tp")
        self.assertAlmostEqual(s["r_gross"], (101.0 - 100.0) / 2.0, places=6)

    def test_stop_first_when_same_bar(self):
        b = b5_from(flat(2) + [(103.0, 97.0, 100.0)] + flat(3))
        s = vs.simulate_v(b, T0, 1, 98.0, 102.0, None, 1.0, 24)
        self.assertEqual(s["result"], "stop")
        self.assertAlmostEqual(s["r_gross"], -1.0, places=6)

    def test_partial_then_break_even(self):
        b = b5_from(flat(2) + [(102.5, 100.0, 102.0)] + [(102.1, 99.9, 100.0)] + flat(3))
        s = vs.simulate_v(b, T0, 1, 98.0, 102.0, 106.0, 0.5, 24)
        self.assertEqual(s["result"], "tp1_be")
        self.assertAlmostEqual(s["r_gross"], 0.5 * 1.0, places=6)

    def test_short_symmetry(self):
        b = b5_from(flat(2) + [(100.0, 97.5, 98.0)] + flat(3, 98.0))
        s = vs.simulate_v(b, T0, -1, 102.0, 98.0, None, 1.0, 24)
        self.assertEqual(s["result"], "tp")
        self.assertAlmostEqual(s["r_gross"], 1.0, places=6)

    def test_gap_beyond_the_stop_cancels(self):
        b = b5_from([(100.0, 100.0, 100.0)] * 3)
        self.assertEqual(vs.simulate_v(b, T0, 1, 100.5, 103.0, None, 1.0, 24)["result"], "cancel")

    def test_hold_is_extended_only_with_volume(self):
        # entree a l'instant 24 h de la serie ; sortie prevue 1 h plus tard (hold 1 h, prolongation a 2 h)
        base = 24 * 12
        quiet = [10.0] * (base + 40)
        for k in range(base, base + 12):
            quiet[k] = 4.0                                                    # derniere heure : volume faible
        busy = [10.0] * (base + 40)
        for k in range(base, base + 12):
            busy[k] = 40.0                                                    # derniere heure : 4 fois la normale
        s1 = vs.simulate_v(b5_from(flat(base + 40), vol=quiet), T0 + 24 * HOUR, 1, 90.0, 120.0, None, 1.0, 1, 2)
        s2 = vs.simulate_v(b5_from(flat(base + 40), vol=busy), T0 + 24 * HOUR, 1, 90.0, 120.0, None, 1.0, 1, 2)
        self.assertFalse(s1["extended"])
        self.assertAlmostEqual(s1["hours"], 1.0, places=6)
        self.assertTrue(s2["extended"])
        self.assertAlmostEqual(s2["hours"], 2.0, places=6)


class GeometryTests(unittest.TestCase):
    def ev(self, d=1):
        return {"price": 100.0, "atr": 1.0, "dir": d, "V": 100.2 if d > 0 else 99.8, "l": 99.5, "h": 100.5, "up": [(101.5, 80), (103.0, 70), (106.0, 90)], "dn": [(98.5, 80), (97.0, 70)]}

    def test_structure_stop_is_under_the_bar_and_widened_to_one_atr(self):
        stop, tp1, tp2, part = vs.geometry(self.ev(), "struct", "pool")
        self.assertAlmostEqual(stop, 99.0)                                     # sous le plus bas de la bougie - 0,25 ATR... elargi a 1 ATR
        self.assertEqual((tp1, tp2, part), (101.5, None, 1.0))

    def test_too_far_structure_stop_gives_no_trade(self):
        e = self.ev()
        e["l"] = 94.0
        self.assertIsNone(vs.geometry(e, "struct", "pool"))
        self.assertIsNotNone(vs.geometry(e, "atr15", "pool"))

    def test_pool_target_must_pay_one_risk_and_exist(self):
        e = self.ev()
        e["up"] = [(100.4, 80)]
        self.assertIsNone(vs.geometry(e, "struct", "pool"))
        stop, tp1, _, _ = vs.geometry(e, "struct", "pool2R")                   # repli a 2 fois le risque
        self.assertAlmostEqual(tp1, 100.0 + 2 * (100.0 - stop))
        stop, tp1, _, _ = vs.geometry(e, "struct", "2R")
        self.assertAlmostEqual(tp1, 100.0 + 2 * (100.0 - stop))

    def test_half_and_short(self):
        stop, tp1, tp2, part = vs.geometry(self.ev(), "atr15", "poolhalf")
        self.assertEqual((tp1, tp2, part), (101.5, 103.0, 0.5))
        s, t1, t2, p = vs.geometry(self.ev(-1), "atr15", "poolhalf")
        self.assertAlmostEqual(s, 101.5)
        self.assertEqual((t1, t2), (98.5, 97.0))


class EventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rnd = random.Random(9)
        b = fine.Bars(MIN)
        px = 100.0
        for k in range(130 * 1440):
            o = px
            c = o * (1 + rnd.gauss(0, 0.0007))
            h, l = max(o, c) * 1.0003, min(o, c) * 0.9997
            b.append(T0 + k * MIN, o, h, l, c, 5 + rnd.random() * 10, 0.0)
            px = c
        cls.ds = bt.Dataset.from_1m(b.build_cum())
        cls.ev = vs.build_events(cls.ds, T0 + 90 * DAY, T0 + 125 * DAY)

    def test_events_exist_and_are_consistent(self):
        ev = self.ev
        self.assertGreater(len(ev), 50)
        for e in ev:
            self.assertEqual(e["t"] % HOUR, 0)
            if e["tf"] == "4h":
                self.assertEqual(e["t"] % (4 * HOUR), 0)
            self.assertTrue(e["l"] <= e["V"] <= e["h"])                       # la bougie touche le niveau
            self.assertEqual(e["dir"], 1 if e["c"] > e["V"] else -1)          # sens = cote de la cloture
            self.assertIn(e["type"], ("cross", "bounce"))
            self.assertGreater(e["atr"], 0)
            self.assertTrue(all(p > e["price"] for p, _ in e["up"]))
            self.assertTrue(all(p < e["price"] for p, _ in e["dn"]))
            self.assertIn(e["grp"], ("W", "M"))
        self.assertEqual([e["t"] for e in ev], sorted(e["t"] for e in ev))

    def test_cooldown_per_level_and_direction(self):
        seen = {}
        for e in self.ev:
            k = (e["tf"], e["level"], e["dir"])
            step = HOUR if e["tf"] == "1h" else 4 * HOUR
            if k in seen:
                self.assertGreaterEqual(e["t"] - seen[k], vs.COOLDOWN_BARS * step)
            seen[k] = e["t"]

    def test_attach_and_pick_one_trade_at_a_time(self):
        ev = [{**e, "fade": False} for e in self.ev]
        vs.attach(ev, self.ds, ["atr15|2R|H24"])
        a, b = T0 + 90 * DAY, T0 + 125 * DAY
        tr = vs.pick(ev, "atr15|2R|H24", lambda e: True, bt.DEFAULT_COSTS, a, b)
        self.assertGreater(len(tr), 3)
        for x, y in zip(tr, tr[1:]):
            self.assertLessEqual(x["exit_t"], y["fill_t"] + 1)               # jamais deux positions a la fois
        m = bt.metrics(tr, a, b)
        self.assertIsNotNone(m["expR"])

    def test_as_candidates_keeps_the_highest_priority_level_per_bar_and_direction(self):
        base = {"t": 1000, "tf": "1h", "dir": 1, "type": "cross", "level": "x", "rank": 5, "atr": 1.0, "price": 100.0, "reg": 0, "sims": {"c": {"result": "tp", "filled": True}}}
        evs = [dict(base), dict(base, rank=1, level="y"), dict(base, dir=-1, level="z")]
        c = vs.as_candidates(evs, "c", lambda e: True)
        self.assertEqual(sorted(x["key"] for x in c), ["y|1h", "z|1h"])
        c2 = vs.as_candidates(evs, "c", lambda e: e["level"] != "y")
        self.assertEqual(sorted(x["key"] for x in c2), ["x|1h", "z|1h"])

    def test_rules_do_not_depend_on_the_side_taken(self):
        """Un filtre juge le signal d'origine : la variante inverse (meme signal, sens oppose) doit donner la meme reponse."""
        for e in self.ev[:120]:
            f = {**e, "dir": -e["dir"], "fade": True}
            for name, _, rule in stratstudy.rules():
                self.assertEqual(bool(rule(e)), bool(rule(f)), name)

    def test_full_study_runs_serializes_and_matches_a_direct_pick(self):
        a, b, split = T0 + 90 * DAY, T0 + 125 * DAY, T0 + 110 * DAY
        evs = []
        for e in self.ev:
            evs.append({**e, "fade": False})
            evs.append({**e, "dir": -e["dir"], "fade": True})
        eras = [("a", a, split), ("b", split, b)]
        rep = stratstudy.run(self.ds, evs, "TEST", a, b, split, eras, control_runs=3, min_exit=3, min_rule=3, extra_hedges=None)
        json.dumps(rep)
        self.assertEqual(rep["kind"], "vwap-strategy")
        self.assertEqual(len(rep["exits"]), len(vs.CONFIGS))
        ex = [x["is"]["expR"] for x in rep["exits"] if x["is"]["expR"] is not None]
        self.assertEqual(ex, sorted(ex, reverse=True))
        self.assertTrue(1 <= len(rep["chosenExits"]) <= 3 and set(rep["chosenExits"]) <= set(vs.CONFIGS))
        self.assertEqual(len(rep["variants"]), len(stratstudy.rules()) * 2 * len(rep["chosenExits"]))
        self.assertEqual({v["side"] for v in rep["variants"]}, {"suivre", "inverse"})
        self.assertEqual(rep["ranking"][0], [rep["best"]["name"], rep["best"]["side"], rep["best"]["cfg"]])
        self.assertIn("text", rep["verdict"])
        self.assertIsInstance(rep["verdict"]["edge"], bool)
        self.assertIn(rep["verdict"]["level"], ("edge", "weak", "none"))
        self.assertEqual(rep["verdict"]["edge"], rep["verdict"]["level"] == "edge")
        # la ligne « regle litterale » vaut une selection directe sur la meme periode
        cfg = rep["chosenExits"][0]
        lit = [e for e in evs if not e["fade"]]
        vs.attach(lit, self.ds, [cfg])
        direct = vs.pick(lit, cfg, lambda e: True, bt.DEFAULT_COSTS, a, b)
        self.assertEqual(rep["literal"]["all"]["n"], len(direct))
        self.assertAlmostEqual(rep["literal"]["all"]["expR"], sum(t["r"] for t in direct) / len(direct), places=9)
        h = rep["hedge"]
        self.assertEqual(h["weights"], [0.25, 0.5, 1.0])
        self.assertTrue(h["all"]["rows"])
        for r in h["all"]["rows"]:
            self.assertEqual(len(r["mix"]), 3)

    def test_parallel_and_sequential_exits_agree(self):
        evs = [{**e, "fade": False} for e in self.ev] * 40                    # assez d'evenements pour passer par le parallele
        cfg = "atr15|2R|H24"
        seq = stratstudy.Sims(self.ds, 1)
        seq.ensure(evs, cfg)
        ref = [e["sims"][cfg] for e in evs]
        par = stratstudy.Sims(self.ds, 2)
        for e in evs:
            e["sims"] = {}
        par.ensure(evs, cfg)
        self.assertEqual(ref, [e["sims"][cfg] for e in evs])


class HedgeTests(unittest.TestCase):
    def trades(self, rs, start=0):
        return [{"exit_t": start + k * hedge.WEEK + 1000, "r": r, "stop_pct": 0.01} for k, r in enumerate(rs)]

    def test_series_and_corr(self):
        tr = self.trades([1, -1, 2, -2])
        s = hedge.series(tr, 0, 4 * hedge.WEEK)
        self.assertEqual(len(s), 5)
        self.assertAlmostEqual(s[0], 0.01)
        self.assertAlmostEqual(hedge.corr([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]), 1.0)
        self.assertAlmostEqual(hedge.corr([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]), -1.0)

    def test_perfect_hedge_removes_drawdown(self):
        rnd = random.Random(3)
        rs = [rnd.choice((-1.0, 2.0)) for _ in range(120)]
        main = self.trades(rs)
        mirror = self.trades([-r + 0.6 for r in rs])                           # gagne quand la principale perd, avec un petit biais positif
        junk = self.trades([rnd.choice((-1.0, 1.0)) for _ in range(120)])
        ev = hedge.evaluate(main, {"miroir": mirror, "bruit": junk}, 0, 120 * hedge.WEEK)
        row = {r["name"]: r for r in ev["rows"]}
        self.assertLess(row["miroir"]["corr"], -0.9)
        best = hedge.best_hedge(ev)
        self.assertEqual(best[1], "miroir")
        self.assertLess(best[3]["maxDD"], ev["main"]["maxDD"])


if __name__ == "__main__":
    unittest.main()
