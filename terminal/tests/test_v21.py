"""V21 : absorptions. Sur les bougies (delta fort contre le sens de la bougie, vrai delta), mesure appariee, rapport ; en direct au prix
pres (ruban) ; service, Lecture, outil."""
import json
import random
import tempfile
import unittest
from pathlib import Path

from data.orderflow import AbsorbWatch
from engine import absorption as ab
from engine import fine
from engine.atr import Candle

H = 3_600_000


def flow_bars(n=300, seed=2):
    """Bougies ordinaires : le delta suit le prix."""
    rnd = random.Random(seed)
    out, p = [], 100.0
    for i in range(n):
        o = p
        r = rnd.gauss(0, 0.004)
        p = o * (1 + r)
        v = 100 * (1 + abs(rnd.gauss(0, 0.4)))
        share = min(0.9, max(0.1, 0.5 + 0.1 * r / 0.004 + rnd.gauss(0, 0.03)))
        out.append(Candle(i * H, o, max(o, p) * 1.001, min(o, p) * 0.999, p, v, v * share))
    return out


def synth(N, seed, effect=0.0):
    rnd = random.Random(seed)
    out, p, drift = [], 100.0, 0.0
    for i in range(N):
        o = p
        r = rnd.gauss(drift, 0.004)
        drift *= 0.7
        p = o * (1 + r)
        v = 100 * (1 + abs(rnd.gauss(0, 0.6)))
        share = 0.5 + 0.1 * (r / 0.004) + rnd.gauss(0, 0.06)
        if rnd.random() < 0.01:                                  # absorption : flux contre le prix
            share = 0.5 - 0.35 * (1 if r > 0 else -1)
            if effect:
                drift = effect * (1 if r > 0 else -1)
        share = min(0.95, max(0.05, share))
        out.append(Candle(i * H, o, max(o, p) * 1.001, min(o, p) * 0.999, p, v, v * share))
    return out


class CandleAbsorptionTests(unittest.TestCase):
    def test_detects_only_delta_against_the_candle(self):
        cs = flow_bars()
        self.assertEqual(ab.detect(cs), [])                                     # flux ordinaire : rien
        low = min(k.l for k in cs[-12:])
        o = cs[-1].c
        cs.append(Candle(len(cs) * H, o, o * 1.004, low * 0.99, o * 1.002, 400.0, 30.0))      # gros vendeurs, bougie verte, nouveau plus bas
        o2 = cs[-1].c
        cs.append(Candle(len(cs) * H, o2, o2 * 1.002, o2 * 0.996, o2 * 0.998, 400.0, 370.0))  # gros acheteurs, bougie rouge
        ev = ab.detect(cs)
        self.assertEqual([e["side"] for e in ev], ["bull", "bear"])
        b = ev[0]
        self.assertTrue(b["z"] <= -2 and b["delta"] < 0 and b["extreme"] and b["price"] == cs[-2].l)
        self.assertEqual(b["grade"], 3)                                          # forte et au plus bas
        self.assertEqual(ev[1]["price"], cs[-1].h)
        self.assertEqual(len(ab.detect(cs, last=1)), 1)
        self.assertTrue(ab.has_real_delta(cs))
        self.assertFalse(ab.has_real_delta([Candle(k.t, k.o, k.h, k.l, k.c, k.v, 0.0) for k in cs]))

    def test_study_finds_planted_effect_and_not_noise(self):
        st = ab.study(synth(30000, 4, 0.003))
        self.assertTrue(st["ready"])
        self.assertEqual((st["bull"]["verdict"]["up"], st["bear"]["verdict"]["up"]), ("net", "net"))
        self.assertGreater(st["bull"]["h"]["4"]["up"]["rate"], st["bull"]["h"]["4"]["up"]["control"])
        st0 = ab.study(synth(30000, 4, 0.0))
        self.assertNotEqual(st0["bull"]["verdict"]["up"], "net")
        self.assertEqual(set(st0["bull"]["h"]), {str(h) for h in st0["horizons"]})
        rep = ab.report("TEST", {"1h": st, "4h": {"ready": False}}, "essai", "terminal", 1, 0.1)
        self.assertEqual((rep["kind"], rep["origin"], rep["version"]), ("absorption", "terminal", ab.VERSION))
        self.assertTrue(rep["summary"] and all(x["tf"] == "1h" for x in rep["summary"]))
        self.assertIn("Absorption acheteuse", rep["summary"][0]["text"] + rep["summary"][1]["text"])
        c = ab.compact(st)
        self.assertEqual((c["unit"], c["primary"]), ("1 heure", 4))
        json.dumps(rep)
        self.assertEqual(ab.study(synth(200, 1))["ready"], False)


