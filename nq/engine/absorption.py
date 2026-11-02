"""Absorptions mesurées AU PRIX, dans le footprint. Module PUR.

Une absorption, c'est un flux agressif important qui frappe un prix sans le faire céder : des ordres passifs (limites) ont tout pris.
On la cherche de deux façons, sur chaque barre (de 1 minute en direct), à partir de son footprint et des échelles habituelles des `base`
barres PRÉCÉDENTES (rien du futur) :

  1. au niveau (« niveau ») : dans les `edge_ticks` ticks du plus bas de la barre, les vendeurs agressifs (au bid) ont traité un volume
     ≥ `level_k` × le plus gros niveau habituel d'une barre, ce volume pèse au moins `share_min` des ventes agressives de la barre, et la
     barre a clôturé LOIN de son plus bas (position de clôture ≥ `clv_min`) : les vendeurs ont tapé, le prix n'a pas suivi -> acheteurs
     passifs, signal haussier. Symétrique au plus haut (acheteurs agressifs absorbés, signal baissier) ;
  2. effort sans résultat (« effort ») : volume ≥ `effort_vol` × l'habituel, |delta| ≥ `effort_delta` × l'habituel, mais une étendue
     ≤ `effort_range` × l'habituelle et une clôture qui ne va pas dans le sens du delta.

Chaque absorption a un prix (moyenne pondérée du volume absorbé), une zone [lo, hi], une quantité et une force 0..1. Puis on la SUIT
dans les barres d'après (`track`) : active tant que le prix ne traite pas au-delà de la zone de plus de `break_ticks` ticks, cassée sinon,
expirée en fin de journée de trading ; chaque retour dans la zone qui tient est compté comme un « test ». Deux absorptions du même côté au
même prix (à `merge_ticks` près) tant que la première tient = une seule zone, « répétée », plus forte (souvent un ordre caché qui se recharge).

Ce sont des valeurs de départ : elles se mesurent (onglet Backtest) avant qu'on s'y fie."""
import math
from dataclasses import dataclass

from . import clock


@dataclass(frozen=True)
class AbsParams:
    base: int = 60              # barres précédentes qui donnent les échelles habituelles
    edge_ticks: int = 3         # largeur (ticks) de la zone d'extrême où l'on mesure le flux absorbé
    level_k: float = 1.6        # flux absorbé ≥ k × le plus gros niveau habituel d'une barre
    share_min: float = 0.30     # ... et ≥ cette part du flux agressif du même côté dans la barre
    clv_min: float = 0.45       # clôture loin de l'extrême : 0 = sur l'extrême, 1 = à l'opposé
    effort_vol: float = 2.0     # effort sans résultat : volume ≥ 2 × l'habituel
    effort_range: float = 0.6   # ... étendue ≤ 0,6 × l'habituelle
    effort_delta: float = 1.5   # ... |delta| ≥ 1,5 × l'habituel (racine de la moyenne des carrés)
    break_ticks: int = 4        # zone cassée quand le prix traite au-delà de N ticks (1 point sur NQ)
    merge_ticks: int = 2        # deux absorptions du même côté à N ticks près : la même zone
    min_strength: float = 0.30  # en dessous : ignorée


PARAMS = AbsParams()


def _features(b, tick):
    """(volume, étendue, delta, plus gros niveau de la barre) — le plus gros niveau vaut 0 sans footprint."""
    lvl = max((s + q for s, q in b.fp.values()), default=0.0) if b.fp else 0.0
    return b.v, b.h - b.l, b.bv - b.sv, lvl


def _scales(feats):
    n = len(feats)
    if not n:
        return None
    avg_v = sum(f[0] for f in feats) / n
    avg_r = sum(f[1] for f in feats) / n
    rms_d = math.sqrt(sum(f[2] * f[2] for f in feats) / n)
    avg_l = sum(f[3] for f in feats) / n
    return avg_v, avg_r, rms_d, avg_l


