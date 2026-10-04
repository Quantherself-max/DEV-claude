"""Serveur local (bibliotheque standard uniquement) : API JSON, reglages et fichiers statiques de web/.
Securite : n'ecoute que sur 127.0.0.1, refuse les en-tetes Host etrangers (DNS rebinding) et exige un jeton
de session sur toutes les requetes qui modifient quelque chose (un autre site ne peut pas le lire)."""
import json
import mimetypes
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from alerts.notifier import ConsoleNotifier, TelegramNotifier
from alerts.rules import AlertEngine
from config import ROOT, load_config, write_env
from data.binance import BinanceSource
from data.simulated import SimulatedSource
from service import TFS, Service

WEB = Path(__file__).resolve().parent / "web"


def default_source(cfg):
    return BinanceSource() if cfg.source == "binance" else SimulatedSource()


def build_parts(cfg, make_source=default_source):
    source = make_source(cfg)
    notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base) \
        if cfg.telegram_on else ConsoleNotifier()
    return source, Service(source, cfg), AlertEngine(cfg, notifier), notifier


class App:
    def __init__(self, cfg, env_path: Path | None = None, make_source=default_source):
        self.env_path = env_path or ROOT / ".env"
        self.make_source = make_source
        self.token = secrets.token_hex(16)
        self.started = time.time()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.reload_lock = threading.Lock()
        self._install(cfg)

    def _install(self, cfg):
        source, service, alerts, notifier = build_parts(cfg, self.make_source)
        service.listeners.append(self.alert_cycle)
        self.cfg, self.source, self.service, self.alerts, self.notifier = cfg, source, service, alerts, notifier

    def reload(self, cfg):
        """Applique de nouveaux reglages sans redemarrer le programme. Les donnees ne sont rechargees que si la
        source ou les paires changent (sinon seules les alertes / Telegram sont remplacees)."""
        with self.reload_lock:
            old = self.cfg
            if (cfg.source, tuple(cfg.symbols), cfg.anchor_date) != (old.source, tuple(old.symbols), old.anchor_date):
                self._install(cfg)
                self.wake.set()
            else:
                self.notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base) \
                    if cfg.telegram_on else ConsoleNotifier()
                self.alerts = AlertEngine(cfg, self.notifier)
                self.cfg = cfg

    def alert_cycle(self, service):
        if service is not self.service:          # ancien service (apres un changement de reglages)
            return
        states = {s: service.get_state(s, self.cfg.alert_tf) for s, m in service.markets.items() if m.ready}
        if states:
            self.alerts.run_cycle(states)

    def refresh_loop(self):
        while not self.stop.is_set():
            t0 = time.time()
            self.service.refresh_all()
            self.wake.clear()
            self.wake.wait(max(1.0, self.cfg.refresh_seconds - (time.time() - t0)))

    # --- reglages ---
    def settings(self):
        c = self.cfg
        tok = c.telegram_token
        return {"source": c.source, "symbols": list(c.symbols),
                "telegram": {"configured": c.telegram_on, "tokenHint": ("..." + tok[-4:]) if tok else "",
                             "chatId": c.telegram_chat_id},
                "alertMinScore": c.alert_min_score, "alertTf": c.alert_tf, "alertCooldownHours": c.alert_cooldown_hours,
                "alertSweep": c.alert_sweep}

    def save_settings(self, body: dict):
        upd = {}
        if body.get("source") in ("simulated", "binance"):
            upd["TERMINAL_SOURCE"] = body["source"]
        if isinstance(body.get("symbols"), list):
            syms = [s.strip().upper() for s in body["symbols"] if isinstance(s, str) and s.strip().isalnum()]
            if syms:
                upd["TERMINAL_SYMBOLS"] = ",".join(syms[:6])
        if body.get("telegramToken"):
            tok = str(body["telegramToken"]).strip()
            if ":" not in tok or len(tok) > 100:
                raise ValueError("token Telegram invalide (format attendu 123456:ABC...)")
            upd["TELEGRAM_BOT_TOKEN"] = tok
        if "telegramChatId" in body:
            cid = str(body["telegramChatId"]).strip()
            if cid and not cid.lstrip("-").isdigit():
                raise ValueError("chat id invalide (un nombre)")
            upd["TELEGRAM_CHAT_ID"] = cid
        if body.get("alertMinScore") is not None:
            upd["TERMINAL_ALERT_MIN_SCORE"] = str(max(2, min(6, int(body["alertMinScore"]))))
        if body.get("alertCooldownHours") is not None:
            upd["TERMINAL_ALERT_COOLDOWN_HOURS"] = str(max(0.5, min(48.0, float(body["alertCooldownHours"]))))
        if body.get("alertTf") in TFS:
            upd["TERMINAL_ALERT_TF"] = body["alertTf"]
        if body.get("alertSweep") is not None:
            upd["TERMINAL_ALERT_SWEEP"] = "1" if body["alertSweep"] else "0"
        write_env(self.env_path, upd)
        cfg = load_config(self.env_path)
        cfg.port, cfg.host, cfg.data_dir = self.cfg.port, self.cfg.host, self.cfg.data_dir
        self.reload(cfg)
        return self.settings()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LiqTerminal/2.0"

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

        def _host_ok(self):
            port = self.server.server_address[1]
            return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "hote refuse"}, 403)
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
                                       "anchor": c.anchor_date, "statsK": c.stats_k, "statsHorizon": c.stats_horizon,
                                       "csrf": app.token})
                if u.path == "/api/settings":
                    return self._json(app.settings())
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

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Terminal-Token") != app.token:
                return self._json({"error": "requete refusee"}, 403)
            try:
                n = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(min(n, 20000)).decode("utf-8") or "{}") if n else {}
                path = urlparse(self.path).path
                if path == "/api/settings":
                    return self._json(app.save_settings(body))
                if path == "/api/test/binance":
                    sym = app.cfg.symbols[0] if app.cfg.symbols else "BTCUSDT"
                    res = BinanceSource(retries=1, timeout=12).selftest(sym)
                    return self._json({"results": [{"name": a, "ok": b, "detail": c} for a, b, c in res]})
                if path == "/api/test/telegram":
                    tok = body.get("token") or app.cfg.telegram_token
                    cid = body.get("chatId") or app.cfg.telegram_chat_id
                    if not tok or not cid:
                        return self._json({"ok": False, "detail": "token et chat id requis"})
                    ok, detail = TelegramNotifier(tok, cid, app.cfg.telegram_api_base).send(
                        "✅ Test du terminal : Telegram fonctionne.")
                    return self._json({"ok": ok, "detail": detail})
                if path == "/api/telegram/chatid":
                    tok = body.get("token") or app.cfg.telegram_token
                    if not tok:
                        return self._json({"chats": [], "detail": "token requis"})
                    try:
                        chats = TelegramNotifier(tok, "", app.cfg.telegram_api_base).find_chat_ids()
                    except Exception as e:
                        code = getattr(e, "code", None)
                        msg = "token refuse par Telegram (verifie-le)" if code in (401, 404) else f"{type(e).__name__}: {e}"
                        return self._json({"chats": [], "detail": msg})
                    return self._json({"chats": [{"id": str(k), "name": v} for k, v in chats.items()],
                                       "detail": "" if chats else "aucun message recu : ecris d'abord un message a ton bot"})
                return self._json({"error": "inconnu"}, 404)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

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
