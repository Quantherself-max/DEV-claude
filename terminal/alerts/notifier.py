"""Envoi des alertes : console (essai a blanc) ou Telegram (bot cree avec @BotFather).
V25 : dernier envoi retenu (reussi ou non, avec la raison en clair) et diagnostic pas a pas du bot."""
import json
import threading
import time
import urllib.error
import urllib.request

LAST = {}                    # dernier envoi Telegram : {"ok", "t", "detail", "chat", "bot", "help"} (affiche dans le badge et le diagnostic)
_lock = threading.Lock()


def explain(detail: str) -> str:
    """Reponse d'erreur de Telegram -> ce qu'il faut faire, en clair."""
    d = (detail or "").lower()
    if "401" in d or "unauthorized" in d:
        return "token refusé par Telegram : il a été mal copié ou révoqué. Recopie-le depuis @BotFather (/mybots → ton bot → API Token)."
    if "404" in d and "chat" not in d:
        return "token refusé par Telegram (adresse du bot introuvable) : recopie le token depuis @BotFather."
    if "chat not found" in d:
        return ("chat id inconnu pour ce bot : ouvre TON bot dans Telegram, appuie sur Démarrer (ou envoie-lui « bonjour »), puis clique sur "
                "« Trouver mon chat id ». Le chat id d'un autre bot ou d'un autre compte ne marche pas.")
    if "bots can't send messages to bots" in d or "bot can't send messages to bots" in d:
        return ("le chat id enregistré est celui d'un bot (souvent le numéro au début du token) : il faut TON chat id. Écris « bonjour » à ton bot, "
                "puis « Trouver mon chat id ».")
    if "bot was blocked" in d:
        return "tu as bloqué le bot dans Telegram : ouvre la conversation avec le bot et débloque-le (Redémarrer)."
    if "not a member" in d or "not enough rights" in d or "have no rights" in d:
        return "pour un groupe ou un canal, ajoute le bot comme membre (administrateur pour un canal) avec le droit d'écrire."
    if "conflict" in d or "409" in d:
        return ("un autre programme lit déjà les messages de ce bot (un autre terminal allumé, sur un serveur par exemple) : "
                "n'en garde qu'un, ou crée un deuxième bot pour l'autre.")
    if "429" in d or "too many requests" in d:
        return "trop de messages envoyés d'un coup : Telegram demande d'attendre un peu."
    if "timed out" in d or "timeout" in d or "urlerror" in d or "connection" in d or "name or service" in d or "getaddrinfo" in d or "ssl" in d:
        return "Telegram injoignable depuis ce PC : connexion internet, pare-feu, antivirus ou VPN qui bloque api.telegram.org."
    return detail or "erreur inconnue"


def _remember(ok: bool, detail: str, chat, token: str = ""):
    with _lock:
        LAST.clear()
        LAST.update({"ok": ok, "t": time.time(), "detail": detail, "chat": str(chat), "bot": (token or "")[-6:], "help": "" if ok else explain(detail)})


def last_for(token: str, chat) -> dict:
    """Dernier envoi fait avec CE token et CE chat id (un echec avec d'anciens reglages ne compte plus une fois corriges)."""
    with _lock:
        d = dict(LAST)
    return d if d and d.get("chat") == str(chat) and d.get("bot") == (token or "")[-6:] else {}


class ConsoleNotifier:
    name = "console"

    def send(self, text: str):
        print("\n[ALERTE]\n" + text + "\n")
        return True, "console"


class TelegramNotifier:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, api_base: str = "https://api.telegram.org", timeout: int = 15):
        self.token, self.chat_id, self.base, self.timeout = token, chat_id, api_base.rstrip("/"), timeout

    def _call(self, method: str, payload: dict | None = None):
        url = f"{self.base}/bot{self.token}/{method}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def call(self, method: str, payload: dict | None = None):
        """Comme _call, mais sans exception : (ok, resultat ou message d'erreur lisible)."""
        try:
            res = self._call(method, payload)
            return (True, res.get("result")) if res.get("ok") else (False, str(res.get("description") or res)[:200])
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            e.close()
            try:
                body = json.loads(body).get("description") or body
            except ValueError:
                pass
            return False, f"HTTP {e.code} : {body}"
        except Exception as e:           # reseau coupe, timeout...
            return False, f"{type(e).__name__}: {e}"

    def send(self, text: str):
        ok, res = self.call("sendMessage", {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True})
        detail = "envoye" if ok else res
        _remember(ok, detail, self.chat_id, self.token)
        return ok, detail

    def find_chat_ids(self):
        """Apres avoir ecrit un message a ton bot : liste des conversations vues par le bot."""
        res = self._call("getUpdates")
        seen = {}
        for u in res.get("result", []):
            m = u.get("message") or u.get("channel_post") or {}
            c = m.get("chat")
            if c:
                seen[c["id"]] = c.get("username") or c.get("title") or c.get("first_name") or ""
        return seen
