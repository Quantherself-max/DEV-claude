"""Delta, CVD, volume et squeezes (V10) : indicateurs de flux et de levier, lecture en direct et variables de l'etude.

Vocabulaire (en clair) :
  - delta = volume acheteur agressif - volume vendeur agressif ; CVD = delta cumule ; desequilibre = delta / volume sur une fenetre (de -1 a +1) ;
  - OI (Open Interest, interet ouvert) = nombre de contrats ouverts : il monte quand de NOUVELLES positions s'ouvrent, il baisse quand elles se ferment ou se font liquider ;
  - « shorts qui s'accumulent » (Velo, ATAS) : le prix derive lentement ou tient, l'OI monte et le CVD baisse. Les vendeurs agressifs ouvrent des positions courtes sans que le prix
    baisse : si le prix remonte, ils doivent racheter de force = SQUEEZE HAUSSIER possible ; l'image miroir (OI en hausse, CVD en hausse, prix qui ne monte pas) prepare un SQUEEZE BAISSIER
    (liquidation de longs) ;
  - squeeze en cours : le prix s'envole (ou s'effondre) pendant que l'OI CHUTE : ce sont des positions fermees de force.
Divergences mesurees : prix contre flux (le prix fait mieux ou moins bien que ce que le CVD explique), delta recent contre CVD de fond, volume contre mouvement (« effort sans resultat »).

Toutes les series sont HORAIRES et calculees sans regarder le futur (fenetres passees seulement) ; les ecarts sont exprimes en « z » (nombre d'ecarts-types par rapport aux 30 derniers jours),
donc comparables d'un marche et d'une epoque a l'autre. Module PUR (stdlib)."""
import math

HOUR = 3_600_000
ZWIN = 720            # 30 jours de references pour normaliser
ZMIN = 200
WINDOWS = (24, 72)


# ---------------------------------------------------------------- outils de series
def roll_sum(x: list, n: int) -> list:
    """Somme des n dernieres valeurs ; None tant que la fenetre est incomplete ou contient un trou."""
    out, s, bad = [None] * len(x), 0.0, 0
    for i, v in enumerate(x):
        if v is None:
            bad += 1
        else:
            s += v
        if i >= n:
            u = x[i - n]
            if u is None:
                bad -= 1
            else:
                s -= u
        if i >= n - 1 and bad == 0:
            out[i] = s
    return out


def rz(x: list, n: int = ZWIN, minobs: int = ZMIN) -> list:
    """Z-score glissant : (x - moyenne des n dernieres valeurs) / ecart-type, valeur courante comprise ; None s'il y a moins de minobs valeurs."""
    out, s, q, k = [None] * len(x), 0.0, 0.0, 0
    for i, v in enumerate(x):
        if v is not None:
            s += v
            q += v * v
            k += 1
        if i >= n:
            u = x[i - n]
            if u is not None:
                s -= u
                q -= u * u
                k -= 1
        if v is not None and k >= minobs:
            m = s / k
            var = q / k - m * m
            out[i] = (v - m) / math.sqrt(var) if var > 1e-18 else 0.0
    return out


def log_ret(c: list, w: int) -> list:
    return [math.log(c[i] / c[i - w]) if i >= w and c[i] and c[i - w] and c[i] > 0 and c[i - w] > 0 else None for i in range(len(c))]


def imbalance(d: list, v: list, w: int) -> list:
    sd, sv = roll_sum(d, w), roll_sum(v, w)
    return [(a / b) if (a is not None and b and b > 0) else None for a, b in zip(sd, sv)]


def vol_anomaly(v: list, w: int, base: int = 720) -> list:
    """log( volume moyen des w dernieres heures / volume moyen des `base` dernieres heures ) : 0 = volume normal, +0,7 = deux fois plus."""
    sw, sb = roll_sum(v, w), roll_sum(v, base)
    return [math.log((a / w) / (b / base)) if (a and b and a > 0 and b > 0) else None for a, b in zip(sw, sb)]


