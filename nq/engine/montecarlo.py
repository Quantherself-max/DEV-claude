"""Monte Carlo de l'évaluation Lucid. Module PUR.

Question posée : « avec CETTE distribution de journées (sortie du backtest), quelle est ma probabilité de valider l'évaluation avant de toucher
le plancher, et en combien de jours ? ». Un seul backtest donne UN chemin ; l'ordre des journées est en partie de la chance (une grosse perte
au début ne fait pas le même effet qu'à la fin, à cause du plancher qui suit le meilleur solde). On tire donc au hasard, avec remise, des
journées dans l'historique (bootstrap) et on rejoue des milliers d'évaluations avec les VRAIES règles du profil :
  - plancher de fin de journée qui suit le meilleur solde puis se verrouille (ou plancher fixe), et touché EN COURS de journée si le creux
    réalisé de la journée l'atteint (on garde le creux de chaque journée, pas seulement sa clôture) ;
  - cible de profit ET consistance (meilleur jour ≤ X % du profit total) : tant qu'elle n'est pas respectée, on continue de trader ;
  - horizon maximal en jours (au-delà : « ni validé ni perdu »).
Les journées sans trade comptent (elles font passer le temps, pas le solde).

Limites (affichées dans l'interface) : on suppose les journées indépendantes et l'avenir semblable à l'historique. Avec peu de journées,
le résultat est fragile : on le signale."""
import random
from statistics import median

from . import risk


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    k = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def simulate_eval(samples, profile: risk.PropProfile, n_paths: int = 2000, horizon: int = 60, seed: int = 7, eval_fee: float | None = None) -> dict:
    """`samples` : liste de (P&L net de la journée, creux réalisé de la journée ≤ 0). Renvoie probabilités et distribution des durées."""
    samples = [(float(p), min(0.0, float(lo))) for p, lo in samples]
    if not samples:
        return {"ok": False, "msg": "aucune journée à tirer"}
    rng = random.Random(seed)
    c = (profile.consistency_pct or 0.0) / 100.0
    lock = risk.locked_level(profile)
    trailing = profile.dd_mode == "eod_trailing"
    n_pass = n_breach = n_cons_wait = 0
    pass_days, breach_days, finals = [], [], []
    for _ in range(int(n_paths)):
        bal = peak = profile.start_balance
        floor = profile.start_balance - profile.max_drawdown
        best = 0.0
        waited = False
        outcome = None
        for d in range(1, int(horizon) + 1):
            pnl, low = samples[rng.randrange(len(samples))]
            if bal + low <= floor + 1e-9:                     # plancher touché en cours de journée
                outcome = "breach"
                bal = bal + low
                break
            bal += pnl
            if bal <= floor + 1e-9:
                outcome = "breach"
                break
            best = max(best, pnl)
            if trailing:
                peak = max(peak, bal)
                nf = peak - profile.max_drawdown
                if lock is not None:
                    nf = min(nf, lock)
                floor = max(floor, nf)
            profit = bal - profile.start_balance
            if profit >= profile.profit_target - 1e-6:
                if not c or best <= c * profit + 1e-9:
                    outcome = "pass"
                    break
                waited = True                                  # cible atteinte mais consistance pas encore respectée
        finals.append(bal)
        if outcome == "pass":
            n_pass += 1
            pass_days.append(d)
            n_cons_wait += 1 if waited else 0
        elif outcome == "breach":
            n_breach += 1
            breach_days.append(d)
    n = int(n_paths)
    pass_days.sort()
    breach_days.sort()
    finals.sort()
    p_pass = n_pass / n
    traded = [p for p, _ in samples]
    return {
        "ok": True, "paths": n, "horizon": int(horizon), "sampleDays": len(samples), "fragile": len(samples) < 15,
        "pPass": round(p_pass, 3), "pBreach": round(n_breach / n, 3), "pTimeout": round((n - n_pass - n_breach) / n, 3),
        "consistencyDelayed": round(n_cons_wait / n_pass, 3) if n_pass else None,      # part des validations retardées par la consistance
        "daysToPass": {"p25": _pct(pass_days, 0.25), "median": median(pass_days) if pass_days else None, "p75": _pct(pass_days, 0.75)},
        "daysToBreach": {"median": median(breach_days) if breach_days else None},
        "finalBalance": {"p10": round(_pct(finals, 0.10), 2), "median": round(_pct(finals, 0.5), 2), "p90": round(_pct(finals, 0.90), 2)},
        "dayMean": round(sum(traded) / len(traded), 2), "dayWorstLow": round(min(lo for _, lo in samples), 2),
        # coût moyen pour obtenir UNE évaluation validée : prix d'une tentative / probabilité de réussite (tentatives indépendantes)
        "attemptsPerPass": round(1 / p_pass, 2) if p_pass > 0 else None,
        "costPerPass": round(eval_fee / p_pass, 2) if eval_fee and p_pass > 0 else None, "evalFee": eval_fee,
    }
