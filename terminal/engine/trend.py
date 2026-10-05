"""Tendance de fond : position du cours face aux moyennes mobiles de 50 et 200 jours (calculees sur les clotures horaires).

  +1 (haussiere)  : le cours est au-dessus des DEUX moyennes ;
  -1 (baissiere)  : le cours est sous les DEUX moyennes ;
   0 (indecise)   : entre les deux.

Pourquoi c'est dans le terminal : c'est le seul filtre qui ressort du backtest (voir engine/study.py et le rapport « Backtest ») :
sur BTC de 2013 a 2026, les idees DANS le sens de cette tendance ont rapporte en moyenne +0,15 fois le risque par trade apres frais,
celles CONTRE elle -0,11. Module PUR, meme definition que backtest.regime_at (les deux sont verifies par un test)."""

FAST_DAYS = 50
SLOW_DAYS = 200
LABELS = {1: "haussière", -1: "baissière", 0: "indécise"}


def state(closes, fast_days: int = FAST_DAYS, slow_days: int = SLOW_DAYS) -> dict:
    """closes : clotures des bougies 1 h FERMEES, dans l'ordre. Renvoie {ready, regime, label, price, fast, slow, distFast, distSlow, ...}."""
    nf, ns = fast_days * 24, slow_days * 24
    n = len(closes)
    if n < ns:
        return {"ready": False, "bars": n, "need": ns}
    price = closes[-1]
    fast = sum(closes[-nf:]) / nf
    slow = sum(closes[-ns:]) / ns
    reg = 1 if price > fast and price > slow else -1 if price < fast and price < slow else 0
    return {"ready": True, "regime": reg, "label": LABELS[reg], "price": price, "fast": fast, "slow": slow,
            "distFast": (price / fast - 1.0) * 100.0, "distSlow": (price / slow - 1.0) * 100.0,
            "fastDays": fast_days, "slowDays": slow_days}


def alignment(regime, side: str):
    """+1 : l'idee va dans le sens de la tendance ; -1 : contre ; 0 : tendance indecise ; None : tendance inconnue."""
    if regime is None:
        return None
    return regime * (1 if side == "long" else -1)
