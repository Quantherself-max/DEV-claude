"""V24.1 : gros ordres agressifs et absorptions lisibles. Logique de regroupement des bulles (web/panels.js), executee avec Node
quand il est installe (sinon ces tests sont sautes : le reste du terminal n'a pas besoin de Node)."""
from __future__ import annotations
import json
import shutil
import subprocess
import unittest
from pathlib import Path

PANELS = Path(__file__).resolve().parent.parent / "web" / "panels.js"


def run_js(body: str):
    """Charge panels.js (classes seulement) et execute `body`, qui renvoie une valeur JSON."""
    script = ("const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8');\n"
              "const {Panel, FlowUnder} = new Function(src + '\\nreturn {Panel, FlowUnder};')();\n"
              f"const out = (() => {{ {body} }})();\nprocess.stdout.write(JSON.stringify(out));")
    r = subprocess.run(["node", "-e", script, str(PANELS)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "Node n'est pas installé")
class BubbleTests(unittest.TestCase):
    def test_orders_of_a_candle_side_and_price_are_added_with_their_price_range(self):
        out = run_js("""
            const big = [{t: 1000, price: 100.00, qty: 1, usd: 600, side: 'sell'}, {t: 2000, price: 100.004, qty: 2, usd: 900, side: 'sell'},
                         {t: 1500, price: 100.01, qty: 1, usd: 700, side: 'buy'}, {t: 400000, price: 100.0, qty: 1, usd: 800, side: 'sell'},
                         {t: 3000, price: 101.0, qty: 1, usd: 100, side: 'sell'}];
            return Panel.clusterBig(big, 300000, 500).sort((a, b) => a.side.localeCompare(b.side) || a.bt - b.bt);""")
        self.assertEqual([(g["side"], g["bt"], g["n"]) for g in out], [("buy", 0, 1), ("sell", 0, 2), ("sell", 300000, 1)])
        s = out[1]
        self.assertEqual((s["usd"], s["lo"], s["hi"], s["t"], s["t1"]), (1500, 100.0, 100.004, 1000, 2000))   # meme case de 0,05 % (grille fixe)
        self.assertAlmostEqual(s["price"], (100.0 * 600 + 100.004 * 900) / 1500)

    def test_overlapping_bubbles_merge_only_within_the_same_candle_and_side(self):
        out = run_js("""
            const r = u => Panel.bubbleR(u, 1e6);
            const p = (side, bt, y, usd, price) => ({side, bt, y, usd, price, qty: usd / price, n: 1, t: bt, t1: bt, lo: price, hi: price, r: r(usd)});
            const pts = [p('sell', 0, 100, 4e6, 85000), p('sell', 0, 104, 2e6, 84990), p('sell', 0, 160, 3e6, 84800),
                         p('buy', 0, 102, 5e6, 84995), p('sell', 300, 101, 2e6, 84997)];
            return Panel.mergeBubbles(pts, 1e6).map(b => [b.side, b.bt, b.n, b.usd, Math.round(b.y), b.lo, b.hi, !!b.merged]).sort();""")
        self.assertEqual(out, sorted([["sell", 0, 2, 6e6, 101, 84990, 85000, True], ["sell", 0, 1, 3e6, 160, 84800, 84800, False],
                                      ["buy", 0, 1, 5e6, 102, 84995, 84995, False], ["sell", 300, 1, 2e6, 101, 84997, 84997, False]]))

    def test_bubble_size_grows_with_the_amount_and_stays_bounded(self):
        rs = run_js("return [0.5e6, 1e6, 2e6, 4e6, 8e6, 1e9].map(u => Panel.bubbleR(u, 1e6));")
        self.assertEqual(rs[0], rs[1])                                         # jamais plus petit que le minimum
        self.assertTrue(all(a < b for a, b in zip(rs[1:5], rs[2:5])))
        self.assertEqual(rs[-1], 10)                                           # plafond : une bulle ne mange pas le graphique
        self.assertEqual(run_js("return Panel.LABELS;"), {"top": 3, "all": 1e9, "none": 0})

    def test_under_layer_only_redraws_when_bubbles_change(self):
        out = run_js("""
            const u = new FlowUnder(); let n = 0;
            u.attached({chart: {}, series: {}, requestUpdate: () => { n += 1; }});
            const b = [{time: 1, price: 100, r: 4, dx: 3, c: [0, 0, 0], fa: 0.6, sa: 1, lw: 1.5}];
            u.set(b); u.set(b.map(x => ({...x}))); u.set([]);
            return {n, zOrder: u.paneViews()[0].zOrder(), items: u.items.length};""")
        self.assertEqual(out, {"n": 2, "zOrder": "bottom", "items": 0})       # dessinee SOUS les bougies


if __name__ == "__main__":
    unittest.main()
