"""Etude de la cassure de la bascule du gamma (V41.1) : quand le prix passe du gamma positif au gamma negatif (les teneurs de marche
devraient alors vendre la baisse) ou l'inverse, de combien va le mouvement a partir de la cassure avant de se retourner ?

Donnees : une suite d'instantanes du gamma ({"t": instant ou il est connu, "flip": bascule, "flips": toutes les bascules, "curve": gamma
par prix, facultatif}) et des bougies 1 minute. Sans courbe, la zone vient de la seule bascule : gamma positif au-dessus, negatif en dessous
(c'est la forme observee a chaque heure sur les archives Binance 2023).

Evenement : la cloture d'une minute passe de l'autre cote d'une bascule de l'instantane en cours (pas un simple changement d'instantane),
apres au moins `hold` minutes de l'autre cote, au plus un evenement par sens toutes les `cool` millisecondes. Mesures a partir de la cloture
de la minute de cassure :
  - mouvement avant retournement : plus grand ecart dans le sens attendu avant un retour de R % depuis l'extreme (R = 1, 2, 3 %) ;
  - plus grands ecarts pour et contre, et variation, a 4 h, 24 h et 72 h ;
  - course : le prix fait-il X % dans le sens attendu avant X % contre (X = 1, 2 %) ;
  - retour au-dessus (ou en dessous) du niveau casse en 4 h et en 24 h.
Temoins : les memes mesures depuis chaque heure pleine de la periode, et un tirage au hasard du meme nombre d'heures (part des tirages qui
font au moins aussi bien que les cassures). Module PUR."""
from __future__ import annotations
import bisect
import random
import statistics

MIN, H, DAY = 60_000, 3_600_000, 86_400_000
REVERSALS = (1, 2, 3)
HORIZONS = (("4h", 4 * H), ("24h", DAY), ("72h", 3 * DAY))


def zone(snap: dict, price: float) -> int:
    """+1 gamma positif, -1 gamma negatif, 0 inconnu (hors de la courbe)."""
    curve = snap.get("curve")
    if curve:
        ps = [q[0] for q in curve]
        i = bisect.bisect_left(ps, price)
        if i <= 0 or i >= len(ps):
            return 0
        (p0, v0), (p1, v1) = curve[i - 1], curve[i]
        v = v0 + (v1 - v0) * (price - p0) / (p1 - p0)
        return 1 if v > 0 else -1 if v < 0 else 0
    f = snap.get("flip")
    if not f:
        return 0
    return 1 if price > f else -1 if price < f else 0


def events(snaps: list[dict], bars, hold: int = 60, cool: int = DAY, max_age: int = 2 * H) -> list[dict]:
    """bars = (t, h, l, c), listes alignees. d = -1 : passage en gamma negatif (baisse attendue), +1 : passage en gamma positif."""
    t, _, _, c = bars
    st_t = [s["t"] for s in snaps]
    out, last = [], {1: -10 ** 18, -1: -10 ** 18}
    run, prev = {1: 0, -1: 0}, None
    for i in range(1, len(t)):
        j = bisect.bisect_right(st_t, t[i]) - 1                  # instantane deja connu a cette minute (aucun regard vers le futur)
        if j < 0 or t[i] - st_t[j] > max_age:
            prev, run = None, {1: 0, -1: 0}
            continue
        s = snaps[j]
        cur, before = zone(s, c[i]), zone(s, c[i - 1])
        if before and cur and before != cur and prev == before and run[before] >= hold and t[i] - last[cur] >= cool:
            lo, hi = min(c[i - 1], c[i]), max(c[i - 1], c[i])
            crossed = [f for f in (s.get("flips") or [s.get("flip")]) if f and lo <= f <= hi]
            out.append({"i": i, "t": t[i], "d": cur, "level": crossed[0] if crossed else s.get("flip"), "price": c[i]})
            last[cur] = t[i]
        if cur:
            run[cur] = run[cur] + 1 if cur == prev else 1
            run[-cur] = 0
        prev = cur
    return out


