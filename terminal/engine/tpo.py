"""TPO (profil de marche, « Time Price Opportunity ») (V17, enrichi en V19) : pour chaque seance (1 jour, 4 heures ou 1 heure), chaque tranche de
temps recoit une lettre (A, B, C...) et cette lettre est posee sur chaque prix que la tranche a touche. On lit :
  - le POC (prix touche par le plus de tranches) et la zone de valeur (70 % des lettres autour du POC) ;
  - les SINGLE PRINTS : prix touches par une seule tranche, a l'interieur du profil (le prix y est passe vite, sans s'y arreter). Au moins
    MIN_SINGLE lignes de suite ;
  - les QUEUES (excess) : single prints au bord haut ou bas du profil (rejet net : enchere terminee) ;
  - les POOR HIGH / POOR LOW : plus haut (ou plus bas) touche par au moins deux tranches, sans queue (enchere mal terminee).
V19 ajoute, par seance :
  - le VOLUME et le DELTA (acheteurs - vendeurs agressifs) a chaque prix, repartis selon le trajet de chaque bougie, et le POC en volume ;
  - la PREMIERE HEURE (« initial balance » : 1 h pour la seance d'1 jour, 30 min pour 4 h, 10 min pour 1 h), ses cassures et extensions
    (x1,5 et x2 sa hauteur), le TYPE DE JOURNEE (classement de J. Dalton : sans tendance, normale, variation de normale, tendance, neutre,
    double distribution), la FORME du profil (P, b, D, I, B), le FACTEUR DE ROTATION et l'equilibre des lettres autour du POC ;
  - le contexte face a la seance precedente : MIGRATION de la zone de valeur, POSITION DE L'OUVERTURE, « REGLE DES 80 % » (ouverture hors de
    la valeur d'hier, retour dans la valeur tenu deux tranches : objectif l'autre bord) ;
  - les POC VIERGES (POC jamais retraverses depuis) et un PROFIL COMPOSITE des dernieres seances avec ses noeuds forts (HVN) et faibles (LVN).
Tranches : 30 min pour la seance d'1 jour (00 h UTC), 5 min pour les seances de 4 h et d'1 h. Bougies 5 min. Module PUR."""
import math
from bisect import bisect_left

from .sessionvp import nice_step, nodes, spread

MIN = 60_000
H = 60 * MIN
DAY = 24 * H
# rows : nombre de lignes pour l'amplitude typique d'une seance (memes reglages que la mesure sur l'historique, engine/tpostudy.py)
KINDS = {"D": {"len": DAY, "bracket": 30 * MIN, "ib": 60 * MIN, "label": "1 jour", "n": 10, "rows": 60, "comp": 5},
         "4h": {"len": 4 * H, "bracket": 5 * MIN, "ib": 30 * MIN, "label": "4 heures", "n": 12, "rows": 36, "comp": 6},
         "1h": {"len": H, "bracket": 5 * MIN, "ib": 10 * MIN, "label": "1 heure", "n": 24, "rows": 20, "comp": 12}}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
VA = 0.70
MIN_SINGLE = 2

DAY_TYPES = {
    "nontrend": ("Sans tendance", "Peu d'activité, fourchette étroite : le marché attend (souvent avant une annonce)."),
    "normal": ("Normale", "La première heure contient presque toute la journée : de gros intervenants ont fixé les bornes tôt."),
    "normalvar": ("Variation de normale", "Une sortie de la première heure d'un seul côté, jusqu'à environ deux fois sa hauteur."),
    "trend": ("Tendance", "Sortie franche d'un seul côté, clôture près de l'extrême : un camp a dominé toute la journée."),
    "neutral": ("Neutre", "Sorties des deux côtés de la première heure : personne n'a pris le contrôle."),
    "double": ("Double distribution", "Deux zones d'échange séparées par des single prints : le marché a changé de niveau en cours de séance."),
}
SHAPES = {"P": "forme P : échanges concentrés en haut (rachats de vendeurs ou acheteurs tardifs)",
          "b": "forme b : échanges concentrés en bas (liquidation d'acheteurs)",
          "D": "forme D : équilibre, échanges centrés",
          "I": "forme allongée : tendance, peu d'échanges à chaque prix",
          "B": "deux bosses : deux zones d'acceptation"}


