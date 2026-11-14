"""CVD exact, transaction par transaction (V45).

Chaque transaction porte le côté de l'AGRESSEUR (celui qui a pris la liquidité) : chez Binance, `m` (isBuyerMaker) vrai = l'acheteur
était passif, donc une VENTE agressive. Le delta d'une période est achats agressifs - ventes agressives ; le CVD est sa somme cumulée.

Arithmétique : prix et quantités en ENTIERS (unités de 10^-8, lues du texte de la bourse par quant.num.units) ; le notionnel en dollars
est le produit de deux entiers (unités de 10^-16) : les sommes sont exactes quel que soit le nombre de transactions. Les seuils de
détection se comparent par produits d'entiers (jamais de division flottante).

- TickCvd : barres de `step_ms` (une minute par défaut) construites des transactions : ouverture, haut, bas, clôture, achats, ventes
  (pièces et dollars), nombre de transactions ; chaque barre sait si elle est COMPLÈTE (aucune coupure du flux pendant sa durée). Les
  barres passées se chargent des bougies officielles (volume acheteur agressif exact de la bourse) par `seed`.
- divergences : creux et sommets confirmés (n barres de chaque côté) du prix comparés au CVD aux mêmes instants. Une divergence n'est
  connue qu'à la confirmation du second pivot (`known`), jamais avant : pas de regard vers l'avenir.
- absorptions : beaucoup de volume agressif d'un côté (delta fort) sans déplacement du prix dans ce sens.
- VenueFlow : plusieurs bourses, additionnées en dollars.
Module PUR."""
from __future__ import annotations
from fractions import Fraction

from .num import SCALE, UNIT

T, O, H, L, C, BUY, SELL, BUYQ, SELLQ, N, OK = range(11)
QUNIT = UNIT * UNIT                         # notionnel : unités de 10^-16 dollar


class TickCvd:
    """Barres exactes d'un marché. `add` pour chaque transaction ; `gap(t0, t1)` quand le flux a été coupé (les barres touchées ne sont plus
    complètes) ; `seed` / `replace` pour les barres officielles."""

    def __init__(self, step_ms: int = 60_000, keep: int = 2880):
        self.step, self.keep = int(step_ms), int(keep)
        self.bars: dict[int, list] = {}
        self.first_tick = None              # heure de la première transaction reçue en direct
        self.last_t = 0
        self.last_px = None
        self.ticks = 0
        self.buy = self.sell = 0            # cumuls depuis le démarrage (pièces, unités)
        self.buyq = self.sellq = 0          # cumuls en dollars (unités de 10^-16)

    # ---------- écriture ----------
    def add(self, t_ms: int, px_u: int, qty_u: int, side: int, quote_u: int | None = None) -> None:
        """Une transaction. side = +1 achat agressif, -1 vente agressive. `quote_u` (dollars, unités de 10^-8) pour les contrats cotés en
        dollars (inverses) : la quantité en pièces n'est alors qu'indicative."""
        if qty_u <= 0 or px_u <= 0:
            return
        q = px_u * qty_u if quote_u is None else quote_u * UNIT
        t0 = t_ms - t_ms % self.step
        b = self.bars.get(t0)
        if b is None:
            first = self.first_tick is None
            b = self.bars[t0] = [t0, px_u, px_u, px_u, px_u, 0, 0, 0, 0, 0, not first and t_ms >= self.last_t]
            if first:
                self.first_tick = t_ms
                b[OK] = t_ms == t0              # complète seulement si le flux a commencé pile au début de la barre
            if len(self.bars) > self.keep + 8:
                for k in sorted(self.bars)[:len(self.bars) - self.keep]:
                    del self.bars[k]
        if px_u > b[H]:
            b[H] = px_u
        if px_u < b[L]:
            b[L] = px_u
        if t_ms >= self.last_t:
            b[C] = px_u
            self.last_t, self.last_px = t_ms, px_u
        if side > 0:
            b[BUY] += qty_u
            b[BUYQ] += q
            self.buy += qty_u
            self.buyq += q
        else:
            b[SELL] += qty_u
            b[SELLQ] += q
            self.sell += qty_u
            self.sellq += q
        b[N] += 1
        self.ticks += 1

    def gap(self, t0_ms: int, t1_ms: int) -> None:
        """Flux coupé de t0 à t1 : les barres de cet intervalle (et celles qui n'existent pas encore) ne sont pas complètes."""
        t = t0_ms - t0_ms % self.step
        while t <= t1_ms:
            b = self.bars.get(t)
            if b is None:
                self.bars[t] = [t, 0, 0, 0, 0, 0, 0, 0, 0, 0, False]
            else:
                b[OK] = False
            t += self.step

    def seed(self, rows, replace: bool = True) -> int:
        """Barres officielles : [(t0, o, h, l, c, achats, ventes, achats $, ventes $, n)] en unités entières. Elles sont complètes par
        définition (c'est la bourse qui les a comptées). `replace` faux : seulement les barres absentes ou incomplètes."""
        n = 0
        for r in rows:
            t0 = int(r[0])
            cur = self.bars.get(t0)
            if cur is not None and cur[OK] and not replace:
                continue
            self.bars[t0] = [t0, *[int(x) for x in r[1:10]], True]
            n += 1
        if len(self.bars) > self.keep + 8:
            for k in sorted(self.bars)[:len(self.bars) - self.keep]:
                del self.bars[k]
        return n

    def check(self, row) -> str | None:
        """Compare une barre faite des transactions à la barre officielle de la bourse : None si le volume et le volume acheteur sont
        IDENTIQUES à l'unité près, sinon le texte de l'écart. C'est le contrôle d'intégrité du flux en direct."""
        b = self.bars.get(int(row[0]))
        if b is None:
            return "barre absente"
        v, bv = b[BUY] + b[SELL], b[BUY]
        ov, obv = int(row[5]) + int(row[6]), int(row[5])
        if (v, bv) == (ov, obv):
            return None
        return f"volume {v / UNIT:.8f} contre {ov / UNIT:.8f}, achats {bv / UNIT:.8f} contre {obv / UNIT:.8f}"

    # ---------- lecture ----------
    def closed(self, now_ms: int, since_ms: int = 0) -> list:
        """Barres FERMÉES (fin <= now_ms), dans l'ordre, sans les barres vides créées par une coupure."""
        return [self.bars[k] for k in sorted(self.bars) if since_ms <= k and k + self.step <= now_ms and self.bars[k][N] > 0]

    def window(self, t0_ms: int, t1_ms: int) -> dict:
        """Sommes exactes des barres qui commencent dans [t0, t1[ : achats, ventes, delta (pièces et dollars), part couverte."""
        buy = sell = buyq = sellq = n = have = 0
        t = t0_ms - t0_ms % self.step
        if t < t0_ms:
            t += self.step
        want = 0
        while t < t1_ms:
            want += 1
            b = self.bars.get(t)
            if b is not None:
                buy += b[BUY]
                sell += b[SELL]
                buyq += b[BUYQ]
                sellq += b[SELLQ]
                n += b[N]
                have += 1 if b[OK] else 0
            t += self.step
        return {"buy": buy, "sell": sell, "delta": buy - sell, "buyq": buyq, "sellq": sellq, "deltaq": buyq - sellq, "n": n,
                "cover": Fraction(have, want) if want else Fraction(0)}


