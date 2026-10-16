import json
import shutil
import subprocess
import unittest
from pathlib import Path

from engine import context, risk

WEB = Path(__file__).resolve().parent.parent / "web"
P = risk.PropProfile()


@unittest.skipUnless(shutil.which("node"), "node absent : test de l'interface ignoré")
class ParseNumTests(unittest.TestCase):
    """`parseNum` (web/util.js) lit ce que l'utilisateur tape : un retrait « 1 000 » ne doit jamais devenir 1 $."""
    def run_js(self, inputs):
        script = ("const vm=require('vm'),fs=require('fs');const U=vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8')+';U',{Intl,localStorage:{}});"
                  "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(s=>{const n=U.parseNum(s);return Number.isNaN(n)?'NaN':n})))")
        r = subprocess.run(["node", "-e", script, str(WEB / "util.js"), json.dumps(inputs)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_french_and_english_formats(self):
        cases = {"1 000": 1000, "1 000": 1000, "1 000,5": 1000.5, "1,000": 1000, "1,5": 1.5, "0,500": 0.5, "25000.25": 25000.25, "25 000,25": 25000.25,
                 "1,234.56": 1234.56, "1.234,56": 1234.56, "1.234.567": 1234567, "1.5": 1.5, "-200": -200, "-1 200,5": -1200.5, " 500 ": 500, "500": 500}
        got = self.run_js(list(cases))
        for (k, want), g in zip(cases.items(), got):
            self.assertEqual(g, want, repr(k))

    def test_garbage_is_nan_not_a_truncated_number(self):
        bad = ["", "abc", "12abc", "1 000 $", "--5", "1,2,3", "1.2.3", "12e3", "Infinity", "NaN", ",", "."]
        self.assertEqual(self.run_js(bad), ["NaN"] * len(bad))


class RoundingTests(unittest.TestCase):
    def test_python_rounds_half_up_like_the_interface(self):
        self.assertEqual(context.fr(472.5, 0), "473")
        self.assertEqual(context.fr(262.5, 0), "263")
        self.assertEqual(context.fr(2.5, 0), "3")
        self.assertEqual(context.fr(-2.5, 0), "−3")
        self.assertEqual(context.fr(1234.567, 2), "1 234,57")
        self.assertEqual(context.fr(0.125, 2), "0,13")
        self.assertEqual(context.fr(25000, 0), "25 000")

    def test_a_payout_maximum_is_never_rounded_above_the_cap(self):
        days = [("2026-10-05", 211.46), ("2026-10-06", 211.46), ("2026-10-07", 211.46), ("2026-10-08", 211.46), ("2026-10-09", 211.46)]
        s = risk.state(days, 0, 0, P, "funded", [], "2026-10-12")            # profit 1 057,30 $ -> plafond 528,65 $
        po = s["payout"]
        self.assertEqual(po["cap"], 528.65)
        self.assertEqual(po["max"]["amount"], 528)                           # jamais 529 : la demande resterait au-dessus du plafond
        self.assertEqual(po["max"]["net"], 475.2)
        self.assertEqual(po["max"]["cushion"], 429.3)


if __name__ == "__main__":
    unittest.main()
