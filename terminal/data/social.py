"""Lecture des posts de quelques comptes X (FACULTATIF, hors score).

- API officielle X v2 avec TON jeton (TERMINAL_X_BEARER_TOKEN dans .env, jamais renvoye a l'interface). Aucune donnee n'est
  envoyee a X : on ne fait que lire les derniers posts publics des comptes que tu as choisis.
- Cout : la lecture est facturee par post lu (environ 0,005 $ selon les tarifs publies, a verifier sur ton compte developpeur).
  Pour le limiter, les posts ne sont lus QU'AU MOMENT D'ENVOYER UNE IDEE (3 par semaine au maximum) ou quand tu cliques
  sur « Voir l'avis », puis gardes 30 minutes en memoire. Maximum 10 comptes x 5 a 20 posts.
- Un echec (jeton, credits, reseau) n'a jamais d'effet sur les idees : l'avis est simplement indisponible."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from engine import stance

HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
COST_PER_POST = 0.005
MAX_ACCOUNTS = 10
TTL = 1800.0                 # les posts d'un compte sont gardes 30 minutes
FAIL_TTL = 300.0             # une erreur est gardee 5 minutes (on ne martele pas l'API)


def clean_handles(raw) -> list[str]:
    """Accepte « @a, b c » ou une liste ; renvoie des identifiants valides, sans doublon, 10 au maximum."""
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[,;\s]+", str(raw or ""))
    out = []
    for p in parts:
        h = p.strip().lstrip("@")
        if h and HANDLE.match(h) and h.lower() not in [x.lower() for x in out]:
            out.append(h)
    return out[:MAX_ACCOUNTS]


class XError(Exception):
    pass


class XClient:
    def __init__(self, token: str, base: str = "https://api.x.com", timeout: int = 12, users_file: Path | None = None):
        self.token, self.base, self.timeout, self.users_file = token, base.rstrip("/"), timeout, users_file
        self._users: dict[str, str] | None = None

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}", "User-Agent": "liq-terminal"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = {401: "jeton refusé par X (vérifie-le)", 402: "crédits X épuisés : recharge ton compte développeur",
                   403: "accès refusé par X (forfait ou compte)", 404: "compte introuvable", 429: "limite de requêtes X atteinte, réessaie plus tard"}
            raise XError(msg.get(e.code, f"erreur X (HTTP {e.code})"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise XError(f"X injoignable ({getattr(e, 'reason', e)})")
        except ValueError:
            raise XError("réponse X illisible")

    # --- identifiants de comptes : gardes sur le disque (l'identifiant ne change jamais) ---
    def _load_users(self):
        if self._users is None:
            try:
                self._users = json.loads(self.users_file.read_text(encoding="utf-8")) if self.users_file else {}
            except (OSError, ValueError):
                self._users = {}
        return self._users

    def user_id(self, handle: str) -> str:
        users = self._load_users()
        key = handle.lower()
        if key in users:
            return users[key]
        d = self._get(f"/2/users/by/username/{urllib.parse.quote(handle)}")
        uid = (d.get("data") or {}).get("id")
        if not uid:
            raise XError("compte introuvable ou protégé")
        users[key] = uid
        if self.users_file:
            try:
                self.users_file.parent.mkdir(parents=True, exist_ok=True)
                self.users_file.write_text(json.dumps(users), encoding="utf-8")
            except OSError:
                pass
        return uid

    def posts(self, handle: str, n: int = 10) -> list[dict]:
        """Derniers posts du compte (sans reposts ni reponses), du plus recent au plus ancien."""
        uid = self.user_id(handle)
        d = self._get(f"/2/users/{uid}/tweets", {"max_results": max(5, min(100, n)), "exclude": "retweets,replies",
                                                 "tweet.fields": "created_at,lang"})
        out = []
        for p in d.get("data") or []:
            try:
                t = int(datetime.strptime(p["created_at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
            except (KeyError, ValueError):
                continue
            out.append({"id": p.get("id"), "t": t, "text": p.get("text", ""), "url": f"https://x.com/{handle}/status/{p.get('id')}"})
        return out


class Influencers:
    """Avis des comptes suivis sur une paire, compare au sens d'une idee. Tout est facultatif et sans effet sur le score."""

    def __init__(self, cfg, now=time.time):
        self.cfg, self.now = cfg, now
        self.cache: dict[str, tuple] = {}
        self.lock = threading.Lock()
        self.client = XClient(cfg.x_token, cfg.x_api_base, users_file=Path(cfg.data_dir) / "x_users.json") if cfg.x_token else None

    @property
    def configured(self) -> bool:
        return bool(self.cfg.x_on and self.cfg.x_token and self.cfg.x_accounts)

    def _fetch(self, handle: str):
        """(posts, erreur, nb de posts reellement lus)."""
        with self.lock:
            hit = self.cache.get(handle.lower())
        if hit and self.now() - hit[0] < (TTL if not hit[2] else FAIL_TTL):
            return hit[1], hit[2], 0
        try:
            posts = self.client.posts(handle, self.cfg.x_posts)
            err = None
        except XError as e:
            posts, err = [], str(e)
        with self.lock:
            self.cache[handle.lower()] = (self.now(), posts, err)
        return posts, err, len(posts)

    def opinions(self, symbol: str, side: str) -> dict:
        if not self.configured:
            return {"on": False, "configured": False}
        base, _ = stance.asset_names(symbol)
        now_ms = int(self.now() * 1000)
        handles = list(self.cfg.x_accounts)
        with ThreadPoolExecutor(max_workers=5) as ex:
            res = list(ex.map(self._fetch, handles))
        accounts, read = [], 0
        for h, (posts, err, n) in zip(handles, res):
            read += n
            if err:
                accounts.append({"handle": h, "error": err})
                continue
            a = stance.read_account(posts, symbol, now_ms, self.cfg.x_max_age_h)
            a.update(handle=h, relation=stance.relation(a["stance"], side))
            accounts.append(a)
        return {"on": True, "configured": True, "symbol": symbol, "side": side, "asset": base, "t": now_ms, "accounts": accounts,
                "summary": stance.summarize(accounts), "cost": {"posts": read, "usd": round(read * COST_PER_POST, 3)}}

    def test(self, token: str | None = None, handle: str | None = None) -> dict:
        """Verifie le jeton et un compte (1 recherche + 5 posts lus, soit environ 0,03 $)."""
        tok = token or self.cfg.x_token
        h = (clean_handles(handle) or list(self.cfg.x_accounts) or [""])[0]
        if not tok:
            return {"ok": False, "detail": "jeton X manquant"}
        if not h:
            return {"ok": False, "detail": "indique au moins un compte à suivre"}
        try:
            posts = XClient(tok, self.cfg.x_api_base, users_file=Path(self.cfg.data_dir) / "x_users.json").posts(h, 5)
        except XError as e:
            return {"ok": False, "detail": str(e)}
        return {"ok": True, "detail": f"jeton valide : {len(posts)} post(s) lu(s) sur @{h}", "posts": len(posts)}
