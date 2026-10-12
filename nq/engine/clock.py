"""Horloge du marche : heure de New York (ET) et de Paris, sans base de fuseaux, et sessions du CME.

Pourquoi sans `zoneinfo` : sous Windows, Python n'a pas de base de fuseaux horaires (il faudrait installer `tzdata`). Les regles de
l'heure d'ete sont simples et fixes, on les code donc ici et on les teste :
  - Etats-Unis : du 2e dimanche de mars (2 h) au 1er dimanche de novembre (2 h) ;
  - Europe     : du dernier dimanche de mars (1 h UTC) au dernier dimanche d'octobre (1 h UTC).
Attention : pendant 2 a 3 semaines par an (mars et fin octobre / debut novembre) les deux changements ne tombent pas le meme jour, et
l'ouverture de New York (9 h 30 ET) n'est plus a 15 h 30 a Paris mais a 14 h 30. Tout est donc calcule, jamais « 15 h 30 en dur ».

Journee de trading du CME (indices actions) : ouverture le dimanche soir a 18 h ET, pause de 17 h a 18 h ET du lundi au jeudi, fermeture le
vendredi a 17 h ET. La « journee de trading » porte la date de sa CLOTURE (le dimanche 18 h ET appartient a la journee du lundi).
Les jours feries de bourse ne sont pas geres (a ajouter a partir d'un calendrier). Module PUR."""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

SEC = 1000
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000