def reversal_move(bars, i0: int, d: int, r_pct: float, cap: int = 30 * DAY):
    """(mouvement en %, minutes jusqu'a l'extreme) avant un retour de r_pct % depuis l'extreme ; None si pas fini dans `cap`."""
    t, h, l, c = bars
    p0 = c[i0]
    ext, k_ext = p0, i0
    for k in range(i0 + 1, len(t)):
        if t[k] - t[i0] > cap:
            return None
        if d < 0:
            if l[k] < ext:
                ext, k_ext = l[k], k
            if h[k] >= ext * (1 + r_pct / 100):
                return (p0 - ext) / p0 * 100, (t[k_ext] - t[i0]) / MIN
        else:
            if h[k] > ext:
                ext, k_ext = h[k], k
            if l[k] <= ext * (1 - r_pct / 100):
                return (ext - p0) / p0 * 100, (t[k_ext] - t[i0]) / MIN
    return None


def excursions(bars, i0: int, d: int, horizon: int):
    """(ecart pour, ecart contre, variation) en % sur `horizon` ; None si les bougies ne couvrent pas tout l'horizon."""
    t, h, l, c = bars
    p0 = c[i0]
    j = bisect.bisect_right(t, t[i0] + horizon)
    if j >= len(t) or j <= i0 + 1 or t[j - 1] < t[i0] + horizon - 5 * MIN:
        return None
    lo, hi = min(l[i0 + 1:j]), max(h[i0 + 1:j])
    fav = ((p0 - lo) if d < 0 else (hi - p0)) / p0 * 100
    adv = ((hi - p0) if d < 0 else (p0 - lo)) / p0 * 100
    return fav, adv, d * (c[j - 1] - p0) / p0 * 100


def race(bars, i0: int, d: int, x_pct: float, cap: int = 30 * DAY):
    """1 si X % dans le sens attendu arrive avant X % contre, 0 sinon, None si indecis (meme minute) ou pas fini."""
    t, h, l, c = bars
    up, dn = c[i0] * (1 + x_pct / 100), c[i0] * (1 - x_pct / 100)
    for k in range(i0 + 1, len(t)):
        if t[k] - t[i0] > cap:
            return None
        hu, hd = h[k] >= up, l[k] <= dn
        if hu and hd:
            return None
        if hu or hd:
            return int(hd if d < 0 else hu)
    return None


def back_through(bars, i0: int, d: int, level: float, horizon: int) -> int:
    """1 si une cloture repasse de l'autre cote du niveau casse dans `horizon` (fausse cassure)."""
    t, _, _, c = bars
    j = bisect.bisect_right(t, t[i0] + horizon)
    return int(any((x > level) if d < 0 else (x < level) for x in c[i0 + 1:j]))


def summary(vals) -> dict | None:
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
    return {"n": len(v), "mean": statistics.mean(v), "median": statistics.median(v), "p25": q(0.25), "p75": q(0.75), "p90": q(0.9)}


def measure(bars, starts: list[int], d: int, levels: dict | None = None) -> dict:
    out: dict = {"n": len(starts)}
    for r in REVERSALS:
        z = [reversal_move(bars, i, d, r) for i in starts]
        out[f"move{r}"] = summary(x[0] for x in z if x)
        out[f"move{r}_raw"] = [round(x[0], 4) for x in z if x]
        out[f"time{r}"] = summary(x[1] for x in z if x)
    for name, hz in HORIZONS:
        e = [x for x in (excursions(bars, i, d, hz) for i in starts) if x]
        out[f"for{name}"], out[f"against{name}"], out[f"ret{name}"] = summary(x[0] for x in e), summary(x[1] for x in e), summary(x[2] for x in e)
        out[f"win{name}"] = sum(1 for x in e if x[2] > 0) / len(e) if e else None
    for x in (1, 2):
        rr = [v for v in (race(bars, i, d, x) for i in starts) if v is not None]
        out[f"race{x}"] = {"share": sum(rr) / len(rr), "n": len(rr)} if rr else None
    if levels:
        for name, hz in (("4h", 4 * H), ("24h", DAY)):
            b = [back_through(bars, i, d, levels[i], hz) for i in starts if levels.get(i)]
            out[f"back{name}"] = sum(b) / len(b) if b else None
    return out


