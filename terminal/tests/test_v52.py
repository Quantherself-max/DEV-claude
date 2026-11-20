"""V52 : l'assistant lit lui-même les données du terminal avec des outils (alerts/terminaltools.py), dans un onglet Assistant à part."""
from __future__ import annotations
import json
import os
import tempfile
import types
import unittest
from unittest import mock

from alerts import assistant as A
from alerts import terminaltools as TT
from tests.test_assistant import fake_sdk, cfg, FakeService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def usage(inp=5000, out=400):
    return types.SimpleNamespace(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                 server_tool_use=types.SimpleNamespace(web_search_requests=0))


def tool_use(*calls):
    content = [types.SimpleNamespace(type="text", text="Je regarde.")]
    content += [types.SimpleNamespace(type="tool_use", id=f"tu_{i}", name=n, input=a) for i, (n, a) in enumerate(calls)]
    return types.SimpleNamespace(stop_reason="tool_use", content=content, usage=usage())


def final(text):
    return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)], usage=usage())


class FakeTools:
    def __init__(self):
        self.ran = []

    def defs(self):
        return [{"name": "quant", "description": "x", "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}]

    def run(self, name, args):
        self.ran.append((name, args))
        return json.dumps({"erreur": "manque"}) if name == "panne" else json.dumps({"lu": name, **args})

    def label(self, name, args):
        return name + " " + " ".join(str(v) for v in args.values())


class ToolLoopTest(unittest.TestCase):
    def make(self, responses):
        calls = []
        a = A.Assistant(cfg(chat_web=False), lambda: FakeService(), tempfile.mkdtemp())
        a.tools = FakeTools()
        return a, calls, fake_sdk(responses, calls)

    def test_parallel_tools_then_answer(self):
        a, calls, sdk = self.make([tool_use(("quant", {"paire": "SOLUSDT"}), ("panne", {})), final("Le comptant achète.")])
        with mock.patch.object(A, "sdk", return_value=sdk):
            r = a.ask("qui achète sur SOL ?", focus={"symbol": "SOLUSDT", "tf": "1h"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["answer"], "Le comptant achète.")                 # seul le texte final, pas « Je regarde. »
        self.assertEqual(a.tools.ran, [("quant", {"paire": "SOLUSDT"}), ("panne", {})])
        reqs = [c for c in calls if "messages" in c]
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0]["tools"][0]["name"], "quant")
        self.assertIn("Outils du terminal", reqs[0]["system"][0]["text"])
        self.assertEqual(reqs[0]["system"][0]["cache_control"], {"type": "ephemeral"})
        first_user = reqs[0]["messages"][-1]["content"]
        self.assertIn("L'utilisateur regarde SOLUSDT en 1h", first_user[0]["text"])
        last = reqs[1]["messages"][-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual([b["tool_use_id"] for b in last["content"]], ["tu_0", "tu_1"])     # les deux résultats dans UN message
        self.assertTrue(last["content"][1].get("is_error"))
        marks = [b for m in reqs[1]["messages"] if isinstance(m["content"], list) for b in m["content"] if isinstance(b, dict) and "cache_control" in b]
        self.assertEqual(len(marks), 1)                                       # un seul repère de cache dans les messages
        self.assertEqual(r["read"], ["quant SOLUSDT", "panne "])
        self.assertEqual(a.history()[-1]["read"], ["quant SOLUSDT", "panne "])
        self.assertIsNone(a.progress)

    def test_rounds_are_capped(self):
        many = [tool_use(("quant", {"paire": "BTCUSDT"})) for _ in range(A.MAX_TOOL_ROUNDS + 3)]
        a, calls, sdk = self.make(many + [final("fin")])
        with mock.patch.object(A, "sdk", return_value=sdk):
            r = a.ask("boucle ?")
        self.assertLessEqual(len(a.tools.ran), A.MAX_TOOL_ROUNDS + 1)
        reqs = [c for c in calls if "messages" in c]
        self.assertTrue(any(isinstance(b, dict) and b.get("type") == "text" and "réponds maintenant" in b.get("text", "")
                            for m in reqs[-1]["messages"] if isinstance(m["content"], list) for b in m["content"]))
        self.assertIn("ok", r)

    def test_macro_comment_keeps_no_tools(self):
        a, calls, sdk = self.make([final("commentaire")])
        with mock.patch.object(A, "sdk", return_value=sdk):
            a.ask("commente", context="bilan")
        req = [c for c in calls if "messages" in c][0]
        self.assertNotIn("tools", req)
        self.assertNotIn("Outils du terminal", req["system"][0]["text"])
        self.assertEqual(a.tools.ran, [])


class SlimTest(unittest.TestCase):
    def test_slim_rules(self):
        t = 1_795_190_146_030
        s = TT.slim({"t": t, "times": [1_795_190_146], "x": 1.23456789, "rows": [[1, 2, 3, 4, 5, 6, 7, 8]] * 40, "candles": [1], "n": 7}, cap=5)
        self.assertEqual(s["t"], TT.paris(t))
        self.assertEqual(s["times"], [TT.paris(1_795_190_146_000)])
        self.assertEqual(s["x"], 1.23457)
        self.assertEqual(len(s["rows"]), 6)                                   # 5 plus récentes et la mention des omises
        self.assertEqual(len(s["rows"][-1]), 8)                               # une ligne de valeurs n'est jamais coupée
        self.assertNotIn("candles", s)
        self.assertEqual(s["n"], 7)
        big = TT.dump({"l": [{"a": "x" * 600}] * 200})
        self.assertLessEqual(len(big), TT.LIMIT + 40)


class RealToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from config import Config
        from data.simulated import SimulatedSource
        import server
        c = Config(source="simulated", symbols=("BTCUSDT", "SOLUSDT"), data_dir=tempfile.mkdtemp(), port=0)
        cls.app = server.App(c, make_source=lambda c: SimulatedSource())
        cls.app.service.refresh_all()

    def test_every_tool_answers_within_limits(self):
        T = self.app.assistant.tools
        self.assertIsInstance(T, TT.TerminalTools)
        names = [d["name"] for d in T.defs()]
        self.assertEqual(len(names), 13)
        for d in T.defs():
            self.assertFalse(d["input_schema"]["additionalProperties"])
        args = {"niveaux_et_zones": {"paire": "SOLUSDT", "unite": "4h"}, "bougies": {"paire": "BTCUSDT", "unite": "1h", "nombre": 10},
                "profils_volume": {"paire": "BTCUSDT", "periodes": ["D", "Y"]}, "tpo": {"paire": "BTCUSDT", "seance": "D"},
                "quant": {"paire": "SOLUSDT"}, "options_btc": {}, "liquidations": {"paire": "BTCUSDT"},
                "flux_par_taille": {"paire": "SOLUSDT", "unite": "1h"}, "idees_et_signaux": {"paire": "SOLUSDT"}, "macro": {"periode": "semaine"},
                "divergences": {}, "strategie_et_regime": {"paire": "BTCUSDT"}, "gamma_options": {}}
        for n in names:
            out = T.run(n, args[n])
            self.assertLessEqual(len(out), TT.LIMIT + 40, n)
            json.loads(out) if not out.endswith("trop long)") else None
        b = json.loads(T.run("bougies", {"paire": "BTCUSDT", "unite": "1h", "nombre": 10}))
        self.assertEqual(len(b["bougies"]), 10)
        self.assertEqual(len(b["bougies"][0]), 8)
        p = json.loads(T.run("profils_volume", {"paire": "BTCUSDT", "periodes": ["Y"]}))["profils"]["année"]
        self.assertTrue(p["acheteurs_dominants"] or p["vendeurs_dominants"])
        self.assertIn("erreur", json.loads(T.run("quant", {"paire": "SOLUSDT"})))   # données simulées : pas de moteur exact, et on le dit
        self.assertIn("erreur", json.loads(T.run("bougies", {"paire": "ETHUSDT", "unite": "1h", "nombre": 5})))


if __name__ == "__main__":
    unittest.main()
