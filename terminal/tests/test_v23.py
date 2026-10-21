"""V23 : transactions exactes. Empreinte (volume acheteur / vendeur a chaque prix par 5 minutes), synchronisation archives + API + direct
recollee par numero de transaction (jamais de trou ni de double compte), branchement sur les profils, VWAP exact."""
from __future__ import annotations
import io
import math
import random
import tempfile
import unittest
import zipfile

from data import trades as tr
from engine import footprint as fpm
from engine import vp

DAY = 86_400_000
D0 = 1_791_590_400_000 - 1_791_590_400_000 % DAY          # un minuit UTC


def make_trades(t0, t1, every_ms=10_000, seed=1, first_id=1000, p0=100.0, tick=0.01):
    """Transactions fictives : une toutes les ~every_ms, prix en marche au hasard sur le pas de cotation, numeros consecutifs."""
    rnd = random.Random(seed)
    out, t, a, p = [], t0, first_id, p0
    while t < t1:
        p = max(tick, round(p + tick * rnd.choice((-2, -1, 0, 1, 2)), 2))
        out.append((a, p, round(rnd.uniform(0.1, 5), 3), rnd.random() < 0.5, t))
        a += 1
        t += rnd.randint(1, 2 * every_ms)
    return out


def zip_day(rows, header=True):
    buf = io.StringIO()
    if header:
        buf.write("agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n")
    for a, p, q, m, t in rows:
        buf.write(f"{a},{p:.2f},{q},{a},{a},{t},{'true' if m else 'false'}\n")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("X-aggTrades.csv", buf.getvalue())
    return out.getvalue()


class Market:
    """Fausse bourse : archives quotidiennes et API aggTrades sur une liste de transactions connue, horloge reglable."""

    def __init__(self, trades, now, published):
        self.trades, self.now, self.published = trades, now, set(published)
        self.calls = 0

    def fetch(self, url):
        day = url.rsplit("-aggTrades-", 1)[1][:10]
        d = next((x for x in self.published if tr.ymd(x) == day), None)
        if d is None:
            return None
        return zip_day([x for x in self.trades if d <= x[4] < d + DAY])

    def get(self, path, params):
        self.calls += 1
        assert path == "/fapi/v1/aggTrades"
        if "fromId" in params:
            sel = [x for x in self.trades if x[0] >= params["fromId"] and x[4] <= self.now][:params["limit"]]
        else:
            sel = [x for x in self.trades if params["startTime"] <= x[4] <= params["endTime"]][:params["limit"]]
        return [{"a": a, "p": f"{p:.2f}", "q": str(q), "f": a, "l": a, "T": t, "m": m} for a, p, q, m, t in sel]


def brute_rows(trades, t0, t1, k0, n, rstep):
    vol = [0.0] * n
    for _, p, q, _, t in trades:
        if t0 <= t < t1:
            j = min(n - 1, max(0, math.floor(p / rstep + 1e-9) - k0))
            vol[j] += q
    return vol


def run_until(ts, cond, limit=20000):
    for _ in range(limit):
        ts.step()
        if cond():
            return True
    return False


