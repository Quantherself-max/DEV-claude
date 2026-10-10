"""Mesure TPO sur l'historique (V19) : les repères du profil de marché tiennent-ils leurs promesses ? Module PUR (aucun accès réseau).

Sur chaque séance (1 jour : tranches de 30 min ; 4 heures et 1 heure : tranches de 5 min), avec exactement le moteur du terminal (engine/tpo.py)
et un pas de prix fixé SANS regarder le futur (médiane des amplitudes des 10 séances précédentes divisée par le nombre de lignes) :
  1. SINGLE PRINTS : sont-ils comblés (le prix retraverse toute la zone) plus souvent qu'une bande TÉMOIN de même largeur placée à la même distance
     de la clôture, de l'autre côté ? Comparaison appariée, erreur-type groupée par séance.
  2. POOR HIGH / POOR LOW : sont-ils dépassés (« réparés ») plus souvent que les extrêmes avec une QUEUE (excess), à distance égale de la clôture
     (comparaison stratifiée par distance) ?
  3. POC : sont-ils revisités plus souvent qu'un prix témoin à la même distance de la clôture ? Et les POC restés vierges la séance suivante ?
  4. PREMIÈRE HEURE (initial balance) : fréquence des cassures, des extensions à 1,5 et 2 fois sa hauteur, et sens de la séance après la
     première cassure.
  5. RÈGLE DES 80 % : après une ouverture hors de la valeur précédente et deux tranches clôturées dedans, l'autre bord est-il atteint dans la
     séance ? Témoin : même ouverture, simple retour dans la valeur (sans la condition des deux tranches).
  6. MIGRATION DE LA VALEUR, POSITION DE L'OUVERTURE, TYPE DE JOURNÉE et FORME : ce qui suit (sens de la séance suivante), face au taux de base.
Les résultats sont donnés pour toute la période et pour ses deux moitiés (stabilité). Plusieurs mesures étant faites, un écart isolé peut être
dû à la chance : seuls les écarts nets ET de même signe dans les deux moitiés méritent d'être retenus."""
import math
from array import array
from bisect import bisect_left
from collections import deque
from datetime import datetime, timezone

from . import tpo
from .sessionvp import nice_step

HORIZONS = {"D": (1, 3, 5, 10, 20), "4h": (1, 3, 6, 18, 42), "1h": (1, 4, 24, 72, 168), "W": (1, 2, 4, 8, 13), "M": (1, 2, 3, 6, 12)}
ROWS = {"D": 60, "4h": 36, "1h": 20, "W": 60, "M": 60}


