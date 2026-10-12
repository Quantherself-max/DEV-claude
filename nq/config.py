"""Configuration : variables d'environnement `NQ_*`, completees par un fichier `.env` (voir config.example.env)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read_text(path: Path) -> str:
    """Texte d'un fichier de reglages ecrit a la main : UTF-8 avec ou sans BOM (Bloc-notes de Windows), sinon Windows-1252."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _load_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in _read_text(path).splitlines():
            line = line.strip().lstrip("﻿")
            if line.startswith("export "):
                line = line[7:].lstrip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def env_sources(env_path: Path) -> list:
    """« .env.txt » (Windows cache les extensions : un « .env » cree avec le Bloc-notes devient « .env.txt »), puis « .env », qui l'emporte."""
    p = Path(env_path)
    return [f for f in (p.with_name(p.name + ".txt"), p) if f.is_file()]


@dataclass
class Config:
    source: str = "simulated"        # simulated = prix FICTIFS (essai) | csv = transactions lues dans un fichier (voir README)
    instrument: str = "NQ"           # instrument du graphique : NQ | MNQ | ES | MES
    host: str = "127.0.0.1"          # local uniquement : le terminal n'est pas expose sur le reseau
    port: int = 8766                 # (le terminal crypto est sur 8765 : les deux peuvent tourner en meme temps)
    refresh_seconds: float = 1.0     # frequence de lecture de la source
    display_tz: str = "paris"        # fuseau des heures affichees : paris | et
    big_lot: int = 0                 # taille d'un « gros ordre » (0 = valeur par defaut de l'instrument)
    zone_pts: float = 6.0            # largeur d'une zone de confluence, en points
    sim_days: int = 4                # jours de donnees simulees
    sim_start: str = ""              # heure de depart de la simulation (« 2026-10-12T15:40:00Z », UTC) : le temps avance ensuite normalement. Vide = maintenant.
    csv_path: str = ""
    csv_tz: str = "utc"              # fuseau des heures SANS indication du fichier : utc | et | paris
    csv_columns: str = ""            # colonnes si le fichier n'a pas d'en-tete : « time,price,size,side »
    csv_buy_codes: tuple = ()        # valeurs de la colonne « cote » qui veulent dire acheteur agressif (si ce n'est pas B / buy / ask)
    csv_sell_codes: tuple = ()
    data_dir: str = str(ROOT / "data_local")


def _flag(v) -> bool:
    return str(v).lower() not in ("0", "false", "non", "no", "")


def load_config(env_path: Path | None = None) -> Config:
    env = {}
    for f in env_sources(env_path or ROOT / ".env"):
        env.update(_load_env_file(f))
    env.update({k: v for k, v in os.environ.items() if k.startswith("NQ_") and v.strip()})      # variables du systeme : elles l'emportent
    c = Config()
    g = env.get
    c.source = g("NQ_SOURCE", c.source).lower()
    c.instrument = g("NQ_INSTRUMENT", c.instrument).upper()
    c.host = g("NQ_HOST", c.host)
    c.port = int(g("NQ_PORT", c.port))
    c.refresh_seconds = max(0.2, float(g("NQ_REFRESH_SECONDS", c.refresh_seconds)))
    c.display_tz = "et" if g("NQ_DISPLAY_TZ", c.display_tz).lower() in ("et", "ny", "newyork") else "paris"
    c.big_lot = max(0, int(float(g("NQ_BIG_LOT", c.big_lot))))
    c.zone_pts = max(1.0, float(g("NQ_ZONE_PTS", c.zone_pts)))
    c.sim_days = max(2, min(8, int(float(g("NQ_SIM_DAYS", c.sim_days)))))
    c.sim_start = g("NQ_SIM_START", c.sim_start)
    c.csv_path = g("NQ_CSV_PATH", c.csv_path)
    c.csv_tz = g("NQ_CSV_TZ", c.csv_tz).lower()
    c.csv_columns = g("NQ_CSV_COLUMNS", c.csv_columns)
    c.csv_buy_codes = tuple(x.strip() for x in g("NQ_CSV_BUY_CODES", "").split(",") if x.strip())
    c.csv_sell_codes = tuple(x.strip() for x in g("NQ_CSV_SELL_CODES", "").split(",") if x.strip())
    c.data_dir = g("NQ_DATA_DIR", c.data_dir)
    return c


def validate(c: Config) -> list:
    """Problemes de configuration, en francais ([] si tout va bien)."""
    from engine.instruments import INSTRUMENTS
    bad = []
    if c.source not in ("simulated", "csv"):
        bad.append(f"NQ_SOURCE « {c.source} » inconnue : simulated ou csv.")
    if c.instrument not in INSTRUMENTS:
        bad.append(f"NQ_INSTRUMENT « {c.instrument} » inconnu : {', '.join(INSTRUMENTS)}.")
    if c.source == "csv" and not c.csv_path:
        bad.append("NQ_SOURCE=csv demande NQ_CSV_PATH (le chemin du fichier de transactions).")
    if c.sim_start:
        try:
            from datetime import datetime
            datetime.fromisoformat(c.sim_start.replace("Z", "+00:00"))
        except ValueError:
            bad.append(f"NQ_SIM_START « {c.sim_start} » illisible : écris par exemple 2026-10-12T15:40:00Z (heure UTC).")
    if c.csv_tz not in ("utc", "et", "paris"):
        bad.append(f"NQ_CSV_TZ « {c.csv_tz} » inconnu : utc, et ou paris.")
    return bad
