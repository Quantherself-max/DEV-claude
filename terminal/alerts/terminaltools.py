"""Outils de l'assistant (V52) : Claude lit lui-même, à chaque question, les données du terminal dont il a besoin.

Au lieu d'un résumé figé joint à chaque question, l'assistant reçoit un catalogue d'outils (un par partie du terminal : niveaux et
zones, bougies avec delta et intérêt ouvert, profils de volume, TPO, Quant, options et baleines, liquidations, flux par taille, idées,
macro, divergences, stratégie, gamma). Il appelle ceux qui servent la question ; le terminal les exécute ici, sur ses données du moment,
et lui renvoie le résultat. Chaque résultat est CONDENSÉ (nombres à 6 chiffres significatifs, heures de Paris, listes raccourcies aux
éléments les plus récents, tableaux bruts retirés) pour rester lisible et peu coûteux : 24 000 caractères au plus par appel.

Rien n'est inventé : une partie indisponible renvoie {"erreur": ...}, que l'assistant doit dire."""
from __future__ import annotations
import json
import math
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:                                                     # Windows sans base de fuseaux : heure d'hiver de Paris
    PARIS = timezone(timedelta(hours=1))

LIMIT = 24_000                       # caractères au plus par résultat d'outil
HOUR = 3_600_000
DAY = 86_400_000
TIME_KEYS = {"t", "time", "times", "start", "end", "t0", "t1", "created", "known", "expiry", "since", "at", "last", "ref", "oiT", "oiAt",
             "nextFunding", "fundNext", "firstSnap", "liveSince", "lastT", "built", "computedAt", "sent", "closed", "opened", "until"}
DROP = {"candles", "developing", "spark", "csrf", "img", "image", "png"}


def paris(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, PARIS).strftime("%d/%m/%y %H:%M")


def _sig(v: float) -> float:
    if v == 0 or not math.isfinite(v):
        return v if math.isfinite(v) else None
    return float(f"{v:.6g}")


def slim(x, cap: int = 25, key: str = "", depth: int = 0, drop=DROP):
    """Copie lisible : flottants à 6 chiffres significatifs, heures en clair (heure de Paris), listes réduites à leurs `cap` derniers
    éléments (les plus récents), textes longs coupés, clés lourdes retirées."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, float):
        return _sig(x)
    if isinstance(x, int):
        if 1_300_000_000_000 <= x <= 2_300_000_000_000:
            return paris(x)
        if key in TIME_KEYS and 1_300_000_000 <= x <= 2_300_000_000:
            return paris(x * 1000)
        return x
    if isinstance(x, str):
        return x if len(x) <= 700 else x[:700] + "…"
    if depth > 8:
        return "…"
    if isinstance(x, dict):
        return {str(k): slim(v, cap, str(k), depth + 1, drop) for k, v in x.items() if k not in drop}
    if isinstance(x, (list, tuple)):
        lst = list(x)
        if len(lst) <= 16 and not any(isinstance(v, (list, tuple, dict)) for v in lst):
            return [slim(v, cap, key, depth + 1, drop) for v in lst]       # une ligne de valeurs (bougie, tranche) : jamais coupée
        if len(lst) > cap:
            return [f"({len(lst) - cap} éléments plus anciens omis)"] + [slim(v, cap, key, depth + 1, drop) for v in lst[-cap:]]
        return [slim(v, cap, key, depth + 1, drop) for v in lst]
    try:
        return _sig(float(x))                                           # Decimal, Fraction
    except (TypeError, ValueError):
        return str(x)[:200]


def dump(obj, cap: int = 25, drop=DROP) -> str:
    """JSON compact sous LIMIT caractères : les listes raccourcissent jusqu'à tenir, puis coupure franche signalée."""
    for c in (cap, 12, 6, 3):
        s = json.dumps(slim(obj, c, drop=drop), ensure_ascii=False, separators=(",", ":"))
        if len(s) <= LIMIT:
            return s
    return s[:LIMIT] + "…(résultat coupé : trop long)"


def _sym_prop(syms):
    return {"type": "string", "enum": list(syms), "description": "Paire : " + ", ".join(syms)}