def _eval(b, sc, tick, p: AbsParams):
    """Absorption éventuelle de la barre `b` connaissant les échelles `sc` des barres d'avant. dict ou None."""
    avg_v, avg_r, rms_d, avg_l = sc
    if b.v <= 0 or avg_v <= 0:
        return None
    rng = b.h - b.l
    d = b.bv - b.sv
    vr = b.v / avg_v
    clv = (b.c - b.l) / rng if rng > 0 else 0.5
    cands = []
    if b.fp and avg_l > 0:
        lo_i, hi_i = int(round(b.l / tick)), int(round(b.h / tick))
        for side, idxs, agg_tot, k_agg, close_away in (
                ("bull", range(lo_i, min(hi_i, lo_i + p.edge_ticks - 1) + 1), b.sv, 0, clv),
                ("bear", range(max(lo_i, hi_i - p.edge_ticks + 1), hi_i + 1), b.bv, 1, 1.0 - clv)):
            rows = [(k, b.fp[k][k_agg]) for k in idxs if k in b.fp and b.fp[k][k_agg] > 0]
            qty = sum(q for _, q in rows)
            if not rows or agg_tot <= 0 or qty < p.level_k * avg_l or qty < p.share_min * agg_tot or close_away < p.clv_min:
                continue
            price = sum(k * q for k, q in rows) / qty * tick
            agrees = (d < 0) if side == "bull" else (d > 0)          # le delta de la barre va dans le sens du flux absorbé : plus net
            s = (0.40 * min(1.0, qty / (3.0 * p.level_k * avg_l)) + 0.25 * min(1.0, vr / 3.0)
                 + 0.20 * min(1.0, close_away) + 0.15 * (1.0 if agrees else 0.4))
            cands.append({"side": side, "kind": "niveau", "price": round(round(price / tick) * tick, 10), "qty": round(qty, 2),
                          "lo": round(min(k for k, _ in rows) * tick, 10), "hi": round(max(k for k, _ in rows) * tick, 10), "strength": s})
    if (avg_r > 0 and rms_d > 0 and vr >= p.effort_vol and rng <= p.effort_range * avg_r and abs(d) >= p.effort_delta * rms_d):
        side = "bull" if d < 0 else "bear"
        held = clv >= 0.4 if side == "bull" else clv <= 0.6           # le prix n'a pas suivi le flux
        if held:
            k_agg = 0 if side == "bull" else 1
            if b.fp:
                k = max(b.fp, key=lambda i: b.fp[i][k_agg])
                price = k * tick
            else:
                price = b.l if side == "bull" else b.h
            s = 0.35 * min(1.0, vr / 4.0) + 0.35 * min(1.0, abs(d) / (3.0 * rms_d)) + 0.30 * max(0.0, 1.0 - rng / avg_r)
            same = [c for c in cands if c["side"] == side]
            if same:                                                    # les deux lectures disent la même chose : on renforce
                same[0]["kind"] = "niveau+effort"
                same[0]["strength"] = min(1.0, same[0]["strength"] + 0.15)
            else:
                cands.append({"side": side, "kind": "effort", "price": round(price, 10), "qty": round(abs(d), 2),
                              "lo": round(price - tick, 10), "hi": round(price + tick, 10), "strength": s})
    cands = [c for c in cands if c["strength"] >= p.min_strength]
    if not cands:
        return None
    best = max(cands, key=lambda c: c["strength"])
    best["strength"] = round(min(1.0, best["strength"]), 3)
    best["t"] = b.t
    return best


def detect(bars, i: int, tick: float, p: AbsParams = PARAMS):
    """Absorption éventuelle de la barre i (échelles prises sur les `base` barres d'avant). None s'il n'y a pas assez d'historique."""
    if i < p.base:
        return None
    sc = _scales([_features(b, tick) for b in bars[i - p.base:i]])
    return _eval(bars[i], sc, tick, p) if sc else None


