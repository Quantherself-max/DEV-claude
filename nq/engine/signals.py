"""Moteur de SETUPS de scalping NQ. Module PUR.

Ce module lit ce que les autres moteurs mesurent déjà — barres + footprint, CVD (divergences, absorptions), profil de volume
(POC / VAH / VAL / HVN / LVN), VWAP et ses bandes, niveaux et zones de confluence, phase de séance — et en tire des SETUPS : des
configurations de scalping, chacune avec un sens (long / short), un **score 0..100**, la liste des ingrédients qui l'ont déclenchée,
un stop et des objectifs suggérés.

Rien ici n'est une promesse de gain. Chaque ingrédient est un fait observable ; le score est une **somme pondérée transparente** (les poids
sont dans `PARAMS`, à mesurer et ajuster avec le backtest) ; et les RÈGLES LUCID filtrent ou annulent le setup :
  - compte au plancher (`breached`) ou limite de perte journalière atteinte (`dllHit`) -> plus de setup ;
  - fenêtre de fermeture forcée (dernières minutes avant 16 h 45 ET) -> setup annulé (« trop tard pour un scalp ») ;
  - consistance en évaluation : si le gain du jour approche le plafond autorisé, le setup est signalé ;
  - micro-scalping : un setup dont l'objectif tient en quelques secondes est signalé (Lucid surveille au-delà de 50 % des gains).

Le but : des setups MESURABLES. Le backtest (`engine/backtest.py`) les rejoue sur l'historique et dit s'ils auraient passé l'évaluation,
touché le plancher, respecté la consistance — pour corréler la stratégie aux règles, comme demandé."""
import math
from dataclasses import dataclass, field, replace

from . import cvd as cvdmod
from .bars import atr
from .footprint import imbalances


@dataclass(frozen=True)
class Params:
    look: int = 60                       # barres regardées en arrière pour les divergences / swings
    min_score: float = 30.0              # score minimal pour qu'un setup soit émis
    edge_pts: float = 4.0                # « à » un niveau = à moins de edge_pts points
    band_sigma: float = 1.6              # bande VWAP considérée « étirée » à partir de ce nombre d'écarts-types
    stop_atr: float = 1.1                # stop = ce multiple de l'ATR au-delà du point d'invalidation...
    stop_min_ticks: int = 8              # ... avec un minimum
    stop_max_ticks: int = 60             # ... et un maximum (un scalp ne risque pas 20 points)
    flat_guard_min: int = 12             # pas de nouveau setup dans les N dernières minutes avant 16 h 45 ET
    micro_secs: int = 5                  # objectif atteignable en ≤ N s -> signalé « micro-scalping »
    imb_stack: int = 3                   # nb de prix consécutifs en déséquilibre pour une « pile »
    # poids des ingrédients (direction x force, additionnés) ; mesurés par backtest
    w: dict = field(default_factory=lambda: {
        "divergence": 26.0, "absorption": 22.0, "stack": 18.0, "va_edge": 16.0, "vwap_band": 14.0,
        "zone": 20.0, "ib_break": 18.0, "cvd_trend": 12.0, "phase": 8.0,
    })


PARAMS = Params()
_ACTIVE = {"open", "am", "pm", "power"}          # phases où un scalp a le plus de sens (volatilité + volume)
_DEAD = {"lunch", "asia", "break", "closed"}     # phases molles : on pénalise


def _dist_pts(a: float, b: float) -> float:
    return abs(a - b)


def _swing(bars, lo: bool, n: int = 2, back: int = 40):
    """Dernier plus-bas (lo=True) ou plus-haut local sur les `back` dernières barres (pivot confirmé par `n` barres de chaque côté)."""
    arr = [b.l for b in bars] if lo else [b.h for b in bars]
    j1 = len(arr) - n
    for j in range(j1 - 1, max(n, len(arr) - back) - 1, -1):
        x = arr[j]
        if lo and all(x <= arr[j + q] and x <= arr[j - q] for q in range(1, n + 1)):
            return x
        if not lo and all(x >= arr[j + q] and x >= arr[j - q] for q in range(1, n + 1)):
            return x
    return None


