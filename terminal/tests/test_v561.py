"""V56.1 : les niveaux gamma (et tout ce qui est dessiné par-dessus les bougies) avaient disparu de l'onglet Option. Depuis la V55,
l'échelle du temps des bougies est masquée quand des fenêtres sont dessous (elle passe sous la dernière) ; la bibliothèque graphique
rend alors une largeur nulle pour l'échelle du temps, et le dessin s'en servait comme largeur de la zone des bougies : les lignes gamma
s'arrêtaient à 200 pixels, cachées sous leurs étiquettes, les barres de gamma étaient écrasées. La largeur se mesure maintenant sans elle."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")


class PlotWidthTest(unittest.TestCase):
    def test_no_plot_width_from_the_time_scale(self):
        p = read("panels.js")
        self.assertIn("  plotWidth() {", p)
        self.assertIn("const plotW = this.plotWidth();", p)                    # layout() : la base de tous les dessins
        self.assertIn("const plotW = this.plotWidth() || Math.max(300, this.body.clientWidth - 70)", p)
        body = p[p.index("class Panel"):]
        uses = [m.start() for m in re.finditer(r"timeScale\(\)\.width\(\)|\bts\.width\(\)", body)]
        self.assertEqual(len(uses), 1, "la largeur de l'échelle du temps n'est lue que dans plotWidth()")
        self.assertIn("p.plotWidth ? p.plotWidth() : ts.width()", read("desk.js"))

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_fallbacks(self):
        js = ("const LT = {serverNow: () => 0, st: {mainOpts: {}}};\n" + read("panels.js") + "\n"
              "const mk = (ts, pane, ps) => Object.assign(Object.create(Panel.prototype), {body: {clientWidth: 1300},\n"
              "  chart: {timeScale: () => ({width: () => ts}), paneSize: pane == null ? undefined : () => ({width: pane, height: 300}), priceScale: () => ({width: () => ps})}});\n"
              "console.log(JSON.stringify([mk(1200, 1190, 80).plotWidth(), mk(0, 1190, 80).plotWidth(), mk(0, null, 80).plotWidth(), mk(0, 0, 80).plotWidth()]));")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.js"
            f.write_text(js, encoding="utf-8")
            out = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertEqual(json.loads(out.stdout), [1200, 1190, 1220, 1220])      # échelle du temps masquée : la zone du graphique, sinon le corps moins l'échelle des prix


if __name__ == "__main__":
    unittest.main()
