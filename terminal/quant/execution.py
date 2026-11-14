"""Coûts d'exécution réalistes d'un backtest : frais, glissement dynamique, financement réel (V45).

- Frais : taux « maker » (ordre limite qui attend dans le carnet) et « taker » (ordre au marché, stop), réglables.
- Glissement d'un ordre au marché, en fraction du prix :
      glissement = base + k_vol × (ATR d'une minute / prix) + bande × notionnel / (2 × profondeur dans la bande)
    base    : la moitié de l'écart achat-vente habituel ;
    k_vol   : part du mouvement typique d'une minute perdue à l'exécution : plus le marché est agité (stop touché dans une cascade),
              plus l'exécution est mauvaise ;
    impact  : carnet supposé de densité constante dans la bande : exécuter un notionnel N contre une profondeur P dans une bande b
              déplace le prix de b × N / P, soit b × N / (2 P) en moyenne sur l'ordre. Sans profondeur connue, ce terme est nul et le
              rapport le dit.
  Ce modèle est une HYPOTHÈSE annoncée, pas une mesure : aucune formule ne remplace le carnet réel de l'instant.
- Financement : la somme des taux RÉELLEMENT publiés par la bourse aux échéances (00 h, 08 h, 16 h UTC chez Binance) traversées par la
  position. Un long PAIE un taux positif, un short le REÇOIT (et l'inverse pour un taux négatif) : le signe compte.
Les résultats de backtest sont en multiples du risque (R) sur des bougies : flottants 64 bits (voir quant.metrics). Module PUR."""
from __future__ import annotations
from bisect import bisect_right

DEFAULT = {"maker": 0.0002, "taker": 0.0005, "slip_base": 0.00005, "slip_vol": 0.10, "impact_band": 0.001}


class FundingSeries:
    """Taux de financement publiés : [(heure ms, taux)]. `between(t0, t1)` : somme des taux des échéances t0 < t <= t1 et leur nombre.
    `covers(t0, t1)` : vrai si la série couvre toute la période (sinon le backtest garde le taux constant et le dit)."""

    def __init__(self, events, period_ms: int = 8 * 3_600_000):
        ev = sorted((int(t), float(r)) for t, r in events)
        self.t = [t for t, _ in ev]
        self.cum = [0.0]
        for _, r in ev:
            self.cum.append(self.cum[-1] + r)
        self.period = period_ms

    def __len__(self):
        return len(self.t)

    def between(self, t0: int, t1: int):
        a, b = bisect_right(self.t, t0), bisect_right(self.t, t1)
        return self.cum[b] - self.cum[a], b - a

    def covers(self, t0: int, t1: int) -> bool:
        return bool(self.t) and self.t[0] <= t0 + self.period and self.t[-1] >= t1 - self.period

    def mean(self):
        return self.cum[-1] / len(self.t) if self.t else None


def slippage(costs: dict, atr_frac: float | None = None, notional: float | None = None, depth: float | None = None) -> float:
    """Glissement (fraction du prix) d'un ordre au marché. atr_frac = ATR d'une minute / prix à l'instant de l'ordre."""
    if "slip_base" not in costs:
        return float(costs.get("slip", 0.0))                           # ancien modèle : glissement fixe
    s = costs["slip_base"]
    if atr_frac is not None and atr_frac > 0:
        s += costs.get("slip_vol", 0.0) * atr_frac
    depth = depth if depth is not None else costs.get("depth_usd")
    notional = notional if notional is not None else costs.get("notional_usd")
    if depth and notional and depth > 0:
        s += costs.get("impact_band", 0.001) * notional / (2.0 * depth)
    return s


def funding_r(sim: dict, costs: dict, k: float) -> tuple:
    """Coût de financement d'un trade simulé, en multiples du risque (positif = payé), et son origine ('réel' ou 'constant').
    k = notionnel par unité de risque (prix d'entrée / distance au stop). La position est entière jusqu'à l'objectif 1, puis réduite de
    la part vendue."""
    sgn = 1.0 if sim.get("side", "long") == "long" else -1.0
    rest = 1.0 - sim.get("partial", 0.0) if sim.get("tp1") else 1.0
    series = costs.get("funding")
    t0, t1 = sim.get("fill_t"), sim.get("exit_t")
    if series is not None and t0 is not None and t1 is not None and series.covers(t0, t1):
        tp1_t = sim.get("tp1_t")
        if sim.get("tp1") and tp1_t is not None:
            a, _ = series.between(t0, tp1_t)
            b, _ = series.between(tp1_t, t1)
            rate = a + rest * b
        else:
            rate, _ = series.between(t0, t1)
        return k * sgn * rate, "réel"
    # sans série : taux constant par 8 heures, payé par les longs et REÇU par les shorts
    hours = sim.get("hours", 0.0)
    share = (0.5 * (1.0 + rest)) if sim.get("tp1") else 1.0
    return k * sgn * costs.get("funding8h", 0.0) / 8.0 * hours * share, "constant"


def net_r(sim: dict, costs: dict) -> dict:
    """Résultat net d'un trade simulé (engine.backtest.simulate) : brut - frais - glissement - financement, en R, avec le détail."""
    k = sim["fill_px"] / sim["risk"]
    fees = slip = 0.0
    if sim["entry_kind"] == "taker":
        fees += k * costs["taker"]
        slip += k * slippage(costs, sim.get("atr_in"))
    else:
        fees += k * costs["maker"]
    for kind, f in sim["legs"]:
        if kind == "taker":
            fees += k * f * costs["taker"]
            slip += k * f * slippage(costs, sim.get("atr_out"))
        else:
            fees += k * f * costs["maker"]
    fund, origin = funding_r(sim, costs, k)
    return {"net": sim["r_gross"] - fees - slip - fund, "gross": sim["r_gross"], "fees": fees, "slip": slip, "funding": fund,
            "fundingFrom": origin}
