"""Communication de la Fed (V25) : dates des reunions du comite de politique monetaire (FOMC), communiques, comptes rendus et discours
(flux RSS publics de la Fed), texte des communiques, ce qui a change d'un communique a l'autre (mot a mot), votes contre la decision
et ton du communique (restrictif / accommodant) par un lexique simple et affiche.

Module PUR (aucun acces reseau : le telechargement passe par les fournisseurs de data/external.py). Les pages de la Fed n'ont pas
de format garanti : chaque lecture est tolerante, et un echec laisse la derniere copie gardee."""
from __future__ import annotations
import difflib
import html as html_mod
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FED = "https://www.federalreserve.gov"
FEEDS = {"monetary": "/feeds/press_monetary.xml", "speeches": "/feeds/speeches.xml"}
CALENDAR = "/monetarypolicy/fomccalendars.htm"
DAY = 86_400_000

# Reunions 2026 publiees par la Fed (mardi-mercredi ; * = avec projections economiques). Sert de repli si la page du calendrier
# est injoignable ; la page, lue chaque semaine, donne aussi les annees suivantes.
FOMC_FALLBACK = [(2026, 1, 27, 28, False), (2026, 3, 17, 18, True), (2026, 4, 28, 29, False), (2026, 6, 16, 17, True),
                 (2026, 7, 28, 29, False), (2026, 9, 15, 16, True), (2026, 10, 27, 28, False), (2026, 12, 8, 9, True)]
MONTHS_EN = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                              "october", "november", "december"])}


def _ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def meeting(y, m, d1, d2, sep, m2=None):
    """Reunion : debut et fin (decision le 2e jour vers 14 h a Washington, 18 h ou 19 h UTC)."""
    m2 = m2 or (m if d2 >= d1 else m % 12 + 1)
    y2 = y + 1 if m2 < m else y
    return {"start": _ms(y, m, d1), "end": _ms(y2, m2, d2), "decision": _ms(y2, m2, d2, 18), "sep": bool(sep)}


def fallback_meetings():
    return [meeting(*x) for x in FOMC_FALLBACK]


def clean(fragment: str) -> str:
    """HTML -> texte : balises retirees, entites decodees, espaces normalises."""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


# ---------- calendrier des reunions ----------
def month_num(tok: str) -> int:
    """« January », « Jan », « apr » -> numero du mois (0 si inconnu)."""
    tok = tok.strip().lower()[:3]
    return next((v for k, v in MONTHS_EN.items() if k.startswith(tok)), 0) if len(tok) == 3 else 0


def parse_calendar(page: str) -> list:
    """Page « Meeting calendars » de la Fed -> reunions [{start, end, decision, sep}] (toutes les annees affichees).
    Structure attendue : un titre « 2026 FOMC Meetings » par annee, puis des paires mois (« January », « Apr/May ») / jours
    (« 27-28 », « 17-18* », « 30-1 »). Les lignes sans jours lisibles (vote par ecrit, reunion annulee) sont ignorees."""
    out = []
    parts = re.split(r"(\d{4})\s+FOMC\s+Meetings", page or "")
    for i in range(1, len(parts) - 1, 2):
        year, body = int(parts[i]), parts[i + 1]
        months = re.findall(r"fomc-meeting__month[^>]*>(.*?)</div>", body, re.S | re.I)
        dates = re.findall(r"fomc-meeting__date[^>]*>(.*?)</div>", body, re.S | re.I)
        for mo, da in zip(months, dates):
            mo, da = clean(mo).lower(), clean(da)
            names = [n for n in (month_num(x) for x in mo.split("/")) if n]
            m = re.match(r"(\d{1,2})\s*[-–]\s*(\d{1,2})(\*)?", da)
            if not names or not m or "cancel" in da.lower():
                continue
            d1, d2 = int(m.group(1)), int(m.group(2))
            out.append(meeting(year, names[0], d1, d2, bool(m.group(3)), names[-1] if len(names) > 1 else None))
    return sorted(out, key=lambda x: x["start"])


def next_meeting(meetings: list, t: int):
    """Prochaine decision (reunion en cours comprise) a l'instant t, ou None."""
    for mt in sorted(meetings or [], key=lambda x: x["start"]):
        if mt["decision"] >= t:
            return mt
    return None


def last_meeting(meetings: list, t: int):
    past = [mt for mt in meetings or [] if mt["decision"] <= t]
    return max(past, key=lambda x: x["decision"]) if past else None


# ---------- flux RSS (communiques, discours) ----------
def _tag(item: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, re.S | re.I)
    if not m:
        return ""
    v = m.group(1)
    c = re.match(r"\s*<!\[CDATA\[(.*?)\]\]>\s*$", v, re.S)
    return clean(c.group(1) if c else html_mod.unescape(v))