def brackets(bars, start: int, end: int, bracket_ms: int):
    """[(numero, plus haut, plus bas, ouverture, cloture)] des tranches de la seance [start, end), du plus ancien au plus recent."""
    out = {}
    for k in bars:
        if k.t < start or k.t >= end:
            continue
        i = (k.t - start) // bracket_ms
        b = out.get(i)
        if b is None:
            out[i] = [k.h, k.l, k.o, k.c]
        else:
            b[0], b[1], b[3] = max(b[0], k.h), min(b[1], k.l), k.c
    return [(i, h, l, o, c) for i, (h, l, o, c) in sorted(out.items())]


def _va(cnt, poc):
    n, tot = len(cnt), sum(cnt)
    acc, up, dn = cnt[poc], poc, poc
    while acc < tot * VA and (up < n - 1 or dn > 0):
        u = cnt[up + 1] if up < n - 1 else -1
        d = cnt[dn - 1] if dn > 0 else -1
        if u >= d:
            up += 1
            acc += cnt[up]
        else:
            dn -= 1
            acc += cnt[dn]
    return up, dn


def profile(bars, start: int, end: int, bracket_ms: int, step: float, min_single: int = MIN_SINGLE, ib_ms: int | None = None):
    """Profil TPO de la seance. None sans donnees. Lignes : [prix bas, nombre de lettres, lettres, volume, delta (None sans volume acheteur)]."""
    br = brackets(bars, start, end, bracket_ms)
    if not br or step <= 0:
        return None
    if ib_ms is None and bracket_ms >= 30 * MIN:
        ib_ms = 2 * bracket_ms                             # par defaut : les deux premieres tranches (la premiere heure en tranches de 30 min)
    hi, lo = max(b[1] for b in br), min(b[2] for b in br)
    k0 = math.floor(lo / step + 1e-9)
    n = math.floor(hi / step + 1e-9) - k0 + 1
    lets = [[] for _ in range(n)]
    for i, h, l, _o, _c in br:
        for j in range(max(0, math.floor(l / step + 1e-9) - k0), min(n - 1, math.floor(h / step + 1e-9) - k0) + 1):
            lets[j].append(i)
    cnt = [len(x) for x in lets]
    vol, buy = [0.0] * n, [0.0] * n
    sel = [k for k in bars if start <= k.t < end]
    for k in sel:
        spread(k, k0, n, step, vol, buy)
    has_tb = any(k.tb > 0 for k in sel)
    mid = (n - 1) / 2
    poc = max(range(n), key=lambda j: (cnt[j], -abs(j - mid)))
    up, dn = _va(cnt, poc)
    vpoc = max(range(n), key=lambda j: vol[j]) if any(vol) else None
    out = {"start": start, "end": end, "step": step, "high": hi, "low": lo, "brackets": len(br), "bracketMs": bracket_ms,
           "open": sel[0].o if sel else br[0][3], "close": sel[-1].c if sel else br[-1][4],
           "poc": (k0 + poc + 0.5) * step, "vah": (k0 + up + 1) * step, "val": (k0 + dn) * step,
           "vpoc": (k0 + vpoc + 0.5) * step if vpoc is not None else None, "volume": sum(vol),
           "delta": (2 * sum(buy) - sum(vol)) if has_tb else None,
           "rows": [[round((k0 + j) * step, 10), cnt[j], "".join(LETTERS[i % len(LETTERS)] for i in lets[j]), round(vol[j], 6),
                     round(2 * buy[j] - vol[j], 6) if has_tb else None] for j in range(n)],
           "br": [[i, h, l, c] for i, h, l, _o, c in br],
           "singles": [], "tailHigh": None, "tailLow": None, "poorHigh": False, "poorLow": False}
    # equilibre des lettres autour du POC et facteur de rotation (+1 / -1 par plus haut et plus bas plus hauts / plus bas que la tranche d'avant)
    out["tpoAbove"], out["tpoBelow"] = sum(cnt[poc + 1:]), sum(cnt[:poc])
    rf = 0
    for (_, h0, l0, _, _), (_, h1, l1, _, _) in zip(br, br[1:]):
        rf += (h1 > h0) - (h1 < h0) + (l1 > l0) - (l1 < l0)
    out["rotation"] = rf
    if ib_ms:
        ib = [b for b in br if b[0] * bracket_ms < ib_ms]
        if ib:
            ih, il = max(b[1] for b in ib), min(b[2] for b in ib)
            rng = max(ih - il, step)
            done = br[-1][0] * bracket_ms >= ib_ms                   # la seance a depasse la premiere heure
            out["ib"] = [il, ih]
            out["ibMs"] = ib_ms
            out["ibStats"] = {"high": ih, "low": il, "range": ih - il, "complete": done,
                              "extUp": max(0.0, hi - ih) / rng, "extDn": max(0.0, il - lo) / rng,
                              "targets": {"up15": ih + 0.5 * rng, "up2": ih + rng, "dn15": il - 0.5 * rng, "dn2": il - rng}}
    if len(br) < 2 or n < 3:
        return out
    top = 0
    while top < n and cnt[n - 1 - top] == 1:
        top += 1
    bot = 0
    while bot < n and cnt[bot] == 1:
        bot += 1
    if top >= n:                                           # tout le profil est en une seule lettre par prix : rien a lire
        return out
    if top >= min_single:
        out["tailHigh"] = [(k0 + n - top) * step, hi]
    if bot >= min_single:
        out["tailLow"] = [lo, (k0 + bot) * step]
    out["poorHigh"] = cnt[n - 1] >= 2                      # au moins deux tranches au plus haut, donc pas de queue
    out["poorLow"] = cnt[0] >= 2
    j = bot
    while j < n - top:
        if cnt[j] == 1:
            s = j
            while j < n - top and cnt[j] == 1:
                j += 1
            if j - s >= min_single:
                out["singles"].append([(k0 + s) * step, (k0 + j) * step])
        else:
            j += 1
    out["shape"] = shape(cnt, poc, out, step)
    return out


