"""Instruments futures et contrat trimestriel en cours. Module PUR.

NQ (E-mini Nasdaq-100) : 1 point = 20 $, pas de cotation 0,25 point = 5 $.
MNQ (Micro) : 1 point = 2 $, pas 0,25 point = 0,50 $ (un dixieme d'un NQ).
Contrats trimestriels : H (mars), M (juin), U (septembre), Z (decembre). Echeance = 3e vendredi du mois a 9 h 30 ET ; le volume passe au
contrat suivant environ 8 jours avant (le jeudi de la semaine precedente) : c'est la date de « roll » estimee ici. C'est une estimation :
au moment du roll, regarde le volume reel de ta plateforme."""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .clock import DAY, et_to_utc

MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}
MONTH_FR = {3: "mars", 6: "juin", 9: "sept.", 12: "déc."}
ROLL_DAYS_BEFORE = 8


@dataclass(frozen=True)
class Instrument:
    root: str
    name: str
    tick: float                 # pas de cotation, en points
    point_value: float          # dollars par point
    mini_equiv: float = 1.0     # 1 mini = 1.0 ; 1 micro = 0.1 (sert aux plafonds de contrats « minis / micros »)
    big_lot: int = 30           # taille a partir de laquelle une transaction est « grosse » (reglable)

    @property
    def tick_value(self) -> float:
        return self.tick * self.point_value

    def idx(self, price: float) -> int:
        """Indice de tick du prix (prix = indice x pas)."""
        return int(round(price / self.tick))

    def price(self, idx: int) -> float:
        return round(idx * self.tick, 10)

    def snap(self, price: float) -> float:
        return self.price(self.idx(price))

    def dollars(self, points: float, qty: float = 1) -> float:
        return points * self.point_value * qty


NQ = Instrument("NQ", "E-mini Nasdaq-100", 0.25, 20.0, 1.0, 30)
MNQ = Instrument("MNQ", "Micro E-mini Nasdaq-100", 0.25, 2.0, 0.1, 100)
ES = Instrument("ES", "E-mini S&P 500", 0.25, 50.0, 1.0, 50)
MES = Instrument("MES", "Micro E-mini S&P 500", 0.25, 5.0, 0.1, 150)
INSTRUMENTS = {i.root: i for i in (NQ, MNQ, ES, MES)}
MICRO_OF = {"MNQ": "NQ", "MES": "ES"}


def get(root: str) -> Instrument:
    try:
        return INSTRUMENTS[root.upper()]
    except KeyError:
        raise ValueError(f"instrument inconnu : {root} (connus : {', '.join(INSTRUMENTS)})") from None


def third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return date(year, month, 1 + (4 - first.weekday()) % 7 + 14)


@dataclass(frozen=True)
class Contract:
    root: str
    month: int
    year: int
    expiry_ms: int
    roll_ms: int

    @property
    def code(self) -> str:
        """Code court a un chiffre d'annee, comme sur Tradovate / NinjaTrader (NQZ6)."""
        return f"{self.root}{MONTH_CODE[self.month]}{self.year % 10}"

    @property
    def code_long(self) -> str:
        return f"{self.root}{MONTH_CODE[self.month]}{self.year % 100:02d}"

    @property
    def label(self) -> str:
        return f"{self.code} ({MONTH_FR[self.month]} {self.year})"


def contract(root: str, month: int, year: int) -> Contract:
    d = third_friday(year, month)
    expiry = et_to_utc(d.year, d.month, d.day, 9, 30)
    roll = et_to_utc(d.year, d.month, d.day, 0, 0) - ROLL_DAYS_BEFORE * DAY
    return Contract(root, month, year, expiry, roll)


def front_contract(utc_ms: int, root: str = "NQ") -> Contract:
    """Contrat « de tete » estime a cet instant : le premier trimestriel dont la date de roll n'est pas encore passee."""
    y = datetime.fromtimestamp(utc_ms / 1000.0, timezone.utc).year
    for year in (y - 1, y, y + 1):
        for month in (3, 6, 9, 12):
            c = contract(root, month, year)
            if c.roll_ms > utc_ms:
                return c
    raise ValueError("contrat introuvable")
