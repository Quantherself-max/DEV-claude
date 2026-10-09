"""TPO (V17) : lettres par tranche, POC, zone de valeur, single prints, queues, poor high / low, marques comblees ou non, seances."""
import unittest

from engine import tpo
from engine.atr import Candle

M30 = 30 * 60_000
M5 = 5 * 60_000


def bar(t, lo, hi):
    return Candle(t, lo, hi, lo, hi, 1.0, 0.5)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        # une bougie par tranche de 30 min ; pas de 1 $ : lignes 100 a 107
        #   A, B : 100,5 - 102,5   C : 102,5 - 106,5 (traverse seule 103 a 105)   D, E : 106,5 - 107,5
        self.bars = [bar(0, 100.5, 102.5), bar(M30, 100.5, 102.5), bar(2 * M30, 102.5, 106.5), bar(3 * M30, 106.5, 107.5), bar(4 * M30, 106.5, 107.5)]
        self.p = tpo.profile(self.bars, 0, tpo.DAY, M30, 1.0)

    def test_letters_poc_and_value_area(self):
        p = self.p
        self.assertEqual(p["brackets"], 5)
        self.assertEqual([r[0] for r in p["rows"]], [100, 101, 102, 103, 104, 105, 106, 107])
        self.assertEqual([r[1] for r in p["rows"]], [2, 2, 3, 1, 1, 1, 3, 2])
        self.assertEqual(p["rows"][2][2], "ABC")                          # lettres des tranches qui ont touche 102
        self.assertEqual(p["rows"][7][2], "DE")
        self.assertEqual(p["poc"], 102.5)                                 # egalite 3 / 3 : la ligne la plus proche du milieu
        self.assertEqual((p["val"], p["vah"]), (100.0, 107.0))
        self.assertEqual(p["ib"], [100.5, 102.5])                         # premiere heure (tranches A et B)

    def test_single_prints_and_poor_extremes(self):
        p = self.p
        self.assertEqual(p["singles"], [[103.0, 106.0]])                  # 103, 104, 105 : une seule tranche (C)
        self.assertTrue(p["poorHigh"])                                    # deux tranches au plus haut, pas de queue
        self.assertTrue(p["poorLow"])
        self.assertIsNone(p["tailHigh"])
        self.assertIsNone(p["tailLow"])

    def test_tail_is_not_a_single_print_nor_poor(self):
        bars = [bar(0, 100.5, 102.5), bar(M30, 100.5, 102.5), bar(2 * M30, 101.5, 105.5)]
        p = tpo.profile(bars, 0, tpo.DAY, M30, 1.0)
        self.assertEqual([r[1] for r in p["rows"]], [2, 3, 3, 1, 1, 1])
        self.assertEqual(p["tailHigh"], [103.0, 105.5])                   # rejet net en haut : queue (excess)
        self.assertFalse(p["poorHigh"])
        self.assertTrue(p["poorLow"])
        self.assertEqual(p["singles"], [])
        one = tpo.profile([bar(0, 100.5, 102.5)], 0, tpo.DAY, M30, 1.0)  # une seule tranche : rien a lire
        self.assertEqual((one["singles"], one["poorHigh"], one["poorLow"]), ([], False, False))
        self.assertIsNone(tpo.profile([], 0, tpo.DAY, M30, 1.0))
        short = [bar(0, 100.5, 102.5), bar(M30, 100.5, 102.5), bar(2 * M30, 102.5, 103.5)]
        self.assertEqual(tpo.profile(short, 0, tpo.DAY, M30, 1.0)["singles"], [])          # une seule ligne isolee : pas assez (2 minimum)
        self.assertEqual(tpo.profile(short, 0, tpo.DAY, M30, 1.0, min_single=1)["tailHigh"], [103.0, 103.5])

    def test_marks_filled_and_repaired(self):
        p = self.p
        m = tpo.marks(p, 104.0, 110.0, False)                             # le prix n'est pas redescendu sous 104 : zone pas comblee
        self.assertEqual(m["singles"], [[103.0, 106.0, False]])
        self.assertEqual(m["poorHigh"], {"price": 107.5, "active": False})   # 110 > 107,5 : plus haut depasse, repare
        self.assertEqual(m["poorLow"], {"price": 100.5, "active": True})
        m = tpo.marks(p, 102.9, 106.2, False)
        self.assertEqual(m["singles"], [[103.0, 106.0, True]])            # toute la zone a ete retraversee
        self.assertTrue(m["poorHigh"]["active"])
        m = tpo.marks(p, 0.0, 1e9, True)                                  # seance en cours : rien n'est encore comble ni repare
        self.assertEqual(m["singles"][0][2], False)
        self.assertTrue(m["poorHigh"]["active"] and m["poorLow"]["active"])


class SessionsTests(unittest.TestCase):
    def test_sessions_common_step_cache_and_marks(self):
        day = tpo.DAY
        bars = []
        for d in range(3):                                                # 3 jours de bougies 5 min, chaque jour un peu plus haut
            for i in range(day // M5):
                base = 100 + 5 * d + (i % 24) * 0.25
                bars.append(Candle(d * day + i * M5, base, base + 0.4, base - 0.4, base, 1.0, 0.5))
        now = 2 * day + 12 * 3_600_000
        bars = [k for k in bars if k.t <= now]
        cache = {}
        r = tpo.sessions(bars, "D", now, n=5, cache=cache)
        self.assertEqual(r["kind"], "D")
        self.assertEqual([s["start"] for s in r["sessions"]], [0, day, 2 * day])     # de la plus ancienne a la plus recente
        self.assertTrue(all(s["step"] == r["step"] for s in r["sessions"]))
        self.assertEqual([s["marks"]["current"] for s in r["sessions"]], [False, False, True])
        self.assertEqual(len(cache), 2)                                   # seances terminees gardees en memoire
        again = tpo.sessions(bars, "D", now, n=5, cache=cache)
        self.assertEqual(again["sessions"][0]["rows"], r["sessions"][0]["rows"])
        for s in r["sessions"]:
            self.assertTrue(s["val"] <= s["poc"] <= s["vah"])
            self.assertEqual(s["label"], "1 jour")
        h4 = tpo.sessions(bars, "4h", now)
        self.assertTrue(1 <= len(h4["sessions"]) <= tpo.KINDS["4h"]["n"])
        self.assertTrue(h4["sessions"][-1]["marks"]["current"])
        self.assertEqual(tpo.sessions([], "1h", now)["sessions"], [])
        lo, hi = tpo.suffix_extremes(bars)
        self.assertEqual((lo[0], hi[0]), (min(k.l for k in bars), max(k.h for k in bars)))


if __name__ == "__main__":
    unittest.main()
