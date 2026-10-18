"""V27 : terminal allégé. Lexique et plan de trade retirés, idées de trade sur une page à part (plus d'onglet Idées dans le panneau de
droite), une seule page Macro, options du graphique principal rangées en menus déroulants sans en perdre aucune."""
import json
import re
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from config import Config
from server import App, serve
from tests.test_v241 import run_js

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


@unittest.skipUnless(shutil.which("node"), "Node n'est pas installé")
class MenuTests(unittest.TestCase):
    # toutes les options de la V26, une par une : aucune ne doit disparaître du graphique principal
    KEYS = {"data-mo": ["sess", "sessW", "sessM", "nodes", "dpoc", "npoc", "tpoM", "tpoW", "tpoD", "tpo4", "tpo1", "vwap", "gex", "dom", "big", "absorb"],
            "data-opt": ["pools", "ppools", "plan"], "data-mosel": ["bigMin", "absorbMode", "bigLabels"]}

    def test_every_option_is_in_exactly_one_menu(self):
        out = run_js("""
            const html = Panel.tools('main'), menus = {};
            const re = /<span class="dd" data-dd="([a-z]+)">([\\s\\S]*?)<\\/div><\\/span>/g;
            let m; while ((m = re.exec(html))) menus[m[1]] = m[2];
            return {menus, rest: html.replace(re, '')};""")
        self.assertEqual(list(out["menus"]), ["zones", "liq", "prof", "tpo", "vwap", "flow", "ideas"])
        self.assertEqual(out["rest"].strip(), "")                                             # rien en dehors des menus
        for attr, keys in self.KEYS.items():
            for k in keys:
                where = [d for d, body in out["menus"].items() if f'{attr}="{k}"' in body]
                self.assertEqual(len(where), 1, f"{attr}={k} : {where}")
        self.assertEqual(len(re.findall(r'name="mode" value="(ess|conf|all)"', out["menus"]["zones"])), 3)
        self.assertIn("data-flowreset", out["menus"]["flow"])
        self.assertIn('href="#/signals"', out["menus"]["ideas"])

    def test_groups_match_their_counters(self):
        out = run_js("return {dd: Panel.DD, modes: Panel.MODES};")
        self.assertEqual(out["dd"]["prof"], ["sess", "sessW", "sessM", "nodes", "dpoc", "npoc"])
        self.assertEqual(out["dd"]["tpo"], ["tpoM", "tpoW", "tpoD", "tpo4", "tpo1"])
        self.assertEqual(out["modes"], {"ess": "Essentiel", "conf": "Confluences", "all": "Tous"})

    def test_ideas_menu_lists_sent_ideas_with_their_state(self):
        out = run_js("""
            const trades = [{id: 'a', symbol: 'BTCUSDT', side: 'short', status: 'active', created: 1, entry: 100, stop: 101, hedgeOf: 'x'},
                            {id: 'b', symbol: 'BTCUSDT', side: 'long', status: 'closed', created: 2, entry: 90, stop: 89},
                            {id: 'c', symbol: 'SOLUSDT', side: 'long', status: 'active', created: 3, entry: 10, stop: 9},
                            {id: 'd', symbol: 'BTCUSDT', side: 'long', status: 'active', created: 4, entry: 95, stop: 94, mode: 'alerte'}];
            globalThis.LT = {st: {symbol: 'BTCUSDT', planOn: true, planHide: ['b'], plans: [], sig: {desk: {trades}}},
                             planVisible: t => t.id !== 'b', parisAt: t => 'T' + t, fmtP: v => String(v)};
            const p = Object.create(Panel.prototype), list = p.planList();
            LT.st.planOn = false; const off = p.planList();
            LT.st.planOn = true; LT.st.sig.desk.trades = []; const none = p.planList();
            return {list, off, none};""")
        lst = out["list"]
        self.assertEqual(re.findall(r'data-ptog="(\w)"', lst), ["a", "b"])                    # la paire affichée, sans les alertes
        self.assertIn('data-ptog="a" checked', lst)
        self.assertNotIn('data-ptog="b" checked', lst)
        self.assertIn("couverture", lst)
        self.assertIn("Réafficher l'idée masquée", lst)
        self.assertIn("masqués", out["off"])
        self.assertIn("Aucune idée envoyée sur BTC", out["none"])


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
        self.assertEqual(cfg["version"], "27")


if __name__ == "__main__":
    unittest.main()