def oi_change(oi: list, w: int) -> list:
    return [math.log(oi[i] / oi[i - w]) if (i >= w and oi[i] and oi[i - w] and oi[i] > 0 and oi[i - w] > 0) else None for i in range(len(oi))]


def ffill(x: list, max_gap: int = 6) -> list:
    """Comble les trous de moins de max_gap pas avec la derniere valeur connue."""
    out, last, age = [], None, 0
    for v in x:
        if v is not None:
            last, age = v, 0
            out.append(v)
        else:
            age += 1
            out.append(last if (last is not None and age <= max_gap) else None)
    return out


def _map(fn, *series):
    """Combinaison terme a terme de plusieurs series (None des qu'une valeur manque)."""
    return [None if any(v is None for v in vs) else fn(*vs) for vs in zip(*series)]


def _gate(z):
    """Vaut 1 quand le prix n'a presque pas bouge, 0 quand il a bouge de 2 ecarts-types ou plus (la configuration « le prix ne reagit pas »)."""
    return max(0.0, 1.0 - abs(z) / 2.0)


# ---------------------------------------------------------------- catalogue des variables
# nom -> (groupe, titre, sens attendu pour le RENDEMENT (+1 haussier, -1 baissier, 0 libre), hypothese, unite, besoin d'OI)
CATALOG = {
    "ret24": ("Référence", "Rendement des 24 dernières heures (le prix seul)", 0, "Élan ou retour à la moyenne du prix, sans aucune donnée de flux : la référence que les autres variables doivent battre.", "%", False),
    "ret72": ("Référence", "Rendement des 72 dernières heures (le prix seul)", 0, "Même référence sur trois jours.", "%", False),
    "imb24": ("Flux (delta, CVD)", "Déséquilibre acheteurs / vendeurs agressifs, 24 h", +1, "Plus d'acheteurs agressifs que de vendeurs : la pression continue ?", "%", False),
    "imb72": ("Flux (delta, CVD)", "Déséquilibre acheteurs / vendeurs agressifs, 72 h", +1, "Même idée sur trois jours (CVD de fond).", "%", False),
    "divp24": ("Divergences", "Prix contre flux (24 h)", +1, "Le prix tient ou monte alors que le flux vend : des acheteurs passifs absorbent (ou les vendeurs agressifs sont piégés).", "z", False),
    "divp72": ("Divergences", "Prix contre flux (72 h)", +1, "Même idée sur trois jours : dérive lente du prix contre un CVD qui baisse.", "z", False),
    "divd": ("Divergences", "Delta récent contre CVD de fond (6 h contre 72 h)", +1, "Le flux des dernières heures se retourne par rapport au flux des trois derniers jours.", "z", False),
    "volmom24": ("Divergences", "Mouvement confirmé par le volume (24 h)", +1, "Un mouvement accompagné d'un volume anormal continue plus souvent.", "z", False),
    "effort24": ("Divergences", "Volume sans mouvement (effort sans résultat, 24 h)", 0, "Beaucoup de volume pour peu de mouvement : absorption, souvent avant un mouvement brusque (sens libre).", "z", False),
    "oi24": ("Levier (intérêt ouvert)", "Variation de l'intérêt ouvert (24 h)", 0, "L'OI monte : du levier s'accumule, le prochain mouvement est plus violent (sens libre).", "%", True),
    "oi72": ("Levier (intérêt ouvert)", "Variation de l'intérêt ouvert (72 h)", 0, "Même idée sur trois jours.", "%", True),
    "sfuel24": ("Squeeze", "Carburant de short squeeze (24 h)", +1, "OI en hausse, flux vendeur, prix qui ne baisse pas : des shorts s'accumulent, un rebond les forcerait à racheter.", "z", True),
    "sfuel72": ("Squeeze", "Carburant de short squeeze (72 h)", +1, "Même configuration sur trois jours (dérive lente, « slow bleed »).", "z", True),
    "lfuel24": ("Squeeze", "Carburant de long squeeze (24 h)", -1, "OI en hausse, flux acheteur, prix qui ne monte pas : des longs s'accumulent, un recul les liquiderait.", "z", True),
    "lfuel72": ("Squeeze", "Carburant de long squeeze (72 h)", -1, "Même configuration sur trois jours.", "z", True),
    "squp6": ("Squeeze", "Squeeze haussier en cours (6 h)", -1, "Le prix s'envole pendant que l'OI chute : des shorts sont rachetés de force ; la hausse s'essouffle-t-elle ensuite ?", "z", True),
    "sqdn6": ("Squeeze", "Purge de longs en cours (6 h)", +1, "Le prix s'effondre pendant que l'OI chute : des longs sont liquidés ; rebond ensuite ?", "z", True),
    "fund": ("Levier (intérêt ouvert)", "Financement (coût des longs)", -1, "Financement très positif : foule acheteuse, carburant de liquidation à la baisse.", "%", True),
}
# variables pour la cible « ampleur » : valeurs absolues (le sens ne compte pas, seul compte « le prochain mouvement sera-t-il plus grand que d'habitude ? »)
AMP_CATALOG = {
    "a_ret24": ("Référence", "Mouvement des 24 dernières heures, en valeur absolue (le prix seul)", 0, "La volatilité d'hier annonce celle de demain (regroupement de volatilité) : la référence que le volume et le levier doivent battre.", "%", False),
    "a_imb24": ("Flux (delta, CVD)", "Déséquilibre du flux, en valeur absolue (24 h)", 0, "Un flux très unilatéral précède-t-il un mouvement plus grand ?", "%", False),
    "a_divp24": ("Divergences", "Écart prix / flux, en valeur absolue (24 h)", 0, "Quand le prix et le flux se contredisent, le mouvement suivant est-il plus grand ?", "z", False),
    "vol24": ("Divergences", "Volume anormal (24 h)", 0, "Un volume anormal annonce-t-il plus de mouvement ?", "z", False),
    "effort24": CATALOG["effort24"],
    "oi24": CATALOG["oi24"],
    "oi72": CATALOG["oi72"],
    "fuel24": ("Squeeze", "Carburant de squeeze, l'un ou l'autre sens (24 h)", 0, "Le plus fort des deux carburants (shorts ou longs qui s'accumulent) : mouvement plus grand ensuite ?", "z", True),
    "fuel72": ("Squeeze", "Carburant de squeeze, l'un ou l'autre sens (72 h)", 0, "Même mesure sur trois jours.", "z", True),
    "sq6": ("Squeeze", "Squeeze en cours, l'un ou l'autre sens (6 h)", 0, "Prix qui s'emballe pendant que l'OI chute : le mouvement continue-t-il plus fort que d'habitude ?", "z", True),
    "a_fund": ("Levier (intérêt ouvert)", "Financement, en valeur absolue", 0, "Un financement extrême (dans un sens ou l'autre) annonce-t-il plus de mouvement ?", "%", True),
}