def shape(cnt, poc, p, step):
    """Forme du profil a partir des lettres : P, b, D, I (allongee) ou B (deux bosses)."""
    n, tot = len(cnt), sum(cnt)
    if n < 6 or tot <= 0:
        return None
    if p["singles"]:
        s = p["singles"][0]
        a, b = (s[0] - p["low"]) / max(p["high"] - p["low"], step), (s[1] - p["low"]) / max(p["high"] - p["low"], step)
        if 0.15 < a and b < 0.85:
            return "B"
    width = max(cnt) / max(1, p["brackets"])
    if width < 0.3 and p["brackets"] >= 6:
        return "I"
    upper, lower = sum(cnt[int(n * 0.6):]) / tot, sum(cnt[:int(n * 0.4) + 1]) / tot
    pos = (poc + 0.5) / n
    if pos >= 0.6 and upper >= 0.5:
        return "P"
    if pos <= 0.4 and lower >= 0.5:
        return "b"
    return "D"


def day_type(p, typical_range: float | None):
    """Type de journee (J. Dalton) a partir de la premiere heure et des extensions. None tant que la premiere heure n'est pas finie."""
    st = p.get("ibStats")
    if not st or not st["complete"]:
        return None
    up, dn = st["extUp"], st["extDn"]
    rng = p["high"] - p["low"]
    if typical_range and rng < 0.55 * typical_range and up + dn < 0.3:
        return "nontrend"
    if up > 0.15 and dn > 0.15:
        return "neutral"
    ext = max(up, dn)
    if ext <= 0.15:
        return "normal"
    if ext > 0.5 and p.get("shape") == "B":
        return "double"
    if ext > 1.0:
        close_pos = (p["close"] - p["low"]) / max(rng, 1e-12)
        if (up > dn and close_pos >= 0.75) or (dn > up and close_pos <= 0.25):
            return "trend"
    return "normalvar"


def va_relation(cur, prev):
    """Migration de la zone de valeur par rapport a la seance precedente."""
    a, b, pa, pb = cur["val"], cur["vah"], prev["val"], prev["vah"]
    if a >= pb:
        return ("higher", "Valeur plus haute (sans recouvrement) : les acheteurs acceptent des prix plus élevés.")
    if b <= pa:
        return ("lower", "Valeur plus basse (sans recouvrement) : les vendeurs imposent des prix plus bas.")
    if a >= pa and b <= pb:
        return ("inside", "Valeur à l'intérieur de celle d'hier : équilibre, compression avant un mouvement.")
    if a <= pa and b >= pb:
        return ("outside", "Valeur plus large que celle d'hier : volatilité, les deux camps s'affrontent.")
    if b > pb:
        return ("overlapHigher", "Valeur un peu plus haute, en recouvrement : légère pression acheteuse.")
    return ("overlapLower", "Valeur un peu plus basse, en recouvrement : légère pression vendeuse.")