class FootprintEngineTests(unittest.TestCase):
    def test_rows_profile_moments_and_blob(self):
        trades = make_trades(D0, D0 + 6 * 3_600_000, every_ms=2000)
        fp = fpm.Footprint(0.01, 0.01)
        for _, p, q, m, t in trades:
            fp.add(p, q, m, t)
        self.assertTrue(fp.exact)
        fp.seal(D0 + 3 * 3_600_000)                                    # moitie fermee, moitie ouverte : meme resultat
        k0 = math.floor(min(x[1] for x in trades) / 0.05) - 1
        n = math.floor(max(x[1] for x in trades) / 0.05) - k0 + 2
        vol, buy = [0.0] * n, [0.0] * n
        tot = fp.add_rows(D0, D0 + DAY, k0, n, 0.05, vol, buy)
        ref = brute_rows(trades, D0, D0 + DAY, k0, n, 0.05)
        self.assertAlmostEqual(tot, sum(x[2] for x in trades), places=6)
        self.assertTrue(all(abs(a - b) < 1e-9 for a, b in zip(vol, ref)))      # au prix pres : exact
        self.assertAlmostEqual(sum(buy), sum(x[2] for x in trades if not x[3]), places=6)
        v, pv, p2v = fp.moments(D0, D0 + DAY)
        self.assertAlmostEqual(pv / v, sum(x[1] * x[2] for x in trades) / sum(x[2] for x in trades), places=9)
        prof = vp.Profile()
        fp.add_profile(D0, D0 + DAY, prof)
        self.assertAlmostEqual(sum(prof.bins.values()), tot, places=6)
        fp.cover(D0, D0 + 3_600_000)
        fp.cover(D0 + 3_600_000, D0 + 7_200_000)                      # intervalles contigus fusionnes
        self.assertEqual(fp.cov, [[D0, D0 + 7_200_000]])
        self.assertTrue(fp.complete(D0 + 300_000, D0 + 600_000))
        self.assertFalse(fp.complete(D0 + 7_000_000, D0 + 7_500_000))
        fp.uncover(D0 + 600_000, D0 + 900_000)
        self.assertFalse(fp.complete(D0 + 600_000, D0 + 900_000))
        fp2 = fpm.Footprint(0.01, 0.01)
        head = fp2.load_blob(fp.day_blob(D0, {"lastId": 7}))
        self.assertEqual(head["lastId"], 7)
        v2, pv2, _ = fp2.moments(D0, D0 + DAY)
        self.assertAlmostEqual(v2, v, places=5)
        self.assertEqual(fp2.cov, fp.cov)

    def test_coarse_step_for_btc(self):
        self.assertEqual(fpm.storage_step(82_000.0, 0.1), 5.0)
        self.assertEqual(fpm.storage_step(110.0, 0.01), 0.01)
        self.assertEqual(fpm.tick_of("81711.0"), 0.1)
        fp = fpm.Footprint(5.0, 0.1)
        self.assertFalse(fp.exact)
        fp.add(81_712.3, 2.0, False, D0)
        fp.add(81_718.9, 1.0, True, D0)
        vol, buy = [0.0] * 4, [0.0] * 4                               # lignes de 10 $ depuis 81 700
        fp.add_rows(D0, D0 + 300_000, 8170, 4, 10.0, vol, buy)
        self.assertEqual(vol, [0.0, 3.0, 0.0, 0.0])                   # 81 710 - 81 720 : les deux, sans approximation
        vol, buy = [0.0] * 8, [0.0] * 8                               # lignes de 2,5 $ : un pas de 5 $ est partage au prorata
        fp.add_rows(D0, D0 + 300_000, 32682, 8, 2.5, vol, buy)
        self.assertAlmostEqual(sum(vol), 3.0)


class TradeSyncTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.trades = make_trades(D0 - 3 * DAY, D0 + DAY)
        self.now = D0 + 6 * 3_600_000
        self.mk = Market(self.trades, self.now, published=(D0 - DAY, D0 - 2 * DAY))

    def sync(self):
        return tr.TradeSync("TESTUSDT", self.dir, 3, self.mk.get, self.mk.fetch, now_ms=lambda: self.mk.now, rest_pause=0.0)

    def check_exact(self, ts, t0, t1):
        fp = ts.fp
        self.assertTrue(fp.complete(t0, t1))
        k0, n = 900, 300                                              # lignes de 0,1 $ de 90 a 120
        vol, buy = [0.0] * n, [0.0] * n
        fp.add_rows(t0, t1, k0, n, 0.1, vol, buy)
        ref = brute_rows(self.trades, t0, t1, k0, n, 0.1)
        self.assertLess(max(abs(a - b) for a, b in zip(vol, ref)), 1e-6)

    def test_archives_then_api_then_live_without_gap_or_double(self):
        ts = self.sync()
        ok = run_until(ts, lambda: ts.head_t is not None and ts.head_t >= self.now - 20_000 and not ts.catching_up and D0 - 2 * DAY in ts.done)
        self.assertTrue(ok)
        self.assertIn(D0 - DAY, ts.done)
        self.check_exact(ts, D0 - 2 * DAY, D0 + 5 * 3_600_000)        # archives + rattrapage par l'API : exact au prix pres
        self.assertEqual(ts.fp.step, 0.01)
        live = [x for x in self.trades if self.now < x[4] <= self.now + 3_600_000]
        self.mk.now += 3_600_000
        skip = set(x[0] for x in live[100:140])                      # coupure du flux : 40 transactions jamais recues en direct
        for a, p, q, m, t in live:
            if a not in skip:
                ts.on_live({"a": a, "p": str(p), "q": str(q), "m": m, "T": t})
        run_until(ts, lambda: not ts.q, 5000)
        self.assertEqual(ts.head_id, live[-1][0])
        self.check_exact(ts, D0 - 2 * DAY, D0 + 6 * 3_600_000 + 3_000_000)   # le trou a ete rattrape par l'API
        ts.flush()
        ts2 = self.sync()                                             # redemarrage : rien n'est compte deux fois
        ts2.load()
        self.assertEqual(ts2.head_id, ts.head_id)
        self.mk.now += 1_800_000
        run_until(ts2, lambda: ts2.head_t >= self.mk.now - 20_000 and not ts2.catching_up, 5000)
        self.check_exact(ts2, D0 - 2 * DAY, ts2.head_t - ts2.head_t % 300_000)
        st = ts2.status()
        self.assertEqual(st["complete"], 2)                          # le 3e jour n'est pas publie
        self.assertGreater(st["today"], 0.99)

    def test_yesterday_not_published_yet(self):
        self.mk.published = {D0 - 2 * DAY}                           # l'archive d'hier n'est pas encore publiee
        ts = self.sync()
        run_until(ts, lambda: ts.head_t is not None and ts.head_t >= self.now - 20_000 and not ts.catching_up)
        self.check_exact(ts, D0 - 2 * DAY, D0 + 5 * 3_600_000)        # hier : par l'API, a partir de la fin d'avant-hier
        ts.step()
        self.assertIn(D0 - DAY, ts.done)                             # hier est complet sans archive

    def test_no_archive_at_all_starts_from_api(self):
        self.mk.published = set()
        ts = self.sync()
        run_until(ts, lambda: ts.head_t is not None and ts.head_t >= self.now - 20_000 and not ts.catching_up)
        self.check_exact(ts, D0 - DAY, D0 + 5 * 3_600_000)
        self.assertFalse(ts.fp.complete(D0 - 2 * DAY, D0 - DAY))


if __name__ == "__main__":
    unittest.main()


class ExactVwapTests(unittest.TestCase):
    def test_dollar_volume_gives_the_exact_vwap(self):
        from engine.atr import Candle, avg_price, resample
        from engine.periods import AnchoredVWAP, PeriodTracker
        from engine import vwapx
        k1 = Candle(D0, 100.0, 110.0, 90.0, 100.0, 10.0, 5.0, 10.0 * 92.0)    # prix typique 100, prix moyen REEL 92
        k2 = Candle(D0 + 3_600_000, 100.0, 104.0, 96.0, 100.0, 30.0, 15.0, 30.0 * 103.0)
        self.assertEqual(avg_price(k1), 92.0)
        self.assertEqual(avg_price(Candle(D0, 1, 3, 1, 2, 5, 2)), 2.0)        # sans volume en dollars : prix typique
        tr = PeriodTracker("D")
        for k in (k1, k2):
            tr.feed(k)
        vw, _ = tr.acc.vwap()
        self.assertAlmostEqual(vw, (920 + 3090) / 40.0)                       # somme des dollars / somme des quantites
        av = AnchoredVWAP(D0)
        av.feed(k1)
        self.assertAlmostEqual(av.snapshot(k2)["vwap"], (920 + 3090) / 40.0)
        self.assertEqual(resample([k1, k2], DAY)[0].q, 920 + 3090)
        fine = [Candle(D0 + 3_600_000 + i * 300_000, 100, 101, 99, 100, 1.0, 0.5, 100.0 + i) for i in range(12)]
        res = vwapx.series([k1] + fine, [D0 + 3_600_000 + i * 300_000 for i in range(12)], 300_000, [], kinds=("D",),
                           fine_from=D0 + 3_600_000, fine_ms=300_000)
        v = res["vwap"]["D"]
        self.assertIsNone(v[0])                                               # premiere bougie de la periode : ligne coupee (comme avant)
        self.assertAlmostEqual(v[1], (920 + 100.0 + 101.0) / 12.0)            # puis a jour a chaque bougie 5 min
        self.assertAlmostEqual(v[5], (920 + sum(100.0 + i for i in range(6))) / 16.0)


