"""Rejeu historique des idees de trade : qu'aurait donne la STRUCTURE (niveaux + geometrie) depuis 2019 ?

On rejoue les bougies 1h fermees dans l'ordre. A chaque instant (toutes les 2 h) on reconstruit les niveaux connus a
ce moment-la (VWAP jour / semaine / mois / annee et bandes, ouvertures, plus hauts / plus bas precedents, profils de
volume courants et precedents, POC nus), les zones de confluence, puis les idees avec EXACTEMENT les memes regles que
le terminal en direct (signals.build_ideas). Chaque idee est jouee sur les bougies suivantes :
  - ordre limite valable `valid_hours` ; annule si le stop est touche avant l'execution ;
  - apres execution : stop, objectif 1 ou sortie au marche apres `hold_hours` ;
  - si stop et objectif sont dans la meme bougie, le STOP est compte en premier (hypothese prudente).
Comparaison : pour chaque idee, 3 « temoins » de meme forme (meme distance d'entree, meme stop, meme objectif en
amplitudes d'heure) places a des heures tirees au hasard. Seul l'ecart au temoin mesure ce que la qualite du niveau apporte.

Limites assumees : l'historique des poches de liquidation (29 jours), des annonces et du flux d'ordres n'existe pas sur
7 ans : le rejeu mesure la structure seule. Les ordres sont supposes executes au prix limite, sans frais ni glissement."""
import random
import time

from . import signals
from .confluence import Level, find_zones
from .periods import NakedPocs, PeriodTracker
from .stats import atr_series, wilson

VERSION = 1
TIERS = (7.0, 9.0, 11.0)
WARMUP = 24 * 60
DAY_MS = 86_400_000


