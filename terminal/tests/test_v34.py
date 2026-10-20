"""V34 : fusionner et déplier les profils TPO (comme sur Exocharts)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from config import Config
from engine import tpo as tpo_engine
from server import App

WEB = Path(__file__).resolve().parent.parent / "web"
TPO_JS = (WEB / "tpo.js").read_text(encoding="utf-8")


class PageTests(unittest.TestCase):
    def test_controls(self):
        for k in ('data-a="${act}"', "btn('merge'", "btn('split'", "btn('expand'", "btn('splitall'", 'data-tpo-o="expand"', "function items(", "function merge(", "function pick("):
            self.assertIn(k, TPO_JS)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("tpoGroups: st.tpoGroups", app)                                          # fusions gardées d'une ouverture à l'autre
        self.assertIn("expand: false", app)
        self.assertIn(".tpobtn", (WEB / "style.css").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("node"), "node absent : calcul de la fusion non vérifié")
class MergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Config(source="simulated", symbols=("BTCUSDT",), data_dir=tempfile.mkdtemp(), port=0), env_path=None)
        cls.app.service.refresh_all()

    def run_merge(self, mem, step, after, price):
        js = ("const Panel = {TH: {}}; " + TPO_JS + "\nconst a = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
              "process.stdout.write(JSON.stringify(TPO._merge(a.mem, a.step, a.after, a.price)));")
        out = subprocess.run(["node", "-e", js], input=json.dumps({"mem": mem, "step": step, "after": after, "price": price}),
                             capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout)

    def test_merge_matches_the_engine_composite(self):
        d = self.app.service.get_tpo("BTCUSDT", "D", 12)
        ss, step = d["sessions"], d["step"]
        done = [s for s in ss if not s["marks"]["current"]]
        mem = done[-5:-1]
        m = self.run_merge(mem, step, done[-1:], d["price"])
        ref = tpo_engine.composite(mem, step)                                                   # même calcul que le composite du moteur
        self.assertEqual(m["nMem"], 4)
        self.assertAlmostEqual(m["poc"], ref["poc"])
        self.assertAlmostEqual(m["vah"], ref["vah"])
        self.assertAlmostEqual(m["val"], ref["val"])
        self.assertEqual(sum(r[1] for r in m["rows"]), sum(r[1] for s in mem for r in s["rows"]))                 # toutes les lettres
        self.assertAlmostEqual(sum(r[3] for r in m["rows"]), sum(s["volume"] for s in mem), places=4)
        self.assertEqual((m["high"], m["low"]), (max(s["high"] for s in mem), min(s["low"] for s in mem)))
        self.assertEqual((m["open"], m["close"]), (mem[0]["open"], mem[-1]["close"]))
        # dépliée : une colonne par tranche, dans l'ordre, les séances à la suite
        self.assertEqual(m["cols"], sum(s["br"][-1][0] + 1 for s in mem))
        self.assertEqual([c[0] for c in m["br"]], sorted(c[0] for c in m["br"]))
        self.assertEqual(len(m["br"]), sum(len(s["br"]) for s in mem))
        for a, b in m["singles"]:                                                               # single prints : une seule tranche à ces prix
            for r in m["rows"]:
                if a - 1e-9 <= r[0] < b - 1e-9:
                    self.assertEqual(r[1], 1)

    def test_merge_including_the_live_session(self):
        d = self.app.service.get_tpo("BTCUSDT", "D", 12)
        mem = d["sessions"][-3:]
        m = self.run_merge(mem, d["step"], [], d["price"])
        self.assertTrue(m["marks"]["current"])
        self.assertFalse(m["marks"]["poc"]["naked"])


if __name__ == "__main__":
    unittest.main()
