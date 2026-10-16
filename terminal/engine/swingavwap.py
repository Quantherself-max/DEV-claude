"""VWAP ancres sur un mouvement precedent d'au moins X % (par defaut 5 %), et reactions du prix a ces VWAP.

Le mouvement est detecte par un zigzag CONFIRME, sans donnees du futur :
  - un sommet n'est connu que lorsque le prix a baisse d'au moins X % depuis lui (date de confirmation = cloture de cette bougie) ;
  - un creux n'est connu que lorsque le prix a rebondi d'au moins X % depuis lui.
Deux sortes d'ancres, toutes deux issues d'un mouvement d'au moins X % :
  - « H » : VWAP ancre sur le SOMMET qui a precede la baisse (debut de la baisse) ; le prix est dessous, le VWAP joue le role de resistance ;
  - « L » : VWAP ancre sur le CREUX de la baisse (fin de la baisse, apres un rebond d'au moins X %) ; le prix est dessus, le VWAP joue le role de support.
Un « contact » est une bougie 1 h qui touche le VWAP ancre ; son sens est le cote de la CLOTURE (meme convention que vwapstrat).
Les evenements ont le meme format que vwapstrat.build_events (sorties et selection partagees). Module PUR."""
from . import backtest as bt
from .backtest import DAY, HOUR

MAX_AGE_DAYS = 30                 # un VWAP ancre n'est suivi que pendant 30 jours
COOLDOWN_BARS = 3                 # meme ancre, meme sens : pas de nouvel evenement avant 3 bougies


def zigzag(b, pct: float) -> list[dict]:
    """Pivots confirmes sur les bougies `b` (fine.Bars) : [{kind: 'H'|'L', i: index du sommet/creux, px, ic: index de la bougie de confirmation}].
    Une bougie qui confirmerait les deux sens a la fois est ignoree pour la confirmation (cas rare)."""
    n = len(b.t)
    if n < 3:
        return []
    h, l = b.h, b.l
    out = []
    trend = 0                                         # +1 : on suit un sommet candidat ; -1 : un creux candidat ; 0 : pas encore decide
    hi_px, hi_i, lo_px, lo_i = h[0], 0, l[0], 0
    for j in range(1, n):
        if trend == 0:
            if h[j] > hi_px:
                hi_px, hi_i = h[j], j
            if l[j] < lo_px:
                lo_px, lo_i = l[j], j
            up = h[j] >= lo_px * (1 + pct) and lo_i < j
            dn = l[j] <= hi_px * (1 - pct) and hi_i < j
            if up and not dn:
                out.append({"kind": "L", "i": lo_i, "px": lo_px, "ic": j})
                trend, hi_px, hi_i = 1, h[j], j
            elif dn and not up:
                out.append({"kind": "H", "i": hi_i, "px": hi_px, "ic": j})
                trend, lo_px, lo_i = -1, l[j], j
        elif trend == 1:
            if h[j] > hi_px:
                hi_px, hi_i = h[j], j
            elif l[j] <= hi_px * (1 - pct):
                out.append({"kind": "H", "i": hi_i, "px": hi_px, "ic": j})
                trend, lo_px, lo_i = -1, l[j], j
        else:
            if l[j] < lo_px:
                lo_px, lo_i = l[j], j
            elif h[j] >= lo_px * (1 + pct):
                out.append({"kind": "L", "i": lo_i, "px": lo_px, "ic": j})
                trend, hi_px, hi_i = 1, h[j], j
    return out


def avwap_at(b, ia: int, j: int):
    """VWAP ancre a la bougie ia, valeur a la CLOTURE de la bougie j (incluse) ; None sans volume."""
    v = b.cv[j + 1] - b.cv[ia]
    return (b.cpv[j + 1] - b.cpv[ia]) / v if v > 0 else None


def build_events(ds: "bt.Dataset", start_ms: int, end_ms: int, pct: float = 0.05, max_age_days: float = MAX_AGE_DAYS, ma=None, warm_days: int = 120) -> list[dict]:
    """Contacts des VWAP ancres sur un mouvement d'au moins `pct` : un evenement par bougie 1 h fermee qui touche l'ancre (sur [start_ms, end_ms))."""
    b = ds.b1h
    ma = ma or bt.regime_series(b)
    piv = zigzag(b, pct)
    out = []
    n = len(b.t)
    max_bars = int(max_age_days * 24)
    for a_k, p in enumerate(piv):
        ia, ic = p["i"], p["ic"]
        if b.t[ic] + HOUR < start_ms - warm_days * DAY:
            continue
        # profondeur de la baisse : « H » -> sommet vers le plus bas atteint jusqu'a l'instant t ; « L » -> sommet precedent vers ce creux
        prev = piv[a_k - 1] if a_k > 0 else None
        depth_L = (prev["px"] - p["px"]) / prev["px"] if (p["kind"] == "L" and prev is not None and prev["kind"] == "H") else None
        low_so_far = min(b.l[ia:ic + 1]) if p["kind"] == "H" else p["px"]
        last, touches = {}, 0
        for j in range(ic + 1, min(n, ia + max_bars)):
            T = int(b.t[j] + HOUR)
            if T >= end_ms:
                break
            if p["kind"] == "H" and b.l[j] < low_so_far:
                low_so_far = b.l[j]
            if T < start_ms:
                continue
            V = avwap_at(b, ia, j)
            if V is None:
                continue
            l_, h_, cl, pc = b.l[j], b.h[j], b.c[j], b.c[j - 1]
            if not (l_ <= V <= h_) or cl == V:
                continue
            d = 1 if cl > V else -1
            if T - last.get(d, -10 ** 15) < COOLDOWN_BARS * HOUR:
                continue
            last[d] = T
            touches += 1
            atr = ds.atr_at(T)
            if atr <= 0:
                continue
            side_before = 1 if pc > V else -1
            depth = depth_L if p["kind"] == "L" else (p["px"] - low_so_far) / p["px"]
            vol_prev = sum(b.v[max(0, j - 24):j])
            out.append({"t": T, "tf": "1h", "dir": d, "type": "cross" if (pc - V) * (cl - V) < 0 else "bounce", "level": "VWAP ancré " + ("sur le sommet" if p["kind"] == "H" else "sur le creux"),
                        "anchor": p["kind"], "fam": "avwap", "grp": p["kind"], "rank": 0 if p["kind"] == "H" else 1, "V": V, "price": cl, "atr": atr, "o": b.o[j], "h": h_, "l": l_, "c": cl,
                        "volr": b.v[j] / (vol_prev / max(1, min(24, j))) if vol_prev > 0 else None, "reg": bt.regime_at(ds, ma, T), "sideBefore": side_before,
                        "ageD": (T - b.t[ia]) / DAY, "depth": depth, "touchNo": touches, "anchorT": int(b.t[ia]), "up": [], "dn": []})
    out.sort(key=lambda e: (e["t"], e["rank"]))
    return out


def reaction(e: dict) -> str:
    """Ce que fait la cloture face au VWAP ancre : « tient » (reste du meme cote qu'avant : rejet pour un sommet, rebond pour un creux) ou « traverse »."""
    return "tient" if e["dir"] == e["sideBefore"] else "traverse"
