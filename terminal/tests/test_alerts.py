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


if __name__ == "__main__":
    unittest.main()
