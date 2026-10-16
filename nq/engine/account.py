"""Journal du compte prop firm : trades saisis, P&L par journee de trading, etat du compte. Persistant (un fichier JSON local).

Etapes : l'EVALUATION, puis le COMPTE FINANCE (un nouveau compte de simulation : le solde repart du capital, la consistance disparait, le palier de
taille et les retraits s'appliquent). Le passage est une saisie « etape » ; seules les saisies posterieures comptent pour le compte courant.

Le journal est la SEULE source du solde : le terminal ne se connecte pas a ta plateforme. Il faut donc y saisir chaque trade (ou, pour un compte
deja entame, un « ajustement » de P&L par journee). Plus tard, un import automatique depuis ta plateforme pourra le remplir.

Ecriture atomique (fichier temporaire puis remplacement) : un arret brutal ne corrompt pas le journal. Un fichier illisible est mis de cote
(`.corrompu-AAAAMMJJ-HHMMSS`) sans jamais etre ecrase."""
import json
import math
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from . import clock, risk
from .instruments import INSTRUMENTS

VERSION = 1
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
T_MIN = 1_420_070_400_000                  # 2015-01-01 (ms UTC) : en dessous, c'est presque sûrement un horodatage en SECONDES
T_AHEAD = 36 * 3_600_000                   # on n'enregistre pas ce qui n'est pas encore arrivé (36 h de marge pour les fuseaux)
KINDS = ("trade", "adjust", "payout", "stage")


class AccountError(ValueError):
    """Saisie invalide (message en francais, affiche tel quel)."""


def _num(v, label: str, lo=None, hi=None) -> float:
    """Nombre FINI dans [lo ; hi] : ni booleen, ni NaN, ni infini (qui empoisonneraient le solde et le JSON), ni absurde."""
    if isinstance(v, bool) or v is None:
        raise AccountError(f"{label} : un nombre est attendu")
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):                     # OverflowError : entier de plus de 308 chiffres
        raise AccountError(f"{label} : un nombre est attendu") from None
    if not math.isfinite(x):
        raise AccountError(f"{label} : un nombre fini est attendu")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise AccountError(f"{label} : valeur hors limites ({lo if lo is not None else '−∞'} à {hi if hi is not None else '+∞'})")
    return x


def _day(v) -> str:
    """Jour de trading AAAA-MM-JJ (forme stricte : une autre écriture ne serait jamais comparée comme un jour)."""
    d = str(v) if v is not None else ""
    try:
        if not DAY_RE.match(d):
            raise ValueError
        date.fromisoformat(d)
    except ValueError:
        raise AccountError("jour invalide : écris AAAA-MM-JJ") from None
    return d


def _text(v, n: int) -> str:
    """Texte libre (note, setup) tronque a n caracteres, sans caractere impossible a ecrire en UTF-8 (un substitut isole ferait echouer la sauvegarde)."""
    return str(v if v is not None else "").encode("utf-8", "replace").decode("utf-8")[:n]


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_record(r) -> None:
    """Un enregistrement du journal lu sur le disque doit pouvoir etre somme sans planter : types STRICTS (une chaine « 12.5 » n'est pas un nombre),
    sinon le fichier est mis de cote."""
    if not isinstance(r, dict) or r.get("kind") not in KINDS:
        raise ValueError("saisie inconnue")
    if not isinstance(r["id"], int) or isinstance(r["id"], bool):
        raise ValueError("identifiant invalide")
    _day(r["day"])
    if not _isnum(r["t"]):
        raise ValueError("horodatage invalide")
    k = r["kind"]
    if k in ("trade", "adjust") and not _isnum(r["net"]):
        raise ValueError("montant invalide")
    if k == "trade":
        if not _isnum(r["fees"]):
            raise ValueError("frais invalides")
        for f in ("inst", "side"):
            if not isinstance(r.get(f), str):
                raise ValueError(f"{f} invalide")
        for f in ("qty", "entry", "exit", "gross", "pts"):
            if f in r and not _isnum(r[f]):
                raise ValueError(f"{f} invalide")
        if r.get("hold_s") is not None and not _isnum(r["hold_s"]):
            raise ValueError("duree invalide")
        if not isinstance(r.get("setup", ""), str):
            raise ValueError("setup invalide")
    if k == "payout" and not (_isnum(r["amount"]) and r["amount"] > 0):
        raise ValueError("retrait invalide")
    if k == "stage" and r.get("stage") != "funded":
        raise ValueError("etape inconnue")


