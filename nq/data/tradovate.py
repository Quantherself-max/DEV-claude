"""Source de données TEMPS RÉEL via l'API OFFICIELLE de Tradovate, avec TES identifiants.

Lucid relie ton compte à Tradovate. Tradovate publie une API (REST pour se connecter, WebSocket pour le flux de marché). Ce module
l'utilise normalement : il se connecte avec TON nom d'utilisateur et TON mot de passe (lus dans `.env`, jamais écrits dans le code), reçoit
un jeton, ouvre la socket de données et s'abonne au NQ. Rien n'est contourné : ce sont tes identifiants, l'API officielle, tes données.

Pré-requis côté Tradovate (sinon la connexion est refusée — c'est une limite de TON compte, pas un bug) :
  - l'« API Access » doit être activé sur le compte (souvent un abonnement en plus, ~25 $/mois) ;
  - un abonnement aux DONNÉES de marché CME doit être actif (frais de bourse), sinon la socket s'authentifie mais n'envoie pas de cotations.
Si l'un manque, le terminal l'affiche dans l'onglet Source ; passe alors par NinjaTrader (NQTickLogger).

Comment on fabrique les transactions : l'abonnement `md/subscribeQuote` donne, à chaque mise à jour, le dernier prix traité, le meilleur
bid / ask et le VOLUME CUMULÉ de la séance. À chaque fois que le volume cumulé augmente, on émet une transaction de la taille de
l'augmentation, au dernier prix, avec le côté de l'agresseur déduit du bid / ask (prix ≥ ask = acheteur, ≤ bid = vendeur) — exactement comme
l'enregistreur NinjaTrader. Ce n'est pas aussi fin qu'un vrai flux tick-par-tick (plusieurs transactions dans une même mise à jour sont
regroupées), mais c'est robuste et le delta est réel la plupart du temps.

Non testé en direct depuis l'environnement de développement (pas d'accès au compte) : si quelque chose cloche, l'onglet Source montre le
dernier message d'erreur, et le détail des trames est journalisé (NQ_TRADOVATE_DEBUG=1) pour corriger vite."""
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request

from engine.bars import Tick
from engine.instruments import front_contract

from .base import DataError, Source
from .wsclient import WsClient, WsError

log = logging.getLogger("nq.tradovate")

HOSTS = {
    "live": {"rest": "https://live.tradovateapi.com/v1", "md": "wss://md.tradovateapi.com/v1/websocket"},
    "demo": {"rest": "https://demo.tradovateapi.com/v1", "md": "wss://md-demo.tradovateapi.com/v1/websocket"},
}
HEARTBEAT_S = 2.5                       # Tradovate ferme la socket sans battement de cœur régulier
RENEW_MARGIN_S = 600                    # on renouvelle le jeton 10 min avant son expiration


