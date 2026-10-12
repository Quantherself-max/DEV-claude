"""Lecture de la seance : l'essentiel d'un coup d'oeil, avec un verdict par ligne. Module PUR.

Ce n'est PAS un generateur de signaux. Chaque ligne decrit un fait mesure (position face au VWAP, a la zone de valeur, a l'initial balance,
flux d'ordres, amplitude du jour) avec un ton : `bull` (favorable aux acheteurs), `bear` (aux vendeurs), `info`, `warn`. Les setups viendront
au-dessus de cette lecture, et seront MESURES avant d'etre crus (voir README, « Methode »)."""
from . import clock, cvd, vp, vwap
from .bars import atr, resample
from .events import blackout, upcoming
from .levels import nearest


def fr(x, d: int = 1) -> str:
    """Nombre a la francaise : virgule decimale, espace fine insecable pour les milliers, vrai signe moins."""
    return f"{x:,.{d}f}".replace(",", "\u202f").replace(".", ",").replace("-", "\u2212")


def _adr(mk, day: str, n: int = 5):
    """Amplitude moyenne (plus haut - plus bas) de la seance reguliere des n journees precedentes, ou None."""
    rngs, d = [], day
    for _ in range(12):
        d = mk.prev_day(d)
        if not d:
            break
        o = mk.window_ohlc(d, "rth")
        if o:
            rngs.append(o["h"] - o["l"])
        if len(rngs) >= n:
            break
    return (sum(rngs) / len(rngs), len(rngs)) if rngs else (None, 0)


