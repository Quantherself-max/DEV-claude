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
