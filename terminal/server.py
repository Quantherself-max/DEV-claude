"""Serveur local (bibliotheque standard uniquement) : API JSON, reglages et fichiers statiques de web/.
Securite : n'ecoute que sur 127.0.0.1, refuse les en-tetes Host etrangers (DNS rebinding) et exige un jeton
de session sur toutes les requetes qui modifient quelque chose (un autre site ne peut pas le lire)."""
from __future__ import annotations
import gzip
import hashlib
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from bisect import bisect_right
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from alerts.assistant import MODELS as CHAT_MODELS, Assistant, TelegramChat, install_sdk
from alerts import notifier as notifier_mod
from alerts.notifier import ConsoleNotifier, TelegramNotifier
from alerts import readings as readings_mod
from alerts.rules import AlertEngine
from alerts.trades import OPEN, TradeDesk
from config import ROOT, chat_is_bot, chat_ok, clean_chat, clean_token, env_sources, load_config, token_ok, write_env
from data import reports as reports_mod
from data import heatbook as heat_mod
from data.binance import BinanceSource
from data.live import LiveFeed
from data.orderflow import OrderFlow, SimFlow
from data.social import Influencers, clean_handles
from data.simulated import SimulatedSource
from service import ALERT_TFS, TFS, Service, chart_bars
from prefsync import PrefSync, env_shareable
from updater import Updater, UpdateError

WEB = Path(__file__).resolve().parent / "web"
VERSION = "42"
API_LEVEL = 42                                                   # adresses /api que les pages web de cette version attendent (la page compare)
CODE_SKIP = {"data_local", "__pycache__", "tests", "serveur", ".update", ".git", "node_modules"}