def features(c: list, v: list, d: list, oi: list | None = None, fund: list | None = None, zwin: int = ZWIN, zmin: int = ZMIN) -> dict:
    """Variables du catalogue, heure par heure. c = cloture, v = volume, d = delta (acheteurs - vendeurs agressifs), oi = interet ouvert (en contrats), fund = financement par periode."""
    out = {}
    z = lambda x: rz(x, zwin, zmin)
    ret = {w: log_ret(c, w) for w in (6,) + WINDOWS}
    imb = {w: imbalance(d, v, w) for w in (6,) + WINDOWS}
    zr = {w: z(ret[w]) for w in ret}
    zi = {w: z(imb[w]) for w in imb}
    zv = {w: z(vol_anomaly(v, w)) for w in (24,)}
    for w in WINDOWS:
        out[f"ret{w}"] = ret[w]
        out[f"imb{w}"] = imb[w]
        out[f"divp{w}"] = _map(lambda a, b: a - b, zr[w], zi[w])
    out["divd"] = _map(lambda a, b: a - b, zi[6], zi[72])
    out["volmom24"] = _map(lambda a, b: a * b, zr[24], zv[24])
    out["effort24"] = _map(lambda a, b: a - abs(b), zv[24], zr[24])
    out["vol24"] = zv[24]
    out["a_ret24"] = [None if x is None else abs(x) for x in ret[24]]
    out["a_imb24"] = [None if x is None else abs(x) for x in imb[24]]
    out["a_divp24"] = [None if x is None else abs(x) for x in out["divp24"]]
    if oi is not None:
        oi = ffill(oi)
        oc = {w: oi_change(oi, w) for w in (6,) + WINDOWS}
        zo = {w: z(oc[w]) for w in oc}
        for w in WINDOWS:
            out[f"oi{w}"] = oc[w]
            out[f"sfuel{w}"] = _map(lambda a, b, r: (a - b) / 2.0 * _gate(r), zo[w], zi[w], zr[w])
            out[f"lfuel{w}"] = _map(lambda a, b, r: (a + b) / 2.0 * _gate(r), zo[w], zi[w], zr[w])
        out["squp6"] = _map(lambda r, o: (r - o) / 2.0, zr[6], zo[6])
        out["sqdn6"] = _map(lambda r, o: (-r - o) / 2.0, zr[6], zo[6])
        out["fuel24"] = _map(max, out["sfuel24"], out["lfuel24"])
        out["fuel72"] = _map(max, out["sfuel72"], out["lfuel72"])
        out["sq6"] = _map(max, out["squp6"], out["sqdn6"])
    if fund is not None:
        f = ffill(fund, 24)
        out["fund"] = f
        out["a_fund"] = [None if x is None else abs(x) for x in f]
    return out