class ServiceFootprintTests(unittest.TestCase):
    """Empreinte connue attachee a un marche simule : chaque calcul du terminal doit suivre les transactions, pas les bougies."""

    def test_profiles_tpo_zones_and_vwap_follow_the_trades(self):
        import types
        from config import Config
        from server import App
        from data.store import M5
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None)
        app.service.refresh_all()
        m = app.service.markets["BTCUSDT"]
        now = app.source.now_ms()
        bars = [k for k in m.store.fine_m5() if k.v > 0]
        price = bars[-1].c
        fp = fpm.Footprint(fpm.storage_step(price, 0.1), 0.1)
        for k in bars:                                                   # transactions fictives : tout le volume a la cloture de la bougie
            fp.add(k.c, k.tb, False, k.t + 1)
            fp.add(k.c, k.v - k.tb, True, k.t + 2)
        fp.cover(bars[0].t, now)
        m.trades = types.SimpleNamespace(fp=fp)
        res = m.session_profile("D")
        self.assertEqual(res["exact"], 1.0)
        step, rows = res["step"], res["rows"]
        k0 = math.floor(rows[0][0] / step + 1e-9)
        ref = [0.0] * len(rows)
        for k in bars:
            if k.t >= res["start"]:
                ref[min(len(ref) - 1, max(0, math.floor(k.c / step + 1e-9) - k0))] += k.v
        self.assertLess(max(abs(r[1] - x) for r, x in zip(rows, ref)), 1e-6 * max(ref))   # au prix pres : le volume est ou il s'est echange
        vw, sd, exact = m.vwap_exact(res["start"])
        sub = [k for k in bars if k.t >= res["start"]]
        V = sum(k.v for k in sub)
        mu = sum(fp.price_of(fp.idx(k.c)) * k.v for k in sub) / V
        sd_ref = math.sqrt(max(sum(fp.price_of(fp.idx(k.c)) ** 2 * k.v for k in sub) / V - mu * mu, 0.0))
        self.assertTrue(exact)
        self.assertAlmostEqual(sd, sd_ref, delta=sd_ref * 1e-6 + 1e-9)
        t = m.tpo("D", n=3)
        cur = t["sessions"][-1]
        self.assertEqual(cur["exact"], 1.0)
        wins = m.vp_profiles("5m")
        self.assertTrue(wins)
        for w in wins:
            if w["start"] >= bars[0].t:
                self.assertGreater(w["exact"], 0.99, w["label"])             # profils choisis : au prix pres sur toute leur fenetre
        zf = m._fine_profile(price)
        self.assertGreater(zf.exact, 0.99)
        st = m.state("5m")
        self.assertTrue(st["levels"] if "levels" in st else True)
        naked = m.naked_list("D")
        self.assertTrue(all("poc" in x for x in naked))


class IncrementalSessionTests(unittest.TestCase):
    def test_incremental_profile_equals_full_rebuild(self):
        from engine import sessionvp
        from engine.atr import Candle
        rnd = random.Random(3)
        bars, p = [], 100.0
        for i in range(400):
            o = p
            p = max(1.0, p + rnd.gauss(0, 0.3))
            v = rnd.uniform(1, 9)
            bars.append(Candle(D0 + i * 300_000, o, max(o, p) + 0.1, min(o, p) - 0.1, p, v, v * rnd.random()))
        memo = {}
        sessionvp.build(bars[:300], memo=memo, memo_sig="x")
        for m in (301, 301, 330, 400):                                 # meme bougie en cours, puis nouvelles bougies
            inc = sessionvp.build(bars[:m], memo=memo, memo_sig="x")
            full = sessionvp.build(bars[:m])
            self.assertEqual(inc["rows"], full["rows"])
            self.assertEqual(inc["developing"], full["developing"])
        other = sessionvp.build(bars[:400], memo=memo, memo_sig="y")  # couverture des transactions changee : tout est refait
        self.assertEqual(other["rows"], full["rows"])