def resample(bars: list, step_ms: int) -> list:
    """Regroupe des barres (triées) en barres de `step_ms` ; une barre regroupée est complète si toutes ses parties le sont."""
    out, cur, parts = [], None, 0
    for b in bars:
        t0 = b[T] - b[T] % step_ms
        if cur is None or cur[T] != t0:
            cur = [t0, b[O], b[H], b[L], b[C], 0, 0, 0, 0, 0, True]
            out.append(cur)
        if b[H] > cur[H]:
            cur[H] = b[H]
        if b[L] < cur[L]:
            cur[L] = b[L]
        cur[C] = b[C]
        for k in (BUY, SELL, BUYQ, SELLQ, N):
            cur[k] += b[k]
        cur[OK] = cur[OK] and b[OK]
    return out


def cumulative(bars: list, quote: bool = False) -> list:
    """CVD (somme cumulée des deltas) à la clôture de chaque barre, en unités entières (pièces, ou dollars si quote)."""
    out, c = [], 0
    b_i, s_i = (BUYQ, SELLQ) if quote else (BUY, SELL)
    for b in bars:
        c += b[b_i] - b[s_i]
        out.append(c)
    return out


# ---------- divergences prix / CVD ----------
def pivots(vals: list, left: int, right: int, low: bool) -> list:
    """Indices des creux (low) ou sommets : strictement plus extrême que les `left` valeurs précédentes, au moins aussi extrême que les
    `right` suivantes. Un pivot à l'indice i n'est connu qu'à la clôture de la barre i + right."""
    out = []
    for i in range(left, len(vals) - right):
        x = vals[i]
        if low:
            if all(x < vals[i - q] for q in range(1, left + 1)) and all(x <= vals[i + q] for q in range(1, right + 1)):
                out.append(i)
        elif all(x > vals[i - q] for q in range(1, left + 1)) and all(x >= vals[i + q] for q in range(1, right + 1)):
            out.append(i)
    return out