# ---------------------------------------------------------------- lecture en direct
def _last(x):
    return x[-1] if x else None


def snapshot(c: list, v: list, d: list, oi: list | None = None, zwin: int = ZWIN, zmin: int = 120) -> dict | None:
    """Etat d'aujourd'hui a partir de series horaires (la derniere valeur est la derniere heure COMPLETE). None si l'historique est trop court."""
    if len(c) < 100 or not v or not d:
        return None
    z = lambda x: rz(x, zwin, zmin)
    zr = {w: _last(z(log_ret(c, w))) for w in (6, 24, 72)}
    zi = {w: _last(z(imbalance(d, v, w))) for w in (6, 24, 72)}
    zv = _last(z(vol_anomaly(v, 24, base=min(720, len(v) - 1))))
    s = {"zr6": zr[6], "zr24": zr[24], "zr72": zr[72], "zi6": zi[6], "zi24": zi[24], "zi72": zi[72], "zv24": zv,
         "ret24": _last(log_ret(c, 24)), "imb24": _last(imbalance(d, v, 24)), "imb72": _last(imbalance(d, v, 72)), "hasOi": False}
    if oi is not None:
        oi2 = ffill(oi)
        if _last(oi2) is not None:
            zo = {w: _last(z(oi_change(oi2, w))) for w in (6, 24, 72)}
            s.update(zo6=zo[6], zo24=zo[24], zo72=zo[72], oi24=_last(oi_change(oi2, 24)), oi72=_last(oi_change(oi2, 72)), hasOi=zo[24] is not None)
    if any(s[k] is None for k in ("zr24", "zi24")):
        return None
    return s


