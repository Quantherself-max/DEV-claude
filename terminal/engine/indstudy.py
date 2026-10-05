"""Que valent vraiment les indicateurs ? Mesure, pour chaque indicateur journalier (engine/indicators.py), ce qu'il dit du rendement FUTUR du bitcoin.

Methode (la meme pour tous, fixee avant de regarder) :
  - signal = rang percentile de l'indicateur parmi ses valeurs PASSEES (fenetre croissante, au moins un an d'historique) : jamais de donnee du futur ;
  - cible = rendement du BTC (logarithmique) a 7, 14 et 30 jours, mesure a partir de la cloture du lendemain (un jour de decalage : la valeur du jour n'est
    connue qu'a la fin du jour) ;
  - regression du rendement futur sur le signal centre (de -1 a +1) ; ecart = difference de rendement attendue entre le haut et le bas de l'historique de
    l'indicateur ; erreur-type robuste a l'autocorrelation (Newey-West : les fenetres de 7 a 30 jours se chevauchent) ;
  - apprentissage jusqu'a la date de coupure, test apres ; quintile haut / milieu / bas pour lire les moyennes ;
  - temoin : le meme signal decale d'une duree au hasard (il garde sa forme et son autocorrelation, mais n'a plus aucun lien avec le prix) : la distribution de
    |t| ainsi obtenue donne le seuil au-dela duquel un resultat n'est plus du hasard.
« informatif » = |t| d'apprentissage au-dessus du seuil du temoin (99 %) ET meme signe sur le test avec |t| >= 1,5. Module PUR."""
import bisect
import math
import random
import time

from . import indicators as ind

DAY = ind.DAY
HORIZONS = (7, 14, 30)


def expanding_rank(x: list, min_hist: int = 365) -> list:
    """Rang percentile (0 a 1) de x[t] parmi les valeurs connues jusqu'a t incluse ; None tant qu'il y a moins de min_hist valeurs."""
    hist, out = [], []
    for v in x:
        if v is None:
            out.append(None)
            continue
        bisect.insort(hist, v)
        n = len(hist)
        if n < min_hist:
            out.append(None)
        else:
            lo, hi = bisect.bisect_left(hist, v), bisect.bisect_right(hist, v)
            out.append((lo + hi - 1) / 2.0 / (n - 1))
    return out


def forward_returns(price: list, h: int, lag: int = 1) -> list:
    """Rendement logarithmique entre la cloture de t+lag et celle de t+lag+h."""
    n = len(price)
    out = [None] * n
    for t in range(n):
        a, b = t + lag, t + lag + h
        if b < n and price[a] and price[b] and price[a] > 0 and price[b] > 0:
            out[t] = math.log(price[b] / price[a])
    return out


def hac_slope(x: list, y: list, lags: int) -> tuple[float, float, int] | None:
    """Pente de y sur x (moindres carres) et statistique t avec erreur-type de Newey-West. x, y alignes (sans None). Renvoie (pente, t, n)."""
    n = len(x)
    if n < 60:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        return None
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx
    a0 = my - b * mx
    z = [(a - mx) * (c - a0 - b * a) for a, c in zip(x, y)]            # moments : (x - moyenne) x residu
    v = sum(q * q for q in z)
    for k in range(1, min(lags, n - 1) + 1):
        w = 1.0 - k / (lags + 1.0)
        v += 2.0 * w * sum(z[i] * z[i - k] for i in range(k, n))
    if v <= 0:
        return None
    se = math.sqrt(v) / sxx
    return b, b / se, n


def _pairs(sig: list, fwd: list, lo: int, hi: int):
    xs, ys = [], []
    for t in range(max(0, lo), min(len(sig), hi)):
        if sig[t] is not None and fwd[t] is not None:
            xs.append(2.0 * sig[t] - 1.0)
            ys.append(fwd[t])
    return xs, ys


def _stat(sig, fwd, lo, hi, lags) -> dict | None:
    xs, ys = _pairs(sig, fwd, lo, hi)
    r = hac_slope(xs, ys, lags)
    if not r:
        return None
    b, t, n = r
    return {"spread": 2.0 * b, "t": t, "n": n}


