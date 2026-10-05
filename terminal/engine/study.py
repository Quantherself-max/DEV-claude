"""Etude complete d'une strategie sur un long historique : rapport honnete et reproductible.

Ce que mesure le rapport (tout est calcule avec les seules donnees connues a chaque instant de decision) :
  1. LA STRATEGIE DU TERMINAL (idees de trade) : resultats, par periode (apprentissage / hors echantillon) et par annee, compares a
     l'achat-conservation et a des trades pris AU HASARD avec la meme forme (memes distances, memes frais).
  2. DES VARIANTES (ablations) : structure seule, + portes de liquidite et de contexte, reprises / rebonds, longs / shorts,
     seuils de qualite, accord ou desaccord du CVD, tendance : quel ingredient apporte quelque chose ?
  3. UNE ETUDE D'EVENEMENTS par outil (balayage de liquidite, ecart au VWAP, contact avec un VWAP ou un VWAP ancre, CVD, tendance) :
     que fait le prix apres l'evenement, par rapport au hasard ? Moyenne PAR EVENEMENT, erreur-type robuste par jour, deux periodes.
  4. UN TEST DE REACTION au contact des zones (la zone retient-elle le prix ?), compare a des instants tires au hasard.
  5. LA TENDANCE journaliere (moyennes mobiles) sur tout l'historique, par grande periode.
Module PUR (stdlib) : aucun reseau. Les gros calculs se parallelisent par trimestre (ProcessPoolExecutor) quand les donnees
viennent d'un dossier (chaque processus recharge le dossier)."""
import math
import random
import time
from array import array
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

from . import backtest as bt
from . import cvd, liqsweep
from .backtest import DAY, HOUR, ms

VERSION = 1
NAN = float("nan")

# =====================================================================================================
#  Panel : une ligne toutes les 15 minutes, mesures connues a l'instant + resultats futurs (pour l'etude uniquement)
# =====================================================================================================
COLS = ("t", "px", "atr", "zD", "zW", "zM", "zY", "dD", "dW", "dM", "dY", "avL90", "avH90", "avL365", "avH365", "swL", "swS",
        "imb1", "imb4", "imb24", "div", "absorb", "ret30", "hrD", "hrW", "hrM", "f4", "f24", "fb1")


class Panel:
    def __init__(self):
        self.c = {k: array("d") for k in COLS}
        self.n = 0

    def add(self, row: dict) -> None:
        for k in COLS:
            v = row.get(k)
            self.c[k].append(NAN if v is None else float(v))
        self.n += 1

    def extend(self, other: "Panel") -> None:
        for k in COLS:
            self.c[k].extend(other.c[k])
        self.n += other.n

    def __getitem__(self, k):
        return self.c[k]


def _keyf(kind, t):
    d = t // DAY
    if kind == "D":
        return d
    if kind == "W":
        return (d + 3) // 7
    dt = datetime.fromtimestamp(t / 1000, timezone.utc)
    return dt.year * 12 + dt.month if kind == "M" else dt.year


