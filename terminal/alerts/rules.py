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


def fmt_pct(x, d=0):
    return "-" if x is None else f"{x * 100:.{d}f} %"


def prob_line(z: dict) -> str:
    p = z.get("prob")
    if not p:
        return "Probabilites : en cours de calcul (historique)."
    b, base = p.get("bounce"), p.get("base")
    parts = []
    if z["side"] != "in":
        parts.append(f"atteinte 24 h ≈ {fmt_pct(p['reach'].get('24'))}")
    if b and b.get("n"):
        parts.append(f"si touchee : rebond {fmt_pct(b['p'])} [n={b['n']}]" + (f" (hasard {fmt_pct(base['p'])})" if base and base.get("n") else ""))
    return "Probabilites (historique 1h) : " + " · ".join(parts) if parts else "Probabilites : pas assez d'historique."


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
            f"{prob_line(z)}\n"
            f"Regle « aimant » (hypothese non validee) : zone {where}.")


class AlertEngine:
    def __init__(self, cfg, notifier, now=time.time):
        self.cfg, self.notifier, self.now = cfg, notifier, now
        # historique separe pour les donnees simulees : il ne doit pas bloquer les vraies alertes (cooldown)
        self.dir = Path(cfg.data_dir) / ("simulated" if cfg.source == "simulated" else "")
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

    def sweep_alerts(self, st: dict, first: bool):
        """Grosse poche de liquidation balayee (journal du moteur OI) : une alerte par balayage."""
        if not getattr(self.cfg, "alert_sweep", False):
            return []
        sw = st.get("sweeps") or {}
        seen = self.__dict__.setdefault("_sweeps_seen", set(self._load_seen()))
        out = []
        for e in sw.get("recent", []):
            key = f"{st['symbol']}:{e['t']}:{e['side']}"
            if key in seen or e["frac"] < self.cfg.alert_sweep_frac:
                continue
            seen.add(key)
            if first:
                continue
            s = sw.get("stats") or {}
            hist = f"rebond {fmt_pct(s.get('p'))} [n={s.get('n')}]" if s.get("n") else "pas encore d'historique"
            arrow, who = ("▼", "longs") if e["side"] == "long" else ("▲", "shorts")
            d = (e["price"] / st["price"] - 1) * 100
            z = {"mid": e["price"], "side": "below" if e["side"] == "long" else "above", "distPct": d}
            text = (f"💥 Poche de liquidation balayee {arrow} {st['symbol']} {fmt_price(e['price'])} ({d:+.2f} %)\n"
                    f"{fmt_pct(e['frac'])} des liquidations de {who} estimees · prix {fmt_price(st['price'])}\n"
                    f"Apres un balayage (historique, 29 j) : {hist}. Estimation par l'OI (proxy).")
            out.append(("sweep", z, text))
        self._save_seen(seen)
        return out

    def _load_seen(self):
        try:
            return json.loads((self.dir / "sweeps_seen.json").read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_seen(self, seen):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "sweeps_seen.json").write_text(json.dumps(sorted(seen)[-500:]), encoding="utf-8")
        except OSError:
            pass

    def macro_alerts(self, macro: dict, first: bool = False):
        """Annonce majeure : une alerte environ 1 h avant (consensus + scenarios), puis un bilan quand le marche a reagi.
        Renvoie [(kind, z, texte)] ; le journal des alertes deja envoyees survit aux redemarrages."""
        if not macro or not getattr(self.cfg, "alert_macro", False):
            return []
        seen = self.__dict__.setdefault("_macro_seen", set(self._load_json("macro_seen.json")))
        now, out = self.now() * 1000, []
        for e in macro.get("upcoming", []):
            mins = (e["t"] - now) / 60000
            key = f"pre:{e['id']}"
            if e["impact"] == 3 and e["w"] >= 0.5 and 10 <= mins <= 65 and key not in seen:
                seen.add(key)
                ex = e.get("exp") or {}
                text = (f"⚠ Annonce majeure dans {int(mins)} min : {e['label']} ({e['country']})\n"
                        f"{ex.get('text') or 'Pas de consensus publie.'}\n"
                        f"{ex.get('scen_up', '')}\n{ex.get('scen_dn', '')}\n"
                        f"Fenetre de danger : spreads larges, meches rapides. Reduis le levier ou reste a plat.")
                out.append(("macro", {"mid": 0.0}, text.replace("\n\n", "\n")))
        for e in macro.get("past", []):
            key = f"post:{e['id']}"
            r = e.get("reaction")
            age = (now - e["t"]) / 60000
            if key in seen or not (e["impact"] == 3 and e["w"] >= 0.5) or not r or r.get("impulse") is None or age > 240:
                continue
            seen.add(key)
            if first:
                continue
            b = r.get("btc") or {}
            c = r.get("cross") or {}
            text = (f"📊 {e['label']} publie ({e['forecast'] or 'sans consensus'}) : surprise {r['impulseLabel']}\n"
                    f"Taux 10 ans {c['US10Y']:+.1f} pb, dollar {c['DXY']:+.2f} % en 15 min" if "US10Y" in c and "DXY" in c else
                    f"📊 {e['label']} publie ({e['forecast'] or 'sans consensus'}) : surprise {r['impulseLabel']}")
            if b.get("r15") is not None:
                text += f"\nBTC {b['r15']:+.2f} % en 15 min" + (f", {b['r60']:+.2f} % en 1 h" if b.get("r60") is not None else "")
            out.append(("macro", {"mid": 0.0}, text))
        self._save_json("macro_seen.json", sorted(seen)[-300:])
        return out

    def _load_json(self, name):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_json(self, name, data):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / name).write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def run_cycle(self, states: dict, macro: dict | None = None):
        """Un passage complet : states = {symbole: etat au timeframe d'alerte} ; macro = analyse macro (optionnelle)."""
        first = not self.started
        for st in states.values():
            zones = self.evaluate(st, first)
            if not getattr(self.cfg, "alert_zones", True):
                zones = []                                    # on garde la memoire des zones mais on n'envoie rien
            self.dispatch(zones + self.sweep_alerts(st, first), st)
        if macro is not None and states:
            self.dispatch(self.macro_alerts(macro, first), next(iter(states.values())))
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
        if not getattr(self.cfg, "alert_zones", True):
            lines = []
        text = "✅ Terminal demarre\n" + ("\n".join(lines) if lines else ("Les alertes de zones sont coupees : tu ne recevras que les idees de trade." if not getattr(self.cfg, "alert_zones", True) else "Aucune confluence active pour l'instant."))
        ok, detail = self.notifier.send(text)
        self._log({"t": self.now(), "symbol": "*", "kind": "startup", "text": text, "sent": ok, "detail": detail})
