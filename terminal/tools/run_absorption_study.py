#!/usr/bin/env python3
"""Absorptions (delta fort CONTRE le sens de la bougie) : le prix va-t-il ensuite dans le sens de l'absorption, et le plus bas (plus haut)
de la bougie tient-il, face a des bougies semblables au flux ordinaire ? Mesure sur l'historique 1 minute de Binance (vrai volume acheteur
agressif), en bougies de 5 minutes, 15 minutes, 1 heure et 4 heures. Rapport affiche dans la page Backtest (« absorptions ») et utilise
par le terminal a cote des absorptions du graphique (il remplace la mesure que le terminal fait tout seul sur son historique 1 heure).

  python tools/fetch_history.py SOLUSDT          # une fois : historique 1 minute de SOL (Binance Vision, sans cle)
  python tools/run_absorption_study.py SOLUSDT   # une a quelques minutes

Aucune cle, aucun acces reseau. Refuse un historique au delta estime (Bitstamp) : une absorption n'a de sens qu'avec le vrai delta."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.reports import base_of  # noqa: E402
from engine import absorption, fine  # noqa: E402

TFS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", help="ex. SOLUSDT (dossier data_local/history/<SYMBOLE> cree par tools/fetch_history.py)")
    ap.add_argument("--folder", help="dossier avec b5m.bin ou b1m.bin et meta.json (defaut : data_local/history/<SYMBOLE>)")
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--tfs", default="5m,15m,1h,4h", help="unites de temps a mesurer, parmi 5m, 15m, 1h, 4h")
    a = ap.parse_args(argv)
    sym = a.symbol.upper()
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / sym
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if "binance" not in str(meta.get("source", "")).lower():
        raise SystemExit(f"Il faut l'historique Binance (vrai volume acheteur agressif) dans {folder}.\n"
                         f"Lance d'abord :  python tools/fetch_history.py {sym}")
    src = None
    for name in ("b5m", "b1m"):
        f = folder / f"{name}.bin"
        if f.exists():
            src = fine.Bars.load(f)
            break
    if src is None:
        raise SystemExit(f"Historique introuvable dans {folder} (b5m.bin ou b1m.bin). Lance :  python tools/fetch_history.py {sym}")
    t0 = time.time()
    tfs = {}
    for tf in [x.strip() for x in a.tfs.split(",") if x.strip()]:
        if tf not in TFS:
            raise SystemExit(f"Unite de temps inconnue : {tf} (5m, 15m, 1h, 4h)")
        t1 = time.time()
        bars = src if src.step == TFS[tf] else fine.resample(src, TFS[tf])
        tfs[tf] = absorption.study(bars)
        st = tfs[tf]
        print(f"  {tf} : {st.get('bars')} bougies, absorptions acheteuses {st.get('bull', {}).get('n')}, vendeuses {st.get('bear', {}).get('n')} "
              f"({time.time() - t1:.0f} s)", flush=True)
    label = base_of(sym)
    rep = absorption.report(label, tfs, meta.get("source", "Binance"), "outil", int(time.time() * 1000), round(time.time() - t0, 1))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"absorption_{label}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print(f"Rapport ecrit : {path}")
    for x in rep["summary"]:
        print(" -", x["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
