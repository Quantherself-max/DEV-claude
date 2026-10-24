#!/usr/bin/env python3
"""Mesure le mouvement du prix apres la cassure de la bascule du gamma (gamma positif -> negatif, et l'inverse). Methode : engine/gexflip.py.

  python tools/run_gex_flip_study.py                       # tes enregistrements (data_local/history/derivs/BTCUSDT.csv, Deribit + Bybit + OKX)
  python tools/run_gex_flip_study.py --source binance2023  # archives horaires des options Binance (mai a octobre 2023)
  python tools/run_gex_flip_study.py --source binance2023 --coin ETH

Le terminal enregistre la bascule toutes les 15 minutes tant qu'il tourne (depuis la V26, toutes bourses depuis la V38) : plus il a tourne,
plus la mesure sur tes enregistrements est solide. Les archives Binance 2023 sont les seules archives gratuites d'options par strike
trouvees, mais Binance ne portait qu'environ 200 millions de dollars d'interet ouvert (Deribit : plusieurs milliards).
Les cours 1 minute viennent de Binance Vision (internet requis, sans cle). Archives gardees dans data_local/history/gexflip/raw."""
from __future__ import annotations
import argparse
import csv
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.derivs import gex_sets  # noqa: E402
from engine import gexflip, history  # noqa: E402
from tools.fetch_history import fetch  # noqa: E402

H, DAY = 3_600_000, 86_400_000
RAW = ROOT / "data_local" / "history" / "gexflip" / "raw"
EOH = "https://data.binance.vision/data/option/daily/EOHSummary/{s}/{s}-EOHSummary-{d}.zip"
EOH_FIRST, EOH_LAST = datetime(2023, 5, 18, tzinfo=timezone.utc), datetime(2023, 10, 23, tzinfo=timezone.utc)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def eoh_snaps(raw: bytes) -> list[dict]:
    """Une archive EOHSummary (un jour) -> un instantane du gamma par heure, connu a la fin de l'heure, avec le calcul du terminal."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")))
    by: dict = {}
    for r in rows:
        by.setdefault((r["date"], r["hour"]), []).append(r)
    out = []
    for (d, hh), rs in sorted(by.items()):
        t = ms(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)) + (int(hh) + 1) * H
        opts = []
        for r in rs:
            try:
                oi, oiu, iv = float(r["openinterest_contracts"] or 0), float(r["openinterest_usdt"] or 0), float(r["mark_iv"] or 0)
                _, ymd, strike, _ = r["symbol"].split("-")
                exp = ms(datetime.strptime("20" + ymd, "%Y%m%d").replace(tzinfo=timezone.utc)) + 8 * H       # echeance a 8 h UTC
            except ValueError:
                continue
            if oi > 0 and iv > 0:
                spot = oiu / oi
                opts.append({"ex": "Binance", "strike": float(strike), "kind": r["type"], "oi": oi, "iv": iv, "f": spot, "expiry": exp, "index": spot})
        if len(opts) < 20:
            continue
        try:
            a = gex_sets(opts, t)["all"]["all"]
        except Exception:
            continue
        out.append({"t": t, "flip": a["flip"], "flips": a["flips"], "curve": a["curve"]})
    return out


def binance2023(coin: str) -> list[dict]:
    sym = f"{coin}USDT"
    days, d = [], EOH_FIRST
    while d <= EOH_LAST:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    def one(day):
        dest = RAW / "eoh" / sym / f"{day}.zip"
        return eoh_snaps(dest.read_bytes()) if fetch(EOH.format(s=sym, d=day), dest) else []
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, days))
    return [s for r in res for s in r]


def recorded(path: Path) -> list[dict]:
    """Enregistrements du terminal : bascule toutes bourses (V38) sinon Deribit seul (V26)."""
    out = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            f = r.get("gexAllFlip") or r.get("gexFlip")
            try:
                if f:
                    out.append({"t": int(float(r["t"])), "flip": float(f)})
            except (KeyError, ValueError):
                continue
    return out


def bars_for(sym: str, market: str, t0: int, t1: int):
    """Bougies 1 minute de Binance Vision sur [t0, t1] (archives mensuelles, puis quotidiennes pour le mois en cours)."""
    t, h, l, c = [], [], [], []
    now = datetime.now(timezone.utc)
    files = []
    for y, m in history.months(t0, t1):
        if (y, m) < (now.year, now.month):
            files.append(history.vision_url(sym, market, y, m))
        else:
            for dd in range(1, now.day):
                files.append(history.vision_url(sym, market, y, m, dd))
    for url in files:
        dest = RAW / "klines" / market / url.rsplit("/", 1)[1]
        if not fetch(url, dest):
            continue
        for x in history.parse_rows(history.read_zip_rows(dest)):
            if t0 - H <= x[0] <= t1 + 30 * DAY and (not t or x[0] > t[-1]):
                t.append(x[0]); h.append(x[2]); l.append(x[3]); c.append(x[4])
    return t, h, l, c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("enregistre", "binance2023"), default="enregistre")
    ap.add_argument("--coin", default="BTC", help="BTC (ou ETH avec binance2023)")
    ap.add_argument("--hold", type=int, default=60, help="minutes de l'autre côté avant la cassure (défaut 60)")
    ap.add_argument("--cool", type=float, default=24, help="heures minimum entre deux cassures du même sens (défaut 24)")
    ap.add_argument("--json", help="fichier où écrire le résultat complet")
    a = ap.parse_args(argv)
    coin = a.coin.upper()
    if a.source == "binance2023":
        snaps, market, age = binance2023(coin), "spot", 2 * H
        title = f"{coin} : cassure de la bascule du gamma, options Binance (mai à octobre 2023)"
    else:
        f = ROOT / "data_local" / "history" / "derivs" / f"{coin}USDT.csv"
        if not f.exists():
            raise SystemExit(f"Aucun enregistrement : {f}. Lance le terminal (source Binance) et laisse-le tourner quelques semaines.")
        snaps, market, age = recorded(f), "futures", H
        title = f"{coin} : cassure de la bascule du gamma, tes enregistrements (Deribit, Bybit, OKX)"
    if len(snaps) < 48:
        raise SystemExit(f"Seulement {len(snaps)} instantanés du gamma : trop peu pour mesurer.")
    print(f"{len(snaps)} instantanés du gamma, du {datetime.fromtimestamp(snaps[0]['t'] / 1000, timezone.utc):%d/%m/%Y} au "
          f"{datetime.fromtimestamp(snaps[-1]['t'] / 1000, timezone.utc):%d/%m/%Y}. Cours 1 minute en cours de lecture…", flush=True)
    bars = bars_for(f"{coin}USDT", market, snaps[0]["t"], snaps[-1]["t"])
    rep = gexflip.study(snaps, bars, a.hold, int(a.cool * H), age)
    print(gexflip.text(rep, title))
    out = Path(a.json) if a.json else ROOT / "data_local" / "reports" / f"gexflip_{coin}_{a.source}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep), encoding="utf-8")
    print(f"\nRésultat complet : {out}")


if __name__ == "__main__":
    main()
