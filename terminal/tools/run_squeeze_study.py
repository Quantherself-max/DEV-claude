#!/usr/bin/env python3
"""Delta, CVD, volume, short / long squeezes : mesure sur plusieurs annees de donnees horaires, rapport affiche par la page « Backtest ».

  python tools/fetch_history.py BTCUSDT --since 2021-12 --metrics      # une fois : bougies 1 min (volume acheteur agressif REEL) + interet ouvert + financement
  python tools/run_squeeze_study.py BTCUSDT                            # delta reel + interet ouvert reel + financement reel (>= 4 ans depuis decembre 2021)
  python tools/run_squeeze_study.py SOLUSDT                            # meme chose sur ton actif
  python tools/run_squeeze_study.py --folder dossier_bitstamp --label BTC --start 2014-01-01 --split 2022-01-01     # delta estime (sans interet ouvert), 12 ans

Sans interet ouvert, seules les divergences de flux et de volume sont mesurees ; avec lui, les « carburants de squeeze » (shorts / longs qui s'accumulent) et les squeezes en cours.
Le calcul dure de quelques secondes a une minute. Aucune cle."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.reports import base_of  # noqa: E402
from engine import backtest as bt, fine, history, squeezestudy  # noqa: E402

DAY = 86_400_000


def month_start(ms: int) -> int:
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return bt.ms(d.year, d.month, 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", nargs="?", help="ex. BTCUSDT, SOLUSDT (dossier data_local/history/<SYMBOLE>)")
    ap.add_argument("--folder", help="dossier de series fines (b1h.bin) : par exemple l'historique Bitstamp")
    ap.add_argument("--label", help="nom du rapport (defaut : symbole sans USDT)")
    ap.add_argument("--out", default=str(ROOT / "data_local" / "reports"))
    ap.add_argument("--start", help="premier jour evalue AAAA-MM-JJ (defaut : 40 jours apres le debut des donnees)")
    ap.add_argument("--split", help="separation apprentissage / test AAAA-MM-JJ (defaut : 55 % de la periode)")
    ap.add_argument("--shifts", type=int, default=30)
    a = ap.parse_args(argv)
    if not a.symbol and not a.folder:
        ap.error("donne un symbole (BTCUSDT) ou --folder")
    folder = Path(a.folder) if a.folder else ROOT / "data_local" / "history" / a.symbol.upper()
    if not (folder / "b1h.bin").exists():
        raise SystemExit(f"Historique introuvable dans {folder}. Lance d'abord :  python tools/fetch_history.py {a.symbol or 'BTCUSDT'} --since 2021-12 --metrics")
    label = (a.label or (base_of(a.symbol.upper()) if a.symbol else folder.name)).upper()
    meta = {}
    if (folder / "meta.json").exists():
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    b1h = fine.Bars.load(folder / "b1h.bin").build_cum()
    if len(b1h) < 24 * 400:
        raise SystemExit(f"Historique trop court ({len(b1h) // 24} jours) : il faut au moins 400 jours.")
    oi, fund = history.load_pairs(folder / "oi_1h.csv"), history.load_pairs(folder / "funding.csv")
    real = "Binance" in str(meta.get("source", ""))
    t_first, t_last = int(b1h.t[0]), int(b1h.t[-1])
    day = lambda s: bt.ms(*(int(x) for x in s.split("-")))
    start = day(a.start) if a.start else t_first + 40 * DAY
    split = day(a.split) if a.split else month_start(start + int(0.55 * (t_last - start)))
    parts = ["delta réel (volume acheteur agressif, Binance)" if real else "delta estimé (position de la clôture dans chaque bougie d'une minute)"]
    parts += ["intérêt ouvert réel" if oi else "pas d'intérêt ouvert"]
    parts += ["financement réel" if fund else "pas de financement"]
    source = ("réel : " if real else "estimé : ") + str(meta.get("source", folder.name)) + " ; " + ", ".join(parts)
    t0 = time.time()
    rep = squeezestudy.run(b1h, label, start, t_last, split, oi=oi or None, fund=fund or None, source=source, shifts=a.shifts,
                           progress=lambda m: print(f"  {m} ({time.time() - t0:.0f} s)", flush=True))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"squeeze_{label}.json"
    f.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    print("\n" + rep["verdict"]["text"])
    for n in rep["verdict"]["notes"]:
        print(" -", n)
    print(f"\nRapport écrit : {f}  (page « Backtest » du terminal, menu « Rapport »)")


if __name__ == "__main__":
    main()
