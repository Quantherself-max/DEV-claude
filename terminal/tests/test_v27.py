"""V27 : terminal allégé. Lexique et plan de trade retirés, idées de trade sur une page à part (plus d'onglet Idées dans le panneau de
droite), une seule page Macro. (Les menus déroulants du graphique de la V27 sont remplacés en V28 par le menu « ＋ Éléments » : test_v28.)"""
import json
import re
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from server import App, serve

WEB = Path(__file__).resolve().parent.parent / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")


class PagesTests(unittest.TestCase):
    def test_removed_pages_are_gone(self):
        for gone in ('data-sub="lex"', 'data-sub="plan"', 'data-an="lex"', 'data-an="plan"', 'id="anLex"', 'id="anPlan"',
                     'data-sub="week"', 'data-sub="month"', 'macroweek.js', 'macromonth.js', 'data-tab="signals"'):
            self.assertNotIn(gone, HTML)
        self.assertFalse((WEB / "macroweek.js").exists())
        self.assertFalse((WEB / "macromonth.js").exists())
        self.assertNotIn("renderLex", (WEB / "analysis.js").read_text(encoding="utf-8"))
        self.assertNotIn("/api/plan", (WEB / "analysis.js").read_text(encoding="utf-8"))

    def test_one_macro_entry_and_an_ideas_page(self):
        self.assertEqual(len(re.findall(r'data-sub="macro"', HTML)), 1)                     # une seule entrée Macro dans le menu
        self.assertIn('<script src="macro.js"></script>', HTML)
        self.assertIn('data-page="signals"', HTML)                                           # la page Idées de trade existe
        self.assertEqual(HTML.count('id="sigBox"'), 1)
        side = HTML[HTML.index('<aside id="side">'):HTML.index('</aside>', HTML.index('<aside id="side">'))]
        self.assertNotIn("sigBox", side)                                                     # plus d'idées dans le panneau de droite

    def test_old_bookmarks_lead_to_macro(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("const OLD_SUBS = {week: 'macro', month: 'macro', plan: 'macro', lex: 'macro'}", app)
        self.assertIn("signals: 'Idées de trade'", app)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0), env_path=None)
        cls.httpd = serve(cls.app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pages_are_served_and_plan_is_gone(self):
        code, body = self.get("/macro.js")
        self.assertEqual(code, 200)
        self.assertIn(b"const Macro", body)
        self.assertEqual(self.get("/macroweek.js")[0], 404)
        self.assertEqual(self.get("/api/plan?symbol=BTCUSDT&side=long&tp=2&sl=1&lev=10&h=24")[0], 404)
        cfg = json.loads(self.get("/api/config")[1])
        self.assertGreaterEqual(float(cfg["version"]), 27)


if __name__ == "__main__":
    unittest.main()
