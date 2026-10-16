"""Grille de prix logarithmique : un bin = pct % de large (comme dans les scripts Pine)."""
import math


class Grid:
    def __init__(self, pct: float, min_px: float = 0.01):
        self.step = math.log(1.0 + pct / 100.0)
        self.min_px = min_px
        self.base = math.floor(math.log(min_px) / self.step)

    def idx(self, p: float) -> int:
        return max(0, math.floor(math.log(max(p, self.min_px)) / self.step) - self.base)

    def price(self, i: int, off: float = 0.5) -> float:
        return math.exp((i + self.base + off) * self.step)


def rnd(x: float) -> int:
    """Arrondi 'moitie vers le haut' comme math.round de Pine (Python arrondit au pair)."""
    return int(math.floor(x + 0.5))
