"""Régime de marché : prix + intérêt ouvert + financement + CVD des perpétuels + CVD du comptant (V45).

Sur une fenêtre (15 minutes, 1 heure, 4 heures), quatre mesures réelles sont croisées :
  dp    variation du prix (fraction) ;
  doi   variation de l'intérêt ouvert, en pièces (fraction) : monte = des positions s'ouvrent, baisse = elles se ferment ;
  perp  déséquilibre des ordres agressifs sur les perpétuels : (achats - ventes) / volume, de -1 à +1 ;
  spot  la même mesure sur le marché comptant ;
plus, quand ils existent : le financement (par 8 heures) et les dollars de positions liquidées de chaque côté.

Régimes (le premier vrai dans cet ordre est le régime principal ; tous ceux qui sont vrais sont renvoyés dans `tags`) :
  cascade_longs      prix en baisse ET intérêt ouvert en baisse : des longs ferment de force (liquidations de longs si mesurées)
  short_squeeze      prix en hausse ET intérêt ouvert en baisse : des shorts rachètent (liquidations de shorts si mesurées)
  shorts_agressifs   prix en baisse, intérêt ouvert en hausse, perpétuels vendeurs : des shorts s'OUVRENT au marché
  longs_agressifs    prix en hausse, intérêt ouvert en hausse, perpétuels acheteurs : des longs s'ouvrent au marché
  accumulation_spot  comptant acheteur alors que les perpétuels ne mènent pas, sans baisse du prix : achats au comptant (argent réel)
  distribution_spot  comptant vendeur alors que les perpétuels ne mènent pas, sans hausse du prix
  compression        prix immobile, intérêt ouvert en hausse : des positions se construisent des deux côtés (carburant)
  neutre             rien de net
Les seuils sont des arguments (par défaut : prix 0,20 %, intérêt ouvert 0,30 %, déséquilibre 3 %). `score` (0 à 1) dit de combien les
mesures dépassent les seuils ; ce n'est pas une probabilité.
Module PUR, en décimal."""
from __future__ import annotations
from decimal import Decimal

from .num import CTX, D, ONE, ZERO

LABELS = {
    "cascade_longs": "Cascade de liquidations de longs",
    "short_squeeze": "Short squeeze (rachats forcés de shorts)",
    "shorts_agressifs": "Ouverture de shorts agressifs",
    "longs_agressifs": "Ouverture de longs agressifs",
    "accumulation_spot": "Accumulation au comptant",
    "distribution_spot": "Distribution au comptant",
    "compression": "Compression (positions qui se construisent sans mouvement)",
    "neutre": "Neutre",
}
BIAS = {"cascade_longs": -1, "short_squeeze": 1, "shorts_agressifs": -1, "longs_agressifs": 1, "accumulation_spot": 1,
        "distribution_spot": -1, "compression": 0, "neutre": 0}
ORDER = ("cascade_longs", "short_squeeze", "shorts_agressifs", "longs_agressifs", "accumulation_spot", "distribution_spot", "compression")


def _opt(x):
    return None if x is None else D(x)


def _over(x: Decimal, thr: Decimal) -> Decimal:
    """Dépassement du seuil, plafonné à 1 (0 au seuil, 1 à trois fois le seuil)."""
    if thr <= 0:
        return ZERO
    r = CTX.divide(CTX.subtract(abs(x), thr), CTX.multiply(thr, Decimal(2)))
    return max(ZERO, min(ONE, r))


def pct(x: Decimal, dec: int = 2) -> str:
    v = CTX.multiply(x, Decimal(100))
    return f"{v:+.{dec}f} %".replace(".", ",")


