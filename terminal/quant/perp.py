"""Perpétuels linéaires (marge et règlement en USDT, comme BTCUSDT, SOLUSDT, PUMPUSDT) : calculs EXACTS en décimal (V45).

Conventions : side = +1 (long) ou -1 (short) ; qty en pièces (BTC, SOL), toujours positive ; prix en dollars ; taux en fraction
(0.0005 = 0,05 %). Tous les arguments sont des textes de bourse, des entiers ou des Decimal (jamais des flottants : voir quant.num).

Formules
  notionnel                 = qty × prix
  résultat                  = side × qty × (sortie - entrée)
  frais                     = notionnel × taux
  financement reçu          = - side × qty × prix_de_marque × taux     (taux positif : le long paie, le short reçoit)
  marge initiale            = notionnel / levier
  prix de liquidation (marge isolée, une position) : la marge restante égale la marge de maintien
      marge + side × qty × (P - entrée) = qty × P × mmr - montant_de_maintien
      P = (marge + montant_de_maintien - side × qty × entrée) / (qty × (mmr - side))
    C'est la formule publiée par Binance pour une position isolée en mode simple ; `mmr` (taux de marge de maintien) et le montant de
    maintien dépendent du palier de taille de la position : ils se passent en argument (`tiers`). Binance ne publie pas ses paliers sans
    clé ; OKX et Bybit les publient (voir ingest) : le terminal ne les invente pas.
  taille pour un risque     = plancher_au_pas( capital × risque / (|entrée - stop| + frais par pièce) )
Module PUR."""
from __future__ import annotations
from decimal import Decimal

from .num import CTX, D, ONE, ZERO, quantize

LONG, SHORT = 1, -1


def side_of(side) -> int:
    """+1 / -1 à partir de 1, -1, 'long', 'short', 'buy', 'sell'."""
    if side in (1, -1):
        return side
    s = str(side).lower()
    if s in ("long", "buy", "achat"):
        return LONG
    if s in ("short", "sell", "vente"):
        return SHORT
    raise ValueError(f"sens inconnu : {side!r}")


def notional(qty, price) -> Decimal:
    return CTX.multiply(D(qty), D(price))


def pnl(side, qty, entry, exit_) -> Decimal:
    """Résultat brut en dollars (sans frais ni financement)."""
    return CTX.multiply(Decimal(side_of(side)), CTX.multiply(D(qty), CTX.subtract(D(exit_), D(entry))))


def fee(qty, price, rate) -> Decimal:
    return CTX.multiply(notional(qty, price), D(rate))


def funding_payment(side, qty, mark, rate) -> Decimal:
    """Dollars REÇUS (positif) ou payés (négatif) à une échéance de financement."""
    return CTX.multiply(Decimal(-side_of(side)), CTX.multiply(notional(qty, mark), D(rate)))


def funding_total(side, qty, events, t_open: int, t_close: int) -> Decimal:
    """Somme des financements d'une position tenue de t_open à t_close (ms). `events` : [(heure ms, taux, prix de marque)] ; une échéance
    compte si la position est ouverte À cette heure : t_open < heure <= t_close (une position ouverte pile à l'échéance ne paie pas)."""
    tot = ZERO
    for t, rate, mark in events:
        if t_open < t <= t_close:
            tot = CTX.add(tot, funding_payment(side, qty, mark, rate))
    return tot


def initial_margin(qty, price, leverage) -> Decimal:
    lev = D(leverage)
    if lev <= 0:
        raise ValueError("levier nul ou négatif")
    return CTX.divide(notional(qty, price), lev)


def tier_for(notional_usd, tiers):
    """Palier de marge de maintien pour un notionnel. `tiers` : [(notionnel maximal ou None, mmr, montant de maintien)] triés du plus petit
    au plus grand. Renvoie (mmr, montant)."""
    n = D(notional_usd)
    for cap, mmr, amount in tiers:
        if cap is None or n <= D(cap):
            return D(mmr), D(amount)
    raise ValueError("notionnel au-delà du dernier palier")


