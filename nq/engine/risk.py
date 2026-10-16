"""Regles d'un compte prop firm (Lucid 25K par defaut) et dimensionnement des positions. Module PUR.

Ce module ne decide PAS d'un trade : il dit combien il reste de marge avant le plancher du compte, ce que la regle de consistance autorise, et
combien de contrats prendre pour un risque donne. Toutes les regles sont dans `PropProfile`, modifiables (Reglages / fichier JSON) : les
regles des prop firms changent, et les sources publiques se contredisent sur certains points (marques « a verifier »).

Regles LucidFlex 25K retenues par defaut (recoupees sur plusieurs sources publiques de 2026 ; CONFIRME-LES sur le site de Lucid avant d'acheter) :
  - capital de depart 25 000 $, cible de profit 1 250 $, perte maximale 1 000 $ ;
  - perte maximale « trailing » sur le SOLDE DE FIN DE JOURNEE (EOD) : le plancher monte avec le meilleur solde de fin de journee
    (plancher = meilleur solde EOD - 1 000 $) et s'arrete a capital + 100 $ (25 100 $) ; il ne descend jamais ;
  - limite de perte journaliere : une OPTION choisie au paiement (moins chere si elle est activee), non modifiable ensuite, « souple » (on est
    bloque jusqu'a la seance suivante, le compte survit). Ce profil la laisse desactivee ; au plus 2 minis ou 20 micros (un mini = 10 micros,
    l'ensemble compte : hypothese prudente, non confirmee) ;
  - consistance en evaluation : le meilleur jour ne doit pas depasser 50 % du profit total ;
  - jours de trading minimum : sources contradictoires (0 ou 2) -> a verifier ;
  - positions a plat avant 16 h 45 ET (fermees d'office) ; micro-scalping : compte signale si plus de 50 % des gains viennent de trades
    tenus 5 secondes ou moins (voir `MICRO_*` plus bas) ;
  - COMPTE FINANCE (apres validation) : plus de consistance ; palier de taille (1 mini / 10 micros sous 1 000 $ de profit, puis 2 / 20) mis a jour
    en fin de seance ; retraits : 5 jours a >= 100 $ de profit par cycle, profit positif, minimum 500 $, au plus 50 % du profit et 1 000 $, 90 / 10,
    5 retraits au plus ; a la DEMANDE le plancher saute a 25 100 $ et le solde baisse du montant retire."""
import math
from dataclasses import asdict, dataclass, field, fields, replace

from .instruments import INSTRUMENTS

MICRO_OF_ROOT = {"NQ": "MNQ", "ES": "MES"}           # micro correspondant a chaque mini
MICRO_HOLD_SECONDS = 5                               # Lucid : un trade tenu 5 secondes ou moins est « micro »
MICRO_PROFIT_SHARE = 0.5                             # ... et le compte est signale si plus de 50 % des gains en viennent


