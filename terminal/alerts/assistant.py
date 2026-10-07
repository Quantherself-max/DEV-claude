"""Discussion avec Claude (V12) : pose une question sur Telegram ou dans le terminal (« pourquoi le BTC a perdu 2 % ? »), l'assistant rassemble tout ce que
le terminal sait a cet instant (prix, mouvements recents et ce qui les accompagne, interet ouvert, flux, liquidations reelles, financement, squeeze, options,
macro, autres marches, ou est l'argent...) et Claude repond en s'appuyant sur ces donnees, plus une recherche web d'actualites si besoin.

  - cle API Anthropic (console.anthropic.com, payante a l'usage, distincte de l'abonnement Claude) gardee dans .env ; budget mensuel plafonne ;
  - module officiel `anthropic` (installe a la demande par le terminal : python -m pip install anthropic) ;
  - Telegram : SEULS les messages de TON chat id sont lus ; les autres sont ignores.
Le contexte est construit localement : aucune donnee n'est envoyee ailleurs qu'a l'API de Claude au moment d'une question."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from engine import explain as ex

# modele -> (nom, $ par million de jetons en entree, en sortie, lecture du cache)
MODELS = {"claude-opus-5-5": ("Claude Opus 5.5", 4.0, 20.0, 0.20), "claude-sonnet-5-5": ("Claude Sonnet 5.5", 2.0, 10.0, 0.20),
          "claude-haiku-4-5": ("Claude Haiku 4.5", 1.0, 5.0, 0.10)}
DEFAULT_MODEL = "claude-opus-5-5"
WEB_SEARCH_USD = 0.01                 # 10 $ les 1000 recherches
HISTORY_TURNS = 6                     # echanges gardes pour la suite de la conversation
MAX_CONTINUE = 3

SYSTEM = """Tu es l'assistant du terminal de trading de l'utilisateur (« Liq Terminal »). Il trade surtout SOL et BTC avec levier ; il lit le volume profile, le CVD, les VWAP et VWAP ancrés, la liquidité (poches de liquidation), et relie le marché à la macro, à la géopolitique et aux flux institutionnels. Il cherche l'argent partout où il se trouve.

Comment répondre :
- En français, en le tutoyant, comme dans une discussion Telegram : d'abord la réponse en 2 à 4 phrases, puis le détail utile s'il en faut. Texte brut lisible sur un téléphone : pas de tableau, pas de titre, des puces « • » si besoin.
- Pas d'abréviation sans l'écrire en toutes lettres la première fois (par exemple « intérêt ouvert (Open Interest) »).
- Appuie-toi d'abord sur les données du terminal jointes au message (horodatées en heure de Paris) et cite les chiffres. N'invente jamais un chiffre : si une donnée manque, dis-le.
- Pour expliquer un mouvement de prix : donne la chronologie, puis sépare ce qui est MESURÉ (liquidations, intérêt ouvert, flux d'ordres, annonces, autres marchés au même moment) de ce qui est une HYPOTHÈSE. Si les données du terminal ne suffisent pas, cherche l'actualité du moment sur le web (annonces, géopolitique, ETF, déclarations, piratages, gros transferts) et donne tes sources.
- Niveaux de preuve du terminal : seule la tendance de fond (moyennes 50 et 200 jours) est validée par son backtest ; le reste (financement, intérêt ouvert, flux, squeezes, options, macro) est du contexte sans avantage démontré. Ne présente jamais un indicateur non prouvé comme prédictif.
- Si on te demande quoi faire : des scénarios avec leurs niveaux d'invalidation et ce qui ferait changer d'avis, le risque du levier en une phrase, sans moraliser. Ce n'est pas un conseil financier et tu ne passes aucun ordre."""

HELP = ("Pose-moi n'importe quelle question sur le marché ou sur les analyses du terminal, par exemple :\n"
        "• pourquoi le BTC a perdu 2 % cet après-midi ?\n• les shorts s'accumulent sur SOL ?\n• qu'est-ce qui arrive cette semaine en macro ?\n\n"
        "Commandes : /reset (nouvelle conversation), /cout (dépense du mois), /aide.")


def sdk():
    """Le module officiel `anthropic`, ou None s'il n'est pas installe."""
    try:
        import anthropic
        return anthropic
    except ImportError:
        return None


def install_sdk(timeout: float = 300.0) -> tuple:
    """python -m pip install anthropic (puis --user si l'installation globale est refusee). Renvoie (ok, message)."""
    if sdk():
        return True, "déjà installé"
    last = ""
    for extra in ([], ["--user"]):
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "anthropic", *extra],
                               capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"pip indisponible ({type(e).__name__})"
        if r.returncode == 0:
            import importlib
            import site
            try:
                site.addsitedir(site.getusersitepackages())             # dossier utilisateur cree pendant l'installation
            except Exception:
                pass
            importlib.invalidate_caches()
            return (True, "installé") if sdk() else (False, "installé : relance le terminal pour l'utiliser")
        last = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        last = last[0][:200]
    return False, f"échec de l'installation : {last}"


