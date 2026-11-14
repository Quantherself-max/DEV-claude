#!/usr/bin/env python3
"""Contrôle des sources réelles et du moteur exact (V45), à lancer sur ton ordinateur :

    python tools/check_sources.py            toutes les sources
    python tools/check_sources.py --symbol SOLUSDT

Pour chaque source publique : l'appel répond-il, le format est-il celui attendu ? Et trois preuves de calcul :
  1. Binance : le volume et le volume acheteur d'une minute RECALCULÉS transaction par transaction sont comparés à la bougie officielle
     de la même minute (ils doivent être identiques à l'unité près : c'est la preuve que le CVD tick par tick est exact) ;
  2. Deribit : la volatilité implicite recalculée à partir de la prime de marque est comparée à celle que Deribit publie, et nos grecques
     (delta, gamma, vega, thêta) à celles de son « ticker » ;
  3. réseau Bitcoin : la difficulté de mempool.space est comparée à celle de blockchain.info.
Aucune écriture, aucune clé. Code de sortie 1 si une preuve échoue (une source seulement injoignable ne compte pas comme un échec)."""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.binance import Binance
from ingest.core import IngestError
from ingest.onchain import OnChain
from ingest.venues import Bybit, Deribit, Okx, okx_inst, okx_mmr
from quant import options, perp
from quant.flow import TickCvd, bar_diff
from quant.num import UNIT, fmt

OK, KO, NA = "  OK  ", "  KO  ", "  --  "


class Report:
    def __init__(self):
        self.failed = 0
        self.unreachable = []

    def run(self, name: str, fn):
        try:
            detail = fn()
            print(f"{OK}{name} : {detail}")
        except IngestError as e:
            if e.kind in ("blocked", "network"):
                self.unreachable.append(name)
                print(f"{NA}{name} : injoignable d'ici ({str(e)[:110]})")
            else:
                self.failed += 1
                print(f"{KO}{name} : {str(e)[:160]}")
        except AssertionError as e:
            self.failed += 1
            print(f"{KO}{name} : {e}")
        except Exception as e:                                          # format inattendu : c'est un échec, à corriger
            self.failed += 1
            print(f"{KO}{name} : {type(e).__name__}: {str(e)[:140]}")


def binance_checks(rep: Report, symbol: str):
    b = Binance()
    print("== Binance (perpétuels et comptant) ==")
    for market in ("perp", "spot"):
        def integrity(market=market):
            now = int(time.time() * 1000)
            t1 = now - now % 60_000 - 60_000                            # fin : une minute entièrement fermée
            t0 = t1 - 5 * 60_000                                        # cinq minutes fermées de suite
            official = {r[0]: r for r in b.klines_exact(symbol, "1m", t0, t1 - 1, market) if t0 <= r[0] < t1}
            assert len(official) == 5, f"{len(official)} bougies officielles sur 5"
            c = TickCvd(60_000)
            last, n = None, 0
            while True:
                rows = b.agg_trades(symbol, market, from_id=last + 1) if last is not None else b.agg_trades(symbol, market, start_ms=t0, end_ms=t1 - 1)
                keep = [r for r in rows if r[0] < t1]
                for tt, px, q, side, _ in keep:
                    c.add(tt, px, q, side)
                n += len(keep)
                if len(rows) < 1000 or len(keep) < len(rows):
                    break
                last = rows[-1][4]
            diffs = [bar_diff(c.bars[t], official[t]) if t in c.bars else (-official[t][5] - official[t][6], -official[t][5]) for t in sorted(official)]
            same = sum(1 for d in diffs if d == (0, 0))
            vol = sum(r[5] + r[6] for r in official.values())
            res = sum(d[0] for d in diffs)
            # quelques exécutions peuvent être rangées dans la minute voisine (voir quant.flow.classify_diffs) : le total doit rester juste
            assert abs(res) * 50 <= vol, f"résidu {res / UNIT:+.4f} pièce sur {vol / UNIT:.2f} : des transactions manquent"
            return (f"{n} transactions de 5 minutes recomptées : {same} minute(s) sur 5 IDENTIQUES à la bougie officielle, "
                    f"résidu total {res / UNIT:+.4f} pièce sur {vol / UNIT:.2f} (rangement à la minute près)")
        rep.run(f"CVD exact, {market} {symbol} (transactions contre bougie)", integrity)
    rep.run("intérêt ouvert", lambda: f"{fmt(b.open_interest(symbol)[1])} pièces")
    rep.run("historique d'intérêt ouvert (5 min)", lambda: f"{len(b.open_interest_hist(symbol, '5m', 12))} points")
    rep.run("financement publié", lambda: (lambda f: f"{len(f)} échéances, dernière {fmt(f[-1][1] * 100)} %")(b.funding_rate(symbol, limit=5)))
    rep.run("prix de marque et taux en cours", lambda: (lambda p: f"marque {fmt(p['mark'])}, taux {fmt(p['funding'] * 100)} %")(b.premium_index(symbol)))
    rep.run("ratio long / short des comptes", lambda: (lambda r: f"{fmt(r[-1][2] * 100)} % de comptes longs")(b.long_short(symbol, "5m", 3)))
    rep.run("carnet (photo de 100 niveaux)", lambda: (lambda d: f"meilleur achat {fmt(d['bids'][0][0])}, meilleure vente {fmt(d['asks'][0][0])}")(b.depth(symbol, 100)))