TZ_LABEL = {"et": "New York", "paris": "Paris"}


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int:
    """Jour du mois du n-ieme `weekday` (lundi = 0 ... dimanche = 6)."""
    first = date(year, month, 1)
    return 1 + (weekday - first.weekday()) % 7 + 7 * (n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> int:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last.day - (last.weekday() - weekday) % 7


def us_dst(utc_ms: int) -> bool:
    y = _utc(utc_ms).year
    start = datetime(y, 3, _nth_weekday(y, 3, 6, 2), 7, 0, tzinfo=timezone.utc)      # 2 h EST = 7 h UTC
    end = datetime(y, 11, _nth_weekday(y, 11, 6, 1), 6, 0, tzinfo=timezone.utc)       # 2 h EDT = 6 h UTC
    return start <= _utc(utc_ms) < end


def eu_dst(utc_ms: int) -> bool:
    y = _utc(utc_ms).year
    start = datetime(y, 3, _last_weekday(y, 3, 6), 1, 0, tzinfo=timezone.utc)
    end = datetime(y, 10, _last_weekday(y, 10, 6), 1, 0, tzinfo=timezone.utc)
    return start <= _utc(utc_ms) < end


def et_offset(utc_ms: int) -> int:
    return -4 * HOUR if us_dst(utc_ms) else -5 * HOUR


def paris_offset(utc_ms: int) -> int:
    return 2 * HOUR if eu_dst(utc_ms) else HOUR


def wall(utc_ms: int, tz: str = "et") -> datetime:
    """Heure murale (datetime sans fuseau) a New York (`et`) ou Paris (`paris`)."""
    off = et_offset(utc_ms) if tz == "et" else paris_offset(utc_ms)
    return datetime.fromtimestamp((utc_ms + off) / 1000.0, timezone.utc).replace(tzinfo=None)


def et(utc_ms: int) -> datetime:
    return wall(utc_ms, "et")


def et_to_utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """Heure murale de New York -> ms UTC (a l'heure du changement, la premiere heure valide est retenue)."""
    guess = int(datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp() * 1000)
    for off in (-4 * HOUR, -5 * HOUR):
        cand = guess - off
        if et_offset(cand) == off:
            return cand
    return guess + 5 * HOUR


def wall_to_utc(w: datetime, tz: str = "utc") -> int:
    """Heure murale (datetime sans fuseau) a New York (`et`), Paris (`paris`) ou en UTC (`utc`) -> ms UTC.
    Heure ambigue (changement d'heure d'automne) : la premiere occurrence est retenue."""
    guess = int(w.replace(tzinfo=timezone.utc).timestamp() * 1000)
    if tz == "utc":
        return guess
    fn = et_offset if tz == "et" else paris_offset
    for off in ((-4 * HOUR, -5 * HOUR) if tz == "et" else (2 * HOUR, HOUR)):
        cand = guess - off
        if fn(cand) == off:
            return cand
    return guess - fn(guess)


def fmt_hm(utc_ms: int, tz: str = "paris") -> str:
    w = wall(utc_ms, tz)
    return f"{w.hour:02d}:{w.minute:02d}"


def fmt_hms(utc_ms: int, tz: str = "paris") -> str:
    w = wall(utc_ms, tz)
    return f"{w.hour:02d}:{w.minute:02d}:{w.second:02d}"


# ---------- ouverture du marche et journee de trading ----------
def is_open(utc_ms: int) -> bool:
    """Globex indices actions : dimanche 18 h ET -> vendredi 17 h ET, pause 17 h - 18 h ET du lundi au jeudi. Jours feries non geres."""
    w = et(utc_ms)
    wd, tod = w.weekday(), w.hour * 60 + w.minute
    if wd == 5:                                   # samedi
        return False
    if wd == 6:                                   # dimanche : ouvert a partir de 18 h
        return tod >= 18 * 60
    if wd == 4:                                   # vendredi : ferme a 17 h
        return tod < 17 * 60
    return not (17 * 60 <= tod < 18 * 60)


def trading_day(utc_ms: int) -> str:
    """Date (AAAA-MM-JJ) de la journee de trading : celle de la cloture de 17 h ET. Dimanche 18 h ET -> lundi."""
    w = et(utc_ms)
    d = w.date() + (timedelta(days=1) if w.hour >= 18 else timedelta(0))
    return d.isoformat()


def prev_day(day: str) -> str:
    """Journee de trading precedente (le week-end est saute ; jours feries ignores)."""
    d = date.fromisoformat(day) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def next_day(day: str) -> str:
    d = date.fromisoformat(day) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


# (jour relatif a la journee de trading, heure, minute) : debut, fin. « -1 » = la veille calendaire (le dimanche pour le lundi).
WINDOWS = {
    "globex": ((-1, 18, 0), (0, 17, 0)),     # toute la journee de trading
    "asia": ((-1, 18, 0), (0, 3, 0)),
    "london": ((0, 3, 0), (0, 8, 0)),
    "pre": ((0, 8, 0), (0, 9, 30)),          # pre-ouverture US (annonces de 8 h 30)
    "on": ((-1, 18, 0), (0, 9, 30)),         # « overnight » : tout ce qui precede l'ouverture US
    "rth": ((0, 9, 30), (0, 16, 0)),         # seance reguliere
    "ib": ((0, 9, 30), (0, 10, 30)),         # « initial balance » : la premiere heure
    "post": ((0, 16, 0), (0, 17, 0)),
}


@lru_cache(maxsize=1024)
def window(day: str, name: str) -> tuple:
    """(debut, fin) en ms UTC de la fenetre `name` de la journee de trading `day`."""
    d0 = date.fromisoformat(day)
    out = []
    for rel, hh, mm in WINDOWS[name]:
        d = d0 + timedelta(days=rel)
        out.append(et_to_utc(d.year, d.month, d.day, hh, mm))
    return out[0], out[1]


FORCED_FLAT = (16, 45)          # comptes de simulation Lucid : positions fermees d'office a 16 h 45 ET (avant, les jours de seance raccourcie)


def forced_flat(day: str) -> int:
    """Instant (ms UTC) de la fermeture forcee des positions Lucid pour la journee de trading `day`."""
    y, m, d = (int(x) for x in day.split("-"))
    return et_to_utc(y, m, d, *FORCED_FLAT)


# ---------- phases de la journee (pour l'affichage et le contexte) ----------
PHASES = (            # (debut en minutes ET, cle, libelle)
    (3 * 60, "london", "Londres"),
    (8 * 60, "pre", "Pré-ouverture US"),
    (9 * 60 + 30, "open", "Ouverture US (IB)"),
    (10 * 60 + 30, "am", "Matinée US"),
    (11 * 60 + 30, "lunch", "Creux de midi"),
    (13 * 60 + 30, "pm", "Après-midi US"),
    (15 * 60, "power", "Dernière heure"),
    (16 * 60, "post", "Après la clôture US"),
    (17 * 60, "break", "Pause quotidienne"),
    (18 * 60, "asia", "Asie"),
)


def phase(utc_ms: int) -> dict:
    """Phase en cours : {key, label, rth, open}. `rth` = seance reguliere americaine (9 h 30 - 16 h ET)."""
    if not is_open(utc_ms):
        w = et(utc_ms)
        brk = w.weekday() < 4 and 17 * 60 <= w.hour * 60 + w.minute < 18 * 60
        return {"key": "break" if brk else "closed", "label": "Pause quotidienne" if brk else "Marché fermé", "rth": False, "open": False}
    w = et(utc_ms)
    tod = w.hour * 60 + w.minute
    key, label = "asia", "Asie"
    for start, k, lab in PHASES:
        if tod >= start:
            key, label = k, lab
    return {"key": key, "label": label, "rth": 9 * 60 + 30 <= tod < 16 * 60, "open": True}


KEY_MARKS = (          # moments qui comptent pour un scalpeur NQ (heure ET)
    (3 * 60, "Ouverture de Londres"),
    (8 * 60 + 30, "Annonces US de 8 h 30"),
    (9 * 60 + 30, "Ouverture de New York"),
    (10 * 60, "Annonces US de 10 h"),
    (10 * 60 + 30, "Fin de l'initial balance"),
    (11 * 60 + 30, "Début du creux de midi"),
    (13 * 60 + 30, "Reprise de l'après-midi"),
    (14 * 60, "Annonces / Fed de 14 h"),
    (15 * 60, "Dernière heure"),
    (16 * 60, "Clôture de New York"),
    (16 * 60 + 45, "Fermeture forcée des comptes Lucid (16 h 45 ET)"),
    (17 * 60, "Pause quotidienne"),
    (18 * 60, "Réouverture Globex"),
)


def next_marks(utc_ms: int, n: int = 3) -> list:
    """Les n prochains moments cles [(libelle, ms UTC)]. Un repere compte si le marche est ouvert a cet instant (ou juste avant, pour la
    pause de 17 h) ; le vendredi 17 h devient « Fermeture du week-end »."""
    out = []
    d0 = et(utc_ms).date()
    for add in range(0, 6):
        d = d0 + timedelta(days=add)
        for tod, lab in KEY_MARKS:
            t = et_to_utc(d.year, d.month, d.day, tod // 60, tod % 60)
            if t <= utc_ms or not (is_open(t) or is_open(t - 1)):
                continue
            if tod == 17 * 60 and d.weekday() == 4:
                lab = "Fermeture du week-end"
            out.append((lab, t))
    out.sort(key=lambda x: x[1])
    return out[:n]
