"""Indicateurs JOURNALIERS construits a partir des jeux libres (data/opendata.py), tous calcules avec ce qui est connu a la fin du jour.

Chaque indicateur : une serie alignee sur les jours UTC [start, end]. Une valeur manquante est None. Module PUR.

  En chaine (Coin Metrics, BTC) : flux nets vers les bourses, offre sur les bourses, MVRV, hashrate, adresses actives, transactions, frais, volume au comptant ;
  Liquidite : offre de stablecoins (USDT + USDC + DAI) ;
  Macro / geopolitique : VIX, petrole (Brent), gaz naturel, indice dollar reconstruit ;
  Prix : momentum, distance a la moyenne 200 jours (le filtre de tendance du terminal), baisse depuis le plus haut, volatilite realisee.
« attendu » = le sens suppose AVANT de mesurer (+1 : plus haut = hausse ensuite) ; il sert a dire si la mesure confirme l'intuition."""
import math

DAY = 86_400_000


def days(start: int, end: int) -> list[int]:
    return list(range(start, end + 1, DAY))


def dense(series: list[tuple[int, float]], grid: list[int], max_gap: int = 7) -> list:
    """Serie alignee sur la grille ; une valeur est reportee au plus `max_gap` jours (marches fermes le week-end, jours feries) puis redevient None."""
    d = dict(series)
    out, last, age = [], None, 0
    for t in grid:
        if t in d:
            last, age = d[t], 0
            out.append(last)
        elif last is not None and age < max_gap:
            age += 1
            out.append(last)
        else:
            last = None
            out.append(None)
    return out


def _lag(x, n):
    return [None] * n + x[:-n] if n else list(x)


def pct_change(x: list, n: int) -> list:
    p = _lag(x, n)
    return [(a / b - 1.0) if (a is not None and b is not None and b != 0) else None for a, b in zip(x, p)]


def roll_mean(x: list, n: int, min_obs: int | None = None) -> list:
    min_obs = min_obs or max(2, int(n * 0.8))
    out, s, c, win = [], 0.0, 0, []
    for v in x:
        win.append(v)
        if v is not None:
            s += v
            c += 1
        if len(win) > n:
            o = win.pop(0)
            if o is not None:
                s -= o
                c -= 1
        out.append(s / c if c >= min_obs and len(win) == n else None)
    return out


def roll_sum(x: list, n: int) -> list:
    out, s, win = [], 0.0, []
    bad = 0
    for v in x:
        win.append(v)
        if v is None:
            bad += 1
        else:
            s += v
        if len(win) > n:
            o = win.pop(0)
            if o is None:
                bad -= 1
            else:
                s -= o
        out.append(s if len(win) == n and bad == 0 else None)
    return out


def ratio(a: list, b: list, minus_one: bool = True) -> list:
    return [((u / v) - (1.0 if minus_one else 0.0)) if (u is not None and v not in (None, 0)) else None for u, v in zip(a, b)]


def combine(f, *xs) -> list:
    return [f(*v) if all(q is not None for q in v) else None for v in zip(*xs)]


def cummax(x: list) -> list:
    out, m = [], None
    for v in x:
        if v is not None:
            m = v if m is None else max(m, v)
        out.append(m)
    return out


def realized_vol(price: list, n: int = 30) -> list:
    r = [None] + [math.log(b / a) if (a and b and a > 0 and b > 0) else None for a, b in zip(price, price[1:])]
    out = []
    for i in range(len(r)):
        w = r[max(0, i - n + 1):i + 1]
        w = [v for v in w if v is not None]
        if len(w) >= int(n * 0.8) and i >= n - 1:
            m = sum(w) / len(w)
            out.append(math.sqrt(sum((v - m) ** 2 for v in w) / (len(w) - 1)) * math.sqrt(365))
        else:
            out.append(None)
    return out