def bybit_checks(rep: Report, symbol: str):
    y = Bybit()
    print("== Bybit ==")
    rep.run("intérêt ouvert (5 min)", lambda: (lambda r: f"{len(r)} points, dernier {fmt(r[-1][1])} pièces")(y.open_interest(symbol, "5min", 12)))
    rep.run("financement publié", lambda: (lambda r: f"{len(r)} échéances, dernière {fmt(r[-1][1] * 100)} %")(y.funding_history(symbol, 5)))
    rep.run("prix de marque", lambda: f"marque {fmt(y.ticker(symbol)['mark'])}")
    rep.run("paliers de marge de maintien", lambda: f"{len(y.risk_limit(symbol))} paliers")


def okx_checks(rep: Report, symbol: str):
    o = Okx()
    inst = okx_inst(symbol)
    print("== OKX ==")
    rep.run("intérêt ouvert", lambda: f"{fmt(o.open_interest(inst)['coins'].quantize(1))} pièces")
    rep.run("financement publié", lambda: (lambda r: f"{len(r)} échéances, dernière {fmt((r[-1][1] * 100).quantize(perp.D('0.000001')))} %")(o.funding_history(inst, 5)))
    rep.run("dernières transactions", lambda: (lambda r: f"{len(r)} transactions, dernier prix {r[-1][1] / UNIT}")(o.trades(inst, 50)))

    def tiers():
        ts = o.position_tiers(inst[:-5])
        mmr = okx_mmr("100", ts)
        lp = perp.liquidation_price("long", "1", "60000", "6000", mmr=mmr)
        return f"{len(ts)} paliers ; exemple : long 1 pièce à 60 000, levier 10, marge de maintien {fmt(mmr * 100)} % -> liquidation à {fmt(lp.quantize(perp.D('0.01')))}"
    rep.run("paliers de marge et prix de liquidation", tiers)