def build(mk, lv: dict, events=None, acct: dict | None = None, source: dict | None = None, now_ms: int | None = None) -> dict:
    """Lecture de la seance. `now_ms` : l'heure de l'horloge (phase, reperes, annonces) ; par defaut celle de la derniere transaction. Quand le
    marche est ferme, les donnees restent celles de la derniere seance mais la phase est « marche ferme »."""
    with mk.lock:
        if mk.last is None:
            return {"ready": False, "notes": [{"tone": "warn", "text": "En attente des premières transactions."}]}
        data_now = mk.last.t
        now = now_ms or data_now
        price = mk.last.p
        day = clock.trading_day(data_now)                  # la journee des DONNEES (le samedi : celle du vendredi)
        ph = clock.phase(now)
        started = data_now >= clock.window(day, "rth")[0]  # la seance reguliere de cette journee a commence (et reste « la seance » jusqu'a 18 h ET)
        notes = []
        out = {"ready": True, "price": price, "day": day, "phase": ph, "notes": notes}

        def note(tone, text):
            notes.append({"tone": tone, "text": text})

        # ----- source et qualite du delta -----
        if source and source.get("simulated"):
            note("warn", "Données SIMULÉES : les prix et les volumes sont fictifs, rien ici ne dit quoi que ce soit du vrai marché.")
        real = mk.cls.real_share
        out["deltaReal"] = real
        if real < 0.8:
            note("warn", f"Delta ESTIMÉ (règle du tick) : seulement {real * 100:.0f} % des transactions donnent le côté de l'agresseur. "
                         "Le CVD et les absorptions sont indicatifs.")

        # ----- volatilite -----
        b1 = mk.chart_bars(60_000, 200)
        b5 = resample(b1, 300_000) if len(b1) >= 5 else []
        out["atr1"] = round(atr(b1[-60:]), 2) if len(b1) > 2 else None
        out["atr5"] = round(atr(b5[-60:]), 2) if len(b5) > 2 else None

        # ----- VWAP -----
        lad = mk.ladder(day, "rth") if started else mk.ladder(day, "gx")
        scope = "séance" if started else "Globex"
        if lad is not None and not lad.empty() and lad.sd:
            m, sd = lad.vwap, lad.sd
            z = (price - m) / sd if sd > 0 else 0.0
            out["vwap"] = {"v": round(m, 2), "sd": round(sd, 2), "z": round(z, 2), "scope": scope}
            side = "au-dessus" if z >= 0 else "en dessous"
            tone = "bull" if z > 0.25 else "bear" if z < -0.25 else "info"
            extra = ""
            if abs(z) >= 2:
                extra = " : étirement extrême, le prix est loin de sa moyenne de séance"
            elif abs(z) >= 1:
                extra = " : prix éloigné de la moyenne, déséquilibre installé"
            note(tone, f"Prix {side} du VWAP {scope} ({fr(m, 2)}) de {fr(abs(price - m), 1)} pts, soit {fr(z, 1)} écart-type{extra}.")

        # ----- zone de valeur de la veille et de la seance -----
        pvs = None
        prev = mk.prev_day(day)
        if prev and mk.ladder(prev, "rth"):
            pvs = vp.stats(mk.ladder(prev, "rth"), min_row_ticks=4)
        if pvs:
            rel = "au-dessus" if price > pvs["vah"] else "en dessous" if price < pvs["val"] else "dans"
            out["valueAreaPrev"] = {"vah": pvs["vah"], "val": pvs["val"], "poc": pvs["poc"], "rel": rel}
            if rel == "dans":
                note("info", f"Prix DANS la zone de valeur de la veille ({fr(pvs['val'], 2)} – {fr(pvs['vah'], 2)}) : marché en équilibre, les extrémités de la zone font office de bornes.")
            elif rel == "au-dessus":
                note("bull", f"Prix AU-DESSUS de la zone de valeur de la veille (VAH {fr(pvs['vah'], 2)}) : acceptation haussière si le prix s'y maintient, piège s'il y revient.")
            else:
                note("bear", f"Prix EN DESSOUS de la zone de valeur de la veille (VAL {fr(pvs['val'], 2)}) : acceptation baissière si le prix s'y maintient, piège s'il y revient.")

        # ----- initial balance -----
        a, b = clock.window(day, "ib")
        ib = mk.ohlc(a, b)
        if ib and data_now >= a:
            done = data_now >= b
            rng = ib["h"] - ib["l"]
            out["ib"] = {"hi": ib["h"], "lo": ib["l"], "range": round(rng, 2), "done": done}
            if done:
                pos = "au-dessus" if price > ib["h"] else "en dessous" if price < ib["l"] else "dans"
                tone = "bull" if pos == "au-dessus" else "bear" if pos == "en dessous" else "info"
                note(tone, f"Initial balance terminé : {fr(ib['l'], 2)} – {fr(ib['h'], 2)} ({fr(rng, 0)} pts) ; prix {pos} de l'IB.")
            else:
                note("info", f"Initial balance en formation : {fr(ib['l'], 2)} – {fr(ib['h'], 2)} ({fr(rng, 0)} pts) ; il se termine à {clock.fmt_hm(b, 'paris')} (Paris).")

        # ----- amplitude du jour -----
        o = mk.window_ohlc(day, "rth") if started else None
        adr, nadr = _adr(mk, day)
        if o and adr:
            rng = o["h"] - o["l"]
            out["range"] = {"today": round(rng, 2), "adr": round(adr, 2), "ratio": round(rng / adr, 2), "n": nadr}
            tone = "warn" if rng / adr >= 1.0 else "info"
            note(tone, f"Amplitude de la séance : {fr(rng, 0)} pts, soit {rng / adr * 100:.0f} % de la moyenne des {nadr} dernières séances ({fr(adr, 0)} pts)"
                       + (" : journée déjà très étendue, les extensions deviennent rares." if rng / adr >= 1.0 else "."))

        # ----- flux -----
        if len(b1) >= 15:
            imb5, imb15 = cvd.imbalance(b1, 5), cvd.imbalance(b1, 15)
            cv = cvd.cumulative(b1, vwap.key_rth if started else vwap.key_globex)
            cur = lad.delta if lad is not None else None                          # CVD de la seance = delta cumule de la seance
            slope = sum(x.bv - x.sv for x in b1[-15:])                            # variation du CVD sur 15 minutes
            div, force = cvd.divergence(b1, cv, len(b1) - 1, look=60)
            ab = [(i, s) for i, s in cvd.marks(b1) if i >= len(b1) - 10]
            out["flow"] = {"imb5": round(imb5, 3), "imb15": round(imb15, 3), "cvd": cur, "cvdSlope15": slope, "divergence": div, "divStrength": round(force, 2),
                           "absorption": ab[-1][1] if ab else None, "scope": scope}
            tone = "bull" if imb15 > 0.08 else "bear" if imb15 < -0.08 else "info"
            note(tone, f"Flux agressif sur 15 min : {50 * (1 + imb15):.0f} % d'achats (5 min : {50 * (1 + imb5):.0f} %). CVD {scope} : "
                       f"{fr(cur, 0) if cur is not None else '—'}" + (f" ({'+' if slope >= 0 else '−'}{fr(abs(slope), 0)} sur 15 min)." if slope is not None else "."))
            if div == "bull":
                note("bull", "Divergence haussière du CVD : le prix fait un plus bas plus bas, mais les vendeurs agressifs s'épuisent.")
            elif div == "bear":
                note("bear", "Divergence baissière du CVD : le prix fait un plus haut plus haut, mais les acheteurs agressifs s'épuisent.")
            if ab:
                i, s = ab[-1]
                note("bull" if s == "bull" else "bear",
                     f"Absorption {'acheteuse' if s == 'bull' else 'vendeuse'} à {clock.fmt_hm(b1[i].t, 'paris')} (Paris), à {fr(b1[i].c, 2)} : "
                     + ("des ordres passifs ont absorbé de fortes ventes agressives, le prix a tenu." if s == "bull"
                        else "des ordres passifs ont absorbé de forts achats agressifs, le prix a plafonné."))

        # ----- niveaux proches -----
        nr = nearest(lv.get("levels", []), price, 2) if lv else {"above": [], "below": []}
        out["near"] = nr
        z_near = [z for z in (lv or {}).get("zones", []) if abs(z["dist"]) <= 8]
        if z_near:
            z = max(z_near, key=lambda z: z["score"])
            note("info", f"Prix à {fr(abs(z['dist']), 1)} pts d'une zone de confluence ({fr(z['lo'], 2)} – {fr(z['hi'], 2)}, score {z['score']:g}) : "
                         + " + ".join(z["names"][:4]) + ".")

        # ----- temps et annonces -----
        marks = clock.next_marks(now, 2)
        out["marks"] = [{"label": lab, "t": t, "paris": clock.fmt_hm(t, "paris"), "in": round((t - now) / 60_000)} for lab, t in marks]
        if marks:
            lab, t = marks[0]
            note("info", f"Prochain repère : {lab} dans {round((t - now) / 60_000)} min ({clock.fmt_hm(t, 'paris')} à Paris).")
        evs = events or []
        bo = blackout(evs, now)
        if bo:
            note("warn", f"FENÊTRE À ÉVITER : {bo.name} ({clock.fmt_hm(bo.t, 'paris')} à Paris). Carnets d'ordres instables, slippage élevé.")
        nxt = upcoming(evs, now, 3, 24, 2)
        out["events"] = [e.to_dict() for e in nxt]
        for e in nxt[:1]:
            if not bo:
                note("info", f"Annonce à venir : {e.name} à {clock.fmt_hm(e.t, 'paris')} (Paris), impact {e.to_dict()['impactLabel']}.")

        # ----- compte -----
        if acct:
            if acct.get("breached"):
                note("warn", "Plancher du compte atteint : plus aucun trade.")
            elif acct.get("dailyStopHit"):
                note("warn", f"Stop quotidien atteint (−{fr(acct['dailyStop'], 0)} $) : fin de journée.")
            elif acct.get("status") in ("danger", "warn"):
                note("warn", f"Marge avant le plancher : {fr(acct['buffer'], 0)} $ seulement. Réduis la taille.")
        if not ph.get("open"):
            note("info", f"{ph['label']} : le marché est fermé, les données affichées sont celles de la dernière séance.")
        return out