@dataclass
class PropProfile:
    name: str = "LucidFlex 25K · évaluation"
    start_balance: float = 25_000.0
    profit_target: float = 1_250.0
    max_drawdown: float = 1_000.0
    dd_mode: str = "eod_trailing"           # eod_trailing = plancher qui suit le meilleur solde de fin de journee | static = plancher fixe
    lock_offset: float = 100.0              # le plancher ne monte plus au-dela de capital + lock_offset (None = jamais verrouille)
    max_minis: int = 2
    max_micros: int = 20
    consistency_pct: float | None = 50.0    # meilleur jour <= X % du profit total (evaluation) ; None = pas de regle (compte finance)
    daily_loss_limit: float | None = None   # option du paiement, « souple » : bloque jusqu'a la seance suivante sans faire echouer le compte ; None = desactivee
    min_trading_days: int | None = None     # aucun minimum officiel trouve (2 jours en pratique a cause de la consistance 50 %)
    # --- compte FINANCE : retraits LucidFlex 25K (article « LucidFlex Payouts ») ; plafonds qui ne montent PAS avec les retraits suivants ---
    payout_days: int = 5                    # jours « gagnants » requis par cycle de retrait
    payout_day_profit: float = 100.0        # profit net minimal d'un jour gagnant (25K)
    payout_min: float = 500.0               # montant minimal d'une demande
    payout_cap: float = 1_000.0             # plafond d'une demande (25K)
    payout_cap_pct: float = 0.5             # ... et au plus cette part du profit (le texte de l'article dit « solde », son tableau « profit » : on retient le profit)
    payout_split: float = 0.9               # part du trader (90 / 10)
    max_payouts: int = 5                    # puis passage en Live, au choix de Lucid
    scaling: tuple = ((0.0, 1, 10), (1_000.0, 2, 20))   # (profit simule minimal, minis, micros) du compte finance ; mis a jour en fin de seance
    # --- discipline personnelle (PAS des regles de Lucid) : valeurs de depart, a regler ensemble ---
    risk_per_trade: float = 100.0           # risque maximal par trade, en dollars
    daily_stop: float = 300.0               # perte de la journee a partir de laquelle on s'arrete
    # frais ALLER-RETOUR par contrat, en dollars. NQ / MNQ : table du centre d'aide de Lucid (1,75 $ et 0,50 $ PAR COTE, soit 3,50 $ et 1,00 $ l'aller-retour).
    # ES / MES : meme valeur par defaut, non verifiee. Frais de bourse / NFA eventuels non inclus : a remplacer par tes frais reels si tu les connais.
    fee_rt: dict = field(default_factory=lambda: {"NQ": 3.50, "MNQ": 1.00, "ES": 3.50, "MES": 1.00})
    to_verify: tuple = ("jours de trading minimum (0 ou 2 selon les sources)",
                        "frais : commissions Lucid NQ 1,75 $ / MNQ 0,50 $ par côté (confirme à l'achat) ; frais de bourse éventuels non inclus",
                        "limite de perte journalière : option du paiement, montant à lire sur la page d'achat",
                        "retraits : le jour à 100 $ est-il net de frais et compté par séance ? le « 50 % » porte-t-il sur le profit ou sur le solde ?",
                        "le compte financé repart-il de 25 000 $ avec un plancher à 24 000 $ ?")

    @classmethod
    def from_dict(cls, d: dict) -> "PropProfile":
        """Profil par defaut dont on remplace les champs presents dans `d` (les champs inconnus sont ignores). Leve ValueError si une valeur est
        inutilisable (nombre attendu, palier mal forme, ...) : ce profil sert de base a tous les calculs, il doit etre sain une fois construit."""
        base = cls()
        optional = {"consistency_pct", "daily_loss_limit", "min_trading_days", "lock_offset"}      # None est une valeur valide
        for k in {f.name for f in fields(cls)}:
            if k in (d or {}) and (d[k] is not None or k in optional):
                setattr(base, k, d[k])
        for k in _FLOAT_FIELDS:
            v = getattr(base, k)
            setattr(base, k, None if v is None and k in optional else _number(v, k))
        for k in _INT_FIELDS:
            v = getattr(base, k)
            setattr(base, k, None if v is None and k in optional else int(_number(v, k)))
        if base.daily_loss_limit == 0:                         # 0 = « pas de limite » (champ vide), pas une limite a 0 $ qui verrouillerait chaque seance
            base.daily_loss_limit = None
        base.to_verify = tuple(base.to_verify)
        try:
            base.scaling = tuple(sorted((_number(t[0], "scaling"), int(_number(t[1], "scaling")), int(_number(t[2], "scaling"))) for t in base.scaling))
        except (IndexError, TypeError) as e:
            raise ValueError("scaling : une liste de paliers [profit, minis, micros] est attendue") from e
        try:
            base.fee_rt = {**PropProfile().fee_rt, **{str(k).upper(): _number(v, "fee_rt") for k, v in (base.fee_rt or {}).items()}}
        except AttributeError as e:
            raise ValueError("fee_rt : un dictionnaire {contrat: frais} est attendu") from e
        validate_profile(base)
        return base

    def to_dict(self) -> dict:
        d = asdict(self)
        d["to_verify"] = list(self.to_verify)
        d["scaling"] = [list(t) for t in self.scaling]
        return d


_FLOAT_FIELDS = ("start_balance", "profit_target", "max_drawdown", "lock_offset", "consistency_pct", "daily_loss_limit", "payout_day_profit", "payout_min",
                 "payout_cap", "payout_cap_pct", "payout_split", "risk_per_trade", "daily_stop")
_INT_FIELDS = ("max_minis", "max_micros", "min_trading_days", "payout_days", "max_payouts")