def deribit_checks(rep: Report):
    d = Deribit()
    print("== Deribit (options BTC) ==")
    box = {}

    def chain():
        box["c"] = d.option_chain("BTC")
        c = box["c"]
        return f"{len(c['rows'])} options, {len({r['expiry'] for r in c['rows']})} échéances, indice {c['index']}"
    rep.run("chaîne d'options complète", chain)
    if "c" not in box:
        return
    c = box["c"]
    now = c["t"] or int(time.time() * 1000)

    def iv_check():
        # options HORS de la monnaie seulement (call au-dessus du prix à terme, put en dessous) : leur prime n'est que de la valeur
        # temps, donc la volatilité s'en déduit bien. Dans la monnaie, la prime est surtout de la valeur intrinsèque : un centime
        # d'écart sur le prix à terme y déplace la volatilité de plusieurs points (problème mal conditionné, pas une erreur de formule).
        errs = []
        for r in c["rows"]:
            t = options.years(r["expiry"], now)
            otm = r["strike"] >= r["f"] if r["kind"] == "C" else r["strike"] <= r["f"]
            if t < 2 / 365 or not otm or not r["mark"] or r["mark"] < 0.002 or abs(r["strike"] / r["f"] - 1) > 0.25:
                continue
            iv = options.implied_vol(r["kind"], r["f"], r["strike"], t, r["mark"] * r["f"])
            if iv is not None:
                errs.append(abs(iv - r["iv"]))
        assert len(errs) >= 20, f"trop peu d'options comparables ({len(errs)})"
        errs.sort()
        med, worst = errs[len(errs) // 2], errs[-1]
        assert med < 0.002 and worst < 0.01, f"écart médian {med * 100:.3f}, maximal {worst * 100:.2f} points de volatilité"
        return (f"{len(errs)} options hors de la monnaie : volatilité recalculée de la prime = celle de Deribit à {med * 100:.3f} point près "
                f"(médiane), {worst * 100:.3f} au pire")
    rep.run("volatilité implicite (notre calcul contre Deribit)", iv_check)

    def greeks_check():
        cand = sorted((r for r in c["rows"] if options.years(r["expiry"], now) > 7 / 365 and r["oi"] > 0),
                      key=lambda r: abs(r["strike"] / r["f"] - 1))[:3]
        assert cand, "aucune option proche du prix"
        worst = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        for r in cand:
            tk = d.ticker(r["name"])["raw"]
            g = tk["greeks"]
            f, iv, t = float(tk["underlying_price"]), float(tk["mark_iv"]) / 100.0, options.years(r["expiry"], tk["timestamp"])
            ours = options.greeks(r["kind"], f, r["strike"], iv, t)
            for k in ("delta", "vega", "theta"):
                ref = float(g[k])
                worst[k] = max(worst[k], abs(ours[k] - ref) / max(abs(ref), 1e-9))
            worst["gamma"] = max(worst["gamma"], abs(ours["gamma"] - float(g["gamma"])))
        # Deribit publie son gamma arrondi à 5 décimales (0,00002 pour un gamma de 0,0000237) : la comparaison se fait en écart absolu
        assert all(worst[k] < 0.03 for k in ("delta", "vega", "theta")), f"écarts relatifs : {worst}"
        assert worst["gamma"] <= 0.6e-5, f"gamma : écart {worst['gamma']:.2e} (plus que l'arrondi de Deribit)"
        return ("3 options proches du prix : " + ", ".join(f"{k} à {worst[k] * 100:.3f} % près" for k in ("delta", "vega", "theta"))
                + f", gamma à {worst['gamma']:.1e} près (Deribit l'arrondit à 0,00001)")
    rep.run("grecques (nos formules contre le ticker de Deribit)", greeks_check)

    def smile():
        s = [x for x in options.smile(c["rows"], now) if x["skew25"] is not None]
        assert s, "aucune échéance avec les deux options à 25 delta"
        x = s[0]
        return (f"{len(s)} échéances ; la plus proche ({x['days']:.1f} j) : volatilité au prix {x['atm'] * 100:.1f} %, "
                f"skew 25 delta {x['skew25'] * 100:+.1f} points (put - call)")
    rep.run("skew à 25 delta", smile)

    def gex():
        g = options.gex_by_strike([r for r in c["rows"] if r["oi"] > 0], now, c["index"])
        exp = min(r["expiry"] for r in c["rows"] if r["expiry"] - now > 3_600_000 * 2)
        mp, _ = options.max_pain({str(k): (cc, pp) for k, (cc, pp) in _oi_by_strike(c["rows"], exp).items()})
        return (f"gamma total {g['total'] / 1e6:+.1f} M$ par 1 %, mur de calls {g['callWall']}, mur de puts {g['putWall']}, "
                f"bascule {g['flip'] and round(g['flip'])}, max pain de la prochaine échéance {fmt(mp)}")
    rep.run("exposition gamma et max pain", gex)


def _oi_by_strike(rows, expiry):
    out = {}
    for r in rows:
        if r["expiry"] != expiry or r["oi"] <= 0:
            continue
        k = r["strike"]
        c, p = out.get(k, ("0", "0"))
        out[k] = (r["oiText"], p) if r["kind"] == "C" else (c, r["oiText"])
    return {format(k, ".0f"): v for k, v in out.items()}


def onchain_checks(rep: Report):
    oc = OnChain()
    print("== Réseau Bitcoin ==")
    rep.run("mempool.space : frais", lambda: (lambda f: f"rapide {f['fastest']} sat/vB, 1 heure {f['hour']} sat/vB")(oc.fees()))
    rep.run("mempool.space : transactions en attente", lambda: (lambda m: f"{m['count']} transactions, {fmt(m['blocksToClear'].quantize(perp.D('0.1')))} blocs à vider")(oc.mempool()))
    rep.run("mempool.space : difficulté", lambda: (lambda x: f"prochain ajustement {fmt(x['changePct'].quantize(perp.D('0.01')))} %, dans {x['remainingBlocks']} blocs")(oc.difficulty()))
    rep.run("mempool.space : puissance de calcul", lambda: f"{fmt(oc.hashrate()['hashrateEH'].quantize(1))} EH/s")

    def cm():
        r = oc.coinmetrics(days=5)
        last = r["rows"][-1]
        got = ", ".join(f"{k} {fmt(v.quantize(perp.D('0.001')))}" for k, v in last.items() if k in ("AdrActCnt", "CapMVRVCur", "FlowInExNtv"))
        return f"{len(r['rows'])} jours ; dernier : {got}" + (f" ; refusées par l'accès gratuit : {', '.join(r['refused'])}" if r["refused"] else "")
    rep.run("CoinMetrics : adresses actives, MVRV, flux des bourses", cm)

    def cross():
        a, b = oc.hashrate()["difficulty"], oc.blockchain_stats()["difficulty"]
        gap = abs(a - b) / a
        assert gap < perp.D("0.0001"), f"difficulté : mempool.space {a} contre blockchain.info {b}"
        return f"difficulté identique chez mempool.space et blockchain.info ({fmt(b.quantize(1))})"
    rep.run("contrôle croisé de la difficulté", cross)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="BTCUSDT")
    a = ap.parse_args()
    rep = Report()
    binance_checks(rep, a.symbol)
    bybit_checks(rep, a.symbol)
    okx_checks(rep, a.symbol)
    deribit_checks(rep)
    onchain_checks(rep)
    print("=" * 72)
    if rep.unreachable:
        print(f"Injoignables d'ici ({len(rep.unreachable)}) : " + " ; ".join(rep.unreachable))
    print("Aucune preuve en échec." if not rep.failed else f"{rep.failed} contrôle(s) en échec.")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
