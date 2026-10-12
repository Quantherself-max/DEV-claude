"""Journal du compte prop firm : trades saisis, P&L par journee de trading, etat du compte. Persistant (un fichier JSON local).

Le journal est la SEULE source du solde : le terminal ne se connecte pas a ta plateforme. Il faut donc y saisir chaque trade (ou, pour un compte
deja entame, un « ajustement » de P&L par journee). Plus tard, un import automatique depuis ta plateforme pourra le remplir.

Ecriture atomique (fichier temporaire puis remplacement) : un arret brutal ne corrompt pas le journal. Un fichier illisible est mis de cote
(`.corrompu-AAAAMMJJ-HHMMSS`) sans jamais etre ecrase."""
import json
import os
import threading
import time
from pathlib import Path

from . import clock, risk
from .instruments import INSTRUMENTS

VERSION = 1


class AccountError(ValueError):
    """Saisie invalide (message en francais, affiche tel quel)."""


class Account:
    def __init__(self, path, profile: risk.PropProfile | None = None, now_ms=None):
        self.path = Path(path)
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.lock = threading.RLock()
        self.records: list = []
        self.next_id = 1
        self.overrides: dict = {}
        self.profile = profile or risk.PropProfile()
        self._load()

    # ---------- persistance ----------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = list(d.get("records", []))
            self.next_id = int(d.get("next_id", len(self.records) + 1))
            self.overrides = dict(d.get("profile", {}))
            self.profile = risk.PropProfile.from_dict({**self.profile.to_dict(), **self.overrides})
        except (OSError, ValueError, TypeError, AttributeError):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                self.path.rename(self.path.with_name(self.path.name + f".corrompu-{stamp}"))
            except OSError:
                pass
            self.records, self.next_id, self.overrides = [], 1, {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"version": VERSION, "profile": self.overrides, "next_id": self.next_id, "records": self.records},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---------- saisies ----------
    def set_profile(self, changes: dict) -> risk.PropProfile:
        """Modifie des regles ou des limites personnelles (champs de PropProfile). Les champs inconnus sont refuses."""
        with self.lock:
            known = set(risk.PropProfile().to_dict())
            bad = [k for k in changes if k not in known]
            if bad:
                raise AccountError(f"réglage inconnu : {', '.join(bad)}")
            merged = {**self.overrides, **changes}
            try:
                prof = risk.PropProfile.from_dict({**risk.PropProfile().to_dict(), **merged})
                for k in ("start_balance", "profit_target", "max_drawdown", "risk_per_trade", "daily_stop"):
                    if float(getattr(prof, k)) <= 0:
                        raise AccountError(f"{k} doit être positif")
            except (TypeError, ValueError) as e:
                raise AccountError(f"valeur invalide : {e}") from None
            self.overrides, self.profile = merged, prof
            self._save()
            return prof

    def add_trade(self, inst: str, side: str, qty, entry, exit, t: int | None = None, fees=None, setup: str = "", note: str = "") -> dict:
        inst = str(inst).upper()
        side = str(side).lower()
        if inst not in INSTRUMENTS:
            raise AccountError(f"instrument inconnu : {inst}")
        if side not in ("long", "short"):
            raise AccountError("sens inconnu : long ou short")
        try:
            qty, entry, exit = float(qty), float(entry), float(exit)
            fees = None if fees in (None, "") else float(fees)
        except (TypeError, ValueError):
            raise AccountError("quantité, prix ou frais invalides") from None
        if qty <= 0 or qty != int(qty):
            raise AccountError("la quantité doit être un nombre entier de contrats")
        if entry <= 0 or exit <= 0:
            raise AccountError("les prix doivent être positifs")
        i = INSTRUMENTS[inst]
        entry, exit = i.snap(entry), i.snap(exit)
        sgn = 1 if side == "long" else -1
        gross = (exit - entry) * sgn * i.point_value * qty
        fee = self.profile.fee_rt.get(inst, 0.0) * qty if fees is None else fees
        t = int(t) if t else self.now_ms()
        with self.lock:
            rec = {"id": self.next_id, "kind": "trade", "t": t, "day": clock.trading_day(t), "inst": inst, "side": side, "qty": int(qty),
                   "entry": entry, "exit": exit, "gross": round(gross, 2), "fees": round(fee, 2), "net": round(gross - fee, 2),
                   "pts": round((exit - entry) * sgn, 4), "setup": str(setup)[:60], "note": str(note)[:300]}
            self.next_id += 1
            self.records.append(rec)
            self._save()
            return rec

    def add_adjust(self, day: str, net, note: str = "") -> dict:
        """Ajoute (ou retire) un P&L net a une journee de trading : pour reprendre un compte deja entame."""
        try:
            net = float(net)
            clock.window(str(day), "rth")
        except (TypeError, ValueError):
            raise AccountError("jour (AAAA-MM-JJ) ou montant invalide") from None
        with self.lock:
            rec = {"id": self.next_id, "kind": "adjust", "t": self.now_ms(), "day": str(day), "net": round(net, 2), "note": str(note)[:300]}
            self.next_id += 1
            self.records.append(rec)
            self._save()
            return rec

    def undo(self) -> dict | None:
        """Annule la derniere saisie."""
        with self.lock:
            if not self.records:
                return None
            rec = self.records.pop()
            self._save()
            return rec

    def delete(self, rec_id: int) -> bool:
        with self.lock:
            n = len(self.records)
            self.records = [r for r in self.records if r["id"] != rec_id]
            if len(self.records) != n:
                self._save()
            return len(self.records) != n

    def reset(self) -> int:
        """Vide le journal (une copie est gardee a cote). Renvoie le nombre de saisies effacees."""
        with self.lock:
            n = len(self.records)
            if n and self.path.is_file():
                self.path.replace(self.path.with_name(self.path.name + f".avant-reset-{time.strftime('%Y%m%d-%H%M%S')}"))
            self.records, self.next_id = [], 1
            self._save()
            return n

    # ---------- lecture ----------
    def day_pnls(self) -> dict:
        out: dict = {}
        for r in self.records:
            out[r["day"]] = round(out.get(r["day"], 0.0) + r["net"], 2)
        return dict(sorted(out.items()))

    def snapshot(self, today: str, open_pnl: float = 0.0) -> dict:
        """Etat du compte pour la journee de trading `today` (voir risk.state)."""
        with self.lock:
            days = self.day_pnls()
            closed = [(d, v) for d, v in days.items() if d < today]
            st = risk.state(closed, days.get(today, 0.0), open_pnl, self.profile)
            st["today"] = today
            st["days"] = [{"day": d, "pnl": v} for d, v in days.items()]
            st["records"] = [r for r in self.records if r["day"] == today]
            st["profile"] = self.profile.to_dict()
            st["toVerify"] = list(self.profile.to_verify)
            return st

    def perf(self) -> dict:
        """Statistiques des trades saisis (gagnants, perdants, esperance), globales et par setup : sert a juger la strategie sur le reel."""
        tr = [r for r in self.records if r["kind"] == "trade"]

        def agg(rows):
            n = len(rows)
            if not n:
                return {"n": 0}
            w = [r["net"] for r in rows if r["net"] > 0]
            l = [r["net"] for r in rows if r["net"] <= 0]
            gw, gl = sum(w), -sum(l)
            return {"n": n, "winRate": len(w) / n, "avgWin": gw / len(w) if w else 0.0, "avgLoss": -gl / len(l) if l else 0.0,
                    "expectancy": sum(r["net"] for r in rows) / n, "net": sum(r["net"] for r in rows),
                    "profitFactor": (gw / gl) if gl > 0 else None, "fees": sum(r["fees"] for r in rows)}

        by: dict = {}
        for r in tr:
            by.setdefault(r.get("setup") or "(sans setup)", []).append(r)
        return {"all": agg(tr), "bySetup": {k: agg(v) for k, v in sorted(by.items())}}