def _number(v, name: str) -> float:
    """Nombre FINI (ni booleen, ni NaN, ni infini) ou ValueError : une valeur non finie empoisonnerait tous les soldes et le JSON envoye a l'interface."""
    if isinstance(v, bool) or v is None:
        raise ValueError(f"{name} : un nombre est attendu")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} : un nombre est attendu") from None
    if not math.isfinite(x):
        raise ValueError(f"{name} : un nombre fini est attendu")
    return x


def validate_profile(p: "PropProfile") -> None:
    """Refuse (ValueError, message en francais) un profil qui ferait planter ou fausser les calculs : plafonds nuls, paliers vides, parts hors de ]0 ; 1]."""
    if p.dd_mode not in ("eod_trailing", "static"):
        raise ValueError("dd_mode : eod_trailing ou static")
    for k in ("start_balance", "profit_target", "max_drawdown", "risk_per_trade", "daily_stop", "payout_min", "payout_cap"):
        if getattr(p, k) <= 0:
            raise ValueError(f"{k} doit être positif")
    if p.payout_cap < p.payout_min:
        raise ValueError("payout_cap doit être au moins égal à payout_min")
    if p.payout_day_profit < 0 or (p.lock_offset is not None and p.lock_offset < 0):
        raise ValueError("payout_day_profit et lock_offset ne peuvent pas être négatifs")
    for k in ("payout_cap_pct", "payout_split"):
        if not 0 < getattr(p, k) <= 1:
            raise ValueError(f"{k} doit être compris entre 0 (exclu) et 1")
    if p.consistency_pct is not None and not 0 < p.consistency_pct <= 100:
        raise ValueError("consistency_pct doit être compris entre 0 (exclu) et 100")
    if p.daily_loss_limit is not None and p.daily_loss_limit <= 0:
        raise ValueError("daily_loss_limit doit être positif (laisse vide pour aucune limite)")
    for k in ("max_minis", "max_micros", "payout_days", "max_payouts"):
        if getattr(p, k) < 1:
            raise ValueError(f"{k} doit être au moins 1")
    if p.min_trading_days is not None and p.min_trading_days < 0:
        raise ValueError("min_trading_days ne peut pas être négatif")
    if not p.scaling:
        raise ValueError("scaling : au moins un palier est nécessaire")
    if len({t[0] for t in p.scaling}) != len(p.scaling) or any(t[1] < 1 or t[2] < 1 for t in p.scaling):
        raise ValueError("scaling : seuils de profit distincts et au moins 1 mini / 1 micro par palier")
    if any(v < 0 for v in p.fee_rt.values()):
        raise ValueError("fee_rt : des frais négatifs ne sont pas acceptés")


def locked_level(p: PropProfile):
    """Niveau auquel le plancher se verrouille (capital + lock_offset), ou None."""
    return p.start_balance + p.lock_offset if p.dd_mode == "eod_trailing" and p.lock_offset is not None else None


def ledger(days: list, payouts: list, p: PropProfile) -> dict:
    """Solde et plancher APRES les journees `days` [(jour, P&L net)] et les retraits `payouts` [(jour, montant demande)].

    eod_trailing : plancher = max(plancher precedent, min(meilleur solde de fin de journee - perte max, capital + lock_offset)). Il ne baisse jamais.
    Un retrait est applique au DEBUT de son jour (avant le P&L de ce jour) : le solde baisse du montant demande et le plancher saute au niveau
    verrouille (l'article Lucid : « once you request a payout, your MLL automatically adjusts to the Locked MLL Balance »)."""
    pnl_by_day: dict = {}
    for d, x in days:
        pnl_by_day[d] = pnl_by_day.get(d, 0.0) + x
    pay_by_day: dict = {}
    for d, a in payouts:
        pay_by_day[d] = pay_by_day.get(d, 0.0) + a
    lock = locked_level(p)
    bal = peak = p.start_balance
    floor = p.start_balance - p.max_drawdown
    paid = 0.0
    for d in sorted(set(pnl_by_day) | set(pay_by_day)):
        if d in pay_by_day:
            bal = round(bal - pay_by_day[d], 2)
            paid += pay_by_day[d]
            if lock is not None:
                floor = max(floor, lock)
        if d in pnl_by_day:
            bal = round(bal + pnl_by_day[d], 2)                # au centime : sans cela 999,9999999999964 $ de profit n'atteint pas le palier de 1 000 $
            if p.dd_mode == "eod_trailing":
                peak = max(peak, bal)
                nf = peak - p.max_drawdown
                if lock is not None:
                    nf = min(nf, lock)
                floor = max(floor, nf)
    locked = lock is not None and floor >= lock - 1e-9
    return {"floor": floor, "peak": peak, "balance": bal, "locked": locked, "paid": paid}