def _day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def build_sessions(bars, kind: str, start: int, end: int, rows: int | None = None, progress=None, bracket: int | None = None):
    """Profils de toutes les seances completes de [start, end) (bars : fine.Bars en 5 min, 15 min ou 1 h). Calendrier du terminal : jour
    00 h UTC, semaine du lundi, mois calendaire. 'idx' : numero d'ordre de la seance ; 'i0'/'i1' : premiere bougie de la seance et premiere
    bougie apres elle (suivi du prix ensuite)."""
    spec = tpo.KINDS[kind]
    rows, br = rows or ROWS[kind], bracket or spec["bracket"]
    t = bars.t
    s = tpo.session_start(kind, start)
    if s < start:
        s = tpo.session_end(kind, s)
    out, ranges = [], []
    nominal = tpo.session_end(kind, s) - s
    total = max(1, (end - s) // nominal)
    k = 0
    while True:
        e = tpo.session_end(kind, s)
        if e > end:
            break
        need = 0.9 * (e - s) / bars.step
        i0, i1 = bisect_left(t, s), bisect_left(t, e)
        k += 1
        if progress and k % 500 == 0:
            progress(k, total)
        if i1 - i0 < need:
            s = e
            continue
        cs = bars.candles(i0, i1)
        hi, lo = max(bars.h[i0:i1]), min(bars.l[i0:i1])
        last = sorted(ranges[-10:])
        typical = last[len(last) // 2] if last else hi - lo
        step = nice_step(max(typical, 1e-9) / rows)
        p = tpo.profile(cs, s, e, br, step, ib_ms=spec["ib"])
        ranges.append(hi - lo)
        if p is not None and p["high"] > p["low"]:
            out.append({"p": p, "start": s, "idx": tpo.session_index(kind, s), "cs": cs, "typical": typical, "i0": i0, "i1": i1})
        s = e
    return out


def _future(ss, k, h):
    """(plus bas, plus haut) des seances k+1 .. k+h (None si l'historique s'arrete avant, ou s'il manque des seances)."""
    if k + h >= len(ss):
        return None
    if ss[k + h]["idx"] - ss[k]["idx"] != h:                  # trou dans les donnees : on ne compte pas
        return None
    lo = min(ss[j]["p"]["low"] for j in range(k + 1, k + h + 1))
    hi = max(ss[j]["p"]["high"] for j in range(k + 1, k + h + 1))
    return lo, hi


def paired(groups):
    """groups : par seance, liste de couples (repere 0/1, temoin 0/1). Taux, ecart et statistique t groupee par seance."""
    xs = [(x, y) for g in groups for x, y in g]
    n = len(xs)
    if n < 30:
        return {"n": n, "rate": None, "control": None, "diff": None, "t": None}
    rx, ry = sum(x for x, _ in xs) / n, sum(y for _, y in xs) / n
    d = rx - ry
    var = sum((sum(x - y for x, y in g) - d * len(g)) ** 2 for g in groups if g)
    se = math.sqrt(var) / n
    return {"n": n, "rate": rx, "control": ry, "diff": d, "t": d / se if se > 0 else None}


def _split(ss):
    mid = len(ss) // 2
    return [("all", 0, len(ss)), ("first", 0, mid), ("second", mid, len(ss))]


class PathIndex:
    """Premier franchissement d'un prix par les plus hauts (ou plus bas) des bougies, en O(log n) : tables des maxima / minima de chaque bloc
    de 2^j bougies (j jusqu'a la plus longue fenetre suivie)."""

    def __init__(self, h, l, max_len: int):
        self.n = len(h)
        self.mx, self.mn = [array("d", h)], [array("d", l)]
        for j in range(1, max(1, int(max_len).bit_length()) + 1):
            half = 1 << (j - 1)
            pm, pn = self.mx[-1], self.mn[-1]
            m = len(pm) - half
            if m <= 0:
                break
            self.mx.append(array("d", map(max, pm[:m], pm[half:half + m])))
            self.mn.append(array("d", map(min, pn[:m], pn[half:half + m])))
        self.top = len(self.mx) - 1

    def first_ge(self, p: int, x: float, limit: int):
        """Premiere bougie de [p, p + limit) dont le plus haut atteint x (None sinon)."""
        end, i = min(self.n, p + limit), p
        for j in range(self.top, -1, -1):
            if i + (1 << j) <= end and self.mx[j][i] < x:
                i += 1 << j
        return i if i < end and self.mx[0][i] >= x else None

    def first_le(self, p: int, x: float, limit: int):
        end, i = min(self.n, p + limit), p
        for j in range(self.top, -1, -1):
            if i + (1 << j) <= end and self.mn[j][i] > x:
                i += 1 << j
        return i if i < end and self.mn[0][i] <= x else None


def reaction(P: PathIndex, p0: int, a: float, b: float, c: float, limit: int):
    """Premier retour du prix a la bande [a, b] apres la seance (cloture c) : 1 s'il repart ensuite d'au moins la hauteur de la bande AVANT de
    la traverser (la bande a tenu), 0 s'il la traverse d'abord, None si pas de retour, pas de conclusion dans la fenetre, ou les deux dans la
    meme bougie (ordre inconnu). Bande au-dessus du prix : approche par le bas (et inversement)."""
    X = b - a
    if a > c:
        q = P.first_ge(p0, a, limit)
        if q is None:
            return None
        tr, rj = P.first_ge(q, b, limit), P.first_le(q + 1, a - X, limit)
    elif b < c:
        q = P.first_le(p0, b, limit)
        if q is None:
            return None
        tr, rj = P.first_le(q, a, limit), P.first_ge(q + 1, b + X, limit)
    else:
        return None
    if tr is None and rj is None:
        return None
    if rj is None or (tr is not None and tr < rj):
        return 0
    if tr is None or rj < tr:
        return 1
    return None


def _feats(ss):
    """Par seance : (sens -1/0/+1, amplitude / amplitude typique, position de la cloture dans la fourchette 0..1)."""
    out = []
    for x in ss:
        p = x["p"]
        rng = p["high"] - p["low"]
        d = 1 if p["close"] > p["open"] else -1 if p["close"] < p["open"] else 0
        out.append((d, rng / max(x["typical"], 1e-12), (p["close"] - p["low"]) / max(rng, 1e-12)))
    return out


def _similar(feats, k: int, win: int):
    """Seances SEMBLABLES a la seance k : meme sens, amplitude relative a +/- 30 %, cloture au meme endroit de la fourchette (+/- 0,15),
    de la plus proche dans le temps a la plus lointaine (au plus win seances d'ecart)."""
    d, rr, cp = feats[k]
    if d == 0:
        return
    n = len(feats)
    for dj in range(1, win + 1):
        if k - dj < 0 and k + dj >= n:
            return
        for j in (k - dj, k + dj):
            if 0 <= j < n:
                f = feats[j]
                if f[0] == d and abs(f[1] / rr - 1) <= 0.3 and abs(f[2] - cp) <= 0.15:
                    yield j


def _min_count(p, a: float, b: float):
    """Plus petit nombre de lettres sur les lignes du profil couvertes par [a, b] (None hors du profil)."""
    rows, step = p["rows"], p["step"]
    j0 = int(math.floor((a - rows[0][0]) / step + 1e-9))
    j1 = int(math.ceil((b - rows[0][0]) / step - 1e-9)) - 1
    if j0 < 0 or j1 >= len(rows) or j1 < j0:
        return None
    return min(r[1] for r in rows[j0:j1 + 1])


def _future_table(ss, horizons):
    """(plus bas, plus haut) des h seances suivantes pour chaque seance et chaque horizon (None si trou ou fin de l'historique)."""
    n = len(ss)
    lows, highs, idx = [x["p"]["low"] for x in ss], [x["p"]["high"] for x in ss], [x["idx"] for x in ss]
    out = {}
    for h in horizons:
        mins, maxs = [None] * n, [None] * n
        dq_lo, dq_hi = deque(), deque()
        for i in range(n):                                    # fenetre glissante [i - h + 1, i]
            while dq_lo and lows[dq_lo[-1]] >= lows[i]:
                dq_lo.pop()
            dq_lo.append(i)
            while dq_hi and highs[dq_hi[-1]] <= highs[i]:
                dq_hi.pop()
            dq_hi.append(i)
            if dq_lo[0] <= i - h:
                dq_lo.popleft()
            if dq_hi[0] <= i - h:
                dq_hi.popleft()
            k = i - h                                         # seance dont c'est la fenetre k+1 .. k+h
            if k >= 0 and idx[i] - idx[k] == h:
                mins[k], maxs[k] = lows[dq_lo[0]], highs[dq_hi[0]]
        out[h] = (mins, maxs)
    return out


WIN = {"D": 250, "4h": 540, "1h": 720, "W": 156, "M": 240}       # ecart maximal (en seances) pour chercher des seances semblables
NCONT = 20                                                       # temoins par zone


def measure_singles(ss, horizons, kind: str = "D", bars=None):
    """Single prints face a deux temoins :
      - MIROIR (V19) : bande de meme largeur a la meme distance de la cloture, de l'autre cote ;
      - APPARIE (V20, la reference) : la meme bande (meme position par rapport a la cloture, en amplitudes typiques) dans des seances
        SEMBLABLES (meme sens, amplitude et position de cloture proches) ou ces prix ont ete touches par au moins deux tranches. On compare
        donc, a mouvement egal, des prix « passes vite » a des prix « echanges ». Ce temoin neutralise aussi la derive haussiere du bitcoin (les
        single prints sont plus souvent sous la cloture : laissees par les hausses).
    Mesures : comble (toute la zone retraversee) dans les h seances suivantes ; REACTION au premier retour (rebond d'au moins la hauteur de la
    zone avant de la traverser) ; ELAN (la seance suivante va-t-elle dans le meme sens, face aux seances semblables sans single print).
    Renvoie (singles, reaction, elan), chacun par periode 'all' / 'first' / 'second'."""
    H = list(horizons)
    fut = _future_table(ss, H)
    feats = _feats(ss)
    win = WIN.get(kind, 250)
    P, limit = None, 0
    if bars is not None and len(ss) > 1:
        nominal = tpo.session_end(kind, ss[1]["start"]) - ss[1]["start"]
        limit = int(H[-1] * nominal / bars.step * 1.12) + 2
        P = PathIndex(bars.h, bars.l, limit)
    recs = []                                                 # par seance : (k, {h: [(x, temoin miroir)]}, {h: [(x, touche miroir)]}, {h: [...]}, [reaction], [reaction miroir])
    elan = []
    for k, x in enumerate(ss):
        p = x["p"]
        if not p["singles"]:
            continue
        c, typ = p["close"], x["typical"]
        fill_m, touch_m, fill_a = {h: [] for h in H}, {h: [] for h in H}, {h: [] for h in H}
        r_a, r_m = [], []
        for z0, z1 in p["singles"]:
            m0, m1 = 2 * c - z1, 2 * c - z0
            for h in H:
                lo, hi = fut[h][0][k], fut[h][1][k]
                if lo is None:
                    continue
                fill_m[h].append((int(lo <= z0 and hi >= z1), int(lo <= m0 and hi >= m1)))
                touch_m[h].append((int(lo <= z1 and hi >= z0), int(lo <= m1 and hi >= m0)))
            dA, dB = (z0 - c) / typ, (z1 - c) / typ
            ctl = []
            for j in _similar(feats, k, win):
                pj = ss[j]["p"]
                a, b = pj["close"] + dA * ss[j]["typical"], pj["close"] + dB * ss[j]["typical"]
                if a < pj["low"] or b > pj["high"]:
                    continue
                mc = _min_count(pj, a, b)
                if mc is None or mc < 2:
                    continue
                ctl.append((j, a, b))
                if len(ctl) >= NCONT:
                    break
            if len(ctl) < 3:
                continue
            for h in H:
                lo, hi = fut[h][0][k], fut[h][1][k]
                if lo is None:
                    continue
                v = [int(fut[h][0][j] <= a and fut[h][1][j] >= b) for j, a, b in ctl if fut[h][0][j] is not None]
                if v:
                    fill_a[h].append((int(lo <= z0 and hi >= z1), sum(v) / len(v)))
            if P is not None:
                rs = reaction(P, x["i1"], z0, z1, c, limit)
                if rs is not None:
                    v = [rv for rv in (reaction(P, ss[j]["i1"], a, b, ss[j]["p"]["close"], limit) for j, a, b in ctl) if rv is not None]
                    if v:
                        r_a.append((rs, sum(v) / len(v)))
                    rm = reaction(P, x["i1"], m0, m1, c, limit)
                    if rm is not None:
                        r_m.append((rs, rm))
        recs.append((k, fill_m, touch_m, fill_a, r_a, r_m))
        # elan : la seance suivante continue-t-elle dans le meme sens, face aux seances semblables SANS single print ?
        d = feats[k][0]
        if d and k + 1 < len(ss) and ss[k + 1]["idx"] - ss[k]["idx"] == 1:
            nx = ss[k + 1]["p"]
            cv = []
            for j in _similar(feats, k, win):
                if j + 1 < len(ss) and not ss[j]["p"]["singles"] and ss[j + 1]["idx"] - ss[j]["idx"] == 1:
                    q = ss[j + 1]["p"]
                    cv.append(int((q["close"] - q["open"]) * d > 0))
                    if len(cv) >= NCONT:
                        break
            if len(cv) >= 3:
                elan.append((k, int((nx["close"] - nx["open"]) * d > 0), sum(cv) / len(cv)))
    singles, react, el = {}, {}, {}
    for name, a, b in _split(ss):
        sel = [r for r in recs if a <= r[0] < b]
        singles[name] = {str(h): {"fill": paired([r[1][h] for r in sel]), "touch": paired([r[2][h] for r in sel]),
                                  "matched": paired([r[3][h] for r in sel])} for h in H}
        react[name] = {"matched": paired([r[4] for r in sel]), "mirror": paired([r[5] for r in sel])} if P is not None else None
        el[name] = paired([[(x1, y1)] for k, x1, y1 in elan if a <= k < b])
    return singles, react, el


def _strat(rows, h):
    """rows : (groupe, distance relative, repare 0/1). Taux bruts et ecart stratifie poor - excess (a distance egale)."""
    bins = [0.0, 0.1, 0.25, 0.5, 0.75, 10.0]
    cell = {}
    for g, dist, ok in rows:
        bi = next(i for i in range(len(bins) - 1) if dist < bins[i + 1])
        c = cell.setdefault((g, bi), [0, 0])
        c[0] += ok
        c[1] += 1
    raw = {}
    for g in ("poor", "excess", "other"):
        n = sum(v[1] for (gg, _), v in cell.items() if gg == g)
        raw[g] = {"n": n, "rate": (sum(v[0] for (gg, _), v in cell.items() if gg == g) / n) if n else None}
    num = den = var = 0.0
    for bi in range(len(bins) - 1):
        p, e = cell.get(("poor", bi)), cell.get(("excess", bi))
        if not p or not e or p[1] < 10 or e[1] < 10:
            continue
        rp, re_ = p[0] / p[1], e[0] / e[1]
        w = p[1]
        num += w * (rp - re_)
        den += w
        var += w * w * (rp * (1 - rp) / p[1] + re_ * (1 - re_) / e[1])
    d = num / den if den else None
    se = math.sqrt(var) / den if den else None
    return {"raw": raw, "diff": d, "t": (d / se) if d is not None and se else None, "n": int(den)}


def measure_extremes(ss, horizons):
    out = {}
    for name, a, b in _split(ss):
        res = {}
        for h in horizons:
            rows = []
            for k in range(a, b):
                p = ss[k]["p"]
                f = _future(ss, k, h)
                if f is None:
                    continue
                lo, hi = f
                r = p["high"] - p["low"]
                c = p["close"]
                gh = "poor" if p["poorHigh"] else "excess" if p["tailHigh"] else "other"
                gl = "poor" if p["poorLow"] else "excess" if p["tailLow"] else "other"
                rows.append((gh, (p["high"] - c) / r, int(hi > p["high"])))
                rows.append((gl, (c - p["low"]) / r, int(lo < p["low"])))
            res[str(h)] = _strat(rows, h)
        out[name] = res
    return out


def measure_poc(ss, horizons):
    out = {}
    for name, a, b in _split(ss):
        res = {}
        for h in horizons:
            g_all, g_virgin = [], []
            for k in range(a, b):
                p = ss[k]["p"]
                f = _future(ss, k, h)
                if f is None:
                    continue
                lo, hi = f
                P, c = p["poc"], p["close"]
                M = 2 * c - P
                g_all.append([(int(lo <= P <= hi), int(lo <= M <= hi))])
                if h > 1:
                    f1 = _future(ss, k, 1)
                    if f1 and not (f1[0] <= P <= f1[1]) and not (f1[0] <= M <= f1[1]):
                        g_virgin.append([(int(lo <= P <= hi), int(lo <= M <= hi))])
            res[str(h)] = {"all": paired(g_all), "virgin": paired(g_virgin) if h > 1 else None}
        out[name] = res
    return out


def measure_ib(ss):
    """Premiere heure : frequence des cassures et des extensions ; puis, A PARTIR DU MOMENT de la premiere cassure (seule question utile pour
    trader : la cassure dit-elle quelque chose de la suite ?), part des seances qui cloturent au-dela du niveau casse (50 % = aucune information)
    et part qui reviennent jusqu'a l'autre bord de la premiere heure (echec)."""
    n = up = dn = both = none = 0
    ext15 = ext2 = broke_side = 0
    cont = {"up": [], "down": []}                              # 1 si cloture au-dela du niveau casse
    fail = {"up": 0, "down": 0}
    for x in ss:
        p = x["p"]
        st = p.get("ibStats")
        if not st or not st["complete"] or st["range"] <= 0:
            continue
        n += 1
        u, d = st["extUp"] > 0, st["extDn"] > 0
        both += u and d
        up += u and not d
        dn += d and not u
        none += not u and not d
        for e in (st["extUp"], st["extDn"]):
            if e > 0:
                broke_side += 1
                ext15 += e >= 0.5
                ext2 += e >= 1.0
        side, t_break = None, None
        for i, h, l, c in p["br"]:
            if i * p["bracketMs"] < p["ibMs"]:                  # tranches de la premiere heure elle-meme
                continue
            if h > st["high"] and l < st["low"]:
                break                                           # les deux cotes dans la meme tranche : ordre inconnu
            if h > st["high"] or l < st["low"]:
                side, t_break = ("up" if h > st["high"] else "down"), p["start"] + i * p["bracketMs"]
                break
        if side:
            lvl = st["high"] if side == "up" else st["low"]
            cont[side].append(int(p["close"] > lvl) if side == "up" else int(p["close"] < lvl))
            after = [k for k in x["cs"] if k.t >= t_break]
            fail[side] += any(k.l <= st["low"] for k in after) if side == "up" else any(k.h >= st["high"] for k in after)
    if not n:
        return None
    r = lambda a, b: a / b if b else None

    def side_stats(sd):
        v = cont[sd]
        m = sum(v) / len(v) if v else None
        return {"n": len(v), "closeBeyond": m, "t": (m - 0.5) / math.sqrt(0.25 / len(v)) if v else None, "failure": r(fail[sd], len(v))}
    return {"n": n, "none": none / n, "upOnly": up / n, "downOnly": dn / n, "both": both / n,
            "ext15": r(ext15, broke_side), "ext2": r(ext2, broke_side), "firstUp": side_stats("up"), "firstDown": side_stats("down")}


def measure_eighty(ss):
    setups = hits = 0
    base_n = base_hits = 0
    for k in range(1, len(ss)):
        cur, prev = ss[k]["p"], ss[k - 1]["p"]
        if ss[k]["idx"] - ss[k - 1]["idx"] != 1:
            continue
        e = tpo.eighty(cur, prev, ss[k]["cs"], cur["step"])
        if not e:
            continue
        val, vah = prev["val"], prev["vah"]
        # temoin : premier retour dans la valeur (une tranche qui la touche), puis l'autre bord atteint ensuite dans la seance ?
        entry = None
        for i, h, l, c in cur["br"]:
            if l <= vah and h >= val:
                entry = cur["start"] + (i + 1) * cur["bracketMs"]
                break
        if entry is not None:
            after = [x for x in ss[k]["cs"] if x.t >= entry]
            target = vah if e["side"] == "up" else val
            base_n += 1
            base_hits += any(x.h >= target for x in after) if e["side"] == "up" else any(x.l <= target for x in after)
        if e["trigger"] is not None:
            setups += 1
            hits += bool(e["reached"])
    return {"n": setups, "rate": hits / setups if setups else None, "controlN": base_n, "control": base_hits / base_n if base_n else None}


def _next_dir(ss, groups_of):
    """Pour chaque groupe : part des seances SUIVANTES haussieres (cloture > ouverture) et rendement moyen, face a toutes les seances."""
    res, allr = {}, []
    for k in range(len(ss) - 1):
        nx = ss[k + 1]["p"]
        if ss[k + 1]["idx"] - ss[k]["idx"] != 1:
            continue
        ret = (nx["close"] / nx["open"] - 1) * 100
        allr.append(ret)
        g = groups_of(k)
        if g:
            res.setdefault(g, []).append(ret)
    base = sum(1 for x in allr if x > 0) / len(allr) if allr else None
    out = {}
    for g, v in res.items():
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1))
        out[g] = {"n": len(v), "up": sum(1 for x in v if x > 0) / len(v), "mean": m, "t": m / (sd / math.sqrt(len(v))) if sd > 0 and len(v) > 1 else None}
    return {"base": base, "groups": out}


