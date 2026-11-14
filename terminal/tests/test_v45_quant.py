"""V45 : moteur de calcul exact (quant). Chaque valeur attendue est calculée à la main dans le commentaire du test."""
from __future__ import annotations
import math
import os
import sys
import unittest
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant import book, execution, flow, metrics, num, options, perp, profile, regime
from quant.num import D, UNIT, units

U = UNIT


class NumTest(unittest.TestCase):
    def test_float_is_refused_and_text_is_exact(self):
        with self.assertRaises(TypeError):
            D(0.1)
        self.assertEqual(D("0.1") + D("0.2"), D("0.3"))                 # en flottants : 0.30000000000000004
        self.assertNotEqual(0.1 + 0.2, 0.3)
        self.assertEqual(num.from_float(0.1), D("0.1"))
        with self.assertRaises(ValueError):
            D("NaN")
        with self.assertRaises(ValueError):
            D("abc")

    def test_units_fast_path_matches_decimal(self):
        for s in ("0.001", "68224.47", "0", "1", "123.45678901", ".5", "5.", "-2.50", "+3.1", "0.00000001", "1e-3", "2.5E2"):
            self.assertEqual(units(s), int(D(s) * U), s)
        self.assertEqual(units(7), 7 * U)
        self.assertEqual(units(b"1.5"), 150_000_000)
        with self.assertRaises(ValueError):
            units("0.123456789")                                         # 9 décimales : refusé, pas arrondi
        self.assertEqual(units("0.123456789", 9), 123456789)
        self.assertEqual(num.from_units(150_000_000), D("1.5"))

    def test_quantize_and_fmt(self):
        self.assertEqual(num.quantize("0.123456", "0.001"), D("0.123"))
        self.assertEqual(num.quantize("0.123456", "0.001", "ceil"), D("0.124"))
        self.assertEqual(num.quantize("68224.47", "0.1", "near"), D("68224.5"))
        self.assertEqual(num.quantize("-1.25", "0.1"), D("-1.3"))            # plancher : vers moins l'infini
        self.assertEqual(num.fmt("68224.5", "0.01"), "68224.50")
        self.assertEqual(num.fmt(D("1E+3")), "1000")
        self.assertEqual(num.decimals_of("0.00100"), 3)

    def test_timestamps(self):
        ms = 1_794_619_186_123
        self.assertEqual(num.to_ms(ms), ms)
        self.assertEqual(num.to_ms(ms // 1000), ms // 1000 * 1000)
        self.assertEqual(num.to_ms(ms * 1000 + 999), ms)                      # microsecondes, tronquées
        self.assertEqual(num.to_ms(ms * 1_000_000 + 5), ms)                   # nanosecondes
        self.assertEqual(num.to_ms(str(ms)), ms)
        self.assertEqual(num.to_ms("1794619186.123"), ms)
        self.assertEqual(num.to_ms(1.794619186E12), 1_794_619_186_000)        # flottant de blockchain.info
        self.assertEqual(num.to_ms("2026-11-10T00:00:00.000000000Z"), 1_794_268_800_000)
        self.assertEqual(num.to_ms("2026-11-10T01:00:00+01:00"), 1_794_268_800_000)
        self.assertEqual(num.to_ms("2026-11-10 00:00:00.5"), 1_794_268_800_500)
        self.assertEqual(num.to_ms("1970-01-01T00:00:01Z"), 1000)
        with self.assertRaises(TypeError):
            num.to_ms(None)


class PerpTest(unittest.TestCase):
    def test_pnl_fees_funding(self):
        # long 0.5 BTC de 68 000 à 69 000 : +500 $ ; short : -500 $
        self.assertEqual(perp.pnl("long", "0.5", "68000", "69000"), D("500"))
        self.assertEqual(perp.pnl(-1, "0.5", "68000", "69000"), D("-500"))
        self.assertEqual(perp.fee("0.5", "68000", "0.0005"), D("17"))        # 34 000 × 0,05 %
        # financement +0,01 % sur 34 000 $ : le long paie 3,40 $, le short reçoit 3,40 $
        self.assertEqual(perp.funding_payment("long", "0.5", "68000", "0.0001"), D("-3.4"))
        self.assertEqual(perp.funding_payment("short", "0.5", "68000", "0.0001"), D("3.4"))
        ev = [(8, "0.0001", "68000"), (16, "-0.0002", "68000"), (24, "0.0001", "68000")]
        # ouverte à 8 (pile à l'échéance : ne paie pas), fermée à 16 : seule l'échéance de 16 compte : le long REÇOIT 6,80 $
        self.assertEqual(perp.funding_total("long", "0.5", ev, 8, 16), D("6.8"))
        self.assertEqual(perp.funding_total("long", "0.5", ev, 0, 24), D("0"))           # -3,4 + 6,8 - 3,4

    def test_liquidation_price_isolated(self):
        # long 1 BTC à 60 000, levier 10 : marge 6 000 ; mmr 0,4 % : P = (6000 - 60000) / (0,004 - 1) = 54 216,867...
        p = perp.liquidation_price("long", "1", "60000", "6000", mmr="0.004")
        self.assertEqual(p.quantize(D("0.01")), D("54216.87"))
        # vérification : à ce prix la marge restante vaut la marge de maintien
        self.assertAlmostEqual(float(D("6000") + (p - D("60000"))), float(p * D("0.004")), places=20)
        # short : P = (6000 + 60000) / (0,004 + 1) = 65 737,05...
        s = perp.liquidation_price("short", "1", "60000", "6000", mmr="0.004")
        self.assertEqual(s.quantize(D("0.01")), D("65737.05"))
        self.assertEqual(perp.bankruptcy_price("long", "1", "60000", "6000"), D("54000"))
        self.assertIsNone(perp.liquidation_price("long", "1", "60000", "70000", mmr="0.004"))   # marge > position : pas de liquidation

    def test_liquidation_with_tiers(self):
        tiers = [("50000", "0.004", "0"), ("600000", "0.005", "50"), (None, "0.01", "3050")]
        # 5 BTC à 60 000 (300 000 $) : palier 2 ; P = (30000 + 50 - 300000) / (5 × (0,005 - 1)) = 54 261,306...
        p = perp.liquidation_price("long", "5", "60000", "30000", tiers=tiers)
        self.assertEqual(p.quantize(D("0.01")), D("54261.31"))
        self.assertEqual(perp.tier_for("600000", tiers), (D("0.005"), D("50")))
        self.assertEqual(perp.tier_for("600000.01", tiers), (D("0.01"), D("3050")))

    def test_position_size(self):
        # 10 000 $ de capital, 1 % de risque (100 $), entrée 68 000, stop 67 320 (680 $) : 100 / 680 = 0,14705... -> 0,147 BTC
        r = perp.position_size("10000", "0.01", "68000", "67320", "0.001")
        self.assertEqual(r["qty"], D("0.147"))
        self.assertEqual(r["notional"], D("9996"))
        self.assertEqual(r["loss_at_stop"], D("99.96"))
        self.assertEqual(r["side"], 1)
        # avec les frais (0,05 % à l'entrée et à la sortie) : par pièce 680 + 34 + 33,66 = 747,66 -> 0,13375 -> 0,133
        r = perp.position_size("10000", "0.01", "68000", "67320", "0.001", "0.0005", "0.0005")
        self.assertEqual(r["qty"], D("0.133"))
        self.assertLessEqual(r["loss_at_stop"], D("100"))
        # plafond de levier 0,5 : notionnel au plus 5 000 $ -> 0,0735 -> 0,073
        r = perp.position_size("10000", "0.01", "68000", "67320", "0.001", max_leverage="0.5")
        self.assertEqual((r["qty"], r["capped"]), (D("0.073"), True))
        with self.assertRaises(ValueError):
            perp.position_size("10000", "0.01", "68000", "68000", "0.001")

    def test_break_even_and_net(self):
        be = perp.break_even("long", "68000", "0.0005", "0.0005")
        r = perp.net_result("long", "1", "68000", be, "0.0005", "0.0005")
        self.assertLess(abs(r["net"]), D("1e-30"))
        be = perp.break_even("short", "68000", "0.0002", "0.0005")
        self.assertLess(abs(perp.net_result("short", "1", "68000", be, "0.0002", "0.0005")["net"]), D("1e-30"))
        self.assertEqual(perp.r_multiple("long", "68000", "67320", "69360"), D("2"))
        self.assertEqual(perp.r_multiple("short", "68000", "68680", "69360"), D("-2"))


def tick(c, t, px, qty, side):
    c.add(t, units(px), units(qty), side)


class FlowTest(unittest.TestCase):
    def test_exact_cvd_where_floats_drift(self):
        c = flow.TickCvd(60_000)
        f = 0.0
        for i in range(100_000):                                          # 100 000 achats de 0,001 puis autant de ventes
            c.add(i, units("68000.1"), units("0.001"), 1)
            f += 0.001
        self.assertEqual(c.buy, 100 * U)                                  # exactement 100 BTC
        self.assertNotEqual(f, 100.0)                                     # la somme flottante, elle, dérive
        self.assertEqual(c.buyq, 100 * U * units("68000.1"))

    def test_bars_and_window(self):
        c = flow.TickCvd(60_000)
        tick(c, 60_000, "100", "2", 1)
        tick(c, 61_000, "101", "1", -1)
        tick(c, 119_999, "99", "3", -1)
        tick(c, 120_000, "100", "5", 1)
        b = c.bars[60_000]
        self.assertEqual((b[flow.O], b[flow.H], b[flow.L], b[flow.C]), (100 * U, 101 * U, 99 * U, 99 * U))
        self.assertEqual((b[flow.BUY], b[flow.SELL], b[flow.N]), (2 * U, 4 * U, 3))
        self.assertEqual(b[flow.BUYQ] - b[flow.SELLQ], (200 - 101 - 297) * U * U)
        self.assertTrue(b[flow.OK])                                        # le flux a commencé pile au début de la barre
        w = c.window(60_000, 180_000)
        self.assertEqual((w["delta"], w["n"], w["cover"]), (3 * U, 4, Fraction(1)))
        self.assertEqual(len(c.closed(120_000)), 1)
        c.gap(125_000, 185_000)
        self.assertFalse(c.bars[120_000][flow.OK])
        self.assertEqual(c.window(60_000, 240_000)["cover"], Fraction(1, 3))

    def test_first_bar_incomplete_then_checked_against_official(self):
        c = flow.TickCvd(60_000)
        tick(c, 90_000, "100", "1", 1)                                     # le flux démarre au milieu de la minute
        self.assertFalse(c.bars[60_000][flow.OK])
        official = (60_000, 100 * U, 100 * U, 100 * U, 100 * U, 3 * U, 1 * U, 300 * U * U, 100 * U * U, 7)
        self.assertIn("volume 1.00000000 contre 4.00000000", c.check(official))
        self.assertEqual(c.seed([official], replace=False), 1)
        self.assertIsNone(c.check(official))
        self.assertTrue(c.bars[60_000][flow.OK])

    def _bars(self, lows_highs_delta):
        out = []
        for i, (lo, hi, d) in enumerate(lows_highs_delta):
            buy, sell = (10 + d, 10) if d >= 0 else (10, 10 - d)
            out.append([i * 60_000, hi * U, hi * U, lo * U, lo * U, buy * U, sell * U, buy * U * U, sell * U * U, 2, True])
        return out

    def test_divergence_is_known_only_after_confirmation(self):
        # creux à 95 (barre 3) puis creux plus bas à 93 (barre 9) ; entre les deux le CVD monte : divergence haussière
        seq = [(100, 102, 0), (98, 101, -5), (96, 99, -5), (95, 97, -5), (97, 99, 4), (98, 100, 4), (97, 99, 4), (95, 98, 2),
               (94, 96, 1), (93, 95, 1), (95, 97, 3), (96, 98, 3), (97, 99, 3)]
        bars = self._bars(seq)
        dv = flow.divergences(bars, left=2, right=2)
        bull = [d for d in dv if d["side"] == "bull"]
        self.assertEqual(len(bull), 1)
        d = bull[0]
        self.assertEqual((d["kind"], d["t1"], d["t2"], d["p1"], d["p2"]), ("regular", 3 * 60_000, 9 * 60_000, 95 * U, 93 * U))
        self.assertEqual(d["known"], 12 * 60_000)                          # clôture de la barre 11 = 9 + 2
        self.assertGreater(d["c2"], d["c1"])
        # sans les deux barres de confirmation, la divergence n'existe pas encore
        self.assertEqual([x for x in flow.divergences(bars[:11], left=2, right=2) if x["side"] == "bull"], [])
        self.assertEqual(len([x for x in flow.divergences(bars[:12], left=2, right=2) if x["side"] == "bull"]), 1)

    def test_absorption(self):
        base = [[i * 60_000, 100 * U, 101 * U, 99 * U, 100 * U, 5 * U, 5 * U, 500 * U * U, 500 * U * U, 10, True] for i in range(20)]
        # gros volume acheteur (30 contre 6), le prix ne monte pas : achats absorbés (baissier)
        hit = [20 * 60_000, 100 * U, 101 * U, 99 * U, 100 * U, 30 * U, 6 * U, 3000 * U * U, 600 * U * U, 50, True]
        # même volume mais le prix monte de 2 (amplitude médiane 2) : pas une absorption
        moved = [21 * 60_000, 100 * U, 102 * U, 100 * U, 102 * U, 30 * U, 6 * U, 3000 * U * U, 600 * U * U, 50, True]
        out = flow.absorptions(base + [hit, moved], base=20)
        self.assertEqual([(a["t"], a["side"]) for a in out], [(20 * 60_000, "bear")])
        self.assertEqual(out[0]["imb"], Fraction(24, 36))
        self.assertEqual(out[0]["volRatio"], Fraction(36, 10))

    def test_resample_and_venues(self):
        c = flow.TickCvd(60_000)
        for i in range(10):
            tick(c, i * 60_000, str(100 + i), "1", 1 if i % 2 else -1)
        r = flow.resample(c.closed(600_000), 300_000)
        self.assertEqual(len(r), 2)
        self.assertEqual((r[0][flow.O], r[0][flow.C], r[0][flow.H]), (100 * U, 104 * U, 104 * U))
        self.assertEqual(r[0][flow.BUY] - r[0][flow.SELL], -1 * U)
        v = flow.VenueFlow()
        v.add("binance_perp", 0, units("68000"), units("1"), 1)
        v.add("okx_inverse", 0, units("68000"), units("0.00147058"), -1, quote_u=units("100"))     # contrat de 100 dollars
        w = v.window(0, 60_000)
        self.assertEqual(flow.usd(w["deltaq"]), 67900.0)
        self.assertEqual(flow.usd(w["venues"]["okx_inverse"]["sellq"]), 100.0)


class ProfileTest(unittest.TestCase):
    def test_poc_and_value_area_by_hand(self):
        # lignes de 1 $ à partir de 100 : volumes 1 2 8 10 9 3 1 1 = 35 ; 70 % = 24,5
        vol = [1, 2, 8, 10, 9, 3, 1, 1]
        r = profile.value_area(vol, 100, U, 70)
        # POC = ligne 103 (10). Paire du haut 9 + 3 = 12, paire du bas 8 + 2 = 10 : on prend le haut (22), puis le bas (32 >= 24,5)
        self.assertEqual((r["poc"], r["vah"], r["val"]), (D("103"), D("106"), D("101")))
        self.assertEqual((r["inValue"], r["share"]), (32, Fraction(32, 35)))

    def test_ties_and_integer_threshold(self):
        r = profile.value_area([5, 5, 5, 5], 0, U, 70)
        self.assertEqual((r["poc_u"], r["ties"]), (1 * U, 4))               # égalité : la plus proche du milieu, puis la plus basse
        # exactement 70 % : 7 sur 10 suffit (comparaison en entiers, pas 0,7 × 10 = 7,000000000000001)
        r = profile.value_area([7, 3], 0, U, 70)
        self.assertEqual((r["vah_u"], r["val_u"], r["inValue"]), (1 * U, 0, 7))

    def test_from_trades_and_buckets(self):
        p = profile.ExactProfile(units("0.1"))
        for px, q, s in (("68000.0", "0.5", 1), ("68000.0", "0.25", -1), ("68000.1", "2", 1), ("67999.9", "0.1", -1)):
            p.add(units(px), units(q), s)
        lv = p.levels()
        self.assertEqual((lv["poc"], lv["total"], lv["delta"], lv["pocDelta"]), (D("68000.1"), units("2.85"), units("2.15"), 2 * U))
        # empreinte en flottants : 0,1 + 0,2 n'est pas 0,3 en binaire, mais l'arrondi à 10^-8 redonne la somme exacte
        fp = profile.from_buckets([(13600, 0.1 + 0.2, 0.0)], 5.0, units("0.1"))
        self.assertEqual(fp.buy[13600], units("0.3"))
        with self.assertRaises(ValueError):
            profile.from_buckets([], 0.25, units("0.1"))                    # 0,25 n'est pas un multiple de 0,1
        n = profile.nodes([1, 2, 9, 2, 1, 1, 7, 1, 1], 0, U, span=2, min_pct=30)
        self.assertEqual([k for k, _ in n["hvn"]], [2 * U, 6 * U])


def lv(*rows):
    return [(D(p), D(q)) for p, q in rows]


class BookTest(unittest.TestCase):
    def test_weighted_obi_by_hand(self):
        # milieu 100, bande 1 % (1 $). Bid 99,5 × 10 : distance 0,5 -> poids 0,5 -> 497,5 ; ask 100,5 × 10 : poids 0,5 -> 502,5
        bids, asks = lv(("99.9", "1"), ("99.5", "10")), lv(("100.1", "1"), ("100.5", "10"))
        r = book.obi(bids, asks, "0.01")
        self.assertEqual(r["mid"], D("100"))
        self.assertEqual(r["bid"], D("99.9") * D("0.9") + D("497.5"))
        self.assertEqual(r["ask"], D("100.1") * D("0.9") + D("502.5"))
        self.assertLess(r["obi"], 0)
        # sans poids, un gros ordre loin pèse autant qu'un ordre proche ; avec, il pèse moins
        far = book.obi(lv(("99.9", "1"), ("99.05", "100")), lv(("100.1", "10")), "0.01")
        flat = book.obi(lv(("99.9", "1"), ("99.05", "100")), lv(("100.1", "10")), "0.01", weighted=False)
        self.assertLess(far["obi"], flat["obi"])
        self.assertEqual(book.spread_bps(bids, asks), D("20"))
        self.assertIsNone(book.obi([], asks))

    def test_walls(self):
        bids = lv(*[(str(100 - i * Decimal("0.1")), "1") for i in range(1, 20)])
        asks = lv(*[(str(100 + i * Decimal("0.1")), "1") for i in range(1, 20)])
        bids[9] = (bids[9][0], D("50"))                                      # 99,0 : 50 pièces
        w = book.walls(bids, asks, "0.02", "8")
        self.assertEqual([r[0] for r in w["bid"]], [D("99.0")])
        self.assertEqual(w["ask"], [])
        self.assertEqual(w["bid"][0][3], D("0.01"))                          # à 1 % du prix milieu

    def _book(self, wall_qty, best_bid="99.9"):
        bids = lv((best_bid, "1"), ("99.8", "1"), ("99.7", "1"), ("99.6", wall_qty), ("99.5", "1"), ("99.4", "1"))
        asks = lv(("100.1", "1"), ("100.2", "1"), ("100.3", "1"), ("100.4", "1"), ("100.5", "1"))
        return [b for b in bids if b[1] > 0], asks

    def test_wall_pulled_executed_absorbing(self):
        t = book.WallTracker(band="0.02", k="8", near="0.005")
        self.assertEqual(t.update(0, *self._book("100")), [])
        self.assertEqual(len(t.active()), 1)
        ev = t.update(1000, *self._book("0"))                                # disparu sans transaction, à 0,4 % du prix : retiré
        self.assertEqual([(e["kind"], e["side"], e["price"]) for e in ev], [("retiré", "bid", D("99.6"))])
        t.update(2000, *self._book("100"))
        t.on_trade("99.6", "6000", -1)                                       # 6 000 $ vendus sur le mur de 9 960 $ : plus de la moitié
        ev = t.update(3000, *self._book("0"))
        self.assertEqual(ev[0]["kind"], "exécuté")
        t.update(4000, *self._book("100"))
        t.on_trade("99.6", "12000", -1)                                      # plus que sa taille, et il est toujours là : rechargé
        ev = t.update(5000, *self._book("100"))
        self.assertEqual([e["kind"] for e in ev], ["absorbe"])
        self.assertEqual(len(t.active()), 1)
        t.on_trade("100.1", "500", 1)                                        # un achat agressif ne touche pas un mur de bids
        self.assertEqual(t.active()[0]["traded"], D("12000"))


class RegimeTest(unittest.TestCase):
    def test_the_four_quadrants(self):
        c = regime.classify
        self.assertEqual(c("-0.01", "-0.02", "-0.05", "-0.01")["code"], "cascade_longs")
        self.assertEqual(c("0.01", "-0.02", "0.05", "0.01")["code"], "short_squeeze")
        self.assertEqual(c("-0.01", "0.02", "-0.05", "0.0")["code"], "shorts_agressifs")
        self.assertEqual(c("0.01", "0.02", "0.05", "0.0")["code"], "longs_agressifs")
        self.assertEqual(c("0.001", "0.0", "0.0", "0.06")["code"], "accumulation_spot")
        self.assertEqual(c("-0.001", "0.0", "0.0", "-0.06")["code"], "distribution_spot")
        self.assertEqual(c("0.0005", "0.01", "0.0", "0.0")["code"], "compression")
        self.assertEqual(c("0.0005", "0.0005", "0.0", "0.0")["code"], "neutre")

    def test_missing_inputs_never_invent(self):
        r = regime.classify("0.01")
        self.assertEqual((r["code"], len(r["missing"])), ("neutre", 4))
        # hausse + intérêt ouvert en hausse mais CVD inconnu : on ne peut pas dire « longs agressifs »
        self.assertEqual(regime.classify("0.01", "0.02")["code"], "neutre")

    def test_notes_liquidations_and_funding(self):
        r = regime.classify("-0.01", "-0.02", "-0.05", "0", funding="0.0005", liq_long="9000000", liq_short="1000000")
        self.assertEqual(r["bias"], -1)
        self.assertTrue(any("90 % de longs (confirme)" in n for n in r["notes"]))
        self.assertEqual(r["crowd"], "long")
        self.assertGreater(r["score"], 0)
        # squeeze porté par le comptant : les deux étiquettes sont renvoyées
        r = regime.classify("0.01", "-0.02", "0.0", "0.08")
        self.assertEqual((r["code"], r["tags"]), ("short_squeeze", ["short_squeeze", "accumulation_spot"]))
        self.assertEqual(regime.change("100", "101"), D("0.01"))
        self.assertIsNone(regime.change("0", "5"))
        self.assertEqual(regime.imbalance(3, 1), D("0.5"))


class OptionsTest(unittest.TestCase):
    def test_put_call_parity_and_known_value(self):
        f, k, iv, t = 68000.0, 70000.0, 0.55, 30 / 365
        c, p = options.price("C", f, k, iv, t), options.price("P", f, k, iv, t)
        self.assertAlmostEqual(c - p, f - k, places=8)                       # parité call - put = F - K (taux nul)
        # au prix (F = K) : call = F × (2 N(σ√T / 2) - 1)
        s = 0.5 * math.sqrt(0.25)
        self.assertAlmostEqual(options.price("C", 100.0, 100.0, 0.5, 0.25), 100.0 * (2 * options.norm_cdf(s / 2) - 1), places=12)

    def test_greeks_match_finite_differences(self):
        f, k, iv, t = 68000.0, 66000.0, 0.6, 14 / 365
        for kind in ("C", "P"):
            g = options.greeks(kind, f, k, iv, t)
            h = 1.0
            up, dn, mid = options.price(kind, f + h, k, iv, t), options.price(kind, f - h, k, iv, t), options.price(kind, f, k, iv, t)
            self.assertAlmostEqual(g["delta"], (up - dn) / (2 * h), places=7)
            self.assertAlmostEqual(g["gamma"], (up - 2 * mid + dn) / (h * h), places=7)
            v = (options.price(kind, f, k, iv + 1e-5, t) - options.price(kind, f, k, iv - 1e-5, t)) / 2e-5 / 100
            self.assertAlmostEqual(g["vega"], v, places=5)
        self.assertAlmostEqual(options.greeks("C", f, k, iv, t)["gamma"], options.greeks("P", f, k, iv, t)["gamma"], places=15)

    def test_implied_vol_round_trip(self):
        for kind, k, iv, t in (("C", 80000.0, 0.45, 60 / 365), ("P", 60000.0, 0.9, 3 / 365), ("C", 68000.0, 0.3, 1 / 365),
                               ("P", 40000.0, 1.6, 200 / 365), ("C", 120000.0, 0.7, 300 / 365)):
            prem = options.price(kind, 68000.0, k, iv, t)
            self.assertAlmostEqual(options.implied_vol(kind, 68000.0, k, t, prem), iv, places=8)
        self.assertIsNone(options.implied_vol("C", 68000.0, 60000.0, 0.1, 7999.0))    # sous la valeur intrinsèque
        self.assertIsNone(options.implied_vol("C", 68000.0, 60000.0, 0.1, 68001.0))   # au-dessus de la prime maximale

    def test_max_pain_exact(self):
        # trois strikes ; à 100 : puts 110 paient 10 × 5 = 50, puts 120 : 20 × 1 = 20 -> 70 ; à 110 : calls 100 : 10 × 4 = 40, puts 120 :
        # 10 × 1 = 10 -> 50 ; à 120 : calls 100 : 20 × 4 = 80, calls 110 : 10 × 2 = 20 -> 100
        k, pay = options.max_pain({"100": ("4", "0"), "110": ("2", "5"), "120": ("0", "1")})
        self.assertEqual((k, pay), (D("110"), D("50")))
        self.assertEqual(options.max_pain({}), (None, None))

    def test_smile_and_gex(self):
        now, exp = 0, 30 * 86_400_000
        t = 30 / 365
        rows = []
        for k in range(50000, 90001, 2000):                                   # sourire : les puts loin coûtent plus cher
            iv = 0.5 + 0.000004 * max(0, 68000 - k) + 0.000001 * max(0, k - 68000)
            for kind in ("C", "P"):
                rows.append({"strike": float(k), "kind": kind, "oi": 100.0, "iv": iv, "f": 68000.0, "expiry": exp})
        s = options.smile(rows, now)[0]
        self.assertAlmostEqual(s["atm"], 0.5, places=9)
        self.assertGreater(s["skew25"], 0)
        self.assertAlmostEqual(s["rr25"], -s["skew25"], places=15)
        self.assertTrue(s["strikePut25"] < 68000 < s["strikeCall25"])
        g = options.gex_by_strike(rows, now)
        self.assertAlmostEqual(g["total"], 0.0, places=3)                     # autant de calls que de puts à chaque strike : gamma net nul
        rows2 = [r for r in rows if (r["kind"] == "C") == (r["strike"] >= 68000)]     # calls au-dessus, puts en dessous
        g = options.gex_by_strike(rows2, now)
        self.assertGreaterEqual(g["callWall"], 68000)
        self.assertLess(g["putWall"], 68000)
        self.assertTrue(60000 < g["flip"] < 76000)
        one = options.gex_by_strike([{"strike": 68000.0, "kind": "C", "oi": 1.0, "iv": 0.5, "f": 68000.0, "expiry": exp}], now)
        want = options.greeks("C", 68000.0, 68000.0, 0.5, t)["gamma"] * 68000.0 ** 2 * 0.01
        self.assertAlmostEqual(one["total"], want, places=6)


class MetricsTest(unittest.TestCase):
    def test_drawdown_depth_and_duration(self):
        pts = [(0, 1.0), (1, 1.2), (2, 0.9), (3, 1.0), (5, 1.2), (6, 1.3), (7, 1.17), (9, 1.25)]
        d = metrics.drawdown(pts)
        self.assertAlmostEqual(d["maxDD"], 0.25)                              # de 1,2 à 0,9
        self.assertEqual((d["peakT"], d["troughT"]), (1, 2))
        self.assertEqual(d["longestMs"], 4)                                   # de 1 à 5 ; le dernier (6 -> 9, non retrouvé) dure 3
        self.assertFalse(d["recovered"])
        self.assertAlmostEqual(d["current"], 1 - 1.25 / 1.3)

    def test_sharpe_sortino_by_hand(self):
        r = [0.01, -0.01, 0.02, 0.0]
        m = 0.005
        sd = math.sqrt(((0.005) ** 2 + (0.015) ** 2 + (0.015) ** 2 + (0.005) ** 2) / 3)
        self.assertAlmostEqual(metrics.sharpe(r, 365), m / sd * math.sqrt(365))
        down = math.sqrt((0.01 ** 2) / 4)
        self.assertAlmostEqual(metrics.sortino(r, 365), m / down * math.sqrt(365))
        self.assertIsNone(metrics.sortino([0.01, 0.02]))                      # aucune perte : non défini, pas « infini »
        self.assertIsNone(metrics.sharpe([0.01]))

    def test_trade_stats_and_excursions(self):
        s = metrics.trade_stats([2.0, -1.0, 1.0, -1.0, -1.0, 3.0])
        self.assertEqual((s["n"], s["winRate"], s["expectancy"], s["profitFactor"]), (6, 0.5, 0.5, 2.0))
        self.assertEqual((s["avgWin"], s["avgLoss"], s["payoff"], s["maxLossStreak"], s["maxWinStreak"]), (2.0, -1.0, 2.0, 2, 1))
        e = metrics.excursions([{"r": 2.0, "mae": 0.3, "mfe": 2.5}, {"r": -1.0, "mae": 1.0, "mfe": 0.4}, {"r": 1.0, "mae": 0.5, "mfe": 1.5}])
        self.assertAlmostEqual(e["winners"]["maeMean"], 0.4)
        self.assertAlmostEqual(e["losers"]["mfeMean"], 0.4)
        self.assertAlmostEqual(e["edgeRatio"], (4.4 / 3) / (1.8 / 3))
        self.assertEqual(metrics.quantile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)

    def test_monte_carlo(self):
        rets = [0.02, -0.01] * 50
        a = metrics.monte_carlo(rets, 500, "shuffle", ruin=0.5, seed=1)
        self.assertEqual(a["runs"], 500)
        final = 1.0
        for r in rets:
            final *= 1 + r
        self.assertAlmostEqual(a["final"]["5"], final, places=9)              # permutation : le capital final ne change pas
        self.assertAlmostEqual(a["final"]["95"], final, places=9)
        self.assertGreater(a["dd"]["95"], a["dd"]["5"])                       # mais le drawdown, si
        self.assertEqual(a["ruin"], 0.0)
        self.assertEqual(metrics.monte_carlo(rets, 500, "shuffle", seed=1)["dd"], a["dd"])     # reproductible
        b = metrics.monte_carlo(rets, 500, "bootstrap", seed=1)
        self.assertGreater(b["final"]["95"], b["final"]["5"])                 # avec remise : le capital final varie
        # une stratégie perdante à gros risque finit ruinée presque à coup sûr
        bad = metrics.monte_carlo([-0.1, 0.05] * 40, 300, "bootstrap", ruin=0.5, seed=2)
        self.assertGreater(bad["ruin"], 0.9)
        self.assertLessEqual(bad["ruinLo"], bad["ruin"])
        self.assertEqual(metrics.monte_carlo([0.01], 100)["runs"], 0)

    def test_full_report(self):
        day = 86_400_000
        trades = [{"exit_t": (i + 1) * day, "ret": 0.01 * r, "r": r, "mae": 0.5, "mfe": abs(r) + 0.2}
                  for i, r in enumerate([1.5, -1, 2, -1, -1, 1.5, 2, -1, 1, 1.5, -1, 2])]
        rep = metrics.report(trades, 0, 20 * day, mc_runs=200)
        self.assertEqual(rep["n"], 12)
        self.assertGreater(rep["sharpe"], 0)
        self.assertGreater(rep["sortino"], rep["sharpe"])
        self.assertAlmostEqual(rep["calmar"], rep["cagr"] / rep["maxDD"])
        self.assertAlmostEqual(rep["maxDD"], 1 - 0.99 * 0.99, places=12)      # deux pertes de 1 % de suite
        self.assertEqual(rep["mcShuffle"]["runs"], 200)
        self.assertGreater(rep["ddDays"], 0)


class ExecutionTest(unittest.TestCase):
    SIM = {"fill_px": 68000.0, "risk": 680.0, "r_gross": 2.0, "entry_kind": "taker", "legs": [("maker", 0.5), ("maker", 0.5)],
           "hours": 20.0, "tp1": True, "partial": 0.5, "side": "long", "fill_t": 1 * 3_600_000, "exit_t": 21 * 3_600_000,
           "tp1_t": 10 * 3_600_000, "atr_in": 0.0006, "atr_out": 0.001}

    def test_dynamic_slippage(self):
        c = dict(execution.DEFAULT)
        self.assertAlmostEqual(execution.slippage(c), 0.00005)
        self.assertAlmostEqual(execution.slippage(c, 0.001), 0.00005 + 0.0001)             # marché agité : glissement triplé
        self.assertAlmostEqual(execution.slippage(c, 0.001, notional=1_000_000, depth=5_000_000), 0.00015 + 0.001 * 0.1)
        self.assertEqual(execution.slippage({"slip": 0.0002}), 0.0002)                      # ancien modèle : fixe

    def test_real_funding_has_a_sign(self):
        h = 3_600_000
        fs = execution.FundingSeries([(0, 0.0001), (8 * h, 0.0003), (16 * h, -0.0001), (24 * h, 0.0001)])
        self.assertEqual(fs.between(1 * h, 21 * h), (0.0003 - 0.0001, 2))
        self.assertTrue(fs.covers(1 * h, 21 * h))
        k = 100.0
        c = {**execution.DEFAULT, "funding": fs}
        # long : paie 0,03 % en entier (avant l'objectif 1), puis reçoit 0,01 % sur la moitié restante : 100 × (0,0003 - 0,00005)
        f, origin = execution.funding_r(self.SIM, c, k)
        self.assertAlmostEqual(f, 0.025)
        self.assertEqual(origin, "réel")
        f, _ = execution.funding_r({**self.SIM, "side": "short"}, c, k)
        self.assertAlmostEqual(f, -0.025)                                    # le short REÇOIT ce que le long paie
        f, origin = execution.funding_r(self.SIM, {**execution.DEFAULT, "funding8h": 0.0001}, k)
        self.assertEqual(origin, "constant")
        self.assertAlmostEqual(f, 100 * 0.0001 / 8 * 20 * 0.75)

    def test_net_r_breakdown(self):
        c = {**execution.DEFAULT, "funding8h": 0.0}
        r = execution.net_r(self.SIM, c)
        # frais : entrée au marché 100 × 0,05 % + deux sorties limite 100 × 0,02 % = 0,07 R ; glissement d'entrée 100 × (0,00005 + 0,00006)
        self.assertAlmostEqual(r["fees"], 0.07)
        self.assertAlmostEqual(r["slip"], 0.011)
        self.assertAlmostEqual(r["net"], 2.0 - 0.07 - 0.011)


if __name__ == "__main__":
    unittest.main()