# nom -> (groupe, titre, sens attendu, explication de l'hypothese, unite d'affichage)
CATALOG = {
    "ret_90d": ("Prix", "Momentum 90 jours", +1, "Ce qui a monte continue de monter (momentum de moyen terme).", "%"),
    "ret_30d": ("Prix", "Momentum 30 jours", +1, "Même idée à un mois.", "%"),
    "dist_ma200": ("Prix", "Écart à la moyenne 200 jours", +1, "Au-dessus de la moyenne 200 jours : tendance haussière (c'est le filtre de tendance du terminal).", "%"),
    "dd_ath": ("Prix", "Baisse depuis le plus haut historique", +1, "Plus on est loin du plus haut, plus le rebond est probable (ou plus la tendance est mauvaise : à mesurer).", "%"),
    "rv_30d": ("Prix", "Volatilité réalisée 30 jours", 0, "Les périodes très agitées précèdent des rendements différents (à mesurer).", "%"),
    "netflow_7d": ("En chaîne", "Flux nets vers les bourses (7 jours)", -1, "Des coins qui entrent sur les bourses se vendent : plus d'entrées que de sorties = baissier.", "% de la capitalisation"),
    "exch_supply_30d": ("En chaîne", "Offre sur les bourses (variation 30 jours)", -1, "Les coins quittent les bourses = accumulation = haussier.", "%"),
    "exch_share": ("En chaîne", "Part de l'offre détenue sur les bourses", -1, "Plus la part sur les bourses est haute, plus il y a de vente potentielle.", "%"),
    "mvrv": ("En chaîne", "MVRV (valeur de marché / valeur réalisée)", -1, "MVRV élevé : les détenteurs gagnent beaucoup, risque de vente (surévaluation).", ""),
    "hashrate_30v90": ("En chaîne", "Puissance de minage (30 j contre 90 j)", +1, "Le hashrate qui chute = mineurs en difficulté (capitulation, souvent proche d'un creux).", "%"),
    "adr_30v365": ("En chaîne", "Adresses actives (30 j contre 1 an)", +1, "Activité en hausse = demande réelle.", "%"),
    "tx_30v365": ("En chaîne", "Transactions (30 j contre 1 an)", +1, "Usage du réseau en hausse.", "%"),
    "fee_30v90": ("En chaîne", "Frais en dollars (30 j contre 90 j)", +1, "Frais en hausse = demande de blocs, euphorie ou congestion.", "%"),
    "vol_7v90": ("En chaîne", "Volume au comptant (7 j contre 90 j)", 0, "Volume en hausse : intérêt, mais aussi paniques (à mesurer).", "%"),
    "netflow_30d": ("En chaîne", "Flux nets vers les bourses (30 jours)", -1, "Même idée que sur 7 jours, plus lente.", "% de la capitalisation"),
    "puell": ("En chaîne", "Multiple de Puell (revenu des mineurs / moyenne 1 an)", -1, "Les mineurs très bien payés vendent leurs coins : haut = risque de sommet ; bas = capitulation.", ""),
    "stable_30d": ("Liquidité", "Offre de stablecoins (variation 30 jours)", +1, "Plus de dollars numériques : de la poudre sèche arrive sur le marché.", "%"),
    "usdt_30d": ("Liquidité", "Offre de Tether USDT (variation 30 jours)", +1, "Les émissions de Tether précèdent souvent les achats.", "%"),
    "ssr": ("Liquidité", "Ratio capitalisation BTC / stablecoins (SSR)", -1, "SSR bas : beaucoup de pouvoir d'achat en stablecoins face à la capitalisation du bitcoin.", ""),
    "stable_90d": ("Liquidité", "Offre de stablecoins (variation 90 jours)", +1, "Même idée à trois mois.", "%"),
    "vix": ("Macro", "VIX (peur sur les actions)", +1, "Le VIX très haut marque des paniques : rebond ensuite (contrarien) ?", ""),
    "vix_5d": ("Macro", "VIX (variation 5 jours)", -1, "Un pic soudain de peur pèse sur les actifs risqués.", "%"),
    "brent_30d": ("Macro", "Pétrole Brent (variation 30 jours)", -1, "Choc pétrolier (tension géopolitique) : inflation, banques centrales, aversion au risque.", "%"),
    "natgas_30d": ("Macro", "Gaz naturel (variation 30 jours)", -1, "Choc énergétique.", "%"),
    "dxy_30d": ("Macro", "Dollar (indice reconstruit, variation 30 jours)", -1, "Dollar qui monte : liquidité mondiale qui se resserre, mauvais pour le bitcoin.", "%"),
}


def build(od, start: int, end: int) -> tuple[list[int], dict[str, list], list]:
    """(grille de jours, {indicateur: serie alignee}, prix BTC aligne) depuis un OpenData."""
    grid = days(start, end)
    cm = lambda col: dense(od.cm("btc", col), grid, max_gap=3)
    price = cm("PriceUSD")
    mcap, fin, fout = cm("CapMrktCurUSD"), cm("FlowInExUSD"), cm("FlowOutExUSD")
    sply, splyx = cm("SplyCur"), cm("SplyExNtv")
    net = combine(lambda a, b: a - b, fin, fout)
    fees_usd = combine(lambda f, p: f * p, cm("FeeTotNtv"), price)
    st = dense(od.stablecoin_supply(), grid, max_gap=3)
    usdt = dense(od.cm("usdt", "SplyCur"), grid, max_gap=3)
    iss_usd = cm("IssTotUSD")
    vix, brent, gas, dxy = (dense(od.macro(n), grid, max_gap=5) for n in ("vix", "brent", "natgas", "fx"))
    ma200 = roll_mean(price, 200)
    ind = {
        "ret_90d": pct_change(price, 90), "ret_30d": pct_change(price, 30),
        "dist_ma200": ratio(price, ma200),
        "dd_ath": ratio(price, cummax(price)),
        "rv_30d": realized_vol(price, 30),
        "netflow_7d": combine(lambda n, m: n / m, roll_sum(net, 7), mcap),
        "exch_supply_30d": pct_change(splyx, 30),
        "exch_share": combine(lambda a, b: a / b, splyx, sply),
        "mvrv": cm("CapMVRVCur"),
        "hashrate_30v90": ratio(roll_mean(cm("HashRate"), 30), roll_mean(cm("HashRate"), 90)),
        "adr_30v365": ratio(roll_mean(cm("AdrActCnt"), 30), roll_mean(cm("AdrActCnt"), 365)),
        "tx_30v365": ratio(roll_mean(cm("TxCnt"), 30), roll_mean(cm("TxCnt"), 365)),
        "fee_30v90": ratio(roll_mean(fees_usd, 30), roll_mean(fees_usd, 90)),
        "vol_7v90": ratio(roll_mean(cm("volume_reported_spot_usd_1d"), 7), roll_mean(cm("volume_reported_spot_usd_1d"), 90)),
        "stable_30d": pct_change(st, 30), "stable_90d": pct_change(st, 90), "usdt_30d": pct_change(usdt, 30),
        "ssr": combine(lambda m, q: m / q, mcap, st),
        "netflow_30d": combine(lambda n, m: n / m, roll_sum(net, 30), mcap),
        "puell": ratio(iss_usd, roll_mean(iss_usd, 365)),
        "vix": vix, "vix_5d": pct_change(vix, 5),
        "brent_30d": pct_change(brent, 30), "natgas_30d": pct_change(gas, 30),
        "dxy_30d": pct_change(dxy, 30),
    }
    return grid, ind, price
