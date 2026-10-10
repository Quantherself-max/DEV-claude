import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from alerts import assistant as A
from engine import explain as ex
from engine.atr import Candle

H = 3_600_000
M5 = 300_000
T0 = 1_791_000_000_000 - (1_791_000_000_000 % H)


# ---------------------------------------------------------------- faux module officiel « anthropic »
class _Err(Exception):
    def __init__(self, message="", status_code=400):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def fake_sdk(responses, calls):
    """Module imitant `anthropic` : chaque appel renvoie la reponse suivante de la liste (ou leve l'exception)."""
    mod = types.ModuleType("anthropic")
    mod.APIStatusError = type("APIStatusError", (_Err,), {})
    for name in ("AuthenticationError", "PermissionDeniedError", "RateLimitError", "BadRequestError"):
        setattr(mod, name, type(name, (mod.APIStatusError,), {}))
    mod.APIConnectionError = type("APIConnectionError", (Exception,), {})

    def create(**kw):
        calls.append(kw)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    class Client:
        def __init__(self, api_key=None, timeout=None, max_retries=None):
            calls.append({"init": api_key})
            self.messages = types.SimpleNamespace(create=create)
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    mod.Anthropic = Client
    return mod


def resp(text, stop="end_turn", inp=10_000, out=800, searches=0, urls=()):
    content = [types.SimpleNamespace(type="text", text=text)]
    if urls:
        content.insert(0, types.SimpleNamespace(type="web_search_tool_result", content=[types.SimpleNamespace(url=u) for u in urls]))
    usage = types.SimpleNamespace(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                  server_tool_use=types.SimpleNamespace(web_search_requests=searches))
    return types.SimpleNamespace(stop_reason=stop, content=content, usage=usage)


def cfg(**kw):
    from config import Config
    c = Config(source="simulated", symbols=("BTCUSDT",), chat_key="sk-ant-test-0123456789abcdef", telegram_token="1:abc", telegram_chat_id="42")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class FakeService:
    def __init__(self):
        self.markets, self.ext, self.feed = {}, None, None


