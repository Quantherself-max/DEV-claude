import math, random, unittest
from datetime import datetime, timezone

from engine import vp, liquidity
from engine.atr import Candle, rma_atr, resample
from engine.confluence import Level, find_zones
from engine.grid import Grid
from engine.periods import PeriodTracker, AnchoredVWAP, period_key

H = 3_600_000


def ts(y, m, d, hh=0):
    return int(datetime(y, m, d, hh, tzinfo=timezone.utc).timestamp() * 1000)


def synth_candles(start, n, seed=1, px=85000.0, step=H):
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        o = px
        c = o * (1 + rnd.gauss(0, 0.004))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.002)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.002)))
        out.append(Candle(start + k * step, o, h, l, c, rnd.uniform(50, 500), rnd.uniform(20, 300)))
        px = c
    return out


class VolumeProfileTests(unittest.TestCase):
    def test_conservation_and_value_area(self):
        for n in (24, 168, 720, 8760):
            cs = synth_candles(ts(2026, 1, 1), n, seed=n)
            p = vp.Profile()
            for k in cs:
                p.add(k.l, k.h, k.v)
            tot = sum(k.v for k in cs)
            self.assertAlmostEqual(sum(p.bins.values()), tot, delta=1e-6 * tot)
            rows, b0, g = vp.agg_rows(p, vp.auto_rows(n))
            self.assertAlmostEqual(sum(rows), tot, delta=1e-6 * tot)
            self.assertLessEqual(len(rows), vp.auto_rows(n))
            poc, vah, val = vp.stats(rows, b0, g)
            self.assertLess(val, poc)
            self.assertLess(poc, vah)
            cov = sum(r for i, r in enumerate(rows) if val - 1e-6 <= vp.VP_GRID.price(b0 + i * g, .5 * g) <= vah + 1e-6) / tot
            self.assertGreaterEqual(cov, 0.70 - 1e-9)

    def test_poc_is_the_heaviest_row_and_hvn_found(self):
        rnd = random.Random(5)
        p = vp.Profile()
        # deux zones d'activite : 84000 (lourde) et 80000 (moyenne), un peu de bruit
        for _ in range(400):
            c = rnd.gauss(84000, 250)
            p.add(c - 60, c + 60, rnd.uniform(80, 120))
        for _ in range(250):
            c = rnd.gauss(80000, 250)
            p.add(c - 60, c + 60, rnd.uniform(80, 120))
        lv = vp.levels(p, 650)
        self.assertAlmostEqual(lv["poc"], 84000, delta=450)
        self.assertEqual(len(lv["hvn"]), 1)
        self.assertAlmostEqual(lv["hvn"][0], 80000, delta=500)
        self.assertGreater(lv["vah"], lv["poc"])
        self.assertLess(lv["val"], lv["poc"])

    def test_hvn_never_in_poc_zone_and_at_most_n(self):
        rnd = random.Random(8)
        for t in range(40):
            p = vp.Profile()
            for _ in range(rnd.randint(50, 400)):
                c = rnd.choice([70000, 80000, 90000]) * (1 + rnd.gauss(0, 0.01))
                p.add(c * 0.999, c * 1.001, rnd.uniform(10, 100))
            lv = vp.levels(p, 300, hvn_n=2)
            self.assertLessEqual(len(lv["hvn"]), 2)
            for h in lv["hvn"]:
                self.assertGreater(abs(math.log(h / lv["poc"])) * 100, 0.5)


