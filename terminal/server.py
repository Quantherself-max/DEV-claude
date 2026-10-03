"""Serveur local (bibliotheque standard uniquement) : API JSON + fichiers statiques de web/."""
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from service import TFS

WEB = Path(__file__).resolve().parent / "web"


class App:
    def __init__(self, cfg, service, alerts, notifier):
        self.cfg, self.service, self.alerts, self.notifier = cfg, service, alerts, notifier
        self.started = time.time()
        self.stop = threading.Event()

    def alert_cycle(self, service):
        states = {s: service.get_state(s, self.cfg.alert_tf) for s, m in service.markets.items() if m.ready}
        if states:
            self.alerts.run_cycle(states)

    def refresh_loop(self):
        self.service.listeners.append(self.alert_cycle)
        while not self.stop.is_set():
            t0 = time.time()
            self.service.refresh_all()
            self.stop.wait(max(1.0, self.cfg.refresh_seconds - (time.time() - t0)))


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LiqTerminal/1.0"

        def log_message(self, *a):           # silence
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == "/api/state":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    tf = (q.get("tf") or ["1h"])[0]
                    return self._json(app.service.get_state(sym, tf))
                if u.path == "/api/config":
                    c = app.cfg
                    return self._json({"symbols": list(c.symbols), "tfs": list(TFS), "source": c.source,
                                       "telegram": c.telegram_on, "alertTf": c.alert_tf, "alertMinScore": c.alert_min_score,
                                       "alertMaxDistAtr": c.alert_max_dist_atr, "refresh": c.refresh_seconds,
                                       "anchor": c.anchor_date})
                if u.path == "/api/alerts":
                    return self._json({"telegram": app.cfg.telegram_on, "log": app.alerts.log[-20:][::-1],
                                       "errors": app.service.errors})
                if u.path == "/api/health":
                    return self._json({"ok": True, "uptime": time.time() - app.started,
                                       "ready": {s: m.ready for s, m in app.service.markets.items()},
                                       "errors": app.service.errors, "lastUpdate": app.service.last_update})
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return self._static(u.path)

        def _static(self, path):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            f = (WEB / rel).resolve()
            if WEB not in f.parents or not f.is_file():          # pas de sortie du dossier web/
                self.send_error(404)
                return
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", (mimetypes.guess_type(str(f))[0] or "application/octet-stream") +
                             ("; charset=utf-8" if f.suffix in (".html", ".js", ".css") else ""))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(app: App):
    httpd = ThreadingHTTPServer((app.cfg.host, app.cfg.port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
