"""Backtest de la strategie d'idees de trade (liquidite + VWAP / VWAP ancres / profils de volume + CVD), sur historique fin.

Principe (aucune triche sur l'avenir)
  1. GENERATION : toutes les 15 minutes, avec les seules donnees connues a cet instant, on reconstruit les niveaux (VWAP jour a
     annee et bandes, VWAP ancres sur les extremes, ouvertures, plus hauts / bas, profils de volume, POC nus), les poches de
     liquidite visibles dans le prix, les balayages, le CVD, puis on appelle EXACTEMENT le code des idees du terminal
     (signals.build_ideas / score_idea). Chaque idee candidate est enregistree avec ses mesures.
  2. SIMULATION : chaque candidate est jouee sur les bougies 1 MINUTE suivantes (ordre limite ou marche, stop, objectif 1 avec
     prise de la moitie puis stop a l'entree, objectif 2, sortie au bout de 72 h). Si stop et objectif sont dans la meme minute,
     le STOP est compte en premier. Les frais, le glissement sur les ordres au marche et le financement sont comptes apres.
  3. SELECTION : une regle (variante) choisit les trades dans l'ordre du temps, avec les memes contraintes que le terminal
     (une position a la fois, quota hebdomadaire, une zone ne revient pas avant 48 h).
  4. VERDICT : rendement compose a risque fixe, drawdown, facteur de profit, Sharpe, intervalle de confiance, comparaison a
     l'achat-conservation et a des TRADES AU HASARD de meme forme (memes distances en ATR, memes frais).
Les donnees d'entree sont des fine.Bars. Module PUR (aucun reseau)."""
import math
import random
import time
from bisect import bisect_left
from datetime import datetime, timezone

from . import cvd, fine, liqsweep, signals, sigtest
from .confluence import Level, find_zones
from .periods import NakedPocs, PeriodTracker

HOUR = 3_600_000
DAY = 86_400_000
DEC_MS = 900_000                 # une decision toutes les 15 minutes

DEFAULT_COSTS = {"maker": 0.0002, "taker": 0.0005, "slip": 0.0002, "funding8h": 0.0001}


