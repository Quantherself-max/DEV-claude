#!/usr/bin/env python3
"""Stratégie V31 (prix, intérêt ouvert et CVD sur la liquidité et les VWAP) : mesure sur l'historique Binance, rapport affiché par le terminal.

  python tools/fetch_history.py SOLUSDT --since 2021-10 --metrics     # une fois : bougies 1 minute (volume acheteur agressif réel) + intérêt ouvert
  python tools/run_flow_study.py SOLUSDT                              # rapport data_local/reports/flow_SOL.json

Le calcul dure deux à quatre minutes. Aucune clé."""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.reports import base_of  # noqa: E402
from engine import backtest as bt, fine, flowstrat as fs, history  # noqa: E402

DAY = 86_400_000


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", help="ex. SOLUSDT, BTCUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--tf", default="4h", choices=("1h", "4h"))
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--split", help="séparation apprentissage / test AAAA-MM-JJ (défaut : 55 % de la période)")
    ap.add_argument("--controls", type=int, default=60)
    a = ap.parse_args(argv)
    sym = a.symbol.upper()
    folder = ROOT / "data_local" / "history" / sym
    if not (folder / "b5m.bin").exists() or not (folder / "oi_1h.csv").exists():
        raise SystemExit(f"Historique introuvable. Lance d'abord :  python tools/fetch_history.py {sym} --since 2021-10 --metrics")
    t0 = time.time()
    say = lambda m: print(f"[{time.time() - t0:5.0f} s] {m}", flush=True)
    say("chargement")
    b1h = fine.Bars.load(folder / "b1h.bin").build_cum()
    b5 = fine.Bars.load(folder / "b5m.bin").build_cum()
    ds = bt.Dataset(None, b5, None, b1h, sym)
    oi = fs.hourly_oi(b1h, history.load_pairs(folder / "oi_1h.csv"))
    first = next((int(b1h.t[i]) for i, x in enumerate(oi) if x), None)
    if first is None:
        raise SystemExit("Pas d'intérêt ouvert dans l'historique (option --metrics de fetch_history.py).")
    start = first + 40 * DAY
    end = int(b1h.t[-1]) - 4 * DAY
    split = bt.ms(*(int(x) for x in a.split.split("-"))) if a.split else start + int(0.55 * (end - start))
    say(f"événements {a.tf} du {datetime.fromtimestamp(start / 1000, timezone.utc):%Y-%m-%d} au {datetime.fromtimestamp(end / 1000, timezone.utc):%Y-%m-%d}")
    ev = fs.build_events(ds, oi, start, end, a.tf)
    say(f"{len(ev)} événements")
    rep = fs.study(ds, ev, base_of(sym), start, end, split, progress=say, controls=a.controls)
    rep["symbol"] = sym
    rep["seconds"] = int(time.time() - t0)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"flow_{base_of(sym)}.json"
    f.write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    s = rep["strategy"]
    say(f"rapport : {f}")
    for k in ("is", "oos", "all"):
        m = s[k]
        print(f"  {k:3s} trades {m['n']:4d}  espérance {m.get('expR') if m.get('expR') is not None else float('nan'):+.3f} R  gagnants {m.get('winRate') or 0:.0%}  rendement {m.get('ret', 0):+.0%}  perte max {m.get('maxDD', 0):.0%}")
    print(f"  sortie retenue : {rep['exitLabel']}")
    print(f"  témoin au hasard (test) : {s['control']['oos']}  rang de la stratégie : {s['control']['pctOos']}")


if __name__ == "__main__":
    main()
