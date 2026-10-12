"""Lecture du journal des idees (V24) : pour chaque idee envoyee, un recit en clair (pourquoi, plan, deroule, resultat explique, ce
qu'on peut en retenir), les statistiques par categorie (paire, sens, type, qualite, tendance, entree, mois) et le trajet du prix
autour de l'idee pour le graphique de la page Historique.

Unite des resultats : le risque pris (distance entre l'entree et le stop). Un stop touche coute 1 fois le risque ; a l'objectif 1, la
moitie de la position est encaissee, le reste sort a l'objectif 2 ou a l'entree si le prix revient. Les frais ne sont pas comptes.
Tout ce qui est ecrit ici decrit ce qui s'est passe ; rien n'est deduit au-dela (une idee seule ne prouve rien sur la regle)."""
import math
import time

from alerts.trades import OPEN, MAX_HOLD_H, RESULT_WORD, is_alert, r_of, alert_verdict
from engine import signals as sg
from engine.explain import paris

H = 3_600_000
SIDE_WORD = {"long": "Achat", "short": "Vente"}
CONF_WORD = {True: "d'achat", False: "de vente"}
KIND_WORD = {"rebond": "rebond sur une zone", "reprise": "reprise d'une zone après une mèche ou un balayage"}
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
DECIDED = ("stop", "tp1_be", "tp2", "switch")    # switch (V25.1) : fermee au prix du moment, sur conseil, pour une idee plus forte dans l'autre sens
UNFILLED = ("missed", "expired", "switch_cancel")
BARS = (300_000, 900_000, 1_800_000, 3_600_000, 7_200_000, 14_400_000, 86_400_000)
BAR_WORD = {300_000: "5 minutes", 900_000: "15 minutes", 1_800_000: "30 minutes", 3_600_000: "1 heure", 7_200_000: "2 heures",
            14_400_000: "4 heures", 86_400_000: "1 jour"}
MAX_BARS = 240
AFTER_H = 48                                  # ce que le prix a fait apres la fin de l'idee


# ---------------------------------------------------------------- petits formats (francais, sans abreviation)
def fp(x):
    return sg.fmt_price(x) if x is not None else "-"


def fr(x, d=2):
    """Multiple du risque signe, virgule decimale : +1,25."""
    if x is None:
        return "-"
    v = round(x, d)
    if v == 0:
        v = 0.0
    return f"{v:+.{d}f}".replace(".", ",").replace("-", "−")


def fpc(x, d=2):
    return "-" if x is None else f"{x:+.{d}f} %".replace(".", ",").replace("-", "−")


def fnum(x, d=1):
    return "-" if x is None else f"{x:.{d}f}".replace(".", ",")


def when(ms):
    s = paris(ms)
    d, h = s.split(" ")
    return f"le {d} à {h}"


def dur(ms):
    """Duree en toutes lettres : « 25 minutes », « 3 heures et 20 minutes », « 2 jours et 4 heures »."""
    if ms is None:
        return "-"
    m = max(0, int(round(ms / 60_000)))
    if m < 60:
        return f"{m} minute{'s' if m > 1 else ''}"
    h, mm = divmod(m, 60)
    if h < 24:
        return f"{h} heure{'s' if h > 1 else ''}" + (f" et {mm} minute{'s' if mm > 1 else ''}" if mm else "")
    d, hh = divmod(h, 24)
    return f"{d} jour{'s' if d > 1 else ''}" + (f" et {hh} heure{'s' if hh > 1 else ''}" if hh else "")


# ---------------------------------------------------------------- mesures d'une idee
def risk(t):
    return abs(t["entry"] - t["stop"])


def r_at(t, p):
    """Ecart entre le prix p et l'entree, en multiples du risque, positif dans le sens de l'idee."""
    rk = risk(t)
    if p is None or not rk:
        return None
    return ((p - t["entry"]) if t["side"] == "long" else (t["entry"] - p)) / rk


def pct_at(t, p):
    """Ecart en % du prix entre p et l'entree, positif dans le sens de l'idee."""
    if p is None or not t["entry"]:
        return None
    return (p / t["entry"] - 1.0) * 100.0 * (1 if t["side"] == "long" else -1)


def risk_pct(t):
    return risk(t) / t["entry"] * 100.0 if t["entry"] else None


def end_of(t):
    return t.get("endAt") or t.get("closedAt")


def latent_r(t, price_now):
    """Resultat si la position etait fermee au prix donne (idee executee, encore ouverte ou suivi arrete)."""
    if price_now is None or not t.get("filledAt"):
        return None
    rp = r_at(t, price_now)
    if rp is None:
        return None
    if t["status"] == "tp1" or t.get("tp1At") or t.get("result") in ("tp1_be", "tp2"):
        return 0.5 * t["rr1"] + 0.5 * rp
    return rp


