"""Premier jour utilisable de chaque paire (V42), par marche ('futures' : perpetuel USDT-M, 'spot').

Binance reutilise parfois un symbole : PUMPUSDT a d'abord ete un autre jeton (avril a juin 2025, puis fige a 0,0471 jusqu'au 9 juillet),
avant le jeton de pump.fun, cote a partir du 10 juillet 2025 (environ 0,005 $). Sans cette limite, le terminal melangerait les deux
dans l'historique, les profils et les archives. Le spot PUMPUSDT n'existe sur Binance que depuis le 11 septembre 2025.
Toute lecture d'historique (API et archives Binance Vision) commence au plus tot a ce jour."""
from __future__ import annotations
from datetime import datetime, timezone


def _ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


FIRST = {
    ("PUMPUSDT", "futures"): _ms(2025, 7, 10),
    ("PUMPUSDT", "spot"): _ms(2025, 9, 11),
}


def first_ms(symbol: str, market: str = "futures") -> int:
    """Premier instant utilisable (0 : aucune limite connue)."""
    m = "spot" if market == "spot" else "futures"
    return FIRST.get(((symbol or "").upper(), m), 0)


def clamp(symbol: str, start_ms: int, market: str = "futures") -> int:
    """Debut d'une lecture d'historique, jamais avant le premier jour de la paire."""
    return max(int(start_ms), first_ms(symbol, market))