class PeriodTests(unittest.TestCase):
    def test_week_is_monday_based(self):
        mon = ts(2026, 9, 28)   # lundi
        sun = ts(2026, 9, 27)
        self.assertEqual(period_key("W", mon), period_key("W", mon + 6 * 86400000 + 23 * H))
        self.assertNotEqual(period_key("W", sun + 23 * H), period_key("W", mon))
        self.assertEqual(datetime.fromtimestamp(mon / 1000, timezone.utc).weekday(), 0)

    def test_vwap_matches_direct_formula_and_forming_candle(self):
        cs = synth_candles(ts(2026, 10, 1), 30)          # 1.25 jour
        tr = PeriodTracker("D")
        for k in cs[:-1]:
            tr.feed(k)
        snap = tr.snapshot(forming=cs[-1])                # la derniere bougie est en cours
        day = [k for k in cs if period_key("D", k.t) == period_key("D", cs[-1].t)]
        tp = [(k.h + k.l + k.c) / 3 for k in day]
        v = [k.v for k in day]
        vw = sum(a * b for a, b in zip(tp, v)) / sum(v)
        sd = math.sqrt(sum(b * (a - vw) ** 2 for a, b in zip(tp, v)) / sum(v))
        self.assertAlmostEqual(snap["vwap"], vw, places=6)
        self.assertAlmostEqual(snap["sd"], sd, places=6)
        self.assertEqual(snap["open"], day[0].o)
        self.assertEqual(snap["high"], max(k.h for k in day))
        self.assertEqual(snap["low"], min(k.l for k in day))

    def test_rollover_keeps_previous_period(self):
        cs = synth_candles(ts(2026, 10, 1), 24 * 3 + 5)
        tr = PeriodTracker("D")
        for k in cs:
            tr.feed(k)
        prev_day = [k for k in cs if period_key("D", k.t) == period_key("D", cs[-1].t) - 1]
        self.assertEqual(tr.prev["high"], max(k.h for k in prev_day))
        self.assertEqual(tr.prev["low"], min(k.l for k in prev_day))
        self.assertEqual(tr.prev["open"], prev_day[0].o)
        self.assertIsNotNone(tr.prev["vp"])
        # une bougie en cours qui ouvre un nouveau jour : la periode "courante" repart de zero
        nxt = Candle(cs[-1].t + H * 24, 1, 2, 0.5, 1.5, 10, 5)
        snap = tr.snapshot(forming=nxt)
        self.assertEqual(snap["n"], 1)
        self.assertEqual(snap["open"], 1)
        self.assertIsNone(snap["vp"])
        self.assertIsNotNone(snap["prev"]["vp"])

    def test_anchored_vwap_starts_at_anchor(self):
        cs = synth_candles(ts(2026, 10, 1), 48)
        a = AnchoredVWAP(cs[10].t)
        for k in cs:
            a.feed(k)
        sub = cs[10:]
        tp = [(k.h + k.l + k.c) / 3 for k in sub]
        vw = sum(x * k.v for x, k in zip(tp, sub)) / sum(k.v for k in sub)
        self.assertAlmostEqual(a.snapshot()["vwap"], vw, places=6)


class AtrTests(unittest.TestCase):
    def test_resample_and_atr(self):
        cs = synth_candles(ts(2026, 10, 1), 48)
        r = resample(cs, 4 * H)
        self.assertEqual(len(r), 12)
        self.assertEqual(r[0].o, cs[0].o)
        self.assertEqual(r[0].h, max(k.h for k in cs[:4]))
        self.assertAlmostEqual(sum(k.v for k in r), sum(k.v for k in cs))
        self.assertGreater(rma_atr(r), 0)


# ---------- moteur de liquidation : equivalence avec une version naive ----------
class NaiveLiq:
    G = liquidity.LIQ_GRID

    def __init__(self, levs=(100, 50, 25, 10), wts=(10, 20, 30, 40), mmr=0.004):
        self.levs, self.wts, self.mmr = levs, wts, mmr
        self.L, self.S, self.oi_last = {}, {}, None

    def step(self, oi_now, h, l, c):
        hits = 0
        for i in sorted(self.L):
            if self.G.price(i) >= l:
                del self.L[i]; hits += 1
        for i in sorted(self.S):
            if self.G.price(i) <= h:
                del self.S[i]; hits += 1
        last = self.oi_last
        d = 0.0 if (oi_now is None or last is None) else oi_now - last
        if oi_now is not None:
            self.oi_last = oi_now
        if hits == 0 and d < 0 and last and last > 0:
            f = oi_now / last
            for book in (self.L, self.S):
                for i in book:
                    book[i] *= f
        amt = max(d, 0.0)
        if amt > 0:
            px = (h + l + c) / 3
            rng = h - l
            clv = ((c - l) - (h - c)) / rng if rng > 0 else 0.0
            lsh = max(0.2, min(0.8, 0.5 + 0.5 * clv))
            for lev, w in zip(self.levs, self.wts):
                wq = w / sum(self.wts)
                pl, ps = px * (1 - 1 / lev + self.mmr), px * (1 + 1 / lev - self.mmr)
                if pl < l:
                    i = self.G.idx(pl); self.L[i] = self.L.get(i, 0.0) + amt * lsh * wq
                if ps > h:
                    i = self.G.idx(ps); self.S[i] = self.S.get(i, 0.0) + amt * (1 - lsh) * wq