def ms(y, m=1, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


# =====================================================================================================
#  Donnees
# =====================================================================================================
class Dataset:
    def __init__(self, b1: fine.Bars, b5: fine.Bars, b15: fine.Bars, b1h: fine.Bars, label: str = ""):
        self.b1, self.b5, self.b15, self.b1h, self.label = b1, b5, b15, b1h, label
        self._atr_h = None

    @classmethod
    def from_1m(cls, b1: fine.Bars, label: str = ""):
        return cls(b1, fine.resample(b1, 300_000), fine.resample(b1, 900_000), fine.resample(b1, HOUR), label)

    @classmethod
    def load(cls, folder: str, label: str = ""):
        L = lambda n: fine.Bars.load(f"{folder}/{n}.bin").build_cum()
        return cls(L("b1m"), L("b5m"), L("b15m"), L("b1h"), label)

    def atr_at(self, t_ms: float) -> float:
        """ATR (14 bougies 1 h) a l'instant t, avec les seules bougies 1 h deja FERMEES."""
        if self._atr_h is None:
            b = self.b1h
            a, out = 0.0, [0.0]
            for j in range(1, len(b)):
                pc = b.c[j - 1]
                tr = max(b.h[j] - b.l[j], abs(b.h[j] - pc), abs(b.l[j] - pc))
                a = tr if j < 14 else (a * 13 + tr) / 14
                out.append(a)
            self._atr_h = out
        j = self.b1h.idx_at(t_ms - 1)
        if j >= 0 and self.b1h.t[j] + HOUR > t_ms:
            j -= 1
        return self._atr_h[max(0, j)]


# =====================================================================================================
#  Simulation d'un trade sur bougies fines
# =====================================================================================================
def simulate(b: fine.Bars, t0: float, side: str, etype: str, entry: float, stop: float, tp1: float, tp2,
             valid_h: float = 48, hold_h: float = 72, partial: float = 0.5) -> dict:
    """Joue un ordre place a l'instant t0 sur les bougies fines b. Retourne le deroule SANS frais (voir net_r)."""
    n = len(b.t)
    i = bisect_left(b.t, t0)
    if i >= n:
        return {"result": "open", "filled": False}
    O, H, L, C, T = b.o, b.h, b.l, b.c, b.t
    per_h = HOUR / b.step
    long_ = side == "long"
    sgn = 1.0 if long_ else -1.0
    if etype == "marché":
        j, fp, entry_kind = i, O[i], "taker"
        if (stop - fp) * sgn >= 0 or (tp1 - fp) * sgn <= 0:
            return {"result": "cancel", "filled": False}
    else:
        end = min(n, i + int(valid_h * per_h))
        j = None
        for q in range(i, end):
            if long_:
                if L[q] <= entry:
                    j, fp = q, (O[q] if O[q] < entry else entry)
                    break
                if H[q] >= tp1:
                    return {"result": "missed", "filled": False}
            else:
                if H[q] >= entry:
                    j, fp = q, (O[q] if O[q] > entry else entry)
                    break
                if L[q] <= tp1:
                    return {"result": "missed", "filled": False}
        if j is None:
            return {"result": "nofill" if end - i >= valid_h * per_h - 1 else "open", "filled": False}
        entry_kind = "maker"
    risk = abs(fp - stop)
    if risk <= 0 or (stop - fp) * sgn >= 0:
        return {"result": "cancel", "filled": False}
    hold_end = min(n, j + int(hold_h * per_h))
    pos, stop_cur, tp1_done = 1.0, stop, False
    legs, mfe, mae, res, exit_q = [], 0.0, 0.0, None, hold_end - 1
    q = j
    while q < hold_end:
        hi, lo = H[q], L[q]
        fav, adv = ((hi - fp) / risk, (fp - lo) / risk) if long_ else ((fp - lo) / risk, (hi - fp) / risk)
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
        if (lo <= stop_cur) if long_ else (hi >= stop_cur):                          # le stop d'abord (prudent)
            px = min(O[q], stop_cur) if long_ else max(O[q], stop_cur)
            legs.append(("taker", pos, px))
            pos, exit_q, res = 0.0, q, ("tp1_be" if tp1_done else "stop")
            break
        if q > j:                                                                    # pas d'objectif dans la minute d'execution
            if not tp1_done and ((hi >= tp1) if long_ else (lo <= tp1)):
                legs.append(("maker", partial, tp1))
                pos -= partial
                tp1_done, stop_cur = True, fp                                          # stop a l'entree
                if (lo <= fp) if long_ else (hi >= fp):                              # meme minute : on suppose le retour a l'entree
                    legs.append(("taker", pos, fp))
                    pos, exit_q, res = 0.0, q, "tp1_be"
                    break
            if tp1_done and tp2 is not None and ((hi >= tp2) if long_ else (lo <= tp2)):
                legs.append(("maker", pos, tp2))
                pos, exit_q, res = 0.0, q, "tp2"
                break
        q += 1
    else:
        px = C[hold_end - 1]
        legs.append(("taker", pos, px))
        exit_q, res = hold_end - 1, ("tp1_to" if tp1_done else "timeout")
    r_gross = sum(f * (px - fp) * sgn for _, f, px in legs) / risk
    return {"result": res, "filled": True, "fill_t": int(T[j]), "exit_t": int(T[exit_q] + b.step), "fill_px": fp, "risk": risk,
            "r_gross": r_gross, "entry_kind": entry_kind, "legs": [(k, f) for k, f, _ in legs],
            "hours": (T[exit_q] + b.step - T[j]) / HOUR, "mfe": mfe, "mae": mae, "tp1": tp1_done}


def net_r(sim: dict, costs: dict) -> float:
    """Resultat en multiples du risque APRES frais, glissement (ordres au marche) et financement."""
    k = sim["fill_px"] / sim["risk"]                       # notionnel par unite de risque : le cout en R est k x taux
    taker = costs["taker"] + costs["slip"]
    c = k * (taker if sim["entry_kind"] == "taker" else costs["maker"])
    for kind, f in sim["legs"]:
        c += k * f * (taker if kind == "taker" else costs["maker"])
    c += k * costs["funding8h"] / 8.0 * sim["hours"] * (0.75 if sim["tp1"] else 1.0)
    return sim["r_gross"] - c


# =====================================================================================================
#  Etape 1 : generation des idees candidates (donnees connues a l'instant de la decision)
# =====================================================================================================
def _avwap_levels(ds: Dataset, i5: int, T: int, cache: dict):
    """VWAP ancres (somme cumulee : instantane) : extremes de 1 an / 3 mois (recalcules chaque jour), debut de l'annee et du
    mois precedents, et l'ancre fixe de l'utilisateur (2024-01-01)."""
    day = T // DAY
    if cache.get("day") != day:
        b = ds.b1h
        j1 = b.idx_at(T - 1)
        anchors = []
        for days, lab in ((365, "1 an"), (90, "3 mois")):
            j0 = max(0, j1 - days * 24)
            if j1 - j0 < 240:
                continue
            seg_l, seg_h = b.l[j0:j1], b.h[j0:j1]
            ml, mh = min(seg_l), max(seg_h)
            anchors.append((f"AVWAP bas {lab}", int(b.t[j0 + seg_l.index(ml)])))
            anchors.append((f"AVWAP haut {lab}", int(b.t[j0 + seg_h.index(mh)])))
        d = datetime.fromtimestamp(T / 1000, timezone.utc)
        anchors.append(("AVWAP année préc.", ms(d.year - 1)))
        m = d.year * 12 + d.month - 2
        anchors.append(("AVWAP mois préc.", ms(m // 12, m % 12 + 1)))
        anchors.append(("AVWAP 2024-01-01", ms(2024)))
        seen, out = set(), []
        for lab, a in anchors:
            if a not in seen and a < T - 6 * HOUR:
                seen.add(a)
                out.append((lab, a, ds.b5.idx(a)))
        cache["day"], cache["anchors"] = day, out
    res = []
    for lab, a, ia in cache["anchors"]:
        if ia < i5 - 12:
            vw, sd = ds.b5.vwap(ia, i5 + 1)
            if vw:
                res.append(Level(f"aVWAP:{a}|{lab}", lab, vw, f"aVWAP:{a}", "avwap", {"anchor": a, "sd": sd}))
    return res


def _to_zone_inputs(lvs, price, tol):
    zones = []
    for z, zz in enumerate(find_zones(lvs, tol)):
        inside = zz["lo"] <= price <= zz["hi"]
        zones.append({"id": f"z{z}", "mid": zz["mid"], "lo": zz["lo"], "hi": zz["hi"], "side": "in" if inside else ("above" if zz["mid"] > price else "below"),
                      "members": [m.id for m in zz["members"]], "groups": zz["groups"]})
    return zones


class Snapshot:
    """Tout ce que connait le terminal a l'instant de la decision (aucune donnee future). Passe a la fonction `decide` d'une strategie."""
    __slots__ = ("t", "price", "atr", "i5", "i15", "ds", "tr", "levels", "zones", "pools", "sweeps", "flow", "flow_score", "flow_notes",
                 "opts", "regime", "lvs", "cand15")


def ideas_decide(snap: Snapshot) -> list[dict]:
    """Strategie du terminal : exactement signals.build_ideas + signals.score_idea, puis mise en forme en candidates."""
    o, T, price = snap.opts, snap.t, snap.price
    ideas, _ = signals.build_ideas({"symbol": "BTC", "now": T, "price": price, "atr": snap.atr, "levels": snap.levels, "zones": snap.zones,
                                    "pools": snap.pools, "sweeps": snap.sweeps, "candles": snap.cand15, "opts": o})
    if not ideas:
        return []
    tr = snap.tr
    vw = {k: tr[k].acc.vwap()[0] for k in ("W", "M", "Y")}
    ctx = {"price": price, "vwap": vw, "flow": (snap.flow_score, snap.flow_notes), "macro": {}, "synth": {}, "dom": {}, "is_alt": False, "now": T}
    out = []
    for idea in ideas:
        key = "+".join(sorted(it["group"] for it in idea["st"]["items"]))
        sc = signals.score_idea(idea, ctx, o)
        cm = {x["key"]: x["pts"] for x in sc["comps"]}
        a = snap.flow
        out.append({"side": idea["side"], "kind": idea["kind"], "etype": idea["entryType"], "entry": idea["entry"], "stop": idea["stop"],
                    "tp1": idea["tp1"], "tp2": idea.get("tp2"), "rr1": idea["rr1"], "S": idea["st"]["S"], "n": idea["st"]["n"],
                    "htf": idea["st"]["htf"], "core": idea["st"]["core"], "score": sc["score"], "pts": cm, "gates": len(sc["gates"]),
                    "hold": len(sc["hold"]), "sweep": bool(idea["sweep"]), "pools": len(idea["pools"]), "near": len(idea.get("nearPools", [])),
                    "tp1Kind": idea.get("tp1Kind"), "key": key, "trend": sc["trend"], "imb4": a["imb4"], "div": a["div"], "absorb": a["absorb"],
                    "fs": snap.flow_score, "reg": snap.regime})
    return out


def generate(ds: Dataset, start_ms: int, end_ms: int, opts: dict | None = None, progress=None, min_pool_score: int = 60,
             decide=None, every_ms: int = DEC_MS, dedupe_h: float = 2.0, ma=None) -> list[dict]:
    """Candidates sur [start_ms, end_ms). Les bougies avant start_ms servent de rechauffement (profils, VWAP).
    `decide(snapshot) -> [ordre, ...]` : la strategie (par defaut celle du terminal). Un ordre est un dict avec au moins
    side ('long'|'short'), etype ('limite'|'marché'), entry, stop, tp1 (tp2 facultatif) et key (identifiant de la configuration : une meme
    configuration n'est pas rejouee avant dedupe_h)."""
    o = {**signals.DEFAULTS, **(opts or {})}
    decide = decide or ideas_decide
    ma = ma or regime_series(ds.b1h)
    tr = {k: PeriodTracker(k) for k in ("D", "W", "M", "Y")}
    nd, nw = NakedPocs(30), NakedPocs(12)
    cur_vp, av_cache = {}, {}
    pl = liqsweep.PriceLiquidity(ds.b1h)
    b5, b15 = ds.b5, ds.b15
    out, last_seen = [], {}
    n5 = len(b5.t)
    for i5 in range(n5):
        c = b5.candle(i5)
        pd, pw = tr["D"].prev, tr["W"].prev
        for t in tr.values():
            t.feed(c)
        if tr["D"].prev is not pd and tr["D"].prev:
            nd.on_rollover(tr["D"].prev["vp"]["poc"] if tr["D"].prev["vp"] else None, c.t)
        if tr["W"].prev is not pw and tr["W"].prev:
            nw.on_rollover(tr["W"].prev["vp"]["poc"] if tr["W"].prev["vp"] else None, c.t)
        nd.feed(c)
        nw.feed(c)
        T = c.t + 300_000
        if T >= end_ms:
            break
        if T < start_ms or T % every_ms:
            continue
        if progress and i5 % 20000 == 0:
            progress(min(0.99, (T - start_ms) / max(1, end_ms - start_ms)), "génération")
        price = c.c
        atr = ds.atr_at(T)
        if atr <= 0:
            continue
        lvs = sigtest._levels(tr, nd, nw, cur_vp, i5, price, T)
        lvs += _avwap_levels(ds, i5, T, av_cache)
        i15 = b15.idx_at(T - 1)
        ext = liqsweep.extremes_from_trackers(tr, T)
        pools = pl.pools(price, atr, T, ext)
        for k, p in enumerate(pools):
            lvs.append(Level(f"LIQ|{k}", f"Liq {'longs' if p['side'] == 'long' else 'shorts'}", p["price"], "LIQ", "liq", {"pool": p}))
        tol = max(0.30 * atr, 0.0015 * price)
        zones = _to_zone_inputs(lvs, price, tol)
        levels = [{"id": l.id, "name": l.name, "price": l.price, "group": l.group, "kind": l.kind, "pool": l.extra.get("pool"), "anchor": l.extra.get("anchor")}
                  for l in lvs]
        sw = liqsweep.detect_sweeps([p for p in pools if p["score"] >= min_pool_score], b15, i15, T, hours=o["sweep_hours"])
        a = cvd.analyse(b15, i15)
        fs, fnotes = cvd.flow(a)
        snap = Snapshot()
        snap.t, snap.price, snap.atr, snap.i5, snap.i15, snap.ds, snap.tr = T, price, atr, i5, i15, ds, tr
        snap.levels, snap.zones, snap.pools, snap.sweeps, snap.flow, snap.flow_score, snap.flow_notes = levels, zones, pools, sw, a, fs, fnotes
        snap.opts, snap.regime, snap.lvs, snap.cand15 = o, regime_at(ds, ma, T), lvs, b15.candles(i15 - 47, i15 + 1)
        for od in decide(snap) or []:
            key = od.get("key", "")
            if T - last_seen.get((od["side"], key), -1) < dedupe_h * HOUR:
                continue
            last_seen[(od["side"], key)] = T
            od.update(t=T, atr=atr, price=price)
            out.append(od)
    if progress:
        progress(1.0, "génération terminée")
    return out


def attach_outcomes(cands: list[dict], ds: Dataset, valid_h: float = 48, hold_h: float = 72, partial: float = 0.5, progress=None) -> None:
    """Joue chaque candidate seule (sans contrainte de position) sur les bougies 1 minute."""
    for k, r in enumerate(cands):
        r["sim"] = simulate(ds.b1, r["t"], r["side"], r["etype"], r["entry"], r["stop"], r["tp1"], r.get("tp2"), valid_h, hold_h, partial)
        if progress and k % 2000 == 0:
            progress(k / max(1, len(cands)), "simulation")


# =====================================================================================================
#  Regime de tendance (journalier) et trades « swing » qui le suivent
# =====================================================================================================
def regime_series(b1h: fine.Bars, fast_days: int = 50, slow_days: int = 200):
    """Moyennes mobiles simples sur cloture horaire (fast_days et slow_days en jours). Retourne (mm_rapide, mm_lente) alignees sur b1h ;
    la valeur a l'index j n'utilise que les bougies <= j (donc connue a la FERMETURE de la bougie j)."""
    out = []
    c = b1h.c
    for days in (fast_days, slow_days):
        n = days * 24
        arr = [None] * len(c)
        run = 0.0
        for j in range(len(c)):
            run += c[j]
            if j >= n:
                run -= c[j - n]
            if j >= n - 1:
                arr[j] = run / n
        out.append(arr)
    return out[0], out[1]


def regime_at(ds: "Dataset", ma, T: float) -> int:
    """+1 : clôture horaire fermée > les deux moyennes ; -1 : sous les deux ; 0 : entre les deux ou donnees insuffisantes."""
    j = ds.b1h.idx_at(T - 1)
    if j >= 0 and ds.b1h.t[j] + HOUR > T:
        j -= 1
    if j < 0 or ma[1][j] is None:
        return 0
    c = ds.b1h.c[j]
    if c > ma[0][j] and c > ma[1][j]:
        return 1
    if c < ma[0][j] and c < ma[1][j]:
        return -1
    return 0


def simulate_swing(ds: "Dataset", ma, t0: float, side: str, etype: str, entry: float, stop: float, tp1=None, valid_h: float = 48,
                   hold_days: float = 30, partial: float = 0.5, exit_on_regime: bool = True, b: fine.Bars | None = None) -> dict:
    """Trade qui dure jusqu'a ce que le regime casse : meme execution que simulate() (sur bougies 5 min par defaut), puis
    - stop initial ; si tp1 : prise de `partial` a tp1 et stop a l'entree ;
    - sortie au marche a l'ouverture suivant une cloture horaire qui repasse sous la moyenne rapide (long) / au-dessus (short) ;
    - sortie forcee apres hold_days."""
    b = b or ds.b5
    n = len(b.t)
    i = bisect_left(b.t, t0)
    if i >= n:
        return {"result": "open", "filled": False}
    O, H, L, C, T = b.o, b.h, b.l, b.c, b.t
    per_h = HOUR / b.step
    long_ = side == "long"
    sgn = 1.0 if long_ else -1.0
    if etype == "marché":
        j, fp, entry_kind = i, O[i], "taker"
        if (stop - fp) * sgn >= 0:
            return {"result": "cancel", "filled": False}
    else:
        end = min(n, i + int(valid_h * per_h))
        j = None
        for q in range(i, end):
            if long_:
                if L[q] <= entry:
                    j, fp = q, (O[q] if O[q] < entry else entry)
                    break
            elif H[q] >= entry:
                j, fp = q, (O[q] if O[q] > entry else entry)
                break
        if j is None:
            return {"result": "nofill" if end - i >= valid_h * per_h - 1 else "open", "filled": False}
        entry_kind = "maker"
    risk = abs(fp - stop)
    if risk <= 0 or (stop - fp) * sgn >= 0:
        return {"result": "cancel", "filled": False}
    hold_end = min(n, j + int(hold_days * 24 * per_h))
    pos, stop_cur, tp1_done = 1.0, stop, False
    legs, mfe, mae, res, exit_q = [], 0.0, 0.0, None, hold_end - 1
    b1h, fast = ds.b1h, ma[0]
    per_bar_h = max(1, int(HOUR // b.step))
    q = j
    while q < hold_end:
        hi, lo = H[q], L[q]
        fav, adv = ((hi - fp) / risk, (fp - lo) / risk) if long_ else ((fp - lo) / risk, (hi - fp) / risk)
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
        if (lo <= stop_cur) if long_ else (hi >= stop_cur):
            px = min(O[q], stop_cur) if long_ else max(O[q], stop_cur)
            legs.append(("taker", pos, px))
            pos, exit_q, res = 0.0, q, ("stop_be" if tp1_done else "stop")
            break
        if q > j and tp1 is not None and not tp1_done and ((hi >= tp1) if long_ else (lo <= tp1)):
            legs.append(("maker", partial, tp1))
            pos -= partial
            tp1_done, stop_cur = True, fp
            if (lo <= fp) if long_ else (hi >= fp):
                legs.append(("taker", pos, fp))
                pos, exit_q, res = 0.0, q, "tp1_be"
                break
        # cloture horaire : la bougie 5 min q est la derniere de son heure ?
        if exit_on_regime and (T[q] + b.step) % HOUR == 0:
            jh = b1h.idx_at(T[q])
            if jh >= 0 and fast[jh] is not None:
                ch = b1h.c[jh]
                if (ch < fast[jh]) if long_ else (ch > fast[jh]):
                    nq = q + 1
                    if nq < hold_end:
                        legs.append(("taker", pos, O[nq]))
                        pos, exit_q, res = 0.0, nq, "regime"
                        break
        q += 1
    else:
        legs.append(("taker", pos, C[hold_end - 1]))
        exit_q, res = hold_end - 1, "timeout"
    r_gross = sum(f * (px - fp) * sgn for _, f, px in legs) / risk
    return {"result": res, "filled": True, "fill_t": int(T[j]), "exit_t": int(T[exit_q] + b.step), "fill_px": fp, "risk": risk,
            "r_gross": r_gross, "entry_kind": entry_kind, "legs": [(k, f) for k, f, _ in legs],
            "hours": (T[exit_q] + b.step - T[j]) / HOUR, "mfe": mfe, "mae": mae, "tp1": tp1_done}


# =====================================================================================================
#  Etape 3 : selection par une regle, puis metriques
# =====================================================================================================
def select(cands: list[dict], rule, costs: dict, max_week: int = 5, thr: float | None = None, zone_cooldown_h: float = 48,
           start_ms: int = 0, end_ms: int = 2 ** 62, sim_key: str = "sim") -> list[dict]:
    """Trades retenus par `rule`, dans l'ordre du temps : une position a la fois (un ordre en attente compte), quota hebdomadaire
    (la derniere place exige +8 points si la regle est un seuil de score), une zone ne revient pas avant zone_cooldown_h."""
    chosen, busy_until, wk_count, zone_seen = [], 0, {}, {}
    for r in cands:
        t = r["t"]
        if t < start_ms or t >= end_ms or t < busy_until or not rule(r):
            continue
        sim = r.get(sim_key)
        if not sim or sim["result"] == "open":
            continue
        wk = (t // DAY + 3) // 7
        used = wk_count.get(wk, 0)
        if used >= max_week or (thr is not None and used == max_week - 1 and r["score"] < thr + 8):
            continue
        zk = (r["side"], r["key"])
        if t - zone_seen.get(zk, -1) < zone_cooldown_h * HOUR:
            continue
        zone_seen[zk] = t
        wk_count[wk] = used + 1
        if sim["filled"]:
            busy_until = sim["exit_t"]
            rn = net_r(sim, costs)
            chosen.append({"t": t, "fill_t": sim["fill_t"], "exit_t": sim["exit_t"], "side": r["side"], "kind": r["kind"], "etype": r["etype"], "score": r["score"], "S": r["S"],
                           "r": rn, "r_gross": sim["r_gross"], "result": sim["result"], "mae": sim["mae"], "mfe": sim["mfe"], "stop_pct": sim["risk"] / sim["fill_px"],
                           "hours": sim["hours"], "px": sim["fill_px"], "c": r})
        else:
            busy_until = t + (48 * HOUR if sim["result"] == "nofill" else 0)          # un ordre non execute bloque jusqu'a son expiration
    return chosen


def metrics(trades: list[dict], start_ms: int, end_ms: int, risk_pct: float = 0.01, max_lev: float = 10.0, seed: int = 11) -> dict:
    """Metriques d'une liste de trades (r = resultat net en multiples du risque). Rendement compose a risque fixe."""
    days = max(1.0, (end_ms - start_ms) / DAY)
    m = {"n": len(trades), "days": days}
    if not trades:
        return {**m, "winRate": None, "expR": None, "pf": None, "ret": 0.0, "cagr": 0.0, "maxDD": 0.0, "sharpe": None, "perWeek": 0.0}
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    m["winRate"] = len(wins) / len(rs)
    m["expR"] = sum(rs) / len(rs)
    m["medR"] = sorted(rs)[len(rs) // 2]
    m["pf"] = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else None
    m["avgWin"] = sum(wins) / len(wins) if wins else 0.0
    m["avgLoss"] = sum(losses) / len(losses) if losses else 0.0
    eq, peak, dd = 1.0, 1.0, 0.0
    pts = [(start_ms, 1.0)]
    for t in sorted(trades, key=lambda x: x["exit_t"]):
        eff = min(risk_pct, max_lev * t["stop_pct"])
        low = eq * (1.0 - eff * min(t["mae"], max(1.0, -t["r"])))             # point bas pendant le trade (excursion adverse)
        dd = max(dd, (peak - low) / peak)
        eq *= max(0.0, 1.0 + eff * t["r"])
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        pts.append((t["exit_t"], eq))
    m["ret"] = eq - 1.0
    m["cagr"] = eq ** (365.0 / days) - 1.0 if eq > 0 else -1.0
    m["maxDD"] = dd
    m["exposure"] = sum(t["hours"] for t in trades) * HOUR / (end_ms - start_ms)
    m["perWeek"] = len(trades) / (days / 7.0)
    # Sharpe annualise sur les rendements quotidiens (equity realisee)
    daily, j, last, d0 = [], 0, 1.0, start_ms // DAY
    for d in range(d0, int(end_ms // DAY)):
        end = (d + 1) * DAY
        while j < len(pts) and pts[j][0] <= end:
            last = pts[j][1]
            j += 1
        daily.append(last)
    rets = [daily[k] / daily[k - 1] - 1.0 for k in range(1, len(daily))]
    if len(rets) > 5:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (len(rets) - 1))
        m["sharpe"] = mu / sd * math.sqrt(365) if sd > 0 else None
    else:
        m["sharpe"] = None
    # intervalle de confiance a 90 % de l'esperance (rééchantillonnage des trades)
    rnd = random.Random(seed)
    if len(rs) >= 10:
        means = sorted(sum(rnd.choice(rs) for _ in rs) / len(rs) for _ in range(1500))
        m["expLo"], m["expHi"] = means[int(0.05 * len(means))], means[int(0.95 * len(means))]
        sd = math.sqrt(sum((x - m["expR"]) ** 2 for x in rs) / (len(rs) - 1))
        m["tstat"] = m["expR"] / (sd / math.sqrt(len(rs))) if sd > 0 else None
    m["equity"] = [(int(a), round(b, 5)) for a, b in pts[:: max(1, len(pts) // 400)]]
    return m


def buy_hold(ds: Dataset, start_ms: int, end_ms: int) -> dict:
    b = ds.b1h
    i0, i1 = b.idx(start_ms), b.idx(end_ms) - 1
    if i1 <= i0:
        return {}
    peak, dd = b.c[i0], 0.0
    for j in range(i0, i1 + 1):
        peak = max(peak, b.c[j])
        dd = max(dd, (peak - b.l[j]) / peak)
    days = (end_ms - start_ms) / DAY
    r = b.c[i1] / b.c[i0] - 1.0
    return {"ret": r, "cagr": (1 + r) ** (365.0 / days) - 1.0, "maxDD": dd}


# =====================================================================================================
#  Temoin : trades au hasard de meme forme
# =====================================================================================================
def random_control(trades_cands: list[dict], ds: Dataset, costs: dict, start_ms: int, end_ms: int, runs: int = 150, seed: int = 3,
                   valid_h: float = 48, hold_h: float = 72, partial: float = 0.5, match_regime: bool = False, ma=None) -> dict:
    """Pour chaque trade de la strategie : un trade de MEME FORME (meme sens, memes distances d'entree / stop / objectifs en ATR,
    meme type d'ordre, memes frais) place a un instant tire au hasard. Repete `runs` fois : distribution de l'esperance et du
    taux de reussite obtenus par le hasard seul."""
    rnd = random.Random(seed)
    grid = list(range(((start_ms // DEC_MS) + 1) * DEC_MS, end_ms - 80 * HOUR, DEC_MS))
    geo = []
    for r in trades_cands:
        a = r["atr"]
        sg = 1.0 if r["side"] == "long" else -1.0
        geo.append((r["side"], r["etype"], (r["price"] - r["entry"]) * sg / a, (r["entry"] - r["stop"]) * sg / a, (r["tp1"] - r["entry"]) * sg / a,
                    ((r["tp2"] - r["entry"]) * sg / a) if r.get("tp2") else None))
    exps, wins = [], []
    if match_regime:
        ma = ma or regime_series(ds.b1h)
        want = [r.get("reg") for r in trades_cands]                                      # tendance vecue par la vraie idee
    for _ in range(runs):
        rs = []
        for q, (side, etype, de, sd, t1, t2) in enumerate(geo):
            t = rnd.choice(grid)
            if match_regime and want[q] in (-1, 0, 1):
                for _try in range(60):                                                  # instant tire dans la MEME tendance de fond
                    if regime_at(ds, ma, t) == want[q]:
                        break
                    t = rnd.choice(grid)
            j = ds.b5.idx_at(t - 1)
            price, a = ds.b5.c[j], ds.atr_at(t)
            if a <= 0:
                continue
            sg = 1.0 if side == "long" else -1.0
            entry = price if etype == "marché" else price - sg * de * a
            sim = simulate(ds.b1, t, side, etype, entry, entry - sg * sd * a, entry + sg * t1 * a, (entry + sg * t2 * a) if t2 is not None else None, valid_h, hold_h, partial)
            if sim and sim.get("filled"):
                rs.append(net_r(sim, costs))
        if rs:
            exps.append(sum(rs) / len(rs))
            wins.append(sum(1 for x in rs if x > 0) / len(rs))
    exps.sort()
    wins.sort()
    q = lambda arr, p: arr[min(len(arr) - 1, int(p * len(arr)))] if arr else None
    return {"runs": len(exps), "expMean": sum(exps) / len(exps) if exps else None, "exp5": q(exps, 0.05), "exp95": q(exps, 0.95), "winMean": sum(wins) / len(wins) if wins else None,
            "_exps": exps}


def percentile_of(exps: list[float], x: float) -> float:
    """Part des essais au hasard qui font MIEUX que x (p-value unilaterale)."""
    return sum(1 for v in exps if v >= x) / len(exps) if exps else 1.0
