"""Mesures de performance d'un backtest et simulation de Monte Carlo (V45).

Entrées : les rendements par trade en FRACTION du capital (0.012 = +1,2 %), dans l'ordre de leur sortie, et, pour les mesures en temps,
les points de la courbe de capital [(heure ms, capital)]. Ce sont des statistiques (moyennes, écarts-types, racines carrées) : elles
sont calculées en flottants 64 bits, ce qui est la pratique normale ; les montants, eux, sont en décimal (quant.perp).

  Sharpe   = moyenne / écart-type des rendements périodiques × √(périodes par an)      (écart-type d'échantillon, taux sans risque 0)
  Sortino  = moyenne / écart-type des seuls rendements NÉGATIFS × √(périodes par an)   (écart vers le bas : √(moyenne de min(r, 0)²))
  Calmar   = rendement annualisé composé / drawdown maximal
  Facteur de profit = gains bruts / pertes brutes
  Espérance = moyenne des résultats par trade (en R ou en fraction) ; aussi décomposée : taux de réussite × gain moyen - taux d'échec
              × perte moyenne
  Drawdown maximal : plus forte baisse depuis un sommet, en % ; et sa DURÉE : plus long temps passé sous un sommet (du sommet au
              retour à ce niveau, ou jusqu'à la fin si le capital n'y est pas revenu)
  MAE / MFE : excursion adverse / favorable maximale de chaque trade, en multiples du risque
Monte Carlo : l'ordre des trades est tiré au hasard N fois (1 000 par défaut). Deux modes :
  « shuffle »    les mêmes trades dans un autre ordre (permutation) : le capital final est le même, c'est le CHEMIN (donc le drawdown)
                 qui change ; répond à « ai-je eu de la chance sur l'ordre ? » ;
  « bootstrap »  tirage avec remise : certains trades reviennent, d'autres manquent ; le capital final change aussi ; répond à « et si
                 l'avenir ressemblait à un autre échantillon des mêmes trades ? ».
  Ruine = le capital tombe au moins une fois sous (1 - seuil) du capital de départ (seuil 50 % par défaut). La probabilité est donnée
  avec son intervalle de confiance de Wilson à 95 %.
Module PUR ; le hasard vient d'un générateur à graine fixe (résultat reproductible)."""
from __future__ import annotations
import math
import random

DAY_MS = 86_400_000
Z95 = 1.959963984540054


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def quantile(sorted_xs: list, p: float):
    """Quantile par interpolation linéaire (définition 7 de Hyndman et Fan, celle de numpy par défaut)."""
    n = len(sorted_xs)
    if not n:
        return None
    h = (n - 1) * p
    lo = int(math.floor(h))
    hi = min(n - 1, lo + 1)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (h - lo)


def wilson(k: int, n: int, z: float = Z95):
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - half), min(1.0, c + half)


def sharpe(rets: list, per_year: float = 365.0):
    sd = _std(rets)
    return _mean(rets) / sd * math.sqrt(per_year) if sd > 0 else None


def sortino(rets: list, per_year: float = 365.0, target: float = 0.0):
    if not rets:
        return None
    down = math.sqrt(sum(min(r - target, 0.0) ** 2 for r in rets) / len(rets))
    return (_mean(rets) - target) / down * math.sqrt(per_year) if down > 0 else None


def drawdown(points: list) -> dict:
    """points = [(heure ms, capital)] triés. Renvoie maxDD (fraction), heures du sommet et du creux, durée sous l'eau la plus longue (ms),
    si le dernier sommet a été retrouvé, et le drawdown en cours."""
    if not points:
        return {"maxDD": 0.0, "peakT": None, "troughT": None, "longestMs": 0, "recovered": True, "current": 0.0}
    peak, peak_t = points[0][1], points[0][0]
    max_dd, dd_peak_t, dd_trough_t = 0.0, peak_t, peak_t
    longest, under_since = 0, None
    for t, eq in points:
        if eq >= peak:
            if under_since is not None:
                longest = max(longest, t - under_since)
                under_since = None
            peak, peak_t = eq, t
        else:
            if under_since is None:
                under_since = peak_t
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd, dd_peak_t, dd_trough_t = dd, peak_t, t
    recovered = under_since is None
    if not recovered:
        longest = max(longest, points[-1][0] - under_since)
    last = points[-1][1]
    return {"maxDD": max_dd, "peakT": dd_peak_t, "troughT": dd_trough_t, "longestMs": longest, "recovered": recovered,
            "current": (peak - last) / peak if peak > 0 else 0.0}