def kind_of(title: str, feed: str) -> str:
    t = title.lower()
    if feed == "speeches":
        return "speech"
    if "minutes" in t:
        return "minutes"
    if "fomc statement" in t or "issues fomc statement" in t:
        return "statement"
    if "implementation note" in t:
        return "note"
    if "projection" in t:
        return "projections"
    return "release"


def parse_rss(xml: str, feed: str = "monetary") -> list:
    """Flux RSS 2.0 de la Fed -> [{t, title, link, desc, kind, feed}] (lecture par motifs : pas d'analyseur XML sur une source externe)."""
    out = []
    for item in re.findall(r"<item\b[^>]*>(.*?)</item>", xml or "", re.S | re.I):
        title, link, date = _tag(item, "title"), _tag(item, "link"), _tag(item, "pubDate")
        try:
            t = int(parsedate_to_datetime(date).timestamp() * 1000)
        except (TypeError, ValueError, IndexError):
            continue
        if not title or not link.startswith(("http://", "https://")):
            continue
        out.append({"t": t, "title": title, "link": link, "desc": _tag(item, "description")[:400], "kind": kind_of(title, feed), "feed": feed})
    return out


def merge_items(old: list, new: list, now: int, keep_days: int = 400) -> list:
    d = {x["link"]: x for x in old or []}
    d.update({x["link"]: x for x in new or []})
    return sorted((x for x in d.values() if x["t"] >= now - keep_days * DAY), key=lambda x: x["t"], reverse=True)


def speaker(item: dict) -> str:
    """Orateur d'un discours : « Speech by Governor Waller ... », « Vice Chair Jefferson ... », ou la description du flux."""
    for s in (item.get("title", ""), item.get("desc", "")):
        m = re.search(r"\b((?:Vice Chair for Supervision|Vice Chair|Chair|Governor|President)\s+[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,2})", s)
        if m:
            return m.group(1)
    m = re.match(r"([A-Z][A-Za-z'-]+),\s", item.get("title", ""))          # format « Waller, Titre du discours »
    return m.group(1) if m else ""


