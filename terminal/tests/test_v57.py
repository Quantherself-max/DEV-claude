"""V57 : heatmap du carnet lisible. Palette sombre → bleu → cyan → jaune → orange → blanc pour les plus gros murs, fond caché sous un seuil
(contraste fort, normal ou doux), échelle de toute l'image ou de chaque instant, image deux fois plus fine, carte des liquidations atténuée
sous la heatmap, et les moments sans photo du carnet signalés au lieu d'un vide."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from data.heatbook import HeatBook

WEB = Path(__file__).resolve().parent.parent / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")


class CoverTest(unittest.TestCase):
    def test_columns_without_photo_are_flagged(self):
        b = HeatBook("BTCUSDT")
        t = 1_795_000_000_000
        for i in range(0, 30):                                  # photos de 0 à 5 minutes, puis rien pendant 5 minutes, puis de nouveau
            if 10 <= i < 20:
                continue
            b.add("binance", t + i * 30_000, [(59900.0, 20.0)], [(60100.0, 30.0)], mid=60000.0)
        q = b.query(t, t + 30 * 30_000, 59000.0, 61000.0, cols=30, rows=20)
        self.assertTrue(q["ready"])
        cov = q["cover"]
        self.assertEqual(len(cov), 30)
        self.assertIn("0", cov)
        self.assertTrue(cov.startswith("1"))
        self.assertTrue(cov.endswith("1"))


@unittest.skipUnless(shutil.which("node"), "node absent")
class PaletteTest(unittest.TestCase):
    def test_lut(self):
        d = read("desk.js")
        i, j = d.index("  const HEAT_PAL = ["), d.index("  const CMAP = heatLut('fort');")
        js = d[i:j] + "\nconst F = heatLut('fort'), N = heatLut('normal'), D = heatLut('doux'), a = (L, q) => L[q * 4 + 3], rgb = (L, q) => [L[q * 4], L[q * 4 + 1], L[q * 4 + 2]];\n" \
             "console.log(JSON.stringify({f60: a(F, 60), f90: a(F, 90), n60: a(N, 60), d10: a(D, 10), top: rgb(F, 255), topA: a(F, 255), zero: a(F, 0)}));"
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.js"
            f.write_text(js, encoding="utf-8")
            out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        r = json.loads(out.stdout)
        self.assertEqual(r["f60"], 0)                           # contraste fort : sous 10 % du 99e centile (octet < 81), transparent
        self.assertGreater(r["f90"], 0)
        self.assertGreater(r["n60"], 0)                         # contraste normal : visible dès 3,5 %
        self.assertGreater(r["d10"], 0)                         # doux : tout le carnet
        self.assertEqual(r["top"], [255, 255, 255])             # les plus gros murs : blancs
        self.assertEqual(r["topA"], 255)
        self.assertEqual(r["zero"], 0)


class PageTest(unittest.TestCase):
    def test_options_and_drawing(self):
        d, p = read("desk.js"), read("panels.js")
        for s in ("sel('heatContrast'", "sel('heatScale'", "heatContrast: ['fort', 'normal', 'doux'].includes(s.heatContrast) ? s.heatContrast : 'fort'",
                  "cmap: () => heatLut(st().mainOpts.heatContrast)", "if (scale === 'col')", "Math.min(600, Math.round(w / 2))", "Math.min(400, Math.round(h / 2))",
                  "'heatContrast', 'heatScale'].includes(t.dataset.copt)"):
            self.assertIn(s, d, s)
        for s in ("drawHeatGaps(L, h, H) {", "carnet non photographié (terminal éteint)", "this.drawHeatImage(L, h, st.liqMap, both ? 0.45 : 1)", "hctx.globalAlpha = alpha;"):
            self.assertIn(s, p, s)

    def test_syntax(self):
        if not shutil.which("node"):
            self.skipTest("node absent")
        for f in ("desk.js", "panels.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(WEB / f)]).returncode, 0, f)


if __name__ == "__main__":
    unittest.main()
