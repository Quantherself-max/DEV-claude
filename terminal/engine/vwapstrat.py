"""La strategie de l'utilisateur, ecrite comme une FAMILLE de variantes testables (backtest.py / hedge.py).

Description de depart
  - Declencheur : sur une bougie 1 h ou 4 h qui TOUCHE un VWAP ou un VWAP ancre de la semaine ou du mois, on regarde de quel cote elle
    CLOTURE. Cloture au-dessus -> achat ; cloture en dessous -> vente. (« rebond / reprise » du niveau ; la variante « contre » fait l'inverse.)
  - Objectif et sortie : sur les POCHES DE LIQUIDITE visibles dans le prix (plus hauts / plus bas, creux, sommets, niveaux egaux).
  - Volume profile : position de la cloture par rapport a la VAL / VAH (zone de valeur) pour savoir si le prix REINTEGRE la zone ou la REJETTE.
  - Duree : 1 jour, 2 jours au maximum « s'il y a du volume ».

Le module est PUR : il fabrique les evenements (tout ce qui est connu a la cloture de la bougie), joue chaque trade sur les bougies 5 minutes avec
les memes frais que backtest.py, et fournit les adaptateurs pour backtest.select / metrics."""
import random
from bisect import bisect_left
from datetime import datetime, timezone

from . import backtest as bt
from . import fine, liqsweep
from .backtest import DAY, HOUR
from .periods import PeriodTracker

M5 = 300_000

# niveaux : (nom, groupe periode, famille, priorite) ; priorite = ordre de preference quand plusieurs niveaux sont touches en meme temps
LEVELS = [
    ("VWAP du mois", "M", "vwap"), ("VWAP ancré au début du mois dernier", "M", "avwap"),
    ("VWAP ancré sur le plus bas de 30 jours", "M", "avwap"), ("VWAP ancré sur le plus haut de 30 jours", "M", "avwap"),
    ("VWAP de la semaine", "W", "vwap"), ("VWAP ancré au début de la semaine dernière", "W", "avwap"),
    ("VWAP ancré sur le plus bas de 7 jours", "W", "avwap"), ("VWAP ancré sur le plus haut de 7 jours", "W", "avwap"),
]
LEVEL_INFO = {n: (g, f, k) for k, (n, g, f) in enumerate(LEVELS)}
COOLDOWN_BARS = 3                  # un meme niveau, dans le meme sens, ne redeclenche pas avant 3 bougies de la meme echelle


