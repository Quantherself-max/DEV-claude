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
    tenus 5 secondes ou moins (voir `MICRO_*` plus bas)."""
import math
from dataclasses import asdict, dataclass, field, fields

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
    daily_loss_limit: float | None = None   # Lucid Flex n'en impose pas ; None = aucune
    min_trading_days: int | None = None     # a verifier : 0 ou 2 selon les sources
    # --- discipline personnelle (PAS des regles de Lucid) : valeurs de depart, a regler ensemble ---
    risk_per_trade: float = 100.0           # risque maximal par trade, en dollars
    daily_stop: float = 300.0               # perte de la journee a partir de laquelle on s'arrete
    # frais ALLER-RETOUR par contrat, en dollars. NQ / MNQ : table du centre d'aide de Lucid (1,75 $ et 0,50 $ PAR COTE, soit 3,50 $ et 1,00 $ l'aller-retour).
    # ES / MES : meme valeur par defaut, non verifiee. Frais de bourse / NFA eventuels non inclus : a remplacer par tes frais reels si tu les connais.
    fee_rt: dict = field(default_factory=lambda: {"NQ": 3.50, "MNQ": 1.00, "ES": 3.50, "MES": 1.00})
    to_verify: tuple = ("jours de trading minimum (0 ou 2 selon les sources)",
                        "frais : commissions Lucid NQ 1,75 $ / MNQ 0,50 $ par côté (confirme à l'achat) ; frais de bourse éventuels non inclus",
                        "limite de perte journalière : option du paiement, montant à lire sur la page d'achat",
                        "règles du compte financé")

    @classmethod
    def from_dict(cls, d: dict) -> "PropProfile":
        """Profil par defaut dont on remplace les champs presents dans `d` (les champs inconnus sont ignores)."""
        base = cls()
        optional = {"consistency_pct", "daily_loss_limit", "min_trading_days", "lock_offset"}      # None est une valeur valide
        for k in {f.name for f in fields(cls)}:
            if k in (d or {}) and (d[k] is not None or k in optional):
                setattr(base, k, d[k])
        base.to_verify = tuple(base.to_verify)
        base.fee_rt = {**PropProfile().fee_rt, **{str(k).upper(): float(v) for k, v in (base.fee_rt or {}).items()}}
        return base

    def to_dict(self) -> dict:
        d = asdict(self)
        d["to_verify"] = list(self.to_verify)
        return d


def trailing_floor(day_pnls: list, p: PropProfile) -> dict:
    """Plancher du compte APRES les journees `day_pnls` (P&L net de chaque journee, du plus ancien au plus recent).

    eod_trailing : plancher = max(plancher precedent, min(meilleur solde EOD - perte max, capital + lock_offset)). Il ne baisse jamais."""
    bal = p.start_balance
    peak = bal
    floor = p.start_balance - p.max_drawdown
    for pnl in day_pnls:
        bal += pnl
        if p.dd_mode == "eod_trailing":
            peak = max(peak, bal)
            nf = peak - p.max_drawdown
            if p.lock_offset is not None:
                nf = min(nf, p.start_balance + p.lock_offset)
            floor = max(floor, nf)
    locked = p.dd_mode == "eod_trailing" and p.lock_offset is not None and floor >= p.start_balance + p.lock_offset - 1e-9
    return {"floor": floor, "peak": peak, "balance": bal, "locked": locked}


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


def state(closed_days: list, today_pnl: float, open_pnl: float, p: PropProfile) -> dict:
    """Etat du compte. closed_days : [(jour, P&L net)] des journees TERMINEES ; today_pnl : P&L realise du jour (net de frais) ; open_pnl : latent.

    Le plancher ne change qu'en fin de journee (EOD) : pendant la seance il reste celui de la veille, et la marge (`buffer`) est mesuree sur
    l'EQUITY (solde + latent), prudemment : la limite est consideree touchee des que l'equity l'atteint."""
    pnls = [x[1] for x in closed_days]
    tf = trailing_floor(pnls, p)
    bal_closed = tf["balance"]
    balance = bal_closed + today_pnl
    equity = balance + open_pnl
    floor = tf["floor"]
    buffer = equity - floor
    profit = balance - p.start_balance
    all_days = pnls + ([today_pnl] if today_pnl else [])
    cons = consistency(all_days, p)
    cons["todayCap"] = consistency(pnls, p)["dayCap"]          # gain maximal d'AUJOURD'HUI sans depasser la part autorisee du total (total des journees terminees)
    traded = len([x for x in closed_days if x[1] != 0]) + (1 if today_pnl else 0)
    target_hit = profit >= p.profit_target
    enough_days = p.min_trading_days is None or traded >= p.min_trading_days
    breached = equity <= floor + 1e-9 or (p.daily_loss_limit is not None and today_pnl + open_pnl <= -p.daily_loss_limit)
    passed = (not breached) and target_hit and cons["ok"] and enough_days
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
    best_day = None
    if closed_days:
        best_day = max(closed_days, key=lambda x: x[1])
    return {
        "name": p.name, "status": status, "start": p.start_balance, "balance": balance, "equity": equity, "floor": floor,
        "buffer": buffer, "bufferFrac": frac, "locked": tf["locked"], "peakEod": tf["peak"],
        "profit": profit, "target": p.profit_target, "targetLeft": max(0.0, p.profit_target - profit),
        "progress": max(0.0, min(1.0, profit / p.profit_target)) if p.profit_target else 0.0,
        "targetHit": target_hit, "consistency": cons, "bestDay": best_day[1] if best_day else 0.0, "bestDayDate": best_day[0] if best_day else None,
        "daysTraded": traded, "minDays": p.min_trading_days, "enoughDays": enough_days,
        "todayPnl": today_pnl, "openPnl": open_pnl, "dayPnl": day_now,
        "dailyStop": p.daily_stop, "dailyStopLeft": max(0.0, p.daily_stop + day_now) if day_now < 0 else p.daily_stop,
        "dailyStopHit": day_now <= -p.daily_stop,
        "maxMinis": p.max_minis, "maxMicros": p.max_micros, "riskPerTrade": p.risk_per_trade,
        "passed": passed, "breached": breached,
    }


