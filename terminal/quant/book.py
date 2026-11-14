"""Carnet d'ordres (niveau 2) : déséquilibre pondéré par la distance, murs, ordres retirés ou absorbés (V45).

Entrées : bids et asks = [(prix, quantité)] en Decimal, du meilleur au moins bon (texte de la bourse lu par quant.num.D).

- Déséquilibre (OBI) : (B - A) / (B + A), de -1 (que des vendeurs) à +1 (que des acheteurs). B et A sont les dollars en attente de chaque
  côté dans une bande de ± `band` autour du prix milieu, chaque niveau pesant 1 - distance / band (poids linéaire : 1 au prix milieu,
  0 au bord de la bande ; rationnel, donc exact en décimal). Un ordre proche du prix compte donc plus qu'un ordre lointain.
- Murs : niveaux dont les dollars en attente valent au moins `k` fois la médiane des niveaux de la bande, et au moins `min_usd`.
- WallTracker : suit chaque mur dans le temps et classe sa fin :
    « exécuté »  le prix l'a traversé et le volume échangé à ce prix vaut au moins la moitié de sa taille : liquidité réelle ;
    « retiré »   il disparaît alors que le prix s'en approchait (à moins de `near`) et presque rien n'a été échangé dessus : possible
                 ordre d'affichage (spoofing). Ce n'est qu'un indice : un retrait est aussi une décision normale d'un teneur de marché ;
    « absorbe »  il est toujours là alors qu'il a déjà été échangé plus que sa taille affichée : ordre rechargé (iceberg).
Module PUR."""
from __future__ import annotations
from decimal import Decimal

from .num import CTX, D, ONE, ZERO

TWO = Decimal(2)


def mid_price(bids, asks):
    if not bids or not asks:
        return None
    return CTX.divide(CTX.add(bids[0][0], asks[0][0]), TWO)


def spread_bps(bids, asks):
    m = mid_price(bids, asks)
    if m is None or m <= 0:
        return None
    return CTX.multiply(CTX.divide(CTX.subtract(asks[0][0], bids[0][0]), m), Decimal(10000))


def depth_usd(levels, mid, band) -> Decimal:
    """Dollars en attente d'un côté à moins de `band` (fraction) du prix milieu."""
    lim = CTX.multiply(mid, D(band))
    tot = ZERO
    for p, q in levels:
        if abs(CTX.subtract(p, mid)) > lim:
            break
        tot = CTX.add(tot, CTX.multiply(p, q))
    return tot


def weighted_side(levels, mid, band) -> Decimal:
    lim = CTX.multiply(mid, D(band))
    tot = ZERO
    for p, q in levels:
        d = abs(CTX.subtract(p, mid))
        if d > lim:
            break
        w = CTX.subtract(ONE, CTX.divide(d, lim))
        tot = CTX.add(tot, CTX.multiply(CTX.multiply(p, q), w))
    return tot


def obi(bids, asks, band="0.005", weighted: bool = True) -> dict | None:
    """Déséquilibre du carnet dans ± band (0.005 = 0,5 %). Renvoie obi, bid et ask (dollars pondérés), mid."""
    mid = mid_price(bids, asks)
    if mid is None:
        return None
    if weighted:
        b, a = weighted_side(bids, mid, band), weighted_side(asks, mid, band)
    else:
        b, a = depth_usd(bids, mid, band), depth_usd(asks, mid, band)
    tot = CTX.add(b, a)
    return {"obi": CTX.divide(CTX.subtract(b, a), tot) if tot > 0 else ZERO, "bid": b, "ask": a, "mid": mid, "band": D(band)}