def week_start(t_ms: int) -> int:
    return ((t_ms // DAY + 3) // 7 * 7 - 3) * DAY


def month_start(t_ms: int, back: int = 0) -> int:
    d = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
    m = d.year * 12 + d.month - 1 - back
    return bt.ms(m // 12, m % 12 + 1)


def _pos(c: float, vp) -> int | None:
    """-1 : sous la VAL ; +1 : au-dessus de la VAH ; 0 : dans la zone de valeur."""
    if not vp or vp.get("val") is None or vp.get("vah") is None:
        return None
    return -1 if c < vp["val"] else 1 if c > vp["vah"] else 0


def _tf_bar(b: "fine.Bars", T: int):
    j = b.idx_at(T - 1)
    if j < 1 or b.t[j] + b.step != T:
        return None
    return j


def triggers(vals: dict, l: float, h: float, cl: float, pc: float) -> dict:
    """Niveaux declenches par une bougie (bas l, haut h, cloture cl, cloture precedente pc) : {+1: [(nom, niveau, type)], -1: [...]}.
    Declenchement = la bougie TOUCHE le niveau ; le sens est le cote de la CLOTURE (au-dessus : achat, en dessous : vente) ;
    type « cross » si la cloture precedente etait de l'autre cote, « bounce » sinon."""
    trig = {1: [], -1: []}
    for name, V in vals.items():
        if not (l <= V <= h) or cl == V:
            continue
        d = 1 if cl > V else -1
        trig[d].append((name, V, "cross" if (pc - V) * (cl - V) < 0 else "bounce"))
    return trig


def vp_context(vps: dict, cl: float, pc: float) -> dict:
    """Position de la cloture (et de la precedente) face a la zone de valeur de chaque profil : -1 sous la VAL, 0 dedans, +1 au-dessus de la VAH."""
    return {"pos": {k: _pos(cl, vp) for k, vp in vps.items()}, "posPrev": {k: _pos(pc, vp) for k, vp in vps.items()}}


def build_events(ds: "bt.Dataset", start_ms: int, end_ms: int, warm_days: int = 75, ma=None, min_pool_score: int = 55) -> list[dict]:
    """Evenements de declenchement sur [start_ms, end_ms) a chaque cloture 1 h / 4 h (seules les donnees fermees sont utilisees).
    Les bougies des `warm_days` jours precedents servent de chauffe aux profils de la semaine / du mois precedents."""
    ma = ma or bt.regime_series(ds.b1h)
    b5, b1h = ds.b5, ds.b1h
    b4h = fine.resample(b1h, 4 * HOUR)
    tr = {k: PeriodTracker(k) for k in ("D", "W", "M")}
    pl = liqsweep.PriceLiquidity(b1h)
    out, last_ev = [], {}
    i0 = max(0, b5.idx(start_ms - warm_days * DAY))
    cache = {}
    for i5 in range(i0, len(b5.t)):
        c = b5.candle(i5)
        for t in tr.values():
            t.feed(c)
        T = c.t + M5
        if T >= end_ms:
            break
        if T < start_ms or T % HOUR:
            continue
        atr = ds.atr_at(T)
        if atr <= 0:
            continue
        price = c.c
        # ---- niveaux (VWAP et VWAP ancres) ----
        j1 = b1h.idx_at(T - 1)
        anchors = {"VWAP du mois": None, "VWAP de la semaine": None}
        ws, ms_ = week_start(T), month_start(T)
        day = T // DAY
        if cache.get("day") != day:
            def swing(n, low):
                a = max(0, j1 - n * 24)
                seg = b1h.l[a:j1] if low else b1h.h[a:j1]
                if len(seg) < n * 12:
                    return None
                v = min(seg) if low else max(seg)
                return int(b1h.t[a + list(seg).index(v)])
            cache["day"] = day
            cache["sw"] = {"VWAP ancré sur le plus bas de 30 jours": swing(30, True), "VWAP ancré sur le plus haut de 30 jours": swing(30, False),
                           "VWAP ancré sur le plus bas de 7 jours": swing(7, True), "VWAP ancré sur le plus haut de 7 jours": swing(7, False)}
        anc = {"VWAP du mois": ms_, "VWAP de la semaine": ws, "VWAP ancré au début du mois dernier": month_start(T, 1),
               "VWAP ancré au début de la semaine dernière": ws - 7 * DAY, **cache["sw"]}
        vals = {}
        for name, a in anc.items():
            if a is None:
                continue
            ia = b5.idx(a)
            if i5 - ia > 24:
                vw, sd = b5.vwap(ia, i5 + 1)
                if vw:
                    vals[name] = vw
        if not vals:
            continue
        # ---- volume profiles : zone de valeur courante et precedente (semaine, mois) ----
        vps = {"pw": (tr["W"].prev or {}).get("vp"), "pm": (tr["M"].prev or {}).get("vp"), "cw": tr["W"]._cur_vp(), "cm": tr["M"]._cur_vp()}
        # ---- poches de liquidite (pour les objectifs) ----
        ext = liqsweep.extremes_from_trackers(tr, T)
        pools = [p for p in pl.pools(price, atr, T, ext) if p["score"] >= min_pool_score]
        up = sorted([(p["price"], p["score"]) for p in pools if p["side"] == "short" and p["price"] > price], key=lambda x: x[0])[:5]
        dn = sorted([(p["price"], p["score"]) for p in pools if p["side"] == "long" and p["price"] < price], key=lambda x: -x[0])[:5]
        regime = bt.regime_at(ds, ma, T)
        for tf, bars in (("1h", b1h), ("4h", b4h)):
            if tf == "4h" and T % (4 * HOUR):
                continue
            j = _tf_bar(bars, T)
            if j is None:
                continue
            o, h, l, cl, v = bars.o[j], bars.h[j], bars.l[j], bars.c[j], bars.v[j]
            pc = bars.c[j - 1]
            volr = v / (sum(bars.v[max(0, j - 24):j]) / max(1, min(24, j))) if j > 0 and sum(bars.v[max(0, j - 24):j]) > 0 else None
            ctx = vp_context(vps, cl, pc)
            pos_now, pos_prev = ctx["pos"], ctx["posPrev"]
            trig = triggers(vals, l, h, cl, pc)
            for d, lst in trig.items():
                for name, V, typ in lst:
                    key = (tf, name, d)
                    if T - last_ev.get(key, -10 ** 15) < COOLDOWN_BARS * bars.step:
                        continue
                    last_ev[key] = T
                    g, fam, rank = LEVEL_INFO[name][0], LEVEL_INFO[name][1], LEVEL_INFO[name][2]
                    out.append({"t": T, "tf": tf, "dir": d, "type": typ, "level": name, "grp": g, "fam": fam, "rank": rank, "V": V, "price": price, "atr": atr,
                                "o": o, "h": h, "l": l, "c": cl, "volr": volr, "reg": regime, "pos": pos_now, "posPrev": pos_prev,
                                "n_lv": len(lst), "up": up, "dn": dn,
                                "vp": {k: (None if not vp else (vp.get("val"), vp.get("poc"), vp.get("vah"))) for k, vp in vps.items()}})
    out.sort(key=lambda e: (e["t"], e["tf"], e["rank"]))
    return out


# =====================================================================================================
#  Geometrie des trades (stop, objectifs) et simulation sur bougies 5 minutes
# =====================================================================================================
STOPS = ("struct", "atr15", "atr3", "atr5")
ATR_STOP = {"atr15": 1.5, "atr3": 3.0, "atr5": 5.0}          # stop fixe a N amplitudes d'une bougie 1 h (un trade de 1 a 2 jours supporte un bruit plus large que 1,5)
TPS = ("pool", "pool2R", "2R", "poolhalf")
HOLDS = ("H24", "H48", "H24x")                       # 24 h, 48 h, ou 24 h prolongees a 48 h s'il y a du volume
CONFIGS = [f"{s}|{t}|{h}" for s in STOPS for t in TPS for h in HOLDS]


def geometry(ev: dict, stop_mode: str, tp_mode: str, min_r: float = 1.0, max_pool_atr: float = 8.0):
    """(stop, tp1, tp2, partial) en prix, ou None si le trade n'existe pas (stop trop loin, aucun objectif sur une poche)."""
    px, atr, d, V = ev["price"], ev["atr"], ev["dir"], ev["V"]
    if stop_mode == "struct":
        stop = (min(ev["l"], V) - 0.25 * atr) if d > 0 else (max(ev["h"], V) + 0.25 * atr)
        risk = abs(px - stop)
        if risk > 4.0 * atr:
            return None
        if risk < 1.0 * atr:
            stop, risk = px - d * atr, atr
    else:
        k = ATR_STOP[stop_mode]
        stop, risk = px - d * k * atr, k * atr
    pools = [p for p, s in (ev["up"] if d > 0 else ev["dn"]) if abs(p - px) >= min_r * risk and abs(p - px) <= max_pool_atr * atr]
    if tp_mode == "pool":
        return (stop, pools[0], None, 1.0) if pools else None
    if tp_mode == "pool2R":
        return (stop, pools[0] if pools else px + d * 2 * risk, None, 1.0)
    if tp_mode == "2R":
        return (stop, px + d * 2 * risk, None, 1.0)
    if tp_mode == "poolhalf":
        return (stop, pools[0], pools[1] if len(pools) > 1 else None, 0.5) if pools else None
    raise ValueError(tp_mode)


def simulate_v(b5: "fine.Bars", T: float, d: int, stop: float, tp1: float, tp2, partial: float, hold_h: float, ext_h: float = 0.0) -> dict:
    """Entree au marche a l'ouverture de la bougie 5 min qui suit la cloture, stop, objectif 1 (prise de `partial`, stop a l'entree pour le reste),
    objectif 2, sortie au marche au bout de hold_h ; si ext_h : au bout de hold_h, on garde jusqu'a ext_h seulement si le volume de la derniere heure
    est au moins egal au volume horaire moyen des 24 heures precedentes. Stop compte avant l'objectif dans une meme bougie."""
    n = len(b5.t)
    i = bisect_left(b5.t, T)
    if i >= n - 1:
        return {"result": "open", "filled": False}
    O, H, L, C, Tt = b5.o, b5.h, b5.l, b5.c, b5.t
    fp = O[i]
    long_ = d > 0
    if (stop - fp) * d >= 0 or (tp1 - fp) * d <= 0:
        return {"result": "cancel", "filled": False}
    risk = abs(fp - stop)
    per_h = HOUR / b5.step
    end = min(n, i + int(hold_h * per_h))
    checked, extended = False, False
    pos, stop_cur, tp1_done = 1.0, stop, False
    legs, mfe, mae, res, exit_q = [], 0.0, 0.0, None, end - 1
    q = i
    while q < end:
        hi, lo = H[q], L[q]
        fav, adv = ((hi - fp) / risk, (fp - lo) / risk) if long_ else ((fp - lo) / risk, (hi - fp) / risk)
        mfe, mae = max(mfe, fav), max(mae, adv)
        if (lo <= stop_cur) if long_ else (hi >= stop_cur):
            px = min(O[q], stop_cur) if long_ else max(O[q], stop_cur)
            legs.append(("taker", pos, px))
            pos, exit_q, res = 0.0, q, ("stop_be" if tp1_done else "stop")
            break
        if q > i:
            if not tp1_done and ((hi >= tp1) if long_ else (lo <= tp1)):
                legs.append(("maker", partial, tp1))
                pos -= partial
                tp1_done, stop_cur = True, fp
                if pos <= 1e-9:
                    pos, exit_q, res = 0.0, q, "tp"
                    break
                if (lo <= fp) if long_ else (hi >= fp):
                    legs.append(("taker", pos, fp))
                    pos, exit_q, res = 0.0, q, "tp1_be"
                    break
            if tp1_done and tp2 is not None and ((hi >= tp2) if long_ else (lo <= tp2)):
                legs.append(("maker", pos, tp2))
                pos, exit_q, res = 0.0, q, "tp2"
                break
        q += 1
        if q == end and ext_h and not checked:
            checked = True
            a = b5.cv
            per_hr = int(per_h)
            last_h = a[q] - a[max(0, q - per_hr)]
            prev_h = (a[q - per_hr] - a[q - per_hr - 24 * per_hr]) / 24.0 if q - per_hr - 24 * per_hr >= 0 else 0.0
            if prev_h > 0 and last_h >= prev_h:
                extended = True
                end = min(n, i + int(ext_h * per_h))
    else:
        px = C[end - 1]
        legs.append(("taker", pos, px))
        exit_q, res = end - 1, ("timeout_tp1" if tp1_done else "timeout")
    r_gross = sum(f * (p - fp) * d for _, f, p in legs) / risk
    return {"result": res, "filled": True, "fill_t": int(Tt[i]), "exit_t": int(Tt[exit_q] + b5.step), "fill_px": fp, "risk": risk, "r_gross": r_gross,
            "entry_kind": "taker", "legs": [(k, f) for k, f, _ in legs], "hours": (Tt[exit_q] + b5.step - Tt[i]) / HOUR, "mfe": mfe, "mae": mae, "tp1": tp1_done,
            "extended": extended}


def run_config(ds, ev: dict, cfg: str):
    s_mode, t_mode, h_mode = cfg.split("|")
    g = geometry(ev, s_mode, t_mode)
    if g is None:
        return None
    stop, tp1, tp2, partial = g
    hold, ext = {"H24": (24, 0), "H48": (48, 0), "H24x": (24, 48)}[h_mode]
    return simulate_v(ds.b5, ev["t"], ev["dir"], stop, tp1, tp2, partial, hold, ext)


def attach(events: list[dict], ds, configs=CONFIGS) -> None:
    for ev in events:
        ev["sims"] = {c: run_config(ds, ev, c) for c in configs}


# =====================================================================================================
#  Selection par regle (adaptateur vers backtest.select / metrics)
# =====================================================================================================
def as_candidates(events: list[dict], cfg: str, rule, order_key=None) -> list[dict]:
    """Evenements retenus par `rule`, un seul par (instant, echelle, sens) : le niveau le plus prioritaire parmi ceux que la regle accepte.
    Renvoie des « candidates » au format de backtest.select (sim = resultat de la configuration de sortie `cfg`)."""
    best = {}
    for e in events:
        if not rule(e):
            continue
        s = e["sims"].get(cfg)
        if not s:
            continue
        k = (e["t"], e["tf"], e["dir"])
        if k not in best or e["rank"] < best[k]["rank"]:
            best[k] = e
    out = []
    for e in sorted(best.values(), key=lambda e: (e["t"], 0 if e["tf"] == "4h" else 1, e["rank"])):
        out.append({"t": e["t"], "side": "long" if e["dir"] > 0 else "short", "kind": e["type"], "etype": "marché", "key": f"{e['level']}|{e['tf']}", "score": 0.0,
                    "S": 0.0, "sim": e["sims"][cfg], "ev": e, "atr": e["atr"], "price": e["price"], "reg": e["reg"]})
    return out


def pick(events, cfg, rule, costs, start_ms, end_ms, cooldown_h: float = 6.0, max_open: int = 1):
    """Trades de la regle : une position a la fois, une meme configuration ne revient pas avant cooldown_h."""
    cands = as_candidates(events, cfg, rule)
    return bt.select(cands, lambda r: True, costs, max_week=999, zone_cooldown_h=cooldown_h, start_ms=start_ms, end_ms=end_ms)


# =====================================================================================================
#  Temoin : memes trades a des instants tires au hasard
# =====================================================================================================
def random_control_v(trades: list[dict], ds, cfg: str, costs: dict, start_ms: int, end_ms: int, runs: int = 60, seed: int = 3,
                     match_regime: bool = True, ma=None) -> dict:
    """Pour chaque trade de la strategie : un trade de MEME FORME (meme sens, memes distances de stop et d'objectifs en ATR, meme duree, memes frais)
    a une cloture horaire tiree au hasard, si possible dans la MEME tendance de fond. Repete `runs` fois : distribution de l'esperance obtenue par le hasard."""
    s_mode, t_mode, h_mode = cfg.split("|")
    hold, ext = {"H24": (24, 0), "H48": (48, 0), "H24x": (24, 48)}[h_mode]
    rnd = random.Random(seed)
    ma = ma or bt.regime_series(ds.b1h)
    geo = []
    for tr in trades:
        ev = tr["c"]["ev"]
        g = geometry(ev, s_mode, t_mode)
        if g is None:
            continue
        stop, tp1, tp2, part = g
        a, px, d = ev["atr"], ev["price"], ev["dir"]
        geo.append((d, abs(px - stop) / a, abs(tp1 - px) / a, (abs(tp2 - px) / a) if tp2 is not None else None, part, ev["reg"]))
    grid = list(range(((start_ms // HOUR) + 1) * HOUR, end_ms - 60 * HOUR, HOUR))
    exps = []
    for _ in range(runs):
        rs = []
        for d, sa, ta, t2a, part, reg in geo:
            t = rnd.choice(grid)
            if match_regime:
                for _try in range(60):
                    if bt.regime_at(ds, ma, t) == reg:
                        break
                    t = rnd.choice(grid)
            j = ds.b5.idx_at(t - 1)
            px, a = ds.b5.c[j], ds.atr_at(t)
            if a <= 0:
                continue
            sim = simulate_v(ds.b5, t, d, px - d * sa * a, px + d * ta * a, (px + d * t2a * a) if t2a is not None else None, part, hold, ext)
            if sim.get("filled"):
                rs.append(bt.net_r(sim, costs))
        if rs:
            exps.append(sum(rs) / len(rs))
    exps.sort()
    q = lambda p: exps[min(len(exps) - 1, int(p * len(exps)))] if exps else None
    return {"runs": len(exps), "expMean": sum(exps) / len(exps) if exps else None, "exp5": q(0.05), "exp95": q(0.95), "_exps": exps}
