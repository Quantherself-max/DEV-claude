"""Journal du compte prop firm : trades saisis, P&L par journee de trading, etat du compte. Persistant (un fichier JSON local).

Etapes : l'EVALUATION, puis le COMPTE FINANCE (un nouveau compte de simulation : le solde repart du capital, la consistance disparait, le palier de
taille et les retraits s'appliquent). Le passage est une saisie « etape » ; seules les saisies posterieures comptent pour le compte courant.

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

    def add_trade(self, inst: str, side: str, qty, entry, exit, t: int | None = None, fees=None, setup: str = "", note: str = "", hold_s=None) -> dict:
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
        try:
            hold_s = None if hold_s in (None, "") else float(hold_s)
        except (TypeError, ValueError):
            raise AccountError("la durée du trade doit être un nombre de secondes") from None
        if hold_s is not None and hold_s < 0:
            raise AccountError("la durée du trade ne peut pas être négative")
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
                   "pts": round((exit - entry) * sgn, 4), "hold_s": hold_s, "setup": str(setup)[:60], "note": str(note)[:300]}
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

    def _current(self) -> tuple:
        """(etape, saisies du compte courant, jour du passage en compte finance ou None) : seules les saisies apres le dernier marqueur d'etape comptent."""
        idx = max((i for i, r in enumerate(self.records) if r["kind"] == "stage"), default=-1)
        if idx < 0:
            return "eval", self.records, None
        return self.records[idx]["stage"], self.records[idx + 1:], self.records[idx]["day"]

    def start_funded(self, t: int | None = None, note: str = "") -> dict:
        """Evaluation validee : on passe au compte finance (nouveau compte, solde de depart, plancher de depart). Annulable avec `undo`."""
        with self.lock:
            if self._current()[0] == "funded":
                raise AccountError("le compte est déjà un compte financé")
            t = int(t) if t else self.now_ms()
            rec = {"id": self.next_id, "kind": "stage", "stage": "funded", "t": t, "day": clock.trading_day(t), "note": str(note)[:300]}
            self.next_id += 1
            self.records.append(rec)
            self._save()
            return rec

    def add_payout(self, amount, t: int | None = None, note: str = "") -> dict:
        """Retrait DEMANDE (montant brut, avant le partage 90 / 10). Compte finance seulement. Le solde baisse et le plancher saute au niveau verrouille."""
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise AccountError("montant du retrait invalide") from None
        if not amount > 0:
            raise AccountError("le montant du retrait doit être positif")
        with self.lock:
            if self._current()[0] != "funded":
                raise AccountError("les retraits n'existent que sur le compte financé : passe d'abord en compte financé")
            t = int(t) if t else self.now_ms()
            rec = {"id": self.next_id, "kind": "payout", "t": t, "day": clock.trading_day(t), "amount": round(amount, 2), "note": str(note)[:300]}
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
    def day_pnls(self, recs: list | None = None) -> dict:
        """P&L net par journee de trading (trades et ajustements ; ni les retraits ni les marqueurs d'etape). Par defaut : le compte courant."""
        out: dict = {}
        for r in (self._current()[1] if recs is None else recs):
            if r["kind"] in ("trade", "adjust"):
                out[r["day"]] = round(out.get(r["day"], 0.0) + r["net"], 2)
        return dict(sorted(out.items()))

    def snapshot(self, today: str, open_pnl: float = 0.0) -> dict:
        """Etat du compte courant pour la journee de trading `today` (voir risk.state)."""
        with self.lock:
            stage, recs, since = self._current()
            days = self.day_pnls(recs)
            closed = [(d, v) for d, v in days.items() if d < today]
            payouts = [(r["day"], r["amount"]) for r in recs if r["kind"] == "payout"]
            st = risk.state(closed, days.get(today, 0.0), open_pnl, self.profile, stage, payouts, today)
            st["today"] = today
            st["stageSince"] = since
            if stage == "funded":
                st["name"] = st["name"].replace("évaluation", "compte financé")
            st["days"] = [{"day": d, "pnl": v} for d, v in days.items()]
            st["records"] = [r for r in recs if r["day"] == today]
            st["payouts"] = [r for r in recs if r["kind"] == "payout"]
            st["profile"] = self.profile.to_dict()
            st["toVerify"] = list(self.profile.to_verify)
            st["micro"] = self.micro()
            return st

    def micro(self) -> dict:
        """Part des gains venant de trades tenus MICRO_HOLD_SECONDS secondes ou moins. Lucid signale un compte au-dela de MICRO_PROFIT_SHARE (50 %).
        `shareMin` est un MINIMUM : les trades dont la duree n'a pas ete saisie comptent au denominateur mais jamais au numerateur."""
        tr = [r for r in self.records if r["kind"] == "trade"]
        wins = sum(r["net"] for r in tr if r["net"] > 0)
        known = [r for r in tr if r.get("hold_s") is not None]
        short = sum(r["net"] for r in known if r["net"] > 0 and r["hold_s"] <= risk.MICRO_HOLD_SECONDS)
        return {"trades": len(tr), "known": len(known), "unknown": len(tr) - len(known), "shortWins": round(short, 2), "wins": round(wins, 2),
                "shareMin": (short / wins) if wins > 0 else None, "limit": risk.MICRO_PROFIT_SHARE, "seconds": risk.MICRO_HOLD_SECONDS}

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
