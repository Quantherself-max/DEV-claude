"""V24.2 : Telegram fiable (reglages lus quoi qu'il arrive, diagnostic pas a pas, badge explique, bot qui repond sans Claude)."""
from __future__ import annotations
import sys
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import config as config_mod
from alerts import assistant as A
from alerts import notifier as N
from config import Config, chat_ok, clean_chat, clean_token, load_config, token_ok

TMP_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}   # Python 3.9 (Mac) : option absente

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
BAD = "987654321:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsXX"


class FakeTelegram(BaseHTTPRequestHandler):
    """Faux serveur Telegram : TOKEN est accepte, BAD refuse (401) ; le chat 42 existe, les autres non."""
    sent = []

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        tok, method = self.path.split("/")[1][3:], self.path.split("/")[2]
        if tok != TOKEN:
            return self._send(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        if method == "getMe":
            return self._send(200, {"ok": True, "result": {"id": 1, "is_bot": True, "username": "mon_terminal_bot"}})
        if method == "getWebhookInfo":
            return self._send(200, {"ok": True, "result": {"url": ""}})
        if method in ("getChat", "sendMessage"):
            if str(body.get("chat_id")) != "42":
                return self._send(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
            if method == "sendMessage":
                FakeTelegram.sent.append(body)
                return self._send(200, {"ok": True, "result": {"message_id": 1}})
            return self._send(200, {"ok": True, "result": {"id": 42, "type": "private", "first_name": "Wassim"}})
        return self._send(200, {"ok": True, "result": []})

    do_GET = do_POST

    def log_message(self, *a):
        pass


class SettingsFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
                if not env or k not in env:
                    os.environ.pop(k, None)
            return load_config(self.d / ".env")

    def test_notepad_bom_and_windows_encoding_are_read(self):
        (self.d / ".env").write_bytes(("﻿TELEGRAM_BOT_TOKEN=" + TOKEN + "\r\nTELEGRAM_CHAT_ID=42\r\n").encode("utf-8"))
        c = self.load()
        self.assertEqual((c.telegram_token, c.telegram_chat_id, c.telegram_on), (TOKEN, "42", True))
        (self.d / ".env").write_bytes(("# réglages\nexport TELEGRAM_BOT_TOKEN=\"" + TOKEN + "\"\nTELEGRAM_CHAT_ID = 42\n").encode("cp1252"))
        self.assertTrue(self.load().telegram_on)

    def test_hidden_txt_extension_is_read_and_dot_env_wins(self):
        (self.d / ".env.txt").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=42\n", encoding="utf-8")
        c = self.load()
        self.assertTrue(c.telegram_on)                                       # Windows : « .env » enregistre en « .env.txt »
        (self.d / ".env").write_text("TELEGRAM_CHAT_ID=77777\n", encoding="utf-8")
        c = self.load()
        self.assertEqual((c.telegram_token, c.telegram_chat_id), (TOKEN, "77777"))

    def test_an_empty_system_variable_no_longer_erases_the_file(self):
        (self.d / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=42\n", encoding="utf-8")
        self.assertTrue(self.load({"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": " "}).telegram_on)
        self.assertEqual(self.load({"TELEGRAM_CHAT_ID": "555"}).telegram_chat_id, "555")      # une vraie valeur l'emporte toujours

    def test_pasted_token_and_chat_id_are_cleaned(self):
        for raw in (TOKEN, f" bot{TOKEN}\n", f"https://api.telegram.org/bot{TOKEN}/getMe", f'"{TOKEN}"'):
            self.assertEqual(clean_token(raw), TOKEN)
        self.assertTrue(token_ok(TOKEN))
        self.assertFalse(token_ok("123:abc"))
        self.assertEqual([clean_chat(x) for x in (" -1001234567890 ", "t.me/mon_canal", "https://t.me/mon_canal")], ["-1001234567890", "@mon_canal", "@mon_canal"])
        self.assertTrue(all(chat_ok(x) for x in ("42000", "-1001234567890", "@mon_canal", "42")))
        self.assertFalse(any(chat_ok(x) for x in ("abc", "12.5", "@ab", "")))
        self.assertTrue(config_mod.chat_is_bot("123456789", TOKEN))          # le numero du bot colle a la place du sien
        self.assertFalse(config_mod.chat_is_bot("42", TOKEN))


class NotifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_last_send_is_remembered_with_a_plain_explanation(self):
        ok, _ = N.TelegramNotifier(TOKEN, "42", self.base).send("salut")
        self.assertTrue(ok)
        self.assertEqual((N.LAST["ok"], N.LAST["chat"]), (True, "42"))
        ok, detail = N.TelegramNotifier(TOKEN, "7", self.base).send("salut")
        self.assertFalse(ok)
        self.assertIn("chat not found", detail)
        self.assertIn("Démarrer", N.LAST["help"])
        ok, detail = N.TelegramNotifier(BAD, "42", self.base).send("salut")
        self.assertIn("401", detail)
        self.assertIn("token refusé", N.explain(detail))
        self.assertIn("injoignable", N.explain("URLError: <urlopen error [Errno 111] Connection refused>"))
        self.assertIn("autre programme", N.explain("HTTPError: HTTP Error 409: Conflict"))


class FakeAssistant:
    def __init__(self, key=""):
        self.cfg = Config(chat_key=key, telegram_token=TOKEN, telegram_chat_id="42")
        self.asked = []

    def ask(self, text, src="web"):
        self.asked.append(text)
        return {"answer": "réponse de Claude"}

    def status(self):
        return {"spent": 0.0, "budget": 20.0, "modelName": "Claude"}

    def reset(self):
        pass


class BotWithoutClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []

        class Tg:
            def _call(s, method, payload=None):
                self.sent.append((method, payload))
                return {"ok": True}
        self.mk = lambda timeout: Tg()

    def tearDown(self):
        self.tmp.cleanup()

    def chat(self, key=""):
        a = FakeAssistant(key)
        return a, A.TelegramChat(a.cfg, a, self.tmp.name, make_notifier=self.mk, commands={"etat": lambda: "ÉTAT DU TERMINAL", "idees": lambda: "AUCUNE IDÉE"})

    def test_the_bot_answers_commands_and_explains_without_a_claude_key(self):
        a, c = self.chat()
        self.assertIn("bien relié", c.handle({"chat": {"id": 42}, "text": "/start"}))
        self.assertEqual(c.handle({"chat": {"id": 42}, "text": "/etat"}), "ÉTAT DU TERMINAL")
        self.assertEqual(c.handle({"chat": {"id": 42}, "text": "/idées"}), "AUCUNE IDÉE")
        self.assertIn("clé API Claude", c.handle({"chat": {"id": 42}, "text": "pourquoi le BTC baisse ?"}))
        self.assertEqual(a.asked, [])                                         # rien n'est envoye a Claude sans cle
        a2, c2 = self.chat("sk-ant-key")
        self.assertEqual(c2.handle({"chat": {"id": 42}, "text": "pourquoi ?"}), "réponse de Claude")
        self.assertIn("/etat", c2.handle({"chat": {"id": 42}, "text": "/aide"}))

    def test_a_stranger_gets_only_its_own_chat_id_once_a_day(self):
        _, c = self.chat()
        self.assertIsNone(c.handle({"chat": {"id": 999, "first_name": "Inconnu"}, "text": "bonjour"}))
        msgs = [p for m, p in self.sent if m == "sendMessage"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["chat_id"], "999")
        self.assertIn("Ton chat id est : 999", msgs[0]["text"])
        self.assertNotIn("ÉTAT", msgs[0]["text"])
        c.handle({"chat": {"id": 999}, "text": "encore"})
        self.assertEqual(len([1 for m, _ in self.sent if m == "sendMessage"]), 1)
        self.assertEqual(c.seen["999"], "Inconnu")                            # « Trouver mon chat id » pendant l'ecoute


class AppTelegramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from data.simulated import SimulatedSource
        from server import App
        from tests.test_data_server import NOW
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory(**TMP_KW)
        cls.env = mock.patch.dict(os.environ, {})
        cls.env.start()
        for k in [k for k in os.environ if k.startswith(("TELEGRAM_", "TERMINAL_"))]:
            os.environ.pop(k)
        base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        (Path(cls.tmp.name) / ".env").write_text(f"TELEGRAM_API_BASE={base}\nTERMINAL_SYMBOLS=BTCUSDT\n", encoding="utf-8")
        c = Config(source="simulated", symbols=("BTCUSDT",), data_dir=cls.tmp.name, port=0, telegram_api_base=base)
        cls.app = App(c, env_path=Path(cls.tmp.name) / ".env", make_source=lambda c: SimulatedSource(now_ms=NOW), make_hub=lambda c, s: None)
        cls.app.service.refresh_all()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        N.LAST.clear()

    def test_state_diagnosis_and_saving(self):
        app = self.app
        st = app.telegram_state()
        self.assertFalse(st["on"])
        self.assertIn("Ni token ni chat id", st["reason"])
        d = app.telegram_diagnose()
        names = [s["name"] for s in d["steps"]]
        self.assertIn("Token enregistré", names)
        self.assertFalse(d["ok"])
        d = app.telegram_diagnose(BAD, "42")                                  # valeurs du formulaire, token refuse
        bad = next(s for s in d["steps"] if s["name"] == "Token accepté par Telegram")
        self.assertFalse(bad["ok"])
        self.assertIn("BotFather", bad["fix"])
        self.assertTrue(any(s["name"] == "Formulaire" for s in d["steps"]))
        d = app.telegram_diagnose(TOKEN, "7")                                 # chat inconnu
        conv = next(s for s in d["steps"] if s["name"] == "Conversation trouvée")
        self.assertFalse(conv["ok"])
        self.assertIn("Trouver mon chat id", conv["fix"])
        out = app.save_settings({"telegramToken": f"bot{TOKEN} ", "telegramChatId": " 42 "})
        self.assertTrue(out["telegram"]["configured"])
        self.assertIn(f"TELEGRAM_BOT_TOKEN={TOKEN}", (Path(self.tmp.name) / ".env").read_text())
        d = app.telegram_diagnose()
        self.assertTrue(d["ok"], d)
        self.assertIn("@mon_terminal_bot", next(s for s in d["steps"] if s["name"] == "Token accepté par Telegram")["detail"])
        with self.assertRaises(ValueError) as e:
            app.save_settings({"telegramToken": "pas un token"})
        self.assertIn("BotFather", str(e.exception))
        with self.assertRaises(ValueError) as e:
            app.save_settings({"telegramChatId": "123456789"})              # numero du bot (debut du token) a la place du sien
        self.assertIn("numéro de ton bot", str(e.exception))
        self.assertIn("TON chat id", N.explain("Bad Request: bots can't send messages to bots"))
        ok, _ = app.notifier.send("test")
        self.assertTrue(ok)
        self.assertIn("dernier envoi réussi", app.telegram_state()["reason"])
        self.assertIn("Terminal en marche", app.bot_status())
        self.assertIn("Idées cette semaine", app.bot_status())
        self.assertIn("Aucune idée en cours", app.bot_ideas())


if __name__ == "__main__":
    unittest.main()
