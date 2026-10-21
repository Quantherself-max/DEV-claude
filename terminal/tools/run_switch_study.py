#!/usr/bin/env python3
"""V25.1 : faut-il fermer une idee en cours quand une idee plus forte arrive dans l'autre sens ? Mesure sur l'historique prepare par
fetch_history.py (perpetuels Binance) avec les regles des idees du terminal (rejeu de engine/sigtest.py).

  python tools/run_switch_study.py SOLUSDT
  python tools/run_switch_study.py BTCUSDT --min-s 7

Ecrit data_local/reports/<SYMBOLE>_switch.json et affiche le tableau : pour chaque politique, idees envoyees, executees, somme des
multiples du risque (brute et apres 0,1 % de frais par aller-retour), creux maximal, et gain moyen d'un changement de sens."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import fine, sigtest  # noqa: E402

NAMES = {"never": "jamais (bloquer l'idée opposée)", "both": "garder les deux (couverture)",
         "never_exp72": "jamais + ordre expiré bloque 72 h"}


def name(k):
    if k in NAMES:
        return NAMES[k]
    if k.endswith("_exp72"):
        return "qualité + " + k[5:-6] + " + ordre expiré 72 h"
    return "changer si qualité ≥ en cours + " + k[5:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol")
    ap.add_argument("--min-s", type=float, default=7.0)
    ap.add_argument("--step", type=int, default=2)
    a = ap.parse_args(argv)
    folder = ROOT / "data_local" / "history" / a.symbol.upper()
    b = fine.Bars.load(str(folder / "b1h.bin"))
    candles = b.candles(0, len(b.t))
    t0 = time.time()
    ideas = []
    sigtest.replay(candles, step=a.step, ctrl_n=0, on_idea=lambda i, idea, res: ideas.append(
        (i, idea["side"], idea["st"]["S"], idea["entry"], idea["stop"], idea["tp1"], idea["entryType"] == "marché")))
    st = sigtest.switch_study(candles, ideas, min_s=a.min_s)
    st.update({"symbol": a.symbol.upper(), "from": candles[0].t, "to": candles[-1].t, "seconds": round(time.time() - t0, 1)})
    out = ROOT / "data_local" / "reports" / f"{a.symbol.upper()}_switch.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.symbol.upper()} : {st['ideas']} idées rejouées, {st['seconds']} s")
    print(f"{'politique':40} {'envoyées':>8} {'exéc.':>6} {'R brut':>8} {'R net':>8} {'R/trade':>8} {'creux':>7} {'chgts':>6} {'gain/chgt':>9} {'gagnants':>8} {'bloq. exp.':>10}")
    for k, v in st["policies"].items():
        g = "—" if v["switchGain"] is None else f"{v['switchGain']:+.2f}"
        pt = "—" if v["perTrade"] is None else f"{v['perTrade']:+.3f}"
        print(f"{name(k):40} {v['sent']:>8} {v['filled']:>6} {v['R']:>+8.1f} {v['Rnet']:>+8.1f} {pt:>8} {v['maxDD']:>7.1f} {v['switches']:>6} {g:>9} "
              f"{v['switchWins']:>3}/{v['switchN']:<4} {v['ghostBlocked']:>10}")
    print("\nGain moyen d'un changement selon l'état de l'idée en cours (multiples du risque, gagnants / changements) :")
    for k, v in st["policies"].items():
        if not k.startswith("delta") or k.endswith("_exp72"):
            continue
        bs = v["byState"]
        cell = lambda x: "—" if x["gain"] is None else f"{x['gain']:+.2f} ({x['wins']}/{x['n']})"
        print(f"  qualité + {k[5:]:>3} : en perte {cell(bs['perte']):>16}   en gain {cell(bs['gain']):>16}   ordre en attente {cell(bs['attente']):>16}")


if __name__ == "__main__":
    main()
