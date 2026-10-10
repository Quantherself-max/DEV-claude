"""Avis d'influenceurs sur X (facultatif, INDICATIF) : lecture automatique, par mots-cles, de la position (haussiere /
baissiere) de quelques comptes sur la paire, comparee au sens de l'idee de trade.

Regles d'honnetete
- Cette lecture N'ENTRE PAS dans le score ni dans aucune decision : elle n'est qu'affichee a la fin de l'idee.
- C'est une lecture par mots-cles (francais / anglais, negations et doutes simples) : elle peut se tromper. Chaque compte
  est donne avec un extrait de son post le plus parlant pour que tu verifies toi-meme.
- Seuls les posts recents (48 h par defaut) qui parlent de l'actif comptent ; leur poids baisse de moitie toutes les 12 h.

Module PUR : aucun acces reseau ni disque (voir data/social.py pour la lecture des posts)."""
import re

ASSETS = {
    "BTC": ("btc", "bitcoin", "xbt", "₿"), "ETH": ("eth", "ethereum", "ether"), "SOL": ("sol", "solana"),
    "BNB": ("bnb",), "XRP": ("xrp", "ripple"), "ADA": ("ada", "cardano"), "DOGE": ("doge", "dogecoin"),
    "AVAX": ("avax", "avalanche"), "LINK": ("link", "chainlink"),
}
BULL = {"bullish": 2, "bull": 1, "haussier": 2, "haussière": 2, "haussiere": 2, "breakout": 2, "reclaim": 2, "reclaimed": 2, "uptrend": 2, "rally": 2,
        "rallying": 2, "moon": 2, "mooning": 2, "pump": 1, "pumping": 1, "accumulate": 1, "accumulating": 1, "accumulation": 1, "bounce": 1,
        "bounces": 1, "rebond": 1, "rebondit": 1, "hausse": 1, "buy": 1, "buying": 1, "bought": 1, "achat": 1, "acheter": 1, "achète": 1, "long": 1,
        "longs": 0.5, "longing": 1, "bid": 0.5, "bidding": 1, "🚀": 1, "📈": 1, "🟢": 0.5, "🐂": 1}
BEAR = {"bearish": 2, "bear": 1, "baissier": 2, "baissière": 2, "baissiere": 2, "breakdown": 2, "downtrend": 2, "dump": 1, "dumping": 2, "crash": 2,
        "rekt": 1, "short": 1, "shorts": 0.5, "shorting": 1, "sell": 1, "selling": 1, "sold": 1, "vente": 1, "vendre": 1, "vends": 1, "rejection": 1,
        "rejected": 1, "drop": 1, "dropping": 1, "baisse": 1, "chute": 1, "capitulation": 1, "distribution": 1, "📉": 1, "🔴": 0.5, "🔻": 1, "🐻": 1}
MULTI_BULL = (("higher low", 2), ("higher lows", 2), ("to the moon", 2), ("support held", 2), ("support holds", 2), ("holding support", 2), ("buy the dip", 2),
              ("achat sur repli", 2))
MULTI_BEAR = (("lower high", 2), ("lower highs", 2), ("top is in", 2), ("sell the rip", 2), ("support lost", 2), ("lost support", 2), ("loses support", 2),
              ("vente sur rebond", 2))
NEGATION = {"not", "no", "never", "isn't", "isnt", "aint", "ain't", "without", "pas", "jamais", "plus", "ni", "non"}
HEDGE = {"if", "maybe", "might", "could", "perhaps", "peut-être", "peutetre", "si", "should", "would"}
TERM_AFTER_LONG = {"term", "terme", "-term"}
HALF_LIFE_H = 12.0
CLEAR_RATIO = 0.35


def asset_names(symbol: str):
    base = symbol.upper().replace("USDT", "").replace("USD", "").replace("PERP", "")
    return base, ASSETS.get(base, (base.lower(),))


_TOK = re.compile(r"[\$#]?[a-zà-ÿ'’\-]+|[\U0001F300-\U0001FAFF₿]", re.I)
_URL = re.compile(r"https?://\S+|@\w+")


def tokens(text: str):
    t = _URL.sub(" ", text.lower())
    return [m.group(0).replace("’", "'") for m in _TOK.finditer(t)]


def mentions(text: str, names) -> bool:
    for tk in tokens(text):
        if tk.lstrip("$#") in names:
            return True
    return False


def post_score(text: str) -> float:
    """> 0 haussier, < 0 baissier. Mots-cles ponderes, negations (2 mots avant) et doutes simples."""
    toks = tokens(text)
    s = 0.0
    low = " ".join(toks)
    for phrase, w in MULTI_BULL:
        if phrase in low:
            s += w
    for phrase, w in MULTI_BEAR:
        if phrase in low:
            s -= w
    for i, tk in enumerate(toks):
        w = BULL.get(tk, 0.0) - BEAR.get(tk, 0.0)
        if not w:
            continue
        if tk in ("long", "longs") and i + 1 < len(toks) and toks[i + 1].lstrip("-") in TERM_AFTER_LONG:
            continue                                            # « long term » n'est pas une position longue
        if any(p in NEGATION for p in toks[max(0, i - 2):i]):
            w = -w * 0.7
        s += w
    if s and ("?" in text or any(h in toks for h in HEDGE)):
        s *= 0.6
    return s


