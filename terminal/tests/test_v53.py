"""V53 : les fenêtres sous le graphique principal (intérêt ouvert, delta et CVD, funding, flux par taille spot et perpétuel) ont chacune
leur graphique (web/panes.js) : le graphique des prix se manie librement, chaque fenêtre a sa barre (réglages, rang, lecture, réduire,
retirer), sa poignée de hauteur et sa propre échelle ; menu « ▤ Fenêtres » ; échelle automatique limitée à ce qui est affiché."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
read = lambda name: (WEB / name).read_text(encoding="utf-8")


def node(js: str) -> str:
    with tempfile.TemporaryDirectory() as d:                      # les fichiers dépassent la taille d'un argument de ligne de commande
        f = Path(d) / "t.js"
        f.write_text(js, encoding="utf-8")
        out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr[-1500:])
    return out.stdout


class PageTest(unittest.TestCase):
    def test_files_and_order(self):
        html = read("index.html")
        self.assertIn('<script src="panes.js"></script>\n<script src="panels.js"></script>', html)   # la pile avant le panneau qui l'utilise
        panes = read("panes.js")
        for s in ("class PaneStack", "attributionLogo: false", "setCrosshairPosition", "subscribeVisibleLogicalRangeChange", "minimumWidth",
                  "static touched(w)", "data-pa=\"opts\"", "data-pa=\"up\"", "data-pa=\"down\"", "data-pa=\"read\"", "data-pa=\"min\"", "data-pa=\"x\"",
                  "Desk.paneAct(null, 'resetH')", "Desk.paneAct(null, 'h', this.tmp)", "sep.className = 'psep'"):
            self.assertIn(s, panes, s)

    def test_panels_use_their_own_windows(self):
        p = read("panels.js")
        self.assertIn("this.stack = new PaneStack(this)", p)
        self.assertIn("S.sync(panes);", p)
        self.assertIn("this.headPanes(L)", p)
        self.assertNotIn("drawPanes", p)
        self.assertNotIn("paneP()", p)
        self.assertIn("candleBottom(h) { return Math.max(40, h - (this.axisOff ? 2 : 26)); }", p)   # V55 : l'échelle du temps peut être sous la dernière fenêtre
        for s in ("data-nav=\"out\"", "data-nav=\"in\"", "data-nav=\"left\"", "data-nav=\"right\"", "data-nav=\"auto\"", "data-nav=\"reset\"", "data-winbtn"):
            self.assertIn(s, p, s)
        # échelle automatique : une poche masquée ou une idée masquée n'écrase plus les bougies
        self.assertIn("(st.pools ? LT.shownPools(d).map(x => x.p.price) : [])", p)
        self.assertIn("if (st.planOn) (st.plans || [])", p)

    def test_desk_and_css(self):
        d = read("desk.js")
        for s in ("function paneCfg()", "function setPane(k, on)", "function paneAct(k, a, val)", "function paneOpts(k, btn)", "function toggleWin(btn)",
                  "paneCfg, paneShown, setPane, paneAct, paneOpts, toggleWin", "[data-elbtn],[data-winbtn]", "Fenêtres sous le graphique"):
            self.assertIn(s, d, s)
        css = read("style.css")
        for s in (".psubs{", ".psep{", ".pwin{", ".pwin.min .pchart{display:none}", ".pbody .pnav{", ".ddrow.flash"):
            self.assertIn(s, css, s)

    def test_version(self):
        srv = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(int(re.search(r'VERSION = "(\d+)"', srv).group(1)), 53)
        self.assertGreaterEqual(int(re.search(r"NEED_API = (\d+)", read("app.js")).group(1)), 53)
        self.assertIn("V53", (ROOT / "README.md").read_text(encoding="utf-8"))


class ResilienceTest(unittest.TestCase):
    """V53.1 : une erreur dans la page ne fige plus le terminal (« chargement sans fin ») : elle est affichée et le reste continue."""
    def test_loop_never_stops(self):
        app = read("app.js")
        i = app.index("function loop() {")
        body = app[i:app.index("\n}", i)]
        self.assertLess(body.index("requestAnimationFrame(loop);"), body.index("p.tick()"))   # la prochaine image est demandée AVANT le dessin
        self.assertIn("try { p.tick(); } catch (e) { showErr(e, 'graphique ' + p.kind); }", body)
        for s in ("function showErr(e, where)", "window.addEventListener('error'", "window.addEventListener('unhandledrejection'", "Erreur dans la page du terminal",
                  "const step = (name, fn) =>", "step('graphiques', () => createPanels());", "setTf, showErr};"):
            self.assertIn(s, app, s)
        self.assertIn(".jserr{", read("style.css"))

    def test_panes_cannot_block_the_chart(self):
        p = read("panels.js")
        for s in ("safePanes(fn) {", "this.safePanes(() => this.syncSubcharts(L.d));", "this.safePanes(() => this.headPanes(L));",
                  "this.paneErr >= 3", "[?&]secours", "this.safePanes(() => this.stack.tick())"):
            self.assertIn(s, p, s)
        panes = read("panes.js")
        self.assertEqual(panes.count("} catch (e) { this.err(e); } finally {"), 5)   # rappels de la bibliothèque graphique protégés


@unittest.skipUnless(shutil.which("node"), "node absent")
class LogicTest(unittest.TestCase):
    def test_axis_formats_and_heights(self):
        js = ("const LT = {serverNow: () => 0, st: {mainOpts: {}}};\n" + read("panels.js") + "\n" + read("panes.js") + "\n"
              "const o = LT.st.mainOpts, r = [];\n"
              "r.push(Panel.subFmt('oi', 94000), Panel.subFmt('fund', 0.0021), Panel.subFmt('delta', -1500), Panel.subFmt('szs', 2.5e6));\n"
              "o.fundMode = 'an'; o.deltaUnit = 'usd'; o.oiMode = 'chg';\n"
              "r.push(Panel.subFmt('fund', 2.3), Panel.subFmt('delta', 1.2e6), Panel.subFmt('oi', -450));\n"
              "r.push([1, 2, 3, 5].map(n => PaneStack.defH(n)));\n"
              "r.push(PaneStack.same({from: 1, to: 2}, {from: 1.00001, to: 2}), PaneStack.same({from: 1, to: 2}, {from: 1.5, to: 2}));\n"
              "r.push(PaneStack.touched({down: true}), PaneStack.touched({act: Date.now()}), PaneStack.touched({act: Date.now() - 5000}));\n"
              "console.log(JSON.stringify(r));")
        r = json.loads(node(js))
        self.assertEqual(r[:4], ["94 k", "+0,0021 %", "−1,5 k", "+2,5 M $"])
        self.assertEqual(r[4:7], ["+2,3 %", "+1,2 M $", "−450"])
        for a, b in zip(r[7], [0.2, 0.2, 0.2, 0.132]):                   # V55 : même hauteur pour toutes ; cinq fenêtres : les bougies gardent un tiers
            self.assertAlmostEqual(a, b)
        self.assertEqual(r[8:10], [True, False])
        self.assertEqual(r[10:13], [True, True, False])                  # une fenêtre ne mène le zoom que si on vient de la toucher

    def test_add_remove_order_and_saved_settings(self):
        js = ("globalThis.setTimeout = () => 0; globalThis.clearTimeout = () => {}; let saved = 0;\n"
              "const set = {v55: 1, els: {oi: true}, sizeMkt: 'both', paneH: {oi: 0.3, bad: 0.2, fund: 5}, paneOrder: ['fund', 'x', 'oi', 'fund'], paneRead: {oi: 1, delta: 7}};\n"
              "const LT = {st: {layout: 'u1', utabs: [{id: 'u1', name: 'Option', set}], mainOpts: {}, symbol: 'BTCUSDT', ws: {}}, savePrefs: () => { saved++; },\n"
              "  syncAllTools() {}, refreshAll() {}, updatePlan() {}, pollFlow() {}, api: () => new Promise(() => {}), panels: () => [main]};\n"
              "const main = {kind: 'main', host: {querySelector: () => null}, panes: () => Desk.paneCfg().order.length ? ['oi', 'delta', 'fund'].sort((a, b) => Desk.paneCfg().order.indexOf(a) - Desk.paneCfg().order.indexOf(b)) : ['oi', 'delta', 'fund'],\n"
              "  stack: {layout() {}}, sig: 'x'};\n"
              + read("desk.js") + "\n")
        # Desk lit LT par init() : on l'injecte sans câbler la page
        js = js.replace("const Desk = (() => {\n  'use strict';\n  let LT = null,", "const Desk = (() => {\n  'use strict';\n  let LT = globalThis.LTX,")
        js = js.replace("const LT = {st:", "globalThis.LTX = {st:", 1).replace("panels: () => [main]};", "panels: () => [main]};\nconst LT = globalThis.LTX;", 1)
        js += ("const out = [];\n"
               "out.push(Desk.paneCfg());\n"
               "Desk.setPane('szs', true); out.push([set.els.sizes, set.sizeMkt]);\n"
               "Desk.setPane('szp', true); out.push(set.sizeMkt);\n"
               "Desk.setPane('szs', false); out.push(set.sizeMkt);\n"
               "Desk.setPane('szp', false); out.push('sizes' in set.els);\n"
               "Desk.setPane('delta', true); Desk.setPane('fund', true);\n"
               "Desk.paneAct('oi', 'min'); Desk.paneAct('delta', 'read'); Desk.paneAct('delta', 'read'); Desk.paneAct('delta', 'read');\n"
               "out.push([set.paneMin, set.paneRead]);\n"
               "Desk.paneAct(null, 'h', {delta: 0.25}); out.push(set.paneH);\n"
               "Desk.paneAct('oi', 'x'); out.push('oi' in set.els);\n"
               "Desk.paneAct(null, 'resetAll'); out.push([['paneH', 'paneMin', 'paneOrder', 'paneRead'].filter(k => k in set), saved > 0]);\n"
               "console.log(JSON.stringify(out));")
        r = json.loads(node(js))
        self.assertEqual(r[0], {"order": ["fund", "oi"], "h": {"oi": 0.3}, "min": {}, "read": {"oi": 1}})   # valeurs inconnues ou absurdes écartées
        self.assertEqual(r[1], [True, "spot"])
        self.assertEqual(r[2], "both")
        self.assertEqual(r[3], "perp")
        self.assertFalse(r[4])                                           # les deux fenêtres retirées : l'élément quitte la légende
        self.assertEqual(r[5], [{"oi": True}, {"oi": 1, "delta": 1}])   # V55 : 1 (d'origine) → 0 → 2 → 1
        self.assertEqual(r[6], {"oi": 0.3, "delta": 0.25})
        self.assertFalse(r[7])
        self.assertEqual(r[8], [[], True])


@unittest.skipUnless(shutil.which("node"), "node absent")
class DeltaPowerTest(unittest.TestCase):
    """V53.2 : force de chaque barre du delta (comparée à la normale des 100 bougies d'avant), barres et CVD qui s'ajoutent ou se retirent."""
    def test_power_levels(self):
        js = ("const LT = {serverNow: () => 0, st: {mainOpts: {}}};\n" + read("panels.js") + "\n"
              "const V = []; for (let i = 0; i < 60; i++) V.push(i % 2 ? -100 : 100);\n"
              "V.push(30, 150, 300, -450, null, 1000);\n"
              "const p = Panel.deltaPower(V);\n"
              "console.log(JSON.stringify({early: p.r[10], med: p.med[60], r: p.r.slice(60), lv: p.r.slice(60).map(Panel.powerLevel), txt: Panel.POWER_TXT}));")
        r = json.loads(node(js))
        self.assertIsNone(r["early"])                                    # moins de 20 bougies d'avant : pas de normale
        self.assertEqual(r["med"], 100)
        self.assertEqual(r["r"][:4], [0.3, 1.5, 3, 4.5])
        self.assertIsNone(r["r"][4])                                     # bougie sans delta
        self.assertEqual(r["lv"][:4], [0, 1, 2, 3])
        self.assertEqual(r["lv"][5], 3)
        self.assertEqual(r["txt"], ["faible", "normal", "fort", "très fort"])

    def test_page_strings(self):
        p, panes, desk = read("panels.js"), read("panes.js"), read("desk.js")
        for x in ("static deltaPower(V, N = 100)", "S.zones('delta', {});", "['dT4p', 'très fort'", "Panel.VERY_UP", "% du volume",
                  "la normale", "achat fort", "want.dS && o.deltaThr === true"):
            self.assertIn(x, p, x)
        for x in ("zones(k, z)", "h < 150 ? 1 : 2", "autoScale: true"):
            self.assertIn(x, panes, x)
        for x in ('data-pa="bars"', 'data-pa="line"'):                    # V55 : le CVD a sa propre fenêtre, plus de boutons Barres / CVD
            self.assertNotIn(x, panes, x)
        for x in ("sel('deltaThr'", "deltaThr: s.deltaThr === true", "sel('cvdMode'"):
            self.assertIn(x, desk, x)
        self.assertNotIn("a === 'bars' || a === 'line'", desk)

    def test_cvd_moves_to_its_own_pane(self):
        """V55 : un onglet qui avait le delta et son CVD passe une fois à la disposition à fenêtres séparées (le CVD garde son réglage)."""
        js = ("globalThis.setTimeout = () => 0; globalThis.clearTimeout = () => {};\n"
              "const set = {els: {delta: true, fund: true}, cvdMode: 'perp', paneH: {delta: 0.4}, deltaBars: false};\n"
              "globalThis.LTX = {st: {layout: 'u1', utabs: [{id: 'u1', name: 'Option', set}], mainOpts: {}, symbol: 'BTCUSDT', ws: {}}, savePrefs() {}, syncAllTools() {}, refreshAll() {},\n"
              "  updatePlan() {}, pollFlow() {}, api: () => new Promise(() => {}), panels: () => []};\n"
              + read("desk.js").replace("let LT = null,", "let LT = globalThis.LTX,") + "\n"
              "const out = [];\n"
              "Desk.apply(); const e = set.els;\n"
              "out.push([e.delta, e.dspot, e.cvd, e.oi, e.liq, e.fund, set.cvdMode, set.paneOrder, 'paneH' in set, 'deltaBars' in set, set.v55]);\n"
              "e.cvd = false; set.paneOrder = ['oi']; Desk.apply(); out.push([e.cvd, set.paneOrder, LTX.st.mainOpts.cvdMode, LTX.st.mainOpts.oiColor]);\n"   # une seule fois
              "console.log(JSON.stringify(out));")
        r = json.loads(node(js))
        self.assertEqual(r[0], [True, True, True, True, True, False, "perp", ["delta", "dspot", "cvd", "oi", "liq"], False, False, 1])
        self.assertEqual(r[1], [False, ["oi"], "perp", "dir"])


if __name__ == "__main__":
    unittest.main()
