"""Chiffres macro officiels des Etats-Unis (V18) : base FRED de la Reserve federale de Saint-Louis, telechargement CSV public, sans cle.

Chaque serie est une liste [(date d'observation en ms UTC, valeur)]. La date d'observation est la PERIODE mesuree (septembre pour l'inflation de
septembre publiee mi-octobre), pas la date de publication : `lag` donne le delai minimal habituel entre les deux (sert seulement a reconstruire
un bilan d'une semaine passee sans utiliser un chiffre qui n'etait pas encore publie). Les series peuvent etre revisees apres coup (emplois, PIB) :
FRED donne la derniere valeur connue. Module sans dependance."""
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .base import DataError

FRED = "https://fred.stlouisfed.org"
DAY = 86_400_000

# id -> (libelle, frequence D/W/M/Q, delai minimal de publication en jours, unite affichee)
SERIES = {
    "CPIAUCSL": ("Prix à la consommation (indice, corrigé des variations saisonnières)", "M", 40, "indice"),
    "CPIAUCNS": ("Prix à la consommation (indice brut)", "M", 40, "indice"),
    "CPILFESL": ("Prix à la consommation hors alimentation et énergie (corrigé)", "M", 40, "indice"),
    "CPILFENS": ("Prix à la consommation hors alimentation et énergie (brut)", "M", 40, "indice"),
    "PCEPI": ("Prix des dépenses de consommation (PCE)", "M", 55, "indice"),
    "PCEPILFE": ("Prix des dépenses de consommation hors alimentation et énergie (PCE sous-jacent)", "M", 55, "indice"),
    "PPIFIS": ("Prix à la production, demande finale", "M", 40, "indice"),
    "PAYEMS": ("Emplois non agricoles (milliers)", "M", 31, "milliers"),
    "UNRATE": ("Taux de chômage", "M", 31, "%"),
    "CES0500000003": ("Salaire horaire moyen du privé", "M", 31, "$"),
    "ICSA": ("Inscriptions hebdomadaires au chômage", "W", 5, "personnes"),
    "JTSJOL": ("Offres d'emploi (enquête JOLTS, milliers)", "M", 60, "milliers"),
    "RSAFS": ("Ventes au détail (millions de dollars)", "M", 44, "M$"),
    "RSFSXMV": ("Ventes au détail hors automobiles (millions de dollars)", "M", 44, "M$"),
    "A191RL1Q225SBEA": ("Croissance du produit intérieur brut réel (rythme annualisé)", "Q", 85, "%"),
    "DFEDTARU": ("Taux directeur de la Fed, borne haute", "D", 0, "%"),
    "DFEDTARL": ("Taux directeur de la Fed, borne basse", "D", 0, "%"),
    "DGS2": ("Taux d'État américain à 2 ans", "D", 1, "%"),
    "DGS10": ("Taux d'État américain à 10 ans", "D", 1, "%"),
    "DFII10": ("Taux réel à 10 ans (après inflation)", "D", 1, "%"),
    "T10YIE": ("Inflation anticipée par le marché sur 10 ans", "D", 1, "%"),
    "DTWEXBGS": ("Dollar face à un large panier de devises (indice)", "D", 3, "indice"),
    "WALCL": ("Bilan de la Fed (millions de dollars)", "W", 1, "M$"),
    "WTREGEN": ("Compte du Trésor à la Fed (millions de dollars)", "W", 1, "M$"),
    "RRPONTSYD": ("Prises en pension inversées de la Fed (milliards de dollars)", "D", 1, "Md$"),
    "M2SL": ("Masse monétaire M2 (milliards de dollars)", "M", 25, "Md$"),
    "BAMLH0A0HYM2": ("Écart de taux des obligations à haut rendement", "D", 1, "%"),
    "VIXCLS": ("Volatilité implicite du S&P 500 (VIX)", "D", 1, "points"),
    "NFCI": ("Conditions financières (Fed de Chicago, > 0 = plus tendues que la moyenne)", "W", 5, "points"),
    "DCOILWTICO": ("Pétrole WTI (dollars le baril)", "D", 3, "$"),
}
START = "2016-01-01"                                              # premier telechargement : de quoi mesurer sur ~10 ans
RECENT_DAYS = 400                                                 # ensuite : seulement la derniere annee (revisions comprises)


