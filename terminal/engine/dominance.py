"""Dominance du Bitcoin et force des altcoins face au BTC.

- Dominance « officielle » (CoinGecko / CoinPaprika) : part du BTC dans la capitalisation totale du crypto ;
  le terminal en garde l'historique des qu'il tourne.
- Panier alts/BTC (historique REEL Binance spot) : moyenne equipondere de ETH, SOL, BNB, XRP, ADA, DOGE, AVAX
  et LINK cotes en BTC. S'il monte, les alts battent le BTC (la dominance baisse) ; s'il baisse, l'inverse.
- Regime = (direction du BTC) x (direction du panier) sur 5 jours ; probabilite de continuation mesuree sur
  ~2,7 ans de bougies quotidiennes (le panier surperforme-t-il encore le BTC le jour / les 3 jours suivants ?).
- Beta de la paire affichee face au BTC (30 j) : de combien elle bouge pour 1 % de mouvement du BTC."""
import math
from bisect import bisect_right

from .stats import wilson

HOUR = 3_600_000
DAY = 86_400_000

REGIMES = {
    ("up", "dn"): ("Saison BTC", "bad", "Le BTC monte et capte la liquidité ; les altcoins sous-performent. Défavorable aux longs sur alts : un long SOL doit battre le BTC pour payer.", -0.5),
    ("up", "up"): ("Alt season / appétit pour le risque", "ok", "Le BTC monte et les altcoins montent encore plus vite : la liquidité déborde sur les alts. Favorable aux longs SOL.", 0.6),
    ("dn", "dn"): ("Risk-off : les alts saignent plus", "bad", "Le BTC baisse et les altcoins baissent plus fort : fuite vers le BTC et les stables. Très défavorable aux longs sur alts, les shorts alts sont favorisés.", -0.7),
    ("dn", "up"): ("Rotation fragile vers les alts", "warn", "Les alts résistent ou montent pendant que le BTC baisse. Rare et fragile : souvent le dernier souffle avant un retour de la baisse.", 0.1),
    ("flat", "up"): ("Rotation vers les alts", "ok", "Le BTC est stable et les alts gagnent du terrain : début possible d'une rotation vers les alts.", 0.4),
    ("flat", "dn"): ("Alts délaissées", "warn", "Le BTC est stable mais les alts perdent du terrain : l'argent quitte les alts sans repartir ailleurs.", -0.3),
    ("up", "flat"): ("Hausse portée par le BTC", "muted", "Le BTC monte, les alts suivent à peu près : pas de rotation nette.", 0.15),
    ("dn", "flat"): ("Baisse générale", "warn", "Le BTC baisse, les alts suivent à peu près : pas de rotation nette.", -0.15),
    ("flat", "flat"): ("Consolidation", "muted", "Ni le BTC ni les alts ne prennent la direction : pas de lecture de dominance.", 0.0),
}


def _align(series_by_pair, min_pairs=5):
    """Panier equipondere : exp(moyenne des ln(cloture / premiere cloture commune)) x 100, aux dates communes."""
    pairs = [p for p, s in series_by_pair.items() if s]
    if len(pairs) < min_pairs:
        return []
    maps = {p: dict(series_by_pair[p]) for p in pairs}
    ts = sorted(set.intersection(*[set(m) for m in maps.values()])) if len(pairs) else []
    if len(ts) < 10:                                           # peu de dates communes : on tolere des trous
        ts = sorted(set().union(*[set(m) for m in maps.values()]))
    out, base = [], {}
    for t in ts:
        vals = {p: maps[p][t] for p in pairs if t in maps[p] and maps[p][t] > 0}
        if len(vals) < min_pairs:
            continue
        for p, v in vals.items():
            base.setdefault(p, v)
        out.append((t, 100.0 * math.exp(sum(math.log(v / base[p]) for p, v in vals.items()) / len(vals))))
    return out


def _chg(series, ago_ms):
    if not series:
        return None
    t_last, v_last = series[-1]
    ts = [t for t, _ in series]
    i = bisect_right(ts, t_last - ago_ms) - 1
    return (v_last / series[i][1] - 1) * 100.0 if i >= 0 and series[i][1] else None


