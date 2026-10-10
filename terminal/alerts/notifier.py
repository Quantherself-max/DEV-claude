"""Envoi des alertes : console (essai a blanc) ou Telegram (bot cree avec @BotFather)."""
import json
import urllib.error
import urllib.request


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

    def send(self, text: str):
        try:
            res = self._call("sendMessage", {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True})
            return bool(res.get("ok")), "envoye" if res.get("ok") else str(res)[:200]
        except urllib.error.HTTPError as e:
            detail = f"HTTP {e.code} : {e.read().decode('utf-8', 'replace')[:160]}"
            e.close()
            return False, detail
        except Exception as e:           # reseau coupe, timeout...
            return False, f"{type(e).__name__}: {e}"

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
