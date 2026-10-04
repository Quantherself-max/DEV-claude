import json, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from alerts.notifier import TelegramNotifier
from alerts.rules import AlertEngine, format_alert, fmt_price
from config import Config


class FakeNotifier:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def send(self, text):
        self.sent.append(text)
        return self.ok, "fake"


def make_state(zones, symbol="BTCUSDT", price=85000.0, tol=130.0):
    levels = []
    for z in zones:
        for i, (name, group, kind, extra) in enumerate(z["m"]):
            levels.append({"id": f"{group}|{name}", "name": name, "price": z["mid"] + i, "group": group, "kind": kind,
                           "pool": extra.get("pool")})
    zs = []
    for k, z in enumerate(zones):
        groups = sorted({g for _, g, _, _ in z["m"]})
        side = "above" if z["mid"] > price else "below"
        has_mag = any(e.get("pool", {}).get("magnet") for _, _, _, e in z["m"])
        zs.append({"id": f"z{k}", "mid": z["mid"], "lo": z["mid"], "hi": z["mid"] + 1, "side": side,
                   "distPct": (z["mid"] / price - 1) * 100, "distAtr": z.get("distAtr", abs(z["mid"] - price) / 400.0),
                   "groups": groups, "score": len(groups) + (1 if has_mag else 0), "hasMagnet": has_mag,
                   "members": [f"{g}|{n}" for n, g, _, _ in z["m"]]})
    return {"symbol": symbol, "tf": "1h", "price": price, "tol": tol, "levels": levels, "zones": zs}


Z3 = {"mid": 86000.0, "m": [("PWH", "PWHL", "hl", {}), ("dVWAP", "dVWAP", "vwap", {}), ("wPOC", "wVP", "vp", {})]}
Z2 = {"mid": 84000.0, "m": [("mOpen", "mOpen", "open", {}), ("dVWAP", "dVWAP", "vwap", {})]}
Z2MAG = {"mid": 87400.0, "m": [("PWH", "PWHL", "hl", {}),
                               ("Liq shorts", "LIQ", "liq", {"pool": {"magnet": True, "score": 100}})]}


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


class AlertRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(data_dir=self.tmp.name)
        self.clock, self.n = Clock(), FakeNotifier()
        self.eng = AlertEngine(self.cfg, self.n, now=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_startup_registers_without_spam_then_one_summary(self):
        st = make_state([Z3, Z2])
        self.eng.run_cycle({"BTCUSDT": st})
        self.assertEqual(len(self.n.sent), 1)                   # un seul message : le resume
        self.assertIn("Terminal demarre", self.n.sent[0])
        self.assertIn("86 000", self.n.sent[0])
        self.assertNotIn("84 000", self.n.sent[0])              # 2 sources simples : pas qualifiante
        self.eng.run_cycle({"BTCUSDT": st})
        self.assertEqual(len(self.n.sent), 1)                   # rien de nouveau

    def test_new_zone_alerts_once_and_scoring(self):
        self.eng.run_cycle({"BTCUSDT": make_state([Z2])})
        self.n.sent.clear()
        self.eng.run_cycle({"BTCUSDT": make_state([Z2, Z3, Z2MAG])})
        texts = "\n".join(self.n.sent)
        self.assertEqual(len(self.n.sent), 2)                   # Z3 (3 sources) et Z2MAG (2 sources + AIMANT) ; pas Z2
        self.assertIn("86 000", texts)
        self.assertIn("87 400", texts)
        self.assertIn("AIMANT", texts)
        self.eng.run_cycle({"BTCUSDT": make_state([Z2, Z3, Z2MAG])})
        self.assertEqual(len(self.n.sent), 2)                   # pas de doublon

    def test_drifting_zone_is_not_realerted_but_far_zone_is_new(self):
        self.eng.run_cycle({"BTCUSDT": make_state([])})
        self.eng.run_cycle({"BTCUSDT": make_state([Z3])})
        k = len(self.n.sent)
        drift = dict(Z3, mid=86000.0 + 150)                      # derive de 150 (< 2 x tolerance)
        self.clock.t += 600
        self.eng.run_cycle({"BTCUSDT": make_state([drift])})
        self.assertEqual(len(self.n.sent), k)
        far = dict(Z3, mid=88000.0, distAtr=3.0)
        self.eng.run_cycle({"BTCUSDT": make_state([far])})
        self.assertEqual(len(self.n.sent), k + 1)

    def test_approach_alert_and_cooldown(self):
        self.eng.run_cycle({"BTCUSDT": make_state([])})
        self.eng.run_cycle({"BTCUSDT": make_state([Z3])})
        self.assertEqual(len(self.n.sent), 2)                    # resume + nouvelle
        close = dict(Z3, distAtr=0.3)
        self.clock.t += 900
        self.eng.run_cycle({"BTCUSDT": make_state([close])})
        self.assertIn("approche", self.n.sent[-1])
        k = len(self.n.sent)
        self.eng.run_cycle({"BTCUSDT": make_state([close])})
        self.assertEqual(len(self.n.sent), k)                    # une seule alerte "approche"
        self.clock.t += 7 * 3600                                 # cooldown (6 h) ecoule : on peut re-alerter
        self.eng.run_cycle({"BTCUSDT": make_state([close])})
        self.assertGreater(len(self.n.sent), k)

    def test_too_far_zone_is_ignored(self):
        self.eng.run_cycle({"BTCUSDT": make_state([])})
        self.eng.run_cycle({"BTCUSDT": make_state([dict(Z3, distAtr=9.0)])})
        self.assertEqual(len(self.n.sent), 1)                    # seulement le resume

    def test_hourly_rate_limit_and_log(self):
        self.cfg.alert_max_per_hour = 2
        self.eng.run_cycle({"BTCUSDT": make_state([])})
        zones = [dict(Z3, mid=86000.0 + 1000 * i, distAtr=2.0) for i in range(5)]
        self.eng.run_cycle({"BTCUSDT": make_state(zones)})
        self.assertEqual(len(self.n.sent), 3)                    # le resume + 2 alertes (limite), le reste est bloque
        self.assertEqual(sum(e["detail"] == "limite horaire atteinte" for e in self.eng.log), 3)

    def test_restart_does_not_realert_known_zone(self):
        self.eng.run_cycle({"BTCUSDT": make_state([])})
        self.eng.run_cycle({"BTCUSDT": make_state([Z3])})
        n2 = FakeNotifier()
        eng2 = AlertEngine(self.cfg, n2, now=self.clock)          # "redemarrage" : memoire rechargee
        eng2.run_cycle({"BTCUSDT": make_state([Z3])})
        self.assertEqual(len(n2.sent), 1)                         # uniquement le resume
        self.assertIn("Terminal demarre", n2.sent[0])

    def test_probabilities_in_message(self):
        st = make_state([Z3])
        st["zones"][0]["prob"] = {"reach": {"4": 0.1, "24": 0.35, "72": 0.6}, "bounce": {"p": 0.58, "n": 320},
                                  "base": {"p": 0.51, "n": 900}}
        txt = format_alert("new", st, st["zones"][0])
        self.assertIn("atteinte 24 h ≈ 35 %", txt)
        self.assertIn("rebond 58 % [n=320]", txt)
        self.assertIn("hasard 51 %", txt)

    def test_sweep_alert_once_and_not_at_startup(self):
        ev_old = {"t": 1, "side": "long", "price": 81600.0, "frac": 0.3, "result": "open"}
        st = make_state([])
        st["sweeps"] = {"stats": {"n": 20, "p": 0.6}, "recent": [ev_old]}
        self.eng.run_cycle({"BTCUSDT": st})                          # demarrage : deja vu, pas d'alerte
        self.assertEqual(len(self.n.sent), 1)
        ev_new = {"t": 2, "side": "short", "price": 87600.0, "frac": 0.2, "result": "open"}
        small = {"t": 3, "side": "short", "price": 88000.0, "frac": 0.05, "result": "open"}
        st["sweeps"]["recent"] = [small, ev_new, ev_old]
        self.eng.run_cycle({"BTCUSDT": st})
        self.assertEqual(len(self.n.sent), 2)
        self.assertIn("Poche de liquidation balayee ▲", self.n.sent[-1])
        self.assertIn("rebond 60 % [n=20]", self.n.sent[-1])
        self.eng.run_cycle({"BTCUSDT": st})
        self.assertEqual(len(self.n.sent), 2)                         # pas de doublon

    def test_message_format(self):
        st = make_state([Z2MAG])
        txt = format_alert("new", st, st["zones"][0])
        self.assertIn("Nouvelle confluence", txt)
        self.assertIn("▲", txt)
        self.assertIn("BTCUSDT 87 400", txt)
        self.assertEqual(fmt_price(190.5), "190.50")


class _Telegram(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Telegram.received.append((self.path, body))
        ok = "/botGOOD/" in self.path
        self.send_response(200 if ok else 401)
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok}).encode())

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "result": [{"message": {"chat": {"id": 42, "first_name": "Wassim"}}}]}).encode())

    def log_message(self, *a):
        pass


