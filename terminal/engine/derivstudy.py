"""Backtest des indicateurs de DERIVES enregistres par le terminal (data_local/history/derivs/<paire>.csv) : financement multi-bourses, ecart entre bourses,
variation de l'interet ouvert, ratio put / call, distance au « max pain », volatilite implicite (DVOL), base des futures.

Ces series n'ont pas d'historique libre : le terminal les enregistre toutes les 15 minutes depuis qu'il tourne. Il faut donc laisser tourner le terminal
quelques semaines avant que cette mesure ait un sens. Meme methode que engine/indstudy.py (rang percentile sur fenetre croissante, rendement futur,
Newey-West, apprentissage / test, temoin par decalage), au pas de l'HEURE : horizons 4 h, 24 h, 72 h. Module PUR."""
import csv
import time
from pathlib import Path

from . import indstudy as ist

HOUR = 3_600_000
HORIZONS = (4, 24, 72)
CATALOG = {
    "fund_mean": ("Financement", "Financement moyen des bourses (annualisé)", -1, "Foule acheteuse = carburant de liquidation : financement haut = baissier ensuite.", "%"),
    "fund_spread": ("Financement", "Écart de financement entre bourses", 0, "Désaccord entre bourses : arbitrages, tension.", "%"),
    "oi_chg_24h": ("Positionnement", "Intérêt ouvert hors Binance (variation 24 h)", 0, "Positions qui s'accumulent ou se ferment.", "%"),
    "put_call": ("Options", "Ratio put / call", 0, "Plus de puts : couverture ou paris baissiers (contrarien ?).", ""),
    "maxpain_dist": ("Options", "Distance au max pain (échéance proche)", +1, "Le prix serait attiré vers le max pain à l'approche de l'échéance.", "%"),
    "dvol": ("Options", "Volatilité implicite (DVOL)", +1, "Peur chère = contrarien haussier ?", ""),
    "dvol_chg_24h": ("Options", "DVOL (variation 24 h)", -1, "Hausse brutale de la volatilité implicite : stress.", "%"),
    "basis": ("Futures", "Base du future trimestriel (annualisée)", -1, "Levier cher = foule acheteuse.", "%"),
}


def read_records(path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                t = int(float(r["t"]))
            except (KeyError, ValueError, TypeError):
                continue
            rec = {"t": t}
            for k, v in r.items():
                if k != "t":
                    try:
                        rec[k] = float(v) if v not in ("", None) else None
                    except ValueError:
                        rec[k] = None
            rows.append(rec)
    rows.sort(key=lambda r: r["t"])
    return rows


def hourly(records: list[dict], max_gap_h: int = 3):
    """Grille horaire (dernier enregistrement de chaque heure, reporte au plus max_gap_h heures)."""
    if not records:
        return [], {}
    t0, t1 = records[0]["t"] // HOUR * HOUR, records[-1]["t"] // HOUR * HOUR
    grid = list(range(t0, t1 + HOUR, HOUR))
    cols = sorted({k for r in records for k in r if k != "t"})
    last = {}
    for r in records:
        last[r["t"] // HOUR * HOUR] = r
    out = {c: [] for c in cols}
    cur, age = None, 0
    for t in grid:
        if t in last:
            cur, age = last[t], 0
        elif cur is not None:
            age += 1
            if age > max_gap_h:
                cur = None
        for c in cols:
            out[c].append(cur.get(c) if cur else None)
    return grid, out


def features(grid: list[int], cols: dict, price: list) -> dict:
    def pct(x, n):
        return [(a / b - 1.0) if (a is not None and b not in (None, 0)) else None for a, b in zip(x, [None] * n + x[:-n])]
    f = {"fund_mean": cols.get("meanFundingAnn", []), "fund_spread": cols.get("spreadAnn", []), "put_call": cols.get("putCall", []), "dvol": cols.get("dvol", []), "basis": cols.get("basisAnnNear", [])}
    if "oiOthersUsd" in cols:
        f["oi_chg_24h"] = pct(cols["oiOthersUsd"], 24)
    if "dvol" in cols:
        f["dvol_chg_24h"] = pct(cols["dvol"], 24)
    if "maxPainNext" in cols:
        f["maxpain_dist"] = [(m / p - 1.0) if (m is not None and p) else None for m, p in zip(cols["maxPainNext"], price)]
    return {k: v for k, v in f.items() if v and any(x is not None for x in v)}


def align_price(grid: list[int], closes: list[tuple[int, float]]) -> list:
    d = dict(closes)
    return [d.get(t) for t in grid]


def run(records: list[dict], closes: list[tuple[int, float]], label: str, horizons=HORIZONS, min_hist: int = 24 * 7, shifts: int = 20, split_frac: float = 0.7) -> dict:
    """closes = [(ouverture de l'heure en ms, cloture)] ; renvoie un rapport meme forme que indstudy.run (kind « derivs »)."""
    t0 = time.time()
    grid, cols = hourly(records)
    days = (grid[-1] - grid[0]) / (24 * HOUR) if grid else 0.0
    base = {"kind": "derivs", "label": label, "computedAt": int(time.time() * 1000), "days": days, "records": len(records), "horizons": list(horizons)}
    need = (min_hist + 3 * max(horizons)) * 3 / 24.0
    if days < need:
        return {**base, "usable": False, "reason": f"seulement {days:.1f} jour(s) enregistrés ; il en faut au moins {need:.0f} pour une première lecture (3 à 4 semaines pour qu'elle ait un sens)"}
    price = align_price(grid, closes)
    series = features(grid, cols, price)
    sp = int(len(grid) * split_frac)
    rows, null, thr, last = ist.evaluate(series, price, {k: v for k, v in CATALOG.items() if k in series}, grid, 0, sp, horizons, 1, min_hist, shifts)
    return {**base, "usable": True, "period": {"start": grid[0], "end": grid[last] + HOUR, "split": grid[min(sp, len(grid) - 1)]}, "null": null, "threshold": thr, "rows": rows,
            "counts": {"indicators": len(rows), "tests": len(rows) * len(horizons), "informative": sum(1 for r in rows if r["level"] == "informatif"), "hints": sum(1 for r in rows if r["level"] == "indice")},
            "seconds": round(time.time() - t0)}
