#!/usr/bin/env python3
"""Poches de liquidite : les CONFLUENCES autour d'une poche et sa MATURITE changent-elles ce que fait le prix ? Rapport affiche par la
page « Backtest » (rapport « poches ») et utilise pour expliquer le score d'importance des poches.

  python tools/run_pocket_study.py --folder dossier_bitstamp --label BTC --start 2014-01-01 --split 2022-01-01     # 12 ans de BTC
  python tools/fetch_history.py SOLUSDT                                                                          # une fois : historique 1 min de SOL
  python tools/run_pocket_study.py SOLUSDT                                                                       # meme mesure sur SOL

Poches mesurees : plus hauts / plus bas de la veille, de la semaine, du mois precedents, creux / sommets confirmes sur 1 h, extremes egaux.
Les poches estimees par l'interet ouvert ne sont pas testables (29 jours d'historique chez Binance). Quelques secondes de calcul. Aucune cle."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.reports import base_of  # noqa: E402
from engine import backtest as bt, fine, pocketstudy  # noqa: E402

DAY = 86_400_000


def month_start(ms: int) -> int:
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return bt.ms(d.year, d.month, 1)


def fmt_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d/%m/%Y")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", nargs="?", help="ex. BTCUSDT, SOLUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--folder", help="dossier de series fines (b1h.bin) : par exemple l'historique Bitstamp")
    ap.add_argument("--label", help="nom du rapport (defaut : symbole sans USDT)")
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--start", help="premier jour evalue AAAA-MM-JJ (defaut : 60 jours apres le debut des donnees)")
    ap.add_argument("--split", help="separation apprentissage / test AAAA-MM-JJ (defaut : 60 % de la periode)")
    a = ap.parse_args(argv)
    if not a.symbol and not a.folder:
        ap.error("donne un symbole (SOLUSDT) ou --folder")
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / a.symbol.upper()
    if not (folder / "b1h.bin").exists():
        raise SystemExit(f"Historique introuvable dans {folder}. Lance d'abord :  python tools/fetch_history.py {a.symbol or 'SOLUSDT'}")
    label = (a.label or (base_of(a.symbol.upper()) if a.symbol else folder.name)).upper()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8")) if (folder / "meta.json").exists() else {}
    b1h = fine.Bars.load(folder / "b1h.bin")
    if len(b1h) < 24 * 300:
        raise SystemExit(f"Historique trop court ({len(b1h) // 24} jours) : il faut au moins 300 jours.")
    t_first, t_last = int(b1h.t[0]), int(b1h.t[-1])
    day = lambda s: bt.ms(*(int(x) for x in s.split("-")))
    start = day(a.start) if a.start else t_first + 60 * DAY
    split = day(a.split) if a.split else month_start(start + int(0.6 * (t_last - start)))
    t0 = time.time()
    rep = pocketstudy.run(b1h, start, split, progress=lambda i, n: print(f"  {i * 100 // max(n, 1)} % ({time.time() - t0:.0f} s)", flush=True))
    rep.update(label=label, source=str(meta.get("source", folder.name)), computedAt=int(time.time() * 1000), seconds=round(time.time() - t0, 1),
               period={"from": start, "to": t_last, "split": split, "text": f"{fmt_day(start)} → {fmt_day(t_last)} (test à partir du {fmt_day(split)})"},
               verdict={"text": rep["summary"]["lines"][0] if rep["summary"]["lines"] else "", "notes": rep["summary"]["lines"][1:]})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"pockets_{label}.json"
    f.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    for line in rep["summary"]["lines"]:
        print(" -", line)
    print(f"\nRapport écrit : {f}  (page « Backtest » du terminal, menu « Rapport »)")


if __name__ == "__main__":
    main()