def read_account(posts, symbol: str, now_ms: int, max_age_h: float = 48.0) -> dict:
    """posts : [{"t": ms, "text": str}]. Renvoie la position de ce compte sur l'actif :
    stance 'bull' | 'bear' | 'mixed' | 'unclear' | 'none', avec les compteurs et l'extrait le plus parlant."""
    _, names = asset_names(symbol)
    bull = bear = 0.0
    n_bull = n_bear = n_men = 0
    best, best_abs = None, 0.0
    for p in posts:
        age_h = (now_ms - p["t"]) / 3_600_000
        if age_h < -0.1 or age_h > max_age_h or not mentions(p["text"], names):
            continue
        n_men += 1
        sc = post_score(p["text"])
        if abs(sc) < 1.0:
            continue
        w = 0.5 ** (max(0.0, age_h) / HALF_LIFE_H)
        if sc > 0:
            bull += w
            n_bull += 1
        else:
            bear += w
            n_bear += 1
        if abs(sc) * w > best_abs:
            best, best_abs = p, abs(sc) * w
    last = max([p["t"] for p in posts if mentions(p["text"], names) and 0 <= now_ms - p["t"] <= max_age_h * 3_600_000] or [0])
    tot = bull + bear
    if n_men == 0:
        stance = "none"
    elif tot == 0:
        stance = "unclear"
    else:
        r = (bull - bear) / tot
        stance = "bull" if r >= CLEAR_RATIO else "bear" if r <= -CLEAR_RATIO else "mixed"
    return {"stance": stance, "mentions": n_men, "bull": n_bull, "bear": n_bear, "lastAgeH": (now_ms - last) / 3_600_000 if last else None,
            "excerpt": excerpt(best["text"]) if best else None, "url": best.get("url") if best else None}


def excerpt(text: str, n: int = 120) -> str:
    t = re.sub(r"\s+", " ", _URL.sub("", text)).strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def relation(stance: str, side: str) -> str:
    """Face a l'idee : 'agree' | 'disagree' | 'neutral' (pas d'avis net) | 'none' (rien de recent)."""
    if stance == "none":
        return "none"
    if stance in ("unclear", "mixed"):
        return "neutral"
    return "agree" if (stance == "bull") == (side == "long") else "disagree"


STANCE_WORD = {"bull": "haussier", "bear": "baissier", "mixed": "mitigé", "unclear": "sans position claire", "none": "aucun post récent"}


def summarize(accounts: list[dict]) -> dict:
    c = {"agree": 0, "disagree": 0, "neutral": 0, "none": 0, "total": len(accounts), "errors": 0}
    for a in accounts:
        if a.get("error"):
            c["errors"] += 1
        else:
            c[a["relation"]] += 1
    return c


def ago(h) -> str:
    if h is None:
        return ""
    return f"{max(1, round(h * 60))} min" if h < 1 else f"{round(h)} h"


def format_block(op: dict, symbol: str, side: str, excerpts: bool = True, max_len: int = 1800) -> str:
    """Bloc de fin de message (Telegram) : resume, une ligne par compte, avertissement."""
    s = op["summary"]
    ok = s["total"] - s["errors"]
    who = "ACHAT" if side == "long" else "VENTE"
    lines = ["🗣 AVIS D'INFLUENCEURS SUR X (facultatif, indicatif : n'entre PAS dans le score)",
             f"Pour cette idée de {who} sur {symbol} : {s['agree']} d'accord, {s['disagree']} en désaccord, {s['neutral']} sans avis net, "
             f"{s['none']} sans post récent" + (f", {s['errors']} indisponible(s)" if s["errors"] else "") + f" (sur {s['total']} compte(s))."]
    icon = {"agree": "✅", "disagree": "❌", "neutral": "➖", "none": "…"}
    for a in op["accounts"]:
        if a.get("error"):
            lines.append(f"⚠ @{a['handle']} : indisponible ({a['error']})")
            continue
        d = f"{icon[a['relation']]} @{a['handle']} : "
        d += {"agree": "d'accord", "disagree": "en désaccord", "neutral": "sans avis net", "none": "aucun post récent sur " + op["asset"]}[a["relation"]]
        if a["stance"] != "none":
            d += f" ({STANCE_WORD[a['stance']]}, {a['bull']} post(s) haussier(s), {a['bear']} baissier(s), dernier il y a {ago(a['lastAgeH'])})"
        if excerpts and a.get("excerpt"):
            d += f" « {a['excerpt']} »"
        lines.append(d)
    lines.append("Lecture automatique par mots-clés : elle peut se tromper, lis le post avant de t'en servir. Ce n'est pas un conseil.")
    text = "\n".join(lines)
    if len(text) > max_len and excerpts:
        return format_block(op, symbol, side, excerpts=False, max_len=max_len)
    return text
