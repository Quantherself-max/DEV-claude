#!/usr/bin/env python3
"""Stratégie V32 : DIVERGENCES prix / intérêt ouvert / CVD sur 1 jour, 4 heures et 1 heure, mesurées ensemble sur plusieurs actifs.

  python tools/fetch_history.py SOLUSDT --since 2021-10 --metrics     # une fois par actif : bougies 1 minute (volume acheteur agressif réel) + intérêt ouvert
  python tools/run_div_study.py                                       # SOL, BTC et ETH -> data_local/reports/div_ALL.json
  python tools/run_div_study.py SOLUSDT BTCUSDT                       # d'autres actifs

Le calcul dure quelques minutes. Aucune clé."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.reports import base_of  # noqa: E402
from engine import backtest as bt, fine, flowstrat as fs, history  # noqa: E402

DAY = 86_400_000


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="*", default=["SOLUSDT", "BTCUSDT", "ETHUSDT"])
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--controls", type=int, default=60)
    a = ap.parse_args(argv)
    t0 = time.time()
    say = lambda m: print(f"[{time.time() - t0:5.0f} s] {m}", flush=True)
    assets = {}
    for sym in (s.upper() for s in a.symbols):
        folder = ROOT / "data_local" / "history" / sym
        if not (folder / "b5m.bin").exists() or not (folder / "oi_1h.csv").exists():
            raise SystemExit(f"Historique introuvable pour {sym}. Lance d'abord :  python tools/fetch_history.py {sym} --since 2021-10 --metrics")
        say(f"chargement {sym}")
        b1h = fine.Bars.load(folder / "b1h.bin").build_cum()
        b5 = fine.Bars.load(folder / "b5m.bin").build_cum()
        oi = fs.hourly_oi(b1h, history.load_pairs(folder / "oi_1h.csv"))
        first = next((int(b1h.t[i]) for i, x in enumerate(oi) if x), None)
        if first is None:
            raise SystemExit(f"Pas d'intérêt ouvert pour {sym} (option --metrics de fetch_history.py).")
        start, end = first + 70 * DAY, int(b1h.t[-1]) - 12 * DAY       # 70 jours de chauffe : sommets et creux journaliers
        assets[base_of(sym)] = {"ds": bt.Dataset(None, b5, None, b1h, sym), "oi": oi, "start": start, "end": end, "split": start + int(0.55 * (end - start))}
    rep = fs.study_div(assets, progress=say, controls=a.controls)
    rep["seconds"] = int(time.time() - t0)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "div_ALL.json"
    f.write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    say(f"rapport : {f}")
    for tf in fs.DIV_TFS:
        r = rep["tfs"][tf]
        print(f"  {r['verdict']}  (sortie : {r['exitLabel']} ; apprentissage {r['strategy']['is']['expR']} sur {r['strategy']['is']['n']} trades)")
        for name, m in r["strategy"]["byAsset"].items():
            print(f"     {name} : apprentissage {m['is']['expR']} ({m['is']['n']}) · test {m['oos']['expR']} ({m['oos']['n']})")


if __name__ == "__main__":
    main()
