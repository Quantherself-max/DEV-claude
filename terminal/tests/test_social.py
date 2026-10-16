import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from alerts.trades import TradeDesk
from config import Config, load_config
from data.social import Influencers, XClient, XError, clean_handles
from engine import stance

NOW = 1_790_000_000.0                       # secondes
H = 3600


def iso(age_h):
    return datetime.fromtimestamp(NOW - age_h * H, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


TWEETS = {
    "alice": [("BTC bullish breakout, long here", 2), ("Bitcoin accumulation", 6)],
    "bob": [("BTC bearish, breakdown incoming, shorting", 3)],
    "carl": [("gm everyone", 1)],
    "old": [("BTC bullish", 100)],
}


class FakeX(BaseHTTPRequestHandler):
    log = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeX.log.append(self.path)
        tok = self.headers.get("Authorization", "")
        if tok == "Bearer poor":
            return self._send({"title": "CreditsDepleted"}, 402)
        if tok == "Bearer limit":
            return self._send({}, 429)
        if not tok.startswith("Bearer good"):
            return self._send({}, 401)
        if "/users/by/username/" in self.path:
            h = self.path.split("/users/by/username/")[1].split("?")[0]
            if h == "ghost":
                return self._send({"errors": [{"detail": "not found"}]})
            return self._send({"data": {"id": "id_" + h, "username": h}})
        if "/tweets" in self.path:
            uid = self.path.split("/users/")[1].split("/")[0]
            h = uid[3:]
            if "exclude=retweets%2Creplies" not in self.path:
                return self._send({}, 400)
            return self._send({"data": [{"id": str(i), "text": t, "created_at": iso(a)} for i, (t, a) in enumerate(TWEETS.get(h, []))]})
        self._send({}, 404)


class SocialBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeX)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        FakeX.log.clear()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, **kw):
        base = dict(data_dir=self.tmp.name, x_token="good", x_accounts=("alice", "bob", "carl", "old"), x_api_base=self.base, x_posts=10)
        base.update(kw)
        return Config(**base)


class HandleTests(unittest.TestCase):
    def test_clean_handles(self):
        self.assertEqual(clean_handles("@Alice, bob  carl;alice"), ["Alice", "bob", "carl"])
        self.assertEqual(clean_handles(["@a", "b-c", "d" * 20, "ok_1"]), ["a", "ok_1"])
        self.assertEqual(len(clean_handles(",".join(f"u{i}" for i in range(30)))), 10)
        self.assertEqual(clean_handles(None), [])


class ClientTests(SocialBase):
    def test_posts_are_parsed_and_user_ids_are_cached_on_disk(self):
        users = Path(self.tmp.name) / "users.json"
        c = XClient("good", self.base, users_file=users)
        posts = c.posts("alice", 10)
        self.assertEqual(len(posts), 2)
        self.assertAlmostEqual((NOW * 1000 - posts[0]["t"]) / 3.6e6, 2.0, places=2)
        self.assertEqual(posts[0]["url"], "https://x.com/alice/status/0")
        lookups = [p for p in FakeX.log if "/by/username/" in p]
        self.assertEqual(len(lookups), 1)
        XClient("good", self.base, users_file=users).posts("alice", 10)                     # nouvelle instance : identifiant lu sur le disque
        self.assertEqual(len([p for p in FakeX.log if "/by/username/" in p]), 1)
        self.assertEqual(json.loads(users.read_text()), {"alice": "id_alice"})

    def test_errors_are_explained_in_french(self):
        for tok, word in (("bad", "jeton refusé"), ("poor", "crédits"), ("limit", "limite")):
            with self.assertRaises(XError) as cm:
                XClient(tok, self.base).posts("alice", 5)
            self.assertIn(word, str(cm.exception))
        with self.assertRaises(XError) as cm:
            XClient("good", self.base).posts("ghost", 5)
        self.assertIn("introuvable", str(cm.exception))
        with self.assertRaises(XError) as cm:
            XClient("good", "http://127.0.0.1:9", timeout=2).posts("alice", 5)
        self.assertIn("injoignable", str(cm.exception))


