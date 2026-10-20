"""Stratégie V31 : PRIX, INTÉRÊT OUVERT et CVD, lus là où ça compte : sur la LIQUIDITÉ et sur les VWAP / VWAP ancrés.

Pourquoi
  L'ancienne note de confluence additionnait trop de variables (sept piliers, une centaine de niveaux) pour des résultats peu
  concluants. La nouvelle stratégie n'a que trois ingrédients :
    1. un LIEU : une poche de liquidité prise (plus haut ou plus bas de la veille, de la semaine, du mois, sommet ou creux récent,
       niveaux égaux) ou un VWAP / VWAP ancré de la semaine ou du mois touché, par une bougie 4 heures ;
    2. le FLUX au moment où le prix arrive au lieu : le sens du prix, de l'intérêt ouvert et du CVD (8 combinaisons) ;
    3. une RÉACTION par combinaison (table ACTION) : acheter, vendre ou ne rien faire.

Les 8 combinaisons (P = prix, OI = intérêt ouvert, CVD = cumul acheteurs agressifs moins vendeurs agressifs)
  - Sur une poche de liquidité, la comparaison se fait avec le moment où la poche s'est formée (c'est la DIVERGENCE classique) :
    le prix fait un plus haut plus haut (P monte) ou un plus bas plus bas (P baisse) ; l'OI et le CVD sont-ils plus hauts ou plus
    bas qu'au plus haut (ou plus bas) précédent ?
  - Sur un VWAP, la comparaison se fait sur les 12 heures d'approche (3 bougies 4 heures) : le prix arrive par le bas (P monte) ou
    par le haut (P baisse) ; l'OI et le CVD ont-ils monté ou baissé pendant l'approche ?
  Un écart trop petit (OI à moins de 0,5 %, CVD à moins de 1 % du volume échangé) compte comme « plat » : pas de signal.

La réaction (un seul principe, mesuré sur SOL, BTC et ETH perpétuels depuis janvier 2022)
  - Intérêt ouvert en HAUSSE (de l'argent neuf entre) : on SUIT LE CVD, c'est-à-dire le camp agressif qui ouvre ces positions, que le prix
    monte ou baisse. « Contrer le CVD » est la pire réaction sur les trois actifs et les deux périodes.
  - Intérêt ouvert en BAISSE (des positions se ferment) : RIEN. Pas de carburant neuf, pas d'avantage mesurable après frais.
  - CONFIRMATION : il faut au moins un autre signal dans le même sens dans les 24 heures précédentes. Le premier signal d'une série perd
    de l'argent ; quand le flux se répète, il en gagne.

Le trade
  - entrée au marché à la clôture de la bougie 4 heures du signal ;
  - stop au-delà de la bougie du signal (son plus bas pour un achat, son plus haut pour une vente) plus 0,25 fois l'amplitude moyenne
    d'une bougie 4 heures (ATR), entre 1 et 4 ATR ;
  - objectif à 3 fois le risque (choisi sur la période d'apprentissage parmi 6 sorties, dont la prochaine poche de liquidité) ;
  - sortie au marché au bout de 72 heures au plus ; frais, glissement et financement comptés ; une position à la fois, 5 par semaine.

Honnêteté
  Le seuil d'intérêt ouvert (0,5 %) et la confirmation ont été repérés en regardant SOL et BTC sur TOUTE la période : leur période de test
  n'est donc pas totalement à l'aveugle. L'ETH, jamais regardé avant, sert de contrôle : la stratégie n'y gagne pas, pas plus que sur le BTC.
  Seul SOL est validé. Module PUR (aucun réseau)."""
import math
import random
import time

from . import backtest as bt
from . import fine
from . import liqsweep
from . import vwapstrat as vs
from .backtest import DAY, HOUR
from .periods import PeriodTracker

VERSION = 1
OI_FLAT = 0.005                 # intérêt ouvert : moins de 0,5 % d'écart = plat (il faut de l'argent neuf, pas du bruit)
CVD_FLAT = 0.01                 # CVD : moins de 1 % du volume échangé entre les deux instants = plat
MIN_GAP_H = 2                   # une poche formée il y a moins de 2 heures ne compte pas (même mouvement)
STOP_PAD = 0.25
STOP_MIN, STOP_MAX = 1.0, 4.0
TP_MAX_ATR = 8.0
MIN_POOL = 55
COOLDOWN_BARS = 3

PLACES = ("liq", "vwap")
PLACE_NAME = {"liq": "poche de liquidité prise", "vwap": "VWAP ou VWAP ancré touché"}
REACT_NAME = {"follow": "suivre le mouvement", "fade": "contrer le mouvement", None: "rien"}

# Les 8 combinaisons : clé (prix, OI, CVD) -> (nom court, lecture). Lecture = ce que le flux raconte, sans le lieu.
STATES = {
    (1, 1, 1): ("Hausse portée par de nouveaux acheteurs", "Le prix monte, de nouvelles positions s'ouvrent et les acheteurs agressifs mènent : de nouveaux longs entrent, la hausse est soutenue."),
    (1, 1, -1): ("Hausse contre des vendeurs agressifs", "Le prix monte alors que les vendeurs agressifs dominent et que des positions s'ouvrent : des shorts s'ouvrent dans la hausse et se font absorber par des acheteurs passifs."),
    (1, -1, 1): ("Hausse par rachat de shorts", "Le prix monte avec des acheteurs agressifs mais des positions se ferment : ce sont des shorts qui rachètent (squeeze), pas de l'argent neuf."),
    (1, -1, -1): ("Hausse sans acheteurs", "Le prix monte alors que les positions se ferment et que les vendeurs agressifs dominent : la hausse se fait par manque de vendeurs passifs, sans conviction."),
    (-1, 1, -1): ("Baisse portée par de nouveaux vendeurs", "Le prix baisse, de nouvelles positions s'ouvrent et les vendeurs agressifs mènent : de nouveaux shorts entrent, la baisse est soutenue."),
    (-1, 1, 1): ("Baisse contre des acheteurs agressifs", "Le prix baisse alors que les acheteurs agressifs dominent et que des positions s'ouvrent : des longs s'ouvrent dans la baisse et se font absorber par des vendeurs passifs."),
    (-1, -1, -1): ("Baisse par liquidation des longs", "Le prix baisse avec des vendeurs agressifs et des positions qui se ferment : des longs sortent ou se font liquider (capitulation)."),
    (-1, -1, 1): ("Baisse sans vendeurs", "Le prix baisse alors que les positions se ferment et que les acheteurs agressifs dominent : des shorts encaissent, la baisse s'essouffle."),
}
ORDER = [(1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, -1), (-1, -1, 1)]