def liq_steps(n, seed, crash=False):
    r = random.Random(seed)
    px, oi, out = 85000.0, 80000.0, []
    for t in range(n):
        o = px
        c = o * (1 + r.gauss(0, 0.0011))
        h = max(o, c) * (1 + abs(r.gauss(0, 0.0004)))
        l = min(o, c) * (1 - abs(r.gauss(0, 0.0004)))
        oi = max(1000.0, oi + r.gauss(8, 60) - (oi * 0.02 if crash and t % 7 == 0 else 0))
        out.append((oi, h, l, c))
        px = c
    return out


class LiquidityTests(unittest.TestCase):
    def test_liquidation_price_formula(self):
        e = liquidity.LiqEngine()
        e.step(1000.0, 86100, 85900, 86000)                 # amorce l'OI
        e.step(1100.0, 86100, 85990, 86000)                 # +100 d'OI
        prices_l = sorted(liquidity.LIQ_GRID.price(i) for i in e.lact)
        px = (86100 + 85990 + 86000) / 3
        self.assertTrue(any(abs(p / (px * (1 - 0.01 + 0.004)) - 1) < 0.0006 for p in prices_l))   # long 100x
        self.assertTrue(any(abs(p / (px * (1 - 0.1 + 0.004)) - 1) < 0.0006 for p in prices_l))    # long 10x

    def test_equivalent_to_naive_reference(self):
        for seed, crash in ((1, False), (2, True), (3, False)):
            fast, ref = liquidity.LiqEngine(), NaiveLiq()
            for oi, h, l, c in liq_steps(6000, seed, crash):
                fast.step(oi, h, l, c)
                ref.step(oi, h, l, c)
            a = {("L", i): fast.lsz[i] * fast.g for i in fast.lact} | {("S", i): fast.ssz[i] * fast.g for i in fast.sact}
            b = {("L", i): v for i, v in ref.L.items()} | {("S", i): v for i, v in ref.S.items()}
            self.assertEqual(a.keys(), b.keys())
            for k in a:
                self.assertAlmostEqual(a[k], b[k], delta=1e-9 * max(1, abs(b[k])))
            self.assertEqual(fast.lact, sorted(set(fast.lact)))
            self.assertEqual(fast.sact, sorted(set(fast.sact)))

    def test_pool_selection_rules(self):
        e = liquidity.LiqEngine()
        close = 85000.0
        for oi, h, l, c in liq_steps(8000, 11):
            e.step(oi, h, l, c)
            close = c
        out = e.pools(close, win_abs=0.08 * close)
        self.assertGreater(out["total"], len(out["pools"]))
        pools = out["pools"]
        mx = max(p["size"] for p in pools)
        for p in pools:
            self.assertGreaterEqual(p["rel"], 0.35 - 1e-9)
            self.assertLessEqual(abs(p["price"] - close), 0.08 * close + 1e-6)
            self.assertLessEqual(p["lo"], p["price"])
            self.assertLessEqual(p["price"], p["hi"])
        for side in ("long", "short"):
            side_pools = [p for p in pools if p["side"] == side]
            self.assertLessEqual(len(side_pools), 3)
            self.assertLessEqual(sum(p["magnet"] for p in side_pools), 1)
        self.assertTrue(all((p["side"] == "long") == (p["price"] < close) for p in pools))
        self.assertEqual(max(p["score"] for p in pools), 100 if abs(mx - max(p["size"] for p in pools)) < 1e-12 else max(p["score"] for p in pools))


# ---------- confluences : fuzz contre une reference independante ----------
def zones_ref(levels, tol):
    a = sorted(levels, key=lambda x: x.price)
    out, i = [], 0
    while i < len(a):
        j = max(k for k in range(i, len(a)) if a[k].price <= a[i].price + tol)
        if j > i and len({x.group for x in a[i:j + 1]}) >= 2:
            out.append((round(sum(x.price for x in a[i:j + 1]) / (j - i + 1), 6), j - i + 1))
        i = j + 1
    return out