def trailing_floor(day_pnls: list, p: PropProfile) -> dict:
    """Plancher du compte APRES les journees `day_pnls` (P&L net de chaque journee, du plus ancien au plus recent), sans retrait."""
    return ledger([(f"{i:06d}", x) for i, x in enumerate(day_pnls)], [], p)


def scaling_caps(profit: float, p: PropProfile) -> tuple:
    """(minis, micros, prochain seuil de profit ou None) du compte finance pour ce profit simule (mesure en FIN de seance, jamais en cours de seance)."""
    cur = p.scaling[0]
    for t in p.scaling:
        if profit >= t[0] - 1e-6:
            cur = t
    nxt = next((t[0] for t in p.scaling if t[0] > max(profit, cur[0]) + 1e-6), None)      # un profit negatif reste dans le 1er palier : le prochain est le 2e
    return int(cur[1]), int(cur[2]), nxt


def payout_status(cycle_days: list, balance: float, floor: float, done: int, p: PropProfile, live_balance: float | None = None,
                  equity: float | None = None) -> dict:
    """Ou en est le prochain retrait (compte finance). cycle_days : [(jour, P&L net)] des journees TERMINEES du cycle en cours ; balance : solde a la
    derniere cloture ; floor : plancher a cette date ; done : retraits deja faits ; live_balance / equity : solde et equity du moment (la marge APRES
    retrait se calcule dessus : si la journee est deja negative, le retrait ne doit pas faire passer sous le plancher).

    Eligibilite : au moins `payout_days` jours a >= `payout_day_profit` dans le cycle, profit du cycle positif, et un plafond (min(part du profit,
    plafond)) au moins egal au minimum d'une demande. Le plafond ne monte pas avec le nombre de retraits.
    HYPOTHESES (l'article ne les tranche pas) : un jour compte net de frais et par seance ; le « 50 % » porte sur le profit du compte (solde - capital)."""
    days_ok = [(d, x) for d, x in cycle_days if x >= p.payout_day_profit - 1e-9]
    cycle_profit = sum(x for _, x in cycle_days)
    profit_basis = max(0.0, balance - p.start_balance)
    cap = math.floor(min(p.payout_cap_pct * profit_basis, p.payout_cap) * 100 + 1e-6) / 100          # jamais arrondi vers le haut : on n'affiche pas un maximum que la règle refuse
    lock = locked_level(p)
    floor_after = max(floor, lock) if lock is not None else floor
    live = balance if live_balance is None else live_balance
    eq = live if equity is None else equity
    room = eq - floor_after                                   # marge disponible avant le plancher, au moment de la demande
    why = []
    if len(days_ok) < p.payout_days:
        why.append(f"il manque {p.payout_days - len(days_ok)} jour(s) à ≥ {p.payout_day_profit:.0f} $ dans ce cycle")
    if cycle_profit <= 0:
        why.append("le profit du cycle n'est pas positif")
    if cap < p.payout_min - 1e-9:
        why.append(f"le plafond actuel ({math.floor(cap):.0f} $) est sous le minimum ({p.payout_min:.0f} $) : il faut au moins "
                   f"{math.ceil(p.payout_min / p.payout_cap_pct):.0f} $ de profit sur le compte")
    elif room - p.payout_min <= 0:
        why.append(f"la marge actuelle ({max(0.0, room):.0f} $) ne permet pas un retrait minimal ({p.payout_min:.0f} $) sans toucher le plancher")
    if done >= p.max_payouts:
        why.append(f"{p.max_payouts} retraits déjà faits : passage en Live au choix de Lucid")
    eligible = not why
    req = float(max(p.payout_min, math.floor(min(cap, room - 1)))) if eligible else 0.0       # en dollars entiers, jamais au-dessus du plafond, au moins 1 $ au-dessus du plancher

    def after(amount):
        return {"amount": amount, "net": math.floor(amount * p.payout_split * 100 + 1e-6) / 100, "balance": round(live - amount, 2), "floor": floor_after, "cushion": round(eq - amount - floor_after, 2)}
    return {"eligible": eligible, "why": why, "daysOk": [d for d, _ in days_ok], "daysNeeded": p.payout_days, "dayProfit": p.payout_day_profit,
            "cycleProfit": cycle_profit, "profitBasis": profit_basis, "cap": cap, "minRequest": p.payout_min, "done": done, "left": max(0, p.max_payouts - done),
            "max": after(req) if eligible else None, "min": after(p.payout_min) if eligible or cap >= p.payout_min else None,
            "profitForMin": math.ceil(p.payout_min / p.payout_cap_pct)}