def chance(ev: list[float], base: list[float], draws: int = 4000, seed: int = 5) -> float | None:
    """Part des tirages au hasard (meme nombre d'heures temoins) dont la moyenne est au moins celle des cassures."""
    if not ev or len(base) < len(ev):
        return None
    m, rnd = statistics.mean(ev), random.Random(seed)
    return sum(statistics.mean(rnd.sample(base, len(ev))) >= m for _ in range(draws)) / draws


def study(snaps: list[dict], bars, hold: int = 60, cool: int = DAY, max_age: int = 2 * H, base: bool = True) -> dict:
    """Etude complete : cassures vers le gamma negatif (baisse) et vers le gamma positif (hausse), temoins, part due au hasard."""
    snaps = sorted((s for s in snaps if s.get("flip") or s.get("curve")), key=lambda s: s["t"])
    if not snaps or not bars[0]:
        return {"ok": False, "why": "pas assez de données"}
    t = bars[0]
    ev = events(snaps, bars, hold, cool, max_age)
    rep = {"ok": True, "from": snaps[0]["t"], "to": snaps[-1]["t"], "snaps": len(snaps), "hold": hold, "cool_h": cool / H}
    hours = [i for i in range(len(t)) if snaps[0]["t"] <= t[i] <= snaps[-1]["t"] and t[i] % H == 0] if base else []
    for d, name in ((-1, "down"), (1, "up")):
        e = [x for x in ev if x["d"] == d]
        m = measure(bars, [x["i"] for x in e], d, {x["i"]: x["level"] for x in e})
        m["events"] = [{"t": x["t"], "level": x["level"], "price": x["price"]} for x in e]
        if hours:
            b = measure(bars, hours, d)
            m["chance"] = {f"move{r}": chance(m[f"move{r}_raw"], b[f"move{r}_raw"]) for r in REVERSALS}
            for k in [k for k in b if k.endswith("_raw")]:
                b.pop(k)
            rep[f"base_{name}"] = b
        rep[name] = m
    return rep


def _p(x, k="mean", dec=2):
    return "—" if not x else f"{x[k]:.{dec}f} %"


def text(rep: dict, title: str) -> str:
    """Compte rendu en francais clair."""
    if not rep.get("ok"):
        return f"{title} : {rep.get('why')}"
    lines = [title, f"{rep['snaps']} instantanés du gamma ; cassure retenue après {rep['hold']} minutes de l'autre côté, au plus une par sens toutes les {rep['cool_h']:.0f} heures."]
    for name, label in (("down", "Cassure vers le gamma NÉGATIF (baisse attendue)"), ("up", "Cassure vers le gamma POSITIF (hausse attendue)")):
        m, b = rep[name], rep.get(f"base_{name}")
        lines.append(f"\n{label} : {m['n']} cassures")
        for r in REVERSALS:
            mv, tm = m[f"move{r}"], m[f"time{r}"]
            row = f"  avant un retour de {r} % : moyenne {_p(mv)}, médiane {_p(mv, 'median')}, 3 cas sur 4 sous {_p(mv, 'p75')}"
            if tm:
                row += f", extrême atteint en {tm['median'] / 60:.1f} h (médiane)"
            if b:
                row += f" | heures au hasard : moyenne {_p(b[f'move{r}'])}"
            ch = (m.get("chance") or {}).get(f"move{r}")
            if ch is not None:
                row += f" | hasard au moins aussi bon : {ch * 100:.0f} %"
            lines.append(row)
        for x in (1, 2):
            rc, rb = m.get(f"race{x}"), (b or {}).get(f"race{x}")
            if rc:
                lines.append(f"  {x} % dans le bon sens avant {x} % contre : {rc['share'] * 100:.0f} % des cas" + (f" (hasard : {rb['share'] * 100:.0f} %)" if rb else ""))
        if m.get("back4h") is not None:
            lines.append(f"  le prix revient de l'autre côté du niveau cassé : {m['back4h'] * 100:.0f} % en 4 h, {m['back24h'] * 100:.0f} % en 24 h")
        r24 = m.get("ret24h")
        if r24:
            lines.append(f"  variation à 24 h dans le sens attendu : moyenne {_p(r24)}, positive {m['win24h'] * 100:.0f} % du temps")
    return "\n".join(lines)
