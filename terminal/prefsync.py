"""V36 : les MEMES REGLAGES sur tous tes ordinateurs (PC fixe, Mac...).

Deux parties sont gardees, chacune avec l'heure de sa derniere modification et l'ordinateur qui l'a faite :
- « ui » : tout ce que la page garde dans le navigateur (onglets et leur ordre, elements de chaque graphique, unites de temps, vues,
  TPO fusionnes, grille multi-unites, style...) ;
- « env » : les reglages du terminal (fichier .env) SAUF les secrets (tokens, cles, mots de passe, Telegram) et ce qui est propre a
  l'ordinateur (dossier des donnees, port, dossier de synchronisation).
Copie 1 : dans le dossier des donnees (le navigateur peut etre vide ou change, rien n'est perdu). Copie 2, facultative : dans un
dossier synchronise par ton cloud (iCloud Drive, Google Drive, OneDrive, Dropbox), choisi dans les Reglages sur chaque ordinateur.
La version la plus recente gagne. Aucun secret n'est ecrit dans le cloud."""
from __future__ import annotations
import glob
import json
import os
import re
import secrets
import socket
import time
from pathlib import Path

FILE = "reglages.json"
SUB = "LiqTerminal"                                       # sous-dossier cree dans le dossier synchronise
MAX_BYTES = 1_000_000
SKIP_RE = re.compile(r"TOKEN|KEY|SECRET|PASS|BEARER", re.I)
LOCAL_KEYS = {"TERMINAL_DATA_DIR", "TERMINAL_PORT", "TERMINAL_HOST", "TERMINAL_SYNC_DIR"}


def env_shareable(key: str) -> bool:
    """Reglage du .env recopie sur les autres ordinateurs : les TERMINAL_* sans secret ni chemin propre a la machine."""
    return key.startswith("TERMINAL_") and key not in LOCAL_KEYS and not SKIP_RE.search(key)