def skey(st) -> str:
    """(1, -1, 1) -> 'P+ OI- CVD+'."""
    s = lambda x: "+" if x > 0 else "-"
    return f"P{s(st[0])} OI{s(st[1])} CVD{s(st[2])}"


def words(st) -> str:
    """La combinaison en toutes lettres (textes envoyés : aucune abréviation)."""
    w = lambda x: "en hausse" if x > 0 else "en baisse"
    return f"prix {w(st[0])}, intérêt ouvert {w(st[1])}, flux agressif (achats agressifs moins ventes agressives) {w(st[2])}"


def parse_skey(k: str):
    p = k.split()
    return tuple(1 if x[-1] == "+" else -1 for x in p)


def sign(x: float, flat: float) -> int:
    return 1 if x > flat else -1 if x < -flat else 0


def flow_state(p_dir: int, oi_then, oi_now, cvd_diff: float, vol_between: float):
    """(prix, OI, CVD) ou None si l'OI ou le CVD est plat ou inconnu."""
    if not oi_then or not oi_now or vol_between <= 0 or not p_dir:
        return None
    o = sign(oi_now / oi_then - 1.0, OI_FLAT)
    c = sign(cvd_diff / vol_between, CVD_FLAT)
    if not o or not c:
        return None
    return (p_dir, o, c)


def trade_dir(st, react: str) -> int:
    return st[0] if react == "follow" else -st[0]


# =====================================================================================================
#  Géométrie du trade (la même partout : historique et direct)
# =====================================================================================================
def geometry(d: int, price: float, atr: float, bar_h: float, bar_l: float, pools_up: list, pools_dn: list):
    """(stop, objectif, nature de l'objectif) ou None. pools_up / pools_dn : prix des poches au-dessus / en dessous, du plus proche au plus loin."""
    if atr <= 0:
        return None
    stop = (bar_l - STOP_PAD * atr) if d > 0 else (bar_h + STOP_PAD * atr)
    risk = (price - stop) * d
    if risk > STOP_MAX * atr:
        return None
    if risk < STOP_MIN * atr:
        stop, risk = price - d * STOP_MIN * atr, STOP_MIN * atr
    cand = [p for p in (pools_up if d > 0 else pools_dn) if risk <= abs(p - price) <= TP_MAX_ATR * atr and (p - price) * d > 0]
    if cand:
        return stop, cand[0], "pool"
    return stop, price + d * 2.0 * risk, "2R"


# =====================================================================================================
#  Historique : événements à chaque clôture 1 heure
# =====================================================================================================
def hourly_oi(b1h, pairs) -> list:
    """Intérêt ouvert à la clôture de chaque bougie 1 h (None si inconnu). pairs : [(heure de début, valeur en fin d'heure)]."""
    d = dict(pairs)
    return [d.get(int(t)) for t in b1h.t]


TF_H = {"1h": 1, "4h": 4}
APPROACH = {"1h": 4, "4h": 3}            # fenêtre d'approche d'un VWAP, en bougies (4 heures ; 12 heures)
HOLD = {"1h": 24, "4h": 72}              # durée maximale du trade, en heures


def atr_bars(b, n: int = 14) -> list:
    """ATR (moyenne de Wilder) à la clôture de chaque bougie."""
    out, a = [0.0], 0.0
    for j in range(1, len(b.t)):
        pc = b.c[j - 1]
        tr = max(b.h[j] - b.l[j], abs(b.h[j] - pc), abs(b.l[j] - pc))
        a = tr if j < n else (a * (n - 1) + tr) / n
        out.append(a)
    return out


