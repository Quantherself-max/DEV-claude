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
    def test_price_scale_free_since_v53(self):
        # V53 : les sous-fenêtres ont leurs propres graphiques : l'échelle des prix n'est plus bloquée en automatique
        self.assertNotIn("lockPriceScale", PANELS)
        self.assertNotIn("price: !lock", PANELS)
        self.assertIn("this.applySeries(); this.syncVolume(L.d); this.syncSubcharts(L.d);", PANELS)
        self.assertIn("applyOptions({autoScale: true})", PANELS)                     # bouton « A » et retour à la vue de départ

    def test_values_on_each_window_scale(self):
        # V53 : repères en lignes de prix, avec leur valeur sur l'échelle de la fenêtre (avant : dessinés à la main dans la colonne de l'échelle)
        self.assertIn("axisLabelVisible: true, title: l.txt", PANELS)
        self.assertIn("static subFmt(pk, v)", PANELS)

    def test_levels_and_readings(self):
        for s in ("'haut'", "'bas'", "'milieu'", "'stable'", "'en hausse'", "'en baisse'", "'forte hausse'", "'forte baisse'",
                  "txt: 'élevé'", "txt: 'normal'", "txt: 'négatif fort'", "txt: 'gros achats'", "txt: 'forte entrée'"):
            self.assertIn(s, PANELS, s)
        self.assertIn("static get GRID_N() { return 24; }", PANELS)
        self.assertIn("this.subLevels(pk, panes.includes(pk) ? this.paneGrid(pk, I, L, ok, 'L') : null)", PANELS)
        self.assertIn("plotW >= 760", PANELS)                                         # téléphone : niveau et tendance en deuxième ligne

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_syntax(self):
        self.assertEqual(subprocess.run(["node", "--check", str(ROOT / "web" / "panels.js")]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