def code_signature(root: Path = ROOT) -> str:
    """Empreinte des fichiers Python du terminal (chemin, taille, date) : elle change quand une nouvelle version est copiee dans le dossier
    (mise a jour, ZIP extrait par-dessus, git pull) alors que l'ancien programme tourne encore."""
    h = hashlib.sha1()
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in CODE_SKIP and not x.startswith("."))
        for f in sorted(files):
            if f.endswith(".py"):
                p = Path(d) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                h.update(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def default_source(cfg):
    return BinanceSource() if cfg.source == "binance" else SimulatedSource()


def default_hub(cfg, source):
    """Donnees externes (calendrier, actifs de reference, dominance) : reelles avec Binance, fictives en mode simule."""
    from data.external import ExternalHub, RealProviders, SimProviders
    if cfg.source == "binance":
        return ExternalHub(RealProviders(), source.now_ms, cfg.data_dir, cfg.symbols, derivs=cfg.derivs_on)
    return ExternalHub(SimProviders(source.now_ms), source.now_ms, str(Path(cfg.data_dir) / "simulated"), cfg.symbols, derivs=cfg.derivs_on)


def default_feed(cfg):
    return LiveFeed(cfg.binance_ws, cfg.symbols, cfg.data_dir, spot_ws=getattr(cfg, "binance_spot_ws", None)) \
        if cfg.source == "binance" and cfg.live_ws else None


def _sim_price(service, sym):
    m = service.markets.get(sym)
    return m.price() if m is not None and m.ready else None


def default_flow(cfg, source, service, feed):
    """Flux d'ordres (V15) : carnet Binance + nombre d'ordres OKX + ruban ; donnees fabriquees en mode simule ; rien sans flux temps reel."""
    if not getattr(cfg, "orderflow_on", True):
        return None
    if cfg.source != "binance":
        return SimFlow(cfg.symbols, lambda s: _sim_price(service, s))
    if feed is None or not hasattr(source, "_get"):
        return None
    flow = OrderFlow(cfg.symbols, cfg.binance_ws_public, cfg.okx_ws,
                     lambda s: source._get("/fapi/v1/depth", {"symbol": s, "limit": 1000}, retries=2, timeout=10))
    feed.flow = flow
    return flow


def price_lookup(service, sym):
    """V29 : prix d'une paire à un instant passé (bougie 5 min si elle est encore gardée, sinon bougie d'une heure ; moyenne haut, bas,
    clôture) ; None tant que l'historique n'est pas chargé. Les listes sont copiées une fois : à rappeler pour un nouveau lot."""
    m = service.markets.get(sym)
    if m is None or not m.ready or not m.store.h1:
        return None
    m5, h1 = list(m.store.m5), list(m.store.h1)
    t5, t1 = [k.t for k in m5], [k.t for k in h1]

    def at(t_ms):
        for ts, cs, step in ((t5, m5, 300_000), (t1, h1, 3_600_000)):
            i = bisect_right(ts, t_ms) - 1
            if i >= 0 and t_ms < cs[i].t + step:
                k = cs[i]
                return (k.h + k.l + k.c) / 3
        return None
    return at


def default_heat(cfg, source, service, flow) -> dict:
    """V28 : heatmap du carnet (BTC par defaut) : carnets en direct deja suivis + adresses publiques profondes ; fabriquee en mode simule.
    V29 : memoire longue (un quart d'heure par colonne, heatmap_days jours) remplie par tes photos et, la ou il n'y en a pas, par les
    archives publiques de Binance (bookDepth) ; en mode simule, des archives fabriquees (rien n'est ecrit sur le disque)."""
    syms = [s for s in getattr(cfg, "heatmap_symbols", ()) if s in cfg.symbols]
    if not syms:
        return {}
    from data import heatbook as hb
    days = int(getattr(cfg, "heatmap_days", hb.LT_DAYS) or 0)
    out = {}
    for sym in syms:
        book = hb.HeatBook(sym)
        prices = lambda sym=sym: price_lookup(service, sym)
        if cfg.source != "binance":
            def price_at(t_ms, sym=sym):
                m = service.markets.get(sym)
                if m is None or not m.ready or not m.store.m5:
                    return None
                cs = m.store.m5[-200:]
                i = bisect_right([k.t for k in cs], t_ms) - 1
                return cs[max(i, 0)].c
            sim = hb.SimHeat(price_at)
            if days:
                book.long = hb.HeatLong(sym, days)
            out[sym] = hb.HeatRecorder(book, hb.sim_sources(sim, lambda: source.now_ms() / 1000),
                                       prefill=lambda b=book, sm=sim: hb.sim_backfill(b, sm, source.now_ms()),
                                       now=lambda: source.now_ms() / 1000, prices=prices, archive_today=True,
                                       archive=(lambda day, sym=sym: hb.sim_depth_rows(sym, day, price_lookup(service, sym) or (lambda t: None),
                                                                                        source.now_ms())) if days else None)
        else:
            from data.external import http_json
            if days:
                book.long = hb.HeatLong(sym, days, str(Path(cfg.data_dir) / "heatmap" / sym))
            out[sym] = hb.HeatRecorder(book, hb.real_sources(sym, flow, http_json), str(Path(cfg.data_dir) / "heatmap" / f"{sym}.pkl"),
                                       prices=prices, archive=(lambda day, sym=sym: hb.fetch_depth(sym, day)) if days else None)
    return out


def default_liqmaps(cfg, source, service) -> dict:
    """V29 : carte des liquidations sur plusieurs mois (affichage seulement), pour chaque paire : moteur separe rejoue sur les bougies d'une
    heure avec l'interet ouvert de l'adresse Binance (29 jours) et des archives publiques (heatmap_days jours) ; fabrique en mode simule."""
    days = int(getattr(cfg, "heatmap_days", 180) or 0)
    if days <= 0:
        return {}
    from data import oiarchive
    from engine.liqmap import LiqMapKeeper
    out = {}
    for sym in cfg.symbols:
        market = lambda sym=sym: service.markets.get(sym)
        if cfg.source != "binance":
            def first(sym=sym):
                m = service.markets.get(sym)
                if m is None or not m.store.oi_t:
                    return None
                t = m.store.oi_t[0]
                return t + 300_000, m.store.oi[t]
            clock = lambda: source.now_ms() / 1000
            out[sym] = LiqMapKeeper(sym, market, oiarchive.SimOiArchive(sym, first, days, now=clock), days, now=clock)
        else:
            folder = str(Path(cfg.data_dir) / "history" / sym / "raw_metrics")
            arch = oiarchive.OiArchive(sym, folder, days)
            out[sym] = LiqMapKeeper(sym, market, arch, days, deep=oiarchive.DeepOi(sym, folder))
    return out


def default_trades(cfg, source, feed):
    """V23 : transactions exactes de chaque paire (archives Binance Vision + API publique + flux en direct). Seulement avec Binance."""
    if cfg.source != "binance" or getattr(cfg, "footprint_days", 0) <= 0 or not hasattr(source, "_get"):
        return {}
    from data.trades import TradeSync
    get = lambda path, params: source._get(path, params, retries=2, timeout=20)
    fd = getattr(cfg, "sizeflow_days", 14)
    out = {s: TradeSync(s, Path(cfg.data_dir) / "footprint", cfg.footprint_days, get, flow_days=fd) for s in cfg.symbols}
    spot = {}
    if fd > 0 and hasattr(source, "spot_base"):                  # V39 : transactions du marche spot, pour le flux par taille d'ordre
        sget = lambda path, params: source._get(path, params, host=source.spot_base, retries=2, timeout=20)
        spot = {s: TradeSync(s, Path(cfg.data_dir) / "footprint_spot", fd, sget, market="spot") for s in cfg.symbols}
    if feed is not None:
        feed.trades = out
        feed.spot_trades = spot
    out.update({f"{s}:spot": ts for s, ts in spot.items()})       # la meme liste les demarre, les arrete et affiche leur etat
    hd = getattr(cfg, "sizeflow_history_days", 0)
    if hd > 0 and fd > 0:                                        # V40.1 : historique a l'heure du flux par taille (grandes unites de temps)
        from data.sizehist import SizeHistory
        for s in cfg.symbols:
            for market, ts in (("perp", out.get(s)), ("spot", spot.get(s))):
                if ts is not None:
                    out[f"{s}:hist:{market}"] = SizeHistory(s, market, Path(cfg.data_dir) / "sizehist", hd, minute=ts)
    return out


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
    service.attach_trades(default_trades(cfg, source, feed))
    return source, service, AlertEngine(cfg, notifier), notifier, feed, default_flow(cfg, source, service, feed)


class App:
    def __init__(self, cfg, env_path: Path | None = None, make_source=default_source, make_feed=default_feed,
                 make_hub=default_hub, make_updater=None, updates: bool = False):
        self.env_path = env_path or ROOT / ".env"
        self.make_updater = make_updater or (lambda c: Updater(ROOT, c.update_repo, c.update_branch, c.update_token, api=c.update_api))
        self.updates_on = updates                      # True : lance par run.py, qui sait relancer le terminal apres une mise a jour
        self.httpd = None
        self.restart_requested = False
        self.code_sig = None                           # empreinte des fichiers Python au demarrage (start_code_watch)
        self.code_stale = False                        # True : une autre version a ete copiee dans le dossier depuis le demarrage
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
        self.fund_lock = threading.Lock()
        self.prefs_lock = threading.Lock()
        self._env_check = 0.0
        cfg = self._pull_env_at_start(cfg)
        self._install(cfg)

    def _install(self, cfg):
        old, old_flow, old_heat = self.feed, getattr(self, "flow", None), getattr(self, "heat", {})
        old_liq = getattr(self, "liqmaps", {})
        source, service, alerts, notifier, feed, flow = build_parts(cfg, self.make_source, self.make_feed, self.make_hub)
        self.flow = flow
        self.heat = default_heat(cfg, source, service, flow)
        self.liqmaps = default_liqmaps(cfg, source, service)
        for sym, kp in self.liqmaps.items():                  # V31 : intérêt ouvert archivé pour les idées (poches formées il y a plus de 29 jours)
            service.oi_extra[sym] = kp.archive.points
        service.listeners.append(self.alert_cycle)
        self.cfg, self.source, self.service, self.alerts, self.notifier = cfg, source, service, alerts, notifier
        self.social = Influencers(cfg)
        self.desk = TradeDesk(cfg, notifier, log=alerts._log, opinions=self.social.opinions)
        self.feed = feed
        self.price_cache = {}
        self._ind_cache = {}
        self._fund = {}                                   # V35 : versements de funding par symbole (historique Binance)
        self._spot = {}                                   # V37 : bougies spot par (symbole, unité de temps) : CVD du spot
        self._size_cache = {}                             # V39 : flux par taille d'ordre par (symbole, unité de temps)
        self.assistant = Assistant(cfg, lambda: self.service, cfg.data_dir)
        self.readings = readings_mod.ReadingLog(cfg)
        old_trades = getattr(self, "trades", {})
        self.trades = service.trades
        if old:
            old.stop()
        if old_flow:
            old_flow.stop()
        for hr in old_heat.values():
            hr.stop()
        for kp in old_liq.values():
            kp.stop()
        for ts in old_trades.values():
            ts.stop()
        if feed and self.running:
            feed.start()
        if flow and self.running:
            flow.start()
        if self.running:
            for hr in self.heat.values():
                hr.start()
            for kp in self.liqmaps.values():
                kp.start()
            for ts in self.trades.values():
                ts.start()
        self._chat_restart()

    def _chat_restart(self):
        """(Re)lance l'ecoute des messages Telegram pour la discussion avec Claude, si elle est activee et configuree."""
        old = getattr(self, "tgchat", None)
        if old:
            old.close()
        self.tgchat = None
        c = self.cfg
        if self.running and c.chat_telegram and c.telegram_on:          # V25 : le bot repond meme sans cle Claude (/etat, /idees, /aide)
            self.tgchat = TelegramChat(c, self.assistant, c.data_dir, commands={"etat": self.bot_status, "idees": self.bot_ideas})
            self.tgchat.start()

    # --- Telegram (V25) : reponses du bot sans Claude, etat du badge, diagnostic pas a pas ---
    def bot_status(self) -> str:
        """/etat : le terminal en bref (prix, biais, idees de la semaine, tendance de fond)."""
        now = self.source.now_ms()
        L = [f"Terminal en marche ({'données simulées' if self.cfg.source == 'simulated' else 'Binance'}), version {VERSION}."]
        from engine.signals import fmt_price
        for sym in self.cfg.symbols:
            px = self.service.last_price(sym)
            reg = self.service.regime(sym)
            L.append(f"• {sym.replace('USDT', '')} : {fmt_price(px)}" if px else f"• {sym.replace('USDT', '')} : données en chargement")
            if reg and reg.get("ready"):
                L[-1] += f" · tendance de fond {reg['label']}"
        d = self.desk.public(now)
        w, b = d["week"], d["bias"]
        L.append(f"Idées cette semaine : {w['sent']} sur {w['cap']} au maximum.")
        if not b:
            L.append("Idées en cours : aucune (la prochaine peut être un achat ou une vente).")
        else:
            names = ", ".join(f"{'achat' if o['side'] == 'long' else 'vente'} {o['symbol'].replace('USDT', '')}" for o in b["open"])
            L.append(f"Idées en cours : {names}" + (" (couverture : chaque idée garde son stop et ses objectifs)." if b["mixed"] else
                                                    " (une idée dans l'autre sens peut arriver, en couverture)." if b["mode"] != "never" else
                                                    " (rien dans l'autre sens tant qu'elles ne sont pas terminées)."))
        return "\n".join(L)

    # --- idees du moment : envoyee ou pas, et pourquoi (V25.3) ---
    def idea_state(self, sym: str, idea: dict, warm=None) -> dict:
        """Etat d'envoi d'une configuration du moment (meme logique que l'envoi, rien n'est envoye ici)."""
        try:
            return self.desk.send_state(sym, idea, self.source.now_ms(), nsyms=len(self.service.markets),
                                        warm=idea.get("warm", True) if warm is None else warm)
        except Exception as e:                                             # un etat illisible ne doit jamais casser l'affichage
            return {"state": "unknown", "text": f"état indisponible ({type(e).__name__})"}

    def signals_with_state(self, sym: str) -> dict:
        """Signaux du moment, chaque configuration avec son etat d'envoi (copie : le cache du service n'est pas modifie)."""
        sg = self.service.signals(sym)
        if not sg.get("ready"):
            return sg
        return {**sg, "ideas": [{**i, "send": self.idea_state(sym, i, warm=bool(sg.get("warm")))} for i in sg["ideas"]]}

    def bot_ideas(self) -> str:
        """/idees : les idees encore ouvertes (ordre en attente ou position en cours)."""
        from engine.explain import paris
        from engine.signals import fmt_price
        opens = [t for t in self.desk.trades if t["status"] in OPEN and t.get("mode") != "alerte"]
        if not opens:
            return "Aucune idée en cours. Les idées sont rares (5 par semaine au plus) : tu les reçois ici dès qu'elles sont envoyées."
        st = {"pending": "ordre en attente", "active": "en position", "tp1": "objectif 1 atteint, le reste court"}
        return "Idées en cours :\n" + "\n".join(
            f"• {t['symbol'].replace('USDT', '')} {'achat' if t['side'] == 'long' else 'vente'} du {paris(t['created'])} : entrée {fmt_price(t['entry'])}, "
            f"stop {fmt_price(t['stop'])}, objectif 1 {fmt_price(t['tp1'])} — {st.get(t['status'], t['status'])}" for t in opens)

    def telegram_state(self) -> dict:
        """Etat du badge : configure ou non (et pourquoi), dernier envoi, ecoute des messages."""
        c = self.cfg
        last = notifier_mod.last_for(c.telegram_token, c.telegram_chat_id)
        if not c.telegram_token and not c.telegram_chat_id:
            reason = "Ni token ni chat id enregistrés dans les réglages du terminal."
        elif not c.telegram_token:
            reason = "Token du bot manquant dans les réglages (Réglages → 2)."
        elif not c.telegram_chat_id:
            reason = "Chat id manquant dans les réglages (Réglages → 2 → « Trouver mon chat id »)."
        elif last and not last.get("ok"):
            reason = "Dernier envoi refusé : " + last.get("help", "")
        else:
            reason = "Token et chat id enregistrés" + (" ; dernier envoi réussi." if last.get("ok") else ".")
        t = getattr(self, "tgchat", None)
        return {"on": c.telegram_on, "error": bool(c.telegram_on and last and not last.get("ok")), "reason": reason, "last": last,
                "listening": bool(t), "listenError": (t.last_error if t else None)}

    def telegram_diagnose(self, token: str | None = None, chat: str | None = None) -> dict:
        """Verifie chaque maillon et dit quoi faire : fichier de reglages lu, token et chat id enregistres, token accepte par Telegram,
        conversation trouvee, ecoute des messages, dernier envoi. token / chat : valeurs du formulaire (pas encore enregistrees)."""
        c, steps = self.cfg, []

        def step(name, ok, detail, fix=""):
            steps.append({"name": name, "ok": ok, "detail": detail, "fix": fix})
        files = env_sources(self.env_path)
        txt = self.env_path.with_name(self.env_path.name + ".txt")
        step("Fichier des réglages", bool(files), f"lu : {', '.join(str(f) for f in files)}" if files else f"aucun fichier de réglages : {self.env_path}",
             "Les réglages s'enregistrent avec le bouton « Enregistrer » en bas des Réglages." if not files else
             (f"Un fichier « {txt.name} » existe aussi (Windows cache les extensions) : le terminal le lit, mais « .env » l'emporte." if txt.is_file() and self.env_path.is_file() else ""))
        over = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if os.environ.get(k, "").strip()]
        if over:
            step("Variables du système", None, "défini hors du fichier : " + ", ".join(over), "Ces variables l'emportent sur les Réglages : retire-les si elles sont anciennes.")
        ftok, fchat = clean_token(token) if token else "", clean_chat(chat) if chat else ""
        tok, cid = ftok or c.telegram_token, fchat or c.telegram_chat_id
        step("Token enregistré", bool(c.telegram_token), ("…" + c.telegram_token[-4:]) if c.telegram_token else "aucun",
             "" if c.telegram_token else "Colle le token donné par @BotFather, puis « Enregistrer » (ou un test réussi, qui enregistre tout seul).")
        step("Chat id enregistré", bool(c.telegram_chat_id), c.telegram_chat_id or "aucun",
             "" if c.telegram_chat_id else "Écris « bonjour » à ton bot dans Telegram, puis « Trouver mon chat id ».")
        if (ftok and ftok != c.telegram_token) or (fchat and fchat != c.telegram_chat_id):
            step("Formulaire", False, "les valeurs saisies ne sont pas encore enregistrées", "Clique sur « Enregistrer » en bas des Réglages (ou fais un test réussi).")
        if not tok:
            return {"steps": steps, "ok": False}
        if chat_is_bot(cid, tok):
            step("Chat id", False, f"{cid} est le numéro du bot lui-même (le début du token)",
                 "Il faut TON chat id : écris « bonjour » à ton bot dans Telegram, puis clique sur « Trouver mon chat id ».")
        if not token_ok(tok):
            step("Format du token", False, "ne ressemble pas à un token de bot (123456789:AA… : des chiffres, deux-points, puis environ 35 caractères)",
                 "Recopie-le depuis @BotFather : /mybots → ton bot → API Token.")
        tg = TelegramNotifier(tok, cid, c.telegram_api_base, timeout=12)
        ok, me = tg.call("getMe")
        step("Token accepté par Telegram", ok, f"bot @{me.get('username')}" if ok and isinstance(me, dict) else str(me),
             "" if ok else notifier_mod.explain(str(me)))
        if not ok:
            return {"steps": steps, "ok": False}
        okw, wh = tg.call("getWebhookInfo")
        if okw and isinstance(wh, dict) and wh.get("url"):
            step("Webhook", False, f"le bot envoie ses messages à une autre adresse ({wh['url'][:60]}…)",
                 "Les idées partent quand même, mais le bot ne peut pas lire tes messages. Supprime le webhook si tu ne l'utilises pas.")
        if cid:
            okc, ch = tg.call("getChat", {"chat_id": cid})
            name = (ch.get("username") or ch.get("title") or ch.get("first_name") or "") if okc and isinstance(ch, dict) else ""
            step("Conversation trouvée", okc, f"{ch.get('type', '')} {('@' + name) if name and ch.get('username') else name}".strip() if okc else str(ch),
                 "" if okc else notifier_mod.explain(str(ch)))
        t = getattr(self, "tgchat", None)
        if not c.chat_telegram:
            step("Lecture de tes messages", None, "désactivée (Réglages → 7 : « Discuter aussi sur Telegram »)",
                 "Les idées partent quand même ; le bot ne répond simplement pas à tes messages.")
        elif not (c.telegram_on and tok == c.telegram_token and cid == c.telegram_chat_id):
            pass                                                     # rien a lire tant que ces valeurs ne sont pas enregistrees
        elif not self.running:
            step("Lecture de tes messages", None, "démarre avec le terminal")
        elif t and t.last_error:
            step("Lecture de tes messages", False, t.last_error, notifier_mod.explain(t.last_error))
        else:
            step("Lecture de tes messages", bool(t), ("le bot lit tes messages" + (" et Claude répond" if c.chat_key else " (/etat, /idees, /aide)")) if t else "pas démarrée",
                 "" if t else "Redémarre le terminal.")
        last = notifier_mod.last_for(tok, cid)
        if last:
            step("Dernier envoi", bool(last.get("ok")), ("réussi" if last.get("ok") else last.get("detail", "")) + f" ({time.strftime('%d/%m %H:%M', time.localtime(last['t']))})",
                 "" if last.get("ok") else last.get("help", ""))
        return {"steps": steps, "ok": all(x["ok"] is not False for x in steps)}

    def start_background(self):
        """Demarre les flux temps reel (apres la creation : les tests n'ouvrent aucune connexion)."""
        self.running = True
        if self.feed:
            self.feed.start()
        if self.flow:
            self.flow.start()
        for hr in self.heat.values():
            hr.start()
        for kp in self.liqmaps.values():
            kp.start()
        for ts in self.trades.values():
            ts.start()
        self._chat_restart()

    def shutdown(self):
        self.stop.set()
        self.wake.set()
        if self.feed:
            self.feed.stop()
        if self.flow:
            self.flow.stop()
        for hr in self.heat.values():
            hr.stop()
        for kp in self.liqmaps.values():
            kp.stop()
        for ts in self.trades.values():
            ts.stop()
            try:
                ts.flush()                                   # le jour en cours est sauvegarde : rien a retelecharger au redemarrage
            except Exception:
                pass
        if self.tgchat:
            self.tgchat.close()

    # ---------- V36 : mêmes réglages sur tous tes ordinateurs (prefsync.py) ----------
    def _pull_env_at_start(self, cfg):
        """Au démarrage : les réglages (sans secret) changés sur un autre ordinateur depuis la dernière fois sont repris."""
        self.prefs = PrefSync(cfg.data_dir, self.env_path, cfg.sync_dir)
        try:
            self.prefs.align()
            upd = self.prefs.env_to_apply()
            if upd and self.env_path.exists():
                write_env(self.env_path, upd)
                new = load_config(self.env_path)
                new.port, new.host, new.data_dir = cfg.port, cfg.host, cfg.data_dir
                self.prefs.align()
                return new
        except Exception:                                            # une copie illisible n'empêche jamais le démarrage
            pass
        return cfg

    def pull_env(self, force: bool = False) -> bool:
        """Réglages changés sur un autre ordinateur : appliqués ici (au plus toutes les 20 secondes). True s'il y a eu un changement."""
        if not force and time.time() - self._env_check < 20:
            return False
        self._env_check = time.time()
        with self.prefs_lock:
            upd = self.prefs.env_to_apply()
            if not upd or not self.env_path.exists():
                return False
            write_env(self.env_path, upd)
        cfg = load_config(self.env_path)
        cfg.port, cfg.host, cfg.data_dir = self.cfg.port, self.cfg.host, self.cfg.data_dir
        self.reload(cfg)
        return True

    def prefs_state(self) -> dict:
        applied = False
        try:
            applied = self.pull_env()
        except Exception:
            pass
        ui = self.prefs.newest("ui")
        return {**self.prefs.status(), "envApplied": applied, "uiData": ui["data"] if ui else None}

    def prefs_put(self, body: dict) -> dict:
        data = body.get("data")
        if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise ValueError("réglages illisibles")
        with self.prefs_lock:
            e = self.prefs.put("ui", data, body.get("t"))
        return {"t": e["t"], "from": e["from"], "mine": e["from"] == self.prefs.device, "data": None if e["from"] == self.prefs.device else e["data"]}

    def prefs_sync_dir(self, body: dict) -> dict:
        """Choix du dossier synchronisé (vide : plus de synchronisation). Les deux copies prennent ensuite la version la plus récente."""
        d = str(body.get("dir") or "").strip()
        if d:
            p = Path(os.path.expanduser(d))
            if not p.is_dir():
                raise ValueError("dossier introuvable sur cet ordinateur : vérifie le chemin (ou installe l'application de ton cloud)")
            try:
                (p / "LiqTerminal").mkdir(exist_ok=True)
            except OSError as e:
                raise ValueError(f"impossible d'écrire dans ce dossier : {e.strerror or e}")
            d = str(p)
        write_env(self.env_path, {"TERMINAL_SYNC_DIR": d})
        self.cfg.sync_dir = d
        with self.prefs_lock:
            self.prefs.sync_dir = d
            self.prefs.align()
            if d and not self.prefs.newest("env"):
                self.prefs.push_env()
        self._env_check = 0.0
        return self.prefs_state()

    def prefs_export(self) -> dict:
        ui = self.prefs.newest("ui")
        from prefsync import read_env
        return {"v": 1, "app": "Liq Terminal", "exported": int(time.time() * 1000), "from": self.prefs.device,
                "ui": ui["data"] if ui else {}, "env": read_env(self.env_path)}

    def prefs_import(self, body: dict) -> dict:
        doc = body.get("doc")
        if not isinstance(doc, dict) or not isinstance(doc.get("ui"), dict):
            raise ValueError("ce fichier n'est pas un export des réglages du terminal")
        ui = {k: v for k, v in doc["ui"].items() if isinstance(k, str) and isinstance(v, str)}
        env = {k: str(v) for k, v in (doc.get("env") or {}).items() if isinstance(k, str) and env_shareable(k) and "\n" not in str(v)}
        with self.prefs_lock:
            self.prefs.put("ui", ui)
            if env:
                write_env(self.env_path, env)
                self.prefs.push_env()
        if env:
            cfg = load_config(self.env_path)
            cfg.port, cfg.host, cfg.data_dir = self.cfg.port, self.cfg.host, self.cfg.data_dir
            self.reload(cfg)
        return self.prefs_state()

    def funding_rows(self, sym: str, t0: int) -> tuple:
        """V35 : versements de funding de Binance depuis t0 (ms), gardés en mémoire : on ne redemande que la suite (toutes les 5 minutes)
        ou le début manquant. Rend (versements, erreur)."""
        with self.fund_lock:
            c = self._fund.get(sym) or {"rows": [], "from": None, "at": 0.0, "err": None, "tried": 0.0}
            self._fund[sym] = c
            wall = time.time()
            if wall - c["tried"] < (60 if c["err"] else 0):
                return c["rows"], c["err"]
            try:
                now = self.source.now_ms()
                if c["from"] is None or t0 < c["from"]:
                    old = c["rows"]
                    got = self.source.funding_history(sym, t0, (old[0][0] - 1) if old else now)
                    c["rows"] = sorted({t: r for t, r in list(got) + list(old)}.items())
                    c["from"], c["at"] = t0, wall
                elif wall - c["at"] > 300:
                    last = c["rows"][-1][0] if c["rows"] else t0
                    got = self.source.funding_history(sym, last + 1, now)
                    c["rows"] = sorted({t: r for t, r in list(c["rows"]) + list(got)}.items())
                    c["at"] = wall
                c["err"] = None
            except Exception as e:                                   # réseau, source sans historique : on garde ce qu'on a
                c["err"] = f"{type(e).__name__}: {str(e)[:120]}"
            c["tried"] = wall
            return c["rows"], c["err"]

    def spot_rows(self, sym: str, tf: str, t0: int) -> tuple:
        """V37 : bougies SPOT de la même paire depuis t0, gardées en mémoire ; on ne redemande que la fin (au plus toutes les 20 secondes)
        ou le début manquant. Rend (bougies, erreur)."""
        from data.store import merge
        with self.fund_lock:
            c = self._spot.get((sym, tf)) or {"rows": [], "from": None, "at": 0.0, "err": None, "tried": 0.0}
            self._spot[(sym, tf)] = c
            wall = time.time()
            if wall - c["tried"] < (60 if c["err"] else 20):
                return c["rows"], c["err"]
            c["tried"] = wall
        try:
            now = self.source.now_ms()
            rows = list(c["rows"])
            if c["from"] is None or t0 < c["from"]:
                rows = self.source.spot_candles(sym, tf, t0, now)
                frm = t0
            else:
                tail = self.source.spot_candles(sym, tf, rows[-1].t if rows else t0, now)
                merge(rows, tail)
                frm = c["from"]
            rows = rows[-6000:]
            with self.fund_lock:
                c.update(rows=rows, err=None, at=wall, **{"from": frm})
        except Exception as e:                                       # spot injoignable : le perpétuel reste affiché
            with self.fund_lock:
                c["err"] = f"{type(e).__name__}: {str(e)[:120]}"
        return c["rows"], c["err"]

    def agg_funding(self, sym: str, prem: dict, oi_now, hours) -> dict | None:
        """V37 : funding en cours de Binance, Bybit, OKX et Hyperliquid, pondéré par l'intérêt ouvert (dollars) de chacune."""
        from engine import subcharts
        rows = []
        if prem.get("funding") is not None and oi_now and prem.get("mark"):
            rows.append({"ex": "Binance", "funding": prem["funding"], "intervalH": hours or 8.0, "oiUsd": oi_now[1] * prem["mark"]})
        ext = getattr(self.service, "ext", None)
        try:
            snap = ((ext.derivs.get("perps") or {}).get(sym) or {}) if ext is not None else {}
            rows += [r for r in snap.get("rows") or [] if isinstance(r, dict)]
        except Exception:
            pass
        return subcharts.aggregate_funding(rows)

    POS_WINDOW = {"1m": 60, "5m": 48, "15m": 32, "1h": 24, "4h": 18, "1d": 14, "1w": 8, "1M": 6}

    def indicators(self, sym: str, tf: str, fund: bool = False, spot: bool = False) -> dict:
        """V30 : sous le graphique, l'interet ouvert en bougies (releves de l'adresse Binance, 29 jours, des archives de la carte des
        liquidations, plusieurs mois, et V33 : des archives depuis decembre 2021, une valeur par heure) et le delta de chaque bougie avec son cumul (CVD), pour les memes bougies que le graphique."""
        from engine import subcharts
        from engine.atr import INTERVAL_MS
        m = self.service.markets.get(sym)
        if m is None:
            raise KeyError(f"symbole inconnu : {sym}")
        if tf not in TFS:
            raise KeyError(f"timeframe inconnu : {tf}")
        if not m.ready:
            return {"symbol": sym, "tf": tf, "ready": False}
        with self.service.lock:
            cs = m.chart_candles(tf)[-chart_bars(tf):]
            live = dict(m.store.oi)
            oi_now = m.store.oi_now
            prem = dict(m.store.ctx.get("premium") or {})
        fr, ferr = self.funding_rows(sym, cs[0].t) if (fund and cs) else ([], None)
        sp, serr = self.spot_rows(sym, tf, cs[0].t) if (spot and cs) else ([], None)
        kp = self.liqmaps.get(sym)
        arch = kp.archive.points() if kp is not None and kp.archive is not None else {}
        deep = kp.deep.points() if kp is not None and kp.deep is not None else {}
        if deep:                                                     # V33 : années précédentes, une valeur par heure (les relevés 5 minutes passent devant)
            arch = {**deep, **arch}
        key = (sym, tf, len(cs), cs[-1].t if cs else 0, cs[-1].c if cs else 0, cs[-1].v if cs else 0, len(live), len(arch), fund, len(fr),
               prem.get("funding"), ferr, tuple(oi_now) if oi_now else None, spot, len(sp), sp[-1].v if sp else 0, serr)
        hit = self._ind_cache.get((sym, tf, fund, spot))
        if hit and hit[0] == key:
            return hit[1]
        now = self.source.now_ms()
        ts, vs = subcharts.merge_points(live, arch, oi_now, now)     # V37 : + l'intérêt ouvert à l'instant
        times = [k.t for k in cs]
        oi = subcharts.oi_candles(times, INTERVAL_MS[tf], ts, vs)
        d, cvd = subcharts.deltas(cs)
        du, exact = subcharts.deltas_usd(cs)                         # V37 : delta en dollars (exact quand Binance le donne)
        win = self.POS_WINDOW.get(tf, 24)
        pos = subcharts.positions(cs, oi, d, win)                    # V37 : qui ouvre, qui ferme
        out = {"symbol": sym, "tf": tf, "ready": True, "unit": sym.replace("USDT", ""), "times": [t // 1000 for t in times],
               "oi": oi, "delta": d, "cvd": cvd, "deltaUsd": du, "deltaExact": exact, "close": [k.c for k in cs],
               "oiSince": ts[0] if ts else None, "realDelta": any(x is not None for x in d),
               "oiLive": bool(oi_now and ts and ts[-1] == int(oi_now[0])), "oiAt": ts[-1] if ts else None, **pos}
        if spot:                                                     # V37 : delta et CVD du marché spot (Binance)
            sd, sdu = subcharts.align_spot(times, sp)
            out.update(spotDelta=sd, spotDeltaUsd=sdu, spotErr=serr, spotOk=any(x is not None for x in sd))
        if fund:                                                     # V35 : funding de chaque bougie (% par 8 h), barre en cours estimée
            out.update(subcharts.funding_bars(times, INTERVAL_MS[tf], fr, prem.get("funding") if fr else None, now, prem.get("next_funding")))
            out.update(fundNext=prem.get("next_funding"), fundErr=ferr, fundEx="Binance",
                       fundAgg=self.agg_funding(sym, prem, oi_now, out.get("fundHours")))
            last_f = next((v for v in reversed(out["funding"]) if v is not None), None)
            out["posNote"] = subcharts.crowding(pos["posSum"], last_f)
        self._ind_cache[(sym, tf, fund, spot)] = (key, out)
        return out

    def size_flow(self, sym: str, tf: str) -> dict:
        """V39 : delta en dollars par TAILLE d'ordre (moins de 1 000 $ ... plus d'un million), perpetuel et spot Binance, pour les memes
        bougies que le graphique (engine/sizeflow.py). Mode simule : repartition fabriquee a partir du delta des bougies."""
        from engine import sizeflow
        from engine.atr import INTERVAL_MS
        m = self.service.markets.get(sym)
        if m is None:
            raise KeyError(f"symbole inconnu : {sym}")
        if tf not in TFS:
            raise KeyError(f"timeframe inconnu : {tf}")
        if not m.ready:
            return {"symbol": sym, "tf": tf, "ready": False}
        with self.service.lock:
            cs = m.chart_candles(tf)[-chart_bars(tf):]
        if not cs:
            return {"symbol": sym, "tf": tf, "ready": False}
        step, times = INTERVAL_MS[tf], [k.t for k in cs]
        perp, spot = self.trades.get(sym), self.trades.get(f"{sym}:spot")
        hist = {m: self.trades.get(f"{sym}:hist:{m}") for m in ("perp", "spot")}
        key = (sym, tf, len(cs), times[-1], cs[-1].v, perp.flow.version if perp else None, spot.flow.version if spot else None,
               tuple(len(h.done) if h else None for h in hist.values()), int(time.time() // 10))
        hit = self._size_cache.get((sym, tf))
        if hit and hit[0] == key:
            return hit[1]
        out = {"symbol": sym, "tf": tf, "ready": True, "times": [t // 1000 for t in times], "edges": list(sizeflow.EDGES),
               "names": sizeflow.NAMES, "groups": [[n, d, list(c)] for n, d, c in sizeflow.GROUPS]}
        if self.cfg.source != "binance":
            out["perp"] = {**sizeflow.simulated(cs, 7), "ok": True, "simulated": True}
            sp, serr = self.spot_rows(sym, tf, cs[0].t)
            if sp:
                idx = {k.t: k for k in sp}
                al = [idx.get(t) for t in times]
                sim = sizeflow.simulated([k or cs[i] for i, k in enumerate(al)], 11)
                for c in range(sizeflow.NCLS):
                    sim["delta"][c] = [v if al[i] is not None else None for i, v in enumerate(sim["delta"][c])]
                out["spot"] = {**sim, "ok": True, "simulated": True}
            else:
                out["spot"] = {"ok": False, "why": serr or "pas de bougie spot"}
        else:
            for name, ts in (("perp", perp), ("spot", spot)):
                if ts is None:
                    out[name] = {"ok": False, "why": "désactivé (réglage des jours de transactions à 0)" if name == "spot" else "transactions exactes désactivées"}
                    continue
                h = hist.get(name)
                ser = sizeflow.combined(times, step, [ts.flow, h.flow if h else None])      # V40.1 : la minute, puis l'historique a l'heure
                st = ts.status()
                ok = any(v is not None for v in ser["delta"][0])
                out[name] = {**ser, "ok": ok, "state": st.get("state"), "days": st.get("days"), "complete": st.get("complete"),
                             "error": st.get("error"), "why": None if ok else f"téléchargement des transactions en cours ({st.get('state')})",
                             "hist": h.status() if h else None}
        self._size_cache[(sym, tf)] = (key, out)
        return out

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
                for k, ts in self.trades.items():                # V40.1 : jours d'historique du flux par taille, sans redemarrer
                    if ":hist:" in k:
                        ts.days = getattr(cfg, "sizeflow_history_days", ts.days)
                        if self.running:
                            ts.start()
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
        self.reading_cycle(service, list(states))

    def reading_cycle(self, service, symbols):
        """Une lecture par jour et par paire (historique des analyses), puis le prix 24 h / 3 j / 7 j apres les lectures passees."""
        try:
            now = self.source.now_ms()
            for s in symbols:
                if self.readings.due(s, now):
                    self.readings.record(s, now, readings_mod.snapshot(service.lecture(s)))
            self.readings.evaluate(lambda sym, t: service.markets[sym]._price_at(t) if sym in service.markets else None, now)
            service.errors.pop("lectures", None)
        except Exception as e:
            service.errors["lectures"] = f"{type(e).__name__}: {e}"

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
            for s in symbols:                                       # journal d'avant V24 : moments cles retrouves sur les bougies 5 min gardees
                if any(t["symbol"] == s and t.get("v", 1) < 2 for t in self.desk.trades):
                    self.desk.backfill(s, service.all_m5(s), now)
            self.desk.run_cycle(sigs, m5s, now)
            service.errors.pop("idees", None)
        except Exception as e:
            service.errors["idees"] = f"{type(e).__name__}: {e}"

    def refresh_loop(self):
        while not self.stop.is_set():
            t0 = time.time()
            self.service.refresh_all()
            self.macro_week_tick()
            self.macro_month_tick()
            self.wake.clear()
            self.wake.wait(max(1.0, self.cfg.refresh_seconds - (time.time() - t0)))

    # --- bilan macro de la semaine (V18) ---
    def macro_week_tick(self, force: bool = False) -> None:
        """Toutes les 30 minutes : le bilan de la semaine en cours est recalcule et archive (une version par semaine, meme sans ouvrir la page).
        Si l'option est cochee, il part sur Telegram le samedi a partir de 8 h UTC (les chiffres americains de la semaine sont sortis)."""
        now = time.time()
        ext = self.service.ext
        fred_t = (ext.updated.get("fred"), ext.updated.get("calendar")) if ext else None
        if not force and now - getattr(self, "_mw_tick", 0) < 1800 and fred_t == getattr(self, "_mw_src", None):
            return
        self._mw_tick, self._mw_src = now, fred_t
        try:
            rep = self.service.macro_week()
        except Exception as e:
            self.service.errors["bilan macro"] = f"{type(e).__name__}: {str(e)[:120]}"
            return
        self.service.errors.pop("bilan macro", None)
        due = rep["start"] + 5 * 86_400_000 + 8 * 3_600_000
        if self.cfg.macro_week_telegram and self.cfg.telegram_on and not rep.get("sentAt") and self.service.source.now_ms() >= due:
            from alerts.assistant import split_text
            try:
                for part in split_text(rep["summary"]):
                    self.notifier.send(part)
                self.service.macro_week_mark_sent(rep["week"], now)
            except Exception as e:
                self.service.errors["bilan macro Telegram"] = f"{type(e).__name__}: {str(e)[:120]}"

    # --- analyse macro du mois (V25) ---
    def macro_month_tick(self, force: bool = False) -> None:
        """Toutes les 30 minutes : l'analyse du mois en cours est recalculee et archivee. Si l'option est cochee, l'analyse du mois ecoule
        part sur Telegram le 1er du mois a partir de 8 h UTC (une seule fois)."""
        from engine import macromonth
        now = time.time()
        ext = self.service.ext
        src = tuple((ext.updated or {}).get(k) for k in ("fred", "fed", "imf")) if ext else None
        if not force and now - getattr(self, "_mm_tick", 0) < 1800 and src == getattr(self, "_mm_src", None):
            return
        self._mm_tick, self._mm_src = now, src
        try:
            self.service.macro_month()
        except Exception as e:
            self.service.errors["analyse du mois"] = f"{type(e).__name__}: {str(e)[:120]}"
            return
        self.service.errors.pop("analyse du mois", None)
        cur = macromonth.month_start(self.service.source.now_ms())
        if not (self.cfg.macro_month_telegram and self.cfg.telegram_on) or self.service.source.now_ms() < cur + 8 * 3_600_000:
            return
        key = macromonth.month_key(cur - 86_400_000)
        try:
            rep = self.service.macro_month(key)
        except (KeyError, ValueError):
            return
        if rep.get("sentAt"):
            return
        from alerts.assistant import split_text
        try:
            for part in split_text(rep["summary"]):
                self.notifier.send(part)
            self.service.macro_month_mark_sent(key, now)
        except Exception as e:
            self.service.errors["analyse du mois Telegram"] = f"{type(e).__name__}: {str(e)[:120]}"

    def macro_month_research(self, key: str | None) -> dict:
        """Recherche de Claude pour le mois : rapports des grandes banques, discussion au sein de la Fed, projections ; tableau des banques."""
        from alerts.assistant import MONTH_PROMPT
        from engine import macromonth
        rep = self.service.macro_month(key)
        res = self.assistant.ask(MONTH_PROMPT, src="mois", context=rep["summary"], web_uses=10)
        if res.get("ok"):
            text, rows = macromonth.parse_banks(res["answer"])
            self.service.macro_month_banks(rep["month"], {"text": text, "rows": rows, "t": int(time.time() * 1000), "usd": round(res.get("usd", 0.0), 4),
                                                          "model": res.get("model")})
        return {**res, "month": rep["month"]}

    def macro_week_comment(self, key: str | None) -> dict:
        """Commentaire de Claude sur une semaine : rapports, geopolitique, institutionnels (recherche web), a partir du bilan chiffre."""
        from alerts.assistant import WEEK_PROMPT
        rep = self.service.macro_week(key)
        res = self.assistant.ask(WEEK_PROMPT, src="bilan", context=rep["summary"], web_uses=6)
        if res.get("ok"):
            self.service.macro_week_comment(rep["week"], {"text": res["answer"], "t": int(time.time() * 1000), "usd": round(res.get("usd", 0.0), 4),
                                                         "model": res.get("model")})
        return {**res, "week": rep["week"]}

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

    # --- fichiers remplaces pendant que le terminal tourne (V17.1) ---
    def start_code_watch(self, every: float = 15.0):
        """Surveille les fichiers Python : si une nouvelle version est copiee dans le dossier (ZIP extrait par-dessus, git pull...), le terminal
        redemarre tout seul quand il est lance par run.py ; sinon la page affiche un bandeau « relance le terminal »."""
        self.code_sig = code_signature()
        threading.Thread(target=self._code_watch, args=(every,), daemon=True).start()

    def code_check(self, prev: str | None) -> str | None:
        """Un passage de la surveillance. Renvoie l'empreinte vue. Il faut la meme empreinte nouvelle deux fois de suite (copie terminee)."""
        try:
            sig = code_signature()
        except OSError:
            return prev
        if sig == self.code_sig or sig != prev or self.upd_lock.locked():   # inchange, copie en cours, ou installation par updater.py
            return sig
        if not self.code_stale:
            self.code_stale = True
            print("\n== Une nouvelle version du terminal a été copiée dans le dossier"
                  + (" : redémarrage automatique ==\n" if self.updates_on else " : ferme cette fenêtre et relance le terminal pour l'utiliser ==\n"), flush=True)
        if self.updates_on:
            self.request_restart()
        return sig

    def _code_watch(self, every: float):
        prev = self.code_sig
        while not self.stop.wait(every) and not self.restart_requested:
            prev = self.code_check(prev)

    def request_restart(self, delay: float = 2.0) -> bool:
        """Arrete proprement le serveur pour que run.py le relance avec la nouvelle version. Sans run.py (lancement manuel), la version s'applique au prochain demarrage."""
        if self.restart_requested:
            return True
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

    # --- historique des idees (V24) ---
    def history(self):
        """Journal complet avec recit de chaque idee, statistiques par categorie et ce que le backtest attendait pour chaque paire."""
        syms = sorted({t["symbol"] for t in self.desk.trades} | set(self.cfg.symbols))
        expect = {}
        for s in syms:
            try:
                expect[s] = reports_mod.terminal_expect(self.service.report_dirs, s)
            except Exception:
                expect[s] = None
        prices = {s: self.service.last_price(s) for s in syms}
        return self.desk.history(self.source.now_ms(), lev=self.cfg.signal_leverage, expect=expect, prices=prices)

    def trade_detail(self, tid: str):
        """Fiche d'une idee : bougies autour de l'idee (5 min tant qu'elles sont gardees, sinon 1 h), niveaux, moments cles, recit,
        et ce que le prix a fait dans les 48 heures apres la fin."""
        from alerts import journal
        tr = next((t for t in self.desk.trades if t["id"] == tid), None)
        if tr is None:
            raise KeyError(f"idée introuvable : {tid}")
        now = self.source.now_ms()
        a, b, end = journal.window(tr, now)
        finest, rows = self.service.trade_candles(tr["symbol"], a, max(b, min(now, end + journal.AFTER_H * 3_600_000)))
        p = journal.path(tr, rows, finest, now)
        pnow = self.service.last_price(tr["symbol"]) if tr["status"] in ("active", "tp1") else None
        return {"id": tid, "symbol": tr["symbol"], **p, "story": journal.story(tr, lev=tr.get("lev") or self.cfg.signal_leverage, price_now=pnow),
                "source": "5 minutes" if finest == 300_000 else "1 heure (bougies 5 minutes plus conservées pour cette période)"}

    # --- reglages ---
    def settings(self):
        c = self.cfg
        tok = c.telegram_token
        return {"source": c.source, "symbols": list(c.symbols),
                "telegram": {"configured": c.telegram_on, "tokenHint": ("..." + tok[-4:]) if tok else "",
                             "chatId": c.telegram_chat_id, "envFile": str(self.env_path), **self.telegram_state()},
                "alertMinScore": c.alert_min_score, "alertTf": c.alert_tf, "alertCooldownHours": c.alert_cooldown_hours,
                "alertMode": c.alert_mode, "alertSweep": c.alert_sweep, "alertMacro": c.alert_macro, "alertZones": c.alert_zones, "historyYears": c.history_years,
                "footprintDays": c.footprint_days, "sizeHistDays": getattr(c, "sizeflow_history_days", 180), "trades": {s: t.status() for s, t in getattr(self, "trades", {}).items()},
                "signalOn": c.signal_on, "signalMinScore": c.signal_min_score, "signalMaxWeek": c.signal_max_week, "signalMaxPerSymbol": c.signal_max_per_symbol,
                "signalLeverage": c.signal_leverage, "signalTrendGate": c.signal_trend_gate, "signalDirection": c.signal_direction, "signalOpposite": c.signal_opposite,
                "macroWeekTelegram": c.macro_week_telegram, "macroMonthTelegram": c.macro_month_telegram,
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
            tok = clean_token(body["telegramToken"])                 # V25 : espaces, prefixe « bot » ou adresse de l'API retires
            if not token_ok(tok):
                raise ValueError("token Telegram invalide : il ressemble à 123456789:AAH… (des chiffres, deux-points, puis environ 35 caractères), tel que donné par @BotFather")
            upd["TELEGRAM_BOT_TOKEN"] = tok
        if "telegramChatId" in body:
            cid = clean_chat(body["telegramChatId"])
            if cid and not chat_ok(cid):
                raise ValueError("chat id invalide : un nombre (123456789, ou -100… pour un groupe ou un canal) ou @nom_du_canal")
            if chat_is_bot(cid, upd.get("TELEGRAM_BOT_TOKEN") or self.cfg.telegram_token):
                raise ValueError("ce chat id est le numéro de ton bot (le début du token), pas le tien : écris « bonjour » à ton bot dans Telegram, "
                                 "puis clique sur « Trouver mon chat id »")
            upd["TELEGRAM_CHAT_ID"] = cid
        if body.get("alertMinScore") is not None:
            upd["TERMINAL_ALERT_MIN_SCORE"] = str(max(2, min(6, int(body["alertMinScore"]))))
        if body.get("alertCooldownHours") is not None:
            upd["TERMINAL_ALERT_COOLDOWN_HOURS"] = str(max(0.5, min(48.0, float(body["alertCooldownHours"]))))
        if body.get("alertTf") in ALERT_TFS:
            upd["TERMINAL_ALERT_TF"] = body["alertTf"]
        if body.get("alertSweep") is not None:
            upd["TERMINAL_ALERT_SWEEP"] = "1" if body["alertSweep"] else "0"
        if body.get("historyYears") is not None:
            upd["TERMINAL_HISTORY_YEARS"] = str(max(0, min(10, int(body["historyYears"]))))
        if body.get("sizeHistDays") is not None:
            upd["TERMINAL_SIZEFLOW_HISTORY_DAYS"] = str(max(0, min(1500, int(body["sizeHistDays"]))))
        if body.get("footprintDays") is not None:
            upd["TERMINAL_FOOTPRINT_DAYS"] = str(max(0, min(400, int(body["footprintDays"]))))
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
        if body.get("signalDirection") in ("long", "short", "both"):
            upd["TERMINAL_SIGNAL_DIRECTION"] = body["signalDirection"]
        if body.get("signalOpposite") in ("hedge", "never"):
            upd["TERMINAL_SIGNAL_OPPOSITE"] = body["signalOpposite"]
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
        if body.get("macroWeekTelegram") is not None:
            upd["TERMINAL_MACRO_WEEK_TELEGRAM"] = "1" if body["macroWeekTelegram"] else "0"
        if body.get("macroMonthTelegram") is not None:
            upd["TERMINAL_MACRO_MONTH_TELEGRAM"] = "1" if body["macroMonthTelegram"] else "0"
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
        try:                                                         # V36 : les réglages sans secret partent vers tes autres ordinateurs
            with self.prefs_lock:
                self.prefs.push_env()
        except Exception:
            pass
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
            if app.code_stale:
                self.send_header("X-Terminal-Stale", "1")
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
                    return self._json(app.service.get_state(sym, tf, (q.get("gexScope") or ["all"])[0], (q.get("gexSrc") or ["all"])[0]))
                if u.path == "/api/config":
                    c = app.cfg
                    return self._json({"symbols": list(c.symbols), "tfs": list(TFS), "alertTfs": list(ALERT_TFS), "source": c.source,
                                       "heatmapSymbols": sorted(app.heat), "liqmapSymbols": sorted(app.liqmaps), "heatmapDays": c.heatmap_days,
                                       "telegram": c.telegram_on, "telegramState": app.telegram_state(), "alertTf": c.alert_tf, "alertMinScore": c.alert_min_score,
                                       "alertMaxDistAtr": c.alert_max_dist_atr, "refresh": c.refresh_seconds,
                                       "anchor": c.anchor_date, "statsK": c.stats_k, "statsHorizon": c.stats_horizon,
                                       "historyYears": c.history_years,
                                       "csrf": app.token, "wsBase": c.binance_ws if c.source == "binance" else "",
                                       "cbWs": c.coinbase_ws if c.source == "binance" else "",
                                       "version": VERSION, "api": API_LEVEL, "supervised": app.updates_on, "stale": app.code_stale})
                if u.path == "/api/vp":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.get_vp(sym, (q.get("tf") or ["1h"])[0]))
                if u.path == "/api/vps":
                    return self._json({**app.service.vp_state, "auto": {tf: list(v) for tf, v in __import__("engine.vpx", fromlist=["x"]).AUTO_BY_TF.items()}})
                if u.path == "/api/macroweek":
                    return self._json(app.service.macro_week((q.get("week") or [None])[0] or None))
                if u.path == "/api/macroweeks":
                    return self._json(app.service.macro_weeks())
                if u.path == "/api/macromonth":
                    return self._json(app.service.macro_month((q.get("month") or [None])[0] or None))
                if u.path == "/api/macromonths":
                    return self._json(app.service.macro_months())
                if u.path == "/api/tpo":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    gi = lambda k: int(float((q.get(k) or ["0"])[0] or 0)) or None
                    return self._json(app.service.get_tpo(sym, (q.get("kind") or ["D"])[0], gi("n"), gi("rows")))
                if u.path == "/api/mtf":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.get_mtf(sym, (q.get("tf") or ["1h"])[0]))
                if u.path == "/api/series":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.service.get_series(sym, (q.get("tf") or ["1h"])[0]))
                if u.path == "/api/overview":
                    o = app.service.overview()
                    o["alerts"] = [{"t": a["t"], "text": a["text"].split("\n")[0], "sent": a.get("sent")} for a in app.alerts.log[-6:][::-1]]
                    o["feed"] = app.feed.status() if app.feed else None
                    o["flow"] = app.flow.status() if app.flow else None
                    o["trades"] = {s: t.status() for s, t in app.trades.items()}
                    o["errors"] = app.service.errors
                    d = app.desk.public(app.source.now_ms())
                    o["week"], o["tradeStats"], o["openTrades"] = d["week"], d["stats"], [t for t in d["trades"] if t["status"] in ("pending", "active", "tp1")]
                    o["bias"] = d["bias"]
                    for card in o.get("symbols") or []:                         # V25.3 : l'idee du moment est-elle partie ? sinon pourquoi
                        if card.get("idea") and card["idea"].get("side"):
                            card["idea"] = {**card["idea"], "send": app.idea_state(card["symbol"], card["idea"])}
                    return self._json(o)
                if u.path == "/api/signals":
                    syms = [(q.get("symbol") or [""])[0].upper()] if (q.get("symbol") or [""])[0] else list(app.service.markets)
                    for sy in syms:
                        if sy not in app.service.markets:
                            raise KeyError(f"symbole inconnu : {sy}")
                    return self._json({"symbols": {sy: app.signals_with_state(sy) for sy in syms}, "desk": app.desk.public(app.source.now_ms()),
                                       "on": app.cfg.signal_on, "direction": app.cfg.signal_direction})
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
                    lec = app.service.lecture(sym)
                    idea = lec.get("idea")
                    return self._json({**lec, "deskBias": app.desk.bias(app.source.now_ms()),
                                       "ideaSend": app.idea_state(sym, idea) if idea and idea.get("side") else None})
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
                if u.path == "/api/heatmap":                         # V28 : heatmap du carnet (temps x prix)
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    hr = app.heat.get(sym)
                    if hr is None:
                        return self._json({"ready": False, "symbol": sym, "off": True,
                                           "why": "heatmap désactivée pour cette paire (réglage TERMINAL_HEATMAP)" if sym in app.cfg.symbols else "paire inconnue"})
                    f1 = lambda k, d: float((q.get(k) or [d])[0])
                    ex = [e for e in (q.get("ex") or [",".join(heat_mod.EXCHANGES)])[0].split(",") if e in heat_mod.EXCHANGES]
                    out = hr.book.query(int(f1("t0", 0)), int(f1("t1", 0)), f1("lo", 0), f1("hi", 0), int(f1("cols", 300)), int(f1("rows", 250)), ex)
                    out.update(symbol=sym, since=hr.book.since(), step=hr.book.step, status=hr.status(), exchanges=ex, long=hr.long_status())
                    return self._json(out)
                if u.path == "/api/indicators":                      # V30 : interet ouvert en bougies, delta et CVD sous le graphique
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.indicators(sym, (q.get("tf") or ["1h"])[0], (q.get("fund") or ["0"])[0] == "1",
                                                     (q.get("spot") or ["0"])[0] == "1"))
                if u.path == "/api/gex":                             # V40 : onglet GEX (options BTC)
                    return self._json(app.service.gex_page((q.get("scope") or ["all"])[0], (q.get("src") or ["all"])[0]))
                if u.path == "/api/sizeflow":                        # V39 : delta par taille d'ordre, perpétuel et spot
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    return self._json(app.size_flow(sym, (q.get("tf") or ["1h"])[0]))
                if u.path == "/api/liqmap":                          # V29 : carte des liquidations sur plusieurs mois (estimée)
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    kp = app.liqmaps.get(sym)
                    if kp is None:
                        return self._json({"ready": False, "symbol": sym, "off": True,
                                           "why": "carte coupée (TERMINAL_HEATMAP_DAYS=0)" if sym in app.cfg.symbols else "paire inconnue"})
                    f1 = lambda k, d: float((q.get(k) or [d])[0])
                    mp = kp.map
                    out = mp.query(int(f1("t0", 0)), int(f1("t1", 0)), f1("lo", 0), f1("hi", 0), int(f1("cols", 300)), int(f1("rows", 250)),
                                   app.service.last_price(sym)) if mp else {"ready": False, "why": "carte en préparation"}
                    out.update(symbol=sym, status=kp.status(), unit=sym.upper().replace("USDT", ""))
                    return self._json(out)
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
                if u.path == "/api/flow":
                    sym = (q.get("symbol") or [app.cfg.symbols[0]])[0].upper()
                    if sym not in app.service.markets:
                        raise KeyError(f"symbole inconnu : {sym}")
                    if not app.flow:
                        return self._json({"symbol": sym, "ready": False, "off": True, "rows": [], "big": [],
                                           "why": "flux d'ordres désactivé (TERMINAL_ORDERFLOW=0 ou flux temps réel coupé)"})
                    f1 = lambda k, d: float((q.get(k) or [d])[0] or d)
                    center = f1("center", 0.0) or None
                    return self._json(app.flow.ladder(sym, f1("step", 0.0), int(f1("rows", 60)), center, int(f1("since", 0))))
                if u.path == "/api/price":
                    return self._json(app.live_price((q.get("symbol") or [app.cfg.symbols[0]])[0].upper()))
                if u.path == "/api/settings":
                    return self._json(app.settings())
                if u.path == "/api/prefs":                           # V36
                    return self._json(app.prefs_state())
                if u.path == "/api/prefs/export":
                    return self._json(app.prefs_export())
                if u.path == "/api/update":
                    return self._json(app.update_status())
                if u.path == "/api/history":
                    return self._json({**app.history(), "readings": app.readings.public(), "direction": app.cfg.signal_direction,
                                       "opposite": getattr(app.cfg, "signal_opposite", "hedge"),
                                       "since": int(app.started * 1000), "source": app.cfg.source, "symbols": list(app.cfg.symbols)})
                if u.path == "/api/history/trade":
                    return self._json(app.trade_detail((q.get("id") or [""])[0]))
                if u.path == "/api/chat":
                    t = app.tgchat
                    return self._json({**app.assistant.status(), "history": app.assistant.history(),
                                       "telegramListening": bool(t), "telegramError": t.last_error if t else None})
                if u.path == "/api/alerts":
                    return self._json({"telegram": app.cfg.telegram_on, "log": app.alerts.log[-20:][::-1],
                                       "errors": app.service.errors})
                if u.path == "/api/health":
                    return self._json({"ok": True, "uptime": time.time() - app.started, "version": VERSION, "api": API_LEVEL, "root": str(ROOT),
                                       "stale": app.code_stale,
                                       "ready": {s: m.ready for s, m in app.service.markets.items()},
                                       "errors": app.service.errors, "lastUpdate": app.service.last_update,
                                       "feed": app.feed.status() if app.feed else None,
                                       "trades": {s: t.status() for s, t in app.trades.items()}})
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
                path = urlparse(self.path).path
                cap = 1_000_000 if path.startswith("/api/prefs") else 20000      # V36 : les réglages de la page peuvent dépasser 20 Ko
                body = json.loads(self.rfile.read(min(n, cap)).decode("utf-8") or "{}") if n else {}
                if path == "/api/settings":
                    return self._json(app.save_settings(body))
                if path == "/api/prefs":                             # V36 : réglages de la page, gardés et partagés entre ordinateurs
                    return self._json(app.prefs_put(body))
                if path == "/api/prefs/syncdir":
                    return self._json(app.prefs_sync_dir(body))
                if path == "/api/prefs/import":
                    return self._json(app.prefs_import(body))
                if path == "/api/chat":
                    return self._json(app.assistant.ask(str(body.get("question") or ""), src="web"))
                if path == "/api/macroweek/comment":
                    return self._json(app.macro_week_comment(str(body.get("week") or "") or None))
                if path == "/api/macromonth/research":
                    return self._json(app.macro_month_research(str(body.get("month") or "") or None))
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
                if path == "/api/flow/reset":
                    sym = str(body.get("symbol") or app.cfg.symbols[0]).upper()
                    if app.flow:
                        app.flow.reset(sym)
                    return self._json({"ok": bool(app.flow), "symbol": sym})
                if path == "/api/vps":
                    return self._json({**app.service.set_vp(body.get("specs"), body.get("anchors", app.service.vp_state["anchors"])), "ok": True})
                if path == "/api/test/binance":
                    sym = app.cfg.symbols[0] if app.cfg.symbols else "BTCUSDT"
                    res = BinanceSource(retries=1, timeout=12).selftest(sym)
                    return self._json({"results": [{"name": a, "ok": b, "detail": c} for a, b, c in res]})
                if path == "/api/test/telegram":
                    tok = clean_token(body.get("token")) or app.cfg.telegram_token
                    cid = clean_chat(body.get("chatId")) or app.cfg.telegram_chat_id
                    if not tok or not cid:
                        return self._json({"ok": False, "detail": "token et chat id requis"})
                    ok, detail = TelegramNotifier(tok, cid, app.cfg.telegram_api_base).send(
                        "✅ Test du terminal : Telegram fonctionne.")
                    saved = False
                    if ok and (tok != app.cfg.telegram_token or cid != app.cfg.telegram_chat_id) and token_ok(tok) and chat_ok(cid):
                        app.save_settings({"telegramToken": tok, "telegramChatId": cid})      # V25 : un test reussi enregistre tout seul
                        saved = True
                    return self._json({"ok": ok, "detail": detail if ok else notifier_mod.explain(detail), "raw": detail, "saved": saved})
                if path == "/api/test/x":
                    return self._json(app.social.test(str(body.get("token") or "").strip() or None, body.get("handle")))
                if path == "/api/telegram/diagnose":
                    return self._json(app.telegram_diagnose(str(body.get("token") or "").strip() or None, str(body.get("chatId") or "").strip() or None))
                if path == "/api/telegram/chatid":
                    tok = clean_token(body.get("token")) or app.cfg.telegram_token
                    if not tok:
                        return self._json({"chats": [], "detail": "token requis"})
                    t = app.tgchat
                    if t and tok == app.cfg.telegram_token:              # le bot ecoute deja : lire Telegram en meme temps serait refuse (409)
                        return self._json({"chats": [{"id": k, "name": v} for k, v in t.seen.items()],
                                           "detail": "" if t.seen else "aucun message reçu depuis le démarrage : écris « bonjour » à ton bot, puis réessaie"})
                    try:
                        chats = TelegramNotifier(tok, "", app.cfg.telegram_api_base).find_chat_ids()
                    except Exception as e:
                        code = getattr(e, "code", None)
                        return self._json({"chats": [], "detail": notifier_mod.explain(f"HTTP {code}" if code else f"{type(e).__name__}: {e}")})
                    return self._json({"chats": [{"id": str(k), "name": v} for k, v in chats.items()],
                                       "detail": "" if chats else "aucun message reçu : ouvre ton bot dans Telegram, appuie sur Démarrer ou écris « bonjour », puis réessaie"})
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