class LiveAbsorptionTests(unittest.TestCase):
    def test_burst_absorbed_then_confirmed_or_broken(self):
        w = AbsorbWatch("SOLUSDT")
        w.floor = 1000.0
        t, r = 0.0, random.Random(1)
        for _ in range(4000):                                                   # bruit : construit le seuil
            t += 0.25
            w.on_trade(t, 100 + r.gauss(0, 0.05), r.uniform(0.1, 2), "buy" if r.random() < .5 else "sell")
        self.assertIsNotNone(w.thr)
        n0 = len(w.events)
        for _ in range(200):                                                    # vendeurs agressifs a 100,00 : le prix tient
            t += 0.1
            w.on_trade(t, 100.0, 20.0, "sell")
            w.on_trade(t, 100.01, 0.2, "buy")
        new = [e for e in list(w.events)[n0:] if e["side"] == "bull"]
        self.assertEqual(len(new), 1)                                           # une seule absorption pour l'episode
        e = new[0]
        self.assertEqual((e["price"], e["status"]), (100.0, "en cours"))
        self.assertLess(e["delta"], 0)
        for _ in range(40):                                                     # le prix s'eloigne vers le haut
            t += 0.5
            w.on_trade(t, 100.2, 0.5, "buy")
        self.assertEqual(e["status"], "confirmée")
        n1 = len(w.events)
        for _ in range(200):                                                    # acheteurs agressifs a 100,30, puis le prix passe au travers
            t += 0.1
            w.on_trade(t, 100.3, 20.0, "buy")
        bear = [x for x in list(w.events)[n1:] if x["side"] == "bear"]
        self.assertEqual(len(bear), 1)
        w.on_trade(t + 1, 100.36, 1.0, "buy")
        self.assertEqual(bear[0]["status"], "cassée")
        self.assertTrue(all("usd" in x and "refill" in x for x in w.recent()))


class ServiceV21Tests(unittest.TestCase):
    def test_state_lecture_flow_and_report_kind(self):
        from config import Config
        from data import reports as reports_mod
        from server import App
        cfg = Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0)
        app = App(cfg, env_path=None)
        app.service.refresh_all()
        svc = app.service
        m = svc.markets["BTCUSDT"]
        svc.compute_absorb("BTCUSDT", list(m.store.closed_h1()))
        self.assertTrue(m.absorb_study["1h"]["ready"] and m.absorb_study["4h"]["ready"])
        found = 0
        for tf in ("5m", "1h", "4h"):
            a = m.state(tf)["absorb"]
            self.assertTrue(a["real"])
            self.assertIn(a["studyTf"], ("1h", "4h"))
            found += len(a["events"])
            for e in a["events"]:
                self.assertIn(e["side"], ("bull", "bear"))
                self.assertTrue((e["z"] <= -2) if e["side"] == "bull" else (e["z"] >= 2))
        self.assertGreater(found, 0)                                             # des absorptions fabriquees dans les donnees simulees
        self.assertFalse((Path(cfg.data_dir) / "reports").exists())              # donnees simulees : aucun rapport ecrit
        lec = svc.lecture("BTCUSDT")
        self.assertTrue(lec["ready"])
        if app.flow:                                                             # flux d'ordres (simule) : absorptions en direct
            fl = app.flow.ladder("BTCUSDT", 20.0, 4)
            self.assertIn("absorb", fl)
            self.assertIn("absorbThr", fl)
        self.assertIn("absorption", reports_mod.KINDS)


class ToolTests(unittest.TestCase):
    def test_tool_needs_real_delta_and_writes_report(self):
        from tools import run_absorption_study as tool
        d = Path(tempfile.mkdtemp())
        b = fine.Bars(300_000)
        for k in synth(9000, 7, 0.0):
            b.append(k.t // 12, k.o, k.h, k.l, k.c, k.v, 2 * k.tb - k.v)
        b.build_cum()
        b.save(d / "b5m.bin")
        with self.assertRaises(SystemExit):                                     # pas de meta Binance : refuse
            tool.main(["SOLUSDT", "--folder", str(d), "--out", str(d / "out"), "--tfs", "5m"])
        (d / "meta.json").write_text(json.dumps({"source": "Binance Vision (futures), volume acheteur agressif reel"}), encoding="utf-8")
        self.assertEqual(tool.main(["SOLUSDT", "--folder", str(d), "--out", str(d / "out"), "--tfs", "5m,15m"]), 0)
        rep = json.loads((d / "out" / "absorption_SOL.json").read_text(encoding="utf-8"))
        self.assertEqual((rep["origin"], rep["label"]), ("outil", "SOL"))
        self.assertTrue(rep["tfs"]["5m"]["ready"])


if __name__ == "__main__":
    unittest.main()