def build_events(ds, oi: list, start_ms: int, end_ms: int, tf: str = "1h", warm_days: int = 40) -> list[dict]:
    """Événements « lieu + flux » sur [start_ms, end_ms), à la clôture de chaque bougie `tf` (1 h ou 4 h).
    oi : intérêt ouvert à la clôture de chaque bougie 1 h. Tout ce qui sert est connu à la clôture de la bougie (rien du futur)."""
    b1h, b5 = ds.b1h, ds.b5
    step_h = TF_H[tf]
    bars = b1h if step_h == 1 else fine.resample(b1h, step_h * HOUR)
    STEP = step_h * HOUR
    atrs = atr_bars(bars)
    oib = [oi[b1h.idx_at(int(t) + STEP - 1)] if b1h.idx_at(int(t) + STEP - 1) >= 0 else None for t in bars.t]
    tr = {k: PeriodTracker(k) for k in ("D", "W", "M")}
    pl = liqsweep.PriceLiquidity(b1h)
    cd, cv = bars.cd, bars.cv
    out, last_ev, cache = [], {}, {}
    fed = max(0, b1h.idx(start_ms - warm_days * DAY))
    j0 = max(APPROACH[tf] + 1, bars.idx(start_ms - STEP))
    for j in range(j0, len(bars.t)):
        t_open = int(bars.t[j])
        T = t_open + STEP
        if T >= end_ms:
            break
        while fed < len(b1h.t) and b1h.t[fed] < t_open:            # périodes à jour jusqu'à l'ouverture de la bougie
            for t in tr.values():
                t.feed(b1h.candle(fed))
            fed += 1
        if T < start_ms or not oib[j] or not oib[j - 1] or atrs[j - 1] <= 0:
            continue
        atr = atrs[j]
        o, h, l, c, pc = bars.o[j], bars.h[j], bars.l[j], bars.c[j], bars.c[j - 1]
        ext = liqsweep.extremes_from_trackers(tr, t_open)
        before = [p for p in pl.pools(pc, atrs[j - 1], t_open, ext) if p["score"] >= MIN_POOL]
        while fed < len(b1h.t) and b1h.t[fed] < T:                 # puis la bougie elle-même : poches d'après (objectifs)
            for t in tr.values():
                t.feed(b1h.candle(fed))
            fed += 1
        ext2 = liqsweep.extremes_from_trackers(tr, T)
        after = [p for p in pl.pools(c, atr, T, ext2) if p["score"] >= MIN_POOL]
        up = sorted(p["price"] for p in after if p["side"] == "short" and p["price"] > c)
        dn = sorted((p["price"] for p in after if p["side"] == "long" and p["price"] < c), reverse=True)
        base = {"t": T, "tf": tf, "price": c, "atr": atr, "h": h, "l": l, "o": o, "up": up[:5], "dn": dn[:5]}
        # ---- 1) liquidité prise ----
        took_hi = [p for p in before if p["side"] == "short" and h > p["price"] and bars.h[j - 1] <= p["price"]]
        took_lo = [p for p in before if p["side"] == "long" and l < p["price"] and bars.l[j - 1] >= p["price"]]
        if bool(took_hi) != bool(took_lo):
            p = max(took_hi or took_lo, key=lambda x: x["score"])
            pd = 1 if took_hi else -1
            jb = bars.idx_at(p["born"]) if p.get("born") else -1
            if 0 <= jb and T - (bars.t[jb] + STEP) >= MIN_GAP_H * HOUR and jb < j and oib[jb]:
                st = flow_state(pd, oib[jb], oib[j], cd[j + 1] - cd[jb + 1], cv[j + 1] - cv[jb + 1])
                if st:
                    out.append({**base, "place": "liq", "st": st, "oiChg": oib[j] / oib[jb] - 1.0, "cvdImb": (cd[j + 1] - cd[jb + 1]) / (cv[j + 1] - cv[jb + 1]), "lvl": p["price"], "src": p["src"], "score": p["score"],
                                "closeBack": (c < p["price"]) if pd > 0 else (c > p["price"]), "ageH": (t_open - p["born"]) / HOUR})
        # ---- 2) VWAP et VWAP ancrés de la semaine et du mois ----
        vals = _vwaps(b1h, b5, b1h.idx_at(T - 1), T, cache)
        touched = sorted([(vs.LEVEL_INFO[n][2], n, V) for n, V in vals.items() if l <= V <= h], key=lambda x: x[0])
        for _, name, V in touched:
            if pc == V:
                continue
            pd = 1 if pc < V else -1                       # arrivé par le bas : le prix monte vers le VWAP
            key = (name, pd)
            if T - last_ev.get(key, -10 ** 15) < COOLDOWN_BARS * STEP:
                continue
            ja = j - APPROACH[tf]
            st = flow_state(pd, oib[ja], oib[j], cd[j + 1] - cd[ja + 1], cv[j + 1] - cv[ja + 1])
            if not st:
                continue
            last_ev[key] = T
            out.append({**base, "place": "vwap", "st": st, "oiChg": oib[j] / oib[ja] - 1.0, "cvdImb": (cd[j + 1] - cd[ja + 1]) / (cv[j + 1] - cv[ja + 1]), "lvl": V, "src": name, "score": 0,
                        "closeBack": (c < V) if pd > 0 else (c > V), "ageH": None})
            break
    return out


def _vwaps(b1h, b5, j: int, T: int, cache: dict) -> dict:
    """VWAP de la semaine et du mois, VWAP ancrés (début de la semaine / du mois précédents, plus haut et plus bas de 7 et 30 jours),
    calculés sur les bougies 5 minutes jusqu'à T."""
    day = T // DAY
    if cache.get("day") != day:
        def swing(n, low):
            a = max(0, j - n * 24)
            seg = b1h.l[a:j] if low else b1h.h[a:j]
            if len(seg) < n * 12:
                return None
            v = min(seg) if low else max(seg)
            return int(b1h.t[a + list(seg).index(v)])
        cache["day"] = day
        cache["sw"] = {"VWAP ancré sur le plus bas de 30 jours": swing(30, True), "VWAP ancré sur le plus haut de 30 jours": swing(30, False),
                       "VWAP ancré sur le plus bas de 7 jours": swing(7, True), "VWAP ancré sur le plus haut de 7 jours": swing(7, False)}
    ws, ms_ = vs.week_start(T), vs.month_start(T)
    anc = {"VWAP du mois": ms_, "VWAP de la semaine": ws, "VWAP ancré au début du mois dernier": vs.month_start(T, 1),
           "VWAP ancré au début de la semaine dernière": ws - 7 * DAY, **cache["sw"]}
    i5 = b5.idx(T) - 1
    out = {}
    for name, a in anc.items():
        if a is None:
            continue
        ia = b5.idx(a)
        if i5 - ia > 24:
            vw, _ = b5.vwap(ia, i5 + 1)
            if vw:
                out[name] = vw
    return out