def read_env(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if env_shareable(k.strip()):
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def cloud_dirs(home: Path | None = None, environ=None) -> list:
    """Dossiers synchronises trouves sur cet ordinateur : [{label, path}] (Mac et Windows)."""
    home = Path(home or Path.home())
    env = os.environ if environ is None else environ
    found, seen = [], set()

    def add(label, p):
        p = Path(p)
        try:
            if p.is_dir() and str(p) not in seen:
                seen.add(str(p))
                found.append({"label": label, "path": str(p)})
        except OSError:
            pass

    add("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs")       # Mac
    add("iCloud Drive", home / "iCloudDrive")                                                    # Windows
    for p in sorted(glob.glob(str(home / "Library" / "CloudStorage" / "GoogleDrive-*"))):        # Mac
        for sub in ("My Drive", "Mon Drive"):
            add("Google Drive", Path(p) / sub)
    for p in [home / "Google Drive", home / "My Drive"] + [Path(f"{d}:/") / s for d in "GHIJ" for s in ("My Drive", "Mon Drive")]:
        add("Google Drive", p)                                                                   # Windows
    for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if env.get(k):
            add("OneDrive", env[k])
    for p in sorted(glob.glob(str(home / "Library" / "CloudStorage" / "OneDrive*"))) + [str(home / "OneDrive")]:
        add("OneDrive", p)
    for p in [home / "Dropbox", home / "Library" / "CloudStorage" / "Dropbox"]:
        add("Dropbox", p)
    return found


class PrefSync:
    def __init__(self, data_dir, env_path: Path, sync_dir: str = ""):
        self.local = Path(data_dir) / "prefs.json"
        self.env_path = Path(env_path)
        self.sync_dir = (sync_dir or "").strip()
        self.error = None
        self.device = self._device(Path(data_dir) / "device.txt")

    @staticmethod
    def _device(p: Path) -> str:
        """Nom de cet ordinateur (pour dire d'ou vient la derniere modification)."""
        try:
            d = p.read_text(encoding="utf-8").strip()
            if d:
                return d[:60]
        except OSError:
            pass
        host = re.sub(r"[^A-Za-z0-9 ._-]", "", socket.gethostname() or "")[:40] or "ordinateur"
        d = f"{host}-{secrets.token_hex(2)}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(d, encoding="utf-8")
        except OSError:
            pass
        return d

    def cloud_file(self) -> Path | None:
        return Path(self.sync_dir) / SUB / FILE if self.sync_dir else None

    @staticmethod
    def _read(p: Path | None) -> dict:
        if p is None:
            return {}
        try:
            if p.stat().st_size > MAX_BYTES:
                return {}
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write(p: Path, doc: dict) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, p)                                   # ecriture d'un seul coup : le cloud ne voit jamais un fichier a moitie ecrit

    def _docs(self):
        return self._read(self.local), self._read(self.cloud_file())

    @staticmethod
    def _newest(a: dict, b: dict, part: str):
        x, y = a.get(part), b.get(part)
        ok = lambda v: isinstance(v, dict) and isinstance(v.get("t"), (int, float)) and isinstance(v.get("data"), dict)
        x, y = (x if ok(x) else None), (y if ok(y) else None)
        if x and y:
            return x if x["t"] >= y["t"] else y
        return x or y

    def newest(self, part: str):
        loc, cl = self._docs()
        return self._newest(loc, cl, part)

    def put(self, part: str, data: dict, t: float | None = None) -> dict:
        """Enregistre une partie (« ui » ou « env ») dans les deux copies, si elle est plus recente que ce qui y est deja."""
        if len(json.dumps(data)) > MAX_BYTES // 2:
            raise ValueError("réglages trop volumineux")
        t = float(t if t is not None else time.time() * 1000)
        entry = {"t": t, "from": self.device, "data": data}
        cur = self.newest(part)
        if cur and cur["t"] > t:                                 # une version plus recente existe deja (autre ordinateur) : on la garde
            return cur
        self._save(part, entry)
        return entry

    def _save(self, part: str, entry: dict) -> None:
        loc = self._read(self.local)
        loc[part] = entry
        loc["v"] = 1
        self._write(self.local, loc)
        cf = self.cloud_file()
        if cf is None:
            return
        try:
            cl = self._read(cf)
            cl[part] = entry
            cl["v"] = 1
            self._write(cf, cl)
            self.error = None
        except OSError as e:
            self.error = f"dossier synchronisé inaccessible : {e.strerror or e}"

    def align(self) -> None:
        """Les deux copies prennent la version la plus recente de chaque partie (apres le choix d'un dossier, au demarrage)."""
        loc, cl = self._docs()
        for part in ("ui", "env"):
            best = self._newest(loc, cl, part)
            if best and (loc.get(part) != best or (self.cloud_file() and cl.get(part) != best)):
                self._save(part, best)

    def push_env(self) -> None:
        """Apres un changement des Reglages sur cet ordinateur : les reglages sans secret partent vers les autres."""
        self.put("env", read_env(self.env_path))

    def env_to_apply(self) -> dict | None:
        """Reglages venus d'un AUTRE ordinateur et differents des notres (None sinon)."""
        best = self.newest("env")
        if not best or best.get("from") == self.device:
            return None
        mine = read_env(self.env_path)
        upd = {k: str(v) for k, v in best["data"].items() if env_shareable(k) and mine.get(k) != str(v) and "\n" not in str(v)}
        return upd or None

    def status(self) -> dict:
        ui, env = self.newest("ui"), self.newest("env")
        cf = self.cloud_file()
        ok = bool(cf) and cf.parent.parent.is_dir()
        meta = lambda e: {"t": e["t"], "from": e.get("from"), "mine": e.get("from") == self.device} if e else None
        return {"device": self.device, "syncDir": self.sync_dir, "syncOk": ok, "syncFile": str(cf) if cf else None,
                "error": self.error if self.sync_dir else None, "ui": meta(ui), "env": meta(env), "candidates": cloud_dirs()}
