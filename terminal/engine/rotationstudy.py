"""Mesure de la rotation du capital et de l'or sur le prix futur (V10) : meme methode que engine/indstudy.py (rang percentile sur fenetre croissante, rendement
futur a 7 / 14 / 30 jours avec un jour de decalage, Newey-West, apprentissage / test, temoin par decalage), appliquee a TROIS cibles :
  - le bitcoin (ou va son prix ?), - les altcoins contre le bitcoin (le capital va-t-il vers les alts ?), - l'or contre le bitcoin (vers l'or ?),
plus l'etude de l'asymetrie bitcoin / or (engine/goldbtc.py) et la carte du capital d'aujourd'hui. Module PUR."""
import time

from . import goldbtc
from . import indstudy as ist
from . import rotation

DAY = 86_400_000
HORIZONS = (7, 14, 30)


def _pts(x: float | None, d=1) -> str:
    return "n/d" if x is None else f"{x:+.{d}f}".replace(".", ",").replace("-", "−")


def run(od, label: str, start_ms: int, end_ms: int, split_ms: int, horizons=HORIZONS, shifts: int = 30, progress=None) -> dict:
    t0 = time.time()
    say = progress or (lambda *_: None)
    say("construction des séries…")
    grid, series, targets, maps = rotation.build(od, start_ms - 400 * DAY, end_ms)
    n = len(grid)
    lo = next((i for i, t in enumerate(grid) if t >= start_ms), 0)
    sp = next((i for i, t in enumerate(grid) if t >= split_ms), n)
    out_targets = []
    for key, (title, desc) in rotation.TARGETS.items():
        say(f"mesure : {title}…")
        cat = {k: (g, t, e if key == "BTC" else 0, h, u) for k, (g, t, e, h, u) in rotation.CATALOG.items()}
        rows, null, thr, last = ist.evaluate(series, targets[key], cat, grid, lo, sp, horizons, 1, 365, shifts)
        out_targets.append({"key": key, "title": title, "desc": desc, "rows": rows, "null": null, "threshold": thr,
                            "counts": {"indicators": len(rows), "tests": len(rows) * len(horizons), "informative": sum(1 for r in rows if r["level"] == "informatif"), "hints": sum(1 for r in rows if r["level"] == "indice")}})
    say("or et bitcoin…")
    gold = goldbtc.analyse(maps["gold"], maps["btcPrice"], grid, split_ms)
    snap = rotation.snapshot(od)
    step = 7
    chart = [[grid[i], round(maps["shares"]["btc"][i], 5), round(maps["shares"]["eth"][i], 5), round(maps["shares"]["alts"][i], 5), round(maps["stableShare"][i], 5) if maps["stableShare"][i] is not None else None]
             for i in range(lo, n, step) if maps["shares"]["btc"][i] is not None]
    rep = {"kind": "rotation", "label": label, "computedAt": int(time.time() * 1000), "period": {"start": start_ms, "end": grid[ist_last(maps)] + DAY, "split": split_ms}, "horizons": list(horizons),
           "targets": out_targets, "gold": gold, "map": {"snapshot": snap, "reading": rotation.reading(snap), "series": chart}, "seconds": round(time.time() - t0)}
    rep["verdict"] = verdict(rep)
    return rep


def ist_last(maps) -> int:
    b = maps["btcPrice"]
    return max((i for i, v in enumerate(b) if v is not None), default=len(b) - 1)


def verdict(rep: dict) -> dict:
    notes = []
    tot_inf = sum(t["counts"]["informative"] for t in rep["targets"])
    tot_hint = sum(t["counts"]["hints"] for t in rep["targets"])
    n_tests = sum(t["counts"]["tests"] for t in rep["targets"])
    g = rep["gold"]
    semi = (g.get("semi") or {}).get("all")
    c90 = (g.get("corr") or {}).get("90")
    if tot_inf:
        names = [f"{r['title']} → {t['title'].lower()}" for t in rep["targets"] for r in t["rows"] if r["level"] == "informatif"]
        text = f"{tot_inf} lien(s) mesurable(s) et stable(s) sur {n_tests} mesures : " + " ; ".join(names) + "."
    else:
        text = f"Sur {n_tests} mesures (9 indicateurs de rotation × 3 cibles × 3 horizons), aucun lien ne dépasse le seuil du hasard à la fois à l'apprentissage et au test : savoir où va le capital aujourd'hui n'indique pas, de façon prouvée, où ira le prix."
    hints = [f"{r['title']} → {t['title'].lower()}" for t in rep["targets"] for r in t["rows"] if r["level"] == "indice"]
    if hints:
        text += " À surveiller (indice sans preuve) : " + " ; ".join(hints) + "."
    for t in rep["targets"]:
        nul = t["null"]
        notes.append(f"Cible « {t['title']} » : seuil du hasard |t| ≥ {str(round(t['threshold'], 1)).replace('.', ',')} (témoin : 95 % à {str(round(nul['p95'], 1)).replace('.', ',')}) ; {t['counts']['informative']} informatif(s), {t['counts']['hints']} indice(s).")
    if c90:
        notes.append(f"Corrélation bitcoin / or (rendements quotidiens, fenêtres de 90 jours) : {_pts(c90['mean'], 2)} en moyenne, de {_pts(c90['min'], 2)} à {_pts(c90['max'], 2)} ; positive {c90['positive'] * 100:.0f} % du temps : le lien existe mais il est faible et change de signe.")
    if semi:
        a, o = semi["asym"], (g["semi"].get("oos") or {}).get("asym")
        txt = (f"Asymétrie : quand l'or monte, le bitcoin bouge de {_pts(semi['up']['beta'], 2)} pour 1 de l'or (t = {_pts(semi['up']['t'], 1)}) ; quand l'or baisse, de {_pts(semi['down']['beta'], 2)} (t = {_pts(semi['down']['t'], 1)}). "
               f"L'écart entre les deux ({_pts(a['diff'], 2)}, t = {_pts(a['t'], 1)}) " + ("est significatif." if abs(a["t"]) >= 2 else "n'est pas significatif : l'asymétrie n'est pas démontrée."))
        notes.append(txt)
    sh = (g.get("shocks") or {}).get("all") or []
    if len(sh) == 2 and sh[0].get("same") and sh[1].get("same"):
        notes.append(f"Jours de choc de l'or : après un jour à {sh[0]['label']} ({sh[0]['n']} jours), le bitcoin gagne {_pts(sh[0]['same']['mean'] * 100, 1)} % le même jour mais {_pts(sh[0]['next']['mean'] * 100, 1)} % le lendemain (t = {_pts(sh[0]['next']['t'], 1)}) ; "
                     f"après {sh[1]['label']} ({sh[1]['n']} jours) : {_pts(sh[1]['same']['mean'] * 100, 1)} % le même jour, {_pts(sh[1]['next']['mean'] * 100, 1)} % le lendemain. Le lien est simultané, pas prédictif.")
    ll = [x for x in (g.get("leadLag") or {}).get("all", []) if x.get("t") is not None]
    if ll:
        best = max(ll, key=lambda x: abs(x["t"]))
        notes.append(f"Avance / retard : le rendement de l'or sur les {best['k']} jours précédents n'explique pas celui du bitcoin du jour (pente {_pts(best['beta'], 2)}, t = {_pts(best['t'], 1)}, le plus fort des trois horizons testés).")
    rd = rep["map"]["reading"]["text"]
    notes.insert(0, "Carte du capital aujourd'hui : " + rd)
    return {"text": text, "notes": notes, "informative": tot_inf, "hints": tot_hint}