def open_location(cur, prev):
    o = cur["open"]
    if o > prev["high"]:
        return ("aboveRange", "Ouverture au-dessus du plus haut précédent (hors de la fourchette) : déséquilibre acheteur.")
    if o < prev["low"]:
        return ("belowRange", "Ouverture sous le plus bas précédent (hors de la fourchette) : déséquilibre vendeur.")
    if o > prev["vah"]:
        return ("aboveValue", "Ouverture au-dessus de la valeur précédente, dans la fourchette.")
    if o < prev["val"]:
        return ("belowValue", "Ouverture sous la valeur précédente, dans la fourchette.")
    return ("inValue", "Ouverture dans la valeur précédente : journée d'équilibre probable.")


def eighty(cur, prev, bars, step):
    """Regle des 80 % : ouverture hors de la valeur precedente, puis deux tranches consecutives cloturees dans cette valeur -> objectif : l'autre
    bord de la valeur. Renvoie {side, trigger, target, reached} ou None."""
    o, val, vah = cur["open"], prev["val"], prev["vah"]
    side = "up" if o < val else "down" if o > vah else None
    if side is None:
        return None
    inside = 0
    for i, h, l, c in cur["br"]:
        inside = inside + 1 if val <= c <= vah else 0
        if inside >= 2:
            trig = cur["start"] + (i + 1) * cur["bracketMs"]
            target = vah if side == "up" else val
            after = [k for k in bars if trig <= k.t < cur["end"]]
            reached = any(k.h >= target for k in after) if side == "up" else any(k.l <= target for k in after)
            return {"side": side, "trigger": trig, "target": target, "reached": reached}
    return {"side": side, "trigger": None, "target": vah if side == "up" else val, "reached": None}


def suffix_extremes(bars):
    """Plus bas et plus haut a partir de chaque bougie jusqu'a la fin (pour savoir si une marque a ete comblee depuis)."""
    n = len(bars)
    lo, hi = [math.inf] * (n + 1), [-math.inf] * (n + 1)
    for i in range(n - 1, -1, -1):
        lo[i] = min(lo[i + 1], bars[i].l)
        hi[i] = max(hi[i + 1], bars[i].h)
    return lo, hi


def marks(p: dict, after_lo: float, after_hi: float, current: bool) -> dict:
    """Marques a suivre sur les graphiques : single prints comblees ou non (le prix a traverse toute la zone depuis la fin de la seance),
    poor high / poor low toujours actifs ou repares (depasses depuis), POC vierge ou non (jamais retraverse depuis)."""
    return {"start": p["start"], "end": p["end"], "current": current,
            "singles": [[a, b, (not current) and after_lo <= a and after_hi >= b] for a, b in p["singles"]],
            "poorHigh": {"price": p["high"], "active": current or not after_hi > p["high"]} if p["poorHigh"] else None,
            "poorLow": {"price": p["low"], "active": current or not after_lo < p["low"]} if p["poorLow"] else None,
            "poc": {"price": p["poc"], "naked": (not current) and not (after_lo <= p["poc"] <= after_hi)}}


