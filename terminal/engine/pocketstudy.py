"""Etude (V14) : les CONFLUENCES et la MATURITE d'une poche de liquidite changent-elles ce que fait le prix ?

Poches mesurables sur tout l'historique : les ordres d'arret VISIBLES dans le prix (plus haut / plus bas de la veille, de la semaine, du mois
precedents ; creux / sommets confirmes sur 1 h ; deux extremes presque egaux = une poche « egaux »). Les poches estimees par l'intérêt
ouvert n'ont que 29 jours d'historique chez Binance : elles ne se testent pas ici.

Deux questions, bougies 1 h fermees, uniquement avec ce qui etait connu a chaque instant :
  1) ATTRACTION (« aimant ») : chaque jour a 00 h UTC, pour chaque poche intacte entre 0,5 et 8 amplitudes moyennes d'une bougie d'une
     heure, le prix la touche-t-il dans les 24 h ? Compare a la frequence d'atteinte de la MEME distance n'importe ou (table d'atteinte
     de la paire). Ecart > 0 = le prix va chercher ces poches plus souvent que la distance seule ne le prevoit.
  2) REACTION au premier contact : depuis la cloture de la bougie de contact, le prix repart-il d'une amplitude moyenne dans l'autre sens
     (retournement : les stops ont ete pris et le mouvement s'arrete) avant d'aller une amplitude plus loin (cassure) ? Compare au taux
     qu'une marche au hasard donnerait depuis la meme position de cloture (correction de depassement), et a des niveaux tires au hasard.
Chaque mesure est decoupee par nombre de confluences (niveaux d'autres sources a moins de 0,3 amplitude), par confluences ponderees
(pocketrank : annee > mois > semaine > jour), par age, par type de poche ; apprentissage / test separes ; erreurs-types REGROUPEES PAR
JOUR (plusieurs poches touchees le meme jour ne sont pas des preuves independantes). Module PUR."""
import math
import random
from bisect import bisect_right

from . import pocketrank as pr
from .liqsweep import EQUAL_PCT, swing_points
from .periods import NakedPocs, PeriodTracker, period_key
from .stats import RHO, _fwd_extreme, _known_levels, atr_series, outcome_at, reach_prob, reach_table, sd_series

H = 3_600_000
DAY = 24 * H
HL_GROUP = {"D": "PDHL", "W": "PWHL", "M": "PMHL"}
TYPE_TXT = {"D": "veille", "W": "semaine précédente", "M": "mois précédent", "S": "creux / sommet 1 h"}
FORCE = {"M": 95, "W": 85, "D": 70, "S": 55}
AGE_BUCKETS = ((6, "moins de 6 h"), (24, "6 à 24 h"), (72, "1 à 3 jours"), (240, "3 à 10 jours"), (720, "10 à 30 jours"), (math.inf, "plus de 30 jours"))
CONFW_BUCKETS = ((8, "faibles (moins de 8 points)"), (20, "moyennes (8 à 19 points)"), (math.inf, "fortes (20 points ou plus)"))
MAX_AGE_D = 60
MAX_DIST = 0.20


def _bucket(x, table):
    for lim, lab in table:
        if x < lim:
            return lab
    return table[-1][1]


class _Acc:
    """Somme des ecarts (reel - attendu) regroupes par jour : ecart moyen et statistique t robuste aux poches d'un meme jour."""
    __slots__ = ("n", "act", "exp", "day")

    def __init__(self):
        self.n, self.act, self.exp, self.day = 0, 0.0, 0.0, {}

    def add(self, day, actual, expected):
        self.n += 1
        self.act += actual
        self.exp += expected
        self.day[day] = self.day.get(day, 0.0) + (actual - expected)

    def out(self):
        if not self.n:
            return {"n": 0, "days": 0, "p": None, "exp": None, "ex": None, "t": None}
        var = sum(v * v for v in self.day.values())
        ex = (self.act - self.exp) / self.n
        t = (self.act - self.exp) / math.sqrt(var) if var > 0 else None
        return {"n": self.n, "days": len(self.day), "p": self.act / self.n, "exp": self.exp / self.n, "ex": ex, "t": t}


class _Table:
    """Une ligne par (dimension, valeur) ; chaque ligne garde tout, apprentissage et test."""

    def __init__(self):
        self.rows = {}

    def add(self, keys, day, actual, expected, test):
        for k in keys:
            r = self.rows.setdefault(k, (_Acc(), _Acc(), _Acc()))
            r[0].add(day, actual, expected)
            r[2 if test else 1].add(day, actual, expected)

    def out(self, order):
        res = []
        for dim, val in order:
            r = self.rows.get((dim, val))
            if not r:
                continue
            a, i, o = (x.out() for x in r)
            res.append({"dim": dim, "name": val, **a, "is": i, "oos": o, "verdict": verdict(a, i, o)})
        return res


