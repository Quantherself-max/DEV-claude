"""Mise a jour automatique du terminal depuis GitHub (V11), sans fermer la fenetre.

Principe :
  1. toutes les 30 minutes, le terminal demande a l'API GitHub le dernier commit de la branche suivie (« auto » = la branche la plus recemment mise a jour qui
     contient le terminal) ;
  2. s'il est plus recent que la version installee : telechargement de l'archive, CONTROLES (fichiers essentiels presents, tout le code Python se compile, les modules
     principaux s'importent dans un processus a part), SAUVEGARDE de la version actuelle, remplacement des fichiers ;
  3. le terminal redemarre tout seul (run.py le relance, la page du navigateur se recharge). Si la nouvelle version plante au demarrage, run.py remet la
     sauvegarde en place et relance l'ancienne version.
Ne sont JAMAIS touches : data_local/ (tes donnees, journaux, rapports), .env (tes reglages et jetons), .update/ (sauvegarde). Les lanceurs (.bat / .command) en cours
d'utilisation ne sont pas remplaces pendant que le terminal tourne (Windows lit le .bat au fil de l'eau) : la nouvelle copie attend dans .update/lanceurs/.
Depot public : aucun jeton necessaire (60 requetes par heure, les commits deja vus sont gardes en memoire) ; s'il redevient prive : jeton GitHub en LECTURE SEULE
(Reglages -> Mises a jour), garde dans .env. Bibliotheque standard uniquement."""
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.github.com"
REPO = "Quantherself-max/DEV-claude"
BRANCH = "auto"
SUBDIR = "terminal"
KEEP = {"data_local", ".env", ".update", ".git"}                  # jamais remplaces ni effaces
LAUNCHERS = {"Lancer-Terminal-Windows.bat", "Lancer-Terminal-Mac.command"}
REQUIRED = ("run.py", "server.py", "service.py", "config.py", "updater.py", "web/index.html")
RESTART_CODE = 3                                                 # code de sortie : « relance-moi »
MAX_ZIP = 300 * 1024 * 1024


class UpdateError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):                         # on suit la redirection a la main, SANS renvoyer le jeton a l'hote suivant
        return None


def _skip(rel: str) -> bool:
    parts = rel.split("/")
    return parts[0] in KEEP or "__pycache__" in parts or rel.endswith((".pyc", ".pyo"))


def walk(root: Path) -> list[str]:
    """Fichiers de code (chemins relatifs, separateur /), hors donnees, reglages et caches."""
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if not _skip(rel):
                out.append(rel)
    return out


