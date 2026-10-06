#!/usr/bin/env python3
"""Telecharge l'historique 1 minute d'un symbole depuis les archives publiques de Binance (data.binance.vision, sans cle) et le convertit
en series fines pour le backtest. Le VOLUME ACHETEUR AGRESSIF y est reel : le CVD n'est plus estime.

  python tools/fetch_history.py SOLUSDT                  # futures perpetuels USDT-M (defaut), depuis le debut disponible
  python tools/fetch_history.py SOLUSDT --market spot    # marche au comptant
  python tools/fetch_history.py BTCUSDT --since 2021-01  # a partir d'un mois
  python tools/fetch_history.py BTCUSDT --since 2021-12 --metrics   # + interet ouvert (5 min) et financement reels : mesure des squeezes (>= 3 ans)
  python tools/fetch_history.py BTCUSDT --since 2021-12 --metrics --skip-klines   # seulement l'interet ouvert et le financement

Les archives brutes sont gardees dans data_local/history/<SYMBOLE>/raw : relancer la commande ne retelecharge que ce qui manque."""
import argparse
import calendar
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import fine, history  # noqa: E402

START = {"futures": "2019-09", "spot": "2017-08"}


def fetch(url: str, dest: Path, retries: int = 4):
    """Telecharge url vers dest. Renvoie True (ok), False (archive absente : 404)."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    last = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "liq-terminal/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            last = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = str(e)
        time.sleep(2 * (k + 1))
    raise SystemExit(f"Echec du telechargement de {url} : {last}\n(acces refuse depuis ton reseau ? Binance Vision est un site public sans cle)")


def fetch_metrics(sym: str, since: str, out: str, workers: int = 8):
    """Interet ouvert (5 min) et ratio taker : archives quotidiennes depuis `since` (au plus tot decembre 2021) ; financement : archives mensuelles.
    Ecrit <out>/<sym>/oi_1h.csv, taker_1h.csv et funding.csv (une valeur par heure pour l'OI, une par periode pour le financement)."""
    y0, m0 = (int(x) for x in since.split("-"))
    day0 = max(datetime(y0, m0, 1, tzinfo=timezone.utc), datetime(2021, 12, 1, tzinfo=timezone.utc))
    now = datetime.now(timezone.utc)
    raw = Path(out) / sym / "raw_metrics"
    days = []
    d = day0
    while d < now.replace(hour=0, minute=0, second=0, microsecond=0):
        days.append(d)
        d = datetime.fromtimestamp(d.timestamp() + 86_400, timezone.utc)
    print(f"Interet ouvert : {len(days)} jours a recuperer ({workers} telechargements en parallele)…", flush=True)

    def one(day):
        f = raw / f"{sym}-metrics-{day:%Y-%m-%d}.zip"
        return f if fetch(history.vision_metrics_url(sym, day.year, day.month, day.day), f) else None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        files = [f for f in ex.map(one, days) if f]
    if not files:
        raise SystemExit("Aucune archive d'interet ouvert trouvee (le perpetuel existe-t-il depuis decembre 2021 ?).")
    rows = []
    for f in sorted(files):
        rows += history.parse_metrics(history.read_zip_rows(str(f)))
    if not rows:
        raise SystemExit("Archives d'interet ouvert illisibles : format inattendu (colonnes create_time, sum_open_interest…).")
    folder = Path(out) / sym
    history.save_pairs(folder / "oi_1h.csv", history.hourly(rows, 1), "t,oi")
    history.save_pairs(folder / "taker_1h.csv", history.hourly(rows, 3), "t,takerRatio")
    print(f"  {len(rows):,} points a 5 minutes -> {len(history.hourly(rows, 1)):,} heures ({datetime.fromtimestamp(rows[0][0] / 1000, timezone.utc):%Y-%m-%d} -> {datetime.fromtimestamp(rows[-1][0] / 1000, timezone.utc):%Y-%m-%d})", flush=True)
    fund = []
    for y, m in history.months(int(day0.timestamp() * 1000), int(now.timestamp() * 1000)):
        if (y, m) >= (now.year, now.month):
            continue
        f = raw / f"{sym}-fundingRate-{y:04d}-{m:02d}.zip"
        if fetch(history.vision_funding_url(sym, y, m), f):
            fund += history.parse_funding(history.read_zip_rows(str(f)))
    fund.sort()
    if fund:
        history.save_pairs(folder / "funding.csv", fund, "t,rate")
    print(f"  financement : {len(fund):,} periodes", flush=True)
    print(f"Etape suivante :  python tools/run_squeeze_study.py {sym}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol", help="ex. SOLUSDT, BTCUSDT")
    ap.add_argument("--market", choices=("futures", "spot"), default="futures")
    ap.add_argument("--since", help="premier mois AAAA-MM (defaut : debut des archives)")
    ap.add_argument("--out", default=str(ROOT / "data_local" / "history"))
    ap.add_argument("--metrics", action="store_true", help="recupere aussi l'interet ouvert (5 min) et le financement reels (perpetuel USDT-M, depuis decembre 2021)")
    ap.add_argument("--skip-klines", action="store_true", help="ne telecharge pas les bougies 1 minute (deja faites)")
    a = ap.parse_args(argv)
    sym = a.symbol.upper()
    since = a.since or START[a.market]
    if a.metrics:
        fetch_metrics(sym, max(since, "2021-12"), a.out)
        if a.skip_klines:
            return
    y0, m0 = (int(x) for x in since.split("-"))
    now = datetime.now(timezone.utc)
    raw = Path(a.out) / sym / "raw"
    files = []
    def daily(y, m, last_day):
        got = 0
        for d in range(1, last_day + 1):
            f = raw / f"{sym}-1m-{y:04d}-{m:02d}-{d:02d}.zip"
            if fetch(history.vision_url(sym, a.market, y, m, d), f):
                files.append(f)
                got += 1
        return got

    py, pm = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    for y, m in history.months(int(datetime(y0, m0, 1, tzinfo=timezone.utc).timestamp() * 1000), int(now.timestamp() * 1000)):
        if (y, m) < (now.year, now.month):
            f = raw / f"{sym}-1m-{y:04d}-{m:02d}.zip"
            ok = fetch(history.vision_url(sym, a.market, y, m), f)
            if ok:
                files.append(f)
                print(f"{y}-{m:02d} ok", flush=True)
            elif (y, m) == (py, pm):                                  # l'archive mensuelle du mois dernier n'est parfois publiee que quelques jours apres
                n = daily(y, m, calendar.monthrange(y, m)[1])
                print(f"{y}-{m:02d} archives quotidiennes : {n} jours", flush=True)
            else:
                print(f"{y}-{m:02d} absent", flush=True)
        else:                                                         # mois en cours : archives quotidiennes jusqu'a hier
            n = daily(y, m, now.day - 1)
            print(f"{y}-{m:02d} (mois en cours) : {n} jours", flush=True)
    if not files:
        raise SystemExit("Aucune archive trouvee pour ce symbole / ce marche.")
    bars, state = fine.Bars(60_000), {}
    for f in files:
        history.append_rows(bars, history.parse_rows(history.read_zip_rows(str(f))), state)
    folder = Path(a.out) / sym
    info = history.build_folder(bars, folder, {"symbol": sym, "market": a.market, "source": f"Binance Vision ({a.market}), volume acheteur agressif reel"})
    print(f"{len(bars):,} minutes ({datetime.fromtimestamp(info['from'] / 1000, timezone.utc):%Y-%m-%d} -> {datetime.fromtimestamp(info['to'] / 1000, timezone.utc):%Y-%m-%d}) -> {folder}")
    print(f"Etape suivante :  python tools/run_study.py {sym}")


if __name__ == "__main__":
    main()
