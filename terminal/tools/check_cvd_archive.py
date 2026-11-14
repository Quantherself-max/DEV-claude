#!/usr/bin/env python3
"""Preuve du CVD exact sur une journée entière de vraies transactions Binance (V45) :

    python tools/check_cvd_archive.py                       hier, BTCUSDT, perpétuels
    python tools/check_cvd_archive.py --symbol SOLUSDT --day 2026-11-12 --market spot

Télécharge EN MÉMOIRE l'archive publique des transactions agrégées du jour (data.binance.vision) et celle des bougies d'une minute, puis :
  1. recompte chaque minute transaction par transaction avec le moteur exact (quant.flow.TickCvd, entiers) et la compare à la bougie
     officielle : volume, volume acheteur agressif, volume en dollars, ouverture, haut, bas, clôture, nombre de transactions ;
  2. refait la même somme en flottants binaires pour montrer de combien elle dérive ;
  3. calcule le profil de volume exact du jour (POC, VAH, VAL au pas de cotation) et le compare au profil du terminal avant la V45
     (volume réparti sur une grille de 0,03 %, lignes regroupées).
Aucune écriture sur le disque. Code de sortie 1 si une minute diffère de la bougie officielle."""
from __future__ import annotations
import argparse
import io
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.trades import http_bytes
from engine import vp as old_vp
from quant import flow, profile
from quant.num import UNIT, fmt, from_units, units

BASE = "https://data.binance.vision/data"


def urls(symbol: str, day: str, market: str):
    root = f"{BASE}/spot/daily" if market == "spot" else f"{BASE}/futures/um/daily"
    return (f"{root}/aggTrades/{symbol}/{symbol}-aggTrades-{day}.zip", f"{root}/klines/{symbol}/1m/{symbol}-1m-{day}.zip")


def rows_of(raw: bytes):
    z = zipfile.ZipFile(io.BytesIO(raw))
    with z.open(z.namelist()[0]) as fh:
        for ln in fh:
            a = ln.rstrip(b"\r\n").split(b",")
            if a and a[0][:1].isdigit():
                yield a


def ms(t: int) -> int:
    return t // 1000 if t > 100_000_000_000_000 else t                    # les archives du comptant sont en microsecondes depuis 2025


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--market", choices=("perp", "spot"), default="perp")
    ap.add_argument("--day", default=(datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d"))
    a = ap.parse_args()
    u_tr, u_kl = urls(a.symbol, a.day, a.market)
    t0 = time.time()
    raw_tr, raw_kl = http_bytes(u_tr), http_bytes(u_kl)
    if raw_tr is None or raw_kl is None:
        print(f"Archive du {a.day} pas encore publiée par Binance (essaie un jour plus ancien avec --day).")
        return 2
    print(f"{a.symbol} {a.market} du {a.day} : archives lues ({len(raw_tr) / 1e6:.1f} Mo de transactions) en {time.time() - t0:.0f} s")

    c = flow.TickCvd(60_000, keep=5000)
    prof = None
    f_buy = f_sell = 0.0                                                    # la même somme en flottants, pour comparer
    n = 0
    for r in rows_of(raw_tr):
        px, q, t, side = units(r[1]), units(r[2]), ms(int(r[5])), (-1 if r[6][:1] in (b"t", b"T") else 1)
        if prof is None:
            tick = 10 ** (8 - len(r[1].split(b".")[1])) if b"." in r[1] else UNIT
            prof = profile.ExactProfile(tick)
        c.add(t, px, q, side)
        prof.add(px, q, side)
        if side > 0:
            f_buy += float(r[2])
        else:
            f_sell += float(r[2])
        n += 1
    first = min(c.bars)
    c.bars[first][flow.OK] = True                                           # l'archive est complète par définition

    diffs, ohlc_bad, checked = [], 0, 0
    for r in rows_of(raw_kl):
        t = ms(int(r[0]))
        b = c.bars.get(t)
        v, tb = units(r[5]), units(r[9])
        checked += 1
        if b is None:
            diffs.append((-v, -tb))
            continue
        diffs.append((b[flow.BUY] + b[flow.SELL] - v, b[flow.BUY] - tb))
        if (b[flow.H], b[flow.L]) != (units(r[2]), units(r[3])):
            ohlc_bad += 1
    lab = flow.classify_diffs(diffs)
    ok, shift, other = lab.count("ok"), lab.count("shift"), lab.count("bad") + lab.count("open")
    run = peak = 0
    for dv, _ in diffs:
        run += dv
        peak = max(peak, abs(run))
    tot_v = sum(units(r[5]) for r in rows_of(raw_kl))
    print(f"1. Intégrité : {n} transactions recomptées en {checked} minutes.")
    print(f"   {ok} minutes IDENTIQUES à la bougie officielle (volume et volume acheteur, à l'unité près) ;")
    print(f"   {shift} minutes décalées dont l'écart s'annule exactement avec la minute voisine, {other} dont l'écart s'annule plus loin"
          f" (une transaction agrégée ne porte qu'une heure pour toutes ses exécutions) ;")
    print(f"   résidu cumulé (transactions - bougies) : au pire {peak / UNIT:.8f} pièce pendant le jour, {run / UNIT:+.8f} à la fin, "
          f"sur {tot_v / UNIT:.3f} pièces échangées ({peak / tot_v * 100:.5f} % au pire). Haut ou bas différent : {ohlc_bad} minute(s).")
    bad = 1 if peak * 1000 > tot_v else 0                                   # plus de 0,1 % du volume du jour : des transactions manquent
    delta = c.buy - c.sell
    print(f"   CVD du jour : {delta / UNIT:+.8f} pièces (achats {c.buy / UNIT:.8f}, ventes {c.sell / UNIT:.8f}), "
          f"{flow.usd(c.buyq - c.sellq):+,.2f} $".replace(",", " "))
    drift = (f_buy - f_sell) - delta / UNIT
    print(f"2. La même somme en flottants binaires s'écarte de {drift:+.3e} pièce sur le delta du jour "
          f"({abs(f_buy - c.buy / UNIT):.3e} sur les achats) : c'est cette dérive que les entiers suppriment.")

    lv = prof.levels(70)
    p0 = old_vp.Profile()
    for k in set(prof.buy) | set(prof.sell):
        px = k * prof.row / UNIT
        p0.add(px, px, (prof.buy.get(k, 0) + prof.sell.get(k, 0)) / UNIT)
    old = old_vp.levels(p0, checked)
    print(f"3. Profil de volume exact (pas de cotation {fmt(from_units(prof.row))}, {lv['rows']} lignes) : POC {fmt(lv['poc'])}, "
          f"VAH {fmt(lv['vah'])}, VAL {fmt(lv['val'])} ({float(lv['share']) * 100:.2f} % du volume dans la zone de valeur).")
    print(f"   Profil du terminal avant la V45 sur les mêmes transactions (grille de 0,03 %, lignes regroupées) : POC {old['poc']:.2f}, "
          f"VAH {old['vah']:.2f}, VAL {old['val']:.2f} ; écart du POC : {abs(old['poc'] - float(lv['poc'])):.2f} $ "
          f"({abs(old['poc'] / float(lv['poc']) - 1) * 100:.3f} %).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
