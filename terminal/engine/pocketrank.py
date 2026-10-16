"""Importance d'une poche de liquidite (V14) : sa TAILLE, les CONFLUENCES autour d'elle et sa FRAICHEUR (depuis quand elle existe).

Score sur 100 = trois parts :
  - taille (50 points au plus) : montant estime face a la plus grosse poche de la fenetre de reference (1 h, la meme quelle que soit
    l'unite de temps affichee), ou force du plus haut / plus bas pour les poches visibles dans le prix (mois > semaine > jour > creux 1 h) ;
  - confluences (30 points au plus) : niveaux d'AUTRES sources a moins de 0,3 amplitude moyenne d'une bougie d'une heure, ponderes par la
    periode (annee > mois > semaine > jour) ; une poche estimee posee sur des ordres d'arret visibles (et l'inverse) compte fort ;
  - fraicheur (20 points au plus) : une poche de moins de 24 h garde tout, puis la part baisse ; plus rien apres 60 jours.
Pourquoi ces poids : etude engine/pocketstudy.py sur BTC 2014-2026 (rapport « poches », 26 552 premiers contacts, apprentissage puis test).
  - au premier contact, une poche visible se retourne 2,8 points plus souvent que la position du prix ne le prevoit (temoin au hasard : +0,6),
    surtout quand elle a moins de 24 h (+3,3 a +3,6) ; apres 10 jours, plus d'effet mesurable : d'ou la fraicheur, pas l'anciennete ;
  - les confluences n'ajoutent rien de net au retournement (+2,9 faibles, +2,7 moyennes, +3,4 fortes) : poids modere ;
  - plus une poche a de confluences, MOINS le prix va jusqu'a elle (-5,5 points d'atteinte en 24 h pour les fortes) : les niveaux autour
    l'arretent avant. Aucune poche n'« attire » le prix plus que sa distance ne le prevoit.
Les poches estimees par l'interet ouvert (29 jours chez Binance) ne sont pas testables : on leur applique les memes regles.
Module PUR (aucun reseau, aucune horloge) : utilise en direct (service.py) et par l'etude.
"""
import math

PERIOD_W = {"y": 10.0, "m": 9.0, "w": 7.0, "d": 4.0}
PERIOD_TXT = {"y": "année", "m": "mois", "w": "semaine", "d": "jour"}
CROSS_W = 10.0                # poche estimee sur des ordres d'arret visibles dans le prix (ou l'inverse)
SIZE_MAX, CONF_MAX, AGE_MAX = 50.0, 30.0, 20.0
CONF_ATR, CONF_MIN_PCT = 0.30, 0.15
# fraicheur (heures -> points) : interpolation lineaire ; au-dela du dernier point, valeur du dernier (mesure : voir plus haut)
MATURITY = ((0.0, 20.0), (24.0, 20.0), (72.0, 13.0), (240.0, 11.0), (720.0, 6.0), (1440.0, 0.0))
UNKNOWN_AGE_PTS = 2.0          # plus ancienne que l'historique disponible
AGE_TXT = ((6.0, "toute fraîche"), (24.0, "fraîche"), (72.0, "de 1 à 3 jours"), (240.0, "de 3 à 10 jours"), (math.inf, "ancienne"))


def group_weight(group: str):
    """(poids, libelle) d'un groupe de niveaux du terminal ; None si le groupe ne compte pas (profils de l'unite de temps affichee, temoin)."""
    g = group or ""
    if g.startswith("xVP") or g == "RAND":
        return None
    if g == "ROUND":
        return 3.0, "nombre rond"
    if g == "nPOC":
        return 6.0, "POC nu"
    if g.startswith("aVWAP"):
        return 7.0, "VWAP ancré"
    if g == "LIQ":
        return CROSS_W, "poche de liquidations estimée"
    if g == "STOPS":
        return CROSS_W, "ordres d'arrêt visibles (plus haut / plus bas)"
    if len(g) == 4 and g[0] == "P" and g.endswith("HL") and g[1].lower() in PERIOD_W:
        p = g[1].lower()
        return PERIOD_W[p], f"plus haut / bas {PERIOD_TXT[p]} précédent"
    if len(g) > 1 and g[0] == "p" and g[1] in PERIOD_W:
        return PERIOD_W[g[1]], f"profil de volume {PERIOD_TXT[g[1]]} précédent"
    if g[0] in PERIOD_W:
        what = "VWAP" if "VWAP" in g else "ouverture" if "Open" in g else "profil de volume" if "VP" in g else "niveau"
        return PERIOD_W[g[0]], f"{what} {PERIOD_TXT[g[0]]}"
    return 3.0, "autre niveau"


def tolerance(price: float, atr_h1: float) -> float:
    return max(CONF_ATR * (atr_h1 or 0.0), CONF_MIN_PCT / 100.0 * price)


def confluences(lo: float, hi: float, levels, tol: float, skip_groups=()):
    """Niveaux d'autres sources a moins de `tol` de la poche [lo, hi]. `levels` : iterable de (nom, groupe, prix).
    Un seul niveau par groupe (le plus proche) : trois lignes du meme VWAP ne font pas trois confluences. Trie par poids decroissant."""
    best = {}
    for name, group, price in levels:
        if price is None or group in skip_groups:
            continue
        gw = group_weight(group)
        if gw is None:
            continue
        d = 0.0 if lo <= price <= hi else min(abs(price - lo), abs(price - hi))
        if d > tol:
            continue
        if group not in best or d < best[group]["d"]:
            best[group] = {"name": name, "group": group, "price": price, "w": gw[0], "what": gw[1], "d": d}
    return sorted(best.values(), key=lambda c: (-c["w"], c["d"]))


def size_points(rel: float) -> float:
    return SIZE_MAX * math.sqrt(max(0.0, min(1.0, rel or 0.0)))


def conf_points(confs) -> float:
    return min(CONF_MAX, sum(c["w"] for c in confs))


def maturity_points(age_h) -> float:
    if age_h is None:
        return UNKNOWN_AGE_PTS
    a = max(0.0, age_h)
    for (x0, y0), (x1, y1) in zip(MATURITY, MATURITY[1:]):
        if a <= x1:
            return y0 + (y1 - y0) * (a - x0) / (x1 - x0)
    return MATURITY[-1][1]


def maturity_label(age_h) -> str:
    if age_h is None:
        return "ancienne"
    for lim, txt in AGE_TXT:
        if age_h < lim:
            return txt
    return "ancienne"


def importance(rel: float, confs, age_h) -> dict:
    """Score d'importance sur 100 et sa decomposition."""
    s, c, a = size_points(rel), conf_points(confs), maturity_points(age_h)
    tot = s + c + a
    return {"score": int(round(tot)), "parts": {"size": round(s, 1), "conf": round(c, 1), "age": round(a, 1)},
            "grade": "forte" if tot >= 60 else "moyenne" if tot >= 40 else "faible", "maturity": maturity_label(age_h)}


def rank(pools, key="imp"):
    """Rang par cote (1 = la plus importante au-dessus / en dessous). Ecrit p['rank'] ; renvoie la liste."""
    for side in ("long", "short"):
        mine = sorted([p for p in pools if p.get("side") == side], key=lambda p: -(p.get(key) or {}).get("score", 0))
        for k, p in enumerate(mine):
            p["rank"] = k + 1
    return pools