def run(bars, kind: str, start: int, end: int, progress=None) -> dict:
    ss = build_sessions(bars, kind, start, end, progress=progress)
    if len(ss) < 60:
        return {"kind": kind, "ready": False, "n": len(ss)}
    sg, react, elan = measure_singles(ss, HORIZONS[kind], kind, bars)
    H = HORIZONS[kind]
    prevs = {}
    for k in range(1, len(ss)):
        if ss[k]["idx"] - ss[k - 1]["idx"] == 1:
            prevs[k] = ss[k - 1]["p"]

    def va_group(k):
        return tpo.va_relation(ss[k]["p"], prevs[k])[0] if k in prevs else None

    def open_group(k):
        return tpo.open_location(ss[k]["p"], prevs[k])[0] if k in prevs else None

    def type_group(k):
        x = ss[k]
        last = sorted(y["p"]["high"] - y["p"]["low"] for y in ss[max(0, k - 10):k])
        dt = tpo.day_type(x["p"], last[len(last) // 2] if last else None)
        if not dt:
            return None
        up = x["p"]["close"] > x["p"]["open"]
        return f"{dt}_{'up' if up else 'down'}" if dt in ("trend", "normalvar") else dt

    def shape_group(k):
        return ss[k]["p"].get("shape")

    def same_session(groups_of):                             # meme seance : part haussiere (face a toutes les seances) et amplitude typique
        res, n_all, up_all = {}, 0, 0
        for k in range(len(ss)):
            g = groups_of(k)
            if not g:
                continue
            p = ss[k]["p"]
            n_all += 1
            up_all += p["close"] > p["open"]
            r = res.setdefault(g, [0, 0, 0.0])
            r[0] += 1
            r[1] += p["close"] > p["open"]
            r[2] += (p["high"] - p["low"]) / max(ss[k]["typical"], 1e-9)
        base = up_all / n_all if n_all else 0.5
        out = {g: {"n": v[0], "up": v[1] / v[0], "rangeX": v[2] / v[0],
                   "t": (v[1] / v[0] - base) / math.sqrt(base * (1 - base) / v[0]) if v[0] and 0 < base < 1 else None} for g, v in res.items()}
        return {"base": base, "groups": out}

    types = {}
    for k in range(len(ss)):
        g = type_group(k)
        if g:
            types[g] = types.get(g, 0) + 1
    tot = sum(types.values()) or 1
    return {"kind": kind, "ready": True, "n": len(ss), "from": _day(ss[0]["start"]), "to": _day(ss[-1]["p"]["end"] - 1), "rows": ROWS[kind],
            "horizons": list(H), "singles": sg, "singlesReaction": react, "singlesElan": elan, "singleCount": sum(len(x["p"]["singles"]) for x in ss),
            "extremes": measure_extremes(ss, H), "poc": measure_poc(ss, H),
            "ib": measure_ib(ss), "eighty": measure_eighty(ss) if kind in ("D", "W", "M") else None, "bracketMs": tpo.KINDS[kind]["bracket"],
            "migration": _next_dir(ss, va_group), "openNext": _next_dir(ss, open_group), "openSame": same_session(open_group),
            "dayTypes": {"freq": {g: v / tot for g, v in types.items()}, "next": _next_dir(ss, type_group)},
            "shapes": _next_dir(ss, shape_group)}


# ---------- synthese lisible (vue TPO, README) ----------
KIND_TXT = {"D": "séances d'1 jour", "4h": "séances de 4 heures", "1h": "séances d'1 heure", "W": "séances d'1 semaine", "M": "séances d'1 mois"}
ORDER = ("W", "M", "D", "4h", "1h")
UNIT = {"D": ("la séance suivante", "5 séances"), "4h": ("la séance de 4 heures suivante", "24 heures"), "1h": ("l'heure suivante", "24 heures"),
        "W": ("la semaine suivante", "4 semaines"), "M": ("le mois suivant", "3 mois")}
ONE = {"D": "une séance", "4h": "une séance de 4 heures", "1h": "une heure", "W": "une semaine", "M": "un mois"}
BRACKET_TXT = {"D": "30 minutes", "4h": "5 minutes", "1h": "5 minutes", "W": "4 heures", "M": "1 jour"}
IB_TXT = {"D": "Première heure", "4h": "30 premières minutes", "1h": "10 premières minutes", "W": "Lundi", "M": "Première semaine"}
SESS_IN = {"D": "la journée", "4h": "la séance", "1h": "l'heure", "W": "la semaine", "M": "le mois"}


def _pct(x, d=0):
    return "—" if x is None else f"{x * 100:.{d}f}".replace(".", ",") + " %"


def _num(x, d=1):
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",").replace("-", "−")


def _pts(x):
    return "—" if x is None else f"{x * 100:+.1f}".replace(".", ",").replace("-", "−") + " points"


def _verdict(all_t, first_d, second_d, all_d):
    """Net si |t| >= 2 sur toute la periode ET meme signe sur les deux moities ; instable si |t| >= 2 mais pas confirme (signe different, ou
    trop peu de cas dans une moitie) ; sinon hasard."""
    if all_t is None or all_d is None:
        return "insuffisant"
    stable = first_d is not None and second_d is not None and (first_d > 0) == (second_d > 0) == (all_d > 0)
    if abs(all_t) >= 2 and stable:
        return "net"
    if abs(all_t) >= 2:
        return "instable"
    return "hasard"


def _sv(r, key, h=None, sub=None):
    """(toute la periode, 1re moitie, 2e moitie) d'une mesure appariee."""
    out = []
    for name in ("all", "first", "second"):
        x = (r.get(key) or {}).get(name)
        if x is not None and h is not None:
            x = x.get(h)
        if x is not None and sub is not None:
            x = x.get(sub)
        out.append(x or {})
    return out


def _singles_item(r, kind):
    H = [str(h) for h in r["horizons"]]
    hk, hm = H[0], H[2]
    unit = UNIT[kind]
    sub = "matched" if "matched" in r["singles"]["all"][hk] else "fill"         # rapports V19 : temoin miroir seulement
    m, m1, m2 = _sv(r, "singles", hk, sub)
    v = _verdict(m.get("t"), m1.get("diff"), m2.get("diff"), m.get("diff"))
    if v == "net" and m.get("diff") is not None and m["diff"] < 0:
        v = "contraire"                                       # mesure nette... dans le sens oppose a l'idee recue
    mm = r["singles"]["all"][hm].get(sub) or {}
    rc = ((r.get("singlesReaction") or {}).get("all") or {}).get("matched") or {}
    ctl = "la même bande placée au même endroit de séances semblables où ces prix ont été échangés (même sens, même amplitude, clôture au même endroit)" \
        if sub == "matched" else "une bande témoin de même largeur à la même distance de la clôture"
    txt = (f"Single prints ({KIND_TXT[kind]}, {r.get('singleCount', '?')} zones) : comblés dès {unit[0]} {_pct(m.get('rate'))} du temps, contre "
           f"{_pct(m.get('control'))} pour {ctl} (écart {_pts(m.get('diff'))}, statistique {_num(m.get('t'))}) ; en {unit[1]} : {_pct(mm.get('rate'))} "
           f"contre {_pct(mm.get('control'))}. ")
    txt += {"contraire": "Pas un aimant : le prix y revient MOINS souvent qu'ailleurs, le mouvement qui les a laissés était convaincu. Ne pas compter sur leur comblement comme objectif.",
            "net": "Effet aimant mesuré : le prix revient les combler plus souvent qu'ailleurs.",
            "instable": "Écart visible sur toute la période" + (" (plutôt MOINS comblés qu'ailleurs)" if (m.get("diff") or 0) < 0 else "") +
                        ", mais pas confirmé sur les deux moitiés (ou trop peu de cas pour le vérifier) : à prendre avec prudence.",
            "hasard": "Aucune différence démontrée avec un prix quelconque.",
            "insuffisant": "Trop peu de cas pour conclure."}[v]
    if rc.get("rate") is not None:
        t = rc.get("t")
        txt += (f" Au premier retour du prix, la zone tient (rebond d'au moins sa hauteur avant d'être traversée) {_pct(rc['rate'])} du temps, contre "
                f"{_pct(rc['control'])} pour les témoins : " + ("elle tient MIEUX qu'un autre prix." if t is not None and t >= 2 else
                                                                  "elle tient MOINS bien qu'un autre prix." if t is not None and t <= -2 else
                                                                  "ni mieux ni moins bien qu'un autre prix."))
    return {"key": "singles", "kind": kind, "verdict": v, "text": txt}


def _elan_item(r, kind):
    e, e1, e2 = _sv(r, "singlesElan")
    if e.get("rate") is None:
        return None
    v = _verdict(e.get("t"), e1.get("diff"), e2.get("diff"), e.get("diff"))
    if v == "net" and e["diff"] < 0:
        v = "contraire"
    return {"key": "elan", "kind": kind, "verdict": v,
            "text": f"Élan ({KIND_TXT[kind]}) : après une séance qui laisse des single prints, {unit_of(kind)} va dans le même sens {_pct(e['rate'])} du temps, "
                    f"contre {_pct(e['control'])} après une séance semblable sans single print (écart {_pts(e['diff'])}, statistique {_num(e['t'])}). " +
                    ("Les single prints signalent un mouvement qui a tendance à continuer." if v == "net" else
                     "Elles signalent plutôt un essoufflement." if v == "contraire" else
                     "Écart non confirmé sur les deux moitiés : à prendre avec prudence." if v == "instable" else "Pas d'effet démontré.")}


def unit_of(kind):
    return UNIT[kind][0]


def summary(rep: dict) -> list:
    """Constats principaux, du plus solide au plus fragile : [{key, kind, verdict, text}]."""
    out = []
    for kind in ORDER:
        r = rep.get(kind)
        if not r or not r.get("ready"):
            continue
        H = [str(h) for h in r["horizons"]]
        hk = H[0]
        unit = UNIT[kind]
        ex = r["extremes"]
        e, e1, e2 = ex["all"][hk], ex["first"][hk], ex["second"][hk]
        v = _verdict(e["t"], e1["diff"], e2["diff"], e["diff"])
        out.append({"key": "poor", "kind": kind, "verdict": v,
                    "text": f"Poor high / poor low ({KIND_TXT[kind]}) : dépassés dès {unit[0]} {_pct(e['raw']['poor']['rate'])} du temps, contre "
                            f"{_pct(e['raw']['excess']['rate'])} pour un extrême avec queue (excess) ; à distance égale de la clôture, écart "
                            f"{_pts(e['diff'])} (statistique {_num(e['t'])}). " +
                            ("Effet net et stable : la queue marque un vrai rejet, le poor high / low une enchère inachevée qui attire un retour."
                             if v == "net" else "Effet non démontré.")})
        out.append(_singles_item(r, kind))
        el = _elan_item(r, kind)
        if el:
            out.append(el)
        pc, p1, p2 = (r["poc"][p][hk]["all"] for p in ("all", "first", "second"))
        v = _verdict(pc["t"], p1["diff"], p2["diff"], pc["diff"])
        pv = r["poc"]["all"][H[1]]["virgin"]
        out.append({"key": "poc", "kind": kind, "verdict": v,
                    "text": f"POC ({KIND_TXT[kind]}) : retraversé dès {unit[0]} {_pct(pc['rate'])} du temps, contre {_pct(pc['control'])} pour un prix témoin "
                            f"à la même distance (écart {_pts(pc['diff'])}, statistique {_num(pc['t'])})"
                            + (f" ; POC resté vierge {ONE[kind]} : revisité ensuite {_pct(pv['rate'])} contre {_pct(pv['control'])}" if pv and pv.get("rate") is not None else "")
                            + (". Léger effet aimant, net et stable." if v == "net" else ". Effet faible ou instable." if v == "instable" else ". Pas d'effet démontré.")})
        ib = r.get("ib")
        if ib:
            fu, fd = ib["firstUp"], ib["firstDown"]
            tu, td = fu.get("t"), fd.get("t")
            if tu is not None and td is not None and tu >= 2 and td >= 2:
                concl = "les cassures ont tendance à tenir, dans les deux sens."
            elif tu is not None and td is not None and tu <= -2 and td <= -2:
                concl = "les cassures sont souvent des pièges, dans les deux sens."
            else:                                             # un cote au-dessus de 50 %, l'autre en dessous : c'est la tendance de fond, pas la cassure
                concl = "la cassure ne dit presque rien de la suite" + (" (l'écart entre le haut et le bas reflète surtout la hausse de fond du bitcoin)."
                                                                         if (fu.get("closeBeyond") or 0) - (fd.get("closeBeyond") or 0) > 0.05 else ".")
            out.append({"key": "ib", "kind": kind, "verdict": "description",
                        "text": f"{IB_TXT[kind]} ({KIND_TXT[kind]}, « première heure » de la séance) : sa fourchette est cassée des deux côtés {_pct(ib['both'])} du temps, "
                                f"d'un seul côté {_pct(ib['upOnly'] + ib['downOnly'])} ; après une cassure, l'extension à 1,5 fois sa hauteur est atteinte "
                                f"{_pct(ib['ext15'])} du temps, à 2 fois {_pct(ib['ext2'])}. Depuis le moment de la première cassure, la séance clôture au-delà du "
                                f"niveau cassé {_pct(fu['closeBeyond'])} (vers le haut) et {_pct(fd['closeBeyond'])} (vers le bas) : {concl}"})
        e8 = r.get("eighty")
        if e8 and e8.get("rate") is not None:
            out.append({"key": "eighty", "kind": kind, "verdict": "description",
                        "text": f"Règle des « 80 % » ({KIND_TXT[kind]}) : après une ouverture hors de la valeur précédente et deux tranches de {BRACKET_TXT[kind]} "
                                f"clôturées dedans, l'autre bord est atteint dans {SESS_IN[kind]} {_pct(e8['rate'])} du temps (sur {e8['n']} cas), contre "
                                f"{_pct(e8['control'])} après un simple retour dans la valeur." + (" Bien loin de 80 %." if e8["rate"] < 0.65 else "")})
        osm = r.get("openSame") or {}
        g = osm.get("groups") or {}
        if g.get("belowValue") and g.get("aboveValue"):
            b, a_ = g["belowValue"], g["aboveValue"]
            vv = "net" if (b.get("t") or 0) >= 2 and (a_.get("t") or 0) <= -2 else "faible"
            out.append({"key": "open", "kind": kind, "verdict": vv,
                        "text": f"Ouverture ({KIND_TXT[kind]}) : sous la valeur précédente, la séance finit en hausse {_pct(b['up'])} du temps ; au-dessus, {_pct(a_['up'])} ; "
                                f"en moyenne {_pct(osm['base'])}. " + ("Le prix a tendance à revenir vers la valeur précédente, et ces séances sont plus larges "
                                f"(×{_num(b['rangeX'], 2)} l'amplitude habituelle)." if vv == "net" else "Écart trop faible pour être retenu.")})
    order = {"net": 0, "contraire": 1, "instable": 2, "faible": 3, "description": 4, "hasard": 5, "insuffisant": 6}
    return sorted(out, key=lambda x: (order.get(x["verdict"], 9), ORDER.index(x["kind"])))


def compact(rep: dict, kind: str):
    """Ce que la vue TPO affiche pour un type de seance : taux mesures a cote des marques et constats."""
    r = (rep or {}).get(kind)
    if not r or not r.get("ready"):
        return None
    H = [str(h) for h in r["horizons"]]
    hk, hm = H[0], H[2]
    sub = "matched" if "matched" in r["singles"]["all"][hk] else "fill"
    sg, sg2 = r["singles"]["all"][hk][sub], r["singles"]["all"][hm][sub]
    e, pc = r["extremes"]["all"][hk], r["poc"]["all"][hk]["all"]
    items = [x for x in rep.get("summary", []) if x["kind"] == kind]
    sv = next((x["verdict"] for x in items if x["key"] == "singles"), None)
    return {"symbol": rep.get("symbol"), "source": rep.get("source"), "from": r["from"], "to": r["to"], "n": r["n"], "horizons": r["horizons"],
            "units": {"next": UNIT[kind][0], "mid": UNIT[kind][1]},
            "singles": {"rate": sg["rate"], "control": sg["control"], "t": sg["t"], "h": int(hk), "rate2": sg2["rate"], "control2": sg2["control"],
                        "h2": int(hm), "control_kind": sub, "verdict": sv, "count": r.get("singleCount"),
                        "reaction": ((r.get("singlesReaction") or {}).get("all") or {}).get("matched"), "elan": (r.get("singlesElan") or {}).get("all")},
            "poor": {"rate": e["raw"]["poor"]["rate"], "excess": e["raw"]["excess"]["rate"], "diff": e["diff"], "t": e["t"], "h": int(hk)},
            "poc": {"rate": pc["rate"], "control": pc["control"], "t": pc["t"], "h": int(hk),
                    "virgin": r["poc"]["all"][H[1]]["virgin"], "virginH": int(H[1])},
            "ib": r.get("ib"), "eighty": r.get("eighty"), "openSame": r.get("openSame"), "dayTypes": (r.get("dayTypes") or {}).get("freq"),
            "summary": items}