def parse_csv(text: str) -> list:
    """CSV FRED (« observation_date,ID » ou « DATE,ID ») -> [(t_ms, valeur)] ; les valeurs manquantes (« . » ou vide) sont ignorees."""
    out = []
    for line in text.splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            d = datetime.strptime(parts[0].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            v = float(parts[1])
        except ValueError:
            continue
        if math.isfinite(v):
            out.append((int(d.timestamp() * 1000), v))
    return out


def merge(old: list, new: list) -> list:
    """Fusion par date d'observation : les nouvelles valeurs (revisions) remplacent les anciennes."""
    d = {int(t): v for t, v in old or []}
    d.update({int(t): v for t, v in new or []})
    return sorted(d.items())


def fetch(sid: str, start: str, base: str = FRED, timeout: float = 25.0) -> list:
    url = f"{base.rstrip('/')}/graph/fredgraph.csv?id={sid}&cosd={start}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Liq Terminal)", "Accept": "text/csv"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise DataError(f"FRED {sid} : HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise DataError(f"FRED injoignable ({type(e).__name__})") from e
    rows = parse_csv(text)
    if not rows and "<html" in text[:300].lower():
        raise DataError(f"FRED {sid} : réponse inattendue (page web au lieu du fichier CSV)")
    return rows


def start_for(existing: list, now_ms: int) -> str:
    if not existing:
        return START
    t = max(int(existing[0][0]), now_ms - RECENT_DAYS * DAY)
    return datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------- series simulees (mode simule et tests) : formes plausibles, deterministes ----------
def _month_starts(start_ms: int, end_ms: int):
    d = datetime.fromtimestamp(start_ms / 1000, timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while d.timestamp() * 1000 <= end_ms:
        yield int(d.timestamp() * 1000)
        d = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)


def simulated(sid: str, now_ms: int, start_ms: int | None = None) -> list:
    """Serie fictive mais coherente (inflation ~3 %, chomage ~4 %, taux ~4 %...), deterministe pour un meme identifiant."""
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(sid))
    wob = lambda i, a=1.0: a * (math.sin(i * 0.37 + seed) * 0.6 + math.sin(i * 0.11 + seed * 0.5) * 0.4)
    origin = int(datetime(2016, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)   # toujours depuis la meme origine : series identiques d'un appel a l'autre
    keep_from = start_ms or origin
    start_ms = origin
    freq, lag = SERIES.get(sid, ("", "D", 1, ""))[1:3]
    end = now_ms - lag * DAY
    if freq == "M":
        ts = list(_month_starts(start_ms, end - 28 * DAY))
    elif freq == "Q":
        ts = [t for t in _month_starts(start_ms, end - 80 * DAY) if datetime.fromtimestamp(t / 1000, timezone.utc).month in (1, 4, 7, 10)]
    elif freq == "W":
        d0 = start_ms // DAY
        ts = list(range((d0 + (2 - d0) % 7) * DAY, end, 7 * DAY))                   # samedis (jour 2 modulo 7 depuis le 1er janvier 1970, un jeudi)
    else:
        ts = [t for t in range(start_ms // DAY * DAY, end, DAY) if (t // DAY + 3) % 7 < 5]
    out = []
    lvl = None
    for i, t in enumerate(ts):
        if sid in ("CPIAUCSL", "CPIAUCNS", "CPILFESL", "CPILFENS", "PCEPI", "PCEPILFE", "PPIFIS"):
            lvl = (lvl or 240.0) * (1 + 0.0025 + wob(i, 0.0012))
        elif sid == "CES0500000003":
            lvl = (lvl or 26.0) * (1 + 0.003 + wob(i, 0.001))
        elif sid in ("PAYEMS",):
            lvl = (lvl or 145_000.0) + 170 + wob(i, 120)
        elif sid in ("RSAFS", "RSFSXMV"):
            lvl = (lvl or 450_000.0) * (1 + 0.003 + wob(i, 0.006))
        elif sid == "M2SL":
            lvl = (lvl or 12_500.0) * (1 + 0.004 + wob(i, 0.003))
        elif sid == "WALCL":
            lvl = (lvl or 4_500_000.0) * (1 + wob(i, 0.004))
        else:
            base = {"UNRATE": 4.2, "ICSA": 225_000, "JTSJOL": 7_600, "A191RL1Q225SBEA": 2.2, "DFEDTARU": 4.5, "DFEDTARL": 4.25, "DGS2": 3.9,
                    "DGS10": 4.2, "DFII10": 1.9, "T10YIE": 2.3, "DTWEXBGS": 121.0, "WTREGEN": 750_000, "RRPONTSYD": 250.0, "BAMLH0A0HYM2": 3.3,
                    "VIXCLS": 16.0, "NFCI": -0.5, "DCOILWTICO": 72.0}.get(sid, 100.0)
            amp = {"UNRATE": 0.4, "ICSA": 20_000, "JTSJOL": 600, "A191RL1Q225SBEA": 1.5, "DFEDTARU": 0.0, "DFEDTARL": 0.0, "DGS2": 0.5, "DGS10": 0.4,
                   "DFII10": 0.3, "T10YIE": 0.15, "DTWEXBGS": 4.0, "WTREGEN": 120_000, "RRPONTSYD": 150.0, "BAMLH0A0HYM2": 0.6, "VIXCLS": 4.0,
                   "NFCI": 0.15, "DCOILWTICO": 8.0}.get(sid, 5.0)
            lvl = base + wob(i * (0.2 if freq == "D" else 1.0), amp)
            if sid == "RRPONTSYD":
                lvl = max(0.0, lvl)
        out.append((t, round(lvl, 4)))
    return [x for x in out if x[0] >= keep_from]
