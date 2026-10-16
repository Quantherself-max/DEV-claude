"""Probabilites MESUREES sur l'historique de l'actif (bougies 1h fermees), pas inventees.

1) Reaction au contact d'un niveau. On rejoue l'historique bougie par bougie avec les niveaux connus a chaque
   instant (VWAP J/S/M et bandes +-2 sigma, opens, plus hauts/bas precedents, POC/VAH/VAL precedents, POC nus,
   nombres ronds) et des niveaux TIRES AU HASARD (temoin). Un "test de support" : la cloture precedente est
   au-dessus du niveau et la bougie suivante le touche. Issue sur les `horizon` bougies suivantes :
     rebond  = une cloture repasse a +k ATR du niveau (cote d'arrivee) avant une cloture a -k ATR ;
     cassure = l'inverse ;  sinon : indecis (exclu du pourcentage, compte a part).
   Avec des seuils symetriques, un marche sans memoire donne ~50 % : le temoin "hasard" sert de reference.
   Resultats par famille de niveau, par nombre de sources en confluence (1, 2, 3+), et selon le flux
   acheteur/vendeur de la bougie de contact (volume agressif reel).
2) Probabilite d'atteinte : frequence historique a laquelle le prix a atteint une distance de d ATR (1h)
   au-dessus / en dessous dans les H heures suivantes.
Les pourcentages viennent avec leur effectif n et un intervalle de confiance a 90 % (Wilson)."""
import math
import random
from bisect import bisect_left
from collections import deque

from .periods import NakedPocs, PeriodTracker

Z90 = 1.645
REACH_DISTS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)
REACH_HOURS = (4, 24, 72)
FAMILIES = ("VWAP", "Bandes VWAP 2σ", "Opens", "Haut/bas veille", "Haut/bas semaine préc.", "Haut/bas mois préc.",
            "POC précédent", "VAH/VAL précédent", "POC nus", "Nombres ronds", "Hasard (témoin)")
P = {"D": "d", "W": "w", "M": "m"}
HL_FAM = {"D": "Haut/bas veille", "W": "Haut/bas semaine préc.", "M": "Haut/bas mois préc."}
HL_GRP = {"D": "PDHL", "W": "PWHL", "M": "PMHL"}


def wilson(k: int, n: int, z: float = Z90):
    if n <= 0:
        return None, None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)


def atr_series(candles, n: int = 14):
    """ATR de Wilder pour chaque bougie (moyenne simple tant qu'il y a moins de n bougies)."""
    out, a, prev, acc = [], 0.0, None, 0.0
    for idx, k in enumerate(candles):
        tr = k.h - k.l if prev is None else max(k.h - k.l, abs(k.h - prev), abs(k.l - prev))
        prev = k.c
        if idx < n:
            acc += tr
            a = acc / (idx + 1)
        else:
            a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


def sd_series(candles, window: int = 48):
    """Ecart-type glissant des variations de cloture d'une bougie a l'autre (en prix)."""
    out, q, s1, s2 = [], deque(), 0.0, 0.0
    prev = None
    for k in candles:
        if prev is not None:
            d = k.c - prev
            q.append(d)
            s1 += d
            s2 += d * d
            if len(q) > window:
                x = q.popleft()
                s1 -= x
                s2 -= x * x
        prev = k.c
        n = len(q)
        out.append(math.sqrt(max(s2 / n - (s1 / n) ** 2, 0.0)) if n >= 2 else 0.0)
    return out


RHO = 0.5826      # depassement moyen d'une marche gaussienne discrete au-dela d'un seuil (Siegmund), en ecarts-types


def round_step(price: float) -> float:
    return 10 ** math.floor(math.log10(price)) / 2.0


