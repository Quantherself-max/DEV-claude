"""Annonces macro et fenetres a eviter. Module PUR (le chargement du fichier est ici, sans reseau).

Le terminal NQ ne telecharge pas encore de calendrier : tu le tiens dans `data_local/events.json` (voir events.example.json), un tableau de
{"t": "2026-10-14T12:30:00Z" (ou ms depuis 1970), "name": "CPI (inflation US)", "impact": 1 a 3, "note": "facultatif"}.
Un flux automatique (calendrier economique, resultats d'entreprises du Nasdaq-100) viendra plus tard.

Pourquoi une fenetre a eviter : une annonce de niveau 3 (CPI, emploi, Fed) fait sauter les carnets d'ordres ; le slippage et les mouvements
d'une seconde sont sans rapport avec le reste de la journee. Les dates ci-dessous (avant / apres) sont des valeurs de depart a regler."""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import clock

MIN = 60_000
IMPACT_LABEL = {1: "faible", 2: "moyen", 3: "fort"}


@dataclass(frozen=True)
class Event:
    t: int
    name: str
    impact: int = 2
    note: str = ""

    def to_dict(self) -> dict:
        return {"t": self.t, "name": self.name, "impact": self.impact, "impactLabel": IMPACT_LABEL.get(self.impact, "?"), "note": self.note,
                "paris": clock.fmt_hm(self.t, "paris"), "et": clock.fmt_hm(self.t, "et")}


def _when(x) -> int:
    if isinstance(x, (int, float)):
        return int(x if x > 1e11 else x * 1000)
    s = str(x).strip()
    if s.isdigit():
        return _when(int(s))
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp() * 1000)


def parse(items) -> list:
    """Liste de dict -> [Event] triee. Les entrees illisibles sont ignorees (le nombre d'ignorees est dans `parse.skipped`)."""
    out, skipped = [], 0
    for it in items or []:
        try:
            out.append(Event(_when(it["t"]), str(it["name"])[:80], max(1, min(3, int(it.get("impact", 2)))), str(it.get("note", ""))[:200]))
        except (KeyError, ValueError, TypeError, AttributeError):
            skipped += 1
    parse.skipped = skipped
    return sorted(out, key=lambda e: e.t)


parse.skipped = 0


def load(path) -> list:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        return parse(json.loads(p.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        return []


def upcoming(events: list, now_ms: int, n: int = 5, horizon_h: float = 48.0, min_impact: int = 1) -> list:
    lim = now_ms + int(horizon_h * 3_600_000)
    return [e for e in events if now_ms - 5 * MIN <= e.t <= lim and e.impact >= min_impact][:n]


def blackout(events: list, now_ms: int, before_min: float = 2.0, after_min: float = 3.0, min_impact: int = 3):
    """L'evenement qui impose une pause a cet instant (de `before_min` avant a `after_min` apres), ou None."""
    for e in events:
        if e.impact >= min_impact and e.t - before_min * MIN <= now_ms <= e.t + after_min * MIN:
            return e
    return None