class Account:
    def __init__(self, path, profile: risk.PropProfile | None = None, now_ms=None):
        self.path = Path(path)
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.lock = threading.RLock()
        self.records: list = []
        self.next_id = 1
        self.overrides: dict = {}
        self.profile = profile or risk.PropProfile()
        self._dll_day: str | None = None             # jour où la limite journalière a été touchée (elle verrouille la séance même si le latent remonte)
        self.profile_dropped: list = []              # réglages du fichier écartés au chargement parce qu'inutilisables (le reste est conservé)
        self._load()

    # ---------- persistance ----------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
            records = list(d.get("records", []))
            for r in records:
                _check_record(r)
            next_id = int(d.get("next_id", len(records) + 1))
            overrides = dict(d.get("profile", {}))
        except (OSError, ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError, RecursionError):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                self.path.rename(self.path.with_name(self.path.name + f".corrompu-{stamp}"))
            except OSError:
                pass
            self.records, self.next_id, self.overrides = [], 1, {}
            return
        self.records, self.next_id = records, max(next_id, max((r["id"] for r in records), default=0) + 1)
        base = self.profile.to_dict()
        errs = (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError)
        try:
            self.profile = risk.PropProfile.from_dict({**base, **overrides})
            self.overrides = overrides
            return
        except errs:
            pass
        kept, dropped = {}, []                                            # un seul réglage inutilisable ne doit pas faire perdre tous les autres
        for k, v in overrides.items():
            try:
                risk.PropProfile.from_dict({**base, **kept, k: v})
                kept[k] = v
            except errs:
                dropped.append(str(k))
        try:
            shutil.copy2(self.path, self.path.with_name(self.path.name + f".avant-reglages-{time.strftime('%Y%m%d-%H%M%S')}"))     # l'original reste lisible
        except OSError:
            pass
        self.profile, self.overrides, self.profile_dropped = risk.PropProfile.from_dict({**base, **kept}), kept, dropped

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"version": VERSION, "profile": self.overrides, "next_id": self.next_id, "records": self.records},
                                      ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except (OSError, UnicodeError) as e:
            raise AccountError(f"écriture du journal impossible ({getattr(e, 'strerror', None) or e}) : la saisie n'a pas été enregistrée") from None

    @contextmanager
    def _txn(self):
        """Verrou + retour arrière : si l'écriture du journal échoue, la mémoire redevient identique au disque (sinon une saisie « refusée » compterait
        quand même, et le nouvel essai la doublerait)."""
        with self.lock:
            before = (list(self.records), self.next_id, dict(self.overrides), self.profile, self._dll_day)
            try:
                yield
            except BaseException:
                self.records, self.next_id, self.overrides, self.profile, self._dll_day = before
                raise

    def _stamp(self, t) -> int:
        """Horodatage (ms UTC) d'une saisie : maintenant par défaut ; sinon un nombre fini, en millisecondes, ni avant 2015 ni dans le futur."""
        if t in (None, "", 0):
            return int(self.now_ms())
        try:
            return int(_num(t, "horodatage", T_MIN, self.now_ms() + T_AHEAD))
        except AccountError:
            raise AccountError("horodatage invalide : une date en millisecondes UTC, postérieure à 2015 et pas dans le futur") from None

    # ---------- saisies ----------
    def set_profile(self, changes: dict) -> risk.PropProfile:
        """Modifie des regles ou des limites personnelles (champs de PropProfile). Les champs inconnus et les valeurs inutilisables sont refuses."""
        if not isinstance(changes, dict):
            raise AccountError("réglages : un objet {champ: valeur} est attendu")
        with self._txn():
            known = set(risk.PropProfile().to_dict())
            bad = [k for k in changes if k not in known]
            if bad:
                raise AccountError(f"réglage inconnu : {', '.join(bad)}")
            merged = {**self.overrides, **changes}
            try:
                prof = risk.PropProfile.from_dict({**risk.PropProfile().to_dict(), **merged})
            except (TypeError, ValueError, AttributeError, KeyError, IndexError) as e:
                raise AccountError(f"valeur invalide : {e}") from None
            if prof.daily_loss_limit != self.profile.daily_loss_limit:       # enregistrer les règles sans toucher à la limite ne rouvre pas une séance verrouillée
                self._dll_day = None
            self.overrides, self.profile = merged, prof
            self.profile_dropped = []
            self._save()
            return prof

    def add_trade(self, inst: str, side: str, qty, entry, exit, t: int | None = None, fees=None, setup: str = "", note: str = "", hold_s=None) -> dict:
        inst = str(inst).upper()
        side = str(side).lower()
        if inst not in INSTRUMENTS:
            raise AccountError(f"instrument inconnu : {inst}")
        if side not in ("long", "short"):
            raise AccountError("sens inconnu : long ou short")
        qty = _num(qty, "quantité", 1, 10_000)
        entry, exit = _num(entry, "prix d'entrée", 0.0001, 1_000_000), _num(exit, "prix de sortie", 0.0001, 1_000_000)
        fees = None if fees in (None, "") else _num(fees, "frais", 0, 1_000_000)
        hold_s = None if hold_s in (None, "") else _num(hold_s, "durée du trade (s)", 0, 7 * 86_400)
        if qty != int(qty):
            raise AccountError("la quantité doit être un nombre entier de contrats")
        i = INSTRUMENTS[inst]
        entry, exit = i.snap(entry), i.snap(exit)
        sgn = 1 if side == "long" else -1
        gross = (exit - entry) * sgn * i.point_value * qty
        t = self._stamp(t)
        with self._txn():
            fee = self.profile.fee_rt.get(inst, 0.0) * qty if fees is None else fees
            rec = {"id": self.next_id, "kind": "trade", "t": t, "day": clock.trading_day(t), "inst": inst, "side": side, "qty": int(qty),
                   "entry": entry, "exit": exit, "gross": round(gross, 2), "fees": round(fee, 2), "net": round(gross - fee, 2),
                   "pts": round((exit - entry) * sgn, 4), "hold_s": hold_s, "setup": _text(setup, 60), "note": _text(note, 300)}
            self.next_id += 1
            self.records.append(rec)
            self._save()
            return rec

    def add_adjust(self, day: str, net, note: str = "") -> dict:
        """Ajoute (ou retire) un P&L net a une journee de trading : pour reprendre un compte deja entame."""
        day = _day(day)
        net = _num(net, "montant", -10_000_000, 10_000_000)
        with self._txn():
            rec = {"id": self.next_id, "kind": "adjust", "t": int(self.now_ms()), "day": day, "net": round(net, 2), "note": _text(note, 300)}
            self.next_id += 1
            self.records.append(rec)
            self._save()
            return rec

    def _current(self) -> tuple:
        """(etape, saisies du compte courant, jour du passage en compte finance ou None) : seules comptent les saisies faites apres le dernier marqueur
        d'etape ET datees de ce jour ou d'apres (une saisie datee d'avant concerne l'evaluation, qu'on rattrape apres coup : elle reste dans le journal
        mais n'entre pas dans le compte finance)."""
        idx = max((i for i, r in enumerate(self.records) if r["kind"] == "stage"), default=-1)
        if idx < 0:
            return "eval", self.records, None
        since = self.records[idx]["day"]
        return self.records[idx]["stage"], [r for r in self.records[idx + 1:] if r["day"] >= since], since

    def start_funded(self, t: int | None = None, note: str = "") -> dict:
        """Evaluation validee : on passe au compte finance (nouveau compte, solde de depart, plancher de depart). Annulable avec `undo`."""
        t = self._stamp(t)
        with self._txn():
            if self._current()[0] == "funded":
                raise AccountError("le compte est déjà un compte financé")
            rec = {"id": self.next_id, "kind": "stage", "stage": "funded", "t": t, "day": clock.trading_day(t), "note": _text(note, 300)}
            self.next_id += 1
            self.records.append(rec)
            self._save()
            return rec

    def add_payout(self, amount, t: int | None = None, note: str = "") -> dict:
        """Retrait DEMANDE (montant brut, avant le partage 90 / 10). Compte finance seulement. Le solde baisse et le plancher saute au niveau verrouille.

        Le journal reflete ce qui s'est passe chez Lucid, qui applique ses propres controles : on ne bloque donc que l'IMPOSSIBLE (montant hors
        du minimum / plafond d'une demande, trop de retraits, solde qui passerait sous le plancher, date avant le compte financé). Ce que le terminal
        juge seulement non conforme d'après ses hypotheses (jours gagnants, part de 50 %) revient en `warnings`, sans empecher la saisie."""
        amount = round(_num(amount, "montant du retrait", 0, 10_000_000), 2)
        if not amount > 0:
            raise AccountError("le montant du retrait doit être positif")
        t = self._stamp(t)
        with self._txn():
            stage, cur, since = self._current()
            if stage != "funded":
                raise AccountError("les retraits n'existent que sur le compte financé : passe d'abord en compte financé")
            day = clock.trading_day(t)
            if day < since:
                raise AccountError(f"ce retrait est daté du {day}, avant le passage en compte financé ({since})")
            p = self.profile
            if sum(1 for r in cur if r["kind"] == "payout") >= p.max_payouts:                       # tous les retraits du journal, quelle que soit leur date
                raise AccountError(f"{p.max_payouts} retraits déjà enregistrés : le compte passe en Live au choix de Lucid")
            if amount < p.payout_min - 1e-9 or amount > p.payout_cap + 1e-9:
                raise AccountError(f"un retrait se demande entre {p.payout_min:.0f} $ et {p.payout_cap:.0f} $ (règle du compte {p.start_balance:.0f} $)")
            after = self._is_after_session(t, day, cur)                                               # même critère que celui qui range ensuite le retrait dans un cycle
            st = self.snapshot(clock.next_day(day) if after else day, latch=False)
            po = st["payout"]
            floor_after = max(st["floor"], risk.locked_level(p) or st["floor"])
            if st["balance"] - amount <= floor_after + 1e-9:
                raise AccountError(f"après ce retrait le solde ({st['balance'] - amount:.0f} $) serait au plancher ({floor_after:.0f} $) ou dessous : montant impossible")
            warns = list(po["why"])
            if amount > po["cap"] + 1e-9:
                warns.append(f"au-dessus du plafond de {math.floor(po['cap']):.0f} $ calculé d'après ton journal (la moitié du profit du compte, {p.payout_cap:.0f} $ au plus)")
            rec = {"id": self.next_id, "kind": "payout", "t": t, "day": day, "amount": amount, "note": _text(note, 300)}
            self.next_id += 1
            self.records.append(rec)
            end = self.snapshot(clock.next_day(max(r["day"] for r in self._current()[1])), latch=False)     # avec les saisies POSTERIEURES déjà au journal
            if end["balance"] - end["floor"] <= 1e-9:
                raise AccountError(f"avec les saisies postérieures de ton journal, ce retrait mettrait le solde ({end['balance']:.0f} $) au plancher ({end['floor']:.0f} $) ou dessous")
            self._save()
            return dict(rec, warnings=warns)

    def undo(self) -> dict | None:
        """Annule la derniere saisie."""
        with self._txn():
            if not self.records:
                return None
            rec = self.records.pop()
            self._dll_day = None
            self._save()
            return rec

    def delete(self, rec_id: int) -> bool:
        with self._txn():
            tgt = next((r for r in self.records if r["id"] == rec_id), None)
            if tgt is not None and tgt["kind"] == "stage" and tgt is not self.records[-1]:
                raise AccountError("le passage en compte financé ne se supprime pas au milieu du journal : annule les saisies suivantes, puis « Annuler la dernière saisie »")
            n = len(self.records)
            self.records = [r for r in self.records if r["id"] != rec_id]
            if len(self.records) != n:
                self._dll_day = None
                self._save()
            return len(self.records) != n

    def reset(self) -> int:
        """Vide le journal (une copie est gardee a cote). Renvoie le nombre de saisies effacees."""
        with self._txn():
            n = len(self.records)
            if n and self.path.is_file():                                                      # COPIE (jamais un déplacement) : si l'écriture qui suit échoue, compte.json est intact
                try:
                    shutil.copy2(self.path, self.path.with_name(self.path.name + f".avant-reset-{time.strftime('%Y%m%d-%H%M%S')}"))
                except OSError as e:
                    raise AccountError(f"copie de sauvegarde impossible ({e.strerror or e}) : journal inchangé") from None
            self.records, self.next_id, self._dll_day = [], 1, None
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

    @staticmethod
    def _is_after_session(t: int, day: str, recs: list) -> bool:
        """Un retrait fait a l'instant `t` du jour `day` est-il saisi APRES les trades de ce jour (apres la fermeture forcee de 16 h 45 ET, ou apres
        le dernier trade du jour) ? Alors ces trades appartiennent au cycle qu'il clot ; sinon (ex. a l'ouverture) le jour ouvre le nouveau cycle."""
        if t >= clock.forced_flat(day):
            return True
        last = max((x["t"] for x in recs if x["kind"] == "trade" and x["day"] == day), default=None)
        return last is not None and t > last

    def snapshot(self, today: str, open_pnl: float = 0.0, latch: bool = True) -> dict:
        """Etat du compte courant pour la journee de trading `today` (voir risk.state). `latch=False` : lecture sans toucher au verrou de la limite
        journaliere (simulation d'un autre jour, par exemple pour valider un retrait)."""
        with self.lock:
            stage, recs, since = self._current()
            days = self.day_pnls(recs)
            closed = [(d, v) for d, v in days.items() if d < today]
            pays = sorted((r for r in recs if r["kind"] == "payout"), key=lambda r: (r["day"], r["t"], r["id"]))       # chronologique, pas dans l'ordre de saisie
            payouts = [(r["day"], r["amount"], self._is_after_session(r["t"], r["day"], recs)) for r in pays]
            st = risk.state(closed, days.get(today, 0.0), open_pnl, self.profile, stage, payouts, today)
            if st["dllHit"]:                                  # la limite journalière verrouille la séance : le latent qui remonte ensuite ne la rouvre pas
                if latch:
                    self._dll_day = today
            elif st["dll"] is not None and self._dll_day == today:
                st["dllHit"] = True
            st["today"] = today
            st["stageSince"] = since
            if stage == "funded":
                st["name"] = st["name"].replace("évaluation", "compte financé")
            st["days"] = [{"day": d, "pnl": v} for d, v in days.items()]
            st["records"] = [r for r in recs if r["day"] == today]
            st["payouts"] = [r for r in recs if r["kind"] == "payout"]
            st["profile"] = self.profile.to_dict()
            st["profileDropped"] = list(self.profile_dropped)
            st["toVerify"] = list(self.profile.to_verify)
            st["micro"] = self.micro()
            return st

    def micro(self) -> dict:
        """Part des gains venant de trades tenus MICRO_HOLD_SECONDS secondes ou moins, sur le compte COURANT. Lucid signale un compte au-dela de
        MICRO_PROFIT_SHARE (50 %). `shareMin` est un MINIMUM : les trades dont la duree n'a pas ete saisie comptent au denominateur mais jamais au numerateur."""
        tr = [r for r in self._current()[1] if r["kind"] == "trade"]
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