def _ingredients(bars, cvd_vals, prof, near, zones, inst, params):
    """Liste d'ingrédients actifs : chacun = (direction ±1, force 0..1, tag, texte). Lit la DERNIÈRE barre (bars[-1]) et son contexte."""
    out = []
    i = len(bars) - 1
    last = bars[-1]
    price = last.c
    tick = inst.tick

    # --- CVD : divergence prix / flux sur la fenêtre récente
    dname, dstr = cvdmod.divergence(bars, cvd_vals, i, look=params.look)
    if dname:
        out.append((1 if dname == "bull" else -1, min(1.0, 0.4 + dstr), "divergence",
                    f"Divergence {('haussière' if dname == 'bull' else 'baissière')} prix / CVD"))

    # --- CVD : absorption sur la dernière barre (gros delta contre le sens, volume fort)
    ab = cvdmod.absorption(bars, i)
    if ab:
        out.append((1 if ab == "bull" else -1, 0.8, "absorption",
                    f"Absorption {('acheteuse' if ab == 'bull' else 'vendeuse')} (le flux opposé est encaissé)"))

    # --- Footprint : piles de déséquilibres diagonaux sur la dernière barre
    if last.fp:
        im = imbalances(last.fp, stack=params.imb_stack)
        buy_st = sum(z - a + 1 for s, a, z in im["stacks"] if s > 0)
        sell_st = sum(z - a + 1 for s, a, z in im["stacks"] if s < 0)
        if buy_st or sell_st:
            d = 1 if buy_st >= sell_st else -1
            n = max(buy_st, sell_st)
            out.append((d, min(1.0, 0.45 + 0.12 * n), "stack",
                        f"Pile de {n} déséquilibre(s) {'acheteur' if d > 0 else 'vendeur'}(s) sur la dernière barre"))

    # --- CVD : pente récente (le flux pousse dans un sens)
    seg = [c for c in cvd_vals[max(0, i - 10):i + 1] if c is not None]
    if len(seg) >= 4:
        slope = seg[-1] - seg[0]
        v = sum(b.v for b in bars[max(0, i - 10):i + 1]) or 1.0
        s = max(-1.0, min(1.0, slope / v / 0.08))
        if abs(s) >= 0.25:
            out.append((1 if s > 0 else -1, min(1.0, abs(s)), "cvd_trend",
                        f"Flux cumulé orienté {'achat' if s > 0 else 'vente'} sur les dernières barres"))

    # --- Profil : rejet d'un bord de la zone de valeur (mean-reversion vers le POC)
    if prof:
        vah, val, poc = prof.get("vah"), prof.get("val"), prof.get("poc")
        if val is not None and price <= val + params.edge_pts and price >= val - 2 * params.edge_pts:
            out.append((1, 0.7, "va_edge", f"Prix au bord BAS de la zone de valeur (VAL {val:g}) : rejet possible vers le POC"))
        elif vah is not None and price >= vah - params.edge_pts and price <= vah + 2 * params.edge_pts:
            out.append((-1, 0.7, "va_edge", f"Prix au bord HAUT de la zone de valeur (VAH {vah:g}) : rejet possible vers le POC"))

    # --- VWAP : prix étiré sur une bande (fade vers le VWAP)
    if prof and prof.get("vwap") is not None and prof.get("sd"):
        m, sd = prof["vwap"], prof["sd"]
        if sd > 0:
            z = (price - m) / sd
            if z >= params.band_sigma:
                out.append((-1, min(1.0, (z - params.band_sigma) / 1.5 + 0.4), "vwap_band",
                            f"Prix à +{z:.1f} σ du VWAP ({m:.0f}) : étiré à la hausse"))
            elif z <= -params.band_sigma:
                out.append((1, min(1.0, (-z - params.band_sigma) / 1.5 + 0.4), "vwap_band",
                            f"Prix à {z:.1f} σ du VWAP ({m:.0f}) : étiré à la baisse"))

    # --- Zone de confluence très proche (réaction attendue) : oriente vers le rejet si le prix arrive dessus
    best = None
    for z in zones or []:
        d = abs(z["mid"] - price)
        if d <= params.edge_pts and (best is None or z["score"] > best["score"]):
            best = z
    if best:
        d = 1 if price <= best["mid"] else -1              # au-dessous d'une zone -> support (rejet haussier) ; au-dessus -> résistance
        out.append((d, min(1.0, 0.3 + best["score"] / 20.0), "zone",
                    f"Zone de confluence score {best['score']:g} à {best['mid']:.0f} ({', '.join(best['names'][:2])})"))

    return out


