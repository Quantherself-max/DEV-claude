#!/usr/bin/env python3
"""Backtest des VWAP ANCRES sur un mouvement precedent d'au moins 5 % (sommet de la baisse, creux) : comment le prix reagit-il, et peut-on le trader ?

  python tools/run_avwap_swing.py SOLUSDT            # utilise data_local/history/SOLUSDT (voir tools/fetch_history.py)
  python tools/run_avwap_swing.py --folder mon_dossier --label MONACTIF --workers 4

Etape 1 : reaction du prix apres chaque contact (4 / 24 / 48 h, probabilite d'aller d'abord d'1 ATR), pour des mouvements de 5, 8 et 12 %.
Etape 2 : trades (12 sorties, 26 filtres, deux sens), protocole de engine/stratstudy.py : apprentissage / test, temoin au hasard.
Resultat : data_local/reports/avwap_<ACTIF>.json, affiche dans la page « Backtest » (liste « Rapport »). Duree : de 5 a 20 minutes ; memoire : 2 a 4 Go."""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from engine import backtest as bt, swingavwap, swingstudy  # noqa: E402
from data.reports import base_of  # noqa: E402
from run_study import auto_periods  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", nargs="?", help="ex. SOLUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--folder", help="dossier de series fines (b1m.bin, b5m.bin, b15m.bin, b1h.bin)")
    ap.add_argument("--label", help="nom du rapport (defaut : symbole sans USDT)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--control-runs", type=int, default=40)
    ap.add_argument("--start", help="debut AAAA-MM-JJ (defaut : 220 jours apres le debut de l'historique)")
    ap.add_argument("--split", help="separation apprentissage / test AAAA-MM-JJ (defaut : un tiers de la fin)")
    ap.add_argument("--pct", type=float, default=5.0, help="taille minimale du mouvement principal, en %% (defaut 5 ; 8 et 12 servent de sensibilite)")
    a = ap.parse_args(argv)
    if not a.symbol and not a.folder:
        ap.error("donne un symbole (SOLUSDT) ou --folder")
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / a.symbol.upper()
    if not (folder / "b1m.bin").exists():
        raise SystemExit(f"Historique introuvable dans {folder}. Lance d'abord :  python tools/fetch_history.py {a.symbol or 'SOLUSDT'}")
    label = (a.label or (base_of(a.symbol.upper()) if a.symbol else folder.name)).upper()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8")) if (folder / "meta.json").exists() else {}
    print("Chargement des séries…", flush=True)
    ds = bt.Dataset.load(str(folder))
    end = int(ds.b1h.t[-1]) + 3_600_000
    start, eras, split = auto_periods(int(ds.b1h.t[0]), end)
    day = lambda s: bt.ms(*(int(x) for x in s.split("-")))
    if a.start:
        start = day(a.start)
    if a.split:
        split = day(a.split)
    eras = [(lab, max(x, start), z) for lab, x, z in eras if z > start]
    print(f"{label} : {datetime.fromtimestamp(start / 1000, timezone.utc):%Y-%m-%d} -> {datetime.fromtimestamp(end / 1000, timezone.utc):%Y-%m-%d} ; apprentissage jusqu'au "
          f"{datetime.fromtimestamp(split / 1000, timezone.utc):%Y-%m-%d}", flush=True)
    t0 = time.time()
    ma = bt.regime_series(ds.b1h)
    main_pct = a.pct / 100.0
    sizes = sorted({main_pct, 0.05, 0.08, 0.12})
    ev = {}
    for pct in sizes:
        ev[pct] = swingavwap.build_events(ds, start, end, pct=pct, ma=ma)
        print(f"  mouvement ≥ {pct * 100:.0f} % : {len(ev[pct]):,} contacts", flush=True)
    rep = swingstudy.run(ds, ev, label, start, end, split, eras, main_pct=main_pct, control_runs=a.control_runs, workers=a.workers,
                         progress=lambda m: print(f"  {m}  ({time.time() - t0:.0f} s)", flush=True))
    rep["source"] = meta.get("source") or "Historique fourni par l'utilisateur"
    out = ROOT / "data_local" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"avwap_{label}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print("\n" + rep.get("verdict", {}).get("text", "Pas assez de trades pour conclure."))
    for n in rep.get("verdict", {}).get("notes", []):
        print(" -", n)
    print(f"\nRapport écrit : {out / ('avwap_' + label + '.json')}  (ouvre la page « Backtest » du terminal)")


if __name__ == "__main__":
    main()