class ExplainTests(unittest.TestCase):
    def test_paris_time_follows_summer_and_winter_time(self):
        jan = 1_767_268_800_000                    # 2026-01-01 12:00 UTC
        jul = 1_782_907_200_000                    # 2026-07-01 12:00 UTC
        self.assertEqual(ex.paris_offset_h(jan), 1)
        self.assertEqual(ex.paris_offset_h(jul), 2)
        self.assertEqual(ex.paris(jan), "01/01 13h00")
        self.assertEqual(ex.paris(jul, False), "14h00")

    def candles(self):
        prices = [100.0] * 20 + [100 - 0.15 * i for i in range(1, 21)] + [97 + 0.2 * i for i in range(1, 11)]
        out = []
        for i, p in enumerate(prices):
            out.append(Candle(T0 + i * M5, p, p + 0.05, p - 0.05, p, 100.0 if 20 <= i < 40 else 50.0, 30.0 if 20 <= i < 40 else 25.0))
        return out

    def test_moves_find_the_drop_and_the_rebound(self):
        cs = self.candles()
        now = cs[-1].t + M5
        mv = ex.moves(cs, now, 24.0)
        kinds = {m["kind"]: m for m in mv}
        self.assertIn("baisse", kinds)
        self.assertIn("hausse", kinds)
        d = kinds["baisse"]
        self.assertAlmostEqual(d["pct"], (96.95 / 100.05 - 1) * 100, places=3)
        self.assertLess(d["t0"], d["t1"])
        self.assertEqual(mv[0]["kind"], "baisse")                             # le plus grand d'abord

    def test_window_facts_and_text(self):
        cs = self.candles()
        m = ex.moves(cs, cs[-1].t + M5, 24.0)[0]
        oi_t = [T0, m["t0"], m["t1"]]
        oi_v = [1000.0, 1000.0, 950.0]
        liqs = [{"t": m["t0"] + M5, "side": "long", "usd": 3e6, "price": 99.0}, {"t": m["t0"] + 2 * M5, "side": "short", "usd": 2e5, "price": 98.0},
                {"t": T0 - 10 * H, "side": "long", "usd": 9e9, "price": 1.0}]
        cross = {"DXY": [(m["t0"] - M5, 100.0), (m["t1"] - M5, 100.5)], "US10Y": [(m["t0"] - M5, 4.0), (m["t1"], 4.08)]}
        events = [{"t": m["t0"] - 30 * 60000, "label": "CPI (USD)", "impact": 3}, {"t": m["t0"] - 5 * H, "label": "trop tôt", "impact": 3}]
        fx = ex.window_facts(m, cs, oi_t, oi_v, liqs, cross, events)
        self.assertAlmostEqual(fx["oiPct"], -5.0, places=6)
        self.assertEqual(fx["liqLong"], 3e6)
        self.assertEqual(fx["liqShort"], 2e5)
        self.assertEqual(fx["liqBiggest"]["usd"], 3e6)
        self.assertAlmostEqual(fx["cross"]["DXY"], 0.5, places=6)
        self.assertAlmostEqual(fx["cross"]["US10Y"], 0.08, places=6)
        self.assertEqual(ex.cross_change("US10Y", 0.08), "taux américain à 10 ans +0,08 point")
        self.assertEqual([e["label"] for e in fx["events"]], ["CPI (USD)"])
        self.assertAlmostEqual(fx["buyPct"], (25 + 20 * 30) / (50 + 20 * 100) * 100, places=6)       # la fenetre part de la derniere bougie au sommet
        self.assertGreater(fx["volRatio"], 1.5)
        txt = ex.move_text("BTCUSDT", m, fx)
        for frag in ("baisse", "heure de Paris", "intérêt ouvert −5,00 %", "longs 3,0 M$", "dollar (DXY) +0,50 %", "CPI (USD)"):
            self.assertIn(frag, txt)


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls, self.responses = [], []
        self.saved = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake_sdk(self.responses, self.calls)

    def tearDown(self):
        if self.saved is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self.saved
        self.tmp.cleanup()

    def make(self, **kw):
        return A.Assistant(cfg(**kw), FakeService, self.tmp.name)

    def test_answer_with_context_cost_and_history(self):
        a = self.make()
        self.responses.append(resp("Le BTC a baissé parce que des longs ont été liquidés.", searches=1, urls=("https://exemple.org/news",)))
        r = a.ask("pourquoi le btc baisse ?")
        self.assertTrue(r["ok"])
        self.assertIn("liquidés", r["answer"])
        self.assertIn("Sources : https://exemple.org/news", r["answer"])
        req = self.calls[-1]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(req["tools"][0]["type"], "web_search_20260209")
        self.assertIn("<donnees_du_terminal>", req["messages"][-1]["content"])
        self.assertTrue(req["messages"][-1]["content"].endswith("pourquoi le btc baisse ?"))
        self.assertAlmostEqual(r["usd"], 10_000 * 4 / 1e6 + 800 * 20 / 1e6 + 0.01, places=6)
        self.assertAlmostEqual(a.spent(), r["usd"], places=4)
        saved = json.loads((Path(self.tmp.name) / "assistant.json").read_text())
        self.assertEqual([m["role"] for m in saved["history"]], ["user", "assistant"])
        self.responses.append(resp("Suite."))
        a.ask("et SOL ?")
        msgs = self.calls[-1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], "pourquoi le btc baisse ?")             # les tours precedents sans le gros bloc de donnees
        a.reset()
        self.responses.append(resp("Nouvelle."))
        a.ask("bonjour")
        self.assertEqual(len(self.calls[-1]["messages"]), 1)

    def test_pause_turn_is_resumed_and_haiku_uses_plain_call(self):
        a = self.make(chat_model="claude-haiku-4-5")
        self.responses += [resp("", stop="pause_turn"), resp("Réponse finale.")]
        r = a.ask("question")
        self.assertEqual(r["answer"], "Réponse finale.")
        reqs = [c for c in self.calls if "model" in c]
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[1]["messages"][-1]["role"], "assistant")
        self.assertNotIn("fallbacks", reqs[0])
        self.assertNotIn("output_config", reqs[0])
        self.assertEqual(reqs[0]["tools"][0]["type"], "web_search_20250305")

    def test_guards_and_readable_errors(self):
        self.assertIn("Clé API", self.make(chat_key="").ask("x")["answer"])
        a = self.make(chat_budget=0.001)
        a.state["usage"][a.month()] = 1.0
        self.assertIn("Budget", a.ask("x")["answer"])
        a = self.make()
        self.responses.append(sys.modules["anthropic"].AuthenticationError("bad key", 401))
        r = a.ask("x")
        self.assertFalse(r["ok"])
        self.assertIn("refusée", r["answer"])
        self.responses.append(sys.modules["anthropic"].BadRequestError("Your credit balance is too low", 400))
        self.assertIn("Crédit", a.ask("x")["answer"])
        self.responses.append(sys.modules["anthropic"].APIStatusError("overloaded", 529))
        self.assertIn("surchargé", a.ask("x")["answer"])
        self.responses.append(resp("", stop="refusal"))
        self.assertIn("refusé", a.ask("x")["answer"])
        sys.modules["anthropic"] = None                                               # module absent
        self.assertIn("Installer le module", a.ask("x")["answer"])

    def test_web_search_can_be_turned_off(self):
        a = self.make(chat_web=False)
        self.responses.append(resp("ok"))
        a.ask("x")
        self.assertNotIn("tools", self.calls[-1])

    def test_telegram_only_answers_the_owner(self):
        a = self.make()
        sent = []

        class FakeTg:
            def _call(self, method, payload=None):
                sent.append((method, payload))
                return {"ok": True}
        chat = A.TelegramChat(a.cfg, a, self.tmp.name, make_notifier=lambda timeout: FakeTg())
        self.assertIsNone(chat.handle({"chat": {"id": 999}, "text": "pourquoi ?"}))
        self.assertEqual(chat.ignored, 1)
        self.assertEqual(sent, [])
        self.assertIn("/reset", chat.handle({"chat": {"id": 42}, "text": "/aide"}))
        self.responses.append(resp("x" * 5000))
        out = chat.handle({"chat": {"id": 42}, "text": "explique"})
        self.assertEqual(len(out), 5000)
        msgs = [p for m, p in sent if m == "sendMessage"]
        self.assertGreaterEqual(len(msgs), 3)                                         # aide + reponse coupee en deux
        self.assertTrue(all(len(p["text"]) <= 4096 for p in msgs))
        self.assertTrue(any(m == "sendChatAction" for m, _ in sent))
        self.assertIn("Dépense du mois", chat.handle({"chat": {"id": 42}, "text": "/cout"}))

    def test_split_text(self):
        parts = A.split_text("a\n" * 3000, 1000)
        self.assertTrue(all(len(p) <= 1000 for p in parts))
        self.assertEqual("".join(parts).count("a"), 3000)


