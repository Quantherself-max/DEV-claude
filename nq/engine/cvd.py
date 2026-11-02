"""CVD (flux cumule d'ordres agressifs) et divergences. Module PUR. (Les absorptions, mesurees au prix dans le footprint : engine/absorption.py.)

delta d'une barre = volume acheteur agressif - volume vendeur agressif ; CVD = somme cumulee de ces deltas, remise a zero au debut de la
seance choisie (journee Globex ou seance reguliere). Le CVD ne vaut que ce que vaut le cote de l'agresseur : voir `bars.SideClassifier`
(part des transactions dont le cote vient de la bourse). Avec un cote estime (regle du tick), le terminal l'affiche clairement.

  - divergence haussiere : le prix fait un plus bas plus bas mais le CVD un plus bas plus HAUT (les vendeurs agressifs s'epuisent) ;
    baissiere : plus haut plus haut du prix, plus haut plus BAS du CVD."""
import math


def cumulative(bars, key_fn) -> list:
    """CVD APRES chaque barre ; remis a zero quand la cle de seance change ; None hors seance (cle None)."""
    out, key, acc = [], None, 0.0
    for b in bars:
        k = key_fn(b.t)
        if k is None:
            out.append(None)
            key = None
            continue
        if k != key:
            key, acc = k, 0.0
        acc += b.bv - b.sv
        out.append(acc)
    return out


def _swings(arr, j0: int, j1: int, n: int, low: bool) -> list:
    out = []
    for j in range(j0 + n, j1 - n + 1):
        x = arr[j]
        if x is None:
            continue
        nb = [arr[j + q] for q in range(-n, n + 1) if q]
        if any(v is None for v in nb):
            continue
        if low and all(x < arr[j - q] for q in range(1, n + 1)) and all(x <= arr[j + q] for q in range(1, n + 1)):
            out.append(j)
        elif not low and all(x > arr[j - q] for q in range(1, n + 1)) and all(x >= arr[j + q] for q in range(1, n + 1)):
            out.append(j)
    return out


def divergence(bars, cvd: list, i: int, look: int = 60, n: int = 2) -> tuple:
    """('bull' | 'bear' | None, force 0..1) sur les `look` dernieres barres jusqu'a la barre i comprise."""
    j0 = max(0, i - look)
    highs = [b.h for b in bars]
    lows = [b.l for b in bars]
    for low, name in ((True, "bull"), (False, "bear")):
        sw = _swings(lows if low else highs, j0, i, n, low)
        if len(sw) < 2:
            continue
        a, c = sw[-2], sw[-1]
        if cvd[a] is None or cvd[c] is None:
            continue
        pa, pc = (lows[a], lows[c]) if low else (highs[a], highs[c])
        vol = sum(b.v for b in bars[a:c + 1])
        if vol <= 0:
            continue
        if (low and pc < pa and cvd[c] > cvd[a]) or (not low and pc > pa and cvd[c] < cvd[a]):
            return name, min(1.0, abs(cvd[c] - cvd[a]) / vol / 0.10)
    return None, 0.0


def imbalance(bars, n: int) -> float:
    """Desequilibre des n dernieres barres : delta / volume, de -1 (que des vendeurs agressifs) a +1 (que des acheteurs)."""
    sub = bars[-n:]
    v = sum(b.v for b in sub)
    return sum(b.bv - b.sv for b in sub) / v if v > 0 else 0.0