def _median(xs: list) -> Decimal:
    s = sorted(xs)
    n = len(s)
    if not n:
        return ZERO
    return s[n // 2] if n % 2 else CTX.divide(CTX.add(s[n // 2 - 1], s[n // 2]), TWO)


def walls(bids, asks, band="0.02", k="8", min_usd="0", top: int = 5) -> dict:
    """Murs de chaque côté dans ± band : [(prix, dollars, multiple de la médiane, distance en fraction du prix milieu)]."""
    mid = mid_price(bids, asks)
    out = {"bid": [], "ask": [], "mid": mid, "median": ZERO}
    if mid is None:
        return out
    lim = CTX.multiply(mid, D(band))
    sides = {}
    allv = []
    for name, lv in (("bid", bids), ("ask", asks)):
        rows = []
        for p, q in lv:
            if abs(CTX.subtract(p, mid)) > lim:
                break
            rows.append((p, CTX.multiply(p, q)))
        sides[name] = rows
        allv += [u for _, u in rows if u > 0]
    med = _median(allv)
    out["median"] = med
    if med <= 0:
        return out
    thr = max(CTX.multiply(med, D(k)), D(min_usd))
    for name, rows in sides.items():
        w = [(p, u, CTX.divide(u, med), CTX.divide(abs(CTX.subtract(p, mid)), mid)) for p, u in rows if u >= thr]
        w.sort(key=lambda r: -r[1])
        out[name] = sorted(w[:top], key=lambda r: r[3])
    return out


class WallTracker:
    """Voir l'en-tête. `update(t_ms, bids, asks)` à chaque photo du carnet ; `on_trade(prix, dollars, side)` à chaque transaction
    (side = +1 achat agressif : il frappe les ASKS ; -1 vente agressive : elle frappe les BIDS). `events` : fins de murs et absorptions."""

    def __init__(self, band="0.02", k="8", min_usd="0", near="0.001", gone_pct="30", max_events: int = 200):
        self.band, self.k, self.min_usd, self.near = D(band), D(k), D(min_usd), D(near)
        self.gone = CTX.divide(D(gone_pct), Decimal(100))
        self.live: dict[tuple, dict] = {}
        self.events: list[dict] = []
        self.max_events = max_events

    def on_trade(self, price, usd, side: int) -> None:
        w = self.live.get(("ask" if side > 0 else "bid", D(price)))
        if w is not None:
            w["traded"] = CTX.add(w["traded"], D(usd))

    def _emit(self, ev: dict) -> None:
        self.events.append(ev)
        if len(self.events) > self.max_events:
            del self.events[:len(self.events) - self.max_events]

    def update(self, t_ms: int, bids, asks) -> list:
        """Met à jour les murs suivis ; renvoie les événements de cette photo."""
        new = []
        found = walls(bids, asks, self.band, self.k, self.min_usd, top=8)
        mid = found["mid"]
        if mid is None:
            return new
        size = {}
        lim = CTX.multiply(mid, self.band)
        for name, lv in (("bid", bids), ("ask", asks)):
            for p, q in lv:
                if abs(CTX.subtract(p, mid)) > lim:
                    break
                size[(name, p)] = CTX.multiply(p, q)
        for name in ("bid", "ask"):
            for p, u, mult, _ in found[name]:
                key = (name, p)
                w = self.live.get(key)
                if w is None:
                    self.live[key] = {"side": name, "price": p, "first": t_ms, "last": t_ms, "peak": u, "cur": u, "traded": ZERO,
                                      "mult": mult, "minDist": CTX.divide(abs(CTX.subtract(p, mid)), mid), "absorbed": False}
        for key, w in list(self.live.items()):
            name, p = key
            cur = size.get(key, ZERO)
            dist = CTX.divide(abs(CTX.subtract(p, mid)), mid)
            crossed = (name == "bid" and bids and bids[0][0] < p) or (name == "ask" and asks and asks[0][0] > p)
            if cur > 0 and not crossed:
                w["last"], w["cur"] = t_ms, cur
                w["peak"] = max(w["peak"], cur)
                w["minDist"] = min(w["minDist"], dist)
                if not w["absorbed"] and w["traded"] >= w["peak"]:
                    w["absorbed"] = True
                    ev = self._event(w, t_ms, "absorbe")
                    new.append(ev)
                if cur >= CTX.multiply(w["peak"], self.gone):
                    continue
            if crossed or w["traded"] >= CTX.divide(w["peak"], TWO):
                kind = "exécuté"
            elif w["minDist"] <= self.near:
                kind = "retiré"
            else:
                kind = "annulé"
            new.append(self._event(w, t_ms, kind))
            del self.live[key]
        for ev in new:
            self._emit(ev)
        return new

    @staticmethod
    def _event(w: dict, t_ms: int, kind: str) -> dict:
        return {"t": t_ms, "kind": kind, "side": w["side"], "price": w["price"], "peak": w["peak"], "traded": w["traded"],
                "lifeMs": t_ms - w["first"], "minDist": w["minDist"], "mult": w["mult"]}

    def active(self) -> list:
        return sorted(self.live.values(), key=lambda w: -w["cur"])