def outcome(t):
    """Categorie lisible : gagnante / perdante / neutre / non executee / en cours / non comptee."""
    res = t.get("result")
    if t["status"] in OPEN:
        return "open"
    if res in ("tp1_be", "tp2"):
        return "win"
    if res == "stop":
        return "loss"
    if res == "switch":
        return "win" if r_of(t) > 0 else "loss"
    if res in UNFILLED:
        return "unfilled"
    return "uncounted"


# ---------------------------------------------------------------- recit d'une idee
def story(t, lev=None, price_now=None):
    """Recit en clair d'une idee (ou d'une alerte) : dict de listes de phrases."""
    alert = is_alert(t)
    long_ = t["side"] == "long"
    e, s, t1, t2 = t["entry"], t["stop"], t["tp1"], t.get("tp2")
    rk_pct = risk_pct(t)
    sym = t["symbol"].replace("USDT", "")
    out = {"why": [], "plan": [], "events": [], "result": [], "facts": [], "lesson": []}

    # --- pourquoi
    z = t.get("zone") or {}
    kind = KIND_WORD.get(t.get("kind"), t.get("kind") or "configuration")
    if alert:
        out["why"].append(f"Configuration {CONF_WORD[long_]} de qualité {t['score']:.0f}/100 sur {sym}, dans l'autre sens que tes trades : "
                          "envoyée comme alerte de prudence, hors quota, et suivie pour savoir si elle avait raison.")
    else:
        out["why"].append(f"{SIDE_WORD[t['side']]} {sym} : {kind}" + (f" ({fp(z.get('lo'))} – {fp(z.get('hi'))})" if z.get("lo") is not None else "")
                          + f", qualité {t['score']:.0f}/100 ({sg.grade(t['score'])}).")
    if t.get("zoneN"):
        out["why"].append(f"La zone réunissait {t['zoneN']} niveaux superposés (qualité de la zone {fnum(t.get('zoneS'))} ; 14 et plus est exceptionnel).")
    al = t.get("align")
    if al is not None:
        above = "au-dessus des" if (al > 0) == long_ else "sous les"
        out["why"].append(f"Dans le sens de la tendance de fond : le cours était {above} moyennes de 50 et 200 jours à l'envoi." if al > 0 else
                          f"À contre-courant de la tendance de fond : {'achat' if long_ else 'vente'} alors que le cours était {above} moyennes de 50 et 200 jours." if al < 0 else
                          "Tendance de fond indécise : le cours était entre les moyennes de 50 et 200 jours à l'envoi.")
    for w in t.get("warn") or []:                                           # (le detail du score est dans t["comps"], affiche en barres)
        out["why"].append(f"Prudence signalée à l'envoi : {w}")
    if t.get("tp1Kind") == "pool":
        out["why"].append("L'objectif 1 était placé juste avant une poche de liquidations en face (le prix y est attiré).")
    if t.get("flipFrom"):
        f = t["flipFrom"]
        out["why"].append(f"Changement de sens : cette idée remplaçait {'l’achat' if f['side'] == 'long' else 'la vente'} {f['symbol'].replace('USDT', '')} {when(f['created'])}.")
    for f in t.get("switchFrom") or []:
        name = f"{'l’achat' if f['side'] == 'long' else 'la vente'} {f['symbol'].replace('USDT', '')} {when(f['created'])}"
        out["why"].append(f"Changement de sens : idée jugée bien plus forte que {name}, encore en cours ; le message disait d'abord de "
                          + ("l'annuler (ordre pas encore exécuté)." if f.get("state") == "pending" else
                             f"le fermer au prix du marché (vers {fp(f.get('price'))}, {fr(f.get('r'))} fois le risque)."))

    # --- plan
    if alert:
        out["plan"].append(f"Configuration {CONF_WORD[long_]} autour de {fp(e)} (ce n'était pas une idée pour toi : tu trades dans l'autre sens).")
        out["plan"].append(f"Elle était fausse si le prix {'repassait sous' if long_ else 'repassait au-dessus de'} {fp(s)} ; sinon le marché pouvait aller chercher {fp(t1)}"
                           + (f", puis {fp(t2)}." if t2 else "."))
    elif t["entryType"] == "marché":
        out["plan"].append(f"Entrée : tout de suite, au prix du marché, vers {fp(e)}.")
    else:
        px0 = t.get("px0")
        gap = f" (le prix était à {fp(px0)}, l'entrée {fnum(abs((e / px0 - 1) * 100), 2)} % plus {'bas' if long_ else 'haut'})" if px0 else ""
        out["plan"].append(f"Entrée : ordre à cours limité à {fp(e)}{gap}, exécuté seulement si le prix {'descend' if long_ else 'monte'} jusque-là.")
    if not alert:
        _plan(out["plan"], t, rk_pct)

    # --- deroule
    if alert:
        _alert_events(out["events"], t)
    else:
        _events(out["events"], t, price_now)
    res, fa, end = t.get("result"), t.get("filledAt"), end_of(t)
    held = (end - fa) if (end and fa) else None
    return _finish(out, t, alert, res, fa, held, lev, price_now, rk_pct)


