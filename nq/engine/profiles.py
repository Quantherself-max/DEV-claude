"""Profils composites (semaine, mois), POC vierges et single prints. Module PUR (lit un `Market`, ne modifie rien).

  - Profil COMPOSITE : la somme des profils Globex (24 h) des journées de trading d'une semaine (lundi -> vendredi, semaine ISO de la
    journée de trading) ou d'un mois civil. Même lecture que le profil du jour (POC, zone de valeur 70 %, HVN / LVN), à l'échelle où les gros
    intervenants travaillent. Les journées passées ne changent plus : leur somme est gardée en cache, seule la journée en cours est ajoutée.
  - POC VIERGE (« naked POC ») : le POC d'une séance régulière passée (ou d'une semaine passée) que le prix n'a JAMAIS retouché depuis la fin
    de ce profil. Un aimant classique : le marché revient souvent « finir le travail ». Le futur trade presque 23 h sur 24 : l'ensemble des prix
    traités après un instant est un intervalle continu [plus bas, plus haut] ; un POC est vierge s'il est en dehors.
  - SINGLE PRINTS (lecture TPO de la séance régulière, périodes de 30 min) : prix traités pendant UNE SEULE période, au milieu du profil —
    le prix y est passé vite, sans échange des deux côtés. Aux extrémités, ce sont des QUEUES (excès : rejet net). Les single prints d'une
    séance passée que le prix n'a pas « comblés » (retraités depuis) restent des cibles et des supports / résistances de scalping.
Tout se calcule sur les barres de 1 minute (plus haut / plus bas) et les profils déjà tenus par le marché."""
from bisect import bisect_left
from datetime import date, timedelta

from . import clock, vp
from .footprint import Ladder

TPO_MS = 30 * 60_000


def week_key(day: str) -> str:
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-S{w:02d}"


def month_key(day: str) -> str:
    return day[:7]