class TradovateSource(Source):
    name = "tradovate"
    simulated = False

    def __init__(self, username, password, cid, sec, app_id="NQScalpTerminal", app_version="1.0", env="live",
                 instrument_root="NQ", symbol=None, debug=False, ws_factory=None, http_fn=None):
        if not username or not password:
            raise DataError("Tradovate : renseigne TRADOVATE_USERNAME et TRADOVATE_PASSWORD dans .env")
        self.cred = {"name": username, "password": password, "appId": app_id, "appVersion": app_version,
                     "deviceId": "nq-scalp-terminal"}
        if cid:
            self.cred["cid"] = _maybe_int(cid)
        if sec:
            self.cred["sec"] = sec
        self.env = env if env in HOSTS else "live"
        self.hosts = HOSTS[self.env]
        self.root = instrument_root
        self.symbol = symbol                                # None : contrat de tête calculé (NQZ6...)
        self.debug = debug
        self.label = f"Tradovate {self.env}"
        self._ws_factory = ws_factory or (lambda url: WsClient(url, timeout=30.0))
        self._http = http_fn or _http_post
        self.q = queue.Queue()                              # transactions prêtes pour le marché (thread sûr)
        self._thread = None
        self._stop = threading.Event()
        self.status = "en attente"
        self.error = None
        self.mode = "quote"
        self.heartbeat_s = HEARTBEAT_S
        self._started = False
        # état de synthèse des transactions depuis les cotations
        self._last_price = None
        self._bid = None
        self._ask = None
        self._cum_vol = None

    # ---------- interface Source ----------
    def history(self, now_ms: int):
        self._ensure_thread()
        return []                                           # l'API de cotations ne rejoue pas l'historique : le terminal part du direct

    def poll(self, now_ms: int) -> list:
        self._ensure_thread()
        out = []
        try:
            while True:
                out.append(self.q.get_nowait())
        except queue.Empty:
            pass
        if self.error and "refus" in self.error.lower():
            raise DataError(self.error)                     # erreur définitive (identifiants / accès) : remonte au terminal
        return out

    def info(self) -> dict:
        d = super().info()
        d.update({"label": self.label, "status": self.status, "error": self.error, "symbol": self._symbol(),
                  "env": self.env, "mode": self.mode})
        return d

    def shutdown(self):
        self._stop.set()

    # ---------- fil de fond ----------
    def _ensure_thread(self):
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._run, name="nq-tradovate", daemon=True)
        self._thread.start()

    def _symbol(self):
        return self.symbol or front_contract(int(time.time() * 1000), self.root).code

    def _run(self):
        backoff = 2.0
        while not self._stop.is_set():
            try:
                self._session()
                backoff = 2.0                               # une session a vécu : on repart vite
            except _AuthDenied as e:
                self.error = f"Connexion refusée par Tradovate : {e}"
                self.status = "refusé"
                log.error("Tradovate : %s", e)
                return                                       # identifiants / accès : inutile de réessayer en boucle
            except (WsError, DataError, OSError, ValueError) as e:
                self.error = str(e)
                self.status = "reconnexion"
                log.warning("Tradovate : %s — nouvelle tentative dans %.0fs", e, backoff)
            if self._stop.wait(backoff):
                return
            backoff = min(backoff * 2, 30.0)

    def _session(self):
        token, md_token, expiry = self._authenticate()
        self.status = "connecté"
        self.error = None
        url = self.hosts["md"]
        ws = self._ws_factory(url)
        ws.connect()
        try:
            self._loop(ws, md_token, expiry)
        finally:
            ws.close()

    def _loop(self, ws, md_token, expiry):
        req_id = [0]

        def request(endpoint, body=None):
            # format Tradovate : endpoint\nid\nquery\ncorps. Le corps d'« authorize » est le jeton BRUT (pas du JSON) ; les autres sont du JSON.
            req_id[0] += 1
            if body is None:
                tail = ""
            elif isinstance(body, str):
                tail = body
            else:
                tail = json.dumps(body)
            ws.send(f"{endpoint}\n{req_id[0]}\n\n" + tail)
            return req_id[0]

        authorized = False
        subscribed = False
        last_beat = time.time()
        sym = self._symbol()
        while not self._stop.is_set():
            now = time.time()
            if now - last_beat >= self.heartbeat_s:         # battement de cœur : sinon Tradovate coupe
                ws.send("[]")
                last_beat = now
            if time.time() > expiry - RENEW_MARGIN_S:       # jeton bientôt expiré : on relance une session propre
                return
            msg = ws.recv(timeout=1.0)
            if msg is None:
                continue
            if self.debug:
                log.info("Tradovate <= %s", msg[:400])
            kind, payloads = _split_frame(msg)
            if kind == "o":                                 # socket ouverte : on s'autorise avec le jeton de DONNÉES
                request("authorize", md_token)
                continue
            if kind == "c":
                raise WsError(f"Tradovate a fermé la socket : {payloads}")
            if kind != "a":
                continue                                    # 'h' battement du serveur, etc.
            for item in payloads:
                if not isinstance(item, dict):
                    continue
                if "s" in item and "i" in item:             # réponse à une requête (statut HTTP)
                    if not authorized:
                        if item["s"] == 200:
                            authorized = True
                            self.status = "autorisé"
                            request("md/subscribeQuote", {"symbol": sym})
                            subscribed = True
                        else:
                            raise _AuthDenied(_err_text(item, "autorisation de la socket refusée"))
                    elif item["s"] != 200 and subscribed:
                        raise DataError(_err_text(item, f"abonnement au flux {sym} refusé"))
                    continue
                if item.get("e") == "md":                   # évènement de données de marché
                    self._on_md(item.get("d") or {})

    # ---------- synthèse des transactions ----------
    def _on_md(self, d):
        for qd in d.get("quotes") or []:
            ent = qd.get("entries") or {}
            bid = _price(ent.get("Bid"))
            ask = _price(ent.get("Offer") or ent.get("Ask"))
            trade = _price(ent.get("Trade"))
            cum = _size(ent.get("TotalTradeVolume") or ent.get("TradeVolume"))
            ts = _ts(qd.get("timestamp") or d.get("timestamp"))
            if bid is not None:
                self._bid = bid
            if ask is not None:
                self._ask = ask
            if trade is not None:
                self._last_price = trade
            if cum is not None and self._last_price is not None:
                if self._cum_vol is None:
                    self._cum_vol = cum                     # première valeur : on cale la base, sans émettre
                elif cum > self._cum_vol:
                    self._emit(ts, self._last_price, cum - self._cum_vol)
                    self._cum_vol = cum
                elif cum < self._cum_vol:                   # remise à zéro de séance : on recale
                    self._cum_vol = cum

    def _emit(self, ts, price, size):
        if price is None or size <= 0:
            return
        side = 0
        if self._ask is not None and price >= self._ask:
            side = 1
        elif self._bid is not None and price <= self._bid:
            side = -1
        self.q.put(Tick(int(ts), float(price), float(size), side))

    # ---------- authentification REST ----------
    def _authenticate(self):
        url = self.hosts["rest"] + "/auth/accesstokenrequest"
        try:
            res = self._http(url, self.cred)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            if e.code in (401, 403):
                raise _AuthDenied(f"HTTP {e.code} — vérifie tes identifiants et l'accès API ({body[:200]})") from None
            raise DataError(f"Tradovate auth : HTTP {e.code} ({body[:200]})") from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise DataError(f"Tradovate injoignable : {e}") from None
        if "p-ticket" in res or "penaltyTime" in res:       # trop d'essais : Tradovate impose une attente
            wait = res.get("p-time") or res.get("penaltyTime") or 60
            raise DataError(f"Tradovate limite les connexions : réessaie dans {wait}s")
        token = res.get("accessToken")
        md_token = res.get("mdAccessToken") or token        # la socket de données utilise le jeton « md » s'il est fourni
        if not token:
            raise _AuthDenied(_err_text(res, "pas de jeton d'accès dans la réponse"))
        expiry = _ts(res.get("expirationTime"), default_ms=int((time.time() + 3600) * 1000)) / 1000.0
        self.label = f"Tradovate {self.env} ({res.get('name', '')})".strip()
        return token, md_token, expiry