def verdict(a, i, o):
    """« effet » : meme signe a l'apprentissage et au test, chacun au-dela de 2 erreurs-types ; « indice » : meme signe des deux cotes et
    l'ensemble au-dela de 2 ; sinon « ≈ hasard ». Signe : + = plus que prevu (attraction ou retournement), - = moins."""
    if not a["n"] or a["t"] is None or not i["n"] or not o["n"] or i["t"] is None or o["t"] is None:
        return "trop peu"
    same = (i["ex"] > 0) == (o["ex"] > 0)
    if same and abs(i["t"]) >= 2 and abs(o["t"]) >= 2:
        return "effet +" if a["ex"] > 0 else "effet −"
    if same and abs(a["t"]) >= 2:
        return "indice +" if a["ex"] > 0 else "indice −"
    return "≈ hasard"


class _Book:
    """Poches vivantes (intactes). Deux extremes du meme cote a moins de 0,15 % : une seule poche « egaux » (plus vieille naissance gardee)."""

    def __init__(self):
        self.alive, self.seq = [], 0

    def add(self, kind, price, typ, born):
        for q in self.alive if typ != "R" else ():
            if q["kind"] == kind and "R" not in q["types"] and abs(q["price"] / price - 1) <= EQUAL_PCT:
                if abs(q["born"] - born) > 2 * H:                  # un autre extreme au meme prix : « egaux » ; sinon le meme extreme vu deux fois
                    q["eq"] += 1
                q["types"].add(typ)
                q["price"] = min(q["price"], price) if kind == "low" else max(q["price"], price)
                q["born"] = min(q["born"], born)
                return q
        self.seq += 1
        q = {"id": self.seq, "kind": kind, "price": price, "types": {typ}, "born": born, "eq": 0}
        self.alive.append(q)
        return q


def _type_keys(q):
    if q["types"] == {"R"}:
        return [("type", "niveau au hasard (témoin)")]
    keys = [("type", TYPE_TXT[t]) for t in ("M", "W", "D", "S") if t in q["types"]]
    if q["eq"]:
        keys.append(("type", "égaux (deux extrêmes au même prix)"))
    return keys


def _features(q, levels, atr, t_ms):
    skip = {HL_GROUP[t] for t in q["types"] if t in HL_GROUP}
    lv = [(k, g, p) for (k, _f, g, p) in levels if g != "RAND"]
    tol = pr.tolerance(q["price"], atr)
    cf = pr.confluences(q["price"], q["price"], lv, tol, skip)
    n = len(cf)
    pts = pr.conf_points(cf)
    age_h = (t_ms - q["born"]) / H
    return n, pts, age_h


def _keys(q, n, pts, age_h):
    rnd = q["types"] == {"R"}
    out = [("all", "niveaux au hasard (témoin)" if rnd else "toutes les poches")]
    if rnd:
        return out + [("randconf", "témoin avec 2 confluences ou plus" if n >= 2 else "témoin sans confluence" if n == 0 else "témoin avec 1 confluence")]
    out += [("conf", "3 ou plus" if n >= 3 else str(n)), ("confw", _bucket(pts, CONFW_BUCKETS)), ("age", _bucket(age_h, AGE_BUCKETS)),
            ("side", "creux (ordres d'arrêt des acheteurs)" if q["kind"] == "low" else "sommets (ordres d'arrêt des vendeurs)")]
    out += _type_keys(q)
    strong, mature = pts >= 20, 24 <= age_h < 240
    out.append(("combo", ("fortes confluences" if strong else "confluences faibles ou moyennes") + (", poche de 1 à 10 jours" if mature else ", poche plus fraîche ou plus vieille")))
    return out


ORDER = ([("all", "toutes les poches"), ("all", "niveaux au hasard (témoin)")] + [("conf", x) for x in ("0", "1", "2", "3 ou plus")]
         + [("confw", lab) for _, lab in CONFW_BUCKETS] + [("age", lab) for _, lab in AGE_BUCKETS]
         + [("type", TYPE_TXT[t]) for t in ("D", "W", "M", "S")] + [("type", "égaux (deux extrêmes au même prix)")]
         + [("side", "creux (ordres d'arrêt des acheteurs)"), ("side", "sommets (ordres d'arrêt des vendeurs)")]
         + [("combo", a + b) for a in ("fortes confluences", "confluences faibles ou moyennes") for b in (", poche de 1 à 10 jours", ", poche plus fraîche ou plus vieille")]
         + [("randconf", x) for x in ("témoin sans confluence", "témoin avec 1 confluence", "témoin avec 2 confluences ou plus")])
