"""Suivi des idees de trade : quota hebdomadaire, envoi Telegram, vie de l'idee (ordre en attente, execute, objectifs,
stop) et journal. Les idees viennent de Service.signals(). Une idee n'est envoyee que si :
  - son score atteint le seuil (la derniere place de la semaine exige 8 points de plus) ;
  - la semaine (lundi 00:00 UTC) n'a pas deja `signal_max_week` idees ;
  - aucune idee n'a ete envoyee pour ce symbole depuis 12 h, et le symbole n'a pas deja 2 idees ouvertes ;
  - aucune annonce majeure n'est imminente (verrou calcule dans le score).
Sens de tes trades (V13, reglage « signal_direction ») : en « long » (achat seulement), une configuration de VENTE n'est pas envoyee comme une idee mais comme
une « alerte pour tes longs » (hors quota, une par paire et par 24 h au plus) ; son resultat est suivi comme celui d'une idee pour savoir si elle avait raison.
Pas de biais contraires (V13.1), toutes paires confondues (BTC et SOL bougent ensemble) : aucune idee dans l'autre sens tant qu'une idee est en cours ou
qu'elle a moins de 24 h. Entre 24 h et 72 h, une idee dans l'autre sens exige que la precedente soit terminee, 10 points de qualite en plus, et le message
commence par « CHANGEMENT DE SENS » en disant clairement qu'elle REMPLACE la precedente.
Le journal est le test le plus honnete : il enregistre ce qui s'est PASSE apres chaque idee envoyee.
Journal detaille (V24) : pour chaque idee, l'heure de chaque etape (execution, objectif 1, fin), le prix le plus favorable et le plus defavorable
atteints pendant la position, le point le plus proche de l'entree pour un ordre jamais execute, et les raisons du score au moment de l'envoi.
Les idees d'avant V24 sont completees en rejouant les memes regles sur les bougies 5 min encore disponibles (sans jamais changer leur resultat)."""
import json
import threading
import time
from pathlib import Path

from engine import signals as sg
from engine.explain import paris

SIDE_WORD = {"long": "achat", "short": "vente"}
THE_SIDE = {"long": "l'achat", "short": "la vente"}
OPEN = ("pending", "active", "tp1")
MAX_HOLD_H = 7 * 24
COOLDOWN_H = 12
LOCK_H = 24                  # aucune idee dans l'autre sens pendant 24 h (et tant que la precedente est en cours), toutes paires confondues
FLIP_H = 72                  # fenetre de « changement de sens »
FLIP_EXTRA = 10.0            # points de qualite en plus pour changer de sens
ALERT_EVERY_H = 24           # une alerte de prudence par paire et par 24 h au plus
FACT_KEYS = ("best", "worst", "near", "tp1At", "endAt", "exitPx")
REPLAY_KEEP_MS = 70 * 24 * 3_600_000      # bougies 5 min gardees par le terminal (data/store.py M5_FINE_DAYS)
RESULT_WORD = {"stop": "stop touché", "tp1_be": "objectif 1 atteint puis sortie à l'équilibre", "tp2": "objectif 2 atteint", "missed": "objectif atteint sans exécution",
               "expired": "expirée sans exécution", "expired_active": "suivi arrêté après 7 jours", None: "en cours"}


def is_alert(t: dict) -> bool:
    return t.get("mode") == "alerte"


def r_of(t: dict):
    """Resultat en multiples du risque (idee executee et terminee), None sinon."""
    res = t.get("result")
    if res == "stop":
        return -1.0
    if res == "tp1_be":
        return 0.5 * t["rr1"]
    if res == "tp2":
        return 0.5 * t["rr1"] + 0.5 * (t["rr2"] or t["rr1"])
    if res == "expired_active" or (res is None and t.get("status") == "tp1"):
        return None
    return 0.0 if res in ("expired", "missed") else None


def alert_verdict(t: dict):
    """Une alerte (configuration dans l'autre sens que tes trades) avait-elle raison ? True / False / None (pas tranche)."""
    if t.get("status") == "tp1" or t.get("result") in ("tp1_be", "tp2", "missed"):
        return True
    if t.get("result") == "stop":
        return False
    return None