def _buckets(sig, fwd, lo, hi) -> dict:
    out = {}
    for name, f in (("top", lambda r: r >= 0.8), ("mid", lambda r: 0.2 < r < 0.8), ("bottom", lambda r: r <= 0.2)):
        ys = [fwd[t] for t in range(max(0, lo), min(len(sig), hi)) if sig[t] is not None and fwd[t] is not None and f(sig[t])]
        out[name] = {"mean": sum(ys) / len(ys), "n": len(ys)} if ys else None
    return out


def placebo_null(signals: dict, fwd14: list, lo: int, hi: int, shifts: int = 30, seed: int = 7) -> dict:
    """|t| obtenus avec des signaux decales d'une duree au hasard (au moins 400 jours) : meme forme, plus aucun lien avec le prix."""
    rnd = random.Random(seed)
    ts = []
    for name, sig in signals.items():
        n = len(sig)
        for _ in range(shifts):
            k = rnd.randrange(400, n - 400)
            s2 = sig[k:] + sig[:k]
            r = _stat(s2, fwd14, lo, hi, 16)
            if r:
                ts.append(abs(r["t"]))
    ts.sort()
    q = lambda p: ts[min(len(ts) - 1, int(p * len(ts)))] if ts else None
    return {"n": len(ts), "p50": q(0.5), "p95": q(0.95), "p99": q(0.99)}


def now_reading(od, min_hist: int = 365) -> dict:
    """Derniere valeur connue de chaque indicateur et son rang percentile historique : {cle: {date, value, rank, prev}} ; `prev` = valeur 30 jours plus tot."""
    last = max((t for t, _ in od.cm("btc", "PriceUSD")), default=None)
    if last is None:
        return {}
    first = min((t for t, _ in od.cm("btc", "PriceUSD")), default=last)
    grid, series, _ = ind.build(od, first, last)
    out = {}
    for k, x in series.items():
        r = expanding_rank(x, min_hist)
        j = max((i for i, v in enumerate(x) if v is not None and r[i] is not None), default=None)
        if j is not None:
            prev = x[j - 30] if j >= 30 else None
            out[k] = {"date": grid[j], "value": x[j], "rank": r[j], "prev": prev}
    return out