def consistency(day_pnls: list, p: PropProfile) -> dict:
    """Regle de consistance : meilleur jour / profit total. `needed` = profit total a atteindre pour VALIDER : le plus grand de la cible et
    du meilleur jour divise par le pourcentage autorise (ex. meilleur jour 700 $ a 50 % -> il faut 1 400 $ de profit, meme si la cible est 1 250 $)."""
    total = sum(day_pnls)
    best = max(day_pnls) if day_pnls else 0.0
    c = (p.consistency_pct or 0.0) / 100.0
    if not c:
        return {"rule": False, "total": total, "best": best, "ratio": None, "ok": True, "needed": p.profit_target, "dayCap": None}
    ratio = best / total if total > 0 and best > 0 else None
    ok = total > 0 and (best <= 0 or best <= c * total + 1e-9)
    return {"rule": True, "total": total, "best": best, "ratio": ratio, "ok": ok,
            "needed": max(p.profit_target, best / c if best > 0 else 0.0), "pct": p.consistency_pct,
            # gain maximal d'une journee qui ne depasse pas c du total : g <= c (T + g)  ->  g <= T c / (1 - c)
            "dayCap": max(0.0, total) * c / (1.0 - c) if c < 1 else None}


def state(closed_days: list, today_pnl: float, open_pnl: float, p: PropProfile, stage: str = "eval", payouts: list | None = None,
          today: str | None = None) -> dict:
    """Etat du compte. closed_days : [(jour, P&L net)] des journees TERMINEES ; today_pnl : P&L realise du jour (net de frais) ; open_pnl : latent ;
    stage : « eval » (evaluation) ou « funded » (compte finance) ; payouts : [(jour, montant demande)] ; today : jour de trading en cours.

    Le plancher ne change qu'en fin de journee (EOD) : pendant la seance il reste celui de la veille, et la marge (`buffer`) est mesuree sur
    l'EQUITY (solde + latent), prudemment : la limite est consideree touchee des que l'equity l'atteint. La limite de perte journaliere (option)
    est « souple » : elle verrouille la fin de seance (`dllHit`) sans faire echouer le compte."""
    pays = [(x[0], x[1], bool(x[2]) if len(x) > 2 else False) for x in (payouts or [])]      # (jour, montant, saisi apres les trades de ce jour)
    merged: dict = {}
    for d, x in closed_days:                                  # un jour present plusieurs fois compte pour UN jour (comme dans ledger)
        merged[d] = merged.get(d, 0.0) + x
    closed_days = sorted(merged.items())
    funded = stage == "funded"
    before = [(d, a) for d, a, _ in pays if today is None or d < today]
    pay_today = sum(a for d, a, _ in pays if today is not None and d == today)
    led = ledger(closed_days, before, p)
    bal_closed, floor = round(led["balance"] - pay_today, 2), led["floor"]
    lock = locked_level(p)
    if pay_today and lock is not None:
        floor = max(floor, lock)
    balance = round(bal_closed + today_pnl, 2)
    equity = balance + open_pnl
    buffer = equity - floor
    profit = balance - p.start_balance
    pnls = [x[1] for x in closed_days]
    all_days = pnls + ([today_pnl] if today_pnl else [])
    pc = replace(p, consistency_pct=None) if funded else p                    # plus de consistance sur le compte finance
    cons = consistency(all_days, pc)
    cons["todayCap"] = consistency(pnls, pc)["dayCap"]                        # gain maximal d'AUJOURD'HUI sans depasser la part autorisee du total (jours termines)
    traded = len([x for x in closed_days if x[1] != 0]) + (1 if today_pnl else 0)
    target_hit = profit >= p.profit_target - 1e-6
    enough_days = p.min_trading_days is None or traded >= p.min_trading_days
    breached = equity <= floor + 1e-9
    passed = (not funded) and (not breached) and target_hit and cons["ok"] and enough_days
    frac = buffer / p.max_drawdown if p.max_drawdown else 1.0
    if breached:
        status = "breached"
    elif passed:
        status = "passed"
    elif frac < 0.25:
        status = "danger"
    elif frac < 0.5:
        status = "warn"
    else:
        status = "ok"
    day_now = today_pnl + open_pnl
    best_day = max(closed_days, key=lambda x: x[1]) if closed_days else None
    # taille autorisee : evaluation = plafond plein ; compte finance = palier selon le profit a la derniere cloture (mis a jour en fin de seance)
    if funded:
        minis, micros, nxt = scaling_caps(led["balance"] - p.start_balance, p)         # palier mesure AVANT un retrait du jour : il ne bouge qu'en fin de seance
    else:
        minis, micros, nxt = p.max_minis, p.max_micros, None
    out = {
        "name": p.name, "stage": stage, "status": status, "start": p.start_balance, "balance": balance, "equity": equity, "floor": floor,
        "buffer": buffer, "bufferFrac": frac, "locked": led["locked"] or (pay_today > 0 and lock is not None), "peakEod": led["peak"],
        "profit": profit, "target": p.profit_target, "targetLeft": max(0.0, p.profit_target - profit),
        "progress": max(0.0, min(1.0, profit / p.profit_target)) if p.profit_target else 0.0,
        "targetHit": target_hit, "consistency": cons, "bestDay": best_day[1] if best_day else 0.0, "bestDayDate": best_day[0] if best_day else None,
        "daysTraded": traded, "minDays": p.min_trading_days, "enoughDays": enough_days,
        "todayPnl": today_pnl, "openPnl": open_pnl, "dayPnl": day_now,
        "dailyStop": p.daily_stop, "dailyStopLeft": max(0.0, p.daily_stop + day_now) if day_now < 0 else p.daily_stop,
        "dailyStopHit": day_now <= -p.daily_stop,
        "dll": p.daily_loss_limit, "dllHit": p.daily_loss_limit is not None and day_now <= -p.daily_loss_limit + 1e-9,
        "maxMinis": p.max_minis, "maxMicros": p.max_micros, "caps": {"minis": minis, "micros": micros, "next": nxt}, "riskPerTrade": p.risk_per_trade,
        "passed": passed, "breached": breached, "paid": led["paid"] + pay_today, "payout": None,
    }
    if funded:
        dated = [x for x in pays if today is None or x[0] <= today]
        last = max(enumerate(dated), key=lambda ix: (ix[1][0], ix[0]))[1] if dated else None        # dernier retrait : le plus tardif, a jour egal le dernier saisi
        # un retrait a l'ouverture de son jour : les trades de ce jour comptent dans le NOUVEAU cycle ; saisi apres ces trades : ils restent dans l'ancien
        cycle = [x for x in closed_days if last is None or x[0] > last[0] or (x[0] == last[0] and not last[2])]
        out["payout"] = payout_status(cycle, bal_closed, floor, len(dated), p, live_balance=balance, equity=equity)
    return out