def split_text(text: str, n: int = 3900) -> list:
    """Coupe un long texte en messages Telegram (4096 caracteres au plus), de preference sur un saut de ligne."""
    out = []
    while len(text) > n:
        cut = text.rfind("\n", 0, n)
        cut = cut if cut > n // 2 else n
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return out + ([text] if text else [])


# ======================================================================== contexte : tout ce que sait le terminal
def _pct(a, b):
    return (a / b - 1.0) * 100.0 if a and b else None


def _price_ago(candles, now, hours):
    t = now - hours * ex.HOUR
    prev = [k for k in candles if k.t <= t]
    return prev[-1].c if prev else None


def build_context(svc, now: int) -> str:
    """Texte (en francais) avec l'etat du marche pour chaque paire suivie, les mouvements recents et leurs faits, la macro et les autres marches."""
    lines = [f"Données du terminal au {ex.paris(now)} (heure de Paris).", ""]
    snap = svc.ext.snapshot() if svc.ext else {}
    cal = snap.get("calendar") or {}
    events = [{"t": e["t"], "label": f"{e.get('title', '?')} ({e.get('country', '')})", "impact": e.get("impact", 0)} for e in cal.values() if e.get("t")]
    cross5 = snap.get("cross5") or {}
    feed = getattr(svc, "feed", None)
    first_an = None
    for sym, m in svc.markets.items():
        if not m.ready:
            lines.append(f"{sym} : données en cours de chargement.")
            continue
        try:
            lec = svc.lecture(sym)
            an = svc.analysis(sym)
        except Exception as e:
            lines.append(f"{sym} : indisponible ({type(e).__name__}).")
            continue
        first_an = first_an or an
        h = lec.get("head") or {}
        c5 = list(m.store.m5)
        price = h.get("price")
        chg = [f"{lab} {ex.f(_pct(price, _price_ago(c5, now, hr)), 2, True)} %" for lab, hr in (("1 h", 1), ("4 h", 4), ("24 h", 24), ("7 j", 168))]
        lines.append(f"=== {sym} : {ex.f(price, 2)} ({', '.join(chg)}) ; amplitude moyenne d'une bougie d'une heure : {ex.f(an.get('atrPct'), 2)} %")
        tr = h.get("trend")
        if tr:
            lines.append(f"Tendance de fond (validée par le backtest) : {tr['label']} ; cours {ex.f(tr['distFast'], 1, True)} % face à la moyenne 50 jours, {ex.f(tr['distSlow'], 1, True)} % face à la moyenne 200 jours.")
        bi = h.get("bias")
        if bi:
            lines.append(f"Biais statistique : {bi['label']}" + (" (validé)" if bi.get("validated") else " (non validé : ne bat pas le hasard, ignoré)") + ".")
        idea = lec.get("idea") or {}
        if idea.get("side"):
            lines.append(f"Idée de trade du terminal : {'achat' if idea['side'] == 'long' else 'vente'}, qualité {ex.f(idea.get('score'), 0)}/100, entrée {ex.f(idea.get('entry'), 2)}, stop {ex.f(idea.get('stop'), 2)}, objectif {ex.f(idea.get('tp1'), 2)}"
                         + ("" if idea.get("eligible") else " (non envoyée)") + ".")
        w = lec.get("watch") or {}
        lv = [f"au-dessus {ex.f(l['mid'], 2)} ({ex.f(l.get('distAtr'), 1)} fois l'amplitude horaire)" for l in w.get("up", [])] + \
             [f"en dessous {ex.f(l['mid'], 2)} ({ex.f(l.get('distAtr'), 1)} fois l'amplitude horaire)" for l in w.get("dn", [])]
        if lv:
            lines.append("Niveaux importants proches : " + " ; ".join(lv) + ".")
        for c in lec.get("chips", []):
            lines.append(f"- {c['title']} [{c.get('evidence', 'contexte')}] : {c['value']}" + (f" — {c['note']}" if c.get("note") else ""))
        sq = lec.get("squeeze")
        if sq:
            v = sq.get("values") or {}
            lines.append(f"- Flux et squeeze [{sq.get('evidence')}] : {sq['label']} — {sq['text']} (prix {ex.f((v.get('ret24') or 0) * 100, 2, True)} % en 24 h, "
                         f"intérêt ouvert {ex.f((v['oi24'] * 100) if v.get('oi24') is not None else None, 1, True)} % en 24 h, acheteurs agressifs {ex.f(50 * (1 + v['imb24']) if v.get('imb24') is not None else None, 0)} % du volume ; {sq.get('evidenceNote', '')})")
        liqs = feed.recent_liqs(sym, now - 26 * ex.HOUR) if feed else []
        oi_t, oi_v = list(m.store.oi_t), list(m.store.oi_v)
        mv = ex.moves(c5, now, 24.0)
        if mv:
            lines.append("Mouvements marquants des dernières 24 h :")
            for x in mv:
                lines.append(ex.move_text(sym, x, ex.window_facts(x, c5, oi_t, oi_v, liqs, cross5, events)))
        lines.append("")
    if first_an:
        mac = first_an.get("macro") or {}
        lines.append("=== Macro")
        if mac.get("label"):
            lines.append(f"Climat des marchés : {mac['label']}" + (f" (score {ex.f(mac.get('score'), 0)} sur 100)" if mac.get("score") is not None else "") + ".")
        for ln in (mac.get("lines") or [])[:6]:
            lines.append(f"- {ln if isinstance(ln, str) else ln.get('text', '')}")
        up = [e for e in mac.get("upcoming") or [] if e["t"] - now <= 3 * 24 * ex.HOUR][:8]
        if up:
            lines.append("Annonces à venir (3 jours) : " + " ; ".join(
                f"{e.get('label') or e.get('title')} le {ex.paris(e['t'])}" + (f" (prévision {e['forecast']}, précédent {e.get('previous', '?')})" if e.get("forecast") else "") for e in up) + ".")
        past = [e for e in mac.get("past") or [] if now - e["t"] <= 3 * 24 * ex.HOUR][:8]
        if past:
            lines.append("Annonces passées (3 jours) : " + " ; ".join(
                f"{e.get('label') or e.get('title')} le {ex.paris(e['t'])}" + (f" (réaction des marchés : {e['reaction']['impulseLabel']})" if (e.get("reaction") or {}).get("impulseLabel") else "") for e in past) + ".")
        crossD = snap.get("crossD") or {}
        cr = []
        for k, name in ex.CROSS_NAMES.items():
            s5, sd = cross5.get(k) or [], crossD.get(k) or []
            last = s5[-1][1] if s5 else (sd[-1][1] if sd else None)
            prev1 = ex._series_at(s5, now - 24 * ex.HOUR, 4 * 24 * ex.HOUR) if s5 else None
            prev5 = sd[-6][1] if len(sd) >= 6 else None
            chg = (lambda a, b: (a - b) if (a is not None and b is not None) else None) if k in ex.POINTS else _pct
            unit = " point" if k in ex.POINTS else " %"
            if last is not None:
                cr.append(f"{name} {ex.f(last, 2)} ({ex.f(chg(last, prev1), 2, True)}{unit} en 24 h, {ex.f(chg(last, prev5), 2, True)}{unit} en 5 séances)")
        if cr:
            lines.append("Autres marchés : " + " ; ".join(cr) + ".")
        fg = mac.get("fng")
        if fg:
            lines.append(f"Peur et avidité (Fear & Greed) : {fg['value']} ({fg['label']}).")
        lec0 = None
        try:
            lec0 = svc.lecture(next(iter(svc.markets)))
        except Exception:
            pass
        money = (lec0 or {}).get("money")
        if money:
            lines.append(f"Où est l'argent (parts du capital, 30 jours) : {money.get('reading')} Or (jeton PAXG) {ex.f(money['gold'].get('price'), 0)} $, {ex.f((money['gold'].get('d30') or 0) * 100, 1, True)} % en 30 jours.")
    return "\n".join(lines)


