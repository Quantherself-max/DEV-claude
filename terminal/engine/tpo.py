"""TPO (profil de marche, « Time Price Opportunity ») (V17) : pour chaque seance (1 jour, 4 heures ou 1 heure), chaque tranche de temps
recoit une lettre (A, B, C...) et cette lettre est posee sur chaque prix que la tranche a touche. On lit :
  - le POC (prix touche par le plus de tranches) et la zone de valeur (70 % des lettres autour du POC) ;
  - les SINGLE PRINTS : prix touches par une seule tranche, a l'interieur du profil (le prix y est passe vite, sans s'y arreter ; ces zones
    sont souvent revisitees). Au moins MIN_SINGLE lignes de suite ;
  - les QUEUES (excess) : single prints au bord haut ou bas du profil (rejet net : enchere terminee) ;
  - les POOR HIGH / POOR LOW : plus haut (ou plus bas) touche par au moins deux tranches, sans queue (enchere mal terminee : niveau qui
    attire souvent un retour).
Tranches : 30 min pour la seance d'1 jour (00 h UTC), 5 min pour les seances de 4 h et d'1 h. Bougies 5 min. Module PUR."""
import math
from bisect import bisect_left

from .sessionvp import nice_step

MIN = 60_000
H = 60 * MIN
DAY = 24 * H
KINDS = {"D": {"len": DAY, "bracket": 30 * MIN, "label": "1 jour", "n": 10, "rows": 40},
         "4h": {"len": 4 * H, "bracket": 5 * MIN, "label": "4 heures", "n": 12, "rows": 28},
         "1h": {"len": H, "bracket": 5 * MIN, "label": "1 heure", "n": 24, "rows": 18}}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
VA = 0.70
MIN_SINGLE = 2


def brackets(bars, start: int, end: int, bracket_ms: int):
    """[(numero, plus haut, plus bas)] des tranches de la seance [start, end), du plus ancien au plus recent."""
    out = {}
    for k in bars:
        if k.t < start or k.t >= end:
            continue
        i = (k.t - start) // bracket_ms
        b = out.get(i)
        if b is None:
            out[i] = [k.h, k.l]
        else:
            b[0], b[1] = max(b[0], k.h), min(b[1], k.l)
    return [(i, h, l) for i, (h, l) in sorted(out.items())]


def profile(bars, start: int, end: int, bracket_ms: int, step: float, min_single: int = MIN_SINGLE):
    """Profil TPO de la seance. None sans donnees."""
    br = brackets(bars, start, end, bracket_ms)
    if not br or step <= 0:
        return None
    hi, lo = max(b[1] for b in br), min(b[2] for b in br)
    k0 = math.floor(lo / step + 1e-9)
    n = math.floor(hi / step + 1e-9) - k0 + 1
    lets = [[] for _ in range(n)]
    for i, h, l in br:
        for j in range(max(0, math.floor(l / step + 1e-9) - k0), min(n - 1, math.floor(h / step + 1e-9) - k0) + 1):
            lets[j].append(i)
    cnt = [len(x) for x in lets]
    mid = (n - 1) / 2
    poc = max(range(n), key=lambda j: (cnt[j], -abs(j - mid)))
    tot, acc, up, dn = sum(cnt), cnt[poc], poc, poc
    while acc < tot * VA and (up < n - 1 or dn > 0):
        u = cnt[up + 1] if up < n - 1 else -1
        d = cnt[dn - 1] if dn > 0 else -1
        if u >= d:
            up += 1
            acc += cnt[up]
        else:
            dn -= 1
            acc += cnt[dn]
    out = {"start": start, "end": end, "step": step, "high": hi, "low": lo, "brackets": len(br),
           "poc": (k0 + poc + 0.5) * step, "vah": (k0 + up + 1) * step, "val": (k0 + dn) * step,
           "rows": [[round((k0 + j) * step, 10), cnt[j], "".join(LETTERS[i % len(LETTERS)] for i in lets[j])] for j in range(n)],
           "singles": [], "tailHigh": None, "tailLow": None, "poorHigh": False, "poorLow": False}
    if len(br) < 2 or n < 3:
        return out
    top = 0
    while top < n and cnt[n - 1 - top] == 1:
        top += 1
    bot = 0
    while bot < n and cnt[bot] == 1:
        bot += 1
    if top >= n:                                           # tout le profil est en une seule lettre par prix : rien a lire
        return out
    if top >= min_single:
        out["tailHigh"] = [(k0 + n - top) * step, hi]
    if bot >= min_single:
        out["tailLow"] = [lo, (k0 + bot) * step]
    out["poorHigh"] = cnt[n - 1] >= 2                      # au moins deux tranches au plus haut, donc pas de queue
    out["poorLow"] = cnt[0] >= 2
    j = bot
    while j < n - top:
        if cnt[j] == 1:
            s = j
            while j < n - top and cnt[j] == 1:
                j += 1
            if j - s >= min_single:
                out["singles"].append([(k0 + s) * step, (k0 + j) * step])
        else:
            j += 1
    if bracket_ms >= 30 * MIN and len(br) >= 2:            # equilibre initial : les deux premieres tranches (la premiere heure)
        first = [b for b in br if b[0] <= 1]
        out["ib"] = [min(b[2] for b in first), max(b[1] for b in first)]
    return out


