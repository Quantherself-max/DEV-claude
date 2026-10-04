"""Suivi des idees de trade : quota hebdomadaire, envoi Telegram, vie de l'idee (ordre en attente, execute, objectifs,
stop) et journal. Les idees viennent de Service.signals(). Une idee n'est envoyee que si :
  - son score atteint le seuil (la derniere place de la semaine exige 8 points de plus) ;
  - la semaine (lundi 00:00 UTC) n'a pas deja `signal_max_week` idees ;
  - aucune idee n'a ete envoyee pour ce symbole depuis 12 h, et le symbole n'a pas deja 2 idees ouvertes ;
  - aucune annonce majeure n'est imminente (verrou calcule dans le score).
Le journal est le test le plus honnete : il enregistre ce qui s'est PASSE apres chaque idee envoyee."""
import json
import time
from pathlib import Path

from engine import signals as sg

SIDE_WORD = {"long": "achat", "short": "vente"}
OPEN = ("pending", "active", "tp1")
MAX_HOLD_H = 7 * 24
COOLDOWN_H = 12


class TradeDesk:
    def __init__(self, cfg, notifier, now=time.time, log=None):
        self.cfg, self.notifier, self.now, self.log = cfg, notifier, now, log
        self.dir = Path(cfg.data_dir) / ("simulated" if cfg.source == "simulated" else "")
        self.file = self.dir / "trades.json"
        self.trades: list[dict] = []
        self.waiting: dict = {}                  # raison pour laquelle la meilleure idee n'est pas envoyee (affichage)
        self._load()

    # --- persistance ---
    def _load(self):
        try:
            self.trades = json.loads(self.file.read_text(encoding="utf-8"))
        except Exception:
            self.trades = []

    def _save(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.trades[-300:], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)
        except OSError:
            pass

    def _send(self, trade, text, kind):
        ok, detail = self.notifier.send(text)
        if self.log:
            self.log({"t": self.now(), "symbol": trade["symbol"], "kind": kind, "mid": trade["entry"], "text": text, "sent": ok, "detail": detail})
        return ok

    # --- semaine ---
    def week(self, now_ms):
        start = sg.week_start(now_ms)
        sent = [t for t in self.trades if t["created"] >= start]
        cap = self.cfg.signal_max_week
        return {"start": start, "sent": len(sent), "cap": cap, "remaining": max(0, cap - len(sent))}

    # --- creation ---
    def consider(self, sigs: dict, now_ms: int):
        """sigs : {symbole: Service.signals(...)}. Envoie les nouvelles idees (meilleures d'abord)."""
        cfg = self.cfg
        w = self.week(now_ms)
        cands = [(i["score"], s, i) for s, sig in sigs.items() if sig.get("ready") and sig.get("warm") for i in sig["ideas"] if i["eligible"]]
        cands.sort(key=lambda x: -x[0])
        self.waiting = {}
        created = []
        for score, sym, idea in cands:
            sent = w["sent"] + len(created)
            if sent >= cfg.signal_max_week:
                self.waiting = {"why": f"quota de la semaine atteint ({cfg.signal_max_week} idées) : la meilleure idée suivante est {sym} {SIDE_WORD[idea['side']]} ({score:.0f}/100)"}
                break
            need = cfg.signal_min_score + (8.0 if cfg.signal_max_week > 1 and sent == cfg.signal_max_week - 1 else 0.0)
            if score < need:
                self.waiting = {"why": f"dernière place de la semaine : exige {need:.0f}/100, la meilleure idée ({sym} {SIDE_WORD[idea['side']]}) a {score:.0f}/100"}
                continue
            if self._duplicate(sym, idea, now_ms):
                continue
            created.append(self._create(sym, idea, now_ms, sent + 1))
        return created

    def _duplicate(self, sym, idea, now_ms):
        for t in self.trades:
            if t["symbol"] != sym:
                continue
            if now_ms - t["created"] < COOLDOWN_H * 3_600_000:
                return True                                              # une seule idee par symbole toutes les 12 h (pas d'achat ET de vente d'un coup)
            if t["side"] != idea["side"]:
                continue
            if t["status"] in OPEN and abs(t["entry"] - idea["entry"]) < 1.5 * idea["atr"]:
                return True
            if t["key"] == idea["key"] and now_ms - t["created"] < 48 * 3_600_000:
                return True
        return sum(1 for t in self.trades if t["symbol"] == sym and t["status"] in OPEN) >= 2

    def _create(self, sym, idea, now_ms, n):
        text = sg.to_text(idea, idea["desc"], n, self.cfg.signal_max_week)
        tr = {"id": f"{sym}-{now_ms}", "key": idea["key"], "symbol": sym, "side": idea["side"], "kind": idea["kind"],
              "created": now_ms, "score": idea["score"], "entry": idea["entry"], "entryType": idea["entryType"],
              "stop": idea["stop"], "tp1": idea["tp1"], "tp2": idea.get("tp2"), "rr1": idea["rr1"], "rr2": idea.get("rr2"),
              "atr": idea["atr"], "zone": idea["zone"],
              "validUntil": now_ms + idea["validHours"] * 3_600_000,
              "status": "active" if idea["entryType"] == "marché" else "pending", "result": None, "checked": now_ms,
              "filledAt": now_ms if idea["entryType"] == "marché" else None, "closedAt": None, "n": n,
              "title": idea["desc"]["headline"], "text": text}
        tr["sent"] = self._send(tr, text, "trade")
        self.trades.append(tr)
        self._save()
        return tr

    # --- vie de l'idee ---
    def track(self, sym: str, candles5: list, now_ms: int):
        """candles5 : [(t, haut, bas, cloture)] bougies 5 min. Fait avancer les idees ouvertes de ce symbole."""
        changed = False
        for tr in self.trades:
            if tr["symbol"] != sym or tr["status"] not in OPEN:
                continue
            for t, h, l, c in candles5:
                if t < tr["created"] or t < tr["checked"] - 300_000:
                    continue
                self._step(tr, t, h, l, now_ms)
                tr["checked"] = max(tr["checked"], t)
                if tr["status"] not in OPEN:
                    break
            if tr["status"] == "pending" and now_ms > tr["validUntil"]:
                self._close(tr, "expired", now_ms)
            elif tr["status"] in ("active", "tp1") and now_ms - tr["filledAt"] > MAX_HOLD_H * 3_600_000:
                self._close(tr, "expired_active", now_ms)
            changed = True
        if changed:
            self._save()

    def _step(self, tr, t, h, l, now_ms):
        long_ = tr["side"] == "long"
        e, s, t1, t2 = tr["entry"], tr["stop"], tr["tp1"], tr["tp2"]
        below = lambda x: l <= x                                            # achat : le prix descend jusqu'a x
        above = lambda x: h >= x
        adverse = (lambda x: below(x)) if long_ else (lambda x: above(x))   # mouvement contre l'idee
        favour = (lambda x: above(x)) if long_ else (lambda x: below(x))    # mouvement dans le sens de l'idee
        if tr["status"] == "pending":
            if adverse(e):                                                  # ordre limite execute
                tr["status"], tr["filledAt"] = "active", t
                self._notify(tr, "fill", now_ms)
                if adverse(s):
                    self._close(tr, "stop", now_ms)                         # execute puis stoppe dans la meme bougie
            elif favour(t1):
                self._close(tr, "missed", now_ms)                           # objectif atteint sans execution
            return
        if t <= tr["filledAt"]:
            return                                                          # bougie d'execution : on ne compte pas l'objectif
        if tr["status"] == "active":
            if adverse(s):
                self._close(tr, "stop", now_ms)
            elif favour(t1):
                tr["status"] = "tp1"
                self._notify(tr, "tp1", now_ms)
                if t2 and favour(t2):
                    self._close(tr, "tp2", now_ms)
        elif tr["status"] == "tp1":
            if adverse(e):
                self._close(tr, "tp1_be", now_ms)
            elif t2 and favour(t2):
                self._close(tr, "tp2", now_ms)

    def _close(self, tr, result, now_ms):
        tr["status"], tr["result"], tr["closedAt"] = "closed", result, now_ms
        self._notify(tr, result, now_ms)

    def _notify(self, tr, kind, now_ms):
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
        closed = [t for t in self.trades if t["status"] == "closed" and t["result"] in ("stop", "tp1_be", "tp2")]
        out = {"ideas": len(self.trades), "executed": sum(1 for t in self.trades if t["filledAt"]), "stop": 0, "tp1_be": 0, "tp2": 0, "r": 0.0}
        for t in closed:
            out[t["result"]] += 1
            out["r"] += -1.0 if t["result"] == "stop" else 0.5 * t["rr1"] if t["result"] == "tp1_be" else 0.5 * t["rr1"] + 0.5 * (t["rr2"] or t["rr1"])
        out["tp1_open"] = sum(1 for t in self.trades if t["status"] == "tp1")
        out["open"] = sum(1 for t in self.trades if t["status"] in OPEN)
        return out

    def public(self, now_ms: int):
        keys = ("id", "symbol", "side", "kind", "created", "score", "entry", "entryType", "stop", "tp1", "tp2", "rr1", "rr2", "validUntil",
                "status", "result", "filledAt", "closedAt", "n", "title", "sent")
        return {"week": self.week(now_ms), "waiting": self.waiting, "stats": self.stats(),
                "trades": [{k: t.get(k) for k in keys} for t in self.trades[-40:][::-1]]}