def _plan(plan, t, rk_pct):
    s, t1, t2 = t["stop"], t["tp1"], t.get("tp2")
    plan.append(f"Stop : {fp(s)} ({fpc(-rk_pct)} contre l'idée). C'est le risque pris : un stop touché coûte 1 fois le risque.")
    plan.append(f"Objectif 1 : {fp(t1)} ({fpc(pct_at(t, t1))}), soit {fnum(t['rr1'], 2)} fois le risque : la moitié de la position y est encaissée et le stop remonte à l'entrée.")
    if t2:
        plan.append(f"Objectif 2 : {fp(t2)} ({fpc(pct_at(t, t2))}), soit {fnum(t.get('rr2') or t['rr1'], 2)} fois le risque : l'autre moitié y est encaissée.")
    else:
        plan.append("Pas d'objectif 2 : l'autre moitié sort aussi à l'objectif 1.")
    if t["entryType"] != "marché":
        vh = t.get("validHours") or round((t["validUntil"] - t["created"]) / H)
        plan.append(f"Validité de l'ordre : {vh} heures ; annulé si l'objectif 1 est atteint avant l'exécution.")
    plan.append(f"Suivi pendant {MAX_HOLD_H // 24} jours au plus après l'entrée.")


def _alert_events(ev, t):
    """Deroule d'une alerte (configuration dans l'autre sens que tes trades) : a-t-elle eu raison ?"""
    e, s, t1, t2 = t["entry"], t["stop"], t["tp1"], t.get("tp2")
    ev.append({"t": t["created"], "kind": "sent", "text": "Alerte envoyée" + (f" (prix {fp(t['px0'])})." if t.get("px0") else ".")})
    if t.get("filledAt") and t["entryType"] != "marché":
        ev.append({"t": t["filledAt"], "kind": "fill", "text": f"Le prix est arrivé sur l'entrée de la configuration ({fp(e)})."})
    if t.get("tp1At") or t["status"] == "tp1" or t.get("result") in ("tp1_be", "tp2"):
        ev.append({"t": t.get("tp1At"), "kind": "tp1", "text": f"Le prix a atteint l'objectif de la configuration ({fp(t1)}) : l'alerte avait raison."})
    res = t.get("result")
    if t["status"] == "closed":
        txt = {"stop": f"Le prix a dépassé le niveau d'invalidation ({fp(s)}) : l'alerte était fausse.",
               "tp1_be": f"Le prix est ensuite revenu sur l'entrée de la configuration ({fp(e)}).",
               "tp2": f"Le prix a aussi atteint le second objectif ({fp(t2 or t1)}).",
               "missed": f"Le prix a atteint l'objectif ({fp(t1)}) sans repasser par l'entrée : l'alerte avait raison.",
               "expired": "Fin de la surveillance : le prix n'est pas arrivé sur la configuration.",
               "expired_active": f"Fin du suivi après {MAX_HOLD_H // 24} jours."}.get(res, RESULT_WORD.get(res, res))
        ev.append({"t": end_of(t), "kind": "end", "text": txt})
    else:
        ev.append({"t": None, "kind": "now", "text": "Alerte encore surveillée."})


def _events(ev, t, price_now):
    e, s, t1, t2 = t["entry"], t["stop"], t["tp1"], t.get("tp2")
    ev.append({"t": t["created"], "kind": "sent", "text": "Idée envoyée" + (f" (prix {fp(t['px0'])})." if t.get("px0") else ".")})
    fa = t.get("filledAt")
    if fa:
        if t["entryType"] == "marché":
            ev.append({"t": fa, "kind": "fill", "text": f"Entrée au prix du marché, vers {fp(e)}."})
        else:
            ev.append({"t": fa, "kind": "fill", "text": f"Ordre exécuté à {fp(e)}, {dur(fa - t['created'])} après l'envoi."})
    tp1_at = t.get("tp1At")
    reached_tp1 = bool(tp1_at) or t.get("result") in ("tp1_be", "tp2") or t["status"] == "tp1"
    if reached_tp1:
        txt = f"Objectif 1 atteint ({fp(t1)})" + (f" après {dur(tp1_at - fa)} en position" if tp1_at and fa else "") + \
              f" : moitié encaissée, {fr(0.5 * t['rr1'])} fois le risque ; stop remonté à l'entrée."
        ev.append({"t": tp1_at, "kind": "tp1", "text": txt})
    end, res = end_of(t), t.get("result")
    held = (end - fa) if (end and fa) else None
    if t["status"] == "closed":
        txt = {"stop": f"Stop touché ({fp(s)})" + (f" après {dur(held)} en position" if held is not None else "") + " : perte de 1 fois le risque.",
               "tp1_be": f"Le prix est revenu à l'entrée ({fp(e)}) : l'autre moitié sort à l'équilibre, sans perte.",
               "tp2": f"Objectif 2 atteint ({fp(t2 or t1)})" + (f" après {dur(held)} en position" if held is not None else "") + ".",
               "missed": f"Objectif 1 ({fp(t1)}) atteint sans que l'ordre à {fp(e)} soit exécuté : idée manquée, ni gain ni perte.",
               "expired": f"Fin de validité : l'ordre à {fp(e)} n'a pas été exécuté ; idée expirée, ni gain ni perte.",
               "expired_active": f"Suivi arrêté après {MAX_HOLD_H // 24} jours en position" + (f" (prix {fp(t['exitPx'])} à ce moment)" if t.get("exitPx") else "") + ".",
               "switch": f"Fermée au prix du marché, vers {fp(t.get('exitPx'))}" + (f", après {dur(held)} en position" if held is not None else "")
                         + f", sur mon conseil : une idée bien plus forte est arrivée dans l'autre sens ({fr(r_of(t))} fois le risque au total).",
               "switch_cancel": f"Ordre à {fp(e)} annulé avant exécution, sur mon conseil : une idée bien plus forte est arrivée dans l'autre sens ; ni gain ni perte."
               }.get(res, RESULT_WORD.get(res, res))
        ev.append({"t": end, "kind": "end", "text": txt})
    elif t["status"] == "pending":
        ev.append({"t": None, "kind": "now", "text": f"Ordre toujours en attente (valable jusqu'{when(t['validUntil']).replace('le ', 'au ', 1)})."})
    else:
        ev.append({"t": None, "kind": "now", "text": "Position toujours en cours" + (f" (prix actuel {fp(price_now)})." if price_now else ".")})


