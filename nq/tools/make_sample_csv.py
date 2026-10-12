#!/usr/bin/env python3
"""Ecrit un fichier de transactions SIMULEES au format que le terminal sait lire (voir README, « Brancher de vraies données »).

Sert a essayer la source fichier sans attendre un export de ta plateforme, et d'exemple de format :

  python tools/make_sample_csv.py ticks.csv                  heure,prix,quantite,cote  (delta REEL)
  python tools/make_sample_csv.py ticks.csv --no-side        sans le cote de l'agresseur (delta ESTIME par la regle du tick)
  python tools/make_sample_csv.py ticks.csv --days 2 --iso   heures au format ISO 8601 au lieu de millisecondes

Puis :  python run.py --source csv --csv ticks.csv"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.simulated import SimulatedSource  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--no-side", action="store_true")
    ap.add_argument("--iso", action="store_true")
    a = ap.parse_args()
    now = int(time.time() * 1000)
    ticks = SimulatedSource(days=max(2, a.days), now_fn=lambda: now).history(now)
    head = "time,price,size" + ("" if a.no_side else ",side")
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + "\n")
        for t in ticks:
            when = datetime.fromtimestamp(t.t / 1000.0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if a.iso else str(t.t)
            f.write(f"{when},{t.p},{t.q}" + ("" if a.no_side else f",{'B' if t.side > 0 else 'S'}") + "\n")
    print(f"{len(ticks)} transactions écrites dans {a.out} ({'sans' if a.no_side else 'avec'} le côté de l'agresseur).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