DIM_TXT = {"all": "Ensemble", "conf": "Nombre de confluences", "confw": "Confluences pondérées (année > mois > semaine > jour)", "age": "Âge de la poche",
           "type": "Type de poche", "side": "Côté", "combo": "Confluences et maturité ensemble", "randconf": "Niveaux au hasard selon leurs confluences"}


def run(b1h, start_ms: int, split_ms: int, end_ms: int | None = None, horizon: int = 24, k: float = 1.0, seed: int = 11, progress=None) -> dict:
    """b1h : fine.Bars 1 h. Renvoie le rapport (dict serialisable)."""
    n = len(b1h)
    candles = b1h.candles(0, n)
    end_ms = end_ms or int(b1h.t[-1]) + H
    atrs = atr_series(candles)
    sds = sd_series(candles)
    tab = reach_table(candles, atrs, hours=(horizon,))
    fmax = _fwd_extreme([c.h for c in candles], horizon, True)
    fmin = _fwd_extreme([c.l for c in candles], horizon, False)
    sw_hi, sw_lo = swing_points(b1h)
    sw = sorted([(tc, tp, p, "high") for tc, tp, p in sw_hi] + [(tc, tp, p, "low") for tc, tp, p in sw_lo])
    sw_t = [x[0] for x in sw]
    sw_i = 0
    tr = {kd: PeriodTracker(kd) for kd in ("D", "W", "M")}
    nd, nw = NakedPocs(30), NakedPocs(12)
    ext = {kd: None for kd in ("D", "W", "M")}          # (cle de periode, bas, instant du bas, haut, instant du haut)
    book = _Book()
    rnd = random.Random(seed)
    attr, reac, sweep = _Table(), _Table(), _Table()
    stats = {"touches": 0, "samples": 0, "open": 0}
    levels = []
    for i in range(n):
        c = candles[i]
        a_prev = atrs[i - 1] if i else None
        # 1) contacts pendant la bougie i (poches connues a la cloture de i-1)
        if c.t >= start_ms and c.t < end_ms and a_prev and i + 1 < n:
            keep = []
            for q in book.alive:
                hit = c.l <= q["price"] if q["kind"] == "low" else c.h >= q["price"]
                if not hit:
                    keep.append(q)
                    continue
                side = "support" if q["kind"] == "low" else "resistance"
                L, a = q["price"], a_prev
                res = outcome_at(candles, i + 1, L, side, a, horizon, k, k)
                if res == "open":
                    stats["open"] += 1
                    continue
                up, dn = L + k * a, L - k * a
                x = (c.c - dn) if side == "support" else (up - c.c)
                ov = RHO * sds[i]
                p0 = min(1.0, max(0.0, (x + ov) / (up - dn + 2 * ov)))
                nconf, pts, age_h = _features(q, levels, a, c.t)
                keys = _keys(q, nconf, pts, age_h)
                day, test = c.t // DAY, c.t >= split_ms
                reac.add(keys, day, 1.0 if res == "bounce" else 0.0, p0, test)
                back = c.c > L if q["kind"] == "low" else c.c < L
                sweep.add([(("sweep" if back else "break"), kk[0] + "|" + kk[1]) for kk in keys], day, 1.0 if res == "bounce" else 0.0, p0, test)
                stats["touches"] += 1
            book.alive = keep
        elif book.alive:
            book.alive = [q for q in book.alive if not (c.l <= q["price"] if q["kind"] == "low" else c.h >= q["price"])]
        # 2) la bougie i se ferme : periodes, POC nus, extremes de periodes, pivots confirmes, temoins
        prev_d, prev_w = tr["D"].prev, tr["W"].prev
        for t in tr.values():
            t.feed(c)
        if tr["D"].prev is not prev_d and tr["D"].prev:
            nd.on_rollover(tr["D"].prev["vp"]["poc"] if tr["D"].prev["vp"] else None, c.t)
            for s in (+1, -1):
                lvl = c.c * (1 + s * rnd.uniform(0.004, 0.03))
                book.add("high" if s > 0 else "low", lvl, "R", c.t + H)
        if tr["W"].prev is not prev_w and tr["W"].prev:
            nw.on_rollover(tr["W"].prev["vp"]["poc"] if tr["W"].prev["vp"] else None, c.t)
        nd.feed(c)
        nw.feed(c)
        for kd in ("D", "W", "M"):
            key = period_key(kd, c.t)
            e = ext[kd]
            if e is None or e[0] != key:
                if e is not None:                                  # la bougie i ouvre une nouvelle periode : extremes de la precedente, s'ils sont intacts
                    if c.l > e[1]:
                        book.add("low", e[1], kd, e[2])
                    if c.h < e[3]:
                        book.add("high", e[3], kd, e[4])
                e = (key, c.l, c.t, c.h, c.t)
            else:
                e = (key, *(e[1:3] if e[1] <= c.l else (c.l, c.t)), *(e[3:5] if e[3] >= c.h else (c.h, c.t)))
            ext[kd] = e
        t_close = c.t + H
        while sw_i < len(sw) and sw_t[sw_i] <= t_close:
            _tc, tp, p, kind = sw[sw_i]
            sw_i += 1
            book.add(kind, p, "S", tp)
        book.alive = [q for q in book.alive if t_close - q["born"] <= MAX_AGE_D * DAY and abs(q["price"] / c.c - 1) <= MAX_DIST]
        levels = _known_levels(tr, nd, nw, [], c.c)
        # 3) echantillon quotidien pour l'attraction
        a = atrs[i]
        if t_close % DAY == 0 and start_ms <= c.t < end_ms and a and fmax[i] is not None:
            day, test = c.t // DAY, c.t >= split_ms
            for q in book.alive:
                up_side = q["kind"] == "high"
                d = ((q["price"] - c.c) if up_side else (c.c - q["price"])) / a
                if not 0.5 <= d <= 8.0:
                    continue
                exp = reach_prob(tab, d, "up" if up_side else "down", horizon)
                if exp is None:
                    continue
                hit = fmax[i] >= q["price"] if up_side else fmin[i] <= q["price"]
                nconf, pts, age_h = _features(q, levels, a, t_close)
                attr.add(_keys(q, nconf, pts, age_h), day, 1.0 if hit else 0.0, exp, test)
                stats["samples"] += 1
        if progress and i % 20000 == 0:
            progress(i, n)
    rep = {"version": 1, "kind": "pockets", "horizon": horizon, "k": k, "bars": n, "start": start_ms, "split": split_ms, "end": end_ms,
           "from": int(b1h.t[0]), "to": int(b1h.t[-1]), "stats": stats, "dims": DIM_TXT,
           "attraction": attr.out(ORDER), "reaction": reac.out(ORDER),
           "sweep": sweep.out([(m, d + "|" + v) for m in ("sweep", "break") for d, v in ORDER])}
    rep["summary"] = summarize(rep)
    return rep


