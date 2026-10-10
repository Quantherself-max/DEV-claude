#!/usr/bin/env python3
"""TPO : les repères du profil de marché (single prints, poor high / low, POC, première heure, règle des 80 %, migration de la valeur, type de
journée, forme) tiennent-ils leurs promesses sur l'historique ? Rapport affiché dans la vue TPO du terminal (« Ce que dit l'historique »).

  python tools/run_tpo_study.py --folder dossier_bitstamp --label BTC                    # séances d'1 jour (bougies 15 min) depuis 2016
  python tools/run_tpo_study.py --folder dossier_bitstamp --label BTC --fine dossier_5min  # + séances de 4 h et d'1 h (bougies 5 min)
  python tools/fetch_history.py SOLUSDT                                                  # une fois : historique 1 min de SOL
  python tools/run_tpo_study.py SOLUSDT                                                  # même mesure sur SOL

Quelques secondes à une minute de calcul. Aucune clé, aucun accès réseau."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.reports import base_of  # noqa: E402
from engine import backtest as bt, fine, tpostudy  # noqa: E402


def _load(folder: Path, names):
    for n in names:
        if (folder / f"{n}.bin").exists():
            return fine.Bars.load(folder / f"{n}.bin")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", nargs="?", help="ex. SOLUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--folder", help="dossier de séries fines (b15m.bin ou b5m.bin) pour les séances d'1 jour")
    ap.add_argument("--fine", help="dossier avec b5m.bin pour les séances de 4 h et d'1 h (défaut : --folder)")
    ap.add_argument("--label", help="nom du rapport (défaut : symbole sans USDT)")
    ap.add_argument("--start", default="2016-01-01", help="premier jour AAAA-MM-JJ (défaut 2016-01-01, ou le début des données)")
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--source", help="nom de la source affiché (défaut : nom du dossier)")
    a = ap.parse_args(argv)
    if not a.symbol and not a.folder:
        ap.error("donne un symbole (SOLUSDT) ou --folder")
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / a.symbol.upper()
    label = (a.label or (base_of(a.symbol.upper()) if a.symbol else folder.name)).upper()
    day = _load(folder, ("b15m", "b5m"))
    if day is None:
        raise SystemExit(f"Historique introuvable dans {folder}. Lance d'abord :  python tools/fetch_history.py {a.symbol or 'SOLUSDT'}")
    fine5 = _load(Path(a.fine) if a.fine else folder, ("b5m",))
    start = max(bt.ms(*(int(x) for x in a.start.split("-"))), int(day.t[0]) + 15 * 86_400_000)
    t0 = time.time()
    rep = {"symbol": label, "kind": "tpo", "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "source": a.source or str(folder.name), "D": tpostudy.run(day, "D", start, int(day.t[-1]))}
    print(f"  séances d'1 jour : {rep['D'].get('n')} ({time.time() - t0:.0f} s)", flush=True)
    if fine5 is not None:
        s5 = max(start, int(fine5.t[0]) + 3 * 86_400_000)
        for kind in ("4h", "1h"):
            t1 = time.time()
            rep[kind] = tpostudy.run(fine5, kind, s5, int(fine5.t[-1]))
            print(f"  séances de {kind} : {rep[kind].get('n')} ({time.time() - t1:.0f} s)", flush=True)
    rep["summary"] = tpostudy.summary(rep)
    t_last = int(day.t[-1])
    first = rep["summary"][0]["text"] if rep["summary"] else ""
    rep.update(label=label, computedAt=int(time.time() * 1000), seconds=round(time.time() - t0, 1),
               period={"from": start, "to": t_last, "text": f"{rep['D'].get('from')} → {rep['D'].get('to')}"},
               verdict={"text": "Mesure des repères du profil de marché. " + first})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"tpo_{label}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print(f"Rapport écrit : {path}")
    for line in rep["summary"]:
        print(" -", line["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