def _finish(out, t, alert, res, fa, held, lev, price_now, rk_pct):
    long_ = t["side"] == "long"
    e, t2 = t["entry"], t.get("tp2")
    # --- resultat explique
    rr1, rr2 = t["rr1"], (t.get("rr2") or t["rr1"])
    r = None if alert else r_of(t)
    if alert:
        v = alert_verdict(t)
        out["result"].append("Alerte juste : le prix est allé vers l'objectif de la configuration ; une position dans ton sens aurait souffert." if v is True else
                             "Alerte fausse : le prix a dépassé le niveau d'invalidation ; il n'y avait pas lieu d'alléger ta position." if v is False else
                             "Alerte pas encore tranchée.")
    elif res == "stop":
        out["result"].append("Résultat : −1 fois le risque (le stop prévu).")
    elif res == "tp1_be":
        out["result"].append(f"Résultat : {fr(r)} fois le risque = moitié à l'objectif 1 (½ × {fnum(rr1, 2)}) + moitié à l'entrée (½ × 0).")
    elif res == "tp2":
        out["result"].append(f"Résultat : {fr(r)} fois le risque = moitié à l'objectif 1 (½ × {fnum(rr1, 2)}) + moitié à l'objectif 2 (½ × {fnum(rr2, 2)}).")
    elif res in ("missed", "expired"):
        out["result"].append("Résultat : 0 (ordre jamais exécuté, aucune position).")
    elif res == "switch_cancel":
        out["result"].append("Résultat : 0 (ordre annulé avant exécution pour une idée plus forte dans l'autre sens, aucune position).")
    elif res == "switch":
        x = t.get("exitPx")
        if t.get("switchState") == "tp1" or t.get("tp1At"):
            out["result"].append(f"Résultat : {fr(r)} fois le risque = moitié à l'objectif 1 (½ × {fnum(rr1, 2)}) + moitié fermée vers {fp(x)} "
                                 f"(½ × {fr(r_at(t, x))}), pour une idée plus forte dans l'autre sens.")
        else:
            out["result"].append(f"Résultat : {fr(r)} fois le risque : position fermée au prix du marché vers {fp(x)}, sur mon conseil, pour une idée plus forte dans l'autre sens.")
    elif res == "expired_active":
        lr = latent_r(t, t.get("exitPx"))
        out["result"].append("Résultat non compté : le terminal ne suit une position que 7 jours." +
                             (f" Au prix de ce moment, elle valait {fr(lr)} fois le risque." if lr is not None else ""))
    elif t["status"] in ("active", "tp1"):
        lr = latent_r(t, price_now)
        out["result"].append("En cours" + (f" : au prix actuel, {fr(lr)} fois le risque (pas encore compté)." if lr is not None else "."))
    else:
        out["result"].append("En attente d'exécution.")
    if r is not None and res in DECIDED and rk_pct:
        move = r * rk_pct
        txt = f"Soit {fpc(move)} sur le prix pour toute la position (le risque valait {fnum(rk_pct, 2)} % du prix)"
        if lev:
            txt += f" ; avec un levier de {fnum(lev, 0)}, {fpc(move * lev, 1)} sur la marge engagée"
        out["result"].append(txt + ".")

    # --- meilleur et pire moment
    b, w, nr = t.get("best"), t.get("worst"), t.get("near")
    if fa and (b or w):
        parts = []
        if b:
            parts.append(f"au mieux, le prix est allé à {fr(r_at(t, b['p']))} fois le risque en ta faveur ({fp(b['p'])} {when(b['t'])})")
        if w:
            parts.append(f"au pire, à {fr(r_at(t, w['p']))} fois le risque ({fp(w['p'])} {when(w['t'])})")
        out["facts"].append(("Pendant la position : " if t["status"] == "closed" else "Depuis l'entrée : ") + " ; ".join(parts) + ".")
    elif not fa and nr and t["status"] == "closed":
        out["facts"].append(f"Au plus près, le prix est passé à {fp(nr['p'])} {when(nr['t'])}, à {fnum(abs(pct_at(t, nr['p']) or 0), 2)} % de l'entrée sans l'atteindre."
                            if (nr["p"] > e if long_ else nr["p"] < e) else f"Au plus près, le prix est passé à {fp(nr['p'])} {when(nr['t'])}.")
    elif t.get("replay") == "absent" and t["status"] == "closed":
        out["facts"].append("Meilleur et pire moment non disponibles : idée antérieure au journal détaillé et bougies de 5 minutes plus conservées (70 jours).")

    # --- a retenir (constats factuels sur CETTE idee)
    les = out["lesson"]
    br = r_at(t, b["p"]) if b else None
    wr = r_at(t, w["p"]) if w else None
    if alert:
        pass
    elif res == "stop":
        if br is not None:
            if br >= 0.75 * rr1:
                les.append(f"Le prix est allé jusqu'à {fr(br)} fois le risque, tout près de l'objectif 1 ({fnum(rr1, 2)}), puis s'est retourné jusqu'au stop.")
            elif br >= 0.3:
                les.append(f"Le prix est d'abord allé dans ton sens (jusqu'à {fr(br)} fois le risque) sans atteindre l'objectif 1, puis a touché le stop.")
            else:
                les.append(f"Le prix n'est presque pas allé dans ton sens (au mieux {fr(br)} fois le risque) : la zone n'a pas tenu.")
        if held is not None and held < H:
            les.append("Stop touché moins d'une heure après l'entrée : l'entrée est arrivée en plein mouvement contraire.")
    elif res == "tp1_be":
        les.append("La moitié a été encaissée, puis le stop remonté à l'entrée a protégé le reste : une idée gagnante même si le prix est revenu.")
        if br is not None and t2:
            les.append(f"Au mieux, le prix est allé à {fr(br)} fois le risque ; l'objectif 2 était à {fnum(rr2, 2)}.")
    elif res == "tp2":
        les.append("Idée allée au bout : les deux objectifs ont été atteints.")
        if wr is not None:
            les.append(f"Au pire moment, la position était à {fr(wr)} fois le risque avant de repartir.")
    elif res == "missed":
        les.append("Le terminal ne court jamais après le prix : une idée manquée ne compte ni en gain ni en perte.")
    elif res == "expired":
        les.append("Le prix n'est jamais revenu jusqu'à l'entrée pendant la validité de l'ordre.")
    elif res == "switch":
        les.append("Fermée avant son stop et ses objectifs pour une idée dans l'autre sens jugée bien plus forte : le résultat compte au prix de fermeture "
                   "conseillé. « Et ensuite ? » dit si garder l'idée aurait mieux payé.")
    elif res == "switch_cancel":
        les.append("Ordre annulé avant exécution pour une idée dans l'autre sens jugée bien plus forte : ni gain ni perte.")
    elif res == "expired_active":
        les.append("Après 7 jours, la gestion de la position te revient : ce résultat n'entre pas dans les statistiques.")
    return out


