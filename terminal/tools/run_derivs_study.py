#!/usr/bin/env python3
"""Mesure ce que valent le financement multi-bourses, l'Open Interest, les options (put / call, max pain, DVOL) et la base des futures sur le prix futur.

  python tools/run_derivs_study.py SOLUSDT

Ces donnees n'ont pas d'historique libre : le terminal les enregistre toutes les 15 minutes (data_local/history/derivs/<PAIRE>.csv) tant qu'il tourne.
Laisse-le tourner 3 a 4 semaines au moins. Les cours horaires viennent de l'API publique de Binance (internet requis). Methode : engine/derivstudy.py."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.external import RealProviders  # noqa: E402
from engine import derivstudy  # noqa: E402

HOUR = 3_600_000


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", help="ex. SOLUSDT")
    ap.add_argument("--folder", default=str(ROOT / "data_local" / "history" / "derivs"))
    a = ap.parse_args(argv)
    f = Path(a.folder) / f"{a.symbol.upper()}.csv"
    if not f.exists():
        raise SystemExit(f"Aucun enregistrement : {f}. Lance le terminal (source Binance) et laisse-le tourner quelques semaines.")
    recs = derivstudy.read_records(f)
    print(f"{len(recs)} enregistrements ({(recs[-1]['t'] - recs[0]['t']) / 86_400_000:.1f} jours).")
    p = RealProviders()
    closes, end = [], recs[-1]["t"] + 3 * HOUR
    start = recs[0]["t"] - HOUR
    t = start
    while t < end:
        page = p.spot_klines(a.symbol.upper(), 1000, "1h", min(end, t + 1000 * HOUR))
        if not page:
            break
        closes += page
        t = page[-1][0] + HOUR
    closes = [(ts, c) for ts, c in dict(closes).items()]
    rep = derivstudy.run(recs, closes, a.symbol.upper())
    if not rep["usable"]:
        raise SystemExit(rep["reason"])
    nul = rep["null"]
    print(f"Seuil du hasard : |t| ≥ {rep['threshold']:.1f} (témoin : 95 % à {nul['p95']:.1f}).\n")
    for r in rep["rows"]:
        cells = []
        for h in rep["horizons"]:
            d = r["h"][str(h)]
            cells.append(f"{h} h : " + (f"écart {d['all']['spread'] * 100:+.2f} % (t {d['all']['t']:+.1f})" if d["all"] else "-"))
        print(f"{r['level']:11s} {r['title'][:46]:46s} " + " | ".join(cells))


if __name__ == "__main__":
    main()
