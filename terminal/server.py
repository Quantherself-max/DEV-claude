"""Serveur local (bibliotheque standard uniquement) : API JSON, reglages et fichiers statiques de web/.
Securite : n'ecoute que sur 127.0.0.1, refuse les en-tetes Host etrangers (DNS rebinding) et exige un jeton
de session sur toutes les requetes qui modifient quelque chose (un autre site ne peut pas le lire)."""
import gzip
import json
import mimetypes
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from alerts.assistant import MODELS as CHAT_MODELS, Assistant, TelegramChat, install_sdk
from alerts.notifier import ConsoleNotifier, TelegramNotifier
from alerts.rules import AlertEngine
from alerts.trades import OPEN, TradeDesk
from config import ROOT, load_config, write_env
from data import reports as reports_mod
from data.binance import BinanceSource
from data.live import LiveFeed
from data.social import Influencers, clean_handles
from data.simulated import SimulatedSource
from service import TFS, Service
from updater import Updater, UpdateError

WEB = Path(__file__).resolve().parent / "web"


def default_source(cfg):
    return BinanceSource() if cfg.source == "binance" else SimulatedSource()


def default_hub(cfg, source):
    """Donnees externes (calendrier, actifs de reference, dominance) : reelles avec Binance, fictives en mode simule."""
    from data.external import ExternalHub, RealProviders, SimProviders
    if cfg.source == "binance":
        return ExternalHub(RealProviders(), source.now_ms, cfg.data_dir, cfg.symbols, derivs=cfg.derivs_on)
    return ExternalHub(SimProviders(source.now_ms), source.now_ms, str(Path(cfg.data_dir) / "simulated"), cfg.symbols, derivs=cfg.derivs_on)


def default_feed(cfg):
    return LiveFeed(cfg.binance_ws, cfg.symbols, cfg.data_dir) if cfg.source == "binance" and cfg.live_ws else None


def build_parts(cfg, make_source=default_source, make_feed=default_feed, make_hub=default_hub):
    source = make_source(cfg)
    notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base) \
        if cfg.telegram_on else ConsoleNotifier()
    service = Service(source, cfg)
    feed = make_feed(cfg)
    if feed:
        service.attach_feed(feed)
    hub = make_hub(cfg, source)
    if hub:
        service.attach_ext(hub)
    return source, service, AlertEngine(cfg, notifier), notifier, feed


