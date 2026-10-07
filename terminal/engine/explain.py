"""Pourquoi le prix a bouge ? Reperage des mouvements recents et des faits qui les accompagnent (V12), pour l'assistant de discussion.

Un mouvement = la plus forte baisse (sommet puis creux) et la plus forte hausse (creux puis sommet) des dernieres heures, sur les bougies 5 minutes.
Pour chacun, les FAITS mesures par le terminal pendant la meme fenetre : variation de l'interet ouvert, flux d'ordres agressifs (CVD), volume par rapport a
la normale, liquidations reelles (longs / shorts), mouvements du dollar, des taux, des actions, de l'or et de la volatilite, annonces macro proches.
Aucune interpretation ici : l'assistant (Claude) s'en charge a partir de ces faits. Module PUR (stdlib)."""
import calendar
import time
from bisect import bisect_right
from datetime import datetime, timezone

M5 = 300_000
HOUR = 3_600_000


# ---------------------------------------------------------------- heure de Paris (sans base de fuseaux : regle europeenne de l'heure d'ete)
def _last_sunday(y: int, m: int) -> int:
    d = calendar.monthrange(y, m)[1]
    while calendar.weekday(y, m, d) != 6:
        d -= 1
    return d


def paris_offset_h(ms: int) -> int:
    """+2 en heure d'ete (du dernier dimanche de mars 01:00 UTC au dernier dimanche d'octobre 01:00 UTC), +1 sinon."""
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    start = datetime(d.year, 3, _last_sunday(d.year, 3), 1, tzinfo=timezone.utc)
    end = datetime(d.year, 10, _last_sunday(d.year, 10), 1, tzinfo=timezone.utc)
    return 2 if start <= d < end else 1


def paris(ms: int, with_day: bool = True) -> str:
    d = datetime.fromtimestamp(ms / 1000 + paris_offset_h(ms) * 3600, timezone.utc)
    return d.strftime("%d/%m %Hh%M" if with_day else "%Hh%M")


# ---------------------------------------------------------------- mouvements
def moves(candles, now_ms: int, hours: float = 24.0, min_pct: float = 0.6) -> list:
    """Plus forte baisse (sommet -> creux suivant) et plus forte hausse (creux -> sommet suivant) sur les `hours` dernieres heures.
    candles : objets avec t, h, l, c (bougies 5 min). Renvoie une liste de {kind, t0, t1, p0, p1, pct} (mouvements d'au moins min_pct %)."""
    cs = [k for k in candles if k.t >= now_ms - hours * HOUR]
    if len(cs) < 6:
        return []
    out = []
    hi, hi_t, best = None, None, None                                      # baisse : sommet puis creux
    for k in cs:
        if hi is None or k.h >= hi:                                        # dernier passage au sommet : le mouvement part de là
            hi, hi_t = k.h, k.t
        dd = k.l / hi - 1.0
        if best is None or dd < best[0]:
            best = (dd, hi_t, k.t, hi, k.l)
    if best and best[0] * 100 <= -min_pct:
        out.append({"kind": "baisse", "t0": best[1], "t1": best[2] + M5, "p0": best[3], "p1": best[4], "pct": best[0] * 100})
    lo, lo_t, best = None, None, None                                      # hausse : creux puis sommet
    for k in cs:
        if lo is None or k.l <= lo:
            lo, lo_t = k.l, k.t
        ru = k.h / lo - 1.0
        if best is None or ru > best[0]:
            best = (ru, lo_t, k.t, lo, k.h)
    if best and best[0] * 100 >= min_pct:
        out.append({"kind": "hausse", "t0": best[1], "t1": best[2] + M5, "p0": best[3], "p1": best[4], "pct": best[0] * 100})
    return sorted(out, key=lambda m: -abs(m["pct"]))


def _value_at(ts: list, vs: list, t: int):
    i = bisect_right(ts, t) - 1
    return vs[i] if i >= 0 else None


def _series_at(pairs: list, t: int, tol_ms: int = 3 * HOUR):
    """Derniere valeur d'une serie [(t, v)] avant t (None si trop ancienne : marche ferme)."""
    ts = [p[0] for p in pairs]
    i = bisect_right(ts, t) - 1
    if i < 0 or t - pairs[i][0] > tol_ms:
        return None
    return pairs[i][1]


