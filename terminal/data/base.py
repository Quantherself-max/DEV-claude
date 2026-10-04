"""Interface d'une source de donnees de marche."""
import time


class DataError(Exception):
    """Erreur de donnees (reseau, blocage geographique, format inattendu...)."""


class Source:
    name = "base"

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def candles(self, symbol: str, interval: str, start_ms: int, end_ms: int):
        """Bougies [start, end] (la derniere peut etre en cours de formation)."""
        raise NotImplementedError

    def open_interest(self, symbol: str, period: str, start_ms: int, end_ms: int):
        """[(timestamp ms de fin de periode, OI en coin), ...] (Binance : 30 derniers jours seulement)."""
        raise NotImplementedError

    # --- contexte (V2) : optionnel, une source peut ne pas le fournir ---
    def premium_index(self, symbol: str) -> dict:
        raise NotImplementedError

    def funding_history(self, symbol: str, start_ms: int, end_ms: int):
        raise NotImplementedError

    def long_short(self, symbol: str, period: str, start_ms: int, end_ms: int, kind: str = "global"):
        raise NotImplementedError

    def spot_price(self, symbol: str) -> float:
        raise NotImplementedError

    def coinbase_price(self, product: str) -> float:
        raise NotImplementedError

    def last_price(self, symbol: str) -> tuple:
        """Dernier prix echange et son horodatage (ms) : secours du flux temps reel."""
        raise NotImplementedError