class _AuthDenied(Exception):
    pass


# ---------- utilitaires ----------
def _http_post(url, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json",
                                                          "User-Agent": "NQ-Scalp-Terminal"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _split_frame(msg: str):
    """Trame façon SockJS de Tradovate : 'o' (ouverture), 'h' (battement), 'a[...]' (messages), 'c[...]' (fermeture). Renvoie (type, liste)."""
    if not msg:
        return "", []
    head = msg[0]
    if head in ("o", "h"):
        return head, []
    if head in ("a", "c"):
        try:
            arr = json.loads(msg[1:])
        except ValueError:
            return head, []
        return head, arr if isinstance(arr, list) else [arr]
    return "", []


def _err_text(item, default):
    if isinstance(item, dict):
        d = item.get("d")
        if isinstance(d, dict) and d.get("errorText"):
            return d["errorText"]
        if isinstance(d, str) and d:
            return d
        if item.get("errorText"):
            return item["errorText"]
    return default


def _price(entry):
    if isinstance(entry, dict):
        v = entry.get("price")
        return float(v) if isinstance(v, (int, float)) else None
    return None


def _size(entry):
    if isinstance(entry, dict):
        v = entry.get("size")
        if isinstance(v, (int, float)):
            return float(v)
    if isinstance(entry, (int, float)):
        return float(entry)
    return None


def _maybe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _ts(value, default_ms=None):
    """Horodatage Tradovate (ISO 8601, souvent en UTC avec Z) -> ms epoch. `default_ms` ou l'heure courante si absent / illisible."""
    if isinstance(value, (int, float)):
        return int(value if value > 1e12 else value * 1000)
    if isinstance(value, str) and value:
        from datetime import datetime, timezone
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return int(d.timestamp() * 1000)
        except ValueError:
            pass
    return default_ms if default_ms is not None else int(time.time() * 1000)