def _levels(tr, nd, nw, cur_vp, i, price, now):
    """Niveaux connus a la cloture de la bougie i (memes noms et memes groupes que le terminal en direct)."""
    out, seen = [], {}

    def add(name, px, group, kind, **extra):
        if px is None:
            return
        n = seen.get(group + name, 0)
        seen[group + name] = n + 1
        out.append(Level(f"{group}|{name}{n or ''}", name, float(px), group, kind, extra))

    for kind in ("D", "W", "M", "Y"):
        t = tr[kind]
        p = kind.lower()
        a = t.acc
        vw, sd = a.vwap()
        add(f"{p}VWAP", vw, f"{p}VWAP", "vwap")
        if kind != "Y" and vw is not None and sd:
            add(f"{p}VWAP+2σ", vw + 2 * sd, f"{p}VWAP", "band")
            add(f"{p}VWAP-2σ", vw - 2 * sd, f"{p}VWAP", "band")
        add(f"{p}Open", a.open, f"{p}Open", "open")
        c = cur_vp.get(kind)
        if c is None or c[0] != t.key or i - c[1] >= 6:
            c = cur_vp[kind] = (t.key, i, t._cur_vp())
        if c[2]:
            add(f"{p}POC", c[2]["poc"], f"{p}VP", "vp")
            for h in c[2]["hvn"]:
                add(f"{p}HVN", h, f"{p}VP", "vp")
        pv = t.prev
        if pv:
            add(f"P{kind}H", pv["high"], f"P{kind}HL", "hl")
            add(f"P{kind}L", pv["low"], f"P{kind}HL", "hl")
            if pv["vp"]:
                g = f"p{p}VP"
                add(f"p{p}POC", pv["vp"]["poc"], g, "vp")
                add(f"p{p}VAH", pv["vp"]["vah"], g, "vp")
                add(f"p{p}VAL", pv["vp"]["val"], g, "vp")
                for h in pv["vp"]["hvn"]:
                    add(f"p{p}HVN", h, g, "vp")
    for unit, nk, span in (("J", nd, DAY_MS), ("S", nw, 7 * DAY_MS)):
        for x in nk.active():
            if abs(x["poc"] / price - 1.0) <= 0.15:
                age = max(2, -(-(now - x["t_end"]) // span) + 1)
                add(f"nPOC {unit}-{age}", x["poc"], "nPOC", "npoc")
    return out


def simulate(candles, i0, side, entry, stop, tp1, market, valid_h=48, hold_h=72):
    """Joue une idee creee a la cloture de la bougie i0. Renvoie (statut, R, fill) ;
    statut : 'nofill' | 'cancel' | 'tp' | 'sl' | 'timeout'."""
    n = len(candles)
    risk = abs(entry - stop)
    if risk <= 0:
        return "cancel", 0.0, False
    long_ = side == "long"
    fill = i0 if market else None
    j = i0 + 1
    if fill is None:
        end = min(n, i0 + 1 + valid_h)
        while j < end:
            k = candles[j]
            hit_entry = k.l <= entry if long_ else k.h >= entry
            if hit_entry:
                fill = j
                if (k.l <= stop) if long_ else (k.h >= stop):
                    return "sl", -1.0, True                           # execute puis stoppe dans la meme bougie
                break
            if (k.l <= stop) if long_ else (k.h >= stop):
                return "cancel", 0.0, False                           # le stop est touche avant l'execution
            j += 1
        if fill is None:
            return ("nofill" if i0 + 1 + valid_h <= n else "open"), 0.0, False
        j = fill + 1
    end = min(n, j + hold_h)
    if j >= n:
        return "open", 0.0, True
    for q in range(j, end):
        k = candles[q]
        if (k.l <= stop) if long_ else (k.h >= stop):
            return "sl", -1.0, True
        if (k.h >= tp1) if long_ else (k.l <= tp1):
            return "tp", abs(tp1 - entry) / risk, True
    if end - j < hold_h:
        return "open", 0.0, True                                      # periode de detention pas finie
    c = candles[end - 1].c
    return "timeout", ((c - entry) if long_ else (entry - c)) / risk, True


def _agg(rows):
    """rows : [(statut, R, fill)] -> comptes et taux."""
    res = [r for r in rows if r[0] != "open"]
    fl = [r for r in res if r[2]]
    tp = sum(1 for r in fl if r[0] == "tp")
    sl = sum(1 for r in fl if r[0] == "sl")
    to = sum(1 for r in fl if r[0] == "timeout")
    out = {"n": len(res), "filled": len(fl), "tp": tp, "sl": sl, "timeout": to,
           "fillRate": len(fl) / len(res) if res else None,
           "expR": sum(r[1] for r in fl) / len(fl) if fl else None}
    p, lo, hi = wilson(tp, tp + sl) if tp + sl else (None, None, None)
    out["win"] = {"p": p, "lo": lo, "hi": hi}
    return out


def verdict(real, ctrl):
    a, b = real["win"], ctrl["win"]
    if real["tp"] + real["sl"] < 30 or a["p"] is None or b["p"] is None:
        return "thin"
    if a["lo"] > b["hi"]:
        return "edge"
    if a["hi"] < b["lo"]:
        return "worse"
    return "none"


def replay(candles, atrs=None, params=None, seed=5, step=2, ctrl_n=3, max_week=5):
    """Rejoue `candles` (bougies 1h fermees). Renvoie les resultats par palier de qualite et la frequence par semaine."""
    o = {**signals.DEFAULTS, **(params or {})}
    atrs = atrs or atr_series(candles)
    n = len(candles)
    if n < WARMUP + 24 * 30:
        return {"ready": False, "bars": n}
    rnd = random.Random(seed)
    tr = {k: PeriodTracker(k) for k in ("D", "W", "M", "Y")}
    nd, nw = NakedPocs(30), NakedPocs(12)
    cur_vp: dict = {}
    min_s = o["min_struct"]
    ideas_all = []                               # idees acceptees sans quota : (t, semaine, S, cote, resultat, temoins)
    last_zone: dict = {}
    last_side: dict = {}
    t0 = time.time()
    for i in range(n - 1):
        k = candles[i]
        prev_d, prev_w = tr["D"].prev, tr["W"].prev
        for t in tr.values():
            t.feed(k)
        if tr["D"].prev is not prev_d and tr["D"].prev:
            nd.on_rollover(tr["D"].prev["vp"]["poc"] if tr["D"].prev["vp"] else None, k.t)
        if tr["W"].prev is not prev_w and tr["W"].prev:
            nw.on_rollover(tr["W"].prev["vp"]["poc"] if tr["W"].prev["vp"] else None, k.t)
        nd.feed(k)
        nw.feed(k)
        if i < WARMUP or i % step or i + 1 + o["valid_hours"] + 72 >= n:
            continue
        a = atrs[i]
        price = k.c
        if not a or a <= 0:
            continue
        lvs = _levels(tr, nd, nw, cur_vp, i, price, k.t + 3_600_000)
        tol = max(0.30 * a, 0.0015 * price)
        zones = []
        for z, zz in enumerate(find_zones(lvs, tol)):
            inside = zz["lo"] <= price <= zz["hi"]
            zones.append({"id": f"z{z}", "mid": zz["mid"], "lo": zz["lo"], "hi": zz["hi"],
                          "side": "in" if inside else ("above" if zz["mid"] > price else "below"),
                          "members": [m.id for m in zz["members"]], "groups": zz["groups"]})
        levels = [{"id": l.id, "name": l.name, "price": l.price, "group": l.group, "kind": l.kind} for l in lvs]
        ideas, _ = signals.build_ideas({"symbol": "x", "now": k.t + 3_600_000, "price": price, "atr": a, "levels": levels, "zones": zones,
                                        "pools": [], "sweeps": [], "candles": candles[max(0, i - 11):i + 1], "opts": o})
        for idea in sorted(ideas, key=lambda x: -x["st"]["S"]):
            gkey = "+".join(sorted(it["group"] for it in idea["st"]["items"]))
            if idea["st"]["S"] < min_s or k.t - last_zone.get((idea["side"], gkey), -10 ** 15) < 48 * 3_600_000 \
                    or k.t - last_side.get(idea["side"], -10 ** 15) < 12 * 3_600_000:
                continue
            last_zone[(idea["side"], gkey)] = k.t
            last_side[idea["side"]] = k.t
            market = idea["entryType"] == "marché"
            res = simulate(candles, i, idea["side"], idea["entry"], idea["stop"], idea["tp1"], market, o["valid_hours"])
            # temoins : meme forme (en amplitudes d'heure) a des heures tirees au hasard
            sgn = 1 if idea["side"] == "long" else -1
            de = (price - idea["entry"]) / a * sgn if not market else 0.0
            sd_ = abs(idea["entry"] - idea["stop"]) / a
            td = abs(idea["tp1"] - idea["entry"]) / a
            ctrl = []
            for _ in range(ctrl_n):
                j0 = rnd.randrange(WARMUP, n - o["valid_hours"] - 74)
                cp, ca = candles[j0].c, atrs[j0]
                if not ca:
                    continue
                e = cp - sgn * de * ca if not market else cp
                s_ = e - sgn * sd_ * ca
                t_ = e + sgn * td * ca
                ctrl.append(simulate(candles, j0, idea["side"], e, s_, t_, market, o["valid_hours"]))
            ideas_all.append((k.t, (k.t // DAY_MS + 3) // 7, idea["st"]["S"], idea["side"], res, ctrl))
    first_w = (candles[WARMUP].t // DAY_MS + 3) // 7
    last_w = (candles[-1].t // DAY_MS + 3) // 7
    total_w = max(1, last_w - first_w + 1)

    def keep(ms):
        """Ce que tu aurais recu avec ce seuil de qualite : au plus `max_week` idees par semaine, la derniere place exigeant mieux."""
        used: dict[int, int] = {}
        out = []
        for it in ideas_all:
            if it[2] < ms:
                continue
            u = used.get(it[1], 0)
            if u >= max_week or (u == max_week - 1 and it[2] < ms + 1.5):
                continue
            used[it[1]] = u + 1
            out.append(it)
        return out, used

    tiers = []
    for ms in TIERS:
        sel, used = keep(ms)
        counts = sorted(used.get(w, 0) for w in range(first_w, last_w + 1))
        real = _agg([t[4] for t in sel])
        ctrl = _agg([c for t in sel for c in t[5]])
        tiers.append({"minS": ms, "real": real, "ctrl": ctrl, "verdict": verdict(real, ctrl),
                      "perWeek": {"mean": sum(counts) / total_w, "p90": counts[int(0.9 * (len(counts) - 1))],
                                  "zeroShare": sum(1 for c in counts if c == 0) / total_w}})
    sel, _ = keep(min_s)
    sides = {}
    for sd in ("long", "short"):
        x = [t for t in sel if t[3] == sd]
        real, ctrl = _agg([t[4] for t in x]), _agg([c for t in x for c in t[5]])
        sides[sd] = {"real": real, "ctrl": ctrl, "verdict": verdict(real, ctrl)}
    return {"ready": True, "version": VERSION, "bars": n, "from": candles[WARMUP].t, "to": candles[-1].t,
            "computedAt": int(time.time() * 1000), "seconds": round(time.time() - t0, 1), "ideas": len(ideas_all),
            "weeks": total_w, "cap": max_week, "tiers": tiers, "sides": sides,
            "params": {"minStruct": min_s, "validHours": o["valid_hours"], "holdHours": 72, "step": step, "ctrl": ctrl_n}}


def tier_for(val, S):
    """Palier de qualite le plus eleve atteint par S (None si aucun)."""
    if not val or not val.get("ready"):
        return None
    best = None
    for t in val["tiers"]:
        if S >= t["minS"]:
            best = t
    return best


def validation_text(val, S, side=None):
    """Phrase en clair sur ce que cette qualite de niveau a donne dans le passe, face aux temoins au hasard."""
    t = tier_for(val, S)
    if not t:
        return None
    r, c = t["real"], t["ctrl"]
    if not r["tp"] + r["sl"]:
        return None
    since = time.strftime("%m/%Y", time.gmtime(val["from"] / 1000))
    base = (f"Rejeu de la structure depuis {since} (zones de qualité ≥ {t['minS']:.0f}, sans poches ni annonces) : "
            f"{r['n']} idées, {r['filled']} exécutées ; objectif 1 atteint avant le stop dans {r['win']['p'] * 100:.0f} % des cas résolus "
            f"({r['win']['lo'] * 100:.0f}-{r['win']['hi'] * 100:.0f} %), contre {c['win']['p'] * 100:.0f} % pour des entrées au hasard de même forme. ")
    return base + {"edge": "→ MIEUX que le hasard.", "none": "→ pas de différence prouvée avec le hasard : à prendre comme un scénario, pas comme un avantage démontré.",
                   "worse": "→ moins bien que le hasard.", "thin": "→ trop peu de cas pour conclure."}[t["verdict"]]