class TerminalTools:
    """Exécute les outils sur l'application (server.App) en cours. `defs()` : le catalogue envoyé à Claude."""

    def __init__(self, app):
        self.app = app

    # ---------- catalogue ----------
    def defs(self) -> list:
        from service import TFS
        syms = list(self.app.cfg.symbols)
        S, TF = _sym_prop(syms), {"type": "string", "enum": list(TFS), "description": "Unité de temps des bougies"}

        def tool(name, desc, props=None, req=None):
            return {"name": name, "description": desc, "input_schema": {"type": "object", "properties": props or {}, "required": req or [],
                                                                        "additionalProperties": False}}
        return [
            tool("niveaux_et_zones", "Niveaux du graphique d'une paire dans une unité de temps : prix, amplitude moyenne d'une bougie, zones de "
                 "confluence notées sur 14 (niveaux de sources différentes superposés), niveaux nommés (plus hauts et plus bas de la veille, de la "
                 "semaine, du mois, VWAP, POC, VAH, VAL, POC vierges), poches de liquidation estimées, balayages récents, contexte, profils du jour, "
                 "de la semaine et du mois (sans le détail par prix), niveaux du gamma des options pour le BTC, absorptions.",
                 {"paire": S, "unite": TF}, ["paire", "unite"]),
            tool("bougies", "Dernières bougies d'une paire (heure de Paris) avec, alignés sur chaque bougie : volume, delta (acheteurs moins "
                 "vendeurs agressifs, en pièces et en dollars), CVD, intérêt ouvert, financement, delta du comptant. Pour décrire un mouvement, "
                 "une tendance récente, qui a poussé le prix.",
                 {"paire": S, "unite": TF, "nombre": {"type": "integer", "minimum": 5, "maximum": 120, "description": "Nombre de bougies (5 à 120)"}},
                 ["paire", "unite", "nombre"]),
            tool("profils_volume", "Profils de volume d'une paire : POC, VAH, VAL, plus haut, plus bas, nœuds de volume (HVN, LVN), forme, delta "
                 "total et part des achats, et les prix où les acheteurs puis les vendeurs ont le plus dominé (delta par prix). Périodes : D jour, "
                 "W semaine, M mois, Q trimestre, PM mois précédent, Y année, PY année précédente, A tout l'historique.",
                 {"paire": S, "periodes": {"type": "array", "items": {"type": "string", "enum": ["D", "W", "M", "Q", "PM", "Y", "PY", "A"]},
                                           "description": "Périodes voulues"}}, ["paire", "periodes"]),
            tool("tpo", "Profils TPO (temps passé à chaque prix) des dernières séances : POC, zone de valeur, fourchette initiale, single prints, "
                 "poor highs et lows, POC vierges. Séances : D jour, 4h, 1h, W semaine, M mois.",
                 {"paire": S, "seance": {"type": "string", "enum": ["D", "4h", "1h", "W", "M"]}}, ["paire", "seance"]),
            tool("quant", "Moteur exact (onglet Quant) d'une paire : CVD transaction par transaction du perpétuel et du comptant (5 min à 24 h), "
                 "achats du comptant contre ceux des perpétuels sur 24 et 48 heures avec la lecture de conviction, régime de marché sur 15 min, "
                 "1 h et 4 h, divergences prix / CVD, absorptions, carnet d'ordres (déséquilibre, murs), profil de volume exact, intérêt ouvert et "
                 "financement sur Binance, Bybit, OKX, et pour le BTC le CVD par bourse et le réseau Bitcoin. Le moteur démarre à la première "
                 "demande : l'historique de 24 heures peut prendre une minute.",
                 {"paire": S}, ["paire"]),
            tool("options_btc", "Options BTC de Deribit : exposition gamma, bascule du gamma, murs de calls et de puts, max pain par échéance, "
                 "volatilité implicite et skew ; les baleines des 24 dernières heures (ordres au-dessus du seuil, avec stratégie, prime, delta et "
                 "vega nets) ; les variations de l'intérêt ouvert de chaque option sur 24 heures (accumulations et réductions).",
                 {"seuil_baleines_usd": {"type": "number", "description": "Notionnel minimal d'une baleine en dollars (1000000, 5000000 ou 10000000)"}},
                 []),
            tool("liquidations", "Liquidations : réelles sur 1, 4 et 24 heures pour la paire (longs et shorts, plus grosses), liquidations du BTC "
                 "par bourse sur 6, 12, 24 et 48 heures avec les gros ordres exécutés, et la carte des liquidations estimée (où des positions à "
                 "levier seraient liquidées au-dessus et en dessous du prix, en dollars).",
                 {"paire": S}, ["paire"]),
            tool("flux_par_taille", "Delta cumulé en dollars par taille d'ordre (petits, moyens, gros) sur le comptant et le perpétuel Binance, "
                 "par bougie : qui achète et qui vend, particuliers ou institutions.",
                 {"paire": S, "unite": TF}, ["paire", "unite"]),
            tool("idees_et_signaux", "Idées de trade du terminal pour une paire (en cours, en attente, envoyées sur Telegram, avec entrée, stop, "
                 "objectifs, qualité), les combinaisons prix / intérêt ouvert / CVD qui les fondent, et le bilan historique des idées.",
                 {"paire": S}, ["paire"]),
            tool("macro", "Macro : la semaine (annonces américaines, surprises face au consensus, réactions mesurées des marchés, vision et "
                 "estimations du terminal, semaine prochaine) ou le mois (Fed, projections, consensus, scénarios, dates clés).",
                 {"periode": {"type": "string", "enum": ["semaine", "mois"]}}, ["periode"]),
            tool("divergences", "Divergences prix / intérêt ouvert / CVD en journalier, 4 heures et 1 heure pour chaque paire, avec ce qu'en dit "
                 "la mesure historique du terminal."),
            tool("strategie_et_regime", "Mesures historiques d'une paire : stratégie VWAP de l'utilisateur (rebonds et clôtures sur VWAP et VWAP "
                 "ancrés), régime de marché, et ce que le backtest valide ou non.",
                 {"paire": S}, ["paire"]),
            tool("gamma_options", "Onglet GEX : profil du gamma des options BTC par strike (Deribit, Bybit, OKX), murs, bascule, plus fort gamma, "
                 "mouvement attendu, échéances."),
        ]

    # ---------- exécution ----------
    def run(self, name: str, args: dict) -> str:
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return json.dumps({"erreur": f"outil inconnu : {name}"}, ensure_ascii=False)
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return json.dumps({"erreur": f"paramètres invalides : {e}"}, ensure_ascii=False)
        except KeyError as e:
            return json.dumps({"erreur": f"inconnu : {e}"}, ensure_ascii=False)
        except Exception as e:                                          # une partie en panne ne casse jamais la réponse
            return json.dumps({"erreur": f"{type(e).__name__}: {str(e)[:200]}"}, ensure_ascii=False)

    def label(self, name: str, args: dict) -> str:
        """Ce que l'outil a lu, en clair (pour la page)."""
        names = {"niveaux_et_zones": "niveaux et zones", "bougies": "bougies", "profils_volume": "profils de volume", "tpo": "TPO",
                 "quant": "Quant", "options_btc": "options BTC et baleines", "liquidations": "liquidations", "flux_par_taille": "flux par taille",
                 "idees_et_signaux": "idées de trade", "macro": "macro", "divergences": "divergences", "strategie_et_regime": "stratégie et régime",
                 "gamma_options": "gamma des options", "web_search": "recherche web"}
        a = args or {}
        bits = [str(a[k]).replace("USDT", "") for k in ("paire", "unite", "seance", "periode") if a.get(k)]
        if a.get("periodes"):
            bits.append("+".join(a["periodes"]))
        if a.get("nombre"):
            bits.append(f"{a['nombre']} bougies")
        if a.get("query"):
            bits.append(f"« {str(a['query'])[:60]} »")
        return names.get(name, name) + (" · " + " ".join(bits) if bits else "")

    @property
    def svc(self):
        return self.app.service

    def _market(self, paire):
        m = self.svc.markets.get(str(paire).upper())
        if m is None:
            raise KeyError(f"paire non suivie : {paire}")
        if not m.ready:
            raise KeyError(f"{paire} : données en cours de chargement")
        return m

    # ---------- outils ----------
    def t_niveaux_et_zones(self, paire, unite):
        sym = str(paire).upper()
        self._market(sym)
        st = self.svc.get_state(sym, unite)
        out = {k: st.get(k) for k in ("symbol", "tf", "price", "atr", "atrPct", "levels", "zones", "liquidity", "sweeps", "context", "session",
                                       "profiles", "vp", "gex", "absorb", "error") if st.get(k) is not None}
        return dump(out, cap=20, drop=DROP | {"rows", "marks", "ladder", "tpo", "stats", "byStrike"})

    def t_bougies(self, paire, unite, nombre=40):
        sym = str(paire).upper()
        m = self._market(sym)
        n = max(5, min(120, int(nombre)))
        with self.svc.lock:
            cs = list(m.chart_candles(unite)[-n:])
        rows = [[paris(k.t), _sig(k.o), _sig(k.h), _sig(k.l), _sig(k.c), _sig(k.v), _sig(2 * k.tb - k.v) if k.tb else None,
                 _sig(2 * k.bq - k.q) if k.bq else None] for k in cs]
        out = {"paire": sym, "unite": unite, "colonnes": ["heure de Paris (ouverture)", "ouverture", "haut", "bas", "clôture", "volume (pièces)",
                                                          "delta (pièces)", "delta (dollars)"], "bougies": rows,
               "derniere_en_cours": bool(cs and cs[-1].t + _ms(unite) > self.app.source.now_ms())}
        try:
            ind = self.app.indicators(sym, unite, True, True)
            times = ind.get("times") or []
            for k, v in ind.items():
                if isinstance(v, list) and len(v) == len(times) and k != "times":
                    out.setdefault("par_bougie", {})[k] = v[-n:]
                elif not isinstance(v, (list, dict)) or k in ("fundAgg", "posSum"):
                    out.setdefault("indicateurs", {})[k] = v
            out.setdefault("par_bougie", {})["times"] = times[-n:]
        except Exception as e:
            out["indicateurs_erreur"] = f"{type(e).__name__}: {e}"
        return dump(out, cap=n + 1)

    def t_profils_volume(self, paire, periodes):
        sym = str(paire).upper()
        m = self._market(sym)
        price = self.svc.last_price(sym)
        out = {"paire": sym, "prix": price, "profils": {}}
        names = {"D": "jour", "W": "semaine", "M": "mois", "Q": "trimestre", "PM": "mois précédent", "Y": "année", "PY": "année précédente",
                 "A": "tout l'historique"}
        with self.svc.lock:
            for k in dict.fromkeys(periodes or []):
                if k not in names:
                    continue
                p = m.session_profile(k) if k in ("D", "W", "M") else m.extra_profile(k)
                out["profils"][names[k]] = _profile_summary(p, price) if p else {"erreur": "pas assez de données"}
        return dump(out, cap=12)

    def t_tpo(self, paire, seance):
        sym = str(paire).upper()
        self._market(sym)
        r = self.svc.get_tpo(sym, seance)
        return dump(r, cap=6, drop=DROP | {"rows", "letters", "grid", "cells", "profile", "tpos", "counts"})

    def t_quant(self, paire):
        hub = getattr(self.app, "quant", None)
        if hub is None:
            return dump({"erreur": "moteur exact indisponible (données simulées ou TERMINAL_QUANT=0)"})
        s = hub.snapshot(str(paire).upper())
        if s.get("ok") is False:
            return dump({"erreur": s.get("why")})
        s = {k: v for k, v in s.items() if k not in ("optFlow", "options", "errors")}
        if isinstance(s.get("cvd"), dict):
            s["cvd"] = {k: v for k, v in s["cvd"].items() if k not in ("series", "liveSince")}
        if isinstance(s.get("spotPerp"), dict):
            s["spotPerp"] = {**s["spotPerp"], "series": (s["spotPerp"].get("series") or [])[-12:]}
        if isinstance(s.get("book"), dict):
            s["book"] = {k: v for k, v in s["book"].items() if k not in ("tracked",)}
        if s.get("warming"):
            s["note"] = "moteur en démarrage : les fenêtres longues peuvent être incomplètes (voir « cover »)"
        return dump(s, cap=10)

    def t_options_btc(self, seuil_baleines_usd=5_000_000):
        hub = getattr(self.app, "quant", None)
        if hub is None:
            return dump({"erreur": "options indisponibles (données simulées ou TERMINAL_QUANT=0)"})
        if hub.opt is None:
            hub.touch(hub.symbols[0], start=hub.autostart)
            hub.poll_options()                                            # une lecture de Deribit, tout de suite
        out = {"options": dict(hub.opt) if hub.opt else {"erreur": hub.errors.get("options Deribit") or "chaîne d'options pas encore lue"}}
        if isinstance(out["options"].get("gex"), dict):
            out["options"]["gex"] = {k: v for k, v in out["options"]["gex"].items() if k != "byStrike"}
        f = getattr(hub, "optflow", None)
        if f is not None:
            s = f.summary(min_usd=max(1_000_000.0, float(seuil_baleines_usd or 5_000_000)))
            w = s.get("whales") or {}
            out["baleines_24h"] = {"seuil_usd": w.get("minUsd"), "totaux": w.get("sum"), "plus_grosses": (w.get("biggest") or [])[:10],
                                   "plus_recentes": (w.get("latest") or [])[:6],
                                   "lecture": "delta net positif = l'initiateur gagne à la hausse ; vega positif = il achète de la volatilité ; "
                                              "le sens est celui de l'initiateur, on ne sait pas s'il ouvre ou ferme"}
            out["interet_ouvert_24h"] = s.get("oi") or {"note": "pas encore deux photos espacées d'au moins une heure"}
            if s.get("error"):
                out["erreur_lecteur"] = s["error"]
        return dump(out, cap=12, drop=DROP | {"legsRaw"})

    def t_liquidations(self, paire):
        sym = str(paire).upper()
        self._market(sym)
        now = self.app.source.now_ms()
        out = {"paire": sym}
        feed = getattr(self.svc, "feed", None)
        if feed is not None:
            evs = feed.recent_liqs(sym, now - DAY, 20000)
            for h in (1, 4, 24):
                sel = [e for e in evs if e.get("t", now) >= now - h * HOUR]
                out[f"reelles_{h}h"] = {"longs_usd": sum(e["usd"] for e in sel if e.get("side") == "long"),
                                        "shorts_usd": sum(e["usd"] for e in sel if e.get("side") == "short"), "nombre": len(sel)}
            out["plus_grosses_24h"] = sorted(evs, key=lambda e: -e.get("usd", 0))[:8]
        try:
            cx = self.app.cex_page()
            if cx.get("ok") is not False:
                out["btc_par_bourse"] = cx
        except Exception as e:
            out["btc_par_bourse"] = {"erreur": f"{type(e).__name__}: {e}"}
        kp = (getattr(self.app, "liqmaps", None) or {}).get(sym)
        price = self.svc.last_price(sym)
        if kp is not None and kp.map is not None and price:
            out["carte_estimee"] = _liqmap_summary(kp.map, price)
        st = self.svc.get_state(sym, "1h")
        out["poches_de_liquidation"] = st.get("liquidity")
        return dump(out, cap=10)

    def t_flux_par_taille(self, paire, unite):
        sym = str(paire).upper()
        self._market(sym)
        return dump(self.app.size_flow(sym, unite), cap=24)

    def t_idees_et_signaux(self, paire):
        sym = str(paire).upper()
        self._market(sym)
        out = {"signaux": self.svc.signals(sym), "bureau": self.app.desk.public(self.app.source.now_ms())}
        try:
            h = self.app.history()
            out["bilan"] = {k: h.get(k) for k in ("stats", "summary", "week", "bias")}
        except Exception as e:
            out["bilan"] = {"erreur": f"{type(e).__name__}: {e}"}
        return dump(out, cap=10)

    def t_macro(self, periode):
        if periode == "mois":
            r = self.svc.macro_month(None)
            keep = ("label", "summary", "verdict", "themes", "regime", "medium", "scenarios", "fed", "statement", "consensus", "upcoming", "lines",
                    "surprises", "markets")
        else:
            r = self.svc.macro_week(None)
            keep = ("week", "summary", "view", "verdict", "themes", "events", "markets", "crypto", "next")
        return dump({k: r.get(k) for k in keep if r.get(k) is not None}, cap=12)

    def t_divergences(self):
        return dump(self.svc.div_report(), cap=12)

    def t_strategie_et_regime(self, paire):
        sym = str(paire).upper()
        self._market(sym)
        out = {}
        for k, f in (("strategie", lambda: self.svc.strategy(sym)), ("regime", lambda: self.svc.regime(sym)), ("preuves", lambda: self.svc.evidence(sym))):
            try:
                out[k] = f()
            except Exception as e:
                out[k] = {"erreur": f"{type(e).__name__}: {e}"}
        return dump(out, cap=10)

    def t_gamma_options(self):
        r = self.svc.gex_page("all", "all")
        if isinstance(r, dict) and isinstance(r.get("profile"), list):
            price = r.get("price") or r.get("spot")
            if price:
                r = {**r, "profile": sorted(r["profile"], key=lambda x: abs((x.get("strike") if isinstance(x, dict) else x[0]) - price))[:30]}
        return dump(r, cap=30)