class TelegramTests(unittest.TestCase):
    def test_send_and_chat_id_against_local_mock(self):
        srv = HTTPServer(("127.0.0.1", 0), _Telegram)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            ok, _ = TelegramNotifier("GOOD", "42", base).send("coucou")
            self.assertTrue(ok)
            path, body = _Telegram.received[-1]
            self.assertEqual(path, "/botGOOD/sendMessage")
            self.assertEqual(body["chat_id"], "42")
            self.assertEqual(body["text"], "coucou")
            ok, detail = TelegramNotifier("BAD", "42", base).send("x")
            self.assertFalse(ok)
            self.assertIn("401", detail)
            self.assertEqual(TelegramNotifier("GOOD", "42", base).find_chat_ids(), {42: "Wassim"})
            ok, detail = TelegramNotifier("GOOD", "42", "http://127.0.0.1:9").send("x")   # reseau coupe
            self.assertFalse(ok)
        finally:
            srv.shutdown()


class MacroAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(data_dir=self.tmp.name, alert_macro=True)
        self.clock, self.n = Clock(), FakeNotifier()
        self.eng = AlertEngine(self.cfg, self.n, now=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def ev(self, mins, **kw):
        now_ms = self.clock.t * 1000
        e = {"id": "cpi1", "t": now_ms + mins * 60_000, "impact": 3, "w": 0.9, "label": "Inflation (CPI)", "country": "USD",
             "forecast": "0.3%", "previous": "0.2%",
             "exp": {"text": "Consensus 0.3% contre 0.2% precedemment : hausse attendue.", "scen_up": "Si superieur : restrictif.", "scen_dn": "Si inferieur : accommodant."}}
        e.update(kw)
        return e

    def test_pre_event_alert_once_between_65_and_10_minutes(self):
        self.assertEqual(self.eng.macro_alerts({"upcoming": [self.ev(180)], "past": []}), [])           # trop tot
        out = self.eng.macro_alerts({"upcoming": [self.ev(55)], "past": []})
        self.assertEqual(len(out), 1)
        self.assertIn("Annonce majeure dans 55 min", out[0][2])
        self.assertIn("restrictif", out[0][2])
        self.assertEqual(self.eng.macro_alerts({"upcoming": [self.ev(50)], "past": []}), [])           # une seule fois
        again = AlertEngine(self.cfg, self.n, now=self.clock)                                          # redemarrage : memoire conservee
        self.assertEqual(again.macro_alerts({"upcoming": [self.ev(45)], "past": []}), [])
        self.assertEqual(self.eng.macro_alerts({"upcoming": [self.ev(5, id="late")], "past": []}), [])  # trop tard pour prevenir
        self.assertEqual(self.eng.macro_alerts({"upcoming": [self.ev(55, id="x", impact=2)], "past": []}), [])
        self.assertEqual(self.eng.macro_alerts({"upcoming": [self.ev(55, id="y", w=0.3)], "past": []}), [])

    def test_post_event_summary_with_measured_reaction(self):
        past = self.ev(-40, reaction={"impulse": 1.9, "impulseLabel": "restrictive forte", "btc": {"r15": -0.62, "r60": -1.1},
                                      "cross": {"US10Y": 6.0, "DXY": 0.25}})
        first = self.eng.macro_alerts({"upcoming": [], "past": [past]}, first=True)
        self.assertEqual(first, [])                                                                   # au demarrage : on enregistre sans envoyer
        self.assertEqual(self.eng.macro_alerts({"upcoming": [], "past": [past]}), [])
        past2 = self.ev(-40, id="nfp", reaction={"impulse": -1.0, "impulseLabel": "accommodante", "btc": {"r15": 0.4, "r60": None},
                                                  "cross": {"US10Y": -3.0, "DXY": -0.1}})
        out = self.eng.macro_alerts({"upcoming": [], "past": [past2]})
        self.assertEqual(len(out), 1)
        self.assertIn("accommodante", out[0][2])
        self.assertIn("BTC +0.40 % en 15 min", out[0][2])
        pending = self.ev(-40, id="p", reaction=None)
        self.assertEqual(self.eng.macro_alerts({"upcoming": [], "past": [pending]}), [])               # pas encore mesure : on attend

    def test_disabled_and_run_cycle_dispatch(self):
        off = AlertEngine(Config(data_dir=self.tmp.name, alert_macro=False), self.n, now=self.clock)
        self.assertEqual(off.macro_alerts({"upcoming": [self.ev(55)], "past": []}), [])
        st = make_state([Z3])
        self.eng.run_cycle({"BTCUSDT": st}, {"upcoming": [], "past": []})                              # demarrage
        self.n.sent.clear()
        self.eng.run_cycle({"BTCUSDT": st}, {"upcoming": [self.ev(55)], "past": []})
        self.assertTrue(any("Annonce majeure" in x for x in self.n.sent))


if __name__ == "__main__":
    unittest.main()