# ---------- dimensionnement ----------
def mini_equiv(positions: dict) -> float:
    """Contrats ouverts en « minis equivalents » : {"NQ": 1, "MNQ": 5} -> 1.5."""
    return sum(q * INSTRUMENTS[r].mini_equiv for r, q in positions.items() if r in INSTRUMENTS)


def max_qty(root: str, p: PropProfile, held: dict | None = None) -> int:
    """Nombre maximal de contrats de `root` autorises, compte tenu de ce qui est deja ouvert (minis et micros partagent le plafond)."""
    inst = INSTRUMENTS[root]
    used = mini_equiv(held or {})
    if inst.mini_equiv >= 1.0:
        room = p.max_minis - used
    else:
        room = p.max_micros * 0.1 - used
        room = min(room, p.max_minis - used)
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
    warns = []
    sizes = {}
    for r in [root] + ([MICRO_OF_ROOT[root]] if root in MICRO_OF_ROOT else []):
        i = INSTRUMENTS[r]
        fee = p.fee_rt.get(r, 0.0)
        per = stop_pts * i.point_value + fee
        n = int(math.floor(risk / per + 1e-9)) if per > 0 else 0
        cap = max_qty(r, p, held)
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
        warns.append(f"Plafond du compte atteint : {s0['cap']} {root} au maximum (au lieu de {s0['wanted']}).")
    if acct:
        buf = acct["buffer"]
        worst = max(v["riskUsd"] for v in sizes.values())
        if worst > 0 and buf > 0 and worst > 0.25 * buf:
            warns.append(f"Ce trade risque {worst:.0f} $, soit {worst / buf * 100:.0f} % de la marge restante avant le plancher ({buf:.0f} $).")
        if acct["dayPnl"] - worst <= -acct["dailyStop"]:
            warns.append(f"Si le stop est touché, la journée atteint ton stop quotidien (−{acct['dailyStop']:.0f} $).")
        if acct["breached"]:
            warns.append("Le plancher du compte est atteint : plus aucun trade.")
    if risk > p.risk_per_trade + 1e-9:
        warns.append(f"Risque demandé ({risk:.0f} $) au-dessus de ta limite par trade ({p.risk_per_trade:.0f} $).")
    first = sizes[root]["targets"][0] if sizes[root]["targets"] else None
    if first and first["gross"] > 0 and sizes[root]["feeUsd"] / first["gross"] > 0.15:
        warns.append(f"Les frais mangent {sizes[root]['feeUsd'] / first['gross'] * 100:.0f} % du premier objectif : objectif trop proche pour ce coût.")
    return out