# ======================================================================== assistant
class Assistant:
    def __init__(self, cfg, get_service, data_dir):
        self.cfg, self.get_service = cfg, get_service
        self.path = Path(data_dir) / "assistant.json"
        self.lock = threading.Lock()
        self.busy = threading.Lock()
        self.state = self._load()

    def _load(self) -> dict:
        try:
            st = json.loads(self.path.read_text(encoding="utf-8"))
            return {"history": list(st.get("history") or [])[-200:], "usage": dict(st.get("usage") or {})}
        except (OSError, ValueError):
            return {"history": [], "usage": {}}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    @staticmethod
    def month(now: float | None = None) -> str:
        return datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%Y-%m")

    def spent(self) -> float:
        return float(self.state["usage"].get(self.month(), 0.0))

    def status(self) -> dict:
        c = self.cfg
        m = c.chat_model if c.chat_model in MODELS else DEFAULT_MODEL
        return {"configured": bool(c.chat_key), "sdk": sdk() is not None, "model": m, "modelName": MODELS[m][0], "web": c.chat_web, "telegram": c.chat_telegram and c.telegram_on,
                "telegramConfigured": c.telegram_on, "budget": c.chat_budget, "spent": round(self.spent(), 4), "busy": self.busy.locked(),
                "keyHint": ("..." + c.chat_key[-4:]) if c.chat_key else "", "models": [{"id": k, "name": v[0], "in": v[1], "out": v[2]} for k, v in MODELS.items()]}

    def history(self, n: int = 40) -> list:
        with self.lock:
            return list(self.state["history"][-n:])

    def reset(self):
        with self.lock:
            self.state["history"].append({"role": "system", "text": "Nouvelle conversation.", "t": int(time.time() * 1000), "src": "reset"})
            self._save()

    def _turns(self) -> list:
        """Derniers echanges (question, reponse) depuis le dernier /reset, en texte simple."""
        h = self.state["history"]
        cut = max((i for i, x in enumerate(h) if x["role"] == "system"), default=-1)
        msgs = [{"role": x["role"], "content": x["text"]} for x in h[cut + 1:] if x["role"] in ("user", "assistant") and x.get("ok", True)]
        msgs = msgs[-2 * HISTORY_TURNS:]
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    def _cost(self, model: str, usage_list: list) -> float:
        _, pin, pout, pcache = MODELS.get(model, MODELS[DEFAULT_MODEL])
        usd = 0.0
        for u in usage_list:
            g = lambda k: getattr(u, k, 0) or 0
            usd += g("input_tokens") * pin / 1e6 + g("output_tokens") * pout / 1e6
            usd += g("cache_creation_input_tokens") * pin * 1.25 / 1e6 + g("cache_read_input_tokens") * pcache / 1e6
            stu = getattr(u, "server_tool_use", None)
            usd += (getattr(stu, "web_search_requests", 0) or 0) * WEB_SEARCH_USD if stu else 0.0
        return usd

    def _request(self, client, model: str, messages: list):
        tools = []
        if self.cfg.chat_web:
            tools = [{"type": "web_search_20250305" if model == "claude-haiku-4-5" else "web_search_20260209", "name": "web_search", "max_uses": 3}]
        kw = {"model": model, "max_tokens": 16000, "system": SYSTEM, "messages": messages}
        if tools:
            kw["tools"] = tools
        if model == "claude-haiku-4-5":
            return client.messages.create(**kw)
        kw["output_config"] = {"effort": "medium"}
        return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)    # refus d'un filtre : autre modele, meme appel

    def ask(self, question: str, src: str = "web", now_ms: int | None = None) -> dict:
        """Repond a une question. {ok, answer, usd, model, seconds} ; ok False avec un message lisible en cas de probleme."""
        question = (question or "").strip()[:4000]
        c = self.cfg
        if not question:
            return {"ok": False, "answer": "Question vide."}
        if not c.chat_key:
            return {"ok": False, "answer": "Clé API Claude manquante : Réglages → 7. Discussion avec Claude."}
        anthropic = sdk()
        if anthropic is None:
            return {"ok": False, "answer": "Module Claude non installé : Réglages → 7 → « Installer le module Claude »."}
        if c.chat_budget > 0 and self.spent() >= c.chat_budget:
            return {"ok": False, "answer": f"Budget du mois atteint ({ex.f(self.spent(), 2)} $ sur {ex.f(c.chat_budget, 0)} $) : augmente-le dans Réglages → 7."}
        if not self.busy.acquire(timeout=1.0):
            return {"ok": False, "answer": "Je réponds déjà à une question, renvoie la tienne dans un instant."}
        t0 = time.time()
        model = c.chat_model if c.chat_model in MODELS else DEFAULT_MODEL
        try:
            now = now_ms or ex.now_ms()
            svc = self.get_service()
            try:
                ctx = build_context(svc, now)
            except Exception as e:
                ctx = f"(Données du terminal indisponibles : {type(e).__name__})"
            with self.lock:
                msgs = self._turns()
                self.state["history"].append({"role": "user", "text": question, "t": now, "src": src})
            msgs.append({"role": "user", "content": f"<donnees_du_terminal>\n{ctx}\n</donnees_du_terminal>\n\n{question}"})
            client = anthropic.Anthropic(api_key=c.chat_key, timeout=180.0, max_retries=2)
            usages, resp, done = [], None, []
            try:
                resp = self._request(client, model, msgs)
                usages.append(resp.usage)
                done.append(resp)
                for _ in range(MAX_CONTINUE):                                   # recherche web longue : la reponse reprend la ou elle s'est arretee
                    if resp.stop_reason != "pause_turn":
                        break
                    msgs = msgs + [{"role": "assistant", "content": resp.content}]
                    resp = self._request(client, model, msgs)
                    usages.append(resp.usage)
                    done.append(resp)
            except anthropic.AuthenticationError:
                return self._fail("Clé API refusée par Anthropic : vérifie-la dans Réglages → 7.")
            except anthropic.PermissionDeniedError:
                return self._fail("Cette clé API n'a pas accès à ce modèle.")
            except anthropic.RateLimitError:
                return self._fail("Trop de questions d'un coup pour ton compte Anthropic : réessaie dans une minute.")
            except anthropic.BadRequestError as e:
                msg = str(getattr(e, "message", e))
                return self._fail("Crédit API épuisé : recharge sur console.anthropic.com → Billing." if "credit" in msg.lower() else f"Requête refusée : {msg[:200]}")
            except anthropic.APIStatusError as e:
                return self._fail("Claude est surchargé en ce moment : réessaie dans une minute." if e.status_code >= 500 else f"Erreur de l'API Claude ({e.status_code}).")
            except anthropic.APIConnectionError:
                return self._fail("Pas de connexion à l'API Claude (internet ?).")
            usd = self._cost(model, usages)
            with self.lock:
                m = self.month()
                self.state["usage"][m] = round(self.state["usage"].get(m, 0.0) + usd, 6)
            if resp.stop_reason == "refusal":
                return self._fail("Claude a refusé de répondre à cette question.", usd)
            text = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            srcs = []
            for b in (b for r in done for b in r.content):                  # sources des recherches, y compris celles d'une reponse mise en pause
                if getattr(b, "type", "") == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
                    for r in b.content[:3]:
                        if getattr(r, "url", None) and r.url not in srcs:
                            srcs.append(r.url)
            if srcs and "http" not in text:
                text += "\n\nSources : " + " ; ".join(srcs[:4])
            if resp.stop_reason == "max_tokens":
                text += "\n\n(réponse coupée : trop longue)"
            text = text or "(réponse vide)"
            with self.lock:
                self.state["history"].append({"role": "assistant", "text": text, "t": ex.now_ms(), "src": src, "usd": round(usd, 4), "model": model})
                self._save()
            return {"ok": True, "answer": text, "usd": usd, "model": model, "seconds": round(time.time() - t0, 1)}
        finally:
            self.busy.release()

    def _fail(self, msg: str, usd: float = 0.0) -> dict:
        with self.lock:
            self.state["history"].append({"role": "assistant", "text": msg, "t": ex.now_ms(), "ok": False, "usd": round(usd, 4)})
            self._save()
        return {"ok": False, "answer": msg, "usd": usd}