def _ms(tf: str) -> int:
    from engine.atr import INTERVAL_MS
    return INTERVAL_MS.get(tf, HOUR)


def _profile_summary(p: dict, price) -> dict:
    """Profil sans le détail par prix : niveaux, nœuds, delta, et les prix où acheteurs et vendeurs ont le plus dominé."""
    out = {k: p.get(k) for k in ("label", "start", "end", "poc", "vah", "val", "high", "low", "volume", "delta", "buyShare", "shape", "hvn", "lvn",
                                 "exact", "step", "source") if p.get(k) is not None}
    rows = [r for r in p.get("rows") or [] if r[2] is not None]
    step = p.get("step") or 0
    if rows:
        d = sorted(rows, key=lambda r: 2 * r[2] - r[1])
        out["vendeurs_dominants"] = [{"de": r[0], "a": r[0] + step, "delta": 2 * r[2] - r[1]} for r in d[:5] if 2 * r[2] - r[1] < 0]
        out["acheteurs_dominants"] = [{"de": r[0], "a": r[0] + step, "delta": 2 * r[2] - r[1]} for r in d[::-1][:5] if 2 * r[2] - r[1] > 0]
        if price:
            here = [r for r in p["rows"] if r[0] <= price < r[0] + step]
            if here:
                r = here[0]
                out["au_prix_actuel"] = {"de": r[0], "a": r[0] + step, "volume": r[1], "delta": (2 * r[2] - r[1]) if r[2] is not None else None,
                                         "part_du_volume_max": r[1] / max(x[1] for x in p["rows"]) if p["rows"] else None}
    out["unite_delta"] = "pièces (acheteurs agressifs moins vendeurs agressifs)"
    return out


def _liqmap_summary(mp, price: float) -> dict:
    """Carte des liquidations estimée, à l'instant : les tranches les plus chargées au-dessus (shorts) et en dessous (longs) du prix."""
    from engine.liquidity import band_price
    b0l, al, b0s, as_ = mp._bands(price)
    rows = []
    for b0, arr, side in ((b0l, al, "longs"), (b0s, as_, "shorts")):
        for i, v in enumerate(arr):
            if v > 0:
                px = band_price(b0 + i)
                rows.append({"prix": px, "cote": side, "usd": v * px, "ecart_pct": (px / price - 1) * 100})
    above = sorted([r for r in rows if r["prix"] > price], key=lambda r: -r["usd"])[:6]
    below = sorted([r for r in rows if r["prix"] <= price], key=lambda r: -r["usd"])[:6]
    return {"au_dessus": sorted(above, key=lambda r: r["prix"]), "en_dessous": sorted(below, key=lambda r: -r["prix"]),
            "note": "estimation à partir de l'intérêt ouvert et des leviers usuels, pas des positions réelles"}
