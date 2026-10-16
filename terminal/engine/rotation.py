"""Ou est l'argent ? Cartographie du capital et rotation entre bitcoin, ETH, altcoins, stablecoins et or (V10).

Donnees libres (Coin Metrics community, github.com/coinmetrics/data) :
  - capitalisations estimees quotidiennes (CapMrktEstUSD, comparables entre actifs depuis juin 2019) : BTC, ETH, un panier constant de 10 altcoins presents depuis 2019
    (BNB, XRP, ADA, DOGE, TRX, LINK, LTC, BCH, XLM, ATOM) et SOL a part (depuis avril 2020) ;
  - offre de stablecoins (USDT + USDC + DAI) = « poudre seche » ;
  - or : PAXG (1 jeton = 1 once d'or, cote 24 h / 24 : l'or de week-end existe), prix quotidien depuis fevrier 2020.
Le panier n'est pas TOUT le marche (quelques centaines d'actifs en plus) : il sert a mesurer des PARTS et leurs variations, pas des montants absolus.

Ce module construit (1) les series de parts et de rotation, (2) les indicateurs journaliers de rotation, (3) les cibles a predire (rendement du bitcoin,
altcoins contre bitcoin, or contre bitcoin). La mesure elle-meme est dans engine/rotationstudy.py. Module PUR."""
import math

from data.opendata import ALT_BASKET
from . import indicators as ind

DAY = ind.DAY

# nom -> (groupe, titre, sens attendu pour la CIBLE principale, hypothese, unite)
CATALOG = {
    "dom_chg_30d": ("Rotation", "Part du bitcoin dans le panier (variation 30 jours)", +1, "Le capital se concentre sur le bitcoin (refuge crypto) : bon pour le BTC, mauvais pour les alts.", "pts"),
    "alts_btc_30d": ("Rotation", "Altcoins contre bitcoin (30 jours)", -1, "Quand les alts surperforment, la prise de risque est élevée : retour au bitcoin ensuite ?", "%"),
    "eth_btc_30d": ("Rotation", "ETH contre bitcoin (30 jours)", -1, "Même idée avec l'ETH.", "%"),
    "sol_btc_30d": ("Rotation", "SOL contre bitcoin (30 jours)", -1, "Même idée avec SOL (ton actif).", "%"),
    "stable_share_chg_30d": ("Liquidité", "Part des stablecoins (variation 30 jours)", -1, "Le capital se réfugie en dollars numériques (part en hausse) ou revient sur le marché (part en baisse).", "pts"),
    "gold_30d": ("Or", "Or (variation 30 jours)", -1, "L'or monte quand les risques géopolitiques et monétaires montent : prudence sur le bitcoin ?", "%"),
    "gold_btc_30d": ("Or", "Or contre bitcoin (30 jours)", -1, "Le capital préfère l'or au bitcoin (ratio PAXG / BTC en hausse).", "%"),
    "gold_trend": ("Or", "Or : écart à sa moyenne 200 jours", -1, "Or en tendance haussière installée = méfiance.", "%"),
    "gold_corr_90d": ("Or", "Corrélation BTC / or (90 jours)", +1, "Quand le bitcoin se comporte comme l'or (corrélation haute), il suit le refuge.", ""),
}
TARGETS = {
    "BTC": ("Rendement du bitcoin", "Le prix du bitcoin lui-même."),
    "ALTS_vs_BTC": ("Altcoins contre bitcoin", "Surperformance du panier d'altcoins face au bitcoin."),
    "GOLD_vs_BTC": ("Or contre bitcoin", "Surperformance de l'or face au bitcoin."),
}


def _mcap(od, name, grid):
    return ind.dense(od.cm(name, "CapMrktEstUSD"), grid, max_gap=3)


def _sum(parts):
    """Somme jour par jour ; une valeur manquante d'un des actifs rend la somme manquante (le panier doit etre complet)."""
    return [sum(v) if all(x is not None for x in v) else None for v in zip(*parts)]


def corr_roll(a: list, b: list, n: int) -> list:
    """Correlation glissante des rendements journaliers de deux series de prix."""
    ra = [None] + [math.log(y / x) if (x and y and x > 0 and y > 0) else None for x, y in zip(a, a[1:])]
    rb = [None] + [math.log(y / x) if (x and y and x > 0 and y > 0) else None for x, y in zip(b, b[1:])]
    out = []
    for i in range(len(a)):
        w = [(x, y) for x, y in zip(ra[max(0, i - n + 1):i + 1], rb[max(0, i - n + 1):i + 1]) if x is not None and y is not None]
        if i >= n and len(w) >= int(n * 0.8):
            mx, my = sum(x for x, _ in w) / len(w), sum(y for _, y in w) / len(w)
            sxx = sum((x - mx) ** 2 for x, _ in w)
            syy = sum((y - my) ** 2 for _, y in w)
            sxy = sum((x - mx) * (y - my) for x, y in w)
            out.append(sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None)
        else:
            out.append(None)
    return out