# ======================================================================== Telegram : discuter avec le bot
class TelegramChat:
    """Lit les messages envoyes au bot (attente longue getUpdates) et repond avec l'assistant. Seul le chat id configure est servi."""

    def __init__(self, cfg, assistant: Assistant, data_dir, make_notifier=None):
        from alerts.notifier import TelegramNotifier
        self.cfg, self.assistant = cfg, assistant
        mk = make_notifier or (lambda timeout: TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id, cfg.telegram_api_base, timeout=timeout))
        self.poll_api, self.send_api = mk(40), mk(20)
        self.offset_path = Path(data_dir) / "telegram_offset.json"
        self.stop = threading.Event()
        self.thread = None
        self.last_error = None
        self.ignored = 0

    def _offset(self):
        try:
            return int(json.loads(self.offset_path.read_text())["offset"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_offset(self, off: int):
        try:
            self.offset_path.parent.mkdir(parents=True, exist_ok=True)
            self.offset_path.write_text(json.dumps({"offset": off}))
        except OSError:
            pass

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, daemon=True, name="telegram-chat")
            self.thread.start()

    def close(self):
        self.stop.set()

    def send(self, text: str):
        for part in split_text(text):
            try:
                self.send_api._call("sendMessage", {"chat_id": self.cfg.telegram_chat_id, "text": part, "disable_web_page_preview": True})
            except Exception as e:
                self.last_error = f"envoi : {type(e).__name__}"

    def handle(self, msg: dict) -> str | None:
        """Traite un message ; renvoie la reponse envoyee (pour les tests)."""
        chat = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if chat != str(self.cfg.telegram_chat_id):
            self.ignored += 1
            return None
        if not text:
            return None
        low = text.lower().split("@")[0]
        if low in ("/start", "/aide", "/help"):
            out = HELP
        elif low == "/reset":
            self.assistant.reset()
            out = "C'est noté : nouvelle conversation."
        elif low in ("/cout", "/coût"):
            st = self.assistant.status()
            out = f"Dépense du mois : {ex.f(st['spent'], 2)} $ sur un budget de {ex.f(st['budget'], 0)} $ ({st['modelName']})."
        else:
            try:
                self.send_api._call("sendChatAction", {"chat_id": self.cfg.telegram_chat_id, "action": "typing"})
            except Exception:
                pass
            out = self.assistant.ask(text, src="telegram")["answer"]
        self.send(out)
        return out

    def run(self):
        off = self._offset()
        fresh = off is None
        while not self.stop.is_set():
            try:
                payload = {"timeout": 25, "allowed_updates": ["message"]}
                if off is not None:
                    payload["offset"] = off
                res = self.poll_api._call("getUpdates", payload)
                self.last_error = None
                if self.stop.is_set():                                         # remplace par un nouvel ecouteur : c'est lui qui traitera ces messages
                    return
                for u in res.get("result", []):
                    off = u["update_id"] + 1
                    self._save_offset(off)
                    m = u.get("message") or {}
                    if fresh and time.time() - m.get("date", 0) > 300:          # premier lancement : on ne repond pas aux vieux messages
                        continue
                    threading.Thread(target=self.handle, args=(m,), daemon=True).start()
                fresh = False
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {str(e)[:120]}"
                self.stop.wait(15)
