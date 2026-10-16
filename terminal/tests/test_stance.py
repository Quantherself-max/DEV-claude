import unittest

from engine import stance as st

H = 3_600_000
NOW = 1_790_000_000_000


def post(text, age_h=1.0):
    return {"t": int(NOW - age_h * H), "text": text, "url": "https://x.com/a/status/1"}


class MentionTests(unittest.TestCase):
    def test_asset_names_and_matching(self):
        self.assertEqual(st.asset_names("BTCUSDT")[0], "BTC")
        self.assertTrue(st.mentions("$BTC looking strong", st.asset_names("BTCUSDT")[1]))
        self.assertTrue(st.mentions("Bitcoin to 100k", st.asset_names("BTCUSDT")[1]))
        self.assertTrue(st.mentions("#SOL and Solana ecosystem", st.asset_names("SOLUSDT")[1]))
        self.assertFalse(st.mentions("Solid setup on the console", st.asset_names("SOLUSDT")[1]))      # « solid » n'est pas SOL
        self.assertFalse(st.mentions("ETH looks weak", st.asset_names("BTCUSDT")[1]))
        self.assertFalse(st.mentions("see https://x.com/btc_fan", st.asset_names("BTCUSDT")[1]))        # les liens et @mentions ne comptent pas


class PostScoreTests(unittest.TestCase):
    def test_bullish_and_bearish_posts(self):
        self.assertGreaterEqual(st.post_score("BTC is bullish, higher lows, long here"), 2)
        self.assertLessEqual(st.post_score("BTC bearish, lower high and breakdown, shorting"), -2)
        self.assertGreaterEqual(st.post_score("Bitcoin 🚀📈"), 1)
        self.assertLessEqual(st.post_score("SOL 📉🔻"), -1)
        self.assertGreaterEqual(st.post_score("BTC haussier, rebond sur le support"), 2)
        self.assertLessEqual(st.post_score("BTC baissier, vente sur rebond"), -2)

    def test_negation_hedge_and_long_term(self):
        self.assertLess(st.post_score("BTC is not bullish here"), 0)
        self.assertLess(abs(st.post_score("if BTC breaks out it is bullish")), abs(st.post_score("BTC breakout bullish")))
        self.assertEqual(st.post_score("I am long term holder of bitcoin"), 0)
        self.assertEqual(st.post_score("What do you think about BTC?"), 0)
        self.assertEqual(st.post_score("gm"), 0)


class AccountTests(unittest.TestCase):
    def read(self, posts, sym="BTCUSDT"):
        return st.read_account(posts, sym, NOW)

    def test_bull_bear_mixed_unclear_none(self):
        self.assertEqual(self.read([post("BTC bullish breakout, long"), post("Bitcoin accumulation continues", 5)])["stance"], "bull")
        self.assertEqual(self.read([post("BTC bearish, breakdown incoming, short")])["stance"], "bear")
        self.assertEqual(self.read([post("BTC bullish breakout", 1), post("BTC bearish breakdown", 1)])["stance"], "mixed")
        self.assertEqual(self.read([post("BTC price is 85k today")])["stance"], "unclear")
        self.assertEqual(self.read([post("Great weather today"), post("ETH bullish")])["stance"], "none")
        self.assertEqual(self.read([])["stance"], "none")

    def test_recent_posts_weigh_more_and_old_posts_are_ignored(self):
        recent_bear = [post("BTC bearish breakdown", 1), post("BTC bullish breakout", 30)]
        self.assertEqual(self.read(recent_bear)["stance"], "bear")
        self.assertEqual(self.read([post("BTC bullish breakout", 60)])["stance"], "none")                # plus de 48 h
        self.assertEqual(self.read([post("BTC bullish breakout", -5)])["stance"], "none")                # date dans le futur : ignore

    def test_excerpt_url_and_counts(self):
        r = self.read([post("BTC bullish " + "x" * 300, 2), post("BTC long", 3)])
        self.assertLessEqual(len(r["excerpt"]), 120)
        self.assertEqual((r["bull"], r["bear"], r["mentions"]), (2, 0, 2))
        self.assertTrue(r["url"].startswith("https://x.com/"))
        self.assertAlmostEqual(r["lastAgeH"], 2.0, places=1)


class RelationTests(unittest.TestCase):
    def test_relation_matrix(self):
        self.assertEqual(st.relation("bull", "long"), "agree")
        self.assertEqual(st.relation("bear", "long"), "disagree")
        self.assertEqual(st.relation("bear", "short"), "agree")
        self.assertEqual(st.relation("bull", "short"), "disagree")
        self.assertEqual(st.relation("mixed", "long"), "neutral")
        self.assertEqual(st.relation("unclear", "short"), "neutral")
        self.assertEqual(st.relation("none", "long"), "none")


class BlockTests(unittest.TestCase):
    def op(self):
        accs = [{"handle": "alice", "stance": "bull", "relation": "agree", "bull": 3, "bear": 0, "lastAgeH": 2.0, "excerpt": "BTC bullish above 85k"},
                {"handle": "bob", "stance": "bear", "relation": "disagree", "bull": 0, "bear": 2, "lastAgeH": 9.0, "excerpt": "BTC breakdown"},
                {"handle": "carl", "stance": "none", "relation": "none", "bull": 0, "bear": 0, "lastAgeH": None, "excerpt": None},
                {"handle": "dora", "error": "jeton refusé par X (vérifie-le)"}]
        return {"on": True, "asset": "BTC", "accounts": accs, "summary": st.summarize(accs)}

    def test_summary_counts_and_text(self):
        op = self.op()
        self.assertEqual(op["summary"], {"agree": 1, "disagree": 1, "neutral": 0, "none": 1, "total": 4, "errors": 1})
        t = st.format_block(op, "BTCUSDT", "long")
        for part in ("n'entre PAS dans le score", "1 d'accord", "1 en désaccord", "@alice", "✅", "❌", "aucun post récent sur BTC", "indisponible", "mots-clés", "ACHAT"):
            self.assertIn(part, t)
        self.assertIn("« BTC bullish above 85k »", t)

    def test_excerpts_are_dropped_when_the_block_is_too_long(self):
        op = self.op()
        short = st.format_block(op, "BTCUSDT", "short", max_len=200)
        self.assertNotIn("«", short)
        self.assertIn("VENTE", short)


if __name__ == "__main__":
    unittest.main()