# ---------- communiques : texte, votes, changements, ton ----------
def statement_paragraphs(page: str) -> list:
    """Paragraphes du communique (sans la note de mise en oeuvre ni les contacts presse)."""
    body = page or ""
    m = re.search(r'id="article"(.*)', body, re.S | re.I)
    if m:
        body = m.group(1)
    body = re.split(r"Implementation Note|For media inquiries|id=\"lastUpdate\"", body, maxsplit=1, flags=re.I)[0]
    pars = [clean(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", body, re.S | re.I)]
    return [p for p in pars if len(p) > 60 and not re.match(r"(for release|for immediate release|share|last update)", p, re.I)]


def sentences(pars: list) -> list:
    """Phrases (sans couper apres une initiale ni « U.S. »)."""
    out = []
    for p in pars or []:
        out += [s.strip() for s in re.split(r"(?<=[a-z0-9%)][.!?])\s+(?=[A-Z])", p) if s.strip()]
    return out


def dissents(pars: list) -> list:
    """Membres qui ont vote contre et ce qu'ils preferaient (texte d'origine, anglais)."""
    txt = " ".join(p for p in pars or [] if "voting against" in p.lower())
    out = []
    for m in re.finditer(r"Voting against (?:this|the) action (?:was|were) (.*?)(?=Voting against|$)", txt):
        out.append(m.group(1).strip().rstrip("."))
    return out


def word_diff(a: str, b: str) -> list:
    """Diff mot a mot entre deux phrases : [(etat, texte)] avec etat '=' (garde), '-' (retire), '+' (ajoute)."""
    wa, wb = a.split(), b.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("=", " ".join(wa[i1:i2])))
        else:
            if i2 > i1:
                out.append(("-", " ".join(wa[i1:i2])))
            if j2 > j1:
                out.append(("+", " ".join(wb[j1:j2])))
    return out


def diff_statements(old: list, new: list) -> dict:
    """Ce qui a change entre deux communiques. Les phrases proches (au moins 55 % de mots communs) sont comparees mot a mot ;
    les autres sont ajoutees ou retirees. {changed: [[(etat, texte)]], added: [...], removed: [...], same: n}"""
    so = [s for s in sentences(old) if not s.lower().startswith("voting")]
    sn = [s for s in sentences(new) if not s.lower().startswith("voting")]
    out = {"changed": [], "added": [], "removed": [], "same": 0}
    sm = difflib.SequenceMatcher(None, so, sn, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out["same"] += i2 - i1
            continue
        olds, news = so[i1:i2], sn[j1:j2]
        used = set()
        for s in news:
            best, bi = 0.0, None
            for k, o in enumerate(olds):
                if k in used:
                    continue
                r = difflib.SequenceMatcher(None, o.split(), s.split(), autojunk=False).ratio()
                if r > best:
                    best, bi = r, k
            if bi is not None and best >= 0.55:
                used.add(bi)
                out["changed"].append(word_diff(olds[bi], s))
            else:
                out["added"].append(s)
        out["removed"] += [o for k, o in enumerate(olds) if k not in used]
    return out


# Lexique du ton (phrases typiques des communiques). Indication grossiere : le texte change peu d'une reunion a l'autre,
# c'est justement ce qui change qui compte (diff_statements).
HAWK = [r"inflation (?:remains|has remained) (?:somewhat )?elevated", r"inflation has moved up", r"upside risks to inflation",
        r"(?:additional|further) policy firming", r"raise the target range", r"increase the target range", r"strong(?:ly)? (?:pace|growth)",
        r"solid pace", r"labor market (?:remains|has remained) (?:solid|strong|tight)", r"(?:has not|not yet) (?:gained|made)",
        r"greater confidence", r"highly attentive to inflation risks", r"reduce its holdings"]
DOVE = [r"lower the target range", r"reduce the target range", r"downside risks to employment",
        r"(?:job gains|employment growth) (?:have|has) slowed", r"unemployment rate has (?:moved|edged|risen) up", r"labor market has (?:softened|cooled|weakened)",
        r"inflation has (?:eased|moderated|declined|come down)", r"growth of economic activity (?:has )?(?:moderated|slowed)",
        r"(?:additional|further) adjustments", r"conclude the reduction", r"end the reduction", r"shift in the balance of risks",
        r"support maximum employment", r"weaken(?:ed|ing)"]


def tone(text: str) -> dict:
    """Ton d'un texte : score = phrases accommodantes − phrases restrictives trouvees (positif = accommodant, favorable aux actifs a risque).
    Les phrases sur les votes sont ignorees (« preferait baisser le taux » n'est pas la decision du comite)."""
    t = " ".join(x for x in sentences([text or ""]) if not x.lower().startswith("voting")).lower()
    hawk = [m.group(0) for p in HAWK for m in re.finditer(p, t)]
    dove = [m.group(0) for p in DOVE for m in re.finditer(p, t)]
    score = len(dove) - len(hawk)
    label = "accommodant" if score >= 2 else "plutôt accommodant" if score == 1 else "restrictif" if score <= -2 else "plutôt restrictif" if score == -1 else "équilibré"
    return {"score": score, "label": label, "hawk": sorted(set(hawk)), "dove": sorted(set(dove))}


def decision(pars: list) -> dict:
    """Decision lue dans le communique : baisse / hausse / maintien du taux, et la nouvelle fourchette telle qu'ecrite."""
    t = " ".join(pars or [])
    m = re.search(r"decided to (lower|raise|maintain|reduce|increase)[^.]*?target range for the federal funds rate(?: by ([\d/\-\s]+) percentage points?)?(?: to| at) ([\d/\-\s]+?(?:to|-)\s?[\d/\-]+) percent", t)
    if not m:
        return {}
    verb = {"reduce": "lower", "increase": "raise"}.get(m.group(1), m.group(1))
    return {"move": {"lower": "baisse", "raise": "hausse", "maintain": "maintien"}[verb], "by": (m.group(2) or "").strip(), "range": m.group(3).strip()}


# ---------- donnees fictives (mode simule et tests) ----------
SIM_STATEMENTS = [
    ("Recent indicators suggest that growth of economic activity moderated in the first half of the year. Job gains have slowed, and the unemployment rate "
     "has edged up but remains low. Inflation has moved up and remains somewhat elevated.",
     "The Committee seeks to achieve maximum employment and inflation at the rate of 2 percent over the longer run. Uncertainty about the economic outlook "
     "remains elevated. The Committee is attentive to the risks to both sides of its dual mandate and judges that downside risks to employment have risen.",
     "In support of its goals and in light of the shift in the balance of risks, the Committee decided to lower the target range for the federal funds rate "
     "by 1/4 percentage point to 4-1/4 to 4-1/2 percent. In considering additional adjustments to the target range for the federal funds rate, the Committee "
     "will carefully assess incoming data, the evolving outlook, and the balance of risks.",
     "Voting for the monetary policy action were the Chair; the Vice Chair; and the other members. Voting against this action was one Governor, who "
     "preferred to lower the target range for the federal funds rate by 1/2 percentage point at this meeting."),
    ("Available indicators suggest that economic activity has been expanding at a moderate pace. Job gains have slowed this year, and the unemployment rate "
     "has edged up through August. Inflation has moved up since earlier in the year and remains somewhat elevated.",
     "The Committee seeks to achieve maximum employment and inflation at the rate of 2 percent over the longer run. Uncertainty about the economic outlook "
     "remains elevated. The Committee is attentive to the risks to both sides of its dual mandate and judges that downside risks to employment rose in recent months.",
     "In support of its goals, the Committee decided to maintain the target range for the federal funds rate at 4-1/4 to 4-1/2 percent. In considering "
     "additional adjustments to the target range for the federal funds rate, the Committee will carefully assess incoming data, the evolving outlook, and "
     "the balance of risks. The Committee decided to conclude the reduction of its aggregate securities holdings on December 1.",
     "Voting for the monetary policy action were the Chair; the Vice Chair; and the other members. Voting against this action were one Governor, who "
     "preferred to lower the target range by 1/4 percentage point, and one President, who preferred no change to the balance sheet at this meeting."),
]


def sim_items(now: int, meetings: list) -> list:
    """Flux fictif coherent : un communique par reunion passee (les deux derniers ont un texte), le compte rendu 3 semaines apres, des discours."""
    out = []
    past = [mt for mt in meetings if mt["decision"] <= now][-4:]
    for k, mt in enumerate(past):
        d = datetime.fromtimestamp(mt["decision"] / 1000, timezone.utc)
        out.append({"t": mt["decision"], "title": "Federal Reserve issues FOMC statement", "kind": "statement", "feed": "monetary", "desc": "",
                    "link": f"{FED}/newsevents/pressreleases/monetary{d:%Y%m%d}a.htm"})
        if mt["decision"] + 21 * DAY <= now:
            out.append({"t": mt["decision"] + 21 * DAY, "title": f"Minutes of the Federal Open Market Committee, {d:%B} {d.day - 1}-{d.day}, {d.year}",
                        "kind": "minutes", "feed": "monetary", "desc": "", "link": f"{FED}/newsevents/pressreleases/monetary{d:%Y%m%d}min.htm"})
    who = ["Governor Waller", "Vice Chair Jefferson", "Governor Bowman", "President Williams", "Governor Barr", "President Hammack"]
    topics = ["the economic outlook", "monetary policy and the labor market", "inflation and the path of policy", "financial stability"]
    for k in range(10):
        t = now - (3 + 6 * k) * DAY
        out.append({"t": t, "title": f"Speech by {who[k % len(who)]} on {topics[k % len(topics)]}", "kind": "speech", "feed": "speeches", "desc": "",
                    "link": f"{FED}/newsevents/speech/sim{k}.htm"})
    return sorted(out, key=lambda x: x["t"], reverse=True)


def sim_rss(items: list) -> str:
    """Flux RSS fictif (meme forme que celui de la Fed) : le mode simule passe par le meme analyseur que les vraies donnees."""
    def one(x):
        d = datetime.fromtimestamp(x["t"] / 1000, timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        return (f"<item><title><![CDATA[{x['title']}]]></title><link>{x['link']}</link><description><![CDATA[{x.get('desc', '')}]]></description>"
                f"<pubDate>{d}</pubDate></item>")
    return '<?xml version="1.0"?><rss version="2.0"><channel><title>FRB</title>' + "".join(one(x) for x in items) + "</channel></rss>"


def sim_calendar_html(meetings: list) -> str:
    """Page fictive du calendrier des reunions (meme structure que celle de la Fed)."""
    names = [k.capitalize() for k in MONTHS_EN]
    by_year = {}
    for mt in meetings:
        a, b = datetime.fromtimestamp(mt["start"] / 1000, timezone.utc), datetime.fromtimestamp(mt["end"] / 1000, timezone.utc)
        mo = names[a.month - 1] if a.month == b.month else f"{names[a.month - 1][:3]}/{names[b.month - 1][:3]}"
        by_year.setdefault(a.year, []).append(f'<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>{mo}</strong></div>'
                                              f'<div class="fomc-meeting__date col-xs-4">{a.day}-{b.day}{"*" if mt["sep"] else ""}</div></div>')
    return "<html><body>" + "".join(f'<div class="panel"><h4><a id="{y}">{y} FOMC Meetings</a></h4>{"".join(rows)}</div>'
                                    for y, rows in sorted(by_year.items(), reverse=True)) + "</body></html>"


def sim_statement_html(pars) -> str:
    return ('<html><body><div id="article"><p class="article__time">For release at 2:00 p.m. EDT</p>' + "".join(f"<p>{p}</p>" for p in pars) +
            '<p><a href="#">Implementation Note issued</a></p><p>For media inquiries, e-mail media@frb.gov or call 202-452-2955.</p></div></body></html>')
