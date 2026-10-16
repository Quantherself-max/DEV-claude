#!/usr/bin/env python3
"""Lance l'etude complete (backtest) sur un historique prepare par fetch_history.py et ecrit le rapport affiche par la page « Backtest ».

  python tools/run_study.py SOLUSDT            # utilise data_local/history/SOLUSDT
  python tools/run_study.py SOLUSDT --workers 4
  python tools/run_study.py --folder mon_dossier --label MONACTIF

Le calcul est long (quelques minutes a une demi-heure selon l'historique et le nombre de coeurs) : il peut tourner pendant que le terminal fonctionne."""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import backtest as bt, study  # noqa: E402
from data.reports import base_of  # noqa: E402

DAY = 86_400_000


def auto_periods(t_first: int, t_last: int):
    """Debut (apres 220 jours de chauffe pour la moyenne de 200 jours) et trois grandes periodes de duree egale, coupees au 1er janvier."""
    start = t_first + 220 * DAY
    y0, y1 = datetime.fromtimestamp(start / 1000, timezone.utc).year + 1, datetime.fromtimestamp(t_last / 1000, timezone.utc).year
    if y1 - y0 < 2:
        return start, [("toute la période", start, t_last)], start + (t_last - start) // 2
    cuts = [start]
    n = y1 - y0 + 1
    for k in (1, 2):
        cuts.append(bt.ms(y0 + round(n * k / 3)))
    cuts.append(t_last)
    cuts = sorted(set(c for c in cuts if start <= c <= t_last))
    eras = []
    for a, b in zip(cuts, cuts[1:]):
        ya, yb = datetime.fromtimestamp(a / 1000, timezone.utc).year, datetime.fromtimestamp((b - 1) / 1000, timezone.utc).year
        eras.append((f"{ya}" if ya == yb else f"{ya}-{yb}", a, b))
    return start, eras, eras[-1][1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", nargs="?", help="ex. SOLUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--folder", help="dossier de series fines (b1m.bin, b5m.bin, b15m.bin, b1h.bin)")
    ap.add_argument("--label", help="nom du rapport (defaut : symbole sans USDT)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--control-runs", type=int, default=60)
    ap.add_argument("--no-panel", action="store_true", help="saute l'etude d'evenements (plus rapide)")
    a = ap.parse_args(argv)
    if not a.symbol and not a.folder:
        ap.error("donne un symbole (SOLUSDT) ou --folder")
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / a.symbol.upper()
    if not (folder / "b1m.bin").exists():
        raise SystemExit(f"Historique introuvable dans {folder}. Lance d'abord :  python tools/fetch_history.py {a.symbol or 'SOLUSDT'}")
    label = (a.label or (base_of(a.symbol.upper()) if a.symbol else folder.name)).upper()
    meta = {}
    if (folder / "meta.json").exists():
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    print("Chargement des series…", flush=True)
    ds = bt.Dataset.load(str(folder))
    start, eras, split = auto_periods(int(ds.b1h.t[0]), int(ds.b1h.t[-1]) + 3_600_000)
    end = int(ds.b1h.t[-1]) + 3_600_000
    print(f"{label} : {datetime.fromtimestamp(start / 1000, timezone.utc):%Y-%m-%d} -> {datetime.fromtimestamp(end / 1000, timezone.utc):%Y-%m-%d}, périodes : "
          + ", ".join(e[0] for e in eras), flush=True)
    t0 = time.time()

    def prog(f, m):
        print(f"  {f * 100:3.0f} %  {m}  ({time.time() - t0:.0f} s)", flush=True)

    note = meta.get("source") or "Historique fourni par l'utilisateur"
    if "Binance" in note:
        note += ". Le flux d'ordres (CVD) vient du volume acheteur agressif réel de chaque minute."
    rep = study.run(ds, label, start, end, split, folder=str(folder), workers=a.workers, control_runs=a.control_runs, progress=prog,
                    source_note=note, panel=not a.no_panel, eras=eras)
    out = ROOT / "data_local" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"backtest_{label}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print("\n" + rep["verdict"]["text"])
    for n in rep["verdict"]["notes"]:
        print(" -", n)
    print(f"\nRapport écrit : {out / ('backtest_' + label + '.json')}  (ouvre la page « Backtest » du terminal)")


if __name__ == "__main__":
    main()
