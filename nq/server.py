"""Serveur local (bibliotheque standard uniquement) : API JSON et fichiers statiques de web/.
Securite : n'ecoute que sur 127.0.0.1, refuse les en-tetes Host etrangers (DNS rebinding) et exige un jeton de session sur toutes les requetes qui
modifient quelque chose (un autre site ne peut pas le lire : pas d'en-tete CORS)."""
import json
import logging
import mimetypes
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from engine.account import AccountError
from service import VERSION, Service

WEB = Path(__file__).resolve().parent / "web"
API_LEVEL = 1
MAX_BODY = 64 * 1024
log = logging.getLogger("nq")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8"}


class App:
    def __init__(self, cfg, service: Service | None = None):
        self.cfg = cfg
        self.service = service or Service(cfg)
        self.token = secrets.token_hex(16)
        self.boot = secrets.token_hex(4)                 # change a chaque demarrage : la page ouverte se recharge toute seule
        self.started = time.time()
        self.httpd = None

    def start(self):
        self.service.start()

    def shutdown(self):
        self.service.shutdown()


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _num(q: dict, key: str, default=None, cast=float):
    v = q.get(key, [None])[0]
    if v in (None, ""):
        return default
    try:
        return cast(v)
    except ValueError:
        raise ApiError(400, f"paramètre « {key} » invalide : {v}") from None


def route_get(app: App, path: str, q: dict):
    s = app.service
    one = lambda k, d=None: q.get(k, [d])[0]
    if path == "/api/health":
        return {"ok": True, "version": VERSION, "api": API_LEVEL, "boot": app.boot, "root": str(Path(__file__).resolve().parent),
                "uptime": round(time.time() - app.started)}
    if path == "/api/config":
        return dict(s.config_view(), token=app.token, boot=app.boot, api=API_LEVEL)
    if path == "/api/state":
        return dict(s.state(), boot=app.boot)
    if path == "/api/bars":
        try:
            return s.bars(one("tf", "1m"), _num(q, "limit", 500, int), _num(q, "since", None, int))
        except ValueError as e:
            raise ApiError(400, str(e)) from None
    if path == "/api/profile":
        return s.profile(one("which", "rth"), _num(q, "rows", None, int))
    if path == "/api/footprint":
        try:
            return s.footprint(one("tf", "5m"), _num(q, "n", 2, int), _num(q, "ratio", 3.0), _num(q, "min", 5.0))
        except ValueError as e:
            raise ApiError(400, str(e)) from None
    if path == "/api/levels":
        return s.levels()
    if path == "/api/context":
        return s.context(one("pos"))
    if path == "/api/account":
        return s.account_view(one("pos"))
    if path == "/api/account/perf":
        return s.account.perf()
    if path == "/api/plan":
        try:
            targets = [x for x in (one("targets") or "").split(",") if x.strip()]
            return s.plan(one("side", "long"), _num(q, "entry"), _num(q, "stop"), targets, one("root"), one("risk"), one("pos"))
        except (ValueError, TypeError) as e:
            raise ApiError(400, str(e) if str(e) else "paramètres du plan invalides") from None
    return None


def route_post(app: App, path: str, body: dict):
    s = app.service
    a = s.account
    try:
        if path == "/api/account/trade":
            return a.add_trade(body.get("inst", s.inst.root), body.get("side"), body.get("qty"), body.get("entry"), body.get("exit"), body.get("t"),
                               body.get("fees"), body.get("setup", ""), body.get("note", ""))
        if path == "/api/account/adjust":
            return a.add_adjust(body.get("day"), body.get("net"), body.get("note", ""))
        if path == "/api/account/undo":
            return {"undone": a.undo()}
        if path == "/api/account/delete":
            return {"deleted": a.delete(int(body.get("id", 0)))}
        if path == "/api/account/reset":
            if body.get("confirm") is not True:
                raise ApiError(400, "confirmation requise")
            return {"erased": a.reset()}
        if path == "/api/account/profile":
            return a.set_profile(body.get("changes") or {}).to_dict()
        if path == "/api/test/file":
            return s.test_file(str(body.get("path", "")))
    except AccountError as e:
        raise ApiError(400, str(e)) from None
    except (ValueError, TypeError) as e:
        raise ApiError(400, str(e)) from None
    return None


def make_handler(app: App):
    port_hosts = lambda: {f"127.0.0.1:{app.cfg.port}", f"localhost:{app.cfg.port}", f"[::1]:{app.cfg.port}", "127.0.0.1", "localhost"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "NQTerminal/" + VERSION
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):                # silence : la fenetre noire reste lisible
            pass

        def _host_ok(self) -> bool:
            hosts = port_hosts()
            if app.httpd is not None and app.httpd.server_address[1] != app.cfg.port:    # port 0 (tests) : on accepte le port reel
                hosts |= {f"127.0.0.1:{app.httpd.server_address[1]}", f"localhost:{app.httpd.server_address[1]}"}
            return (self.headers.get("Host") or "") in hosts

        def _send(self, status: int, data: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if self.close_connection:
                self.send_header("Connection", "close")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, obj):
            self._send(status, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8")

        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            f = (WEB / rel).resolve()
            if WEB.resolve() not in f.parents or not f.is_file():           # ni sortie du dossier web/ (« ../ »), ni dossier
                return self._json(404, {"error": "introuvable"})
            ctype = MIME.get(f.suffix.lower()) or mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            self._send(200, f.read_bytes(), ctype)

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "hôte refusé"})
            u = urlparse(self.path)
            try:
                if u.path.startswith("/api/"):
                    res = route_get(app, u.path, parse_qs(u.query))
                    return self._json(200, res) if res is not None else self._json(404, {"error": "adresse inconnue"})
                self._static(u.path)
            except ApiError as e:
                self._json(e.status, {"error": e.msg})
            except Exception:
                log.exception("GET %s", self.path)
                self._json(500, {"error": "erreur interne (voir la fenêtre noire du terminal)"})

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:                          # corps refuse sans le lire : on ferme la connexion plutot que de le laisser se melanger a la requete suivante
                self.close_connection = True
                return self._json(413 if n > MAX_BODY else 400, {"error": "requête trop grande ou invalide"})
            raw = self.rfile.read(n) if n else b""            # toujours lu en entier, meme si la requete est refusee ensuite (connexion reutilisee par le navigateur)
            if not self._host_ok():
                return self._json(403, {"error": "hôte refusé"})
            if self.headers.get("X-NQ-Token") != app.token:
                return self._json(403, {"error": "jeton invalide : recharge la page"})
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ApiError(400, "corps JSON attendu : un objet")
                res = route_post(app, urlparse(self.path).path, body)
                self._json(200, res) if res is not None else self._json(404, {"error": "adresse inconnue"})
            except ApiError as e:
                self._json(e.status, {"error": e.msg})
            except json.JSONDecodeError:
                self._json(400, {"error": "JSON invalide"})
            except Exception:
                log.exception("POST %s", self.path)
                self._json(500, {"error": "erreur interne (voir la fenêtre noire du terminal)"})

    return Handler


def serve(app: App, port: int | None = None) -> ThreadingHTTPServer:
    class Srv(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = False                       # port deja pris -> erreur claire plutot qu'un deuxieme terminal silencieux

        def handle_error(self, request, client_address):
            if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):      # le navigateur a ferme l'onglet ou coupe une requete : normal
                return
            super().handle_error(request, client_address)

    httpd = Srv((app.cfg.host, app.cfg.port if port is None else port), make_handler(app))
    app.httpd = httpd
    return httpd


def serve_in_thread(app: App, port: int = 0):
    httpd = serve(app, port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t
