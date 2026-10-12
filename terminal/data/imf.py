"""Projections du Fonds monetaire international (V25) : Perspectives de l'economie mondiale (avril et octobre, mises a jour en janvier et
juillet), par l'API publique DataMapper, sans cle. Croissance du produit interieur brut reel, inflation (moyenne annuelle) et chomage, pour
les Etats-Unis, la zone euro, la Chine, le Japon et le monde. Module PUR (le telechargement passe par data/external.py)."""
from datetime import datetime, timezone

IMF = "https://www.imf.org/external/datamapper/api/v1"
INDICATORS = {"NGDP_RPCH": "Croissance du produit intérieur brut réel", "PCPIPCH": "Inflation (moyenne de l'année)", "LUR": "Taux de chômage"}
AREAS = {"USA": "États-Unis", "EURO": "Zone euro", "CHN": "Chine", "JPN": "Japon", "WEOWORLD": "Monde"}


def years(now_ms: int) -> list:
    y = datetime.fromtimestamp(now_ms / 1000, timezone.utc).year
    return [str(y - 1), str(y), str(y + 1), str(y + 2)]


def url(base: str, indicator: str, now_ms: int) -> str:
    return f"{base.rstrip('/')}/{indicator}/{'/'.join(AREAS)}?periods={','.join(years(now_ms))}"


def parse(obj, indicator: str) -> dict:
    """Reponse JSON de DataMapper -> {zone: {annee (texte): valeur}} ; zones et annees absentes ignorees."""
    vals = ((obj or {}).get("values") or {}).get(indicator) or {}
    out = {}
    for area, row in vals.items():
        if area in AREAS and isinstance(row, dict):
            r = {str(k): float(v) for k, v in row.items() if isinstance(v, (int, float))}
            if r:
                out[area] = r
    return out


SIM = {"NGDP_RPCH": {"USA": (2.8, 1.9, 2.0, 2.1), "EURO": (0.9, 1.2, 1.1, 1.3), "CHN": (5.0, 4.8, 4.2, 4.0), "JPN": (0.1, 1.1, 0.6, 0.6),
                     "WEOWORLD": (3.3, 3.2, 3.1, 3.1)},
       "PCPIPCH": {"USA": (3.0, 2.7, 2.4, 2.1), "EURO": (2.4, 2.1, 1.9, 2.0), "CHN": (0.2, 0.0, 0.8, 1.2), "JPN": (2.7, 3.0, 2.0, 1.9),
                   "WEOWORLD": (5.8, 4.2, 3.6, 3.4)},
       "LUR": {"USA": (4.0, 4.3, 4.4, 4.3), "EURO": (6.4, 6.3, 6.2, 6.2), "CHN": (5.1, 5.1, 5.1, 5.1), "JPN": (2.5, 2.5, 2.4, 2.4)}}


def simulated(indicator: str, now_ms: int) -> dict:
    ys = years(now_ms)
    return {a: {y: v for y, v in zip(ys, vals)} for a, vals in SIM.get(indicator, {}).items()}