# ---------------------------------------------------------------- statistiques
def _row(label, ts):
    dec = [t for t in ts if t.get("result") in DECIDED]
    rs = [r_of(t) for t in dec]
    wins = sum(1 for x in rs if x > 0)
    filled = sum(1 for t in ts if t.get("filledAt"))
    return {"label": label, "n": len(ts), "filled": filled, "fillRate": filled / len(ts) if ts else None, "decided": len(dec), "wins": wins,
            "losses": len(dec) - wins, "winRate": wins / len(dec) if dec else None, "r": sum(rs), "avg": sum(rs) / len(rs) if rs else None,
            "open": sum(1 for t in ts if t["status"] in OPEN)}


def _group(ideas, key, order=None):
    by = {}
    for t in ideas:
        k = key(t)
        if k is not None:
            by.setdefault(k, []).append(t)
    keys = list(by)
    if order:
        keys.sort(key=order)
    return [_row(k, by[k]) for k in keys]


def _quality(t):
    s = t.get("score") or 0
    lo = int(s // 10 * 10)
    return f"{lo} à {lo + 9} sur 100" if lo < 90 else "90 et plus"


def _month(t):
    g = time.gmtime(t["created"] / 1000)
    return f"{MONTHS[g.tm_mon - 1]} {g.tm_year}"


TREND = {1: "dans le sens de la tendance de fond", 0: "tendance indécise", -1: "à contre-courant"}


def summary(trades, expect=None):
    """Statistiques des idees (alertes a part) : ensemble, courbe, creux maximal, series, delais, categories, annonce contre realise."""
    ideas = [t for t in trades if not is_alert(t)]
    dec = sorted([t for t in ideas if t.get("result") in DECIDED], key=lambda t: end_of(t) or t["created"])
    tot = _row("Toutes les idées", ideas)
    # courbe cumulee, creux maximal, series
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    streak, worst_streak, cur = 0, 0, 0
    for t in dec:
        r = r_of(t)
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        curve.append({"t": end_of(t) or t["created"], "r": r, "cum": cum, "id": t["id"]})
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    if dec:
        sign = 1 if r_of(dec[-1]) > 0 else -1 if r_of(dec[-1]) < 0 else 0
        for t in reversed(dec):
            x = r_of(t)
            if (x > 0 and sign > 0) or (x < 0 and sign < 0):
                cur += 1
            else:
                break
        cur *= sign
    rs = [r_of(t) for t in dec]
    best = max(dec, key=r_of, default=None)
    worst = min(dec, key=r_of, default=None)
    fills = [t["filledAt"] - t["created"] for t in ideas if t.get("filledAt") and t["entryType"] != "marché"]
    holds = [end_of(t) - t["filledAt"] for t in dec if end_of(t) and t.get("filledAt")]
    out = {**tot, "maxDrawdown": dd, "lossStreak": worst_streak, "streak": cur, "curve": curve,
           "best": {"id": best["id"], "r": r_of(best)} if best else None, "worst": {"id": worst["id"], "r": r_of(worst)} if worst else None,
           "avgFill": sum(fills) / len(fills) if fills else None, "avgHold": sum(holds) / len(holds) if holds else None,
           "missed": sum(1 for t in ideas if t.get("result") == "missed"), "expired": sum(1 for t in ideas if t.get("result") == "expired"),
           "uncounted": sum(1 for t in ideas if t.get("result") == "expired_active"),
           "switched": sum(1 for t in ideas if t.get("result") == "switch"), "cancelled": sum(1 for t in ideas if t.get("result") == "switch_cancel")}
    # moyenne et intervalle a 90 % (approximation normale) : honnete sur la taille de l'echantillon
    if len(rs) >= 2:
        m = sum(rs) / len(rs)
        sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (len(rs) - 1))
        out["avgLo"], out["avgHi"] = m - 1.645 * sd / math.sqrt(len(rs)), m + 1.645 * sd / math.sqrt(len(rs))
    out["verdict"] = verdict(out)
    out["groups"] = [
        {"key": "pair", "title": "Paire", "rows": _group(ideas, lambda t: t["symbol"].replace("USDT", ""))},
        {"key": "side", "title": "Sens", "rows": _group(ideas, lambda t: "achat" if t["side"] == "long" else "vente")},
        {"key": "kind", "title": "Configuration", "rows": _group(ideas, lambda t: KIND_WORD.get(t.get("kind"), t.get("kind")))},
        {"key": "score", "title": "Qualité à l'envoi", "rows": _group(ideas, _quality, order=lambda k: -int(k.split(" ")[0]))},
        {"key": "trend", "title": "Tendance de fond", "rows": _group(ideas, lambda t: TREND.get(t.get("align"), "non enregistrée (avant le journal détaillé)"))},
        {"key": "entry", "title": "Entrée", "rows": _group(ideas, lambda t: "au prix du marché" if t["entryType"] == "marché" else "ordre à cours limité")},
        {"key": "month", "title": "Mois", "rows": _group(ideas, _month, order=lambda k: -_month_index(k))},
    ]
    out["calibration"] = calibration(ideas)
    out["expect"] = expect or {}
    al = [t for t in trades if is_alert(t)]
    vs = [alert_verdict(t) for t in al]
    out["alerts"] = {"n": len(al), "right": sum(1 for v in vs if v is True), "wrong": sum(1 for v in vs if v is False)}
    return out


