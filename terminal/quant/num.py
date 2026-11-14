"""Nombres exacts et horodatages (V45).

- `D(x)` : décimal exact à partir d'un texte de bourse, d'un entier ou d'un Decimal. Un flottant est REFUSÉ (TypeError) : c'est la garantie
  qu'aucun arrondi binaire n'entre dans un calcul d'argent sans qu'on l'ait décidé (`from_float` le fait explicitement, par l'écriture
  la plus courte du nombre).
- `units(texte, échelle)` : entier exact en unités de 10^-échelle (8 par défaut), sans passer par Decimal : c'est le chemin rapide des
  transactions (plusieurs milliers par seconde). Erreur si le texte a plus de décimales que l'échelle.
- `quantize(x, pas, mode)` : arrondi à un multiple du pas de cotation ou du pas de quantité (plancher, plafond, plus proche).
- `to_ms(x)` : heure en millisecondes UTC, quelle que soit l'écriture de la source (secondes, millisecondes, microsecondes,
  nanosecondes, date ISO 8601 avec ou sans fraction).
Contexte de calcul : 40 chiffres significatifs, arrondi bancaire ; une opération invalide ou une division par zéro lève une exception
(jamais de « NaN » silencieux)."""
from __future__ import annotations
import calendar
import re
from decimal import (ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow)

CTX = Context(prec=40, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])
ZERO, ONE = Decimal(0), Decimal(1)
SCALE = 8                                   # unités entières : 10^-8 (assez pour toutes les paires suivies ; vérifié à la lecture)
UNIT = 10 ** SCALE
MODES = {"floor": ROUND_FLOOR, "ceil": ROUND_CEILING, "near": ROUND_HALF_EVEN}


def D(x) -> Decimal:
    """Décimal exact. Texte (« 68224.47 »), entier ou Decimal ; flottant refusé."""
    if isinstance(x, Decimal):
        if not x.is_finite():
            raise ValueError(f"nombre non fini : {x}")
        return x
    if isinstance(x, bool):
        raise TypeError("booléen refusé comme nombre")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, str):
        try:
            v = Decimal(x.strip())
        except InvalidOperation:
            raise ValueError(f"nombre illisible : {x!r}") from None
        if not v.is_finite():
            raise ValueError(f"nombre non fini : {x!r}")
        return v
    if isinstance(x, float):
        raise TypeError("flottant refusé : passer le texte de la bourse, ou from_float() pour un choix explicite")
    raise TypeError(f"type refusé comme nombre : {type(x).__name__}")


def from_float(x: float) -> Decimal:
    """Passage EXPLICITE d'un flottant au décimal, par son écriture la plus courte (0.1 -> 0.1 et non 0.1000000000000000055...)."""
    v = Decimal(repr(float(x)))
    if not v.is_finite():
        raise ValueError(f"nombre non fini : {x}")
    return v


def units(text, scale: int = SCALE) -> int:
    """Entier exact en unités de 10^-scale à partir d'un texte décimal (« 0.001 » -> 100000 à l'échelle 8). Les entiers passent tels quels
    (× 10^scale). Notation scientifique et autres écritures : par Decimal, avec la même garantie d'exactitude."""
    if isinstance(text, int) and not isinstance(text, bool):
        return text * 10 ** scale
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("ascii")
    if isinstance(text, str):
        s = text.strip()
        neg = s.startswith("-")
        body = s[1:] if neg or s.startswith("+") else s
        a, dot, b = body.partition(".")
        if (a or b) and (a.isdigit() or a == "") and (b.isdigit() or b == ""):
            b = b.rstrip("0")
            if len(b) > scale:
                raise ValueError(f"{text!r} a plus de {scale} décimales : échelle insuffisante")
            v = int((a or "0") + b.ljust(scale, "0"))
            return -v if neg else v
    d = CTX.multiply(D(text), Decimal(10) ** scale)
    if d != d.to_integral_value():
        raise ValueError(f"{text!r} a plus de {scale} décimales : échelle insuffisante")
    return int(d)


def from_units(u: int, scale: int = SCALE) -> Decimal:
    return Decimal(u).scaleb(-scale, CTX)


def quantize(x, step, mode: str = "floor") -> Decimal:
    """Multiple de `step` : plancher (taille d'ordre : jamais plus que demandé), plafond ou plus proche."""
    x, step = D(x), D(step)
    if step <= 0:
        raise ValueError("pas nul ou négatif")
    n = CTX.divide(x, step).to_integral_value(rounding=MODES[mode])
    return CTX.multiply(n, step)


def decimals_of(step) -> int:
    """Nombre de décimales d'un pas (« 0.001 » -> 3)."""
    return max(0, -D(step).normalize().as_tuple().exponent)


def fmt(x, step=None) -> str:
    """Écriture décimale sans notation scientifique ; alignée sur les décimales du pas si donné."""
    x = D(x)
    if step is not None:
        return f"{x:.{decimals_of(step)}f}"
    return format(x.normalize(), "f")


def add(*xs) -> Decimal:
    t = ZERO
    for x in xs:
        t = CTX.add(t, D(x))
    return t


def mul(a, b) -> Decimal:
    return CTX.multiply(D(a), D(b))


def div(a, b) -> Decimal:
    return CTX.divide(D(a), D(b))


# ---------- horodatages ----------
ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def to_ms(x) -> int:
    """Heure en millisecondes UTC. Entier ou texte de chiffres : l'unité est déduite de la grandeur (secondes < 10^11 <= millisecondes
    < 10^14 <= microsecondes < 10^17 <= nanosecondes). Texte ISO 8601 : fraction jusqu'à la nanoseconde, décalage horaire respecté ;
    sans décalage, l'heure est prise en UTC. Les fractions de milliseconde sont tronquées."""
    if isinstance(x, bool) or x is None:
        raise TypeError("horodatage absent")
    if isinstance(x, float):
        x = from_float(x)
    if isinstance(x, str):
        s = x.strip()
        m = ISO_RE.match(s)
        if m:
            y, mo, d, h, mi, sec, frac, tz = m.groups()
            base = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(sec or 0), 0, 0, 0)) * 1000
            if frac:
                base += int(frac[:3].ljust(3, "0"))
            if tz and tz != "Z":
                sign = -1 if tz[0] == "-" else 1
                hh, mm = int(tz[1:3]), int(tz[-2:])
                base -= sign * (hh * 60 + mm) * 60_000
            return base
        x = D(s)
    if isinstance(x, Decimal):
        if x != x.to_integral_value():                       # secondes avec fraction (« 1794619186.123 »)
            return int(CTX.multiply(x, Decimal(1000)).to_integral_value(rounding=ROUND_FLOOR))
        x = int(x)
    if not isinstance(x, int):
        raise TypeError(f"horodatage illisible : {x!r}")
    a = abs(x)
    if a < 10 ** 11:
        return x * 1000
    if a < 10 ** 14:
        return x
    if a < 10 ** 17:
        return x // 1000
    return x // 1_000_000