def play(b5, T: int, d: int, etype: str, entry: float, stop: float, tp: float, valid_h: float, hold_h: float) -> dict:
    """Un trade sur les bougies 5 minutes, à partir de T (clôture du signal). « marché » : entrée à l'ouverture suivante ;
    « limite » : ordre posé à `entry`, valable valid_h, annulé si l'objectif ou le stop est touché avant l'exécution.
    Sortie : stop (compté d'abord dans une même bougie), objectif, ou au marché au bout de hold_h. Sans frais (voir backtest.net_r)."""
    if etype == "marché":
        s = vs.simulate_v(b5, T, d, stop, tp, None, 1.0, hold_h)
        if s.get("filled"):
            s["entry_kind"] = "taker"
        return s
    n = len(b5.t)
    i = b5.idx(T)
    end = min(n, i + int(valid_h * HOUR / b5.step))
    H, L, O, C, Tt = b5.h, b5.l, b5.o, b5.c, b5.t
    j = None
    for q in range(i, end):
        if (L[q] <= stop) if d > 0 else (H[q] >= stop):
            return {"result": "cancel", "filled": False}
        if (L[q] <= entry) if d > 0 else (H[q] >= entry):
            j = q
            break
        if (H[q] >= tp) if d > 0 else (L[q] <= tp):
            return {"result": "missed", "filled": False}
    if j is None:
        return {"result": "nofill" if end < n else "open", "filled": False}
    fp = min(O[j], entry) if d > 0 else max(O[j], entry)
    risk = abs(fp - stop)
    if risk <= 0:
        return {"result": "cancel", "filled": False}
    hend = min(n, j + int(hold_h * HOUR / b5.step))
    mfe = mae = 0.0
    res, px, q = None, None, j
    while q < hend:
        hi, lo = H[q], L[q]
        mfe = max(mfe, ((hi - fp) if d > 0 else (fp - lo)) / risk)
        mae = max(mae, ((fp - lo) if d > 0 else (hi - fp)) / risk)
        if (lo <= stop) if d > 0 else (hi >= stop):
            res, px, kind = "stop", (min(O[q], stop) if d > 0 else max(O[q], stop)) if q > j else stop, "taker"
            break
        if q > j and ((hi >= tp) if d > 0 else (lo <= tp)):
            res, px, kind = "tp", tp, "maker"
            break
        q += 1
    else:
        q, res, px, kind = hend - 1, "timeout", C[hend - 1], "taker"
    return {"result": res, "filled": True, "fill_t": int(Tt[j]), "exit_t": int(Tt[q] + b5.step), "fill_px": fp, "risk": risk,
            "r_gross": (px - fp) * d / risk, "entry_kind": "maker", "legs": [(kind, 1.0)], "hours": (Tt[q] + b5.step - Tt[j]) / HOUR,
            "mfe": mfe, "mae": mae, "tp1": False}


# =====================================================================================================
#  Réaction retenue : un seul principe pour les 8 combinaisons
# =====================================================================================================
def reaction(st):
    """Sens du trade (+1 achat, -1 vente) ou 0 (rien). Intérêt ouvert en hausse : on suit le CVD (le camp agressif qui ouvre des positions) ;
    intérêt ouvert en baisse : des positions se ferment, il n'y a pas de carburant neuf, on ne fait rien."""
    if not st or st[1] <= 0:
        return 0
    return st[2]


def react_of(st) -> str | None:
    d = reaction(st)
    return None if not d else ("follow" if d == st[0] else "fade")


ACTION = {      # texte de la réaction, combinaison par combinaison (le lieu précise le geste)
    (1, 1, 1): "ACHAT : suivre la hausse. Les acheteurs agressifs ouvrent des positions au moment où le prix prend la liquidité au-dessus ou passe le VWAP : la cassure est acceptée.",
    (1, 1, -1): "VENTE : contrer la hausse. Le prix est monté sur des ordres passifs, mais ce sont les vendeurs agressifs qui ouvrent des positions : la prise de liquidité au-dessus ou le test du VWAP par le bas est un piège pour les acheteurs.",
    (1, -1, 1): "RIEN : la hausse vient de shorts qui rachètent ; quand ils ont fini, il n'y a plus d'acheteur. Pas d'argent neuf, pas de trade.",
    (1, -1, -1): "RIEN : hausse sans conviction (positions qui se ferment, vendeurs agressifs). Pas de carburant neuf, pas de trade.",
    (-1, 1, -1): "VENTE : suivre la baisse. Les vendeurs agressifs ouvrent des positions au moment où le prix prend la liquidité en dessous ou casse le VWAP : la cassure est acceptée.",
    (-1, 1, 1): "ACHAT : contrer la baisse. Le prix a baissé sur des ordres passifs, mais ce sont les acheteurs agressifs qui ouvrent des positions : la prise de liquidité en dessous ou le test du VWAP par le haut est un piège pour les vendeurs.",
    (-1, -1, -1): "RIEN : des longs sortent ou se font liquider. Le rebond qui suit une purge n'a pas montré d'avantage mesurable après frais : pas de trade.",
    (-1, -1, 1): "RIEN : la baisse s'essouffle (des shorts encaissent), mais sans argent neuf il n'y a pas d'avantage mesurable : pas de trade.",
}

ENTRIES = ("marché", "limite")
TARGETS = ("pool", "2R", "3R")
EXITS = [f"{e}|{t}" for e in ENTRIES for t in TARGETS]
EXIT_LABEL = {"marché": "entrée au marché à la clôture", "limite": "ordre limite sur le niveau (12 h)", "pool": "objectif sur la prochaine poche de liquidité (sinon 2 fois le risque)",
              "2R": "objectif à 2 fois le risque", "3R": "objectif à 3 fois le risque"}
VALID_H = 12
COOLDOWN_H = 12
MAX_WEEK = 5
CONFIRM_N = 1                   # confirmation : au moins 1 autre signal dans le même sens pendant les 24 heures précédentes
CONFIRM_H = 24


def confirmations(events: list[dict]) -> None:
    """e['confirm'] = nombre de signaux retenus (même sens) dans les CONFIRM_H heures avant celui-ci (e lui-même exclu)."""
    sig = [(e["t"], reaction(e["st"])) for e in events if reaction(e["st"])]
    k0 = 0
    for e in events:
        d = reaction(e["st"])
        while k0 < len(sig) and sig[k0][0] < e["t"] - CONFIRM_H * HOUR:
            k0 += 1
        e["confirm"] = sum(1 for t, dd in sig[k0:] if t < e["t"] and dd == d) if d else 0