class ServiceContextTests(unittest.TestCase):
    """Le contexte construit a partir d'un vrai service (donnees simulees) et l'API du serveur."""

    @classmethod
    def setUpClass(cls):
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        c = cfg(data_dir=cls.tmp.name, port=0, telegram_token="", telegram_chat_id="")
        cls.app = App(c, env_path=Path(cls.tmp.name) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
        cls.app.service.refresh_all()
        cls.now = NOW

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_context_has_the_market_picture(self):
        ctx = A.build_context(self.app.service, self.now)
        for frag in ("=== BTCUSDT", "heure de Paris", "Tendance de fond", "Intérêt ouvert", "Flux et squeeze"):
            self.assertIn(frag, ctx)
        self.assertNotIn("None", ctx)
        self.assertLess(len(ctx), 20000)

    def test_settings_keep_the_key_secret(self):
        out = self.app.save_settings({"chatKey": "sk-ant-api03-SECRETKEY123456789", "chatModel": "claude-sonnet-5-5", "chatBudget": 5, "chatWeb": False})
        env = (Path(self.tmp.name) / ".env").read_text()
        self.assertIn("TERMINAL_ANTHROPIC_API_KEY=sk-ant-api03-SECRETKEY123456789", env)
        self.assertNotIn("SECRETKEY", json.dumps(out))
        self.assertNotIn("SECRETKEY", json.dumps(self.app.assistant.status()))
        self.assertEqual(out["chat"]["model"], "claude-sonnet-5-5")
        self.assertEqual(self.app.assistant.status()["modelName"], "Claude Sonnet 5.5")
        with self.assertRaises(ValueError):
            self.app.save_settings({"chatKey": "clé avec espaces"})
        self.assertIsNone(self.app.tgchat)                                            # pas de Telegram configure : personne n'ecoute


if __name__ == "__main__":
    unittest.main()
