#!/usr/bin/env python3
"""Mesure ce que valent 25 indicateurs (en chaine, liquidite, macro / geopolitique, prix) sur le rendement futur du bitcoin, avec des jeux de donnees libres.

  python tools/run_indicators.py                 # telecharge (GitHub : Coin Metrics, datasets/*) dans data_local/opendata puis ecrit data_local/reports/indicators_BTC.json
  python tools/run_indicators.py --offline       # utilise les copies deja telechargees
  python tools/run_indicators.py --start 2014-01-01 --split 2021-01-01

Aucune cle, aucun compte : uniquement des fichiers CSV publics. Methode et seuils : engine/indstudy.py. Duree : quelques secondes."""
import argparse
import sys
import time
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.opendata import OpenData  # noqa: E402
from engine import backtest as bt, indstudy  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default=str(ROOT / "data_local" / "opendata"), help="dossier des CSV libres")
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"), help="dossier du rapport")
    ap.add_argument("--label", default="BTC")
    ap.add_argument("--start", default="2013-01-01")
    ap.add_argument("--split", default="2022-01-01", help="separation apprentissage / test")
    ap.add_argument("--offline", action="store_true", help="ne telecharge rien")
    ap.add_argument("--shifts", type=int, default=30, help="decalages au hasard par indicateur pour le temoin")
    a = ap.parse_args(argv)
    od = OpenData(a.folder, ttl_hours=0 if not a.offline else 10 ** 6)
    if not a.offline:
        print("Téléchargement des jeux libres…", flush=True)
        for k, v in od.refresh(force=True).items():
            print(f"  {k:7s} {v}", flush=True)
    if "btc" not in od.available():
        raise SystemExit("Pas de données Coin Metrics : lance sans --offline (accès à raw.githubusercontent.com nécessaire).")
    day = lambda s: bt.ms(*(int(x) for x in s.split("-")))
    last = max(t for t, _ in od.cm("btc", "PriceUSD"))
    t0 = time.time()
    rep = indstudy.run(od, a.label.upper(), day(a.start), last, day(a.split), shifts=a.shifts, progress=lambda m: print(f"  {m}  ({time.time() - t0:.0f} s)", flush=True))
    rep["source"] = ("Coin Metrics Community (github.com/coinmetrics/data, CC BY-NC 4.0) pour le BTC en chaîne et les stablecoins ; github.com/datasets pour le VIX, le pétrole, le gaz naturel "
                     "et les taux de change (indice dollar reconstruit). Prix du bitcoin : cours de référence Coin Metrics.")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"indicators_{a.label.upper()}.json"
    f.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print("\n" + rep["verdict"]["text"])
    for n in rep["verdict"]["notes"]:
        print(" -", n)
    print(f"\nRapport écrit : {f}  (page « Backtest » du terminal, menu « Rapport »)")


if __name__ == "__main__":
    main()