class ConfluenceTests(unittest.TestCase):
    def test_same_group_alone_is_not_a_confluence(self):
        lv = [Level("1", "pmPOC", 86000, "pmVP", "vp"), Level("2", "pmVAH", 86050, "pmVP", "vp")]
        self.assertEqual(find_zones(lv, 250), [])

    def test_basic_zone(self):
        lv = [Level("a", "wPOC", 84300, "wVP", "vp"), Level("b", "yVWAP", 84410, "yVWAP", "vwap"),
              Level("c", "wOpen", 84500, "wOpen", "open"), Level("d", "dVWAP", 80000, "dVWAP", "vwap")]
        z = find_zones(lv, 250)
        self.assertEqual(len(z), 1)
        self.assertEqual(len(z[0]["members"]), 3)
        self.assertLessEqual(z[0]["hi"] - z[0]["lo"], 250)

    def test_fuzz(self):
        rnd = random.Random(3)
        for t in range(2000):
            n = rnd.randint(0, 24)
            tol = rnd.uniform(20, 600)
            lv = [Level(str(k), f"L{k}", rnd.uniform(70000, 95000), f"g{rnd.randint(1, 14)}", "vp") for k in range(n)]
            got = [(round(z["mid"], 6), len(z["members"])) for z in find_zones(lv, tol)]
            self.assertEqual(got, zones_ref(lv, tol))
            for z in find_zones(lv, tol):
                self.assertLessEqual(z["hi"] - z["lo"], tol + 1e-9)


class LiquiditySnapshotTests(unittest.TestCase):
    H = 3_600_000

    def run_steps(self, e, n, t0, oi0, px=100.0, d_oi=10.0, hi=None, lo=None):
        oi = oi0
        for i in range(n):
            oi += d_oi
            tend = t0 + (i + 1) * 300_000
            e.step(oi, hi or px + 0.1, lo or px - 0.1, px, vol=100.0, tb=50.0, t=tend)
        return oi

    def test_hourly_snapshots_and_birth_of_pool(self):
        from engine.liquidity import LiqEngine
        e = LiqEngine()
        t0 = 10 * self.H                                   # heure ronde
        oi = self.run_steps(e, 36, t0, 1000.0)              # 3 h de nouvelles positions autour de 100
        self.assertEqual([x[0] for x in e.snaps], [t0, t0 + self.H, t0 + 2 * self.H])
        pools = e.pools(100.0, 20.0, keep_pct=10)["pools"]
        self.assertTrue(pools)
        p = max(pools, key=lambda q: q["size"])
        born = p["born"]
        self.assertIsNotNone(born)
        self.assertLessEqual(born, t0 + self.H)             # la poche existe depuis le debut (>= 25 % de sa taille finale)
        # un balayage remet l'age a zero : le prix monte jusqu'aux shorts, ils disparaissent, l'age des shorts repart
        top = max((q for q in pools if q["side"] == "short"), key=lambda q: q["price"])
        e.step(oi, top["hi"] + 5, 99.9, 100.0, vol=100.0, tb=50.0, t=t0 + 37 * 300_000)
        sh = [q for q in e.pools(100.0, 20.0, keep_pct=10)["pools"] if q["side"] == "short" and q["price"] == top["price"]]
        self.assertEqual(sh, [])                             # la poche balayee n'existe plus

    def test_heat_matrix_columns_and_live_column(self):
        from engine.liquidity import LiqEngine, band_of
        e = LiqEngine()
        t0 = 20 * self.H
        self.run_steps(e, 24, t0, 1000.0)
        h = e.heat(90.0, 110.0, t0, t0 + 2 * self.H + 600_000)
        self.assertIsNotNone(h)
        self.assertEqual(h["n"], 3)                          # 2 photos + la colonne de l'heure en cours (etat actuel)
        self.assertEqual(h["cols"][-1][0], t0 + 2 * self.H)
        self.assertTrue(h["cols"][-1][1] and h["cols"][-1][2])
        self.assertEqual(h["b0"], band_of(90.0))
        self.assertIsNone(LiqEngine().heat(90, 110, 0, 1))


if __name__ == "__main__":
    unittest.main()