def _month_index(label):
    m, y = label.rsplit(" ", 1)
    return int(y) * 12 + MONTHS.index(m)


def verdict(s):
    n = s["decided"]
    if n == 0:
        return "Aucune idée terminée pour l'instant : pas encore de résultat à juger."
    head = f"{n} idée{'s' if n > 1 else ''} terminée{'s' if n > 1 else ''} : {s['wins']} gagnante{'s' if s['wins'] > 1 else ''}, {s['losses']} perdante{'s' if s['losses'] > 1 else ''}, " \
           f"résultat {fr(s['r'])} fois le risque ({fr(s['avg'])} en moyenne par idée)."
    if n < 30:
        return head + " C'est encore trop peu pour juger le terminal : il en faut au moins 30, car quelques gains ou pertes de suite peuvent venir du hasard."
    lo, hi = s.get("avgLo"), s.get("avgHi")
    if lo is not None and lo > 0:
        return head + f" Avantage démontré sur ces idées (intervalle à 90 % de la moyenne : {fr(lo)} à {fr(hi)}), hors frais."
    if hi is not None and hi < 0:
        return head + f" Perte démontrée sur ces idées (intervalle à 90 % de la moyenne : {fr(lo)} à {fr(hi)}) : la règle ne marche pas en réel."
    return head + (f" Pas d'avantage démontré : l'intervalle à 90 % de la moyenne va de {fr(lo)} à {fr(hi)} et contient zéro." if lo is not None else "")