class Updater:
    def __init__(self, root, repo: str = REPO, branch: str = BRANCH, token: str = "", api: str = API, subdir: str = SUBDIR, timeout: float = 30.0, smoke: bool = True):
        self.root = Path(root).resolve()
        self.repo, self.branch, self.token = repo.strip().strip("/"), (branch or BRANCH).strip(), (token or "").strip()
        self.api, self.subdir, self.timeout, self.smoke = api.rstrip("/"), subdir.strip("/"), timeout, smoke
        self.dir = self.root / ".update"

    # ------------------------------------------------------------ etat local
    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, st: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def installed(self) -> dict:
        st = self.state()
        return {k: st.get(k) for k in ("sha", "branch", "date", "message", "installedAt")}

    def is_git(self) -> bool:
        return (self.root / ".git").exists() or (self.root.parent / ".git").exists()

    def mark_healthy(self) -> None:
        """Appele par le terminal une fois demarre : la nouvelle version tient, la sauvegarde n'a plus a etre restauree automatiquement."""
        st = self.state()
        if st.get("pendingVerify"):
            st["pendingVerify"] = False
            st["healthyAt"] = time.time()
            self._save_state(st)

    # ------------------------------------------------------------ GitHub
    def _req(self, path_or_url: str, auth: bool = True, raw: bool = False):
        url = path_or_url if path_or_url.startswith("http") else f"{self.api}{path_or_url}"
        headers = {"User-Agent": "liq-terminal-updater", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                data = r.read(MAX_ZIP + 1)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            e.close()
            if loc:
                return self._req(loc, auth=False, raw=raw)
            if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
                raise UpdateError("GitHub limite les vérifications sans jeton (60 par heure) : nouvel essai à la prochaine vérification") from e
            if e.code in (401, 403):
                raise UpdateError("GitHub refuse l'accès : jeton absent, expiré ou sans droit de lecture sur le dépôt (Réglages → Mises à jour)") from e
            if e.code == 404:
                raise UpdateError("introuvable sur GitHub : dépôt privé sans jeton, ou nom de dépôt / de branche inexact") from e
            raise UpdateError(f"GitHub a répondu HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise UpdateError(f"GitHub injoignable ({type(e).__name__})") from e
        if len(data) > MAX_ZIP:
            raise UpdateError("archive trop grosse")
        if raw:
            return data
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise UpdateError("réponse GitHub illisible") from e

    # un commit ne change jamais : sa date, son message et la presence du terminal sont gardes sur disque (sans jeton, GitHub n'accepte que 60 requetes par heure)
    def _cache(self) -> dict:
        try:
            return json.loads((self.dir / "commits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _cache_put(self, sha: str, **kw) -> None:
        c = self._cache()
        c[sha] = {**c.get(sha, {}), **kw}
        if len(c) > 300:
            c = dict(list(c.items())[-200:])
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "commits.json").write_text(json.dumps(c), encoding="utf-8")
        except OSError:
            pass

    def _commit(self, sha_or_ref: str) -> dict:
        hit = self._cache().get(sha_or_ref)
        if hit and hit.get("date"):
            return {"sha": sha_or_ref, "date": hit["date"], "message": hit.get("message", "")}
        c = self._req(f"/repos/{self.repo}/commits/{urllib.parse.quote(sha_or_ref, safe='')}")
        cm = c.get("commit") or {}
        out = {"sha": c.get("sha"), "date": (cm.get("committer") or {}).get("date"), "message": (cm.get("message") or "").split("\n")[0][:200]}
        if out["sha"] and out["date"]:
            self._cache_put(out["sha"], date=out["date"], message=out["message"])
        return out

    def _has_terminal(self, ref: str, sha: str | None = None) -> bool:
        hit = self._cache().get(sha) if sha else None
        if hit and "terminal" in hit:
            return hit["terminal"]
        try:
            self._req(f"/repos/{self.repo}/contents/{self.subdir + '/' if self.subdir else ''}run.py?ref={urllib.parse.quote(sha or ref, safe='')}")
            ok = True
        except UpdateError as e:
            if "limite" in str(e) or "injoignable" in str(e):
                raise
            ok = False
        if sha:
            self._cache_put(sha, terminal=ok)
        return ok

    def latest(self) -> dict:
        """Dernier commit de la branche suivie : {sha, date, message, branch}. En mode « auto » : la branche la plus recemment mise a jour qui contient le terminal."""
        if self.branch != "auto":
            c = self._commit(self.branch)
            return {**c, "branch": self.branch}
        branches = self._req(f"/repos/{self.repo}/branches?per_page=100")
        cands = []
        for b in branches if isinstance(branches, list) else []:
            sha = (b.get("commit") or {}).get("sha")
            if sha:
                c = self._commit(sha)
                cands.append({**c, "branch": b.get("name")})
        cands.sort(key=lambda c: c.get("date") or "", reverse=True)
        for c in cands:
            if self._has_terminal(c["branch"], c.get("sha")):
                return c
        raise UpdateError("aucune branche du dépôt ne contient le terminal")

    def check(self) -> dict:
        """{installed, latest, newer} ; ne modifie rien."""
        inst = self.installed()
        lat = self.latest()
        newer = lat.get("sha") != inst.get("sha")
        if newer and inst.get("date") and lat.get("date") and lat["date"] < inst["date"]:
            newer = False                                        # la branche suivie est plus ancienne que ce qui est installe : on ne recule pas
        return {"installed": inst, "latest": lat, "newer": bool(newer and lat.get("sha"))}

    # ------------------------------------------------------------ installation
    def _stage(self, data: bytes) -> Path:
        stage = self.dir / "staging"
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        try:
            zf = zipfile.ZipFile(__import__("io").BytesIO(data))
        except zipfile.BadZipFile as e:
            raise UpdateError("archive GitHub illisible") from e
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise UpdateError("archive vide")
        top = names[0].split("/")[0]
        prefix = f"{top}/{self.subdir}/" if self.subdir else f"{top}/"
        total = 0
        for info in zf.infolist():
            n = info.filename
            if info.is_dir() or not n.startswith(prefix):
                continue
            rel = n[len(prefix):]
            parts = rel.split("/")
            if not rel or rel.startswith("/") or ".." in parts or ":" in parts[0]:
                raise UpdateError(f"chemin refusé dans l'archive : {n}")
            total += info.file_size
            if total > MAX_ZIP:
                raise UpdateError("archive trop grosse une fois décompressée")
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        return stage

    def verify(self, stage: Path) -> None:
        """Leve UpdateError si la nouvelle version est incomplete, ne se compile pas ou ne s'importe pas."""
        miss = [r for r in REQUIRED if not (stage / r).is_file()]
        if miss:
            raise UpdateError("version incomplète (manque : " + ", ".join(miss) + ")")
        errs = []
        with tempfile.TemporaryDirectory() as tmp:
            for p in stage.rglob("*.py"):
                try:
                    py_compile.compile(str(p), cfile=os.path.join(tmp, "x.pyc"), doraise=True)
                except py_compile.PyCompileError as e:
                    errs.append(f"{p.relative_to(stage).as_posix()} : {str(e.msg).strip().splitlines()[-1][:120]}")
        if errs:
            raise UpdateError("le code de la nouvelle version ne se compile pas : " + " ; ".join(errs[:3]))
        if self.smoke:
            code = "import sys; sys.path.insert(0, sys.argv[1]); import config, updater, server, service"
            try:
                r = subprocess.run([sys.executable, "-c", code, str(stage)], cwd=str(stage), capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired as e:
                raise UpdateError("la nouvelle version ne démarre pas (délai dépassé)") from e
            if r.returncode != 0:
                last = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["erreur inconnue"]
                raise UpdateError("la nouvelle version ne démarre pas : " + last[0][:200])

    def _backup(self) -> list[str]:
        bk = self.dir / "backup"
        if bk.exists():
            shutil.rmtree(bk, ignore_errors=True)
        files = walk(self.root)
        for rel in files:
            dest = bk / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / rel, dest)
        (self.dir / "backup.json").write_text(json.dumps({"files": files, "state": self.state()}, ensure_ascii=False), encoding="utf-8")
        return files

    def _write(self, rel: str, src: Path) -> None:
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp-update")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)

    def apply(self, target: dict | None = None) -> dict:
        """Installe `target` (resultat de latest()) ou le dernier commit. Renvoie {changed: [...], removed: [...], launchers: [...], sha, restart}."""
        if self.is_git():
            raise UpdateError("dossier géré par git : mets-le à jour avec « git pull » (la mise à jour automatique ne touche pas un dépôt git)")
        target = target or self.latest()
        sha = target.get("sha")
        if not sha:
            raise UpdateError("version cible inconnue")
        data = self._req(f"/repos/{self.repo}/zipball/{sha}", raw=True)
        stage = self._stage(data)
        try:
            self.verify(stage)
            new_files = walk(stage)
            old_state = self.state()
            old_manifest = set(old_state.get("files") or [])
            changed, launchers = [], []
            for rel in new_files:
                cur = self.root / rel
                if cur.is_file() and cur.read_bytes() == (stage / rel).read_bytes():
                    continue
                changed.append(rel)
            removed = sorted(r for r in old_manifest - set(new_files) if not _skip(r) and (self.root / r).is_file())
            base = {k: target.get(k) for k in ("sha", "branch", "date", "message")}
            if not changed and not removed:
                self._save_state({**old_state, **base, "installedAt": old_state.get("installedAt") or time.time(), "files": new_files, "pendingVerify": False})
                return {"changed": [], "removed": [], "launchers": [], "sha": sha, "restart": False}
            self._backup()
            done = []
            try:
                for rel in changed:
                    if rel in LAUNCHERS and (self.root / rel).exists():
                        dest = self.dir / "lanceurs" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(stage / rel, dest)
                        launchers.append(rel)
                        continue
                    self._write(rel, stage / rel)
                    done.append(rel)
                for rel in removed:
                    (self.root / rel).unlink()
            except OSError as e:
                self.rollback()
                raise UpdateError(f"remplacement impossible ({type(e).__name__} sur {rel}) : ancienne version remise en place") from e
            self._save_state({**base, "installedAt": time.time(), "files": new_files, "pendingVerify": True, "previous": {k: old_state.get(k) for k in ("sha", "branch", "date", "message")}})
            return {"changed": done, "removed": removed, "launchers": launchers, "sha": sha, "restart": bool(done or removed)}
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def rollback(self) -> bool:
        """Remet la sauvegarde (version precedente) en place. False s'il n'y a pas de sauvegarde."""
        meta = self.dir / "backup.json"
        bk = self.dir / "backup"
        if not meta.exists() or not bk.exists():
            return False
        info = json.loads(meta.read_text(encoding="utf-8"))
        files = set(info.get("files") or [])
        for rel in walk(self.root):                                  # fichiers ajoutes par la version fautive
            if rel not in files and rel not in LAUNCHERS:
                try:
                    (self.root / rel).unlink()
                except OSError:
                    pass
        for rel in files:
            src = bk / rel
            if src.is_file() and rel not in LAUNCHERS:
                self._write(rel, src)
        prev = info.get("state") or {}
        bad = self.state()
        self._save_state({**prev, "pendingVerify": False, "rolledBack": {"sha": bad.get("sha"), "at": time.time()}})
        return True