def equity_points(trades: list, start_ms: int, start_equity: float = 1.0) -> list:
    """Courbe de capital composée : trades = [(heure de sortie ms, rendement en fraction)], triés par heure."""
    eq, pts = start_equity, [(start_ms, start_equity)]
    for t, r in sorted(trades):
        eq *= max(0.0, 1.0 + r)
        pts.append((t, eq))
    return pts


def daily_returns(points: list, start_ms: int, end_ms: int) -> list:
    """Rendement de chaque jour UTC entier entre start et end, à partir de la courbe de capital réalisée."""
    daily, j, last = [], 0, points[0][1] if points else 1.0
    for d in range(start_ms // DAY_MS, int(end_ms // DAY_MS)):
        end = (d + 1) * DAY_MS
        while j < len(points) and points[j][0] <= end:
            last = points[j][1]
            j += 1
        daily.append(last)
    return [daily[k] / daily[k - 1] - 1.0 for k in range(1, len(daily)) if daily[k - 1] > 0]


def trade_stats(rs: list) -> dict:
    """rs = résultats par trade (R ou fraction). Taux de réussite, espérance, facteur de profit, gain et perte moyens, plus longues
    séries. Un résultat nul compte comme une perte (prudent)."""
    n = len(rs)
    if not n:
        return {"n": 0, "winRate": None, "expectancy": None, "profitFactor": None, "avgWin": None, "avgLoss": None, "payoff": None,
                "maxWinStreak": 0, "maxLossStreak": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gl = -sum(losses)
    w = l = mw = ml = 0
    for r in rs:
        if r > 0:
            w, l = w + 1, 0
        else:
            w, l = 0, l + 1
        mw, ml = max(mw, w), max(ml, l)
    aw, al = _mean(wins), _mean(losses)
    return {"n": n, "winRate": len(wins) / n, "expectancy": _mean(rs), "profitFactor": sum(wins) / gl if gl > 0 else None,
            "avgWin": aw if wins else None, "avgLoss": al if losses else None, "payoff": aw / -al if wins and losses and al < 0 else None,
            "maxWinStreak": mw, "maxLossStreak": ml, "median": quantile(sorted(rs), 0.5), "std": _std(rs),
            "tstat": _mean(rs) / (_std(rs) / math.sqrt(n)) if n > 1 and _std(rs) > 0 else None}


def excursions(trades: list) -> dict:
    """trades = [{"r", "mae", "mfe"}] en multiples du risque. Excursions moyennes et médianes, pour les gagnants et les perdants :
    le MAE des gagnants dit de combien un bon trade recule avant de partir (place du stop) ; le MFE des perdants, ce qu'un trade perdant
    a offert avant de se retourner (place de l'objectif). Rapport d'avantage = MFE moyen / MAE moyen."""
    if not trades:
        return {"n": 0}
    out = {"n": len(trades)}
    for name, sel in (("all", trades), ("winners", [t for t in trades if t["r"] > 0]), ("losers", [t for t in trades if t["r"] <= 0])):
        mae = sorted(t["mae"] for t in sel)
        mfe = sorted(t["mfe"] for t in sel)
        out[name] = {"n": len(sel), "maeMean": _mean(mae) if sel else None, "maeMedian": quantile(mae, 0.5), "mae90": quantile(mae, 0.9),
                     "mfeMean": _mean(mfe) if sel else None, "mfeMedian": quantile(mfe, 0.5), "mfe90": quantile(mfe, 0.9)}
    a = out["all"]
    out["edgeRatio"] = a["mfeMean"] / a["maeMean"] if a["maeMean"] else None
    return out


def cagr(final_equity: float, days: float):
    if final_equity <= 0 or days <= 0:
        return -1.0
    return final_equity ** (365.0 / days) - 1.0


def monte_carlo(rets: list, n: int = 1000, mode: str = "shuffle", ruin: float = 0.5, seed: int = 45, dd_levels=(0.1, 0.2, 0.3, 0.5)) -> dict:
    """Voir l'en-tête. rets = rendements par trade en fraction du capital. Renvoie la distribution du drawdown maximal (quantiles 5, 25,
    50, 75, 95, 99 %), du capital final, la probabilité de ruine avec son intervalle de Wilson, et la probabilité de dépasser chaque
    niveau de drawdown."""
    if mode not in ("shuffle", "bootstrap"):
        raise ValueError("mode : shuffle ou bootstrap")
    m = len(rets)
    if m < 2 or n < 1:
        return {"runs": 0, "mode": mode, "trades": m}
    rnd = random.Random(seed)
    floor = 1.0 - ruin
    dds, finals, ruined = [], [], 0
    seq = list(rets)
    for _ in range(n):
        if mode == "shuffle":
            rnd.shuffle(seq)
            run = seq
        else:
            run = [rets[rnd.randrange(m)] for _ in range(m)]
        eq = peak = 1.0
        dd = 0.0
        hit = False
        for r in run:
            eq *= max(0.0, 1.0 + r)
            if eq > peak:
                peak = eq
            elif peak > 0:
                d = 1.0 - eq / peak
                if d > dd:
                    dd = d
            if eq <= floor:
                hit = True
        dds.append(dd)
        finals.append(eq)
        ruined += hit
    dds.sort()
    finals.sort()
    lo, hi = wilson(ruined, n)
    q = lambda xs: {str(int(p * 100)): quantile(xs, p) for p in (0.05, 0.25, 0.5, 0.75, 0.95, 0.99)}
    return {"runs": n, "mode": mode, "trades": m, "ruinLevel": ruin, "ruin": ruined / n, "ruinLo": lo, "ruinHi": hi,
            "dd": q(dds), "ddMean": _mean(dds), "final": q(finals), "finalMean": _mean(finals),
            "ddOver": {str(int(x * 100)): sum(1 for d in dds if d >= x) / n for x in dd_levels}}


def report(trades: list, start_ms: int, end_ms: int, mc_runs: int = 1000, ruin: float = 0.5, seed: int = 45) -> dict:
    """Toutes les mesures d'une liste de trades : [{"exit_t", "ret" (fraction du capital), "r" (multiples du risque), "mae", "mfe"}]."""
    days = max(1.0, (end_ms - start_ms) / DAY_MS)
    order = sorted(trades, key=lambda t: t["exit_t"])
    rets = [t["ret"] for t in order]
    pts = equity_points([(t["exit_t"], t["ret"]) for t in order], start_ms)
    dd = drawdown(pts + [(end_ms, pts[-1][1])])
    daily = daily_returns(pts, start_ms, end_ms)
    final = pts[-1][1]
    g = cagr(final, days)
    out = {"n": len(order), "days": days, "ret": final - 1.0, "cagr": g, "maxDD": dd["maxDD"], "ddDays": dd["longestMs"] / DAY_MS,
           "ddRecovered": dd["recovered"], "ddPeakT": dd["peakT"], "ddTroughT": dd["troughT"],
           "sharpe": sharpe(daily) if len(daily) > 5 else None, "sortino": sortino(daily) if len(daily) > 5 else None,
           "calmar": g / dd["maxDD"] if dd["maxDD"] > 0 else None,
           "r": trade_stats([t["r"] for t in order]), "excursions": excursions(order),
           "mcShuffle": monte_carlo(rets, mc_runs, "shuffle", ruin, seed), "mcBootstrap": monte_carlo(rets, mc_runs, "bootstrap", ruin, seed + 1)}
    return out