def calibration(ideas):
    """Ce que le terminal annonçait a l'envoi (frequences historiques) face a ce qui est arrive."""
    out = {}
    # une idee fermee pour changer de sens avant l'objectif 1 n'a rien tranche : elle est laissee de cote (de meme un ordre annule avant 24 h)
    tp = [t for t in ideas if t.get("pTp") is not None and t.get("filledAt") and (t.get("result") in DECIDED or t["status"] == "tp1")
          and (t.get("result") != "switch" or t.get("tp1At"))]
    if tp:
        hit = sum(1 for t in tp if t.get("result") in ("tp1_be", "tp2") or t["status"] == "tp1" or t.get("tp1At"))
        out["tp1"] = {"n": len(tp), "announced": sum(t["pTp"] for t in tp) / len(tp), "real": hit / len(tp)}
    fl = [t for t in ideas if t.get("pFill") is not None and t["entryType"] != "marché"
          and (t.get("result") != "switch_cancel" or (end_of(t) or 0) >= t["created"] + 24 * H)
          and (t.get("filledAt") or t["status"] == "closed" or t["created"] + 24 * H <= (t.get("checked") or 0))]
    if fl:
        hit = sum(1 for t in fl if t.get("filledAt") and t["filledAt"] - t["created"] <= 24 * H)
        out["fill"] = {"n": len(fl), "announced": sum(t["pFill"] for t in fl) / len(fl), "real": hit / len(fl)}
    return out


# ---------------------------------------------------------------- trajet du prix (graphique de la fiche)
def window(t, now_ms):
    """Debut et fin de la periode affichee : un peu avant l'envoi, un peu apres la fin (ou maintenant)."""
    start = t["created"]
    end = end_of(t) if t["status"] == "closed" else now_ms
    end = min(end or now_ms, now_ms)
    span = max(end - start, 2 * H)
    a = start - max(6 * H, 0.3 * span)
    b = min(now_ms, end + max(6 * H, 0.3 * span))
    return int(a), int(b), int(end)


def bar_for(a, b, finest):
    for ms in BARS:
        if ms >= finest and (b - a) / ms <= MAX_BARS:
            return ms
    return BARS[-1]


def _resample(rows, ms):
    out = []
    for t, o, h, l, c in rows:
        k = t - t % ms
        if out and out[-1][0] == k:
            x = out[-1]
            x[2], x[3], x[4] = max(x[2], h), min(x[3], l), c
        else:
            out.append([k, o, h, l, c])
    return out


def path(t, rows, finest, now_ms):
    """rows : [(t, ouverture, haut, bas, cloture)] a la resolution `finest` (ms), couvrant la fenetre et les 48 h qui suivent la fin.
    Renvoie les bougies du graphique, les niveaux, les evenements et ce que le prix a fait ensuite."""
    a, b, end = window(t, now_ms)
    bar = bar_for(a, b, finest)
    shown = _resample([r for r in rows if a <= r[0] <= b], bar)
    e, s, t1, t2 = t["entry"], t["stop"], t["tp1"], t.get("tp2")

    def close_at(ms):
        prev = None
        for r in rows:
            if r[0] > ms:
                break
            prev = r
        return prev[4] if prev else None

    evs = [{"t": t["created"], "p": t.get("px0") or close_at(t["created"]), "kind": "sent", "label": "envoi"}]
    if t.get("filledAt"):
        evs.append({"t": t["filledAt"], "p": e, "kind": "fill", "label": "exécution" if t["entryType"] != "marché" else "entrée"})
    if t.get("tp1At"):
        evs.append({"t": t["tp1At"], "p": t1, "kind": "tp1", "label": "objectif 1"})
    res = t.get("result")
    if t["status"] == "closed" and end_of(t):
        p_end = {"stop": s, "tp1_be": e, "tp2": t2 or t1, "missed": t1, "expired_active": t.get("exitPx"), "switch": t.get("exitPx")}.get(res)
        evs.append({"t": end_of(t), "p": p_end, "kind": "end", "label": {"stop": "stop", "tp1_be": "sortie à l'entrée", "tp2": "objectif 2", "missed": "objectif 1 sans exécution",
                                                                       "expired": "fin de validité", "expired_active": "fin du suivi",
                                                                       "switch": "fermée (changement de sens)", "switch_cancel": "annulée (changement de sens)"}.get(res, "fin")})
    for k, lab in (("best", "meilleur moment"), ("worst", "pire moment")):
        if t.get(k) and t.get("filledAt"):
            evs.append({"t": t[k]["t"], "p": t[k]["p"], "kind": k, "label": lab})
    if t.get("near") and not t.get("filledAt"):
        evs.append({"t": t["near"]["t"], "p": t["near"]["p"], "kind": "near", "label": "plus près de l'entrée"})
    return {"bars": shown, "bar": bar, "barWord": BAR_WORD.get(bar, ""), "from": a, "to": b,
            "levels": {"entry": e, "stop": s, "tp1": t1, "tp2": t2, "zone": t.get("zone")}, "events": evs,
            "after": after(t, rows, now_ms)}