class App:
    def __init__(self, cfg, env_path: Path | None = None, make_source=default_source, make_feed=default_feed,
                 make_hub=default_hub, make_updater=None, updates: bool = False):
        self.env_path = env_path or ROOT / ".env"
        self.make_updater = make_updater or (lambda c: Updater(ROOT, c.update_repo, c.update_branch, c.update_token, api=c.update_api))
        self.updates_on = updates                      # True : lance par run.py, qui sait relancer le terminal apres une mise a jour
        self.httpd = None
        self.restart_requested = False
        self.boot = secrets.token_hex(4)               # change a chaque demarrage : la page du navigateur se recharge toute seule
        self.upd_lock = threading.Lock()
        self.upd = {"state": "pas encore vérifié", "latest": None, "newer": False, "lastCheck": None, "error": None, "result": None}
        self.tgchat = None
        self.make_source, self.make_feed, self.make_hub = make_source, make_feed, make_hub
        self.running = False
        self.feed = None
        self.token = secrets.token_hex(16)
        self.started = time.time()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.reload_lock = threading.Lock()
        self.price_lock = threading.Lock()
        self._install(cfg)

    def _install(self, cfg):
        old = self.feed
        source, service, alerts, notifier, feed = build_parts(cfg, self.make_source, self.make_feed, self.make_hub)
        service.listeners.append(self.alert_cycle)
        self.cfg, self.source, self.service, self.alerts, self.notifier = cfg, source, service, alerts, notifier
        self.social = Influencers(cfg)
        self.desk = TradeDesk(cfg, notifier, log=alerts._log, opinions=self.social.opinions)
        self.feed = feed
        self.price_cache = {}
        self.assistant = Assistant(cfg, lambda: self.service, cfg.data_dir)
        if old:
            old.stop()
        if feed and self.running:
            feed.start()
        self._chat_restart()

    def _chat_restart(self):
        """(Re)lance l'ecoute des messages Telegram pour la discussion avec Claude, si elle est activee et configuree."""
        old = getattr(self, "tgchat", None)
        if old:
            old.close()
        self.tgchat = None
        c = self.cfg
        if self.running and c.chat_telegram and c.telegram_on and c.chat_key:
            self.tgchat = TelegramChat(c, self.assistant, c.data_dir)
            self.tgchat.start()

    def start_background(self):
        """Demarre les flux temps reel (apres la creation : les tests n'ouvrent aucune connexion)."""
        self.running = True
        if self.feed:
            self.feed.start()
        self._chat_restart()

    def shutdown(self):
        self.stop.set()
        self.wake.set()
        if self.feed:
            self.feed.stop()
        if self.tgchat:
            self.tgchat.close()

    def live_price(self, sym: str) -> dict:
        """Dernier prix (cache 0,5 s) : secours quand le flux WebSocket du navigateur ne passe pas."""
        if sym not in self.service.markets:
            raise KeyError(f"symbole inconnu : {sym}")
        now = time.time()
        with self.price_lock:
            hit = self.price_cache.get(sym)
            if hit and now - hit[0] < 0.5:
                return hit[1]
        try:
            lp = self.feed.last_price(sym, 5.0) if self.feed else None
            if lp:
                res = {"symbol": sym, "price": lp[0], "t": lp[1], "via": "ws"}
            else:
                p, t = self.source.last_price(sym)
                res = {"symbol": sym, "price": p, "t": t, "via": "rest"}
        except Exception as e:
            res = {"symbol": sym, "error": f"{type(e).__name__}: {e}"}
        with self.price_lock:
            self.price_cache[sym] = (now, res)
        return res

    def reload(self, cfg):
        """Applique de nouveaux reglages sans redemarrer le programme. Les donnees ne sont rechargees que si la
        source ou les paires changent (sinon seules les alertes / Telegram sont remplacees)."""
        with self.reload_lock:
            old = self.cfg
            if (cfg.source, tuple(cfg.symbols), cfg.anchor_date, cfg.history_years) != (old.source, tuple(old.symbols), old.anchor_date, old.history_years):
                self._install(cfg)
                self.wake.set()
            else:
                self.notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base) \
                    if cfg.telegram_on else ConsoleNotifier()
                self.alerts = AlertEngine(cfg, self.notifier)
                self.social = Influencers(cfg)
                self.desk = TradeDesk(cfg, self.notifier, log=self.alerts._log, opinions=self.social.opinions)
                self.cfg = cfg
                self.service.cfg = cfg                       # les reglages d'idees (seuil, levier, quota) s'appliquent tout de suite
                for m in self.service.markets.values():
                    m.cfg = cfg
                self.service._sig_cache.clear()
                self.assistant.cfg = cfg
                self._chat_restart()

    def alert_cycle(self, service):
        if service is not self.service:          # ancien service (apres un changement de reglages)
            return
        states = {s: service.get_state(s, self.cfg.alert_tf) for s, m in service.markets.items() if m.ready}
        if not states:
            return
        macro = None
        if self.cfg.alert_macro and self.cfg.alert_mode == "all":
            try:
                macro = service.analysis(next(iter(states)))["macro"]
            except Exception:
                macro = None
        self.alerts.run_cycle(states, macro)
        self.trade_cycle(service, list(states))

    def trade_cycle(self, service, symbols):
        """Idees de trade : suit les idees ouvertes sur les bougies 5 min, puis envoie les nouvelles (quota hebdomadaire)."""
        if not self.cfg.signal_on:
            return
        try:
            now = self.source.now_ms()
            sigs = {s: service.signals(s) for s in symbols}
            m5s = {}
            for s in symbols:
                open_ = [t["checked"] for t in self.desk.trades if t["symbol"] == s and t["status"] in OPEN]
                if open_:
                    m5s[s] = service.recent_m5(s, min(open_))
            self.desk.run_cycle(sigs, m5s, now)
            service.errors.pop("idees", None)
        except Exception as e:
            service.errors["idees"] = f"{type(e).__name__}: {e}"

    def refresh_loop(self):
        while not self.stop.is_set():
            t0 = time.time()
            self.service.refresh_all()
            self.wake.clear()
            self.wake.wait(max(1.0, self.cfg.refresh_seconds - (time.time() - t0)))

    # --- mise a jour automatique (updater.py) ---
    def start_updates(self):
        """Verification periodique des nouvelles versions (premiere verification 90 s apres le demarrage)."""
        self.updates_on = True
        t = threading.Timer(45.0, self._mark_healthy)
        t.daemon = True
        t.start()
        threading.Thread(target=self.update_loop, daemon=True).start()

    def _mark_healthy(self):
        try:
            self.make_updater(self.cfg).mark_healthy()
        except OSError:
            pass

    def update_loop(self):
        if self.stop.wait(90):
            return
        while not self.stop.is_set() and not self.restart_requested:
            self.update_check()
            self.stop.wait(self.cfg.update_minutes * 60)

    def update_status(self) -> dict:
        c = self.cfg
        u = self.make_updater(c)
        st = u.state()
        just = None
        if st.get("installedAt") and st.get("previous") and st["installedAt"] >= self.started - 900:
            just = {"sha": st.get("sha"), "message": st.get("message"), "at": st.get("installedAt")}
        lan = u.dir / "lanceurs"
        return {"configured": bool(c.update_token), "auto": c.update_auto, "repo": c.update_repo, "branch": c.update_branch, "minutes": c.update_minutes,
                "tokenHint": ("..." + c.update_token[-4:]) if c.update_token else "", "installed": u.installed(), "git": u.is_git(), "supervised": self.updates_on,
                "boot": self.boot, "justUpdated": just, "rolledBack": st.get("rolledBack"), "launchers": sorted(p.name for p in lan.iterdir()) if lan.is_dir() else [],
                **{k: self.upd[k] for k in ("state", "latest", "newer", "lastCheck", "error", "result")}}

    def update_check(self, install: bool | None = None) -> dict:
        """Verifie la derniere version ; l'installe si `install` (ou, par defaut, si la mise a jour automatique est active), puis relance le terminal."""
        if not self.upd_lock.acquire(blocking=False):
            return {**self.update_status(), "busy": True}
        try:
            u = self.make_updater(self.cfg)
            self.upd.update(state="vérification…", error=None)
            try:
                r = u.check()
                unknown = not r["installed"].get("sha")
                self.upd.update(latest=r["latest"], newer=r["newer"], lastCheck=time.time(),
                                state=("version installée inconnue : à comparer" if unknown else "mise à jour disponible") if r["newer"] else "à jour")
                if r["newer"] and (self.cfg.update_auto if install is None else install):
                    self.upd["state"] = "installation…"
                    res = u.apply(r["latest"])
                    self.upd.update(result=res, newer=False, state="installée : redémarrage…" if res["restart"] else "à jour")
                    if res["restart"]:
                        self.request_restart()
            except UpdateError as e:
                self.upd.update(state="erreur", error=str(e), lastCheck=time.time())
            except Exception as e:
                self.upd.update(state="erreur", error=f"{type(e).__name__}: {str(e)[:200]}", lastCheck=time.time())
        finally:
            self.upd_lock.release()
        return self.update_status()

    def request_restart(self, delay: float = 2.0) -> bool:
        """Arrete proprement le serveur pour que run.py le relance avec la nouvelle version. Sans run.py (lancement manuel), la version s'applique au prochain demarrage."""
        if not self.updates_on:
            self.upd["state"] = "installée : relance le terminal pour l'utiliser"
            return False
        self.restart_requested = True

        def go():
            time.sleep(delay)                          # laisse partir la reponse en cours
            if self.httpd:
                self.httpd.shutdown()
        threading.Thread(target=go, daemon=True).start()
        return True

    # --- reglages ---
    def settings(self):
        c = self.cfg
        tok = c.telegram_token
        return {"source": c.source, "symbols": list(c.symbols),
                "telegram": {"configured": c.telegram_on, "tokenHint": ("..." + tok[-4:]) if tok else "",
                             "chatId": c.telegram_chat_id},
                "alertMinScore": c.alert_min_score, "alertTf": c.alert_tf, "alertCooldownHours": c.alert_cooldown_hours,
                "alertMode": c.alert_mode, "alertSweep": c.alert_sweep, "alertMacro": c.alert_macro, "alertZones": c.alert_zones, "historyYears": c.history_years,
                "signalOn": c.signal_on, "signalMinScore": c.signal_min_score, "signalMaxWeek": c.signal_max_week, "signalMaxPerSymbol": c.signal_max_per_symbol,
                "signalLeverage": c.signal_leverage, "signalTrendGate": c.signal_trend_gate,
                "x": {"on": c.x_on, "configured": bool(c.x_token and c.x_accounts), "tokenHint": ("..." + c.x_token[-4:]) if c.x_token else "",
                      "accounts": list(c.x_accounts), "posts": c.x_posts},
                "chat": {"configured": bool(c.chat_key), "keyHint": ("..." + c.chat_key[-4:]) if c.chat_key else "", "model": c.chat_model, "web": c.chat_web,
                         "telegram": c.chat_telegram, "budget": c.chat_budget},
                "update": {"auto": c.update_auto, "branch": c.update_branch, "repo": c.update_repo, "configured": bool(c.update_token),
                           "tokenHint": ("..." + c.update_token[-4:]) if c.update_token else ""}}

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
        if body.get("historyYears") is not None:
            upd["TERMINAL_HISTORY_YEARS"] = str(max(0, min(10, int(body["historyYears"]))))
        if body.get("alertMode") in ("ideas", "all"):
            upd["TERMINAL_ALERT_MODE"] = body["alertMode"]
        if body.get("alertZones") is not None:
            upd["TERMINAL_ALERT_ZONES"] = "1" if body["alertZones"] else "0"
        if body.get("alertMacro") is not None:
            upd["TERMINAL_ALERT_MACRO"] = "1" if body["alertMacro"] else "0"
        if body.get("signalOn") is not None:
            upd["TERMINAL_SIGNALS"] = "1" if body["signalOn"] else "0"
        if body.get("signalMinScore") is not None:
            upd["TERMINAL_SIGNAL_MIN_SCORE"] = str(max(40, min(95, float(body["signalMinScore"]))))
        if body.get("signalMaxWeek") is not None:
            upd["TERMINAL_SIGNAL_MAX_WEEK"] = str(max(1, min(10, int(body["signalMaxWeek"]))))
        if body.get("signalMaxPerSymbol") is not None:
            upd["TERMINAL_SIGNAL_MAX_PER_SYMBOL"] = str(max(1, min(10, int(body["signalMaxPerSymbol"]))))
        if body.get("signalLeverage") is not None:
            upd["TERMINAL_SIGNAL_LEVERAGE"] = str(max(1, min(125, float(body["signalLeverage"]))))
        if body.get("signalTrendGate") is not None:
            upd["TERMINAL_SIGNAL_TREND_GATE"] = "1" if body["signalTrendGate"] else "0"
        if body.get("xToken"):
            tok = str(body["xToken"]).strip()
            if len(tok) > 400 or re.search(r"\s", tok):
                raise ValueError("jeton X invalide (une seule chaîne, sans espace)")
            upd["TERMINAL_X_BEARER_TOKEN"] = tok
        if body.get("xClearToken"):
            upd["TERMINAL_X_BEARER_TOKEN"] = ""
        if "xAccounts" in body:
            upd["TERMINAL_X_ACCOUNTS"] = ",".join(clean_handles(body["xAccounts"]))
        if body.get("xPosts") is not None:
            upd["TERMINAL_X_POSTS"] = str(max(5, min(20, int(body["xPosts"]))))
        if body.get("xOn") is not None:
            upd["TERMINAL_X_ON"] = "1" if body["xOn"] else "0"
        if body.get("chatKey"):
            key = str(body["chatKey"]).strip()
            if not re.fullmatch(r"[A-Za-z0-9_\-]{20,300}", key):
                raise ValueError("clé API Claude invalide (une seule chaîne, du type sk-ant-...)")
            upd["TERMINAL_ANTHROPIC_API_KEY"] = key
        if body.get("chatClearKey"):
            upd["TERMINAL_ANTHROPIC_API_KEY"] = ""
        if body.get("chatModel") in CHAT_MODELS:
            upd["TERMINAL_CHAT_MODEL"] = body["chatModel"]
        if body.get("chatWeb") is not None:
            upd["TERMINAL_CHAT_WEB"] = "1" if body["chatWeb"] else "0"
        if body.get("chatTelegram") is not None:
            upd["TERMINAL_CHAT_TELEGRAM"] = "1" if body["chatTelegram"] else "0"
        if body.get("chatBudget") is not None:
            upd["TERMINAL_CHAT_BUDGET"] = str(max(0.0, min(1000.0, float(body["chatBudget"]))))
        if body.get("updateToken"):
            tok = str(body["updateToken"]).strip()
            if len(tok) > 255 or not re.fullmatch(r"[A-Za-z0-9_]+", tok):
                raise ValueError("jeton GitHub invalide (une seule chaîne de lettres, chiffres et _ : github_pat_… ou ghp_…)")
            upd["TERMINAL_GITHUB_TOKEN"] = tok
        if body.get("updateClearToken"):
            upd["TERMINAL_GITHUB_TOKEN"] = ""
        if body.get("updateAuto") is not None:
            upd["TERMINAL_UPDATE_AUTO"] = "1" if body["updateAuto"] else "0"
        if body.get("updateBranch") is not None:
            br = str(body["updateBranch"]).strip() or "auto"
            if not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", br) or ".." in br:
                raise ValueError("nom de branche invalide")
            upd["TERMINAL_UPDATE_BRANCH"] = br
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
            self.send_header("X-Terminal-Boot", app.boot)
            if len(body) > 4000 and "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body, 3)
                self.send_header("Content-Encoding", "gzip")
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
                                       "historyYears": c.history_years,
                                       "csrf": app.token, "wsBase": c.binance_ws if c.source == "binance" else "",
                                       "cbWs": c.coinbase_ws if c.source == "binance" else ""})
                if u.path == "/api/vp":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.get_vp(sym, (q.get("tf") or ["1h"])[0]))
                if u.path == "/api/vps":
                    return self._json({**app.service.vp_state, "auto": {tf: list(v) for tf, v in __import__("engine.vpx", fromlist=["x"]).AUTO_BY_TF.items()}})
                if u.path == "/api/series":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.get_series(sym, (q.get("tf") or ["1h"])[0]))
                if u.path == "/api/overview":
                    o = app.service.overview()
                    o["alerts"] = [{"t": a["t"], "text": a["text"].split("\n")[0], "sent": a.get("sent")} for a in app.alerts.log[-6:][::-1]]
                    o["feed"] = app.feed.status() if app.feed else None
                    o["errors"] = app.service.errors
                    d = app.desk.public(app.source.now_ms())
                    o["week"], o["tradeStats"], o["openTrades"] = d["week"], d["stats"], [t for t in d["trades"] if t["status"] in ("pending", "active", "tp1")]
                    return self._json(o)
                if u.path == "/api/signals":
                    syms = [(q.get("symbol") or [""])[0].upper()] if (q.get("symbol") or [""])[0] else list(app.service.markets)
                    for sy in syms:
                        if sy not in app.service.markets:
                            raise KeyError(f"symbole inconnu : {sy}")
                    return self._json({"symbols": {sy: app.service.signals(sy) for sy in syms}, "desk": app.desk.public(app.source.now_ms()),
                                       "on": app.cfg.signal_on})
                if u.path == "/api/backtest":
                    lab = (q.get("label") or [""])[0]
                    if not lab:
                        return self._json({"reports": reports_mod.summaries(app.service.report_dirs)})
                    kind = (q.get("kind") or ["backtest"])[0]
                    if kind not in reports_mod.KINDS:
                        raise ValueError("type de rapport inconnu")
                    rep = reports_mod.load(app.service.report_dirs, lab, kind)
                    if rep is None:
                        raise KeyError(f"rapport introuvable : {lab}")
                    return self._json(rep)
                if u.path == "/api/lecture":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.lecture(sym))
                if u.path == "/api/strategy":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.strategy(sym))
                if u.path == "/api/influencers":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    side = (q.get("side") or ["long"])[0]
                    if sym not in app.service.markets:
                        raise KeyError(f"symbole inconnu : {sym}")
                    if side not in ("long", "short"):
                        raise ValueError("sens invalide (long ou short)")
                    return self._json(app.social.opinions(sym, side))
                if u.path == "/api/analysis":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.analysis(sym))
                if u.path == "/api/plan":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    g = lambda k, d: float((q.get(k) or [d])[0])
                    return self._json(app.service.plan(sym, (q.get("side") or ["long"])[0], g("tp", 2.0), g("sl", 1.0),
                                                       g("lev", 10.0), int(g("h", 24))))
                if u.path == "/api/heat":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    hrs = float((q.get("hours") or ["0"])[0]) or None
                    return self._json(app.service.get_heat(sym, hrs))
                if u.path == "/api/liqs":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    if sym not in app.service.markets:
                        raise KeyError(f"symbole inconnu : {sym}")
                    f = app.feed
                    since = int(time.time() * 1000) - int(float((q.get("hours") or ["24"])[0]) * 3_600_000)
                    return self._json({"symbol": sym, "live": bool(f), "events": f.recent_liqs(sym, since) if f else [],
                                       "summary": f.liq_summary(sym) if f else None,
                                       "status": f.status() if f else None})
                if u.path == "/api/price":
                    return self._json(app.live_price((q.get("symbol") or [app.cfg.symbols[0]])[0].upper()))
                if u.path == "/api/settings":
                    return self._json(app.settings())
                if u.path == "/api/update":
                    return self._json(app.update_status())
                if u.path == "/api/chat":
                    t = app.tgchat
                    return self._json({**app.assistant.status(), "history": app.assistant.history(),
                                       "telegramListening": bool(t), "telegramError": t.last_error if t else None})
                if u.path == "/api/alerts":
                    return self._json({"telegram": app.cfg.telegram_on, "log": app.alerts.log[-20:][::-1],
                                       "errors": app.service.errors})
                if u.path == "/api/health":
                    return self._json({"ok": True, "uptime": time.time() - app.started,
                                       "ready": {s: m.ready for s, m in app.service.markets.items()},
                                       "errors": app.service.errors, "lastUpdate": app.service.last_update,
                                       "feed": app.feed.status() if app.feed else None})
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
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
                if path == "/api/chat":
                    return self._json(app.assistant.ask(str(body.get("question") or ""), src="web"))
                if path == "/api/chat/reset":
                    app.assistant.reset()
                    return self._json({"ok": True})
                if path == "/api/chat/install":
                    ok, msg = install_sdk()
                    if ok:
                        app._chat_restart()
                    return self._json({"ok": ok, "detail": msg, **app.assistant.status()})
                if path == "/api/update/check":
                    return self._json(app.update_check(install=False))
                if path == "/api/update/apply":
                    return self._json(app.update_check(install=True))
                if path == "/api/vps":
                    return self._json({**app.service.set_vp(body.get("specs"), body.get("anchors", app.service.vp_state["anchors"])), "ok": True})
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
                if path == "/api/test/x":
                    return self._json(app.social.test(str(body.get("token") or "").strip() or None, body.get("handle")))
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
