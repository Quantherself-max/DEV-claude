"""CVD (flux cumule d'ordres agressifs) : desequilibre, divergences avec le prix, absorption.

delta d'une bougie = volume acheteur agressif - volume vendeur agressif. Le CVD est la somme cumulee de ces deltas.
  - desequilibre = delta / volume sur une fenetre (de -1, que des vendeurs agressifs, a +1, que des acheteurs) ;
  - divergence haussiere : le prix fait un plus bas plus bas mais le CVD fait un plus bas plus HAUT (les vendeurs
    agressifs s'epuisent) ; baissiere : plus haut plus haut du prix, plus haut plus BAS du CVD ;
  - absorption haussiere : gros volume avec delta vendeur mais le prix ne baisse pas (un gros acheteur passif absorbe) ;
    baissiere : l'inverse.
Les series viennent de fine.Bars (delta reel Binance, ou proxy par minute sinon : voir fine.py).
Module PUR."""
from .fine import Bars


def _clip(x, lo=-1.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def imbalance(b: Bars, i0: int, i1: int) -> float:
    v = b.volume(i0, i1)
    return b.delta(i0, i1) / v if v > 0 else 0.0


def _swings(arr, j0, j1, n, low):
    out = []
    for j in range(j0 + n, j1 - n + 1):
        x = arr[j]
        if low:
            if all(x < arr[j - q] for q in range(1, n + 1)) and all(x <= arr[j + q] for q in range(1, n + 1)):
                out.append(j)
        elif all(x > arr[j - q] for q in range(1, n + 1)) and all(x >= arr[j + q] for q in range(1, n + 1)):
            out.append(j)
    return out


def divergence(b: Bars, i: int, look: int = 48, n: int = 2):
    """('bull'|'bear'|None, force 0..1) sur les `look` dernieres bougies (derniere fermee = i)."""
    j0 = max(0, i - look)
    for low, name in ((True, "bull"), (False, "bear")):
        sw = _swings(b.l if low else b.h, j0, i, n, low)
        if len(sw) < 2:
            continue
        a, c = sw[-2], sw[-1]
        pa, pc = (b.l[a], b.l[c]) if low else (b.h[a], b.h[c])
        ca, cc = b.cd[a + 1], b.cd[c + 1]
        v = b.volume(a, c + 1)
        if v <= 0:
            continue
        if (low and pc < pa and cc > ca) or (not low and pc > pa and cc < ca):
            return name, _clip(abs(cc - ca) / v / 0.10, 0.0, 1.0)
    return None, 0.0


def absorption(b: Bars, i: int, k: int = 4, base: int = 48):
    """('bull'|'bear'|None) : volume anormal (>= 1,3 x la normale) dont le delta va CONTRE le mouvement du prix (le prix tient)."""
    if i - k - base < 0:
        return None
    v = b.volume(i - k + 1, i + 1)
    avg = b.volume(i - k - base + 1, i - k + 1) / (base / k)
    if avg <= 0 or v < 1.3 * avg:
        return None
    d = b.delta(i - k + 1, i + 1)
    if abs(d) < 0.15 * v:
        return None
    move = b.c[i] - b.o[i - k + 1]
    if d < 0 and move >= 0:
        return "bull"
    if d > 0 and move <= 0:
        return "bear"
    return None


def analyse(b: Bars, i: int) -> dict:
    """Mesures de flux a la bougie fermee i (pas de temps quelconque : les fenetres sont en heures)."""
    per_h = max(1, int(3_600_000 / b.step))
    out = {}
    for h in (1, 4, 24):
        n = h * per_h
        out[f"imb{h}"] = imbalance(b, max(0, i + 1 - n), i + 1)
        out[f"buy{h}"] = 50.0 * (1.0 + out[f"imb{h}"])               # % d'achats agressifs
    out["div"], out["divStrength"] = divergence(b, i, look=12 * per_h)
    out["absorb"] = absorption(b, i, k=max(2, per_h), base=12 * max(2, per_h))
    return out


def flow(a: dict):
    """(score -1..1 : positif = acheteur, notes [(signe, texte)]) en francais clair, a partir de analyse()."""
    notes = []
    s4 = _clip(a["imb4"] / 0.12)
    s24 = _clip(a["imb24"] / 0.08)
    notes.append((s4, f"Flux d'ordres agressifs : {a['buy4']:.0f} % d'achats sur 4 h, {a['buy24']:.0f} % sur 24 h (CVD, flux cumulé acheteur - vendeur)"))
    score = 0.5 * s4 + 0.25 * s24
    if a["div"]:
        sgn = 1 if a["div"] == "bull" else -1
        score += 0.35 * sgn * max(0.4, a["divStrength"])
        notes.append((sgn * 0.5, "Divergence haussière du CVD : le prix fait un plus bas plus bas mais les vendeurs agressifs s'épuisent" if sgn > 0
                      else "Divergence baissière du CVD : le prix fait un plus haut plus haut mais les acheteurs agressifs s'épuisent"))
    if a["absorb"]:
        sgn = 1 if a["absorb"] == "bull" else -1
        score += 0.35 * sgn
        notes.append((sgn * 0.5, "Absorption haussière : de gros volumes vendeurs sont absorbés sans que le prix baisse" if sgn > 0
                      else "Absorption baissière : de gros volumes acheteurs sont absorbés sans que le prix monte"))
    return _clip(score), notes