class TradeDesk:
    def __init__(self, cfg, notifier, now=time.time, log=None, opinions=None):
        self.cfg, self.notifier, self.now, self.log = cfg, notifier, now, log
        self.opinions = opinions                 # f(symbole, sens) -> avis d'influenceurs (facultatif, JAMAIS dans le score)
        self.inline = False                      # tests : lire l'avis tout de suite, sans fil d'arriere-plan
        self._lock = threading.Lock()
        self.dir = Path(cfg.data_dir) / ("simulated" if cfg.source == "simulated" else "")
        self.file = self.dir / "trades.json"
        self.trades: list[dict] = []
        self.waiting: dict = {}                  # raison pour laquelle la meilleure idee n'est pas envoyee (affichage)
        self._quiet = False                      # rejeu du passe (journal d'avant V24) : aucun message
        self._load()

    # --- persistance ---
    def _load(self):
        try:
            self.trades = json.loads(self.file.read_text(encoding="utf-8"))
        except Exception:
            self.trades = []

    def _save(self):
        with self._lock:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                tmp = self.file.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.trades[-300:], ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.file)
            except OSError:
                pass

    def _send(self, trade, text, kind):
        if self._quiet:
            return True
        ok, detail = True, "envoye"
        for part in sg.split_message(text):                          # un long message part en plusieurs, sans rien perdre
            ok1, detail1 = self.notifier.send(part)
            if not ok1:
                ok, detail = False, detail1
        if self.log:
            self.log({"t": self.now(), "symbol": trade["symbol"], "kind": kind, "mid": trade["entry"], "text": text, "sent": ok, "detail": detail})
        return ok

    # --- semaine ---
    def week(self, now_ms):
        start = sg.week_start(now_ms)
        sent = [t for t in self.trades if t["created"] >= start and not is_alert(t)]
        cap = self.cfg.signal_max_week
        return {"start": start, "sent": len(sent), "cap": cap, "remaining": max(0, cap - len(sent))}

    # --- creation ---
    def consider(self, sigs: dict, now_ms: int):
        """sigs : {symbole: Service.signals(...)}. Envoie les nouvelles idees (meilleures d'abord), puis les alertes de prudence."""
        cfg = self.cfg
        direction = getattr(cfg, "signal_direction", "both")
        w = self.week(now_ms)
        cands = [(i["score"], s, i) for s, sig in sigs.items() if sig.get("ready") and sig.get("warm") for i in sig["ideas"] if i["eligible"]]
        cands.sort(key=lambda x: -x[0])
        self.waiting = {}
        created, against = [], []
        for score, sym, idea in cands:
            if direction != "both" and idea["side"] != direction:
                against.append((score, sym, idea))                       # pas une idee pour toi : une alerte de prudence, plus bas
                continue
            sent = w["sent"] + len(created)
            if sent >= cfg.signal_max_week:
                self.waiting = {"why": f"quota de la semaine atteint ({cfg.signal_max_week} idées) : la meilleure idée suivante est {sym} {SIDE_WORD[idea['side']]} ({score:.0f}/100)"}
                break
            per_sym = sum(1 for t in self.trades if t["created"] >= w["start"] and t["symbol"] == sym and not is_alert(t)) + sum(1 for c in created if c["symbol"] == sym)
            if len(sigs) > 1 and per_sym >= min(cfg.signal_max_per_symbol, cfg.signal_max_week):
                self.waiting = {"why": f"{per_sym} idées déjà envoyées cette semaine sur {sym} (maximum {cfg.signal_max_per_symbol} par paire pour laisser de la place aux autres paires)"}
                continue
            need = cfg.signal_min_score + (8.0 if cfg.signal_max_week > 1 and sent == cfg.signal_max_week - 1 else 0.0)
            if score < need:
                self.waiting = {"why": f"dernière place de la semaine : exige {need:.0f}/100, la meilleure idée ({sym} {SIDE_WORD[idea['side']]}) a {score:.0f}/100"}
                continue
            if self._duplicate(sym, idea, now_ms):
                continue
            block = self._contradicts(idea, now_ms)
            if block is not None:
                what = f"{sym} {SIDE_WORD[idea['side']]} contredirait {THE_SIDE[block['side']]} {block['symbol']} du {paris(block['created'])}"
                if block["status"] in OPEN:
                    self.waiting = {"why": f"{what}, encore en cours : pas d'idée dans l'autre sens tant qu'elle n'est pas terminée"}
                else:
                    self.waiting = {"why": f"{what} : pas d'idée dans l'autre sens moins de {LOCK_H} h après une idée (pas avant le {paris(block['created'] + LOCK_H * 3_600_000)})"}
                continue
            prev = self._flip(idea, now_ms)
            if prev is not None and score < need + FLIP_EXTRA:
                self.waiting = {"why": f"{sym} {SIDE_WORD[idea['side']]} change de sens par rapport à {THE_SIDE[prev['side']]} {prev['symbol']} du {paris(prev['created'])} : exige {need + FLIP_EXTRA:.0f}/100, elle a {score:.0f}/100"}
                continue
            created.append(self._create(sym, idea, now_ms, sent + 1, flip=prev))
        for score, sym, idea in against:
            if score >= cfg.signal_min_score and self._alert_ok(sym, idea, now_ms):
                created.append(self._create_alert(sym, idea, now_ms))
        return created

    def _contradicts(self, idea, now_ms):
        """Idee dans l'autre sens, sur n'importe quelle paire, encore en cours ou de moins de 24 h (la plus recente) ; None s'il n'y en a pas."""
        live = [t for t in self.trades if not is_alert(t) and t["side"] != idea["side"]
                and (t["status"] in OPEN or now_ms - t["created"] < LOCK_H * 3_600_000)]
        return max(live, key=lambda t: t["created"], default=None)

    def _flip(self, idea, now_ms):
        """Derniere idee (pas une alerte, toutes paires confondues) de moins de 72 h si elle va dans l'autre sens ; None sinon."""
        prev = [t for t in self.trades if not is_alert(t) and now_ms - t["created"] < FLIP_H * 3_600_000]
        last = max(prev, key=lambda t: t["created"], default=None)
        return last if last is not None and last["side"] != idea["side"] else None

    def bias(self, now_ms):
        """Sens actuel du terminal, toutes paires confondues : celui des idees en cours ou de moins de 24 h. None s'il n'y en a pas
        (la prochaine idee peut aller dans les deux sens ; entre 24 h et 72 h, l'autre sens exige 10 points de plus)."""
        live = [t for t in self.trades if not is_alert(t) and (t["status"] in OPEN or now_ms - t["created"] < LOCK_H * 3_600_000)]
        if not live:
            return None
        last = max(live, key=lambda t: t["created"])
        same = [t for t in live if t["side"] == last["side"]]
        return {"side": last["side"], "symbol": last["symbol"], "created": last["created"], "entry": last["entry"], "status": last["status"],
                "until": max(t["created"] for t in same) + LOCK_H * 3_600_000,
                "open": [{"symbol": t["symbol"], "created": t["created"], "status": t["status"]} for t in same if t["status"] in OPEN],
                "mixed": any(t["side"] != last["side"] for t in live)}

    def _alert_ok(self, sym, idea, now_ms):
        for t in self.trades:
            if t["symbol"] == sym and is_alert(t) and (now_ms - t["created"] < ALERT_EVERY_H * 3_600_000 or (t["key"] == idea["key"] and now_ms - t["created"] < 48 * 3_600_000)):
                return False
        return True

    def _duplicate(self, sym, idea, now_ms):
        for t in self.trades:
            if t["symbol"] != sym or is_alert(t):
                continue
            if now_ms - t["created"] < COOLDOWN_H * 3_600_000:
                return True                                              # une seule idee par symbole toutes les 12 h (pas d'achat ET de vente d'un coup)
            if t["side"] != idea["side"]:
                continue
            if t["status"] in OPEN and abs(t["entry"] - idea["entry"]) < 1.5 * idea["atr"]:
                return True
            if t["key"] == idea["key"] and now_ms - t["created"] < 48 * 3_600_000:
                return True
        return sum(1 for t in self.trades if t["symbol"] == sym and t["status"] in OPEN and not is_alert(t)) >= 2

    def _record(self, sym, idea, now_ms, n):
        desc, probs, st = idea.get("desc") or {}, idea.get("probs") or {}, idea.get("st") or {}
        fill, plan = probs.get("fill") or {}, probs.get("plan") or {}
        return {"id": f"{sym}-{now_ms}", "key": idea["key"], "symbol": sym, "side": idea["side"], "kind": idea["kind"],
                "created": now_ms, "score": idea["score"], "entry": idea["entry"], "entryType": idea["entryType"],
                "stop": idea["stop"], "tp1": idea["tp1"], "tp2": idea.get("tp2"), "rr1": idea["rr1"], "rr2": idea.get("rr2"),
                "atr": idea["atr"], "zone": idea["zone"],
                "validUntil": now_ms + idea["validHours"] * 3_600_000,
                "status": "active" if idea["entryType"] == "marché" else "pending", "result": None, "checked": now_ms,
                "filledAt": now_ms if idea["entryType"] == "marché" else None, "closedAt": None, "n": n,
                "title": idea["desc"]["headline"],
                # journal detaille (V24) : contexte au moment de l'envoi
                "v": 2, "px0": idea.get("price"), "validHours": idea.get("validHours"), "align": idea.get("align"),
                "tp1Kind": idea.get("tp1Kind"), "tp2Kind": idea.get("tp2Kind"), "zoneS": st.get("S"), "zoneN": st.get("n"),
                "comps": [{"label": c.get("label"), "pts": round(float(c.get("pts") or 0.0), 1), "max": c.get("max"), "note": c.get("note") or ""}
                          for c in idea.get("comps") or []],
                "warn": [w for w in idea.get("warn") or [] if w][:6], "lev": (desc.get("leverage") or {}).get("lev"),
                "pFill": fill.get("p24") if idea["entryType"] == "limite" else None, "pTp": (plan.get("tp") or {}).get("p")}

    def _create(self, sym, idea, now_ms, n, flip=None):
        text = sg.to_text(idea, idea["desc"], n, self.cfg.signal_max_week)
        tr = self._record(sym, idea, now_ms, n)
        if flip is not None:
            res = RESULT_WORD.get(flip.get("result"), flip.get("result"))
            text = (f"⚠️ CHANGEMENT DE SENS sur {sym}\nLe {paris(flip['created'])} je t'ai envoyé un{'' if flip['side'] == 'long' else 'e'} {SIDE_WORD[flip['side']]} sur {flip['symbol']} à {sg.fmt_price(flip['entry'])} "
                    f"({res}). Cette idée va dans l'autre sens : elle REMPLACE la précédente, elle ne s'y ajoute pas.\n\n") + text
            tr["flipFrom"] = {"id": flip["id"], "symbol": flip["symbol"], "side": flip["side"], "created": flip["created"], "result": flip.get("result")}
        tr["text"] = text
        tr["sent"] = self._send(tr, text, "trade")
        self.trades.append(tr)
        self._save()
        self._send_opinions(tr)
        return tr

    def _create_alert(self, sym, idea, now_ms):
        """Configuration dans l'autre sens que tes trades : message de prudence (hors quota), suivi pour savoir si elle avait raison."""
        tr = self._record(sym, idea, now_ms, None)
        tr["mode"] = "alerte"
        mine = "long" if idea["side"] == "short" else "short"
        px = sg.fmt_price
        opens = [t for t in self.trades if t["symbol"] == sym and t["side"] == mine and t["status"] in OPEN and not is_alert(t)]
        who = "longs" if mine == "long" else "shorts"
        how = "à l'achat" if mine == "long" else "à la vente"
        lines = [f"🛡 Alerte pour tes {who} · {sym}",
                 f"Le terminal voit une configuration de {SIDE_WORD[idea['side']].upper()} de qualité {idea['score']:.0f}/100 autour de {px(idea['entry'])}. "
                 f"Tu trades {how} : ce n'est pas une idée de {SIDE_WORD[idea['side']]}, c'est un signal de prudence.", ""]
        if mine == "long":
            lines += [f"• Elle est fausse si le prix repasse au-dessus de {px(idea['stop'])} ; tant qu'il reste en dessous, le marché peut aller chercher {px(idea['tp1'])}"
                      + (f", puis {px(idea['tp2'])}." if idea.get("tp2") else "."),
                      "• Si tu es long : allège, remonte ton stop, ou attends que le prix tienne au-dessus de " + px(idea["stop"]) + " avant de renforcer."]
        else:
            lines += [f"• Elle est fausse si le prix repasse sous {px(idea['stop'])} ; tant qu'il reste au-dessus, le marché peut aller chercher {px(idea['tp1'])}"
                      + (f", puis {px(idea['tp2'])}." if idea.get("tp2") else "."),
                      "• Si tu es short : allège, descends ton stop, ou attends que le prix repasse sous " + px(idea["stop"]) + " avant de renforcer."]
        for t in opens:
            kind = "d'achat" if t["side"] == "long" else "de vente"
            lines.append(f"• Ton idée {kind} du {paris(t['created'])} (entrée {px(t['entry'])}, stop {px(t['stop'])}) est toujours ouverte : garde son stop, ne le recule pas.")
        why = [x for x in idea["desc"].get("why", []) if x.strip()][:8]
        if why:
            lines += ["", "▶ POURQUOI"] + why
        text = "\n".join(lines)
        tr["text"], tr["title"] = text, f"{sym} : alerte pour tes {who}"
        tr["sent"] = self._send(tr, text, "trade-alerte")
        self.trades.append(tr)
        self._save()
        return tr

    def _send_opinions(self, tr):
        """Avis des comptes X suivis, envoye juste apres l'idee (message separe, fin de l'analyse). Hors score, hors decision."""
        if not self.opinions:
            return

        def run():
            try:
                from engine import stance
                op = self.opinions(tr["symbol"], tr["side"])
                if not op or not op.get("on"):
                    return
                tr["x"] = op["summary"]
                self._send(tr, stance.format_block(op, tr["symbol"], tr["side"]), "trade-x")
                self._save()
            except Exception as e:                       # un echec n'a aucun effet sur l'idee
                if self.log:
                    self.log({"t": self.now(), "symbol": tr["symbol"], "kind": "trade-x", "mid": tr["entry"], "text": "avis X indisponible", "sent": False,
                              "detail": f"{type(e).__name__}: {e}"})
        if self.inline:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    # --- vie de l'idee ---
    def track(self, sym: str, candles5: list, now_ms: int):
        """candles5 : [(t, haut, bas, cloture)] bougies 5 min. Fait avancer les idees ouvertes de ce symbole."""
        changed = False
        for tr in self.trades:
            if tr["symbol"] != sym or tr["status"] not in OPEN:
                continue
            last = None
            for t, h, l, c in candles5:
                if t < tr["created"] or t < tr["checked"] - 300_000:
                    continue
                self._step(tr, t, h, l, now_ms)
                tr["checked"] = max(tr["checked"], t)
                last = c
                if tr["status"] not in OPEN:
                    break
            self._expire(tr, now_ms, last)
            changed = True
        if changed:
            self._save()

    def _expire(self, tr, now_ms, last_close=None):
        if tr["status"] == "pending" and now_ms > tr["validUntil"]:
            self._close(tr, "expired", now_ms, tr["validUntil"])
        elif tr["status"] in ("active", "tp1") and now_ms - tr["filledAt"] > MAX_HOLD_H * 3_600_000:
            if last_close is not None:
                tr["exitPx"] = last_close                                   # prix au moment ou le suivi s'arrete (resultat latent, non compte)
            self._close(tr, "expired_active", now_ms, tr["filledAt"] + MAX_HOLD_H * 3_600_000)

    def _step(self, tr, t, h, l, now_ms):
        long_ = tr["side"] == "long"
        e, s, t1, t2 = tr["entry"], tr["stop"], tr["tp1"], tr["tp2"]
        below = lambda x: l <= x                                            # achat : le prix descend jusqu'a x
        above = lambda x: h >= x
        adverse = (lambda x: below(x)) if long_ else (lambda x: above(x))   # mouvement contre l'idee
        favour = (lambda x: above(x)) if long_ else (lambda x: below(x))    # mouvement dans le sens de l'idee
        if tr["status"] == "pending":
            near = l if long_ else h                                        # point le plus proche de l'entree tant que l'ordre attend
            nr = tr.get("near")
            if nr is None or (near < nr["p"] if long_ else near > nr["p"]):
                tr["near"] = {"p": near, "t": t}
            if adverse(e):                                                  # ordre limite execute
                tr["status"], tr["filledAt"] = "active", t
                self._notify(tr, "fill", now_ms)
                if adverse(s):
                    self._extreme(tr, t, h, l, fav=False, cap=s)
                    self._close(tr, "stop", now_ms, t)                      # execute puis stoppe dans la meme bougie
                else:
                    self._extreme(tr, t, h, l, fav=False)                   # dans la bougie d'execution, seul le mouvement contraire suit surement l'entree
            elif favour(t1):
                self._close(tr, "missed", now_ms, t)                        # objectif atteint sans execution
            return
        if t <= tr["filledAt"]:
            return                                                          # bougie d'execution : on ne compte pas l'objectif
        if tr["status"] == "active":
            if adverse(s):
                self._extreme(tr, t, h, l, fav=False, cap=s)                # ordre inconnu dans la bougie : on retient le pire (comme le resultat)
                self._close(tr, "stop", now_ms, t)
            elif favour(t1):
                tr["status"], tr["tp1At"] = "tp1", t
                self._notify(tr, "tp1", now_ms)
                if t2 and favour(t2):
                    self._extreme(tr, t, h, l, adv=False, cap=t2)
                    self._close(tr, "tp2", now_ms, t)
                else:
                    self._extreme(tr, t, h, l)
            else:
                self._extreme(tr, t, h, l)
        elif tr["status"] == "tp1":
            if adverse(e):
                self._extreme(tr, t, h, l, fav=False, cap=e)
                self._close(tr, "tp1_be", now_ms, t)
            elif t2 and favour(t2):
                self._extreme(tr, t, h, l, adv=False, cap=t2)
                self._close(tr, "tp2", now_ms, t)
            else:
                self._extreme(tr, t, h, l)

    @staticmethod
    def _extreme(tr, t, h, l, fav=True, adv=True, cap=None):
        """Prix le plus favorable (« best ») et le plus defavorable (« worst ») atteints pendant la position, avec l'heure de la bougie.
        cap : prix de sortie dans la bougie qui ferme la position (stop, entree, objectif 2) ; ce qui va au-dela s'est passe apres la sortie."""
        long_ = tr["side"] == "long"
        if adv:
            p, w = (l if long_ else h), tr.get("worst")
            if cap is not None:
                p = max(p, cap) if long_ else min(p, cap)
            if w is None or (p < w["p"] if long_ else p > w["p"]):
                tr["worst"] = {"p": p, "t": t}
        if fav:
            p, b = (h if long_ else l), tr.get("best")
            if cap is not None:
                p = min(p, cap) if long_ else max(p, cap)
            if b is None or (p > b["p"] if long_ else p < b["p"]):
                tr["best"] = {"p": p, "t": t}

    def _close(self, tr, result, now_ms, at=None):
        """at : heure de la bougie ou c'est arrive (endAt) ; closedAt reste l'heure ou le terminal l'a constate."""
        tr["status"], tr["result"], tr["closedAt"] = "closed", result, now_ms
        tr["endAt"] = at if at is not None else now_ms
        self._notify(tr, result, now_ms)

    # --- journal d'avant V24 : moments cles retrouves en rejouant les memes regles ---
    def backfill(self, sym: str, candles5: list, now_ms: int, limit: int = 60) -> int:
        """candles5 : [(t, haut, bas, cloture)] toutes les bougies 5 min disponibles. Pour les idees sans journal detaille, rejoue les regles
        de suivi sur une copie, sans aucun message, et ne garde les moments cles (heure de l'objectif 1, fin, meilleur et pire prix, point
        le plus proche de l'entree) que si le rejeu retrouve exactement le deroule enregistre. Le resultat enregistre ne change jamais.
        Renvoie le nombre d'idees completees."""
        if not candles5:
            return 0
        first, done, changed = candles5[0][0], 0, False
        for tr in self.trades:
            if tr["symbol"] != sym or tr.get("v", 1) >= 2:
                continue
            if done >= limit:
                break
            if tr["created"] < first:
                if now_ms - tr["created"] > REPLAY_KEEP_MS:                 # bougies 5 min plus disponibles : rien a recalculer
                    tr["v"], tr["replay"] = 2, "absent"
                    changed = True
                continue                                                    # sinon les bougies plus anciennes peuvent encore arriver
            end = tr.get("closedAt") if tr["status"] == "closed" else tr["checked"]
            if end is None or candles5[-1][0] < min(end, now_ms) - 600_000:
                continue                                                    # bougies pas encore a jour
            tr.update(self._replay(tr, candles5, end, now_ms))
            done += 1
            changed = True
        if changed:
            self._save()
        return done

    def _replay(self, tr, candles5, end, now_ms):
        cp = {k: v for k, v in tr.items() if k not in FACT_KEYS}
        market = tr["entryType"] == "marché"
        cp.update(status="active" if market else "pending", result=None, closedAt=None, endAt=None, checked=tr["created"],
                  filledAt=tr["created"] if market else None)
        self._quiet = True
        try:
            last = None
            for t, h, l, c in candles5:
                if t < cp["created"]:
                    continue
                if t > end:
                    break
                self._step(cp, t, h, l, now_ms)
                last = c
                if cp["status"] not in OPEN:
                    break
            if tr["status"] == "closed" and cp["status"] in OPEN and tr["result"] in ("expired", "expired_active"):
                self._expire(cp, max(now_ms, tr.get("closedAt") or 0), last)
        finally:
            self._quiet = False
        same = cp["status"] == tr["status"] and cp.get("result") == tr.get("result") and cp.get("filledAt") == tr.get("filledAt")
        if not same:
            return {"v": 2, "replay": "different"}                          # bougies differentes de celles du suivi en direct : on ne devine rien
        out = {k: cp[k] for k in FACT_KEYS if cp.get(k) is not None and k not in ("exitPx",)}
        if tr["status"] == "closed" and tr["result"] in ("expired", "expired_active"):
            out["endAt"] = tr["validUntil"] if tr["result"] == "expired" else tr["filledAt"] + MAX_HOLD_H * 3_600_000
        if tr.get("exitPx") is None and cp.get("exitPx") is not None:
            out["exitPx"] = cp["exitPx"]
        return {**out, "v": 2, "replay": "ok"}

    def _notify(self, tr, kind, now_ms):
        if is_alert(tr):
            return                                                          # une alerte n'est suivie que pour l'historique, sans message
        w = SIDE_WORD[tr["side"]]
        head = f"{tr['symbol']} {w}"
        px = sg.fmt_price
        msg = {
            "fill": f"✅ Ordre exécuté · {head} à {px(tr['entry'])}\nStop {px(tr['stop'])} · objectif 1 {px(tr['tp1'])}" + (f" · objectif 2 {px(tr['tp2'])}" if tr["tp2"] else "") + ".\nSi tu n'as pas posé d'ordre, ne cours pas après le prix.",
            "tp1": f"🎯 Objectif 1 atteint · {head} ({px(tr['tp1'])})\nConseil : prends une partie des gains et remonte ton stop à l'entrée ({px(tr['entry'])}) : le reste ne peut plus te faire perdre." + (f"\nObjectif 2 : {px(tr['tp2'])}." if tr["tp2"] else ""),
            "tp2": f"🏁 Objectif 2 atteint · {head} ({px(tr['tp2'])}). Idée terminée.",
            "tp1_be": f"↩ {head} : le prix est revenu à l'entrée après l'objectif 1. Le reste est fermé à l'équilibre. Idée terminée.",
            "stop": f"🛑 Stop touché · {head} ({px(tr['stop'])}). L'idée est fausse, perte prévue : 1 fois le risque. Pas de nouvelle entrée sur cette zone avant {COOLDOWN_H} h.",
            "missed": f"➖ {head} : l'objectif 1 ({px(tr['tp1'])}) a été atteint sans que l'ordre à {px(tr['entry'])} soit exécuté. Retire ton ordre : ne cours pas après le prix.",
            "expired": f"⌛ Idée expirée · {head} : l'ordre à {px(tr['entry'])} n'a pas été exécuté dans le délai. Retire-le.",
            "expired_active": f"⌛ {head} : plus de suivi après {MAX_HOLD_H // 24} jours. À toi de gérer la position.",
        }.get(kind)
        if msg:
            self._send(tr, msg, "trade-suivi")

    # --- tout en un ---
    def run_cycle(self, sigs: dict, m5s: dict, now_ms: int):
        for sym, cs in m5s.items():
            self.track(sym, cs, now_ms)
        return self.consider(sigs, now_ms)

    # --- affichage ---
    def stats(self):
        ideas = [t for t in self.trades if not is_alert(t)]
        closed = [t for t in ideas if t["status"] == "closed" and t["result"] in ("stop", "tp1_be", "tp2")]
        out = {"ideas": len(ideas), "executed": sum(1 for t in ideas if t["filledAt"]), "stop": 0, "tp1_be": 0, "tp2": 0, "r": 0.0}
        for t in closed:
            out[t["result"]] += 1
            out["r"] += -1.0 if t["result"] == "stop" else 0.5 * t["rr1"] if t["result"] == "tp1_be" else 0.5 * t["rr1"] + 0.5 * (t["rr2"] or t["rr1"])
        out["tp1_open"] = sum(1 for t in ideas if t["status"] == "tp1")
        out["open"] = sum(1 for t in ideas if t["status"] in OPEN)
        al = [alert_verdict(t) for t in self.trades if is_alert(t)]
        out["alerts"] = {"n": len(al), "right": sum(1 for v in al if v is True), "wrong": sum(1 for v in al if v is False)}
        return out

    def public(self, now_ms: int):
        keys = ("id", "symbol", "side", "kind", "created", "score", "entry", "entryType", "stop", "tp1", "tp2", "rr1", "rr2", "validUntil",
                "status", "result", "filledAt", "closedAt", "n", "title", "sent", "x", "mode", "flipFrom")
        return {"week": self.week(now_ms), "waiting": self.waiting, "stats": self.stats(), "bias": self.bias(now_ms),
                "trades": [{k: t.get(k) for k in keys} for t in self.trades[-40:][::-1]]}

    def history(self, now_ms: int, lev=None, expect=None, prices=None) -> dict:
        """Tout le journal (texte compris) avec le resultat de chaque idee et de chaque alerte, du plus recent au plus ancien.
        V24 : recit en clair de chaque idee, meilleur et pire moment, statistiques par categorie (alerts/journal.py).
        lev : levier des reglages (si l'idee ne l'a pas enregistre) ; expect : {symbole: attendu du backtest} ; prices : {symbole: prix actuel}."""
        from alerts import journal                                          # (journal importe ce module)
        prices = prices or {}
        out = []
        for t in self.trades[::-1]:
            row = {k: t.get(k) for k in ("id", "symbol", "side", "kind", "created", "score", "entry", "entryType", "stop", "tp1", "tp2", "rr1", "rr2",
                                          "status", "result", "filledAt", "closedAt", "n", "title", "sent", "mode", "flipFrom", "text", "checked",
                                          "validUntil", "zone", "align", "zoneS", "comps", "lev", "pFill", "pTp", "best", "worst", "near", "tp1At",
                                          "endAt", "exitPx", "replay", "px0")}
            row["r"] = None if is_alert(t) else r_of(t)
            row["verdict"] = alert_verdict(t) if is_alert(t) else None
            row["resultText"] = RESULT_WORD.get(t.get("result"), t.get("result")) if t.get("status") == "closed" else {"pending": "ordre en attente", "active": "en position",
                                                                                                                        "tp1": "objectif 1 atteint, reste en cours"}.get(t["status"], t["status"])
            pnow = prices.get(t["symbol"]) if t["status"] in ("active", "tp1") else None
            row["outcome"] = journal.outcome(t)
            row["rBest"] = journal.r_at(t, t["best"]["p"]) if t.get("best") else None
            row["rWorst"] = journal.r_at(t, t["worst"]["p"]) if t.get("worst") else None
            row["riskPct"] = journal.risk_pct(t)
            row["rNow"] = journal.latent_r(t, pnow if pnow is not None else t.get("exitPx") if t.get("result") == "expired_active" else None)
            end = journal.end_of(t)
            row["held"] = (end if t["status"] == "closed" else now_ms) - t["filledAt"] if t.get("filledAt") and (end or t["status"] != "closed") else None
            row["story"] = journal.story(t, lev=t.get("lev") or lev, price_now=pnow)
            out.append(row)
        return {"trades": out, "stats": self.stats(), "summary": journal.summary(self.trades, expect), "week": self.week(now_ms), "bias": self.bias(now_ms)}
