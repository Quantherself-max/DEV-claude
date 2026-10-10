#!/usr/bin/env python3
"""Ou est l'argent ? Parts du bitcoin, de l'ETH, des altcoins et des stablecoins, rotation du capital, or (PAXG) et asymetrie bitcoin / or, mesures sur le prix futur.

  python tools/run_rotation.py                 # telecharge les jeux libres (GitHub : Coin Metrics) puis ecrit data_local/reports/rotation_BTC.json
  python tools/run_rotation.py --offline       # copies deja telechargees
  python tools/run_rotation.py --start 2020-07-01 --split 2023-01-01

Donnees : capitalisations estimees quotidiennes depuis juin 2019 (BTC, ETH, 10 altcoins, SOL), offre de stablecoins, or tokenise PAXG depuis fevrier 2020. Aucune cle."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.opendata import OpenData  # noqa: E402
from engine import backtest as bt, rotationstudy  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default=str(ROOT / "data_local" / "opendata"))
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--label", default="BTC")
    ap.add_argument("--start", default="2020-07-01", help="premier jour evalue (un an d'historique est necessaire avant)")
    ap.add_argument("--split", default="2023-01-01", help="separation apprentissage / test")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--shifts", type=int, default=30)
    a = ap.parse_args(argv)
    od = OpenData(a.folder, ttl_hours=10 ** 6 if a.offline else 0)
    if not a.offline:
        print("Téléchargement des jeux libres…", flush=True)
        for k, v in od.refresh(force=True).items():
            print(f"  {k:7s} {v}", flush=True)
    if "btc" not in od.available() or "paxg" not in od.available():
        raise SystemExit("Données Coin Metrics (btc, paxg…) absentes : lance sans --offline (accès à raw.githubusercontent.com nécessaire).")
    day = lambda s: bt.ms(*(int(x) for x in s.split("-")))
    last = max(t for t, _ in od.cm("btc", "PriceUSD"))
    t0 = time.time()
    rep = rotationstudy.run(od, a.label.upper(), day(a.start), last, day(a.split), shifts=a.shifts, progress=lambda m: print(f"  {m} ({time.time() - t0:.0f} s)", flush=True))
    rep["source"] = ("Coin Metrics Community (github.com/coinmetrics/data, CC BY-NC 4.0) : capitalisations estimées de BTC, ETH, SOL et de 10 altcoins, offre de stablecoins (USDT, USDC, DAI), "
                     "or tokenisé PAXG (1 jeton = 1 once, coté 24 h / 24).")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"rotation_{a.label.upper()}.json"
    f.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print("\n" + rep["verdict"]["text"])
    for n in rep["verdict"]["notes"]:
        print(" -", n)
    print(f"\nRapport écrit : {f}  (page « Backtest » du terminal, menu « Rapport »)")


if __name__ == "__main__":
    main()