def liquidation_price(side, qty, entry, margin, mmr=None, maint_amount=0, tiers=None):
    """Prix de liquidation d'une position ISOLÉE (voir l'en-tête). `margin` : marge affectée à la position (marge initiale + ajouts -
    retraits, frais d'ouverture déjà retirés si la bourse les prend sur la marge). Soit `mmr` (et `maint_amount`), soit `tiers` : avec des
    paliers, le palier est celui du notionnel AU prix de liquidation (recherche par itération, stable en quelques tours).
    Renvoie None si la position ne peut pas être liquidée (long couvert à plus de 100 %)."""
    sd, q, e, m = side_of(side), D(qty), D(entry), D(margin)
    if q <= 0 or e <= 0:
        raise ValueError("quantité et prix d'entrée doivent être positifs")

    def solve(r, a):
        den = CTX.multiply(q, CTX.subtract(r, Decimal(sd)))
        if den == 0:
            return None
        p = CTX.divide(CTX.subtract(CTX.add(m, a), CTX.multiply(Decimal(sd), CTX.multiply(q, e))), den)
        return p if p > 0 else None

    if tiers is None:
        if mmr is None:
            raise ValueError("donner mmr ou tiers")
        return solve(D(mmr), D(maint_amount))
    r, a = tier_for(notional(q, e), tiers)
    p = solve(r, a)
    for _ in range(12):
        if p is None:
            return None
        r2, a2 = tier_for(notional(q, p), tiers)
        if (r2, a2) == (r, a):
            return p
        r, a = r2, a2
        p = solve(r, a)
    return p


def bankruptcy_price(side, qty, entry, margin):
    """Prix où toute la marge est perdue (mmr = 0)."""
    return liquidation_price(side, qty, entry, margin, mmr=0)


def position_size(equity, risk_fraction, entry, stop, qty_step, fee_in=0, fee_out=0, max_leverage=None, min_qty=None) -> dict:
    """Taille telle que la perte au stop (frais d'entrée et de sortie compris) ne dépasse pas capital × risque. Arrondie vers le BAS au pas
    de quantité. `max_leverage` plafonne le notionnel à capital × levier. Renvoie qty, notionnel, perte au stop, levier utilisé."""
    eq, rf, e, s = D(equity), D(risk_fraction), D(entry), D(stop)
    if eq <= 0 or rf <= 0 or e <= 0 or s <= 0 or e == s:
        raise ValueError("capital, risque, entrée et stop doivent être positifs, et le stop différent de l'entrée")
    per_unit = CTX.add(abs(CTX.subtract(e, s)), CTX.add(CTX.multiply(e, D(fee_in)), CTX.multiply(s, D(fee_out))))
    q = CTX.divide(CTX.multiply(eq, rf), per_unit)
    capped = False
    if max_leverage is not None:
        q_max = CTX.divide(CTX.multiply(eq, D(max_leverage)), e)
        if q > q_max:
            q, capped = q_max, True
    q = quantize(q, qty_step, "floor")
    if min_qty is not None and q < D(min_qty):
        q = ZERO
    n = notional(q, e)
    return {"qty": q, "notional": n, "loss_at_stop": CTX.multiply(q, per_unit), "leverage": CTX.divide(n, eq),
            "capped": capped, "side": LONG if s < e else SHORT}


def break_even(side, entry, fee_in=0, fee_out=0) -> Decimal:
    """Prix de sortie où le résultat net de frais est nul. Long : entrée × (1 + f_in) / (1 - f_out) ; short : entrée × (1 - f_in) / (1 + f_out)."""
    e, fi, fo = D(entry), D(fee_in), D(fee_out)
    if side_of(side) == LONG:
        return CTX.divide(CTX.multiply(e, CTX.add(ONE, fi)), CTX.subtract(ONE, fo))
    return CTX.divide(CTX.multiply(e, CTX.subtract(ONE, fi)), CTX.add(ONE, fo))


def net_result(side, qty, entry, exit_, fee_in=0, fee_out=0, funding=0) -> dict:
    """Résultat complet d'un aller-retour : brut, frais, financement reçu, net."""
    g = pnl(side, qty, entry, exit_)
    f = CTX.add(fee(qty, entry, fee_in), fee(qty, exit_, fee_out))
    fu = D(funding)
    return {"gross": g, "fees": f, "funding": fu, "net": CTX.add(CTX.subtract(g, f), fu)}


def r_multiple(side, entry, stop, exit_) -> Decimal:
    """Résultat brut en multiples du risque initial (distance entrée - stop)."""
    risk = abs(CTX.subtract(D(entry), D(stop)))
    if risk == 0:
        raise ValueError("stop égal à l'entrée")
    return CTX.divide(CTX.multiply(Decimal(side_of(side)), CTX.subtract(D(exit_), D(entry))), risk)