def _known_levels(tr, nd, nw, rand_lv, price):
    """Niveaux connus a la cloture de la bougie courante : (cle, famille, groupe, prix)."""
    out = []
    for kind in ("D", "W", "M"):
        t = tr[kind]
        p = P[kind]
        a = t.acc
        vw, sd = a.vwap()
        if vw is not None:
            out.append((f"{p}VWAP", "VWAP", f"{p}VWAP", vw))
            if sd:
                out.append((f"{p}VWAP+2", "Bandes VWAP 2σ", f"{p}VWAP", vw + 2 * sd))
                out.append((f"{p}VWAP-2", "Bandes VWAP 2σ", f"{p}VWAP", vw - 2 * sd))
        if a.open is not None:
            out.append((f"{p}Open", "Opens", f"{p}Open", a.open))
        pv = t.prev
        if pv:
            out.append((f"P{kind}H", HL_FAM[kind], HL_GRP[kind], pv["high"]))
            out.append((f"P{kind}L", HL_FAM[kind], HL_GRP[kind], pv["low"]))
            if pv["vp"]:
                g = f"p{p}VP"
                out.append((f"p{p}POC", "POC précédent", g, pv["vp"]["poc"]))
                out.append((f"p{p}VAH", "VAH/VAL précédent", g, pv["vp"]["vah"]))
                out.append((f"p{p}VAL", "VAH/VAL précédent", g, pv["vp"]["val"]))
    for tag, nk in (("d", nd), ("w", nw)):
        for x in nk.active():
            if abs(x["poc"] / price - 1) < 0.15:
                out.append((f"n{tag}{x['t_end']}", "POC nus", "nPOC", x["poc"]))
    step = round_step(price)
    base = math.floor(price / step)
    for m in range(base - 1, base + 3):
        out.append((f"R{m}", "Nombres ronds", "ROUND", m * step))
    for key, v in rand_lv:
        out.append((key, "Hasard (témoin)", "RAND", v))
    return out


def _summ(c):
    if not c:
        return {"n": 0, "bounce": 0, "break": 0, "p": None, "lo": None, "hi": None}
    n, b, x = c[0], c[1], c[2]
    p, lo, hi = wilson(b, n)
    out = {"n": n, "bounce": b, "break": x, "p": p, "lo": lo, "hi": hi}
    if len(c) > 3 and c[3] and n:
        out["expected"] = c[3] / n          # taux attendu par la seule position du prix (sans effet)
    return out


def outcome_at(candles, j: int, level: float, side: str, atr: float, horizon: int, kb: float, kx: float):
    """Issue d'un contact a la bougie j : 'bounce' | 'break' | 'open' (indecis ou horizon pas encore ecoule)."""
    up, dn = level + kb * atr, level - kx * atr
    if side == "resistance":
        up, dn = level + kx * atr, level - kb * atr
    end = min(len(candles), j + horizon)
    for q in range(j, end):
        c = candles[q].c
        if side == "support":
            if c >= up:
                return "bounce"
            if c <= dn:
                return "break"
        else:
            if c <= dn:
                return "bounce"
            if c >= up:
                return "break"
    return "open"


