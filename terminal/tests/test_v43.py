"""V43 : sous-fenêtres du graphique principal : l'échelle des prix reste automatique (les bougies ne passent plus sur l'intérêt ouvert, le delta,
le funding), l'échelle des prix est masquée à côté des sous-fenêtres, et chaque fenêtre a ses graduations, ses lignes haut / bas (ou les seuils
fixes du funding), son niveau et sa tendance sur 24 bougies."""
from __future__ import annotations
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANELS = (ROOT / "web" / "panels.js").read_text(encoding="utf-8")


class PaneGrid(unittest.TestCase):
    def test_price_scale_locked_with_panes(self):
        self.assertIn("lockPriceScale()", PANELS)
        self.assertIn("this.lockPriceScale();\n      this.applySeries(); this.syncVolume(L.d); this.syncSubcharts(L.d);", PANELS)
        self.assertIn("applyOptions({autoScale: true})", PANELS)
        self.assertIn("axisPressedMouseMove: {time: true, price: !lock}", PANELS)

    def test_axis_masked_and_values_in_axis_column(self):
        self.assertIn("ctx.fillRect(plotW, cb, w - plotW, H - cb)", PANELS)
        self.assertIn("ctx.fillText(txt, plotW + 5, y)", PANELS)

    def test_levels_and_readings(self):
        for s in ("'haut'", "'bas'", "'milieu'", "'stable'", "'en hausse'", "'en baisse'", "'forte hausse'", "'forte baisse'",
                  "txt: 'élevé'", "txt: 'normal'", "txt: 'négatif fort'", "txt: 'gros achats'", "txt: 'forte entrée'"):
            self.assertIn(s, PANELS, s)
        self.assertIn("static get GRID_N() { return 24; }", PANELS)
        self.assertIn("this.drawPaneGrid(G, y0, ph, rows.length, plotW, w)", PANELS)
        self.assertIn("plotW >= 760", PANELS)                                         # téléphone : niveau et tendance en deuxième ligne

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_syntax(self):
        self.assertEqual(subprocess.run(["node", "--check", str(ROOT / "web" / "panels.js")]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