DIV_TEXT = {
    ("bull", "regular"): "Divergence haussière : le prix fait un plus bas plus bas, le CVD un plus bas plus haut (les vendeurs agressifs s'épuisent)",
    ("bull", "hidden"): "Divergence haussière cachée : le prix fait un plus bas plus haut, le CVD un plus bas plus bas (les ventes agressives sont absorbées dans la hausse)",
    ("bear", "regular"): "Divergence baissière : le prix fait un plus haut plus haut, le CVD un plus haut plus bas (les acheteurs agressifs s'épuisent)",
    ("bear", "hidden"): "Divergence baissière cachée : le prix fait un plus haut plus bas, le CVD un plus haut plus haut (les achats agressifs sont absorbés dans la baisse)",
}


def divergences(bars: list, left: int = 3, right: int = 3, max_span: int = 120, min_span: int = 4, quote: bool = False) -> list:
    """Divergences entre deux creux (ou deux sommets) CONSÉCUTIFS du prix. Chaque résultat : side ('bull' / 'bear'), kind ('regular' /
    'hidden'), t1 / t2 (heures des deux pivots), p1 / p2 (prix, unités), c1 / c2 (CVD à la clôture des barres pivots), known (heure à partir
    de laquelle la divergence est connue : clôture de la barre t2 + right barres), strength (écart de CVD rapporté au volume échangé entre
    les deux pivots, fraction exacte)."""
    if len(bars) < left + right + 2:
        return []
    cv = cumulative(bars, quote)
    b_i, s_i = (BUYQ, SELLQ) if quote else (BUY, SELL)
    step = bars[1][T] - bars[0][T] if len(bars) > 1 else 0
    out = []
    for low, side in ((True, "bull"), (False, "bear")):
        px = [b[L] if low else b[H] for b in bars]
        pv = pivots(px, left, right, low)
        for a, c in zip(pv, pv[1:]):
            if not (min_span <= c - a <= max_span):
                continue
            p1, p2, c1, c2 = px[a], px[c], cv[a], cv[c]
            if low:
                kind = "regular" if (p2 < p1 and c2 > c1) else "hidden" if (p2 > p1 and c2 < c1) else None
            else:
                kind = "regular" if (p2 > p1 and c2 < c1) else "hidden" if (p2 < p1 and c2 > c1) else None
            if kind is None:
                continue
            vol = sum(bars[k][b_i] + bars[k][s_i] for k in range(a + 1, c + 1))
            out.append({"side": side, "kind": kind, "t1": bars[a][T], "t2": bars[c][T], "p1": p1, "p2": p2, "c1": c1, "c2": c2,
                        "known": bars[c + right][T] + step, "strength": Fraction(abs(c2 - c1), vol) if vol else Fraction(0),
                        "text": DIV_TEXT[(side, kind)]})
    out.sort(key=lambda d: d["known"])
    return out