def scan(bars, tick: float, p: AbsParams = PARAMS, known: dict | None = None, start: int = 0) -> list:
    """Toutes les absorptions de `bars` (échelles glissantes en O(1) par barre). `known` : cache {t: (nb de transactions, volume, résultat)}
    des barres déjà évaluées ; une transaction arrivée en retard dans une barre déjà passée change son nombre de transactions : elle est alors
    réévaluée. La DERNIÈRE barre, qui se forme, n'est jamais gardée. Ne renvoie que les barres d'indice ≥ `start`. Chaque résultat porte
    « i », son indice dans `bars`."""
    out = []
    n = len(bars)
    if n <= p.base:
        return out
    feats = [_features(b, tick) for b in bars]
    s_v = s_r = s_d2 = s_l = 0.0
    for j in range(p.base):
        f = feats[j]
        s_v += f[0]; s_r += f[1]; s_d2 += f[2] * f[2]; s_l += f[3]
    nb = float(p.base)
    for i in range(p.base, n):
        if i >= start:
            b = bars[i]
            last = i == n - 1
            hit = known.get(b.t) if known is not None and not last else None
            if hit is not None and hit[0] == b.n and hit[1] == b.v:
                r = hit[2]
            else:
                r = _eval(b, (s_v / nb, s_r / nb, math.sqrt(max(s_d2, 0.0) / nb), s_l / nb), tick, p)
                if known is not None and not last:
                    known[b.t] = (b.n, b.v, r)
            if r:
                out.append(dict(r, i=i))
        f_in, f_out = feats[i], feats[i - p.base]
        s_v += f_in[0] - f_out[0]; s_r += f_in[1] - f_out[1]; s_d2 += f_in[2] * f_in[2] - f_out[2] * f_out[2]; s_l += f_in[3] - f_out[3]
    return out


def track(marks: list, bars, tick: float, p: AbsParams = PARAMS) -> list:
    """Suit chaque absorption (« i » = indice dans `bars`) dans les barres SUIVANTES : statut active / cassée / expirée, nombre de tests,
    heure de fin. Fusionne une absorption avec une zone précédente du même côté, au même prix, qui tenait encore à ce moment-là.
    Renvoie de nouvelles entrées (les marques ne sont pas modifiées)."""
    out = []
    brk = p.break_ticks * tick

    def advance(z, upto):
        """Lit les barres z["_j"] .. upto (inclus) tant que la zone est active."""
        while z["status"] == "active" and z["_j"] <= upto:
            b = bars[z["_j"]]
            z["_j"] += 1
            if clock.trading_day(b.t) != z["day"]:
                z["status"], z["end"] = "expirée", b.t
                return
            if (z["side"] == "bull" and b.l < z["lo"] - brk) or (z["side"] == "bear" and b.h > z["hi"] + brk):
                z["status"], z["end"] = "cassée", b.t
                return
            inside = b.l <= z["hi"] + tick and b.h >= z["lo"] - tick
            if inside and z["_away"]:
                z["tests"] += 1
                z["_away"] = False
            elif not inside and ((z["side"] == "bull" and b.l > z["hi"] + 4 * tick) or (z["side"] == "bear" and b.h < z["lo"] - 4 * tick)):
                z["_away"] = True

    for m in sorted(marks, key=lambda x: x["i"]):
        i = m["i"]
        for z in out:
            advance(z, i)                                # la barre de la nouvelle marque compte : elle peut casser la zone précédente
        day = clock.trading_day(m["t"])
        prev = next((o for o in reversed(out) if o["side"] == m["side"] and o["status"] == "active" and o["day"] == day
                     and abs(o["price"] - m["price"]) <= p.merge_ticks * tick), None)
        if prev is not None:                             # la même zone qui se recharge (souvent un ordre caché)
            prev["count"] += 1
            prev["qty"] = round(prev["qty"] + m["qty"], 2)
            prev["strength"] = round(min(1.0, max(prev["strength"], m["strength"]) + 0.12), 3)
            prev["lo"], prev["hi"] = min(prev["lo"], m["lo"]), max(prev["hi"], m["hi"])
            if "répétée" not in prev["kind"]:
                prev["kind"] += " répétée"
            prev["_j"] = max(prev["_j"], i + 1)
            continue
        out.append(dict(m, status="active", tests=0, end=None, count=1, day=day, _j=i + 1, _away=False))
    for z in out:
        advance(z, len(bars) - 1)
        z.pop("_j")
        z.pop("_away")
    return out