# ---------- dimensionnement ----------
def mini_equiv(positions: dict) -> float:
    """Contrats ouverts en « minis equivalents » : {"NQ": 1, "MNQ": 5} -> 1.5."""
    return sum(q * INSTRUMENTS[r].mini_equiv for r, q in positions.items() if r in INSTRUMENTS)


def max_qty(root: str, p: PropProfile, held: dict | None = None, caps: tuple | None = None) -> int:
    """Nombre maximal de contrats de `root` autorises, compte tenu de ce qui est deja ouvert (minis et micros partagent le plafond).
    `caps` = (minis, micros) du palier du compte finance ; par defaut le plafond du profil."""
    inst = INSTRUMENTS[root]
    used = mini_equiv(held or {})
    max_minis, max_micros = caps or (p.max_minis, p.max_micros)
    if inst.mini_equiv >= 1.0:
        room = max_minis - used
    else:
        room = max_micros * 0.1 - used
        room = min(room, max_minis - used)
    return max(0, int(math.floor(room / inst.mini_equiv + 1e-9)))


def plan(side: str, entry: float, stop: float, targets: list, root: str, p: PropProfile, acct: dict | None = None,
         risk_usd: float | None = None, held: dict | None = None) -> dict:
    """Calcule la taille et le rapport gain / risque d'un trade avant de le prendre.

    side : 'long' | 'short' ; targets : prix d'objectifs. Renvoie un dict avec la taille pour NQ ET pour MNQ (`sizes`), le detail par objectif et
    des avertissements en francais. Le risque inclut les frais aller-retour. Aucune decision : c'est un calcul."""
    inst = INSTRUMENTS[root]
    side = side.lower()
    if side not in ("long", "short"):
        raise ValueError("sens inconnu : long ou short")
    sgn = 1 if side == "long" else -1
    stop_pts = (entry - stop) * sgn
    if stop_pts <= 0:
        raise ValueError("le stop doit être du bon côté de l'entrée (sous l'entrée pour un achat, au-dessus pour une vente)")
    risk = p.risk_per_trade if risk_usd is None else float(risk_usd)
    caps = (acct["caps"]["minis"], acct["caps"]["micros"]) if acct and acct.get("caps") else None          # palier du compte finance
    warns = []
    sizes = {}
    for r in [root] + ([MICRO_OF_ROOT[root]] if root in MICRO_OF_ROOT else []):
        i = INSTRUMENTS[r]
        fee = p.fee_rt.get(r, 0.0)
        per = stop_pts * i.point_value + fee
        n = int(math.floor(risk / per + 1e-9)) if per > 0 else 0
        cap = max_qty(r, p, held, caps)
        qty = max(0, min(n, cap))
        rows = []
        for tp in targets or []:
            pts = (tp - entry) * sgn
            gross = pts * i.point_value * qty
            net = gross - fee * qty
            risk_tot = qty * per
            rows.append({"price": tp, "pts": pts, "gross": gross, "net": net, "r": (net / risk_tot) if risk_tot > 0 else None})
        sizes[r] = {"qty": qty, "wanted": n, "cap": cap, "capped": n > cap, "stopUsd": stop_pts * i.point_value * qty,
                    "riskUsd": qty * per, "feeUsd": fee * qty, "feeTicks": (fee / i.tick_value) if i.tick_value else 0.0, "targets": rows}
    s0 = sizes[root]
    out = {"side": side, "root": root, "entry": entry, "stop": stop, "stopPts": stop_pts, "stopTicks": stop_pts / inst.tick,
           "riskBudget": risk, "sizes": sizes, "warnings": warns}
    if s0["qty"] == 0:
        micro = MICRO_OF_ROOT.get(root)
        alt = sizes.get(micro) if micro else None
        msg = f"Pour {risk:.0f} $ de risque, le stop ({stop_pts:g} pts) est trop large pour 1 {root}"
        warns.append(msg + (f" : utilise le {micro} ({alt['qty']} contrat(s))." if alt and alt["qty"] else "."))
    if s0["capped"]:
        tier = f" (palier de taille du compte financé : le plafond monte à {acct['caps']['next']:.0f} $ de profit)" if acct and acct.get("stage") == "funded" and (acct.get("caps") or {}).get("next") else ""
        warns.append(f"Plafond du compte atteint : {s0['cap']} {root} au maximum (au lieu de {s0['wanted']}){tier}.")
    if acct:
        buf = acct["buffer"]
        worst = max(v["riskUsd"] for v in sizes.values())
        if worst > 0 and buf > 0 and worst > 0.25 * buf:
            warns.append(f"Ce trade risque {worst:.0f} $, soit {worst / buf * 100:.0f} % de la marge restante avant le plancher ({buf:.0f} $).")
        if acct["dayPnl"] - worst <= -acct["dailyStop"]:
            warns.append(f"Si le stop est touché, la journée atteint ton stop quotidien (−{acct['dailyStop']:.0f} $).")
        if acct["breached"]:
            warns.append("Le plancher du compte est atteint : plus aucun trade.")
        elif acct.get("dllHit"):
            warns.append("La limite de perte journalière est atteinte : plus aucun trade jusqu'à la séance suivante.")
    if risk > p.risk_per_trade + 1e-9:
        warns.append(f"Risque demandé ({risk:.0f} $) au-dessus de ta limite par trade ({p.risk_per_trade:.0f} $).")
    first = sizes[root]["targets"][0] if sizes[root]["targets"] else None
    if first and first["gross"] > 0 and sizes[root]["feeUsd"] / first["gross"] > 0.15:
        warns.append(f"Les frais mangent {sizes[root]['feeUsd'] / first['gross'] * 100:.0f} % du premier objectif : objectif trop proche pour ce coût.")
    return out