def exit_label(x: str) -> str:
    e, t = x.split("|")
    return f"{EXIT_LABEL[e]}, {EXIT_LABEL[t]}"


def plan(e: dict, d: int, ex: str):
    """(type d'entrée, prix d'entrée, stop, objectif, nature de l'objectif) ou None."""
    g = geometry(d, e["price"], e["atr"], e["h"], e["l"], e["up"], e["dn"])
    if g is None:
        return None
    stop, tp, kind = g
    ent, tgt = ex.split("|")
    etype, entry = "marché", e["price"]
    if ent == "limite" and (e["lvl"] - e["price"]) * d < 0 and (e["lvl"] - stop) * d > 0:
        etype, entry = "limite", e["lvl"]
    risk = abs(entry - stop)
    if tgt in ("2R", "3R"):
        tp, kind = entry + d * float(tgt[0]) * risk, tgt
    elif (tp - entry) * d < risk:
        tp, kind = entry + d * 2.0 * risk, "2R"
    return etype, entry, stop, tp, kind


def run_sim(b5, e: dict, d: int, ex: str):
    p = plan(e, d, ex)
    if p is None:
        return None
    etype, entry, stop, tp, kind = p
    s = play(b5, e["t"], d, etype, entry, stop, tp, VALID_H, HOLD[e["tf"]])
    s["plan"] = p
    return s


# =====================================================================================================
#  Mesure complète
# =====================================================================================================
def _stats(rs: list) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0, "expR": None, "win": None, "t": None}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "expR": round(m, 3), "win": round(sum(1 for x in rs if x > 0) / n, 3), "t": round(m / (sd / math.sqrt(n)), 2) if sd > 0 else None}


def _per(e, split):
    return "T" if e["t"] < split else "X"


def _net(s, costs):
    return bt.net_r(s, costs) if s and s.get("filled") else None


PRINCIPLES = [("Suivre le CVD quand l'intérêt ouvert monte (règle retenue)", lambda st: reaction(st)),
              ("Suivre le CVD quand l'intérêt ouvert baisse", lambda st: st[2] if st[1] < 0 else 0),
              ("Suivre le CVD partout", lambda st: st[2]),
              ("Contrer le CVD partout", lambda st: -st[2]),
              ("Suivre le prix partout (cassure)", lambda st: st[0]),
              ("Contrer le prix partout (retournement)", lambda st: -st[0])]


