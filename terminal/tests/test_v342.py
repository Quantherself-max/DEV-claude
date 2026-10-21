"""V34.2 : le terminal tourne avec le Python livré avec macOS (3.9) : annotations différées partout, rien qui demande Python 3.10."""
from __future__ import annotations
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sources():
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts and p.parts[len(ROOT.parts)] not in ("data_local",)]


class Python39Tests(unittest.TestCase):
    def test_lazy_annotations_everywhere(self):
        missing = [str(p.relative_to(ROOT)) for p in sources() if p.read_text(encoding="utf-8").strip() and "from __future__ import annotations" not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [])                                          # « int | None » ne plante plus à l'import en 3.9

    def test_nothing_that_needs_python_310(self):
        bad = re.compile(r"bisect_(left|right)\([^)]*key=|insort\([^)]*key=|itertools\.pairwise|zip\([^)]*strict=|^\s*match \S.*:\s*$|ignore_cleanup_errors=True\)|slots=True")
        hits = [f"{p.relative_to(ROOT)}:{i}" for p in sources() if p.name != "test_v342.py" for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if bad.search(line)]
        self.assertEqual(hits, [])

    def test_mac_launcher(self):
        sh = (ROOT / "Lancer-Terminal-Mac.command").read_text(encoding="utf-8")
        self.assertIn("sys.version_info >= (3, 9)", sh)                         # cherche un Python utilisable, pas seulement « python3 »
        self.assertIn("/opt/homebrew/bin/python3", sh)
        self.assertIn("Python.framework", sh)
        self.assertEqual(subprocess.run(["bash", "-n", str(ROOT / "Lancer-Terminal-Mac.command")]).returncode, 0)
        run = (ROOT / "run.py").read_text(encoding="utf-8")
        self.assertIn("def mac_certificates(", run)
        self.assertIn("SSL_CERT_FILE", run)


if __name__ == "__main__":
    unittest.main()