def classify(dp, doi=None, perp=None, spot=None, funding=None, liq_long=None, liq_short=None,
             p_thr="0.002", oi_thr="0.003", imb_thr="0.03", fund_hot="0.0003", fund_cold="-0.0001") -> dict:
    """Voir l'en-tête. Les mesures absentes (None) ne déclenchent rien : un régime qui en a besoin n'est simplement pas évalué, et
    `missing` les nomme."""
    dp, doi, perp, spot, funding = D(dp), _opt(doi), _opt(perp), _opt(spot), _opt(funding)
    pt, ot, it = D(p_thr), D(oi_thr), D(imb_thr)
    up, down, flat = dp >= pt, dp <= -pt, abs(dp) < pt
    oi_up = doi is not None and doi >= ot
    oi_down = doi is not None and doi <= -ot
    oi_flat = doi is not None and abs(doi) < ot
    tags, why = [], {}
    if down and oi_down:
        tags.append("cascade_longs")
        why["cascade_longs"] = [f"prix {pct(dp)}", f"intérêt ouvert {pct(doi)} : des positions se ferment dans la baisse"]
    if up and oi_down:
        tags.append("short_squeeze")
        why["short_squeeze"] = [f"prix {pct(dp)}", f"intérêt ouvert {pct(doi)} : des positions se ferment dans la hausse"]
    if down and oi_up and perp is not None and perp <= -it:
        tags.append("shorts_agressifs")
        why["shorts_agressifs"] = [f"prix {pct(dp)}", f"intérêt ouvert {pct(doi)}", f"perpétuels vendeurs ({pct(perp, 1)} du volume)"]
    if up and oi_up and perp is not None and perp >= it:
        tags.append("longs_agressifs")
        why["longs_agressifs"] = [f"prix {pct(dp)}", f"intérêt ouvert {pct(doi)}", f"perpétuels acheteurs ({pct(perp, 1)} du volume)"]
    if spot is not None and spot >= it and not down and (perp is None or perp < spot) and not oi_up:
        tags.append("accumulation_spot")
        why["accumulation_spot"] = [f"comptant acheteur ({pct(spot, 1)} du volume)",
                                    "les perpétuels ne mènent pas" + (f" ({pct(perp, 1)})" if perp is not None else "")]
    if spot is not None and spot <= -it and not up and (perp is None or perp > spot) and not oi_up:
        tags.append("distribution_spot")
        why["distribution_spot"] = [f"comptant vendeur ({pct(spot, 1)} du volume)",
                                    "les perpétuels ne mènent pas" + (f" ({pct(perp, 1)})" if perp is not None else "")]
    if flat and oi_up:
        tags.append("compression")
        why["compression"] = [f"prix {pct(dp)} (immobile)", f"intérêt ouvert {pct(doi)}"]
    code = next((c for c in ORDER if c in tags), "neutre")
    # force : moyenne des dépassements des mesures utilisées par le régime principal
    parts = []
    if code in ("cascade_longs", "short_squeeze"):
        parts = [_over(dp, pt), _over(doi, ot)]
    elif code in ("shorts_agressifs", "longs_agressifs"):
        parts = [_over(dp, pt), _over(doi, ot), _over(perp, it)]
    elif code in ("accumulation_spot", "distribution_spot"):
        parts = [_over(spot, it)]
    elif code == "compression":
        parts = [_over(doi, ot)]
    score = CTX.divide(sum(parts, ZERO), Decimal(len(parts))) if parts else ZERO
    notes = list(why.get(code, []))
    ll, ls = _opt(liq_long), _opt(liq_short)
    if ll is not None and ls is not None and (ll > 0 or ls > 0):
        tot = CTX.add(ll, ls)
        share = CTX.divide(ll, tot)
        if code == "cascade_longs":
            notes.append(f"liquidations : {share * 100:.0f} % de longs" + (" (confirme)" if share >= Decimal("0.6") else " (ne confirme pas)"))
        elif code == "short_squeeze":
            notes.append(f"liquidations : {(ONE - share) * 100:.0f} % de shorts" + (" (confirme)" if share <= Decimal("0.4") else " (ne confirme pas)"))
    crowd = None
    if funding is not None:
        if funding >= D(fund_hot):
            crowd = "long"
            notes.append(f"financement {pct(funding, 4)} par 8 h : les longs paient cher (foule longue)")
        elif funding <= D(fund_cold):
            crowd = "short"
            notes.append(f"financement {pct(funding, 4)} par 8 h : les shorts paient (foule short)")
    missing = [n for n, v in (("intérêt ouvert", doi), ("CVD des perpétuels", perp), ("CVD du comptant", spot), ("financement", funding)) if v is None]
    return {"code": code, "label": LABELS[code], "bias": BIAS[code], "score": score, "tags": tags, "notes": notes, "crowd": crowd,
            "missing": missing, "why": why,
            "inputs": {"dp": dp, "doi": doi, "perp": perp, "spot": spot, "funding": funding, "liqLong": ll, "liqShort": ls}}


def change(a, b):
    """Variation relative de a vers b (fraction) ; None si a est nul ou absent."""
    if a is None or b is None:
        return None
    a, b = D(a), D(b)
    if a == 0:
        return None
    return CTX.divide(CTX.subtract(b, a), a)


def imbalance(buy, sell):
    """(achats - ventes) / (achats + ventes) ; None si aucun volume. Entiers ou décimaux."""
    b, s = D(buy), D(sell)
    tot = CTX.add(b, s)
    if tot <= 0:
        return None
    return CTX.divide(CTX.subtract(b, s), tot)