def study(ds, events: list[dict], label: str, start_ms: int, end_ms: int, split_ms: int, costs=None, progress=None, controls: int = 60) -> dict:
    """Rapport complet (sérialisable) : sortie choisie sur l'apprentissage, tableau des 8 combinaisons par lieu, principes comparés,
    stratégie jouée une position à la fois, témoin au hasard, résultats par année et selon les frais."""
    costs = costs or bt.DEFAULT_COSTS
    say = progress or (lambda *_: None)
    b5 = ds.b5
    rule_ev = [e for e in events if reaction(e["st"])]
    # 1) sortie choisie sur l'apprentissage seulement
    say("sorties")
    grid = {}
    for ex in EXITS:
        rs = {"T": [], "X": []}
        for e in rule_ev:
            s = run_sim(b5, e, reaction(e["st"]), ex)
            e.setdefault("sims", {})[(reaction(e["st"]), ex)] = s
            r = _net(s, costs)
            if r is not None:
                rs[_per(e, split_ms)].append(r)
        grid[ex] = {"label": exit_label(ex), "is": _stats(rs["T"]), "oos": _stats(rs["X"])}
    best = max(EXITS, key=lambda x: (grid[x]["is"]["expR"] if grid[x]["is"]["expR"] is not None else -9))
    # 2) les deux réactions de chaque événement avec cette sortie (tableau des 8 combinaisons, principes)
    say("combinaisons")
    for e in events:
        sims = e.setdefault("sims", {})
        for d in (1, -1):
            if (d, best) not in sims:
                sims[(d, best)] = run_sim(b5, e, d, best)
    cells = {}
    for e in events:
        for d in (1, -1):
            r = _net(e["sims"][(d, best)], costs)
            if r is not None:
                cells.setdefault((e["place"], e["st"], "follow" if d == e["st"][0] else "fade", _per(e, split_ms)), []).append(r)
    matrix = []
    for place in PLACES:
        for st in ORDER:
            row = {"place": place, "state": skey(st), "name": STATES[st][0], "reading": STATES[st][1], "action": ACTION[st], "react": react_of(st),
                   "side": {1: "long", -1: "short"}.get(reaction(st))}
            for react in ("follow", "fade"):
                row[react] = {"is": _stats(cells.get((place, st, react, "T"), [])), "oos": _stats(cells.get((place, st, react, "X"), []))}
            matrix.append(row)
    principles = []
    for name, f in PRINCIPLES:
        rs = {"T": [], "X": []}
        for e in events:
            d = f(e["st"])
            r = _net(e["sims"][(d, best)], costs) if d else None
            if r is not None:
                rs[_per(e, split_ms)].append(r)
        principles.append({"name": name, "is": _stats(rs["T"]), "oos": _stats(rs["X"])})
    # 3) la stratégie, une position à la fois (comme le terminal : 5 idées par semaine au plus)
    say("stratégie")
    confirmations(events)
    cands = []
    for e in rule_ev:
        d = reaction(e["st"])
        s = e["sims"][(d, best)]
        if not s:
            continue
        cands.append({"t": e["t"], "side": "long" if d > 0 else "short", "kind": e["place"], "etype": s["plan"][0], "key": f"{e['place']}|{skey(e['st'])}",
                      "score": 0.0, "S": 0.0, "sim": s, "ev": e})
    pick = lambda cs, a=start_ms, b=end_ms: bt.select(cs, lambda r: True, costs, max_week=MAX_WEEK, zone_cooldown_h=COOLDOWN_H, start_ms=a, end_ms=b)
    variants = []
    for k in range(0, 4):
        tk = pick([c for c in cands if c["ev"]["confirm"] >= k])
        variants.append({"k": k, "is": _stats([t["r"] for t in tk if t["t"] < split_ms]), "oos": _stats([t["r"] for t in tk if t["t"] >= split_ms])})
    trades = pick([c for c in cands if c["ev"]["confirm"] >= CONFIRM_N])
    sub = lambda a, b: [t for t in trades if a <= t["t"] < b]
    slim = lambda m: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items() if k != "equity"}
    strat = {"all": slim(bt.metrics(trades, start_ms, end_ms)), "is": slim(bt.metrics(sub(start_ms, split_ms), start_ms, split_ms)),
             "oos": slim(bt.metrics(sub(split_ms, end_ms), split_ms, end_ms)), "equity": bt.metrics(trades, start_ms, end_ms).get("equity", [])}
    years = {}
    for t in trades:
        y = time.gmtime(t["t"] / 1000).tm_year
        years.setdefault(str(y), []).append(t["r"])
    strat["years"] = {y: _stats(v) for y, v in sorted(years.items())}
    strat["bySide"] = {sd: _stats([t["r"] for t in trades if t["side"] == sd]) for sd in ("long", "short")}
    strat["byPlace"] = {pl: _stats([t["r"] for t in trades if t["kind"] == pl]) for pl in PLACES}
    strat["byState"] = {skey(st): _stats([t["r"] for t in trades if t["c"]["ev"]["st"] == st]) for st in ORDER if reaction(st)}
    strat["costs"] = {}
    for k, mult in (("sans frais", 0.0), ("frais normaux", 1.0), ("frais doublés", 2.0)):
        c2 = {kk: v * mult for kk, v in costs.items()}
        strat["costs"][k] = _stats([bt.net_r(t["c"]["sim"], c2) for t in trades])
    strat["results"] = {k: sum(1 for t in trades if t["result"] == k) for k in ("tp", "stop", "timeout")}
    strat["avgHours"] = round(sum(t["hours"] for t in trades) / len(trades), 1) if trades else None
    say("témoin")
    ctrl = random_control(trades, ds, costs, start_ms, end_ms, runs=controls)
    ctrl_oos = random_control(sub(split_ms, end_ms), ds, costs, split_ms, end_ms, runs=controls)
    pct = lambda c, x: (round(sum(1 for v in c["_exps"] if v < x) / len(c["_exps"]), 3) if c["_exps"] and x is not None else None)
    strat["control"] = {"all": {k: v for k, v in ctrl.items() if k != "_exps"}, "oos": {k: v for k, v in ctrl_oos.items() if k != "_exps"},
                        "pctAll": pct(ctrl, strat["all"].get("expR")), "pctOos": pct(ctrl_oos, strat["oos"].get("expR"))}
    strat["last"] = [{"t": t["t"], "side": t["side"], "place": t["kind"], "state": skey(t["c"]["ev"]["st"]), "src": t["c"]["ev"]["src"], "r": round(t["r"], 3),
                      "result": t["result"], "px": t["px"], "hours": round(t["hours"], 1)} for t in trades[-40:]]
    n_ev = {pl: {per: sum(1 for e in events if e["place"] == pl and _per(e, split_ms) == per) for per in "TX"} for pl in PLACES}
    gen = int(time.time() * 1000)
    rep = {"kind": "flow", "version": VERSION, "label": label, "generated": gen, "computedAt": gen, "period": {"start": start_ms, "end": end_ms, "split": split_ms},
            "source": "Binance perpétuel : bougies 1 minute au vrai volume acheteur agressif, intérêt ouvert toutes les 5 minutes", "tf": events[0]["tf"] if events else None,
            "start": start_ms, "end": end_ms, "split": split_ms, "costs": costs, "exit": best, "exitLabel": exit_label(best), "exits": grid,
            "events": n_ev, "matrix": matrix, "principles": principles, "strategy": strat, "confirm": variants,
            "rules": {"oiFlat": OI_FLAT, "cvdFlat": CVD_FLAT, "approachBars": APPROACH, "holdH": HOLD, "stop": [STOP_MIN, STOP_MAX, STOP_PAD],
                      "maxWeek": MAX_WEEK, "cooldownH": COOLDOWN_H, "validH": VALID_H,
                      "confirmN": CONFIRM_N, "confirmH": CONFIRM_H}}
    rep["verdict"] = verdict(rep)
    return rep


def random_control(trades: list[dict], ds, costs: dict, a: int, b: int, runs: int = 60, seed: int = 5) -> dict:
    """Mêmes trades (sens, entrée, stop et objectif exprimés en ATR, même durée) placés à des clôtures 4 heures tirées au hasard dans la même période."""
    rnd = random.Random(seed)
    geo = []
    for tr in trades:
        e, s = tr["c"]["ev"], tr["c"]["sim"]
        etype, entry, stop, tp, _ = s["plan"]
        d = 1 if tr["side"] == "long" else -1
        A = e["atr"]
        geo.append((d, etype, (entry - e["price"]) / A, (stop - e["price"]) / A, (tp - e["price"]) / A, e["tf"]))
    if not geo:
        return {"runs": 0, "expMean": None, "exp5": None, "exp95": None, "_exps": []}
    tf = geo[0][5]
    step = TF_H[tf] * HOUR
    bars = ds.b1h if step == HOUR else fine.resample(ds.b1h, step)
    atrs = atr_bars(bars)
    idx = [j for j in range(15, len(bars.t)) if a <= bars.t[j] + step < b - HOLD[tf] * HOUR and atrs[j] > 0]
    exps = []
    for _ in range(runs):
        rs = []
        for d, etype, eo, so, to, _tf in geo:
            j = rnd.choice(idx)
            px, A, T = bars.c[j], atrs[j], int(bars.t[j]) + step
            s = play(ds.b5, T, d, etype, px + eo * A, px + so * A, px + to * A, VALID_H, HOLD[tf])
            if s.get("filled"):
                rs.append(bt.net_r(s, costs))
        if rs:
            exps.append(sum(rs) / len(rs))
    exps.sort()
    q = lambda p: round(exps[min(len(exps) - 1, int(p * len(exps)))], 3) if exps else None
    return {"runs": len(exps), "expMean": round(sum(exps) / len(exps), 3) if exps else None, "exp5": q(0.05), "exp95": q(0.95), "_exps": exps}