def after(t, rows, now_ms):
    """Ce que le prix a fait dans les 48 heures apres la fin de l'idee (constat, pas un reproche) ; liste de phrases."""
    if t["status"] != "closed" or is_alert(t):
        return []
    end = end_of(t)
    if not end:
        return []
    horizon = min(now_ms, end + AFTER_H * H)
    nxt = [r for r in rows if end < r[0] <= horizon]
    if not nxt:
        return ["Pas encore de bougies après la fin de l'idée."]
    long_ = t["side"] == "long"
    fav = (lambda p: lambda r: r[2] >= p) if long_ else (lambda p: lambda r: r[3] <= p)
    adv = (lambda p: lambda r: r[3] <= p) if long_ else (lambda p: lambda r: r[2] >= p)
    first = lambda cond: next((r for r in nxt if cond(r)), None)
    hours = (horizon - end) / H
    span = f"dans les {hours:.0f} heures suivantes" if hours >= 1.5 else "depuis"
    res, e, t1, t2 = t.get("result"), t["entry"], t["tp1"], t.get("tp2")
    out = []
    if res == "stop":
        hit = first(fav(t1))
        out.append(f"Après le stop, le prix a atteint l'objectif 1 ({fp(t1)}) {when(hit[0])}, {dur(hit[0] - end)} plus tard." if hit else
                   f"Après le stop, le prix n'a pas atteint l'objectif 1 {span}.")
    elif res == "tp1_be":
        if t2:
            hit = first(fav(t2))
            out.append(f"Après la sortie à l'entrée, le prix a atteint l'objectif 2 ({fp(t2)}) {when(hit[0])}, {dur(hit[0] - end)} plus tard : garder le reste aurait payé cette fois." if hit else
                       f"Après la sortie à l'entrée, le prix n'a pas atteint l'objectif 2 {span} : la sortie à l'équilibre n'a rien coûté.")
    elif res == "tp2":
        ext = max(r[2] for r in nxt) if long_ else min(r[3] for r in nxt)
        rr = r_at(t, ext)
        out.append(f"Après l'objectif 2, le prix est encore allé jusqu'à {fr(rr)} fois le risque ({fp(ext)}) {span}." if rr is not None and rr > (t.get("rr2") or t["rr1"]) + 0.05 else
                   f"Le prix s'est arrêté près de l'objectif 2 {span} : sortie bien placée.")
    elif res == "switch":
        tp1_state = t.get("switchState") == "tp1" or bool(t.get("tp1At"))
        lose, win = (e, t2) if tp1_state else (t["stop"], t1)
        hl = first(adv(lose))
        hw = first(fav(win)) if win else None
        if hl and (not hw or hl[0] <= hw[0]):
            out.append((f"Après la fermeture, le prix est revenu à l'entrée ({fp(e)}) {when(hl[0])}, {dur(hl[0] - end)} plus tard : le reste serait sorti à l'équilibre."
                        if tp1_state else
                        f"Après la fermeture, le prix a touché le stop prévu ({fp(lose)}) {when(hl[0])}, {dur(hl[0] - end)} plus tard : fermer a évité la perte complète."))
        elif hw:
            out.append(f"Après la fermeture, le prix a atteint l'objectif {'2' if tp1_state else '1'} prévu ({fp(win)}) {when(hw[0])}, {dur(hw[0] - end)} plus tard : "
                       "garder l'idée aurait mieux payé cette fois.")
        else:
            low_word, tp_word = ("l'entrée", "2") if tp1_state else ("le stop", "1")
            out.append(f"Après la fermeture, le prix n'a touché ni {low_word} ni l'objectif {tp_word} prévus {span}.")
    elif res in UNFILLED:
        hit = first(adv(e))
        if hit:
            then_stop = next((r for r in nxt if r[0] >= hit[0] and adv(t["stop"])(r)), None)
            then_tp = next((r for r in nxt if r[0] > hit[0] and fav(t1)(r)), None)
            tail = ""
            if then_stop and (not then_tp or then_stop[0] <= then_tp[0]):
                tail = " ; ensuite il a touché le stop avant l'objectif 1"
            elif then_tp:
                tail = " ; ensuite il a atteint l'objectif 1"
            out.append(f"Le prix est revenu à l'entrée ({fp(e)}) {when(hit[0])}, {dur(hit[0] - end)} après la fin{tail}.")
        else:
            out.append(f"Le prix n'est pas revenu à l'entrée {span}.")
    elif res == "expired_active":
        last = nxt[-1][4]
        lr = latent_r(t, last)
        if lr is not None:
            out.append(f"{AFTER_H if hours >= AFTER_H else round(hours)} heures après l'arrêt du suivi, la position aurait valu {fr(lr)} fois le risque (prix {fp(last)}).")
    return out