def window_facts(m: dict, candles, oi_t: list, oi_v: list, liqs: list, cross5: dict, events: list) -> dict:
    """Faits mesures pendant la fenetre du mouvement m (voir moves). liqs = [{t, side, usd, price}], cross5 = {nom: [(t, valeur)]},
    events = [{t, label, impact, reaction?}]."""
    t0, t1 = m["t0"], m["t1"]
    sel = [k for k in candles if t0 <= k.t < t1]
    vol = sum(k.v for k in sel)
    buy = sum(k.tb for k in sel)
    dur = max(M5, t1 - t0)
    base = [k for k in candles if t0 - 7 * 24 * HOUR <= k.t < t0]
    base_rate = (sum(k.v for k in base) / (len(base) * M5)) if base else None
    out = {"minutes": dur / 60000.0, "volume": vol, "volRatio": (vol / dur) / base_rate if base_rate else None,
           "buyPct": buy / vol * 100.0 if vol > 0 and buy > 0 else None, "cvd": (2 * buy - vol) if vol > 0 and buy > 0 else None}
    a, b = _value_at(oi_t, oi_v, t0), _value_at(oi_t, oi_v, t1)
    out["oiPct"] = (b / a - 1.0) * 100.0 if a and b else None
    lq = [e for e in liqs if t0 - M5 <= e["t"] <= t1 + M5]
    out["liqLong"] = sum(e["usd"] for e in lq if e["side"] == "long")
    out["liqShort"] = sum(e["usd"] for e in lq if e["side"] == "short")
    big = max(lq, key=lambda e: e["usd"], default=None)
    out["liqBiggest"] = {"t": big["t"], "side": big["side"], "usd": big["usd"], "price": big.get("price")} if big else None
    cross = {}
    for name, pairs in (cross5 or {}).items():
        x0, x1 = _series_at(pairs, t0), _series_at(pairs, t1)
        if x0 and x1:
            cross[name] = (x1 - x0) if name in POINTS else (x1 / x0 - 1.0) * 100.0
    out["cross"] = cross
    out["events"] = [e for e in events if t0 - 2 * HOUR <= e["t"] <= t1 + 30 * 60000]
    return out


# ---------------------------------------------------------------- texte
def f(v, d=1, sign=False, unit=""):
    if v is None:
        return "n/d"
    s = f"{v:+,.{d}f}" if sign else f"{v:,.{d}f}"
    return s.replace(",", " ").replace(".", ",").replace("-", "−") + unit


def usd(v):
    if v is None:
        return "n/d"
    a = abs(v)
    return f(v / 1e9, 2) + " Md$" if a >= 1e9 else f(v / 1e6, 1) + " M$" if a >= 1e6 else f(v / 1e3, 0) + " k$"


CROSS_NAMES = {"DXY": "dollar (DXY)", "US10Y": "taux américain à 10 ans", "SPX": "S&P 500 (futures)", "NDX": "Nasdaq (futures)", "VIX": "VIX", "GOLD": "or"}
POINTS = ("US10Y", "VIX")                  # variations en points, pas en %


def cross_change(name: str, v) -> str:
    return f"{CROSS_NAMES.get(name, name)} {f(v, 2, True)}" + (" point" if name in POINTS else " %")


def move_text(sym: str, m: dict, fx: dict) -> str:
    lines = [f"{sym} : {m['kind']} de {f(m['pct'], 2, True)} % de {paris(m['t0'])} à {paris(m['t1'])} (heure de Paris), de {f(m['p0'], 2)} à {f(m['p1'], 2)}, "
             f"en {f(fx['minutes'], 0)} minutes."]
    flow = []
    if fx.get("oiPct") is not None:
        flow.append(f"intérêt ouvert {f(fx['oiPct'], 2, True)} %")
    if fx.get("buyPct") is not None:
        flow.append(f"acheteurs agressifs {f(fx['buyPct'], 1)} % du volume")
    if fx.get("volRatio") is not None:
        flow.append(f"volume {f(fx['volRatio'], 1)} fois la normale des 7 jours")
    if flow:
        lines.append("  Pendant le mouvement : " + ", ".join(flow) + ".")
    if fx["liqLong"] or fx["liqShort"]:
        big = fx.get("liqBiggest")
        lines.append(f"  Liquidations réelles vues par le terminal : longs {usd(fx['liqLong'])}, shorts {usd(fx['liqShort'])}"
                     + (f" ; la plus grosse : {big['side']} {usd(big['usd'])} à {paris(big['t'], False)}" if big else "") + ".")
    else:
        lines.append("  Liquidations réelles : aucune vue par le terminal (ou flux non connecté à ce moment-là).")
    if fx["cross"]:
        lines.append("  Autres marchés sur la même fenêtre : " + ", ".join(cross_change(k, v) for k, v in fx["cross"].items()) + ".")
    else:
        lines.append("  Autres marchés : fermés ou indisponibles sur cette fenêtre.")
    if fx["events"]:
        lines.append("  Annonces macro proches : " + " ; ".join(f"{e['label']} à {paris(e['t'], False)}" + (" (impact fort)" if e.get("impact", 0) >= 3 else "") for e in fx["events"]) + ".")
    else:
        lines.append("  Aucune annonce macro du calendrier dans les 2 heures avant le mouvement.")
    return "\n".join(lines)


def now_ms() -> int:
    return int(time.time() * 1000)