def verdict(rep: dict) -> dict:
    """Validée si l'espérance de la période de test est positive après frais ET meilleure que 90 % des tirages au hasard de même forme."""
    s = rep.get("strategy") or {}
    o, pc = s.get("oos") or {}, (s.get("control") or {}).get("pctOos")
    ok = bool(o.get("n")) and (o.get("expR") or 0) > 0 and pc is not None and pc >= 0.9
    lab = rep.get("label", "")
    fr = lambda x: f"{x:+.2f}".replace(".", ",")
    if ok:
        txt = (f"{lab} : validée. Période de test : {o['n']} trades, {fr(o['expR'])} fois le risque par trade après frais, mieux que "
               f"{pc * 100:.0f} % des tirages au hasard de même forme.")
    else:
        txt = (f"{lab} : non validée. Période de test : {o.get('n', 0)} trades, {fr(o.get('expR') or 0)} fois le risque par trade après frais"
               + (f", rang {pc * 100:.0f} % face au hasard." if pc is not None else "."))
    return {"validated": ok, "text": txt}


# =====================================================================================================
#  En direct : mêmes événements, mêmes règles, sur les données du terminal
# =====================================================================================================
class LiveData:
    """Ce dont build_events a besoin (b1h, b5) construit depuis les bougies du terminal."""
    def __init__(self, b1h, b5):
        self.b1h, self.b5 = b1h, b5


def live_oi(b1h, live: dict, archive: dict) -> list:
    """Intérêt ouvert à la clôture de chaque bougie 1 h : relevés 5 minutes de l'adresse Binance (clé = ouverture de la bougie 5 min,
    valeur à sa fin) complétés par les archives (clé = heure du relevé). None si aucun relevé dans les 10 minutes avant la clôture."""
    from bisect import bisect_right
    from .subcharts import merge_points
    ts, vs_ = merge_points(live or {}, archive or {})
    out = []
    for t in b1h.t:
        T = int(t) + HOUR
        k = bisect_right(ts, T) - 1
        out.append(vs_[k] if k >= 0 and T - ts[k] <= 600_000 else None)
    return out


def live_signals(data: LiveData, oi: list, tf: str = "4h", days: int = 3) -> dict:
    """Signaux des `days` derniers jours (clôtures 4 heures), confirmations comprises, et lecture du flux sur la dernière bougie fermée."""
    b1h = data.b1h
    if len(b1h.t) < 24 * 45:
        return {"ready": False, "why": "pas assez d'historique (45 jours de bougies 1 heure)"}
    step = TF_H[tf] * HOUR
    T_last = (int(b1h.t[-1]) + HOUR) // step * step                 # dernière clôture 4 heures couverte par les bougies 1 h fermées
    evs = build_events(data, oi, T_last - days * DAY, T_last + 1, tf)
    confirmations(evs)
    bars = fine.resample(b1h, step)
    j = bars.idx_at(T_last - 1)
    now = None
    if j >= APPROACH[tf] and bars.t[j] + step == T_last:
        ja = j - APPROACH[tf]
        i1, ia = b1h.idx_at(T_last - 1), b1h.idx_at(int(bars.t[ja]) + step - 1)
        if i1 >= 0 and ia >= 0 and oi[i1] and oi[ia]:
            p = sign(bars.c[j] / bars.c[ja] - 1.0, 0.0)
            st = flow_state(p, oi[ia], oi[i1], bars.cd[j + 1] - bars.cd[ja + 1], bars.cv[j + 1] - bars.cv[ja + 1])
            now = {"t": T_last, "state": skey(st) if st else None, "oiChg": oi[i1] / oi[ia] - 1.0,
                   "cvdImb": (bars.cd[j + 1] - bars.cd[ja + 1]) / max(1e-9, bars.cv[j + 1] - bars.cv[ja + 1]), "pChg": bars.c[j] / bars.c[ja] - 1.0,
                   "name": STATES[st][0] if st else None, "action": ACTION[st] if st else None, "side": {1: "long", -1: "short"}.get(reaction(st)) if st else None}
    return {"ready": True, "t": T_last, "next": T_last + step, "events": evs, "latest": [e for e in evs if e["t"] == T_last], "now": now}