def _dir(x, thr):
    return None if x is None else "up" if x > thr else "dn" if x < -thr else "flat"


def beta(c_sym, c_btc, last=720):
    """Regression des rendements horaires (`last` heures) de la paire sur ceux du BTC : beta, correlation, R2."""
    a = {k.t: k.c for k in c_sym}
    b = {k.t: k.c for k in c_btc}
    ts = sorted(set(a) & set(b))[-(last + 1):]
    ra = [math.log(a[t1] / a[t0]) for t0, t1 in zip(ts, ts[1:]) if a[t0] > 0 and a[t1] > 0]
    rb = [math.log(b[t1] / b[t0]) for t0, t1 in zip(ts, ts[1:]) if b[t0] > 0 and b[t1] > 0]
    n = min(len(ra), len(rb))
    if n < min(100, last // 2):
        return None
    ra, rb = ra[-n:], rb[-n:]
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    if vb <= 0 or va <= 0:
        return None
    return {"beta": cov / vb, "corr": cov / math.sqrt(va * vb), "r2": cov * cov / (va * vb), "n": n}


def regime_stats(altD, window=5):
    """Sur l'historique quotidien : apres chaque regime (BTC x panier sur `window` jours), le panier
    surperforme-t-il le BTC le jour suivant / dans 3 jours ? Renvoie un tableau par regime + le regime actuel."""
    btc = altD.get("BTCUSDT")
    pairs = {p: s for p, s in altD.items() if p != "BTCUSDT"}
    idx = _align(pairs)
    if not btc or len(idx) < 200:
        return None
    bm, im = dict(btc), dict(idx)
    ts = [t for t in sorted(set(bm) & set(im))]
    b, ix = [bm[t] for t in ts], [im[t] for t in ts]
    n = len(ts)
    cb = [(b[i] / b[i - window] - 1) * 100 for i in range(window, n)]
    ci = [(ix[i] / ix[i - window] - 1) * 100 for i in range(window, n)]
    sb = math.sqrt(sum(x * x for x in cb) / len(cb))
    si = math.sqrt(sum(x * x for x in ci) / len(ci))
    tb, ti = 0.35 * sb, 0.35 * si                                  # seuil « mouvement net » ~ un tiers de l'ecart-type
    cnt, base = {}, [0, 0, 0, 0]
    for k in range(len(cb) - 3):
        i = k + window
        reg = (_dir(cb[k], tb), _dir(ci[k], ti))
        # surperformance relative = le panier (deja cote en BTC) monte
        r1 = ix[i + 1] > ix[i]
        r3 = ix[i + 3] > ix[i]
        c = cnt.setdefault(reg, [0, 0, 0])
        c[0] += 1; c[1] += r1; c[2] += r3
        base[0] += 1; base[1] += r1; base[2] += r3
    out = {}
    for reg, (m, k1, k3) in cnt.items():
        neff = max(1, m // 3)                                       # fenetres glissantes : echantillons chevauchants
        p1, lo1, hi1 = wilson(round(k1 / m * neff), neff)
        p3, lo3, hi3 = wilson(round(k3 / m * neff), neff)
        out["|".join(reg)] = {"n": m, "neff": neff, "p1": k1 / m, "lo1": lo1, "hi1": hi1, "p3": k3 / m, "lo3": lo3, "hi3": hi3}
    cur = (_dir(cb[-1], tb), _dir(ci[-1], ti))
    return {"table": out, "cur": "|".join(cur), "base1": base[1] / base[0], "base3": base[2] / base[0], "days": n,
            "thr": {"btc": tb, "alts": ti}}


def analyse(snap, c_btc_h1, c_sym_h1, sym):
    alt, altD, cg, hist = snap.get("alt") or {}, snap.get("altD") or {}, snap.get("cg"), snap.get("cg_hist") or []
    if not alt and not cg:
        return {"ready": False, "errors": snap.get("errors", {})}
    idx = _align(alt)
    out = {"ready": True, "errors": snap.get("errors", {})}
    if cg:
        d24 = next((h for h in reversed(hist) if h[0] <= cg["t"] - 23 * HOUR), None)
        d7 = next((h for h in reversed(hist) if h[0] <= cg["t"] - 6.5 * DAY), None)
        out["cg"] = {"btc_d": cg["btc_d"], "eth_d": cg.get("eth_d"), "total": cg["total"], "chg24": cg.get("chg24"),
                     "src": cg.get("src"), "d24": cg["btc_d"] - d24[1] if d24 else None, "d7": cg["btc_d"] - d7[1] if d7 else None,
                     "spark": [[h[0], round(h[1], 3)] for h in hist[-600:][::max(1, len(hist[-600:]) // 120)]],
                     "histSince": hist[0][0] if hist else None}
    btc_series = [(k.t, k.c) for k in c_btc_h1[-24 * 45:]]
    btc7, btc24 = _chg(btc_series, 7 * DAY), _chg(btc_series, DAY)
    rel = {}
    for name, series in (("Panier alts/BTC", idx), ("SOL/BTC", alt.get("SOLBTC")), ("ETH/BTC", alt.get("ETHBTC"))):
        if series:
            rel[name] = {"c24": _chg(series, DAY), "c7": _chg(series, 7 * DAY), "last": series[-1][1],
                         "spark": [[t, round(v, 6)] for t, v in series[-24 * 30:][::6]]}
    out["rel"] = rel
    out["btc"] = {"c24": btc24, "c7": btc7}
    if idx and btc7 is not None:
        i7 = rel["Panier alts/BTC"]["c7"]
        reg = (_dir(btc7, 1.5), _dir(i7, 1.0))
        name, tone, text, score = REGIMES[reg]
        out["regime"] = {"key": "|".join(reg), "name": name, "tone": tone, "text": text, "score": score}
    rs = regime_stats(altD) if altD else None
    if rs:
        out["stats"] = rs
        cur = rs["table"].get(rs["cur"])
        out["statsCurrent"] = {"key": rs["cur"], **(cur or {})}
    if sym != "BTCUSDT":
        betas = {w: beta(c_sym_h1, c_btc_h1, 24 * d) for w, d in (("30 j", 30), ("90 j", 90), ("1 an", 365))}
        betas = {w: b for w, b in betas.items() if b}
        if betas:
            out["betas"] = betas
            out["beta"] = betas.get("90 j") or next(iter(betas.values()))
            out["beta"]["window"] = "90 j" if "90 j" in betas else next(iter(betas))
    else:
        out["isBtc"] = True
    pair = alt.get(sym.replace("USDT", "BTC"))
    if pair and sym != "BTCUSDT":
        out["symRel"] = {"name": sym.replace("USDT", "") + "/BTC", "c24": _chg(pair, DAY), "c7": _chg(pair, 7 * DAY)}
    lines = []
    if cg:
        o = out["cg"]
        chg = f" ({o['d24']:+.2f} pt en 24 h)" if o["d24"] is not None else ""
        lines.append(f"Dominance BTC : {o['btc_d']:.1f} %{chg} · capitalisation crypto {o['total'] / 1e12:.2f} T$ ({o['chg24']:+.1f} % en 24 h). Source : {o['src']}.")
    if "regime" in out:
        lines.append(f"Régime sur 5-7 jours : {out['regime']['name']}. {out['regime']['text']}")
    if "statsCurrent" in out and out["statsCurrent"].get("n"):
        c = out["statsCurrent"]
        lines.append(f"Historique réel ({rs['days']} jours) : après ce régime, le panier d'alts a encore surperformé le BTC le lendemain dans {c['p1'] * 100:.0f} % des cas "
                     f"(hasard : {rs['base1'] * 100:.0f} %) et à 3 jours dans {c['p3'] * 100:.0f} % (hasard : {rs['base3'] * 100:.0f} %), sur {c['n']} jours dont {c['neff']} indépendants.")
    if "beta" in out:
        b = out["beta"]
        lines.append(f"{sym.replace('USDT', '')} bouge de {b['beta']:.2f} % quand le BTC bouge de 1 % ({b['window']}, corrélation {b['corr']:.2f}) : "
                     f"un levier 10x sur {sym.replace('USDT', '')} équivaut à ~{10 * b['beta']:.0f}x sur le BTC.")
    out["lines"] = lines
    return out