def _targets_from_levels(near, price, side, inst, prof):
    """Objectifs = niveaux réels dans le sens du trade (au-dessus pour un long), plus le POC/VWAP du profil. Triés par proximité, max 3."""
    cand = []
    arr = near.get("above" if side == "long" else "below", []) if near else []
    for x in arr:
        cand.append(x["price"])
    if prof:
        for k in ("poc", "vwap", "vah" if side == "long" else "val"):
            v = prof.get(k)
            if v is not None and ((side == "long" and v > price) or (side == "short" and v < price)):
                cand.append(round(v, 2))
    cand = sorted(set(round(c, 2) for c in cand), reverse=(side == "short"))
    cand = [c for c in cand if (c > price if side == "long" else c < price)]
    return cand[:3]


def _build_setup(side, ings, bars, prof, near, inst, a, params, atr_pts):
    """Assemble un setup directionnel : score, raisons, entrée, stop, objectifs. None si trop faible."""
    aligned = [g for g in ings if g[0] == (1 if side == "long" else -1)]
    against = [g for g in ings if g[0] == (-1 if side == "long" else 1)]
    if not aligned:
        return None
    raw = sum(params.w.get(tag, 0.0) * strength for _, strength, tag, _ in aligned)
    raw -= 0.6 * sum(params.w.get(tag, 0.0) * strength for _, strength, tag, _ in against)      # le flux contraire réduit la conviction
    tags = {g[2] for g in aligned}
    kind = "momentum" if ({"stack", "ib_break", "cvd_trend"} & tags) and not ({"va_edge", "vwap_band"} & tags) else "reversal"
    price = bars[-1].c
    tick = inst.tick

    # invalidation : pour un retournement, au-delà du dernier extrême ; pour un momentum, sous le dernier swing opposé
    swing = _swing(bars, lo=(side == "long"))
    buf = max(params.stop_min_ticks * tick, min(params.stop_max_ticks * tick, params.stop_atr * atr_pts))
    if side == "long":
        stop = (min(swing, price) if swing is not None else price) - buf
    else:
        stop = (max(swing, price) if swing is not None else price) + buf
    stop = inst.snap(stop)
    stop_pts = abs(price - stop)
    if stop_pts < tick:
        return None
    tgts = _targets_from_levels(near, price, side, inst, prof)
    if not tgts:                                   # pas de niveau : objectif à 1 R puis 2 R
        sgn = 1 if side == "long" else -1
        tgts = [inst.snap(price + sgn * stop_pts), inst.snap(price + sgn * 2 * stop_pts)]
    score = max(0.0, min(100.0, raw))
    first = tgts[0]
    rr = abs(first - price) / stop_pts if stop_pts > 0 else 0.0
    return {
        "side": side, "kind": kind, "score": round(score, 1), "entry": round(price, 2), "stop": round(stop, 2),
        "stopPts": round(stop_pts, 2), "targets": [round(t, 2) for t in tgts], "rr": round(rr, 2),
        "reasons": [{"tag": t, "dir": d, "strength": round(s, 2), "text": txt} for d, s, t, txt in sorted(aligned, key=lambda g: -params.w.get(g[2], 0) * g[1])],
        "against": [{"tag": t, "text": txt} for d, s, t, txt in against],
    }


def _ib_break(bars, near, price, inst, params, rth_started, out):
    """Ajoute un ingrédient de cassure de l'initial balance si un niveau IB est présent dans `near` et vient d'être franchi avec élan."""
    if not rth_started:
        return
    levels = (near.get("above") or []) + (near.get("below") or [])
    ib = {x["kind"]: x["price"] for x in levels if x["kind"] in ("ibh", "ibl")}
    if len(bars) < 3:
        return
    prev = bars[-2]
    if "ibh" in ib and prev.c <= ib["ibh"] < price and bars[-1].delta > 0:
        out.append((1, 0.75, "ib_break", f"Cassure de l'IB High ({ib['ibh']:.0f}) avec delta acheteur"))
    if "ibl" in ib and prev.c >= ib["ibl"] > price and bars[-1].delta < 0:
        out.append((-1, 0.75, "ib_break", f"Cassure de l'IB Low ({ib['ibl']:.0f}) avec delta vendeur"))