# ---------- absorption ----------
def _median(xs: list):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0
    return s[n // 2] if n % 2 else Fraction(s[n // 2 - 1] + s[n // 2], 2)


def absorptions(bars: list, base: int = 60, vol_pct: int = 200, imb_pct: int = 25, move_pct: int = 25, quote: bool = False) -> list:
    """Barres où un côté agresse fort sans déplacer le prix. Conditions, toutes en entiers :
      volume de la barre >= vol_pct % de la médiane des `base` barres précédentes ;
      |delta| >= imb_pct % du volume ;
      déplacement du prix DANS LE SENS du delta (clôture - ouverture) <= move_pct % de l'amplitude médiane des barres précédentes.
    side : 'bull' = ventes agressives absorbées par des acheteurs passifs ; 'bear' = achats agressifs absorbés par des vendeurs passifs.
    Chaque absorption n'utilise que les barres jusqu'à la sienne : connue à sa clôture."""
    b_i, s_i = (BUYQ, SELLQ) if quote else (BUY, SELL)
    out = []
    for i in range(base, len(bars)):
        b = bars[i]
        v = b[b_i] + b[s_i]
        d = b[b_i] - b[s_i]
        if v <= 0 or d == 0 or abs(d) * 100 < imb_pct * v:
            continue
        prev = bars[i - base:i]
        med_v = _median([p[b_i] + p[s_i] for p in prev])
        med_r = _median([p[H] - p[L] for p in prev])
        if med_v <= 0 or v * 100 < vol_pct * med_v:
            continue
        move = (b[C] - b[O]) * (1 if d > 0 else -1)
        if move * 100 > move_pct * med_r:
            continue
        out.append({"t": b[T], "side": "bear" if d > 0 else "bull", "delta": d, "volume": v, "imb": Fraction(abs(d), v),
                    "volRatio": Fraction(v) / Fraction(med_v), "move": b[C] - b[O], "price": b[C], "ok": b[OK],
                    "text": ("Achats agressifs absorbés : gros volume acheteur sans hausse du prix (vendeur passif)" if d > 0 else
                             "Ventes agressives absorbées : gros volume vendeur sans baisse du prix (acheteur passif)")})
    return out


# ---------- plusieurs bourses ----------
class VenueFlow:
    """Un TickCvd par bourse et par marché ; les totaux se font en DOLLARS (les contrats n'ont pas tous la même taille)."""

    def __init__(self, step_ms: int = 60_000, keep: int = 2880):
        self.step, self.keep = step_ms, keep
        self.venues: dict[str, TickCvd] = {}

    def of(self, venue: str) -> TickCvd:
        v = self.venues.get(venue)
        if v is None:
            v = self.venues[venue] = TickCvd(self.step, self.keep)
        return v

    def add(self, venue: str, t_ms: int, px_u: int, qty_u: int, side: int, quote_u: int | None = None) -> None:
        self.of(venue).add(t_ms, px_u, qty_u, side, quote_u)

    def window(self, t0_ms: int, t1_ms: int, venues=None) -> dict:
        """Par bourse et au total : achats, ventes et delta en dollars (unités de 10^-16) sur [t0, t1[."""
        per, buyq, sellq = {}, 0, 0
        for name, v in self.venues.items():
            if venues is not None and name not in venues:
                continue
            w = v.window(t0_ms, t1_ms)
            per[name] = w
            buyq += w["buyq"]
            sellq += w["sellq"]
        return {"venues": per, "buyq": buyq, "sellq": sellq, "deltaq": buyq - sellq}


# ---------- contrôle contre les bougies officielles ----------
def classify_diffs(diffs: list) -> list:
    """Classe l'écart de chaque minute entre le compte fait des transactions agrégées et la bougie officielle.

    Chez Binance, une transaction agrégée (aggTrade) des perpétuels réunit les exécutions d'un même ordre au même prix sous UNE seule
    heure : quand elles tombent de part et d'autre d'un changement de minute, elles sont toutes rangées dans la même minute, alors que
    la bougie officielle range chacune dans la sienne. Une minute a donc un peu trop de volume et une minute proche exactement autant
    en moins : le total est juste. (Constaté sur des journées entières d'archives publiques : tools/check_cvd_archive.py ; sur le
    comptant, les minutes sont toutes identiques.)

    `diffs` : dans l'ordre du temps, (écart de volume, écart de volume acheteur) en unités entières, ou None pour une minute non comptée
    (coupure). Résultat, une étiquette par minute :
      'ok'     identique à la bougie officielle ;
      'shift'  suite de minutes voisines dont les écarts s'annulent exactement : décalage au passage de la minute ;
      'bad'    suite d'écarts qui ne s'annule pas sur place, entourée de minutes identiques (elle s'annule plus loin, ou des
               transactions manquent : c'est le résidu cumulé qui tranche) ;
      'open'   suite qui touche le début, la fin ou une coupure ;
      'gap'    minute non comptée."""
    n = len(diffs)
    out = [None] * n
    i = 0
    while i < n:
        d = diffs[i]
        if d is None:
            out[i] = "gap"
            i += 1
        elif d == (0, 0):
            out[i] = "ok"
            i += 1
        else:
            j = i
            sv = sb = 0
            while j < n and diffs[j] is not None and diffs[j] != (0, 0):
                sv += diffs[j][0]
                sb += diffs[j][1]
                j += 1
            closed = i > 0 and diffs[i - 1] == (0, 0) and j < n and diffs[j] == (0, 0)
            label = "shift" if (sv, sb) == (0, 0) else ("bad" if closed else "open")
            for k in range(i, j):
                out[k] = label
            i = j
    return out


def bar_diff(bar, row):
    """(écart de volume, écart de volume acheteur) entre une barre faite des transactions et la barre officielle `row` (format de seed)."""
    return (bar[BUY] + bar[SELL] - int(row[5]) - int(row[6]), bar[BUY] - int(row[5]))


def usd(q_units: int) -> float:
    """Dollars lisibles (pour l'affichage seulement) à partir d'unités de 10^-16."""
    return q_units / QUNIT


def coins(u: int) -> float:
    """Pièces lisibles (affichage seulement) à partir d'unités de 10^-8."""
    return u / UNIT


__all__ = ["TickCvd", "VenueFlow", "resample", "cumulative", "pivots", "divergences", "absorptions", "classify_diffs", "bar_diff", "usd", "coins", "SCALE", "UNIT", "QUNIT",
           "T", "O", "H", "L", "C", "BUY", "SELL", "BUYQ", "SELLQ", "N", "OK"]