class InfluencerTests(SocialBase):
    def test_not_configured_returns_off_and_makes_no_request(self):
        for cfg in (self.cfg(x_token=""), self.cfg(x_accounts=()), self.cfg(x_on=False)):
            inf = Influencers(cfg, now=lambda: NOW)
            self.assertFalse(inf.configured)
            self.assertEqual(inf.opinions("BTCUSDT", "long"), {"on": False, "configured": False})
        self.assertEqual(FakeX.log, [])

    def test_opinions_agree_disagree_and_cost(self):
        inf = Influencers(self.cfg(), now=lambda: NOW)
        op = inf.opinions("BTCUSDT", "long")
        by = {a["handle"]: a for a in op["accounts"]}
        self.assertEqual((by["alice"]["stance"], by["alice"]["relation"]), ("bull", "agree"))
        self.assertEqual((by["bob"]["stance"], by["bob"]["relation"]), ("bear", "disagree"))
        self.assertEqual(by["carl"]["relation"], "none")
        self.assertEqual(by["old"]["relation"], "none")                                    # post vieux de 100 h : ignore
        self.assertEqual(op["summary"], {"agree": 1, "disagree": 1, "neutral": 0, "none": 2, "total": 4, "errors": 0})
        self.assertEqual(op["cost"]["posts"], 5)
        self.assertAlmostEqual(op["cost"]["usd"], 0.025)
        short = inf.opinions("BTCUSDT", "short")                                           # meme lecture, sens inverse
        self.assertEqual({a["handle"]: a["relation"] for a in short["accounts"]}["alice"], "disagree")
        self.assertEqual({a["handle"]: a["relation"] for a in short["accounts"]}["bob"], "agree")

    def test_posts_are_cached_for_30_minutes_then_read_again(self):
        t = [NOW]
        inf = Influencers(self.cfg(), now=lambda: t[0])
        inf.opinions("BTCUSDT", "long")
        n1 = len([p for p in FakeX.log if "/tweets" in p])
        again = inf.opinions("SOLUSDT", "short")                                           # autre paire, memes posts : aucune nouvelle lecture
        self.assertEqual(len([p for p in FakeX.log if "/tweets" in p]), n1)
        self.assertEqual(again["cost"]["posts"], 0)
        t[0] += 31 * 60
        inf.opinions("BTCUSDT", "long")
        self.assertEqual(len([p for p in FakeX.log if "/tweets" in p]), 2 * n1)

    def test_errors_are_per_account_cached_five_minutes_and_never_raise(self):
        t = [NOW]
        inf = Influencers(self.cfg(x_accounts=("alice", "ghost")), now=lambda: t[0])
        op = inf.opinions("BTCUSDT", "long")
        by = {a["handle"]: a for a in op["accounts"]}
        self.assertEqual(by["alice"]["relation"], "agree")
        self.assertIn("introuvable", by["ghost"]["error"])
        self.assertEqual(op["summary"]["errors"], 1)
        n = len(FakeX.log)
        inf.opinions("BTCUSDT", "long")
        self.assertEqual(len(FakeX.log), n)                                                # l'erreur n'est pas martelee
        bad = Influencers(self.cfg(x_token="bad"), now=lambda: NOW).opinions("BTCUSDT", "long")
        self.assertTrue(all("jeton refusé" in a["error"] for a in bad["accounts"]))

    def test_token_test(self):
        inf = Influencers(self.cfg(), now=lambda: NOW)
        r = inf.test()
        self.assertTrue(r["ok"], r)
        self.assertIn("@alice", r["detail"])
        self.assertFalse(inf.test("bad", "alice")["ok"])
        self.assertFalse(Influencers(self.cfg(x_token="", x_accounts=()), now=lambda: NOW).test()["ok"])
        self.assertTrue(inf.test("good", "@bob")["ok"])


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True, "ok"