def evaluate(bars, cvd_vals, prof, near, zones, inst, now_ms, forced_flat_ms, phase, rth_started,
             acct=None, params: Params = PARAMS) -> dict:
    """Évalue les setups sur la DERNIÈRE barre de `bars`. Entrées déjà extraites (module pur, testable sans Market) :
      bars       : barres de la TF de signal (footprint utile sur la dernière), de la plus ancienne à la plus récente ;
      cvd_vals   : CVD aligné sur `bars` (même longueur ; None hors séance) ;
      prof       : vp.stats du profil actif (poc/vah/val/vwap/sd) ou None ;
      near       : levels.nearest {above, below} ; zones : levels.zones ;
      phase      : clock.phase(now) ; rth_started : la séance régulière a commencé.
    Renvoie {ready, price, atr, setups:[...], blocked:[raisons], ruleNotes:[...]}."""
    if len(bars) < 5 or prof is None:
        return {"ready": False, "setups": [], "blocked": ["pas assez de barres"], "ruleNotes": []}
    atr_pts = atr(bars[-30:]) or (inst.tick * 4)
    ings = _ingredients(bars, cvd_vals, prof, near, zones, inst, params)
    _ib_break(bars, near, bars[-1].c, inst, params, rth_started, ings)

    # pénalité / bonus de phase (n'oriente pas : module la conviction des deux côtés via un pseudo-ingrédient neutre)
    phase_key = phase.get("key")
    phase_factor = 1.0 if phase_key in _ACTIVE else (0.6 if phase_key in _DEAD else 0.85)

    setups = []
    for side in ("long", "short"):
        s = _build_setup(side, ings, bars, prof, near, inst, acct, params, atr_pts)
        if s:
            s["score"] = round(s["score"] * phase_factor, 1)
            setups.append(s)
    setups = [s for s in setups if s["score"] >= params.min_score]
    setups.sort(key=lambda s: -s["score"])
    # un seul sens à la fois : si les deux passent, on garde le plus fort et on note le conflit
    if len(setups) == 2:
        setups = setups[:1]
        setups[0]["conflict"] = True

    blocked, rule_notes = [], []
    mins_to_flat = (forced_flat_ms - now_ms) / 60_000 if forced_flat_ms else 999
    if acct:
        if acct.get("breached"):
            blocked.append("Compte au plancher : aucun trade.")
        if acct.get("dllHit"):
            blocked.append("Limite de perte journalière atteinte : plus de trade jusqu'à la séance suivante.")
    if 0 <= mins_to_flat <= params.flat_guard_min:
        blocked.append(f"Fermeture forcée dans {mins_to_flat:.0f} min (16 h 45 ET) : trop tard pour ouvrir un scalp.")
    elif mins_to_flat < 0:
        blocked.append("Après 16 h 45 ET : les positions sont fermées d'office, pas de nouveau trade.")
    if not rth_started and phase_key not in _ACTIVE:
        rule_notes.append("Hors séance régulière : volume faible, setups moins fiables.")

    if blocked:
        for s in setups:
            s["suppressed"] = True

    # règles Lucid attachées au meilleur setup (consistance, micro-scalping, palier de taille)
    if setups and acct and not blocked:
        s = setups[0]
        cons = acct.get("consistency") or {}
        if acct.get("stage") != "funded" and cons.get("todayCap") is not None and cons["todayCap"] > 0:
            s.setdefault("ruleNotes", []).append(
                f"Consistance : garde le gain du jour sous {cons['todayCap']:.0f} $ (meilleur jour ≤ {cons.get('pct', 50):.0f} % du total).")
        first_pts = abs(s["targets"][0] - s["entry"])
        if atr_pts > 0 and first_pts <= 0.5 * atr_pts:
            s.setdefault("ruleNotes", []).append(
                "Objectif très proche : s'il est tenu en quelques secondes, il compte dans le micro-scalping (Lucid surveille au-delà de 50 %).")
        caps = acct.get("caps") or {}
        if caps.get("next"):
            s.setdefault("ruleNotes", []).append(
                f"Compte financé : {caps['minis']} mini / {caps['micros']} micros au plus jusqu'à {caps['next']:.0f} $ de profit.")

    return {"ready": True, "price": round(bars[-1].c, 2), "atr": round(atr_pts, 2), "phase": phase.get("label"),
            "phaseFactor": round(phase_factor, 2), "setups": setups, "blocked": blocked, "ruleNotes": rule_notes,
            "ingredients": [{"dir": d, "strength": round(s, 2), "tag": t, "text": txt} for d, s, t, txt in ings]}
