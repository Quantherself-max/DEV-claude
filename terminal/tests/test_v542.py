"""V54.2 : un fichier de la page qui n'arrive pas ou qui plante au chargement (onglet Quant noir, « QUANTV is not defined ») est redemandé
une fois ; s'il manque toujours, l'onglet le dit, et l'encadré rouge donne la cause exacte (fichier, ligne) grâce à un capteur posé avant
tous les fichiers de la page."""
from __future__ import annotations
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
read = lambda n: (WEB / n).read_text(encoding="utf-8")


class LoadGuardTest(unittest.TestCase):
    def test_early_capture_before_every_script(self):
        html = read("index.html")
        i, j = html.index("window.__early = [];"), html.index('<script src="vendor/lightweight-charts.standalone.production.js"></script>')
        self.assertLess(i, j)                                                      # avant tous les fichiers de la page
        self.assertIn("t.tagName === 'SCRIPT'", html)                               # fichier non reçu
        self.assertIn("e.lineno", html)                                             # erreur avec sa ligne

    def test_reload_and_guards(self):
        app = read("app.js")
        for s in ("function hasMod(name)", "function modMissing(tab, file)", "async function loadMissing()", "await loadMissing();",
                  "if (hasMod('QUANTV')) QUANTV.init(window.LT, qg); else qg.innerHTML = modMissing('Quant', 'quant.js');",
                  "if (hasMod('GEXV')) GEXV.init(window.LT, gg); else gg.innerHTML = modMissing('GEX', 'gex.js');",
                  "(window.__early || []).forEach(", "Ctrl + F5", "Cmd + Maj + R"):
            self.assertIn(s, app, s)
        for line in app.splitlines():                                               # plus aucun appel non protégé
            if "QUANTV." in line and "hasMod('QUANTV')" not in line and "QUANTV.init(window.LT, qg)" not in line:
                self.fail("appel non protégé : " + line.strip()[:120])
        self.assertIn("var QUANTV = (() => {", read("quant.js"))                    # rechargeable : une seconde exécution reste possible
        self.assertIn("var GEXV = (() => {", read("gex.js"))
        self.assertIn("Array.isArray(a) ? a : []", read("quant.js"))

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_syntax(self):
        for f in ("app.js", "quant.js", "gex.js"):
            self.assertEqual(subprocess.run(["node", "--check", str(WEB / f)]).returncode, 0, f)


if __name__ == "__main__":
    unittest.main()