def classify(s: dict) -> dict:
    """Configuration du moment : {code, label, text, tone, bias} en francais. `bias` = +1 / -1 / 0 : sens du mouvement brusque qui ferait mal a la foule."""
    zr6, zr24, zi24, zv = s.get("zr6"), s["zr24"], s["zi24"], s.get("zv24")
    if s.get("hasOi"):
        zo6, zo24 = s.get("zo6"), s["zo24"]
        if zr6 is not None and zo6 is not None and zr6 >= 1.5 and zo6 <= -0.5:
            return {"code": "squeeze_up", "label": "Squeeze haussier en cours", "tone": "warn", "bias": 0,
                    "text": "Le prix grimpe pendant que l'intérêt ouvert chute : des positions courtes sont rachetées de force. Ce genre de hausse s'épuise souvent quand les rachats sont finis."}
        if zr6 is not None and zo6 is not None and zr6 <= -1.5 and zo6 <= -0.5:
            return {"code": "squeeze_down", "label": "Purge de longs en cours", "tone": "warn", "bias": 0,
                    "text": "Le prix chute pendant que l'intérêt ouvert chute : des positions longues sont liquidées. La purge finie, le prix rebondit parfois, mais la baisse peut continuer."}
        if zo24 >= 0.5 and zi24 <= -0.5 and -1.2 <= zr24 <= 0.8:
            return {"code": "short_fuel", "label": "Des shorts s'accumulent", "tone": "warn", "bias": +1,
                    "text": "L'intérêt ouvert monte, les vendeurs agressifs dominent et pourtant le prix ne baisse pas assez : des shorts s'empilent. Un rebond les forcerait à racheter (squeeze haussier possible)."}
        if zo24 >= 0.5 and zi24 >= 0.5 and -0.8 <= zr24 <= 1.2:
            return {"code": "long_fuel", "label": "Des longs s'accumulent", "tone": "warn", "bias": -1,
                    "text": "L'intérêt ouvert monte, les acheteurs agressifs dominent et pourtant le prix ne monte pas assez : des longs s'empilent. Un recul les ferait liquider (squeeze baissier possible)."}
    dv = zr24 - zi24
    if dv >= 2.0:
        return {"code": "div_price_up", "label": "Le prix fait mieux que le flux", "tone": "", "bias": 0,
                "text": "Le prix monte ou tient alors que les ordres agressifs vendent : soit des acheteurs passifs absorbent (soutien), soit la hausse est creuse (fragile). L'intérêt ouvert et les niveaux tranchent."}
    if dv <= -2.0:
        return {"code": "div_price_down", "label": "Le flux achète, le prix ne suit pas", "tone": "", "bias": 0,
                "text": "Les ordres agressifs achètent mais le prix n'avance pas : des vendeurs passifs absorbent (plafond possible)."}
    if zv is not None and zv >= 1.0 and abs(zr24) <= 0.5:
        return {"code": "effort", "label": "Beaucoup de volume pour peu de mouvement", "tone": "", "bias": 0,
                "text": "Effort sans résultat : le volume est anormal mais le prix reste coincé. Une absorption précède souvent un mouvement brusque, sans en donner le sens."}
    return {"code": "none", "label": "Pas de configuration de squeeze", "tone": "", "bias": 0,
            "text": "Prix, flux et levier sont dans leur normale récente." + ("" if s.get("hasOi") else " (Intérêt ouvert indisponible : seules les divergences de flux sont évaluées.)")}


def captions(s: dict) -> dict:
    """Etiquettes des trois mini-graphiques (prix, intérêt ouvert, CVD), comme sur Velo."""
    zr = s["zr24"]
    price = ("Hausse rapide" if zr >= 1.5 else "Hausse lente" if zr >= 0.5 else "Baisse rapide" if zr <= -1.5 else "Baisse lente (« slow bleed »)" if zr <= -0.5 else "Prix stable")
    zo = s.get("zo24")
    oi = None if not s.get("hasOi") or zo is None else ("Levier en hausse" if zo >= 0.5 else "Levier en baisse" if zo <= -0.5 else "Levier stable")
    zi = s["zi24"]
    flow = ("Acheteurs agressifs dominants" if zi >= 0.5 else "Vendeurs agressifs dominants (shorts qui s'ouvrent ?)" if zi <= -0.5 else "Flux équilibré")
    return {"price": price, "oi": oi, "flow": flow}