def evaluate(series: dict, price: list, catalog: dict, grid: list, lo: int, sp: int, horizons=HORIZONS, lag: int = 1, min_hist: int = 365, shifts: int = 30, say=None):
    """Coeur de la mesure, valable pour n'importe quel pas regulier (jour, heure) : (lignes, temoin, seuil, indice du dernier prix connu).
    `lo` = premiere observation evaluee, `sp` = debut du test ; les horizons et le decalage sont en nombre de pas."""
    say = say or (lambda *_: None)
    n = len(grid)
    last_price = max((i for i, v in enumerate(price) if v is not None), default=n - 1)
    ranks = {k: expanding_rank(v, min_hist) for k, v in series.items()}
    fwd = {h: forward_returns(price, h, lag) for h in horizons}
    say("temoin au hasard…")
    mid = horizons[len(horizons) // 2]
    null = placebo_null(ranks, fwd[mid], lo, sp if sp > lo else n, shifts=shifts)
    thr = max(2.5, null["p99"] or 3.0)
    rows = []
    for k, (grp, title, expect, hyp, unit) in catalog.items():
        if k not in ranks:
            continue
        r, row = ranks[k], {"key": k, "group": grp, "title": title, "expect": expect, "hypothesis": hyp, "unit": unit, "h": {}}
        for h in horizons:
            lags = h + 2
            hi_is = max(lo, sp - h - lag - 1)                  # aucune fenetre d'apprentissage ne deborde sur le test
            row["h"][str(h)] = {"all": _stat(r, fwd[h], lo, n, lags), "is": _stat(r, fwd[h], lo, hi_is, lags), "oos": _stat(r, fwd[h], sp, n, lags),
                                "buckets": _buckets(r, fwd[h], lo, n)}
        j = max((i for i, v in enumerate(series[k]) if v is not None and r[i] is not None), default=None)
        row["now"] = {"date": grid[j], "value": series[k][j], "rank": r[j]} if j is not None else None
        best = None
        for h in horizons:
            a, b = row["h"][str(h)]["is"], row["h"][str(h)]["oos"]
            if a and b and a["t"] * b["t"] > 0:
                score = abs(a["t"])
                if best is None or score > best[0]:
                    best = (score, h, a, b)
        row["level"], row["bestH"] = "rien", None
        if best:
            _, h, a, b = best
            row["bestH"] = h
            if abs(a["t"]) >= thr and abs(b["t"]) >= 1.5:
                row["level"] = "informatif"
            elif abs(a["t"]) >= 2.0 and abs(b["t"]) >= 1.0:
                row["level"] = "indice"
        main = row["h"][str(row["bestH"] or mid)]["all"]
        row["expectOk"] = bool(main and expect and (main["spread"] > 0) == (expect > 0))
        rows.append(row)
    order = {"informatif": 0, "indice": 1, "rien": 2}
    rows.sort(key=lambda r: (order[r["level"]], -max((abs(r["h"][str(h)]["is"]["t"]) for h in horizons if r["h"][str(h)]["is"]), default=0)))
    return rows, null, thr, last_price


def run(od, label: str, start_ms: int, end_ms: int, split_ms: int, horizons=HORIZONS, lag: int = 1, min_hist: int = 365, shifts: int = 30, progress=None) -> dict:
    t0 = time.time()
    say = progress or (lambda *_: None)
    say("construction des indicateurs…")
    grid, series, price = ind.build(od, start_ms - 800 * DAY, end_ms)
    n = len(grid)
    lo = next((i for i, t in enumerate(grid) if t >= start_ms), 0)
    sp = next((i for i, t in enumerate(grid) if t >= split_ms), n)
    rows, null, thr, last_price = evaluate(series, price, ind.CATALOG, grid, lo, sp, horizons, lag, min_hist, shifts, say)
    rep = {"kind": "indicators", "label": label, "computedAt": int(time.time() * 1000), "period": {"start": start_ms, "end": grid[last_price] + DAY, "split": split_ms},
           "horizons": list(horizons), "lag": lag, "minHist": min_hist, "null": null, "threshold": thr, "rows": rows,
           "counts": {"indicators": len(rows), "tests": len(rows) * len(horizons), "informative": sum(1 for r in rows if r["level"] == "informatif"), "hints": sum(1 for r in rows if r["level"] == "indice")},
           "seconds": round(time.time() - t0)}
    rep["verdict"] = verdict(rep)
    return rep


def _pct(v, d=1):
    return "n/d" if v is None else f"{v * 100:+.{d}f}".replace(".", ",").replace("-", "−") + " %"


def verdict(rep: dict) -> dict:
    c, nul = rep["counts"], rep["null"]
    inf = [r for r in rep["rows"] if r["level"] == "informatif"]
    hint = [r for r in rep["rows"] if r["level"] == "indice"]
    notes = [f"{c['indicators']} indicateurs × {len(rep['horizons'])} horizons = {c['tests']} mesures. Le témoin (le même signal décalé au hasard) donne |t| ≥ {str(round(nul['p95'], 1)).replace('.', ',')} dans 5 % des cas et "
             f"≥ {str(round(nul['p99'], 1)).replace('.', ',')} dans 1 % : seuil retenu pour « informatif » : {str(round(rep['threshold'], 1)).replace('.', ',')}."]
    ctrl = next((r for r in rep["rows"] if r["key"] == "dist_ma200"), None)
    if ctrl:
        hk = str(max(rep["horizons"]))
        a, b = ctrl["h"][hk]["is"], ctrl["h"][hk]["oos"]
        if a and b:
            tail = ("l'outil détecte un effet connu." if ctrl["level"] == "informatif" else
                    "il reste sous le seuil du témoin : avec une dizaine d'années de données journalières, ce test ne détecte que des effets forts (« pas de preuve » ne veut pas dire « pas d'effet »).")
            notes.append(f"Contrôle positif : l'écart à la moyenne 200 jours (le filtre de tendance du terminal) donne {_pct(a['spread'])} à {hk} jours sur l'apprentissage (t = {str(round(a['t'], 1)).replace('.', ',')}) et "
                         f"{_pct(b['spread'])} sur le test (t = {str(round(b['t'], 1)).replace('.', ',')}) ; {tail}")
    if inf:
        text = f"{len(inf)} indicateur(s) sur {c['indicators']} ont un lien mesurable et stable avec le rendement futur du bitcoin : " + ", ".join(r["title"] for r in inf) + "."
    else:
        text = f"Aucun des {c['indicators']} indicateurs ne dépasse le seuil du hasard à la fois sur l'apprentissage et sur le test."
    if hint:
        text += " À surveiller (indice sans preuve) : " + ", ".join(r["title"] for r in hint) + "."
    return {"text": text, "notes": notes}