def idea():
    return {"symbol": "BTCUSDT", "side": "long", "kind": "rebond", "score": 80.0, "entry": 100.0, "entryType": "limite", "stop": 98.0, "tp1": 104.0, "tp2": 108.0,
            "rr1": 2.0, "rr2": 4.0, "atr": 1.0, "validHours": 48, "zone": {"lo": 99.9, "hi": 100.0, "mid": 99.95, "side": "below"}, "eligible": True, "hold": [],
            "key": "k", "desc": {"headline": "BTCUSDT : ACHAT", "action": ["a"], "why": ["b"], "context": [], "news": [], "probs": [], "risks": ["c"]}}


class DeskTests(SocialBase):
    MON = 1_759_104_000_000 + 12 * 3_600_000

    def desk(self, opinions):
        n = FakeNotifier()
        d = TradeDesk(self.cfg(), n, opinions=opinions)
        d.inline = True
        return d, n

    def test_opinions_follow_the_idea_in_a_second_message_and_change_nothing(self):
        inf = Influencers(self.cfg(), now=lambda: NOW)
        d, n = self.desk(inf.opinions)
        base_d, base_n = self.desk(None)
        sigs = {"BTCUSDT": {"ready": True, "warm": True, "ideas": [idea()]}}
        out = d.consider(sigs, self.MON)
        base_out = base_d.consider({"BTCUSDT": {"ready": True, "warm": True, "ideas": [idea()]}}, self.MON)
        self.assertEqual(len(n.sent), 2)
        self.assertIn("Idée de trade", n.sent[0])
        self.assertNotIn("AVIS D'INFLUENCEURS", n.sent[0])                                  # l'idee elle-meme ne change pas
        self.assertEqual(n.sent[0], base_n.sent[0])
        self.assertIn("AVIS D'INFLUENCEURS SUR X", n.sent[1])
        self.assertIn("1 d'accord", n.sent[1])
        self.assertEqual(out[0]["x"]["agree"], 1)
        for k in ("score", "entry", "stop", "tp1", "tp2", "status"):
            self.assertEqual(out[0][k], base_out[0][k])                                     # ni le score ni la decision ne bougent
        self.assertEqual(len(base_n.sent), 1)

    def test_a_failure_never_blocks_the_idea(self):
        def boom(sym, side):
            raise RuntimeError("X est en panne")
        logs = []
        n = FakeNotifier()
        d = TradeDesk(self.cfg(), n, log=logs.append, opinions=boom)
        d.inline = True
        out = d.consider({"BTCUSDT": {"ready": True, "warm": True, "ideas": [idea()]}}, self.MON)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(n.sent), 1)
        self.assertTrue(any("avis X indisponible" in l["text"] for l in logs))

    def test_off_means_a_single_message(self):
        d, n = self.desk(lambda s, side: {"on": False, "configured": False})
        d.consider({"BTCUSDT": {"ready": True, "warm": True, "ideas": [idea()]}}, self.MON)
        self.assertEqual(len(n.sent), 1)

    def test_background_thread_delivers_the_opinion(self):
        inf = Influencers(self.cfg(), now=lambda: NOW)
        n = FakeNotifier()
        d = TradeDesk(self.cfg(), n, opinions=inf.opinions)                                 # mode normal : fil d'arriere-plan
        d.consider({"BTCUSDT": {"ready": True, "warm": True, "ideas": [idea()]}}, self.MON)
        import time
        for _ in range(60):
            if len(n.sent) >= 2:
                break
            time.sleep(0.1)
        self.assertEqual(len(n.sent), 2)


class ConfigTests(unittest.TestCase):
    def test_env_parsing_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("TERMINAL_X_BEARER_TOKEN=abc123\nTERMINAL_X_ACCOUNTS=@Alice, bob ,bad-handle\nTERMINAL_X_POSTS=99\nTERMINAL_X_ON=0\n", encoding="utf-8")
            c = load_config(env)
            self.assertEqual((c.x_token, c.x_accounts, c.x_posts, c.x_on), ("abc123", ("Alice", "bob"), 20, False))
            self.assertEqual(Config().x_accounts, ())
            self.assertEqual(Config().x_api_base, "https://api.x.com")


if __name__ == "__main__":
    unittest.main()