def reaction_stats(candles, horizon: int = 24, kb: float = 1.0, kx: float = 1.0, touch_atr: float = 0.15,
                   conf_atr: float = 0.30, conf_min_pct: float = 0.15, warmup: int = 24 * 35, seed: int = 7,
                   atrs=None):
    """Rejoue l'historique (bougies 1h FERMEES, ordre chronologique). Renvoie des comptes par famille,
    par score de confluence et par flux, chacun separe support / resistance."""
    atrs = atrs or atr_series(candles)
    sds = sd_series(candles)
    tr = {k: PeriodTracker(k) for k in ("D", "W", "M")}
    nd, nw = NakedPocs(30), NakedPocs(12)
    rnd = random.Random(seed)
    rand_lv: list[tuple] = []
    last_evt: dict[str, int] = {}
    cnt: dict[str, list] = {}
    undecided: dict[str, int] = {}
    events = 0
    n = len(candles)
    for i in range(n - 1):
        k = candles[i]
        prev_d, prev_w = tr["D"].prev, tr["W"].prev
        for t in tr.values():
            t.feed(k)
        if tr["D"].prev is not prev_d and tr["D"].prev:
            nd.on_rollover(tr["D"].prev["vp"]["poc"] if tr["D"].prev["vp"] else None, k.t)
            for s in (+1, -1):                                      # temoin : 2 niveaux au hasard par jour
                rand_lv.append((f"X{k.t}{s}", k.c * (1 + s * rnd.uniform(0.004, 0.03))))
            rand_lv = rand_lv[-14:]
        if tr["W"].prev is not prev_w and tr["W"].prev:
            nw.on_rollover(tr["W"].prev["vp"]["poc"] if tr["W"].prev["vp"] else None, k.t)
        nd.feed(k)
        nw.feed(k)
        if i < warmup:
            continue
        a = atrs[i]
        if not a or a <= 0:
            continue
        nxt = candles[i + 1]
        tol = touch_atr * a
        levels = _known_levels(tr, nd, nw, rand_lv, k.c)
        for key, fam, grp, L in levels:
            if k.c > L + tol and nxt.l <= L + tol:
                side = "support"
            elif k.c < L - tol and nxt.h >= L - tol:
                side = "resistance"
            else:
                continue
            j = i + 1
            if j - last_evt.get(key, -10 ** 9) < horizon:            # un meme niveau ne compte qu'une fois par horizon
                continue
            last_evt[key] = j
            res = outcome_at(candles, j, L, side, a, horizon, kb, kx)
            if res == "open" and j + horizon > n:
                continue                                              # horizon pas encore ecoule : ignore
            events += 1
            ctol = max(conf_atr * a, conf_min_pct / 100.0 * L)
            groups = {g for (_, _, g, p) in levels if g != "RAND" and abs(p - L) <= ctol}
            score = len(groups) if grp != "RAND" else 0
            keys = [f"family|{fam}|{side}", f"family|{fam}|all"]
            flow_keys, res_flow = [], None
            if grp != "RAND":
                b = "3+" if score >= 3 else str(max(score, 1))
                keys += [f"score|{b}|{side}", f"score|{b}|all"]
                v, tb = nxt.v, nxt.tb
                # Le flux (volume agressif) de la bougie de contact n'est connu qu'a sa CLOTURE : l'issue
                # conditionnelle se mesure donc a partir de la bougie suivante (sinon on triche avec l'avenir).
                up, dn = (L + kb * a, L - kx * a) if side == "support" else (L + kx * a, L - kb * a)
                if v > 0 and tb > 0 and dn < nxt.c < up:
                    delta = 2 * tb - v
                    with_flow = (delta > 0) if side == "support" else (delta < 0)
                    fl = "avec" if with_flow else "contre"
                    res_flow = outcome_at(candles, j + 1, L, side, a, horizon, kb, kx)
                    if not (res_flow == "open" and j + 1 + horizon > n):
                        flow_keys = [f"flow|{fl}|{side}", f"flow|{fl}|all"]
            # taux "attendu" sans aucun effet : depuis la cloture de contact, une marche sans memoire touche le
            # seuil de rebond avec une probabilite (x - bas) / (haut - bas). Seul l'ecart a ce taux est un signal.
            p0 = None
            if flow_keys:
                ov = RHO * sds[j]                      # correction de depassement (les clotures sautent les seuils)
                x = (nxt.c - dn) if side == "support" else (up - nxt.c)
                p0 = min(1.0, max(0.0, (x + ov) / (up - dn + 2 * ov)))
            for key2, r, e in [(k2, res, None) for k2 in keys] + [(k2, res_flow, p0) for k2 in flow_keys]:
                if r == "open":
                    undecided[key2] = undecided.get(key2, 0) + 1
                else:
                    c = cnt.setdefault(key2, [0, 0, 0, 0.0])
                    c[0] += 1
                    c[1 if r == "bounce" else 2] += 1
                    if e is not None:
                        c[3] += e
    out = {"family": {}, "score": {}, "flow": {}}
    for key, c in cnt.items():
        typ, name, side = key.split("|")
        s = _summ(c)
        s["undecided"] = undecided.get(key, 0)
        out[typ].setdefault(name, {})[side] = s
    for key, u in undecided.items():
        typ, name, side = key.split("|")
        out[typ].setdefault(name, {}).setdefault(side, {**_summ(None), "undecided": u})
    out["meta"] = {"bars": n, "events": events, "horizon": horizon, "kb": kb, "kx": kx, "touch_atr": touch_atr,
                   "from": candles[min(warmup, n - 1)].t if n else None, "to": candles[-1].t if n else None}
    return out


