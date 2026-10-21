#!/usr/bin/env python3
"""V25.2 : les idees de couverture (une idee dans l'autre sens envoyee pendant une idee en cours, sans la fermer) ont-elles paye ?
Rejoue ensemble les idees de plusieurs paires (historique prepare par fetch_history.py, perpetuels Binance) avec les regles d'envoi
du terminal, avec et sans le filtre de tendance de fond.

  python tools/run_hedge_study.py SOLUSDT BTCUSDT

Ecrit data_local/reports/hedge_study.json et affiche les tableaux (multiples du risque, brut et apres 0,1 % de frais par aller-retour)."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import fine, sigtest  # noqa: E402


def cell(x):
    pt = "—" if x["perTrade"] is None else f"{x['perTrade']:+.3f}"
    return f"{x['n']:>5} {x['filled']:>5} {x['R']:>+8.1f} {x['Rnet']:>+8.1f} {pt:>8}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--min-s", type=float, default=7.0)
    ap.add_argument("--step", type=int, default=2)
    a = ap.parse_args(argv)
    t0 = time.time()
    series = {}
    for sym in (s.upper() for s in a.symbols):
        b = fine.Bars.load(str(ROOT / "data_local" / "history" / sym / "b1h.bin"))
        candles = b.candles(0, len(b.t))
        ideas = []
        sigtest.replay(candles, step=a.step, ctrl_n=0, on_idea=lambda i, idea, res: ideas.append(
            (i, idea["side"], idea["st"]["S"], idea["entry"], idea["stop"], idea["tp1"], idea["entryType"] == "marché", idea.get("align"))))
        series[sym] = (candles, ideas)
        print(f"{sym} : {len(ideas)} idées rejouées ({time.time() - t0:.0f} s)", flush=True)
    out = {"symbols": list(series), "seconds": None, "runs": {}}
    for gate in (False, True):
        st = sigtest.hedge_study(series, min_s=a.min_s, gate=gate)
        out["runs"]["tendance" if gate else "toutes"] = st
        print(f"\n=== {'seulement dans le sens de la tendance de fond (réglage par défaut du terminal)' if gate else 'toutes les idées'} : {st['ideas']} idées")
        print(f"{'':44} {'idées':>5} {'exéc.':>5} {'R brut':>8} {'R net':>8} {'R/trade':>8}")
        for pol, name in (("never", "une seule direction à la fois"), ("hedge", "couverture permise")):
            v = st[pol]
            print(f"{name:44} {cell(v)}   creux {v['maxDD']:.1f}")
        h = st["hedge"]
        print(f"{'  dont idées de couverture':44} {cell(h['hedge'])}")
        print(f"{'    sur la même paire':44} {cell(h['samePair'])}")
        print(f"{'    sur l autre paire':44} {cell(h['otherPair'])}")
        print(f"{'  dont idées seules':44} {cell(h['alone'])}")
    out["seconds"] = round(time.time() - t0, 1)
    dest = ROOT / "data_local" / "reports" / "hedge_study.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