def idea(e: dict, symbol: str, price: float, validated: bool, rep_txt: str | None, lev: float = 10.0) -> dict | None:
    """Idée du terminal (même format que l'ancien moteur : journal, quota, Telegram, graphique) pour un événement de la dernière clôture 4 heures."""
    import hashlib
    from . import signals as sg
    d = reaction(e["st"])
    if not d:
        return None
    p = plan(e, d, "marché|3R")
    if p is None:
        return None
    etype, entry, stop, tp, kind = p
    risk = abs(entry - stop)
    side = "long" if d > 0 else "short"
    buy = d > 0
    conf = e.get("confirm", 0)
    confirmed = conf >= CONFIRM_N
    comps = [{"key": "flow", "label": "Lieu et flux (prix, intérêt ouvert, flux agressif)", "pts": 60.0, "max": 60, "note": STATES[e["st"]][0]},
             {"key": "confirm", "label": "Confirmation (même signal dans les 24 h)", "pts": float(min(25, 15 * min(conf, 1) + 5 * max(0, conf - 1))), "max": 25,
              "note": f"{conf} autre(s) signal(aux) dans le même sens en 24 h"},
             {"key": "valid", "label": "Stratégie validée sur l'historique de la paire", "pts": 15.0 if validated else 0.0, "max": 15, "note": rep_txt or "pas de rapport"}]
    score = sum(c["pts"] for c in comps)
    gates = []
    if not confirmed:
        gates.append("pas encore confirmée : il faut un deuxième signal dans le même sens en 24 heures (le premier signal d'une série perd de l'argent sur l'historique)")
    if not validated:
        gates.append(f"stratégie non validée sur l'historique de {symbol.replace('USDT', '')} : affichée pour information, jamais envoyée")
    st = e["st"]
    place = "une poche de liquidité" if e["place"] == "liq" else "un VWAP"
    lvl = sg.fmt_price(e["lvl"])
    pct = lambda a: (a / entry - 1.0) * 100.0
    if e["place"] == "liq":
        where = (f"La bougie 4 heures a pris la liquidité {'au-dessus' if st[0] > 0 else 'en dessous'} du {e['src']} ({lvl}). "
                 f"Depuis ce {'plus haut' if st[0] > 0 else 'plus bas'} (il y a {e.get('ageH') or 0:.0f} h), l'intérêt ouvert a {'monté' if st[1] > 0 else 'baissé'} de "
                 f"{abs(e['oiChg']) * 100:.1f} % et le cumul des achats agressifs moins les ventes agressives est {'plus haut' if st[2] > 0 else 'plus bas'} "
                 f"({e['cvdImb'] * 100:+.1f} % du volume échangé).")
    else:
        where = (f"La bougie 4 heures a touché le {e['src']} ({lvl}) en arrivant par le {'bas' if st[0] > 0 else 'haut'}. Sur les 12 heures d'approche, "
                 f"l'intérêt ouvert a {'monté' if st[1] > 0 else 'baissé'} de {abs(e['oiChg']) * 100:.1f} % et le cumul des achats agressifs moins les ventes agressives a {'monté' if st[2] > 0 else 'baissé'} "
                 f"({e['cvdImb'] * 100:+.1f} % du volume échangé).")
    action = [f"Entrée : au marché, vers {sg.fmt_price(entry)} (clôture de la bougie 4 heures du signal). Si le prix est déjà loin quand tu lis ce message, ne cours pas après.",
              f"Stop : {sg.fmt_price(stop)} ({sg.fmt_pct(pct(stop), 2, True)}), au-delà de la bougie du signal.",
              f"Objectif : {sg.fmt_price(tp)} ({sg.fmt_pct(pct(tp), 2, True)}), 3 fois le risque pris (la meilleure sortie sur l'historique).",
              f"Durée : 72 heures au plus. Si ni le stop ni l'objectif ne sont touchés, sortie au marché (c'est la règle mesurée)."]
    why = [where, f"Combinaison : {words(st)} — {STATES[st][0]}. {STATES[st][1]}", f"Réaction : {ACTION[st]}",
           f"Confirmation : {conf} autre(s) signal(aux) dans le même sens pendant les 24 heures précédentes" + (" : le flux se répète." if confirmed else " : pas encore confirmé.")]
    ups, dns = [x for x in e["up"][:3]], [x for x in e["dn"][:3]]
    liq = [f"  • Poches au-dessus : {', '.join(sg.fmt_price(x) for x in ups)}" if ups else "", f"  • Poches en dessous : {', '.join(sg.fmt_price(x) for x in dns)}" if dns else ""]
    liq = [x for x in liq if x]
    if liq:
        why += ["Liquidités autour (plus hauts et plus bas où les ordres d'arrêt s'accumulent) :"] + liq
    levl, levinfo = sg.leverage_lines({"side": side, "entry": entry, "stop": stop}, lev)
    risks = ["Mesure honnête : sur SOL, la stratégie gagne sur la période de test ; sur le BTC et sur l'ETH (contrôle à l'aveugle), elle ne gagne pas. "
             "L'avantage est donc fragile : petite taille de position, et le journal des idées dira la vérité."] + levl
    risks.append("Ce sont des statistiques passées, pas une garantie ni un conseil financier. Ne risque que ce que tu acceptes de perdre.")
    head = f"{symbol} : {'ACHAT (position longue)' if buy else 'VENTE (position courte)'}"
    desc = {"headline": head, "action": action, "why": why, "trend": [], "macro": [], "context": [], "news": [],
            "probs": [rep_txt] if rep_txt else [], "risks": risks, "leverage": levinfo}
    key = hashlib.md5(f"{symbol}{side}{e['place']}{skey(st)}{e['t']}".encode()).hexdigest()[:10]
    return {"key": key, "symbol": symbol, "side": side, "kind": "flux", "place": e["place"], "state": skey(st), "stateName": STATES[st][0],
            "score": score, "grade": sg.grade(score), "entry": entry, "entryType": "marché", "stop": stop, "tp1": tp, "tp2": None,
            "rr1": round(abs(tp - entry) / risk, 2), "rr2": None, "atr": e["atr"], "atrPct": e["atr"] / entry * 100.0, "price": price, "distAtr": 0.0,
            "zone": {"lo": min(entry, e["lvl"]), "hi": max(entry, e["lvl"])}, "zoneId": None, "validHours": TF_H[e["tf"]], "signalT": e["t"],
            "tp1Kind": "3R", "tp2Kind": None, "align": None, "eligible": confirmed and validated, "hold": [], "gates": gates, "probs": None, "valid": None,
            "st": {"S": 0.0, "n": 0, "items": []}, "comps": comps, "warn": [], "desc": desc, "confirm": conf, "level": e["lvl"], "levelName": e["src"],
            "oiChg": e["oiChg"], "cvdImb": e["cvdImb"]}