def build(od, start: int, end: int):
    """(grille, {indicateur: serie}, {cible: serie positive}, parts) depuis un OpenData ; les series de parts servent aussi a la carte du capital."""
    grid = ind.days(start, end)
    btc_price = ind.dense(od.cm("btc", "PriceUSD"), grid, max_gap=3)
    btc, eth, sol = _mcap(od, "btc", grid), _mcap(od, "eth", grid), _mcap(od, "sol", grid)
    alts = _sum([_mcap(od, a, grid) for a in ALT_BASKET])
    stable = ind.dense(od.stablecoin_supply(), grid, max_gap=3)
    gold = ind.dense(od.cm("paxg", "PriceUSD"), grid, max_gap=3)
    basket = _sum([btc, eth, alts])
    share = lambda x: [(a / b) if (a is not None and b) else None for a, b in zip(x, basket)]
    shares = {"btc": share(btc), "eth": share(eth), "alts": share(alts)}
    liq = [(s / (s + b)) if (s is not None and b is not None and s + b > 0) else None for s, b in zip(stable, basket)]
    ratio = lambda a, b: [(x / y) if (x is not None and y) else None for x, y in zip(a, b)]
    diff = lambda x, n: [(a - b) if (a is not None and b is not None) else None for a, b in zip(x, [None] * n + x[:-n])]
    ma200 = ind.roll_mean(gold, 200)
    series = {
        "dom_chg_30d": diff(shares["btc"], 30),
        "alts_btc_30d": ind.pct_change(ratio(alts, btc), 30),
        "eth_btc_30d": ind.pct_change(ratio(eth, btc), 30),
        "sol_btc_30d": ind.pct_change(ratio(sol, btc), 30),
        "stable_share_chg_30d": diff(liq, 30),
        "gold_30d": ind.pct_change(gold, 30),
        "gold_btc_30d": ind.pct_change(ratio(gold, btc_price), 30),
        "gold_trend": ind.ratio(gold, ma200),
        "gold_corr_90d": corr_roll(gold, btc_price, 90),
    }
    targets = {"BTC": btc_price, "ALTS_vs_BTC": ratio(alts, btc), "GOLD_vs_BTC": ratio(gold, btc_price)}
    maps = {"grid": grid, "shares": shares, "stableShare": liq, "btc": btc, "eth": eth, "alts": alts, "sol": sol, "stable": stable, "gold": gold, "btcPrice": btc_price, "basket": basket}
    return grid, series, targets, maps


def snapshot(od) -> dict | None:
    """Carte du capital aujourd'hui (derniere journee complete) : parts, variations a 7 et 30 jours en points, rotation, or. None si les donnees manquent."""
    last = max((t for t, _ in od.cm("btc", "CapMrktEstUSD")), default=None)
    if last is None:
        return None
    grid, series, targets, m = build(od, last - 400 * DAY, last)
    j = max((i for i, v in enumerate(m["shares"]["btc"]) if v is not None), default=None)
    if j is None or j < 31:
        return None
    pick = lambda arr, k: arr[j - k] if j - k >= 0 else None

    def row(name, label, arr):
        v = arr[j]
        return {"key": name, "label": label, "share": v, "d7": (v - pick(arr, 7)) if pick(arr, 7) is not None else None, "d30": (v - pick(arr, 30)) if pick(arr, 30) is not None else None}
    rows = [row("btc", "Bitcoin", m["shares"]["btc"]), row("eth", "Ether (ETH)", m["shares"]["eth"]), row("alts", "Altcoins (panier de 10)", m["shares"]["alts"]), row("stable", "Stablecoins (part du total)", m["stableShare"])]
    rel = lambda key, n: ((m[key][j] / m["btc"][j]) / (m[key][j - n] / m["btc"][j - n]) - 1.0) if (m[key][j] and m["btc"][j] and m[key][j - n] and m["btc"][j - n]) else None
    gold_btc = lambda n: ((m["gold"][j] / m["btcPrice"][j]) / (m["gold"][j - n] / m["btcPrice"][j - n]) - 1.0) if (m["gold"][j] and m["btcPrice"][j] and m["gold"][j - n] and m["btcPrice"][j - n]) else None
    return {"date": grid[j], "rows": rows, "stableUsd": m["stable"][j], "basketUsd": m["basket"][j],
            "rel": {"eth7": rel("eth", 7), "eth30": rel("eth", 30), "alts7": rel("alts", 7), "alts30": rel("alts", 30), "sol7": rel("sol", 7), "sol30": rel("sol", 30), "gold7": gold_btc(7), "gold30": gold_btc(30)},
            "gold": {"price": m["gold"][j], "d30": series["gold_30d"][j], "trend": series["gold_trend"][j], "corr90": series["gold_corr_90d"][j]}}


def reading(snap: dict) -> dict:
    """Phrase de lecture, mesuree sur 30 jours : ou va le capital ? (descriptif : aucune preuve de pouvoir predictif, voir la page Backtest)."""
    if not snap:
        return {"text": "Données indisponibles.", "tone": ""}
    r, rel = {x["key"]: x for x in snap["rows"]}, snap["rel"]
    btc30, alts30, st30 = r["btc"]["d30"], rel.get("alts30"), r["stable"]["d30"]
    parts = []
    if btc30 is not None:
        parts.append("le capital se concentre sur le bitcoin" if btc30 > 0.01 else "le capital quitte le bitcoin pour d'autres cryptos" if btc30 < -0.01 else "la part du bitcoin est stable")
    if alts30 is not None and abs(alts30) > 0.05:
        parts.append(("les altcoins font mieux que le bitcoin" if alts30 > 0 else "les altcoins font moins bien que le bitcoin") + f" ({alts30 * 100:+.0f} % en 30 j)")
    if st30 is not None and abs(st30) > 0.005:
        parts.append("les stablecoins prennent de la place (prudence)" if st30 > 0 else "les stablecoins reculent (le capital revient sur le marché)")
    g30 = rel.get("gold30")
    if g30 is not None and abs(g30) > 0.05:
        parts.append(("l'or fait mieux que le bitcoin" if g30 > 0 else "le bitcoin fait mieux que l'or") + f" ({g30 * 100:+.0f} % en 30 j)")
    return {"text": (parts[0].capitalize() + (" ; " + " ; ".join(parts[1:]) if len(parts) > 1 else "") + ".") if parts else "Pas de rotation marquée sur 30 jours.", "tone": ""}