def composite(profiles, step):
    """Profil composite (somme des lettres et des volumes des seances donnees, sur la meme grille) : POC, zone de valeur, noeuds."""
    if not profiles:
        return None
    cnt, vol = {}, {}
    for p in profiles:
        for r in p["rows"]:
            k = round(r[0] / step)
            cnt[k] = cnt.get(k, 0) + r[1]
            vol[k] = vol.get(k, 0.0) + (r[3] or 0.0)
    ks = sorted(cnt)
    k0, n = ks[0], ks[-1] - ks[0] + 1
    c = [cnt.get(k0 + j, 0) for j in range(n)]
    v = [vol.get(k0 + j, 0.0) for j in range(n)]
    mid = (n - 1) / 2
    poc = max(range(n), key=lambda j: (c[j], -abs(j - mid)))
    up, dn = _va(c, poc)
    base = v if sum(v) > 0 else [float(x) for x in c]
    hvn, lvn = nodes(base, k0, step, poc)
    return {"start": profiles[0]["start"], "end": profiles[-1]["end"], "n": len(profiles), "step": step,
            "rows": [[round((k0 + j) * step, 10), c[j], round(v[j], 6)] for j in range(n)],
            "poc": (k0 + poc + 0.5) * step, "vah": (k0 + up + 1) * step, "val": (k0 + dn) * step, "hvn": hvn, "lvn": lvn,
            "high": (k0 + n) * step, "low": k0 * step}


def sessions(bars, kind: str, now_ms: int, n: int | None = None, rows: int | None = None, cache: dict | None = None):
    """Profils des n dernieres seances (en cours comprise), du plus ancien au plus recent, chacun avec ses marques ('marks') et son contexte
    (type de journee, migration de la valeur, ouverture, regle des 80 %). Pas commun a toutes les seances : la mediane de leurs amplitudes
    divisee par `rows`. `cache` garde les seances terminees. S'y ajoutent le profil composite et les POC vierges."""
    spec = KINDS[kind]
    L, n, rows = spec["len"], n or spec["n"], rows or spec["rows"]
    empty = {"kind": kind, "label": spec["label"], "step": None, "sessions": [], "composite": None, "naked": []}
    if not bars:
        return empty
    times = [k.t for k in bars]
    cur = now_ms // L * L
    back = max(n, spec["comp"]) + 1                        # une seance de plus pour le contexte de la premiere affichee
    starts = [s for s in (cur - i * L for i in range(back - 1, -1, -1)) if s + L > times[0]]
    spans = []
    for s in starts:
        i0, i1 = bisect_left(times, s), bisect_left(times, s + L)
        if i1 > i0:
            spans.append((s, i0, i1, max(k.h for k in bars[i0:i1]) - min(k.l for k in bars[i0:i1])))
    if not spans:
        return empty
    rg = sorted(x[3] for x in spans if x[3] > 0) or [1.0]
    step = nice_step(rg[len(rg) // 2] / max(4, rows))
    slo, shi = suffix_extremes(bars)
    if cache is not None and len(cache) > 500:
        cache.clear()
    built = []
    for s, i0, i1, r in spans:
        current = s == cur
        key = (kind, s, step, "v19")
        p = None if current or cache is None else cache.get(key)
        if p is None:
            p = profile(bars[i0:i1], s, s + L, spec["bracket"], step, ib_ms=spec["ib"])
            if p is None:
                continue
            if cache is not None and not current:
                cache[key] = p
        built.append((p, i0, i1, r, current))
    out = []
    for idx, (p, i0, i1, r, current) in enumerate(built):
        prev = built[idx - 1][0] if idx > 0 and built[idx - 1][0]["end"] == p["start"] else None
        typical = sorted(x[3] for x in built[max(0, idx - 10):idx]) if idx else []
        ctx = {"dayType": None, "va": None, "open": None, "eighty": None}
        dt = day_type(p, typical[len(typical) // 2] if typical else None)
        if dt:
            ctx["dayType"] = {"code": dt, "label": DAY_TYPES[dt][0], "text": DAY_TYPES[dt][1], "provisional": current}
        if prev:
            ctx["va"] = dict(zip(("code", "text"), va_relation(p, prev)))
            ctx["open"] = dict(zip(("code", "text"), open_location(p, prev)))
            ctx["eighty"] = eighty(p, prev, bars[i0:i1], step)
        out.append({**p, "label": spec["label"], "marks": marks(p, slo[i1], shi[i1], current), "ctx": ctx,
                    "shapeText": SHAPES.get(p.get("shape"))})
    done = [x for x in out if not x["marks"]["current"]]
    comp = composite(done[-spec["comp"]:], step)
    naked = [{"start": x["start"], "price": x["poc"], "age": len(out) - 1 - i} for i, x in enumerate(out) if x["marks"]["poc"]["naked"]]
    return {"kind": kind, "label": spec["label"], "step": step, "sessions": out[-n:], "composite": comp, "naked": naked}