def suffix_extremes(bars):
    """Plus bas et plus haut a partir de chaque bougie jusqu'a la fin (pour savoir si une marque a ete comblee depuis)."""
    n = len(bars)
    lo, hi = [math.inf] * (n + 1), [-math.inf] * (n + 1)
    for i in range(n - 1, -1, -1):
        lo[i] = min(lo[i + 1], bars[i].l)
        hi[i] = max(hi[i + 1], bars[i].h)
    return lo, hi


def marks(p: dict, after_lo: float, after_hi: float, current: bool) -> dict:
    """Marques a suivre sur les graphiques : single prints comblees ou non (le prix a traverse toute la zone depuis la fin de la seance),
    poor high / poor low toujours actifs ou repares (depasses depuis)."""
    return {"start": p["start"], "end": p["end"], "current": current,
            "singles": [[a, b, (not current) and after_lo <= a and after_hi >= b] for a, b in p["singles"]],
            "poorHigh": {"price": p["high"], "active": current or not after_hi > p["high"]} if p["poorHigh"] else None,
            "poorLow": {"price": p["low"], "active": current or not after_lo < p["low"]} if p["poorLow"] else None}


def sessions(bars, kind: str, now_ms: int, n: int | None = None, rows: int | None = None, cache: dict | None = None):
    """Profils des n dernieres seances (en cours comprise), du plus ancien au plus recent, chacun avec ses marques ('marks').
    Pas commun a toutes les seances : la mediane de leurs amplitudes divisee par `rows`. `cache` garde les seances terminees."""
    spec = KINDS[kind]
    L, n, rows = spec["len"], n or spec["n"], rows or spec["rows"]
    if not bars:
        return {"kind": kind, "label": spec["label"], "step": None, "sessions": []}
    times = [k.t for k in bars]
    cur = now_ms // L * L
    starts = [s for s in (cur - i * L for i in range(n - 1, -1, -1)) if s + L > times[0]]
    spans = []
    for s in starts:
        i0, i1 = bisect_left(times, s), bisect_left(times, s + L)
        if i1 > i0:
            spans.append((s, i0, i1, max(k.h for k in bars[i0:i1]) - min(k.l for k in bars[i0:i1])))
    if not spans:
        return {"kind": kind, "label": spec["label"], "step": None, "sessions": []}
    rg = sorted(x[3] for x in spans if x[3] > 0) or [1.0]
    step = nice_step(rg[len(rg) // 2] / max(4, rows))
    slo, shi = suffix_extremes(bars)
    if cache is not None and len(cache) > 500:
        cache.clear()
    out = []
    for s, i0, i1, _r in spans:
        current = s == cur
        key = (kind, s, step)
        p = None if current or cache is None else cache.get(key)
        if p is None:
            p = profile(bars[i0:i1], s, s + L, spec["bracket"], step)
            if p is None:
                continue
            if cache is not None and not current:
                cache[key] = p
        out.append({**p, "label": spec["label"], "marks": marks(p, slo[i1], shi[i1], current)})
    return {"kind": kind, "label": spec["label"], "step": step, "sessions": out}