def _fwd_extreme(vals, horizon: int, use_max: bool):
    """Pour chaque i : max (ou min) de vals[i+1 .. i+horizon] (None si la fenetre est incomplete)."""
    n = len(vals)
    out = [None] * n
    dq: deque = deque()
    for i in range(n - 1, -1, -1):
        j_new = i + 1
        if j_new < n:
            while dq and ((vals[dq[-1]] <= vals[j_new]) if use_max else (vals[dq[-1]] >= vals[j_new])):
                dq.pop()
            dq.append(j_new)
        while dq and dq[0] > i + horizon:
            dq.popleft()
        if i + horizon < n and dq:
            out[i] = vals[dq[0]]
    return out


def reach_table(candles, atrs=None, hours=REACH_HOURS, dists=REACH_DISTS, warmup: int = 24 * 14):
    """Frequence historique d'atteinte d'une distance d (en ATR 1h) au-dessus / en dessous en H heures."""
    atrs = atrs or atr_series(candles)
    highs = [k.h for k in candles]
    lows = [k.l for k in candles]
    tab = {"dists": list(dists), "hours": list(hours), "up": {}, "down": {}, "n": {}}
    for H in hours:
        fmax = _fwd_extreme(highs, H, True)
        fmin = _fwd_extreme(lows, H, False)
        up = [0] * len(dists)
        dn = [0] * len(dists)
        n = 0
        for i in range(warmup, len(candles)):
            if fmax[i] is None or not atrs[i]:
                continue
            a, c = atrs[i], candles[i].c
            u, d = (fmax[i] - c) / a, (c - fmin[i]) / a
            n += 1
            for q, dd in enumerate(dists):
                if u >= dd:
                    up[q] += 1
                if d >= dd:
                    dn[q] += 1
        tab["n"][str(H)] = n
        tab["up"][str(H)] = [x / n if n else None for x in up]
        tab["down"][str(H)] = [x / n if n else None for x in dn]
    return tab


def reach_prob(tab, dist_atr: float, direction: str, hours: int):
    """Interpolation lineaire dans la table ; direction 'up' ou 'down'."""
    if not tab or str(hours) not in tab[direction]:
        return None
    ys = tab[direction][str(hours)]
    xs = tab["dists"]
    if ys[0] is None:
        return None
    if dist_atr <= 0:
        return 1.0
    if dist_atr <= xs[0]:
        return ys[0] + (1.0 - ys[0]) * (1 - dist_atr / xs[0])
    if dist_atr >= xs[-1]:
        return ys[-1]
    q = bisect_left(xs, dist_atr)
    x0, x1, y0, y1 = xs[q - 1], xs[q], ys[q - 1], ys[q]
    return y0 + (y1 - y0) * (dist_atr - x0) / (x1 - x0)


def sweep_outcomes(events, candles, atrs, horizon: int = 24, k: float = 1.0):
    """Issue des balayages de poches de liquidation (journal du moteur OI) : 'bounce' = le prix repart a
    +k ATR du niveau balaye (retournement), 'break' = continue a -k ATR (cascade), 'open' = en cours."""
    times = [c.t for c in candles]
    res, cnt = [], [0, 0, 0]
    for e in events:
        j = bisect_left(times, e["t"])
        if j >= len(candles):
            res.append({**e, "result": "open"})
            continue
        side = "support" if e["side"] == "long" else "resistance"
        a = atrs[max(0, j - 1)] or atrs[j]
        r = outcome_at(candles, j, e["price"], side, a, horizon, k, k)
        if r != "open":
            cnt[0] += 1
            cnt[1 if r == "bounce" else 2] += 1
        res.append({**e, "result": r})
    return _summ(cnt), res