def _row(rows, dim, name):
    return next((r for r in rows if r["dim"] == dim and r["name"] == name), None)


def _n(v, signed=False):
    """Nombre a la francaise (virgule, vrai signe moins)."""
    t = f"{v:+.1f}" if signed else f"{v:.1f}"
    return t.replace(".", ",").replace("-", "−")


def summarize(rep: dict) -> dict:
    """Phrases de conclusion, sans enjoliver."""
    out = []
    A, R = rep["attraction"], rep["reaction"]
    base_a, base_r = _row(A, "all", "toutes les poches"), _row(R, "all", "toutes les poches")
    rnd_a, rnd_r = _row(A, "all", "niveaux au hasard (témoin)"), _row(R, "all", "niveaux au hasard (témoin)")
    if base_a and rnd_a and base_a["n"] and rnd_a["n"]:
        out.append(f"Attraction : les poches sont touchées en 24 h {_n(base_a['p'] * 100)} % du temps pour {_n(base_a['exp'] * 100)} % attendus à la même distance "
                   f"(écart {_n(base_a['ex'] * 100, True)} points, {base_a['verdict']}) ; témoin au hasard : écart {_n(rnd_a['ex'] * 100, True)} points ({rnd_a['verdict']}).")
    if base_r and rnd_r and base_r["n"] and rnd_r["n"]:
        out.append(f"Réaction au premier contact : retournement {_n(base_r['p'] * 100)} % pour {_n(base_r['exp'] * 100)} % attendus "
                   f"(écart {_n(base_r['ex'] * 100, True)} points, {base_r['verdict']}) ; témoin au hasard : écart {_n(rnd_r['ex'] * 100, True)} points ({rnd_r['verdict']}).")
    for label, rows in (("attraction", A), ("réaction", R)):
        cw = [_row(rows, "confw", lab) for _, lab in CONFW_BUCKETS]
        if all(cw):
            out.append(f"Confluences pondérées ({label}) : faibles {_n(cw[0]['ex'] * 100, True)}, moyennes {_n(cw[1]['ex'] * 100, True)}, fortes {_n(cw[2]['ex'] * 100, True)} points "
                       f"({cw[2]['verdict']} pour les fortes).")
        ag = [_row(rows, "age", lab) for _, lab in AGE_BUCKETS]
        if all(ag):
            out.append(f"Âge ({label}) : " + ", ".join(f"{lab} {_n(r['ex'] * 100, True)}" for (_, lab), r in zip(AGE_BUCKETS, ag)) + " points.")
    return {"lines": out}