def _start_of(kind, t):
    d = t // DAY
    if kind == "D":
        return d * DAY
    if kind == "W":
        return ((d + 3) // 7 * 7 - 3) * DAY
    dt = datetime.fromtimestamp(t / 1000, timezone.utc)
    return ms(dt.year, dt.month if kind == "M" else 1, 1)


class _Tr:
    """Plus haut / plus bas courants et precedents d'une periode calendaire (sans profil de volume : tres rapide)."""
    def __init__(self, kind):
        self.kind, self.key, self.hi, self.lo, self.prev, self.start = kind, None, None, None, None, None

    def feed(self, t, h, l):
        k = _keyf(self.kind, t)
        if k != self.key:
            if self.key is not None:
                self.prev = (self.hi, self.lo)
            self.key, self.hi, self.lo, self.start = k, h, l, _start_of(self.kind, t)
        else:
            if h > self.hi:
                self.hi = h
            if l < self.lo:
                self.lo = l


class _AccView:
    """Adaptateur : extremes_from_trackers() attend des objets .prev (dict low/high) et .acc (low, high, start, n)."""
    def __init__(self, tr):
        self.prev = {"low": tr.prev[1], "high": tr.prev[0]} if tr.prev else None
        self.acc = type("A", (), {"n": 1, "low": tr.lo, "high": tr.hi, "start": tr.start})()


def build_panel(ds: "bt.Dataset", start_ms: int, end_ms: int, progress=None) -> Panel:
    b5, b15, b1h = ds.b5, ds.b15, ds.b1h
    trs = {k: _Tr(k) for k in "DWMY"}
    pl = liqsweep.PriceLiquidity(b1h)
    n15 = len(b15.t)
    P = Panel()
    cache = {}
    for i in range(n15):
        t0 = b15.t[i]
        T = int(t0 + 900_000)
        for tr in trs.values():
            tr.feed(t0, b15.h[i], b15.l[i])
        if T >= end_ms:
            break
        if T < start_ms:
            continue
        px = b15.c[i]
        atr = ds.atr_at(T)
        if atr <= 0:
            continue
        i5 = b5.idx_at(T - 1)
        r = {"t": T, "px": px, "atr": atr, "hrD": (T % DAY) / HOUR, "hrW": (T - trs["W"].start) / HOUR, "hrM": (T - trs["M"].start) / HOUR}
        for k, tr in trs.items():
            ia = b5.idx(tr.start)
            vw, sd = b5.vwap(ia, i5 + 1)
            if vw and i5 - ia > 12:
                r["z" + k] = (px - vw) / sd if sd and sd > 0 else 0.0
                r["d" + k] = (px - vw) / atr
        day = T // DAY
        if cache.get("day") != day:
            j1 = b1h.idx_at(T - 1)
            an = {}
            for days in (90, 365):
                j0 = max(0, j1 - days * 24)
                if j1 - j0 < 240:
                    continue
                sl, sh = b1h.l[j0:j1], b1h.h[j0:j1]
                an[f"L{days}"] = int(b1h.t[j0 + sl.index(min(sl))])
                an[f"H{days}"] = int(b1h.t[j0 + sh.index(max(sh))])
            cache["day"], cache["an"] = day, {k: (v, b5.idx(v)) for k, v in an.items()}
        for k, (_, ia) in cache["an"].items():
            if i5 - ia > 24:
                vw, sd = b5.vwap(ia, i5 + 1)
                if vw:
                    r["av" + k] = (px - vw) / atr
        j = i - 30 * 96
        if j >= 0:
            r["ret30"] = px / b15.c[j] - 1.0
        ext = liqsweep.extremes_from_trackers({k: _AccView(trs[k]) for k in "DWM"}, T)
        pools = pl.pools(px, atr, T, ext)
        sw = liqsweep.detect_sweeps([p for p in pools if p["score"] >= 60], b15, i, T, hours=8)
        r["swL"] = max([e["frac"] * 200 for e in sw if e["side"] == "long"], default=0)
        r["swS"] = max([e["frac"] * 200 for e in sw if e["side"] == "short"], default=0)
        an_ = cvd.analyse(b15, i)
        r["imb1"], r["imb4"], r["imb24"] = an_["imb1"], an_["imb4"], an_["imb24"]
        r["div"] = {"bull": 1.0, "bear": -1.0}.get(an_["div"], 0.0)
        r["absorb"] = {"bull": 1.0, "bear": -1.0}.get(an_["absorb"], 0.0)
        for h in (4, 24):
            jj = i + 4 * h
            r[f"f{h}"] = (b15.c[jj] / px - 1.0) if jj < n15 else None
        up, dn = px + atr, px - atr
        res = None
        for jj in range(i + 1, min(n15, i + 193)):
            hu, ld = b15.h[jj] >= up, b15.l[jj] <= dn
            if hu and ld:
                res = 0
                break
            if hu:
                res = 1
                break
            if ld:
                res = -1
                break
        else:
            res = 0 if i + 192 < n15 else None
        r["fb1"] = res
        P.add(r)
        if progress and P.n % 20000 == 0:
            progress(min(0.99, (T - start_ms) / max(1, end_ms - start_ms)), "panel")
    return P


# =====================================================================================================
#  Etude d'evenements
# =====================================================================================================
def _g(P, k, i):
    v = P.c[k][i]
    return None if v != v else v


def _hyp_list():
    """(groupe, nom, direction(P, i) -> +1 | -1 | 0). `hrD` = heures depuis 00:00 UTC (les ecarts au VWAP du jour ne sont fiables qu'apres quelques heures)."""
    H = []

    def add(group, name, fn):
        H.append((group, name, fn))

    for thr in (60, 80, 95):
        add("Balayages de liquidité", f"creux balayé (poche ≥ {thr}) → long", lambda P, i, thr=thr: 1 if P["swL"][i] >= thr else 0)
        add("Balayages de liquidité", f"sommet balayé (poche ≥ {thr}) → short", lambda P, i, thr=thr: -1 if P["swS"][i] >= thr else 0)
    add("Balayages de liquidité", "creux balayé + sous le VWAP du jour → long",
        lambda P, i: 1 if P["swL"][i] >= 60 and P["zD"][i] < -1 and P["hrD"][i] >= 4 else 0)
    add("Balayages de liquidité", "sommet balayé + au-dessus du VWAP du jour → short",
        lambda P, i: -1 if P["swS"][i] >= 60 and P["zD"][i] > 1 and P["hrD"][i] >= 4 else 0)
    # un ecart au VWAP n'a de sens qu'apres quelques heures de la periode (ecart-type encore minuscule au debut) : minimum d'heures ecoulees
    MINH = {"D": ("hrD", 4), "W": ("hrW", 48), "M": ("hrM", 72), "Y": ("hrM", 0)}
    for k, lab in (("D", "jour"), ("W", "semaine"), ("M", "mois"), ("Y", "année")):
        hk, hmin = MINH[k]
        add("Écart au VWAP (retour à la moyenne)", f"VWAP {lab} : −2 σ → long",
            lambda P, i, k=k, hk=hk, hmin=hmin: 1 if P["z" + k][i] <= -2 and P[hk][i] >= hmin else 0)
        add("Écart au VWAP (retour à la moyenne)", f"VWAP {lab} : +2 σ → short",
            lambda P, i, k=k, hk=hk, hmin=hmin: -1 if P["z" + k][i] >= 2 and P[hk][i] >= hmin else 0)
        add("Écart au VWAP (poursuite)", f"VWAP {lab} : +2 σ → long (suivre)",
            lambda P, i, k=k, hk=hk, hmin=hmin: 1 if P["z" + k][i] >= 2 and P[hk][i] >= hmin else 0)
        add("Écart au VWAP (poursuite)", f"VWAP {lab} : −2 σ → short (suivre)",
            lambda P, i, k=k, hk=hk, hmin=hmin: -1 if P["z" + k][i] <= -2 and P[hk][i] >= hmin else 0)
    for k, lab in (("D", "jour"), ("W", "semaine"), ("M", "mois")):
        add("Contact avec un VWAP", f"contact du VWAP {lab} par le haut → long", lambda P, i, k=k: _touch(P, i, "d" + k, 1))
        add("Contact avec un VWAP", f"contact du VWAP {lab} par le bas → short", lambda P, i, k=k: _touch(P, i, "d" + k, -1))
    for k, lab in (("L365", "bas de 1 an"), ("H365", "haut de 1 an"), ("L90", "bas de 3 mois"), ("H90", "haut de 3 mois")):
        add("Contact avec un VWAP ancré", f"AVWAP {lab} touché par le haut → long", lambda P, i, k=k: _touch(P, i, "av" + k, 1))
        add("Contact avec un VWAP ancré", f"AVWAP {lab} touché par le bas → short", lambda P, i, k=k: _touch(P, i, "av" + k, -1))
    add("CVD (flux estimé)", "divergence haussière → long", lambda P, i: 1 if P["div"][i] > 0 else 0)
    add("CVD (flux estimé)", "divergence baissière → short", lambda P, i: -1 if P["div"][i] < 0 else 0)
    add("CVD (flux estimé)", "absorption haussière → long", lambda P, i: 1 if P["absorb"][i] > 0 else 0)
    add("CVD (flux estimé)", "absorption baissière → short", lambda P, i: -1 if P["absorb"][i] < 0 else 0)
    add("CVD (flux estimé)", "acheteurs très dominants (4 h) → long (suivre)", lambda P, i: 1 if P["imb4"][i] > 0.25 else 0)
    add("CVD (flux estimé)", "vendeurs très dominants (4 h) → short (suivre)", lambda P, i: -1 if P["imb4"][i] < -0.25 else 0)
    add("CVD (flux estimé)", "acheteurs très dominants (4 h) → short (retour)", lambda P, i: -1 if P["imb4"][i] > 0.25 else 0)
    add("CVD (flux estimé)", "vendeurs très dominants (4 h) → long (retour)", lambda P, i: 1 if P["imb4"][i] < -0.25 else 0)
    add("Tendance", "au-dessus du VWAP annuel et 30 j > 0 → long", lambda P, i: 1 if P["dY"][i] > 0 and P["ret30"][i] > 0 else 0)
    add("Tendance", "sous le VWAP annuel et 30 j < 0 → short", lambda P, i: -1 if P["dY"][i] < 0 and P["ret30"][i] < 0 else 0)
    return H


def _touch(P, i, k, side):
    """Contact d'un niveau : le prix est a moins de 0,25 ATR du niveau, venu de l'autre cote (> 1 ATR) 2 heures plus tot."""
    if i < 8:
        return 0
    d, p = P[k][i], P[k][i - 8]
    if d != d or p != p:
        return 0
    if side > 0 and abs(d) < 0.25 and p > 1.0:
        return 1
    if side < 0 and abs(d) < 0.25 and p < -1.0:
        return -1
    return 0


def event_study(P: Panel, split_ms: int, gap_h: float = 8.0) -> list[dict]:
    """Pour chaque hypothese : que fait le prix apres l'evenement, par rapport a la derive moyenne du marche dans le meme sens ?
    - exces = rendement dans le sens du trade - derive (moyenne PAR EVENEMENT) ; t = exces / erreur-type robuste (regroupement par jour) ;
    - P(+1 ATR avant -1 ATR) : probabilite que le prix aille d'abord d'1 ATR dans le sens du trade (0,5 = hasard)."""
    n = P.n
    T = P["t"]
    base = {}
    for h in ("f4", "f24"):
        xs = [v for v in P[h] if v == v]
        base[h] = sum(xs) / len(xs) if xs else 0.0
    out = []
    for group, name, fn in _hyp_list():
        ev, last = [], {}
        for i in range(n):
            try:
                d = fn(P, i)
            except (TypeError, KeyError):
                d = 0
            if not d:
                continue
            if T[i] - last.get(d, -1e18) < gap_h * HOUR:
                continue
            last[d] = T[i]
            ev.append((i, d))
        row = {"group": group, "name": name, "n": len(ev)}
        if len(ev) < 30:
            out.append(row)
            continue

        def stat(h, lo, hi):
            xs = [(T[i], d * P[h][i] - d * base[h]) for i, d in ev if P[h][i] == P[h][i] and lo <= T[i] < hi]
            if len(xs) < 20:
                return None
            m = sum(x for _, x in xs) / len(xs)
            cl = {}
            for t, x in xs:
                cl[int(t // DAY)] = cl.get(int(t // DAY), 0.0) + (x - m)
            se = math.sqrt(sum(v * v for v in cl.values())) / len(xs)
            return {"n": len(xs), "ex": m, "t": (m / se) if se > 0 else 0.0}

        def prob(lo, hi):
            u = w = 0
            for i, d in ev:
                v = P["fb1"][i]
                if v != v or v == 0 or not lo <= T[i] < hi:
                    continue
                if v == d:
                    u += 1
                else:
                    w += 1
            return {"n": u + w, "p": u / (u + w)} if u + w >= 30 else None

        big = 2 ** 62
        row["all4"], row["all24"] = stat("f4", 0, big), stat("f24", 0, big)
        row["is24"], row["oos24"] = stat("f24", 0, split_ms), stat("f24", split_ms, big)
        row["p_all"], row["p_is"], row["p_oos"] = prob(0, big), prob(0, split_ms), prob(split_ms, big)
        t_all = row["all24"]["t"] if row["all24"] else 0
        a, b = row["is24"], row["oos24"]
        # « stable » : excedent positif dans les deux periodes, solide sur l'ensemble (t >= 3) ET encore soutenu sur la periode recente (t >= 1)
        row["consistent"] = bool(a and b and a["ex"] > 0 and b["ex"] > 0 and t_all >= 3.0 and b["t"] >= 1.0)
        out.append(row)
    return out


# =====================================================================================================
#  Test de reaction au contact d'une zone (apres l'execution d'un ordre limite sur la zone)
# =====================================================================================================
def _barrier(b, t, sg, fp, atr, k, hours):
    i = b.idx(t)
    up, dn = fp + sg * k * atr, fp - sg * k * atr
    per_h = HOUR / b.step
    for q in range(i, min(len(b.t), i + int(hours * per_h))):
        hi, lo = b.h[q], b.l[q]
        a = (hi >= up) if sg > 0 else (lo <= up)
        c = (lo <= dn) if sg > 0 else (hi >= dn)
        if a and c:
            return 0
        if a:
            return 1
        if c:
            return -1
    return 0


def touch_test(cands: list[dict], ds: "bt.Dataset", start_ms: int, end_ms: int, seed: int = 5, max_n: int = 3000) -> list[dict]:
    """Pour les ordres limites executes sur des zones : probabilite d'aller d'abord k ATR dans le sens du trade avant k ATR contre,
    comparee a des instants tires au hasard (meme sens, meme duree)."""
    rnd = random.Random(seed)
    rows, last = [], {}
    for r in cands:
        s = r.get("sim")
        if not s or not s.get("filled") or r["etype"] != "limite" or not start_ms <= r["t"] < end_ms:
            continue
        kk = (r["side"], r["key"])
        if r["t"] - last.get(kk, -1) < 24 * HOUR:
            continue
        last[kk] = r["t"]
        rows.append(r)
    if len(rows) > max_n:
        rows = rnd.sample(rows, max_n)
    out = []
    groups = [("toutes les zones", lambda r: True), ("qualité élevée (S ≥ 11)", lambda r: r["S"] >= 11), ("qualité faible (S < 9)", lambda r: r["S"] < 9),
              ("zones d'achat (longs)", lambda r: r["side"] == "long"), ("zones de vente (shorts)", lambda r: r["side"] == "short"),
              ("reprises après balayage", lambda r: r["kind"] == "reprise"), ("rebonds simples", lambda r: r["kind"] == "rebond")]
    for k, hours in ((0.5, 4), (1.0, 12), (2.0, 48)):
        for gname, f in groups:
            sel = [r for r in rows if f(r)]
            if len(sel) < 40:
                continue
            w = l = wb = lb = 0
            for r in sel:
                sg = 1 if r["side"] == "long" else -1
                s = r["sim"]
                v = _barrier(ds.b5, s["fill_t"], sg, s["fill_px"], r["atr"], k, hours)
                w, l = w + (v > 0), l + (v < 0)
                t = rnd.randrange(start_ms, max(start_ms + 1, end_ms - 3 * DAY))
                j = ds.b5.idx_at(t)
                a = ds.atr_at(t)
                if j < 0 or a <= 0:
                    continue
                u = _barrier(ds.b5, t, sg, ds.b5.c[j], a, k, hours)
                wb, lb = wb + (u > 0), lb + (u < 0)
            if w + l < 30 or wb + lb < 30:
                continue
            p, pb = w / (w + l), wb / (wb + lb)
            se = math.sqrt(0.25 / (w + l) + 0.25 / (wb + lb))
            out.append({"name": gname, "k": k, "hours": hours, "n": len(sel), "p": p, "pBase": pb, "diff": p - pb, "sigma": (p - pb) / se})
    return out


# =====================================================================================================
#  Tendance journaliere sur tout l'historique
# =====================================================================================================
def regime_table(ds: "bt.Dataset", periods: list[tuple[str, int, int]], cost: float = 0.0007) -> list[dict]:
    """Strategies de tendance a 1 position (levier 1) sur les bougies 1 h : CAGR, pire baisse, Sharpe par periode."""
    b = ds.b1h
    c, t = list(b.c), list(b.t)
    n = len(c)

    def sma(days):
        L = days * 24
        out, run = [None] * n, 0.0
        for j in range(n):
            run += c[j]
            if j >= L:
                run -= c[j - L]
            if j >= L - 1:
                out[j] = run / L
        return out

    S = {d: sma(d) for d in (50, 100, 200)}
    strategies = [
        ("acheter-conserver", lambda j: 1.0),
        ("long si au-dessus de la moyenne 200 j, sinon liquidités", lambda j: 1.0 if S[200][j] is not None and c[j] > S[200][j] else 0.0),
        ("long si au-dessus des moyennes 50 j ET 200 j", lambda j: 1.0 if S[200][j] is not None and c[j] > S[200][j] and c[j] > S[50][j] else 0.0),
        ("long si au-dessus de la moyenne 100 j", lambda j: 1.0 if S[100][j] is not None and c[j] > S[100][j] else 0.0),
    ]
    sigs = [[fn(j) for j in range(n)] for _, fn in strategies]
    out = []
    for (name, _), sig in zip(strategies, sigs):
        row = {"name": name, "periods": []}
        for lab, a, z in periods:
            i0, i1 = bisect_left(t, a), bisect_left(t, z)
            if i1 - i0 < 24 * 90:
                row["periods"].append({"label": lab})
                continue
            eq, peak, dd, rets, prev_pos = 1.0, 1.0, 0.0, [], 0.0
            changes = 0
            for j in range(i0, i1 - 1):
                pos = sig[j]
                r = pos * (c[j + 1] / c[j] - 1.0) - abs(pos - prev_pos) * cost
                changes += abs(pos - prev_pos)
                prev_pos = pos
                eq *= 1.0 + r
                peak = max(peak, eq)
                dd = max(dd, 1.0 - eq / peak)
                rets.append(r)
            yrs = len(rets) / (24 * 365.25)
            mu = sum(rets) / len(rets)
            sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (len(rets) - 1))
            row["periods"].append({"label": lab, "cagr": eq ** (1 / yrs) - 1, "maxDD": dd, "sharpe": mu / sd * math.sqrt(24 * 365) if sd > 0 else None,
                                   "changesPerYear": changes / 2 / yrs})
        out.append(row)
    return out


# =====================================================================================================
#  Variantes de la strategie
# =====================================================================================================
def _base(r):
    return r["gates"] == 0 and r["hold"] == 0


def variants():
    """(nom, regle, seuil de score ou None). Deux familles : SANS puis AVEC le filtre « dans le sens de la tendance de fond »."""
    sgn = lambda r: 1 if r["side"] == "long" else -1
    al = lambda r: _base(r) and r.get("reg") == sgn(r)
    return [
        ("Structure seule (toutes les idées de confluence)", lambda r: True, None),
        ("Qualité de structure ≥ 11", lambda r: _base(r) and r["S"] >= 11, None),
        ("Reprises après balayage seulement", lambda r: _base(r) and r["kind"] == "reprise", None),
        ("Rebonds simples seulement", lambda r: _base(r) and r["kind"] == "rebond", None),
        ("Longs seulement", lambda r: _base(r) and r["side"] == "long", None),
        ("Shorts seulement", lambda r: _base(r) and r["side"] == "short", None),
        ("CVD dans le sens du trade", lambda r: _base(r) and r["fs"] * sgn(r) > 0.1, None),
        (LEGACY, lambda r: _base(r) and r["score"] >= 60, 60),
        ("Contre la tendance de fond", lambda r: _base(r) and r.get("reg") == -sgn(r), None),
        ("Tendance de fond indécise", lambda r: _base(r) and r.get("reg") == 0, None),
        ("Dans le sens de la tendance de fond", al, None),
        ("… et qualité de structure ≥ 9", lambda r: al(r) and r["S"] >= 9, None),
        ("… et qualité de structure ≥ 11", lambda r: al(r) and r["S"] >= 11, None),
        ("… et reprise après balayage", lambda r: al(r) and r["kind"] == "reprise", None),
        ("… et rebond simple", lambda r: al(r) and r["kind"] == "rebond", None),
        ("… et ordre limite", lambda r: al(r) and r["etype"] == "limite", None),
        ("… et CVD dans le sens du trade", lambda r: al(r) and r["fs"] * sgn(r) > 0.1, None),
        ("… achats seulement", lambda r: al(r) and r["side"] == "long", None),
        ("… ventes seulement", lambda r: al(r) and r["side"] == "short", None),
        (CURRENT, lambda r: al(r) and r["score"] >= 60, 60),
        ("… score du terminal ≥ 70", lambda r: al(r) and r["score"] >= 70, 70),
    ]


LEGACY = "Ancienne règle : score ≥ 60, sans filtre de tendance"
CURRENT = "Règle actuelle : score ≥ 60 ET dans le sens de la tendance de fond"


def _slim(m: dict) -> dict:
    keys = ("n", "winRate", "expR", "expLo", "expHi", "pf", "ret", "cagr", "maxDD", "sharpe", "perWeek", "exposure", "tstat", "avgWin", "avgLoss")
    return {k: m.get(k) for k in keys}


def run_variants(cands, costs, start_ms, end_ms, eras, years):
    out = []
    for name, rule, thr in variants():
        row = {"name": name}
        trs = bt.select(cands, rule, costs, thr=thr, start_ms=start_ms, end_ms=end_ms)
        row["all"] = _slim(bt.metrics(trs, start_ms, end_ms))
        row["eras"] = []
        for lab, a, z in eras:
            sub = [t for t in trs if a <= t["t"] < z]
            row["eras"].append({"label": lab, **_slim(bt.metrics(sub, a, z))})
        yrs = {}
        for y in years:
            a, z = ms(y), min(ms(y + 1), end_ms)
            sub = [t for t in trs if a <= t["t"] < z]
            if sub:
                yrs[str(y)] = round(sum(t["r"] for t in sub) / len(sub), 3)
        row["years"] = yrs
        out.append((row, trs))
    return out


# =====================================================================================================
#  Execution parallele (par trimestre)
# =====================================================================================================
_DS = None


def _init_worker(folder):
    global _DS
    _DS = bt.Dataset.load(folder)


def _gen_chunk(args):
    a, b, opts = args
    return bt.generate(_DS, a, b, opts)


def _panel_chunk(args):
    a, b = args
    return build_panel(_DS, a, b)


def quarters(start_ms, end_ms):
    out = []
    d = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    y, m = d.year, 1 + 3 * ((d.month - 1) // 3)
    while ms(y, m) < end_ms:
        ny, nm = (y, m + 3) if m + 3 <= 12 else (y + 1, m + 3 - 12)
        out.append((max(ms(y, m), start_ms), min(ms(ny, nm), end_ms)))
        y, m = ny, nm
    return out


def _map(fn, args, folder, ds, workers):
    if folder and workers > 1:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(folder,)) as ex:
            return list(ex.map(fn, args, chunksize=1))
    global _DS
    _DS = ds
    return [fn(a) for a in args]


# =====================================================================================================
#  Rapport
# =====================================================================================================
def run(ds: "bt.Dataset", label: str, start_ms: int, end_ms: int, split_ms: int, folder: str | None = None, workers: int = 1,
        control_runs: int = 100, costs: dict | None = None, progress=None, source_note: str = "", panel: bool = True,
        eras: list | None = None) -> dict:
    """Rapport complet (dict serialisable en JSON). Les `eras` [(libelle, debut, fin)] decoupent les resultats ; split_ms separe
    l'apprentissage de l'hors-echantillon pour l'etude d'evenements."""
    costs = costs or bt.DEFAULT_COSTS
    t0 = time.time()
    say = (lambda f, m: progress(f, m)) if progress else (lambda f, m: None)
    year_of = lambda t: datetime.fromtimestamp(t / 1000, timezone.utc).year
    if not eras:
        eras = [("avant " + str(year_of(split_ms)), start_ms, split_ms), ("depuis " + str(year_of(split_ms)), split_ms, end_ms)]
    qs = quarters(start_ms, end_ms)
    say(0.02, "génération des idées de trade")
    parts = _map(_gen_chunk, [(a, b, None) for a, b in qs], folder, ds, workers)
    cands = [x for p in parts for x in p]
    say(0.40, "simulation des trades (bougies 1 minute)")
    bt.attach_outcomes(cands, ds)
    say(0.52, "variantes")
    years = list(range(year_of(start_ms), year_of(end_ms - 1) + 1))
    vr = run_variants(cands, costs, start_ms, end_ms, eras, years)
    byname = {row["name"]: (row, tr) for row, tr in vr}
    cur_row, cur_trades = byname[CURRENT]
    leg_row, leg_trades = byname[LEGACY]
    al_row, al_trades = byname["Dans le sens de la tendance de fond"]
    co_row, _ = byname["Contre la tendance de fond"]
    ne_row, _ = byname["Tendance de fond indécise"]
    ma = bt.regime_series(ds.b1h)
    say(0.60, "témoins : trades au hasard de même forme")
    ctrl_un = bt.random_control([t["c"] for t in cur_trades], ds, costs, start_ms, end_ms, runs=control_runs) if cur_trades else {}
    ctrl_tr = bt.random_control([t["c"] for t in cur_trades], ds, costs, start_ms, end_ms, runs=control_runs, seed=4, match_regime=True, ma=ma) if cur_trades else {}
    ex_un, ex_tr = ctrl_un.pop("_exps", []), ctrl_tr.pop("_exps", [])
    real = cur_row["all"]["expR"]
    p_un = bt.percentile_of(ex_un, real) if ex_un and real is not None else None
    p_tr = bt.percentile_of(ex_tr, real) if ex_tr and real is not None else None
    gross = (sum(t["r_gross"] for t in cur_trades) / len(cur_trades)) if cur_trades else None
    bh = bt.buy_hold(ds, start_ms, end_ms)
    m_all = bt.metrics(cur_trades, start_ms, end_ms)
    eq_bh = []
    b1h = ds.b1h
    i0, i1 = b1h.idx(start_ms), b1h.idx(end_ms)
    step = max(1, (i1 - i0) // 400)
    for j in range(i0, i1, step):
        eq_bh.append((int(b1h.t[j]), round(b1h.c[j] / b1h.c[i0], 4)))
    say(0.72, "sensibilité aux frais")
    sens = []
    for lab, mult in (("sans frais", 0.0), ("frais prévus", 1.0), ("frais doublés", 2.0)):
        cc = {k: v * mult for k, v in costs.items()}
        tr = bt.select(cands, lambda r: _base(r) and r.get("reg") == (1 if r["side"] == "long" else -1) and r["score"] >= 60, cc, thr=60, start_ms=start_ms, end_ms=end_ms)
        mm = bt.metrics(tr, start_ms, end_ms)
        sens.append({"name": lab, "n": mm["n"], "expR": mm.get("expR"), "ret": mm.get("ret")})
    say(0.76, "réaction aux zones")
    touch = touch_test(cands, ds, start_ms, end_ms)
    say(0.80, "tendance de fond sur tout l'historique")
    reg_eras = [(lab, a, z) for lab, a, z in eras if a >= ds.b1h.t[0] + 220 * DAY]
    reg = regime_table(ds, reg_eras + [("tout l'historique", reg_eras[0][1], end_ms)]) if reg_eras else []
    events = []
    if panel:
        say(0.84, "étude d'événements par outil")
        pparts = _map(_panel_chunk, qs, folder, ds, workers)
        P = Panel()
        for p in pparts:
            P.extend(p)
        events = event_study(P, split_ms)
    say(0.97, "synthèse")
    n_sig = [e for e in events if e.get("consistent")]
    ci_lo = cur_row["all"]["expLo"]
    edge = bool(ci_lo is not None and ci_lo > 0 and real and real > 0 and p_un is not None and p_un < 0.05)
    levels_add = bool(p_tr is not None and p_tr < 0.05)
    f2 = lambda x: "n/a" if x is None else f"{x:+.2f}".replace(".", ",")
    notes = []
    if al_row["all"]["expR"] is not None and co_row["all"]["expR"] is not None:
        notes.append(f"Tendance de fond : les idées dans son sens rapportent {f2(al_row['all']['expR'])} fois le risque par trade après frais "
                     f"({al_row['all']['n']} trades), celles à contre-courant {f2(co_row['all']['expR'])} ({co_row['all']['n']} trades), celles en tendance indécise {f2(ne_row['all']['expR'])}.")
    if leg_row["all"]["expR"] is not None:
        notes.append(f"Sans ce filtre (ancienne règle du terminal) : {f2(leg_row['all']['expR'])} par trade, c'est-à-dire perdant une fois les frais comptés.")
    if p_un is not None and p_tr is not None:
        notes.append(f"Face à des entrées au hasard de même forme : la règle actuelle fait mieux dans {100 * (1 - p_un):.0f} % des tirages ; "
                     f"mais face à des entrées au hasard prises DANS LA MÊME TENDANCE ({f2(ctrl_tr['expMean'])} en moyenne) seulement dans {100 * (1 - p_tr):.0f} % : "
                     + ("les niveaux apportent un plus significatif." if levels_add else "la tendance explique l'essentiel de l'avantage, les niveaux (liquidité, VWAP, profils) n'apportent qu'un petit plus non démontré."))
    if gross is not None and real is not None:
        notes.append(f"Les frais, le glissement et le financement coûtent environ {f2(gross - real).lstrip('+')} fois le risque par trade (avant frais : {f2(gross)}).")
    if n_sig:
        notes.append("Outils dont l'effet est de même sens sur les deux périodes et significatif : " + "; ".join(e["name"] for e in n_sig[:6]) + ".")
    else:
        notes.append("Aucun outil pris isolément (balayage, écart au VWAP, VWAP ancré, CVD) ne montre un effet à la fois significatif et de même sens sur les deux périodes.")
    recent = cur_row["eras"][-1] if cur_row["eras"] else None
    recent_edge = bool(recent and recent["expLo"] is not None and recent["expLo"] > 0)
    if recent and recent["expR"] is not None:
        notes.insert(1, f"Sur la période la plus récente ({recent['label']}) : {f2(recent['expR'])} fois le risque par trade ({recent['n']} trades, intervalle à 90 % de "
                        f"{f2(recent['expLo'])} à {f2(recent['expHi'])}). " + ("L'avantage y est encore démontré." if recent_edge else
                        "L'avantage n'y est plus démontré : il s'est affaibli avec le temps (marché plus mûr), prudence."))
    if edge and recent_edge:
        verdict = "Avantage statistique modeste, démontré sur l'ensemble de l'historique et encore sur la période récente."
    elif edge:
        verdict = (f"Avantage modeste sur l'ensemble de l'historique, mais PLUS démontré sur la période récente ({recent['label']}) : "
                   "il vient surtout de la tendance de fond et s'est affaibli avec le temps.") if recent else "Avantage statistique modeste sur l'ensemble de l'historique."
    else:
        verdict = "Aucun avantage démontré : la règle ne bat pas des entrées au hasard une fois les frais comptés."
    best = max((row for row, _ in vr), key=lambda r: (r["all"]["expR"] if r["all"]["expR"] is not None and r["all"]["n"] >= 100 else -9))
    return {"version": VERSION, "label": label, "source": source_note, "computedAt": int(time.time() * 1000), "seconds": round(time.time() - t0),
            "period": {"start": start_ms, "end": end_ms, "split": split_ms}, "eras": [{"label": l, "start": a, "end": z} for l, a, z in eras],
            "costs": costs, "candidates": len(cands),
            "verdict": {"edge": edge, "recentEdge": recent_edge, "levelsAdd": levels_add, "text": verdict, "notes": notes},
            "trend": {"aligned": al_row["all"], "counter": co_row["all"], "neutral": ne_row["all"], "alignedEras": al_row["eras"], "counterEras": co_row["eras"]},
            "terminal": {"name": CURRENT, **{k: cur_row[k] for k in ("all", "eras", "years")}, "grossR": gross, "pValue": p_un, "pValueTrend": p_tr,
                         "control": ctrl_un, "controlTrend": ctrl_tr, "buyHold": bh, "equity": m_all.get("equity", []), "equityBuyHold": eq_bh,
                         "legacy": {"name": LEGACY, **{k: leg_row[k] for k in ("all", "eras", "years")}}},
            "variants": [row for row, _ in vr], "bestVariant": best["name"], "costSens": sens, "events": events, "touch": touch, "regime": reg,
            "eventThreshold": 3.0}
