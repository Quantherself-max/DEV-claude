"""Regles d'alerte : une confluence qualifiante (assez de sources, assez proche du prix) declenche
une alerte "nouvelle" une fois par cooldown, puis une alerte "approche" quand le prix s'en rapproche.
Au demarrage on enregistre l'existant et on envoie UN resume (pas une rafale)."""
import json
import time
from pathlib import Path


def fmt_price(p: float) -> str:
    s = f"{p:,.0f}" if p >= 1000 else f"{p:,.2f}"
    return s.replace(",", " ")


def zone_members(st: dict, z: dict):
    by_id = {lv["id"]: lv for lv in st["levels"]}
    return [by_id[i] for i in z["members"] if i in by_id]


def member_label(lv: dict) -> str:
    if lv["kind"] == "liq" and lv.get("pool"):
        return f"{lv['name']}{' AIMANT' if lv['pool']['magnet'] else ''} [{lv['pool']['score']}]"
    return lv["name"]


def format_alert(kind: str, st: dict, z: dict) -> str:
    arrow = {"above": "▲", "below": "▼", "in": "◆"}[z["side"]]
    where = {"above": "au-dessus du prix : plutot attiree vers le haut",
             "below": "sous le prix : plutot attiree vers le bas",
             "in": "le prix est dans la zone"}[z["side"]]
    head = "🔔 Nouvelle confluence" if kind == "new" else "📍 Le prix approche la confluence"
    sg = "+" if z["distPct"] > 0 else ""
    names = " + ".join(member_label(m) for m in sorted(zone_members(st, z), key=lambda m: m["price"]))
    return (f"{head} {arrow} {st['symbol']} {fmt_price(z['mid'])}\n"
            f"{sg}{z['distPct']:.2f} % du prix ({z['distAtr']:.1f} ATR {st['tf']})\n"
            f"{names}\n"
            f"Score {z['score']} · prix {fmt_price(st['price'])}\n"
            f"Regle « aimant » (hypothese non validee) : zone {where}.")


class AlertEngine:
    def __init__(self, cfg, notifier, now=time.time):
        self.cfg, self.notifier, self.now = cfg, notifier, now
        self.dir = Path(cfg.data_dir)
        self.state_file = self.dir / "alerts_state.json"
        self.log_file = self.dir / "alerts_log.jsonl"
        self.records: list[dict] = []
        self.sent_times: list[float] = []
        self.log: list[dict] = []
        self.started = False
        self._load()

    # --- persistance ---
    def _load(self):
        try:
            self.records = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            self.records = []

    def _save(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.records), encoding="utf-8")
        except OSError:
            pass

    def _log(self, entry: dict):
        self.log = (self.log + [entry])[-50:]
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- regles ---
    def qualifies(self, z: dict) -> bool:
        return z["score"] >= self.cfg.alert_min_score and z["distAtr"] <= self.cfg.alert_max_dist_atr

    def _match(self, symbol, z, tol, t):
        cd = self.cfg.alert_cooldown_hours * 3600
        for r in self.records:
            if (r["symbol"] == symbol and r["groups"] == z["groups"] and abs(r["mid"] - z["mid"]) <= 2 * tol
                    and t - r["t_new"] <= cd):
                return r
        return None

    def evaluate(self, st: dict, first: bool = False):
        """Renvoie [(kind, zone, texte)] a envoyer pour cet etat ; met a jour la memoire.
        first=True (premier cycle apres le demarrage) : on enregistre l'existant sans rien envoyer."""
        t = self.now()
        sym, out = st["symbol"], []
        qual = [z for z in st["zones"] if self.qualifies(z)]
        for z in sorted(qual, key=lambda z: z["distAtr"]):
            r = self._match(sym, z, st["tol"], t)
            if r is None:
                self.records.append({"symbol": sym, "groups": z["groups"], "mid": z["mid"], "t_new": t, "t_approach": 0.0})
                if not first:
                    out.append(("new", z, format_alert("new", st, z)))
            else:
                r["mid"] = z["mid"]                                   # la zone derive avec les VWAP
                cd = self.cfg.alert_cooldown_hours * 3600
                if z["distAtr"] <= self.cfg.alert_approach_atr and t - r["t_approach"] > cd and not first:
                    r["t_approach"] = t
                    out.append(("approach", z, format_alert("approach", st, z)))
        self.records = [r for r in self.records if t - r["t_new"] <= 24 * 3600]
        self._save()
        return out

    def dispatch(self, items, st):
        """Envoie avec limite horaire ; chaque tentative est journalisee."""
        t = self.now()
        self.sent_times = [x for x in self.sent_times if t - x < 3600]
        for kind, z, text in items:
            entry = {"t": t, "symbol": st["symbol"], "kind": kind, "mid": z["mid"], "text": text}
            if len(self.sent_times) >= self.cfg.alert_max_per_hour:
                entry.update(sent=False, detail="limite horaire atteinte")
            else:
                ok, detail = self.notifier.send(text)
                entry.update(sent=ok, detail=detail)
                if ok:
                    self.sent_times.append(t)
            self._log(entry)

    def run_cycle(self, states: dict):
        """Un passage complet : states = {symbole: etat au timeframe d'alerte}."""
        first = not self.started
        for st in states.values():
            self.dispatch(self.evaluate(st, first), st)
        if first:
            self.startup_summary(states)
            self.started = True

    def startup_summary(self, st_by_symbol: dict):
        lines = []
        for sym, st in st_by_symbol.items():
            for z in sorted([z for z in st["zones"] if self.qualifies(z)], key=lambda z: z["distAtr"])[:5]:
                arrow = {"above": "▲", "below": "▼", "in": "◆"}[z["side"]]
                names = " + ".join(member_label(m) for m in sorted(zone_members(st, z), key=lambda m: m["price"]))
                lines.append(f"{arrow} {sym} {fmt_price(z['mid'])} ({z['distPct']:+.2f} %) · {names}")
        text = "✅ Terminal demarre\n" + ("\n".join(lines) if lines else "Aucune confluence active pour l'instant.")
        ok, detail = self.notifier.send(text)
        self._log({"t": self.now(), "symbol": "*", "kind": "startup", "text": text, "sent": ok, "detail": detail})
