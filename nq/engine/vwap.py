"""VWAP de seance, bandes d'ecart-type et VWAP ancre, alignes sur les barres. Module PUR.

Chaque barre porte pv = somme prix x quantite et pv2 = somme prix^2 x quantite de SES transactions : le VWAP et l'ecart-type sont donc
exacts (aucun « prix typique » de barre). Le VWAP cumule depuis le debut de la seance ; une cle de seance qui change remet les sommes a zero
et une cle `None` (hors seance) donne `None` : la ligne est coupee sur le graphique."""
import math

from . import clock


def key_globex(t: int):
    """Un VWAP par journee de trading (remise a zero a 18 h ET)."""
    return clock.trading_day(t)


def key_rth(t: int):
    """Un VWAP par seance reguliere (9 h 30 - 16 h ET) ; hors seance : None."""
    day = clock.trading_day(t)
    a, b = clock.window(day, "rth")
    return day if a <= t < b else None


def cumulative(bars, key_fn=key_globex, anchor_ms: int | None = None) -> list:
    """Pour chaque barre : (vwap, ecart-type) APRES cette barre, ou (None, None). `anchor_ms` : VWAP ancre (rien avant cet instant)."""
    out = []
    key = None
    s0 = s1 = s2 = 0.0
    for b in bars:
        k = key_fn(b.t) if anchor_ms is None else (0 if b.t >= anchor_ms else None)
        if k is None:
            out.append((None, None))
            key = None
            continue
        if k != key:
            key, s0, s1, s2 = k, 0.0, 0.0, 0.0
        s0 += b.v
        s1 += b.pv
        s2 += b.pv2
        if s0 > 0:
            m = s1 / s0
            out.append((m, math.sqrt(max(s2 / s0 - m * m, 0.0))))
        else:
            out.append((None, None))
    return out


def sample(base_bars, base_vals: list, chart_bars, chart_step: int) -> list:
    """Reporte une serie calculee sur les barres de base vers les barres du graphique : valeur de la DERNIERE barre de base contenue
    dans chaque barre du graphique (None si aucune)."""
    out = []
    j, n = 0, len(base_bars)
    for cb in chart_bars:
        end = cb.t + chart_step
        last = None
        while j < n and base_bars[j].t < end:
            if base_bars[j].t >= cb.t:
                last = base_vals[j]
            j += 1
        out.append(last)
    return out


def bands(vals: list, ks=(1.0, 2.0)) -> dict:
    """{"v": [...], "u1": [...], "l1": [...], "u2": [...], "l2": [...]} a partir de [(vwap, sd) ou None]."""
    out = {"v": []}
    for k in ks:
        out[f"u{k:g}"], out[f"l{k:g}"] = [], []
    for x in vals:
        if x is None or x[0] is None:
            out["v"].append(None)
            for k in ks:
                out[f"u{k:g}"].append(None)
                out[f"l{k:g}"].append(None)
            continue
        m, sd = x
        out["v"].append(round(m, 4))
        for k in ks:
            out[f"u{k:g}"].append(round(m + k * sd, 4))
            out[f"l{k:g}"].append(round(m - k * sd, 4))
    return out
