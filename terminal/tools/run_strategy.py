#!/usr/bin/env python3
"""Backtest de TA strategie (rebonds / clotures sur VWAP et VWAP ancres semaine + mois, volume profile, poches de liquidite, 1 a 2 jours) et de ses variantes.

  python tools/run_strategy.py SOLUSDT            # utilise data_local/history/SOLUSDT (voir tools/fetch_history.py)
  python tools/run_strategy.py --folder mon_dossier --label MONACTIF --workers 4

Ce que fait l'outil (protocole complet dans engine/stratstudy.py) : joue chaque cloture 1 h / 4 h sur un VWAP ou VWAP ancre de la semaine ou du mois,
dans les deux sens, avec 48 sorties differentes, puis une quarantaine de filtres (volume, position face a la VAL / VAH, tendance…), classe sur la
periode d'apprentissage, juge la meilleure sur la periode test, la compare au hasard et cherche une couverture. Resultat : data_local/reports/strategy_<ACTIF>.json,
affiche dans la page « Backtest » (liste « Rapport »).

Memoire : environ 3 a 6 Go pour 13 ans d'historique BTC (moins pour SOL). Duree : de 15 a 40 minutes selon les coeurs."""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from engine import backtest as bt, stratstudy, vwapstrat as vs  # noqa: E402
from data.reports import base_of  # noqa: E402
from run_study import auto_periods  # noqa: E402

_DS = None


def _init(folder):
    global _DS
    _DS = bt.Dataset.load(folder)


def _events(ab):
    a, b = ab
    ev = vs.build_events(_DS, a, b)
    fade = [{**e, "dir": -e["dir"], "fade": True} for e in ev]
    for e in ev:
        e["fade"] = False
    return ev + fade


def chunks(start_ms: int, end_ms: int):
    d = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    y, m = d.year, d.month
    edges = []
    cur = start_ms
    while cur < end_ms:
        m2 = m + 6
        y2, m2 = (y, m2) if m2 <= 12 else (y + 1, m2 - 12)
        nxt = min(bt.ms(y2, m2), end_ms)
        edges.append((cur, nxt))
        cur, y, m = nxt, y2, m2
    return edges


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", nargs="?", help="ex. SOLUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--folder", help="dossier de series fines (b1m.bin, b5m.bin, b15m.bin, b1h.bin)")
    ap.add_argument("--label", help="nom du rapport (defaut : symbole sans USDT)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--control-runs", type=int, default=40)
    ap.add_argument("--start", help="debut AAAA-MM-JJ (defaut : 220 jours apres le debut de l'historique)")
    ap.add_argument("--split", help="separation apprentissage / test AAAA-MM-JJ (defaut : un tiers de la fin)")
    a = ap.parse_args(argv)
    if not a.symbol and not a.folder:
        ap.error("donne un symbole (SOLUSDT) ou --folder")
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / a.symbol.upper()
    if not (folder / "b1m.bin").exists():
        raise SystemExit(f"Historique introuvable dans {folder}. Lance d'abord :  python tools/fetch_history.py {a.symbol or 'SOLUSDT'}")
    label = (a.label or (base_of(a.symbol.upper()) if a.symbol else folder.name)).upper()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8")) if (folder / "meta.json").exists() else {}
    print("Chargement des series…", flush=True)
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
          f"{datetime.fromtimestamp(split / 1000, timezone.utc):%Y-%m-%d} ; périodes : " + ", ".join(e[0] for e in eras), flush=True)
    t0 = time.time()
    print("Construction des événements…", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(str(folder),)) as ex:
        parts = list(ex.map(_events, chunks(start, end)))
    events = [e for p in parts for e in p]
    events.sort(key=lambda e: (e["t"], e["tf"], e["fade"], e["rank"]))
    print(f"  {len(events):,} événements ({time.time() - t0:.0f} s)", flush=True)
    rep = stratstudy.run(ds, events, label, start, end, split, eras, control_runs=a.control_runs, progress=lambda m: print(f"  {m}  ({time.time() - t0:.0f} s)", flush=True), workers=a.workers)
    rep["source"] = (meta.get("source") or "Historique fourni par l'utilisateur")
    out = ROOT / "data_local" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"strategy_{label}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    b = rep.get("best")
    if b:
        print(f"\nMeilleure variante (classée sur l'apprentissage) : {b['name']} ({b['side']}), {stratstudy.cfg_label(b['cfg'])}")
        for k, lab in (("is", "apprentissage"), ("oos", "test")):
            m = b[k]
            print(f"  {lab:14s}: {m['n']} trades, {m['expR']:+.3f} R par trade" if m["expR"] is not None else f"  {lab}: aucun trade")
    print(f"\nRapport écrit : {out / ('strategy_' + label + '.json')}  (ouvre la page « Backtest » du terminal)")


if __name__ == "__main__":
    main()