def period_start(day: str, kind: str) -> str:
    """Premier jour ouvré (lundi -> vendredi) de la semaine ou du mois de `day` (jours fériés ignorés)."""
    d = date.fromisoformat(day)
    d = d - timedelta(days=d.weekday()) if kind == "week" else d.replace(day=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def covers(mk, start: str) -> bool:
    """L'historique gardé commence-t-il au plus tard à `start` ? Sinon un profil / VWAP de cette période serait tronqué."""
    return bool(mk.gx) and min(mk.gx) <= start


def _merge(ladders, tick) -> Ladder:
    out = Ladder(tick)
    for lad in ladders:
        if lad is not None and not lad.empty():
            out.add_rows({k: (r[0], r[1]) for k, r in lad.rows.items()})
    return out


class Composer:
    """Profils composites avec cache des journées passées (une journée close ne change plus)."""
    def __init__(self):
        self._past = {}                 # (clé de période, jours passés, volumes) -> Ladder

    def composite(self, mk, which: str, day: str | None = None):
        """(Ladder, libellé, [jours]) pour `which` dans week / pweek / month / pmonth ; (None, libellé, []) si rien."""
        with mk.lock:
            day = day or mk.day()
            if day is None:
                return None, "", []
            days = sorted(mk.gx)
            if which in ("week", "pweek"):
                key_fn, lab = week_key, "Semaine"
            else:
                key_fn, lab = month_key, "Mois"
            k = key_fn(day)
            if which in ("pweek", "pmonth"):
                before = sorted({key_fn(d) for d in days if key_fn(d) < k})
                if not before:
                    return None, lab + " précédente" if which == "pweek" else lab + " précédent", []
                k = before[-1]
                lab = "Semaine précédente" if which == "pweek" else "Mois précédent"
            sel = [d for d in days if key_fn(d) == k]
            past = [d for d in sel if d < day]
            cur = [d for d in sel if d >= day]
            ck = (which, k, tuple(past), tuple(round(mk.gx[d].volume, 3) for d in past))
            base = self._past.get(ck)
            if base is None:
                base = _merge([mk.gx[d] for d in past], mk.inst.tick)
                if len(self._past) > 16:
                    self._past.clear()
                self._past[ck] = base
            lad = base.copy() if cur else base
            for d in cur:
                lad.add_rows({i: (r[0], r[1]) for i, r in mk.gx[d].rows.items()})
            if lad.empty():
                return None, lab, sel
            n = len(sel)
            part = "" if covers(mk, period_start(sel[0], "week" if which in ("week", "pweek") else "month")) else ", incomplet"
            return lad, f"{lab} ({n} j{part})", sel


class _After:
    """Plus bas / plus haut de toutes les barres ouvertes à partir d'un instant (suffixes), sur les barres de base du marché."""
    def __init__(self, bars):
        self.ts = [b.t for b in bars]
        n = len(bars)
        self.lo = [0.0] * n
        self.hi = [0.0] * n
        lo, hi = float("inf"), float("-inf")
        for j in range(n - 1, -1, -1):
            lo, hi = min(lo, bars[j].l), max(hi, bars[j].h)
            self.lo[j], self.hi[j] = lo, hi

    def range_from(self, t: int):
        j = bisect_left(self.ts, t)
        return None if j >= len(self.ts) else (self.lo[j], self.hi[j])


def naked_pocs(mk, max_days: int = 20, weekly: bool = True, after=None) -> list:
    """POC vierges des séances régulières passées (et des semaines passées) : [{price, kind ('jour'|'semaine'), day/label, age}]."""
    out = []
    with mk.lock:
        if mk.last is None:
            return out
        today = mk.day()
        after = after or _After(mk.series.bars)
        past_days = [d for d in sorted(mk.rth) if d < today][-max_days:]
        prev = past_days[-1] if past_days else None                    # le POC de la veille est déjà un niveau (« POC veille »)
        for d in past_days:
            if d == prev:
                continue
            lad = mk.rth[d]
            if lad.empty():
                continue
            st = vp.stats(lad, min_row_ticks=4)
            rng = after.range_from(clock.window(d, "rth")[1])
            if st and rng and not (rng[0] <= st["poc"] <= rng[1]):
                out.append({"price": st["poc"], "kind": "jour", "day": d, "label": f"nPOC {d[8:10]}/{d[5:7]}", "age": len(past_days) - past_days.index(d)})
        if weekly:
            cur_w = week_key(today)
            weeks = sorted({week_key(d) for d in mk.gx if week_key(d) < cur_w})
            for wk in weeks:
                ds = [d for d in sorted(mk.gx) if week_key(d) == wk]
                if not covers(mk, period_start(ds[0], "week")):         # semaine coupée par l'historique gardé : son POC serait faux
                    continue
                lad = _merge([mk.gx[d] for d in ds], mk.inst.tick)
                if lad.empty():
                    continue
                st = vp.stats(lad, min_row_ticks=4)
                rng = after.range_from(clock.window(ds[-1], "globex")[1])
                if st and rng and not (rng[0] <= st["poc"] <= rng[1]):
                    out.append({"price": st["poc"], "kind": "semaine", "day": ds[-1], "label": f"nPOC sem. {wk[-2:]}", "age": None})
    return out


def single_prints(mk, day: str, row_ticks: int = 4, min_rows: int = 3, after=None) -> list:
    """Single prints et queues de la séance régulière `day` (lecture TPO, périodes de 30 min).
    [{lo, hi, kind: 'single'|'queue haute'|'queue basse', day, filled: 0..1 (part retraitée depuis la fin de la séance), current}]."""
    out = []
    with mk.lock:
        a, b = clock.window(day, "rth")
        now = mk.now_ms()
        if now is None or now <= a:
            return out
        bars = mk.slice(a, min(b, now + 1))
        if not bars:
            return out
        tick = mk.inst.tick
        cur_period = (now - a) // TPO_MS if now < b else None        # période en cours (incomplète) : pas encore lue
        per_row: dict = {}
        for x in bars:
            pr = (x.t - a) // TPO_MS
            r0, r1 = int(round(x.l / tick)) // row_ticks, int(round(x.h / tick)) // row_ticks
            for r in range(r0, r1 + 1):
                per_row.setdefault(r, set()).add(pr)
        if len({p for s in per_row.values() for p in s}) < 2:
            return out
        lo_r, hi_r = min(per_row), max(per_row)
        single = {r for r, s in per_row.items() if len(s) == 1 and not (cur_period is not None and s == {cur_period})}
        runs, run = [], []
        for r in range(lo_r, hi_r + 1):
            if r in single:
                run.append(r)
            else:
                if len(run) >= min_rows:
                    runs.append(run)
                run = []
        if len(run) >= min_rows:
            runs.append(run)
        ended = now >= b
        rng = None
        if ended:
            after = after or _After(mk.series.bars)
            rng = after.range_from(b)
        s_lo, s_hi = min(x.l for x in bars), max(x.h for x in bars)
        for run in runs:
            lo = max(run[0] * row_ticks * tick, s_lo)                  # une ligne déborde l'extrême de la séance : on borne
            hi = min((run[-1] * row_ticks + row_ticks - 1) * tick, s_hi)
            kind = "queue haute" if run[-1] == hi_r else "queue basse" if run[0] == lo_r else "single"
            filled = 0.0
            if rng is not None:
                ov = max(0.0, min(hi, rng[1]) - max(lo, rng[0]))
                filled = 1.0 if hi <= lo else min(1.0, ov / (hi - lo))
            out.append({"lo": round(lo, 10), "hi": round(hi, 10), "kind": kind, "day": day, "filled": round(filled, 2), "current": not ended})
    return out
