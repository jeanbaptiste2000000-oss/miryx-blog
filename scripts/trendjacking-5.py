#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trendjacking.py — Miryx Check (v4, 24/09/2026) — FR / EN / AR

Pour chaque langue : Google Trends + Google Actualités (éditions locales) sont lus
uniquement pour DÉTECTER UN THÈME relationnel d'actualité (ghosting, rupture, jalousie...).
Le titre de l'actualité n'est JAMAIS transmis au modèle : il ne voit qu'un thème générique
et un message d'exemple fictif tiré d'une liste calibrée. Donc aucun nom de personne ne peut
entrer dans un article, dans aucune langue (garde-fou structurel).

Chaque article : accroche vécue -> encadré « Lecture Miryx » (score issu de la liste calibrée,
jamais du modèle) -> 3 réflexes -> CTA : Challenge sur CE message + analyse gratuite + Texto du Jour.

Règles produit : jamais de vrai message privé, jamais de citation inventée, jamais de source
inventée, aucun sujet sensible, aucun HTML du modèle publié, aucun score écrit par le modèle.
Lancé par .github/workflows/trendjacking.yml toutes les 6 h.
"""
import os
import re
import sys
import json
import time
import html
import datetime
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET

import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")  # même modèle que l'app
GCP_SA_JSON = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
BLOG_BASE_URL = "https://blog.miryxcheck.com"
APP_URL = "https://miryxcheck.com"
LANGS = ("fr", "en", "ar")
MAX_PER_RUN_PER_LANG = 1                                    # 1 article par langue et par passage
DAILY_CAP_PER_LANG = int(os.environ.get("DAILY_CAP", "3"))  # réglage, pas une barrière de principe
MAX_GROQ_CALLS_PER_LANG = 3
THEME_COOLDOWN_DAYS = 2                                     # même thème dans la même langue : pas 2 jours de suite
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MiryxTrendBot/4.0; +https://miryxcheck.com)"}

_AR_MAP = str.maketrans({"ة": "ه", "ى": "ي", "ـ": ""})


def norm(s: str) -> str:
    """minuscules, sans accents/voyelles brèves, formes arabes unifiées (أإآ->ا, ة->ه, ى->ي)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return s.translate(_AR_MAP)


# ── Sources par langue ────────────────────────────────────────────────────────
SOURCES = {
    "fr": {"trends": ["FR"],
           "news": [("fr", "FR", "FR:fr")],
           "queries": ["ghosting", "rupture amoureuse", "situationship", "message ambigu ex"]},
    "en": {"trends": ["NG", "GH", "KE"],
           "news": [("en-NG", "NG", "NG:en"), ("en-GH", "GH", "GH:en"), ("en-KE", "KE", "KE:en")],
           "queries": ["ghosting", "breakup", "situationship", "cheating relationship", "texting ex"]},
    "ar": {"trends": ["MA", "TN"],
           "news": [("ar", "MA", "MA:ar"), ("ar", "TN", "TN:ar")],
           "queries": ["انفصال عاطفي", "علاقة حب", "الخيانة الزوجية", "رسائل الحب"]},
}

# ── Thèmes (le SEUL contenu d'actualité que voit le modèle) ────────────────────
THEMES = {
    "ghosting": {"desc": "someone suddenly stops replying (ghosting, left on read, unanswered messages)",
        "kw": {"fr": ["ghosting", "ghoster", "ghoste", "ne repond plus", "laisse en vu"],
               "en": ["ghosting", "ghosted", "left on read", "stopped replying"],
               "ar": ["غوستينج", "تجاهل", "لا يرد", "عدم الرد"]}},
    "breakup": {"desc": "the silence and the first messages after a breakup or separation",
        "kw": {"fr": ["rupture", "rompre", "separation", "separes", "se separe"],
               "en": ["breakup", "break up", "broke up", "split up", "separation", "dumped"],
               "ar": ["انفصال", "فراق", "انفصلا", "انفصلت"]}},
    "ex": {"desc": "getting or sending a message to an ex",
        "kw": {"fr": ["mon ex", "son ex", "ton ex", "ex copain", "ex copine"],
               "en": ["my ex", "his ex", "her ex", "ex boyfriend", "ex girlfriend"],
               "ar": ["طليقي", "طليقتي", "طليقها", "حبيبي السابق", "حبيبتي السابقة"]}},
    "cheating": {"desc": "trust, suspicion and confusing messages inside a couple after doubt or infidelity",
        "kw": {"fr": ["infidelite", "tromperie", "trompe", "trompee", "tromper"],
               "en": ["cheating", "cheated", "infidelity", "unfaithful"],
               "ar": ["خيانه", "خيانة", "خان", "خانت"]}},
    "jealousy": {"desc": "jealousy and the need for reassurance in texts",
        "kw": {"fr": ["jalousie", "jaloux", "jalouse"],
               "en": ["jealous", "jealousy", "possessive"],
               "ar": ["غيره", "غيرة", "غيور"]}},
    "situationship": {"desc": "unclear relationship status, mixed signals, situationship, friendzone",
        "kw": {"fr": ["situationship", "friendzone", "statut flou"],
               "en": ["situationship", "friendzone", "friend zone", "mixed signals", "talking stage"],
               "ar": ["علاقه غامضه", "سيتويشنشيب"]}},
    "couple_crisis": {"desc": "distance, cold replies and inattention inside a couple going through a rough patch",
        "kw": {"fr": ["crise de couple", "divorce", "divorcer", "en couple", "couple"],
               "en": ["marriage", "divorce", "romantic relationship", "married couple", "dating"],
               "ar": ["زوجين", "الزوجين", "طلاق", "زواج", "علاقه عاطفيه"]}},
    "love_message": {"desc": "love confessions, 'I miss you' type messages and crush texts",
        "kw": {"fr": ["declaration d amour", "je t aime", "amoureux", "amoureuse", "flirt"],
               "en": ["love confession", "in love", "crush", "flirting", "flirt"],
               "ar": ["اعتراف بالحب", "حبيب", "حبيبه", "غزل", "حب"]}},
    "texting": {"desc": "short, ambiguous or slow text replies, read receipts",
        "kw": {"fr": ["texto", "sms", "message ambigu", "message ambigue"],
               "en": ["text message", "texting", "ambiguous message", "dms"],
               "ar": ["رساله", "رسايل", "واتساب"]}},
}
THEME_ORDER = list(THEMES)


def _compile(words: list[str], lang: str) -> re.Pattern:
    alt = "|".join(re.escape(norm(w)) for w in words)
    # Arabe : les particules (ال، و، ب…) se collent aux mots -> recherche par sous-chaîne.
    return re.compile(alt if lang == "ar" else r"\b(?:" + alt + r")\b")


THEME_RE = {(t, l): _compile(THEMES[t]["kw"][l], l) for t in THEMES for l in LANGS}

# Sujets qu'on ne « surfe » jamais : santé grave, mort, violences, mineurs, faits divers.
SENSITIVE = {
    "fr": ["cancer", "deces", "decede", "mort", "mourir", "suicide", "suicid", "deuil", "maladie", "hopital", "viol",
           "violer", "agression", "agresse", "abus", "violence", "violent", "feminicide", "meurtre", "assassin",
           "pedophil", "mineur", "mineure", "inceste", "harcelement", "drame", "accident", "cadavre", "disparition",
           "attentat", "guerre"],
    "en": ["cancer", "death", "dead", "died", "dies", "murder", "killed", "rape", "raped", "suicide", "abuse",
           "abused", "violence", "violent", "assault", "shooting", "accident", "kidnap", "abducted", "terror",
           "war", "minor", "child", "harassment", "hospital", "funeral", "grief"],
    "ar": ["سرطان", "وفاه", "وفاة", "موت", "مات", "قتل", "جريمه", "اغتصاب", "انتحار", "عنف", "حادث", "تحرش",
           "اعتداء", "خطف", "حرب", "ارهاب", "ضحايا", "طفل", "قاصر", "جنازه", "مستشفي", "مرض"],
}
SENS_RE = {l: _compile(SENSITIVE[l], l) for l in LANGS}

# Affirmations que le modèle invente (source citée, faux buzz, fausses études, description fausse du produit).
BANNED = {
    "fr": ["reddit", "subreddit", "r/", "forum", "fait le tour", "revient souvent dans l actualite", "selon une etude",
           "des etudes", "chaque matin", "sondage", "statistiques montrent"],
    "en": ["reddit", "subreddit", "r/", "forum", "went viral", "trending online", "according to a study",
           "studies show", "research shows", "every morning", "survey", "statistics show"],
    "ar": ["reddit", "ريديت", "منتدي", "انتشر", "وفقا لدراسه", "حسب دراسه", "دراسات", "كل صباح", "استطلاع", "احصائيات"],
}
BANNED_RE = {l: re.compile("|".join(re.escape(norm(w)) for w in BANNED[l])) for l in LANGS}

# Exemples fictifs calibrés sur la table du prompt de l'app (vibecheck_main.py, « REPERES DE CALIBRATION »).
# Le score affiché vient d'ici, jamais du modèle. Chaque exemple a son défi prêt dans la table `challenges`
# (created_by = 'miryx-blog') : le lecteur peut « deviner le score » sur CE message, puis créer son propre défi.
EXEMPLES = {
    "fr": [
        {"id": 1, "message": "Ok", "low": 5, "high": 15, "challenge": "Idv5jT1U"},
        {"id": 2, "message": "On verra", "low": 20, "high": 35, "challenge": "6Adv5X7A"},
        {"id": 3, "message": "J'ai été occupé", "low": 20, "high": 35, "challenge": "GtP7LQ0c"},
        {"id": 4, "message": "Je sais pas trop… laisse tomber", "low": 35, "high": 55, "challenge": "sd73wvrh"},
        {"id": 5, "message": "Tu penses à moi des fois ?", "low": 55, "high": 70, "challenge": "nTqCm3XW"},
        {"id": 6, "message": "Je ne sais plus quoi penser de nous", "low": 55, "high": 75, "challenge": "PsaHJSJT"},
        {"id": 7, "message": "Je veux qu'on soit sérieux", "low": 65, "high": 85, "challenge": "ReRk9P1S"},
        {"id": 8, "message": "Tu me manques", "low": 65, "high": 80, "challenge": "jvi5blsz"},
        {"id": 9, "message": "Mdr", "low": 5, "high": 15, "challenge": "8FZDCYcJ"},
        {"id": 10, "message": "T'es chiant parfois", "low": 65, "high": 80, "challenge": "BJSC1iZd"},
    ],
    "en": [
        {"id": 1, "message": "Ok", "low": 5, "high": 15, "challenge": "Xs5iapZu"},
        {"id": 2, "message": "We'll see", "low": 20, "high": 35, "challenge": "b8B4O_vw"},
        {"id": 3, "message": "I've been busy", "low": 20, "high": 35, "challenge": "dSQprejA"},
        {"id": 4, "message": "I don't know… never mind", "low": 35, "high": 55, "challenge": "48lvYQZ9"},
        {"id": 5, "message": "Do you ever think about me?", "low": 55, "high": 70, "challenge": "PmG10RJm"},
        {"id": 6, "message": "I don't know what to think of us anymore", "low": 55, "high": 75, "challenge": "XpeBprA3"},
        {"id": 7, "message": "I want us to be serious", "low": 65, "high": 85, "challenge": "yKzBNEnk"},
        {"id": 8, "message": "I miss you", "low": 65, "high": 80, "challenge": "y8HOqlaB"},
        {"id": 9, "message": "Lol", "low": 5, "high": 15, "challenge": "jym-S-SF"},
        {"id": 10, "message": "You're annoying sometimes", "low": 65, "high": 80, "challenge": "2ZvHk4O1"},
    ],
    "ar": [
        {"id": 1, "message": "أوكي", "low": 5, "high": 15, "challenge": "GqtpMuqy"},
        {"id": 2, "message": "سنرى", "low": 20, "high": 35, "challenge": "2q40UPyr"},
        {"id": 3, "message": "كنت مشغولًا", "low": 20, "high": 35, "challenge": "P0cRKyyg"},
        {"id": 4, "message": "لا أعرف… انسَ الأمر", "low": 35, "high": 55, "challenge": "jzSOVxzZ"},
        {"id": 5, "message": "هل تفكر بي أحيانًا؟", "low": 55, "high": 70, "challenge": "yxOI8SyW"},
        {"id": 6, "message": "لم أعد أعرف ماذا أظن بشأننا", "low": 55, "high": 75, "challenge": "T2UcJgVE"},
        {"id": 7, "message": "أريد أن نأخذ الأمر بجدية", "low": 65, "high": 85, "challenge": "QBstF5wr"},
        {"id": 8, "message": "اشتقت لك", "low": 65, "high": 80, "challenge": "t7KffNAP"},
        {"id": 9, "message": "هههه", "low": 5, "high": 15, "challenge": "U4KH2RxH"},
        {"id": 10, "message": "أنت مزعج أحيانًا", "low": 65, "high": 80, "challenge": "POqBd9Ow"},
    ],
}

SIGNAL = {
    "fr": lambda lab: f"Signal {lab}", "en": lambda lab: f"{lab.capitalize()} signal", "ar": lambda lab: f"إشارة {lab}",
}
SIGNAL_WORDS = {
    "fr": ["très faible", "faible", "modéré", "fort", "extrêmement fort"],
    "en": ["very low", "low", "moderate", "strong", "very strong"],
    "ar": ["ضعيفة جدًا", "ضعيفة", "متوسطة", "قوية", "قوية جدًا"],
}

UI = {
    "fr": {"dir": "ltr", "back": "&larr; Tous les articles", "box": "Lecture Miryx · exemple fictif",
           "bench": "repère Miryx", "alt": "Une version plus claire à envoyer :",
           "h2": "Trois réflexes pour ton prochain texto",
           "note": "Le score mesure l'intensité du signal, pas la valeur de la personne ni de la relation. Une lecture reste une hypothèse, jamais une certitude.",
           "cta_defi": "Devine le score de ce message : tu aurais mis combien ? &rarr;",
           "cta_app": "Colle ton dernier texto ambigu · analyse gratuite, sans compte &rarr;",
           "cta_game": "Joue au Texto du Jour &rarr;", "legal": "Mentions légales", "priv": "Confidentialité",
           "idx_title": "Miryx Academy — Décoder les messages ambigus",
           "idx_desc": "Articles sur les textos ambigus, le ghosting, les ruptures et comment décoder ce que les gens veulent vraiment dire.",
           "empty": "Premiers articles bientôt."},
    "en": {"dir": "ltr", "back": "&larr; All articles", "box": "Miryx reading · fictional example",
           "bench": "Miryx benchmark", "alt": "A clearer version to send:",
           "h2": "Three moves for your next text",
           "note": "The score measures signal intensity, not a person's worth or the relationship's. A reading is a hypothesis, never a certainty.",
           "cta_defi": "Guess this message's score: what would you say? &rarr;",
           "cta_app": "Paste your last confusing text · free analysis, no account &rarr;",
           "cta_game": "Play Text of the Day &rarr;", "legal": "Legal notice", "priv": "Privacy",
           "idx_title": "Miryx Academy — Decode ambiguous messages",
           "idx_desc": "Articles on ambiguous texts, ghosting, breakups and how to decode what people really mean.",
           "empty": "First articles coming soon."},
    "ar": {"dir": "rtl", "back": "&rarr; كل المقالات", "box": "قراءة Miryx · مثال افتراضي",
           "bench": "مؤشر Miryx", "alt": "صيغة أوضح يمكنك إرسالها:",
           "h2": "ثلاث خطوات لرسالتك القادمة",
           "note": "الدرجة تقيس شدة الإشارة، لا قيمة الشخص ولا العلاقة. القراءة مجرد فرضية، وليست يقينًا.",
           "cta_defi": "خمّن درجة هذه الرسالة: كم كنت ستعطيها؟ &larr;",
           "cta_app": "الصق آخر رسالة محيّرة · تحليل مجاني بلا حساب &larr;",
           "cta_game": "العب رسالة اليوم &larr;", "legal": "إشعار قانوني", "priv": "الخصوصية",
           "idx_title": "Miryx Academy — فك شفرة الرسائل الغامضة",
           "idx_desc": "مقالات عن الرسائل الغامضة والتجاهل والانفصال وكيف تفهم ما يقصده الناس فعلًا.",
           "empty": "المقالات الأولى قريبًا."},
}
LANG_NAME = {"fr": "French", "en": "English", "ar": "Arabic (Modern Standard, simple and warm, understood from Morocco to the Gulf; avoid heavy dialect)"}
FORBIDDEN_TITLE_START = {"fr": "quand ", "en": "when ", "ar": "عندما "}


def signal_label(lang: str, low: int, high: int) -> str:
    """Échelle officielle du prompt : 0-20 très faible, 21-40 faible, 41-60 modéré, 61-80 fort, 81-100 extrêmement fort."""
    mid = (low + high) / 2
    idx = 0 if mid <= 20 else 1 if mid <= 40 else 2 if mid <= 60 else 3 if mid <= 80 else 4
    return SIGNAL[lang](SIGNAL_WORDS[lang][idx])


# ── État : dérivé des fichiers meta (source de vérité unique) ──────────────────
def read_metas() -> list[dict]:
    out = []
    for lang in LANGS:
        d = os.path.join("articles", lang)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith(".meta.json"):
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        m = json.load(f)
                    m["lang"], m["slug"] = lang, fn[:-len(".meta.json")]
                    out.append(m)
                except Exception:
                    pass
    return out


def today_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", norm(title)).strip("-")
    return s[:70].strip("-")


# ── Sources ───────────────────────────────────────────────────────────────────
def _get_xml(url: str):
    r = requests.get(url, headers=HTTP_HEADERS, timeout=20)
    r.raise_for_status()
    return ET.fromstring(r.content)


def fetch_texts(lang: str) -> tuple[list[str], bool]:
    """Retourne (textes bruts d'actualité, ok). Ces textes ne servent QU'À détecter un thème."""
    cfg, texts, ok_any = SOURCES[lang], [], False
    for geo in cfg["trends"]:
        try:
            root = _get_xml(f"https://trends.google.com/trending/rss?geo={geo}")
            ok_any = True
        except Exception as e:
            print(f"[WARN] Trends {geo} indisponible: {e}")
            continue
        for it in root.iter("item"):
            parts = [(it.findtext("title") or "")]
            for el in it.iter():  # indépendant du namespace 'ht:'
                if el.tag.split("}")[-1] in ("news_item_title", "news_item_snippet") and el.text:
                    parts.append(el.text)
            texts.append(" ".join(parts))
    for hl, gl, ceid in cfg["news"]:
        for q in cfg["queries"]:
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": f"{q} when:2d", "hl": hl, "gl": gl, "ceid": ceid})
            try:
                root = _get_xml(url)
                ok_any = True
            except Exception as e:
                print(f"[WARN] Actualités {lang}/{gl} « {q} » indisponible: {e}")
                continue
            for it in list(root.iter("item"))[:8]:
                texts.append((it.findtext("title") or ""))
    return texts, ok_any


def detect_themes(lang: str, texts: list[str]) -> dict[str, int]:
    """{thème: nombre d'actualités non sensibles qui l'évoquent}. Le contenu des textes est jeté ici."""
    counts: dict[str, int] = {}
    for t in texts:
        n = norm(t)
        if SENS_RE[lang].search(n):
            continue
        for theme in THEME_ORDER:
            if THEME_RE[(theme, lang)].search(n):
                counts[theme] = counts.get(theme, 0) + 1
                break
    return counts


# ── Garde-fous sur le contenu généré ──────────────────────────────────────────
def plain_text(s: str) -> str:
    s = re.sub(r"</?(?:p|h2|ul|ol|li|br)\b[^>]*>", "\n", s or "")
    return html.unescape(re.sub(r"<[^>]+>", "", s))


ALLOWED_CAPS = {
    "miryx", "check", "texto", "jour", "academy", "instagram", "whatsapp", "snapchat", "tiktok", "facebook", "google",
    "messenger", "telegram", "internet", "france", "paris", "dakar", "afrique", "ia", "sms", "wave", "orange", "money",
    "feu", "vert", "radar", "ghost", "detector", "decode", "wrapped", "text", "day", "of", "dm", "ok", "lol",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "lundi", "mardi", "mercredi",
    "jeudi", "vendredi", "samedi", "dimanche",
}


def has_proper_name(text: str) -> bool:
    """FR/EN : deux mots capitalisés consécutifs (hors liste autorisée) = probable nom de personne.
    (L'arabe n'a pas de majuscules : la protection y est structurelle, le modèle ne voit aucun nom.)"""
    for sent in re.split(r"(?<=[.!?…:;])\s+|\n", plain_text(text)):
        run = 0
        for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]*", sent):
            capitalized = len(w) > 1 and w[0].isupper() and not re.match(r"^I['’]", w) and norm(w) not in ALLOWED_CAPS
            run = run + 1 if capitalized else 0
            if run >= 2:
                return True
    return False


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"\w+", norm(s)) if len(w) >= 4}


def too_similar_title(titre: str, previous: list[str]) -> bool:
    """Même premier mot qu'un titre récent ou fort recouvrement de mots."""
    first = norm(titre).split(" ")[0] if titre else ""
    w = _words(titre)
    for p in previous:
        if first and first == norm(p).split(" ")[0]:
            return True
        wp = _words(p)
        if w and wp and len(w & wp) / len(w | wp) > 0.4:
            return True
    return False


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()


def render_body(lang: str, art: dict, ex: dict) -> str:
    e, ui = html.escape, UI[lang]
    paras = "".join(f"<p>{e(p.strip())}</p>" for p in re.split(r"\n\s*\n", art["accroche"]) if p.strip())
    conseils = "".join(f"<li>{e(c)}</li>" for c in art["conseils"])
    return (
        f"{paras}\n"
        '<div class="miryx-box">\n'
        f'<div class="kicker">{ui["box"]}</div>\n'
        f'<p class="msg" dir="auto">« {e(ex["message"])} »</p>\n'
        f'<p class="score"><strong>{signal_label(lang, ex["low"], ex["high"])}</strong> · {ui["bench"]} : {ex["low"]}–{ex["high"]} %</p>\n'
        f'<p>{e(art["lecture"])}</p>\n'
        f'<p class="alt"><strong>{ui["alt"]}</strong> « {e(art["reformulation"])} »</p>\n'
        "</div>\n"
        f'<h2>{ui["h2"]}</h2>\n'
        f"<ol>{conseils}</ol>\n"
        f'<p class="note">{ui["note"]}</p>'
    )


def validate_article(lang: str, data: dict, allowed_ids: list[int]) -> dict | None:
    """Retourne {titre, meta_description, corps_html, exemple_id} ou None. Rejeté = non publié."""
    try:
        eid = int(data["exemple_id"])
        ex = next(x for x in EXEMPLES[lang] if x["id"] == eid and eid in allowed_ids)
        art = {k: _clean(data[k]) for k in ("titre", "meta_description", "lecture", "reformulation")}
        art["accroche"] = re.sub(r"[ \t]+", " ", str(data["accroche"])).strip()
        conseils = [_clean(c) for c in data["conseils"]]
    except Exception:
        print("[WARN] Réponse incomplète ou exemple_id invalide, article ignoré")
        return None
    art["conseils"] = conseils
    checks = [
        (25 <= len(art["titre"]) <= 95, "titre hors limites"),
        (100 <= len(art["meta_description"]) <= 165, "meta description hors limites"),
        (150 <= len(art["accroche"]) <= 700, "accroche hors limites"),
        (80 <= len(art["lecture"]) <= 700, "lecture hors limites"),
        (12 <= len(art["reformulation"]) <= 200, "reformulation hors limites"),
        (len(conseils) == 3 and all(20 <= len(c) <= 240 for c in conseils), "il faut exactement 3 conseils"),
    ]
    for ok, why in checks:
        if not ok:
            print(f"[WARN] {why}, article ignoré")
            return None
    fields = [art["titre"], art["meta_description"], art["accroche"], art["lecture"], art["reformulation"]] + conseils
    blob = "\n".join(fields)
    if "%" in blob or "٪" in blob or re.search(r"\d", art["lecture"]):
        print("[WARN] Le modèle a écrit un score/pourcentage (interdit : le score vient du code), article ignoré")
        return None
    if len(blob.split()) < 120:
        print("[WARN] Article trop court, article ignoré")
        return None
    if BANNED_RE[lang].search(norm(blob)):
        print("[WARN] Affirmation interdite (source citée, fausse étude, faux buzz...), article rejeté")
        return None
    previous = [m.get("titre", "") for m in sorted(read_metas(), key=lambda m: m.get("date", ""), reverse=True)
                if m["lang"] == lang][:8]
    if norm(art["titre"]).startswith(FORBIDDEN_TITLE_START[lang]) or too_similar_title(art["titre"], previous):
        print("[WARN] Titre trop proche des articles récents (ou formule interdite), article rejeté")
        return None
    if lang != "ar" and any(has_proper_name(f) for f in fields):
        print("[WARN] Nom propre probable détecté, article rejeté (règle anti-diffamation)")
        return None
    return {"titre": art["titre"], "meta_description": art["meta_description"],
            "corps_html": render_body(lang, art, ex), "exemple_id": eid}


def _extract_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}") + 1
    return json.loads(raw[start:end])


def generate_article(lang: str, theme: str, allowed_ids: list[int]) -> dict | None:
    menu = "\n".join(f'{x["id"]}. « {x["message"]} »' for x in EXEMPLES[lang] if x["id"] in allowed_ids)
    system_prompt = f"""You write for the blog of Miryx Check (miryxcheck.com), an app that decodes the subtext of ambiguous messages (intensity score, reading, possible replies).
WRITE EVERYTHING IN: {LANG_NAME[lang]}. Second person, direct, warm, never preachy or dramatic.

ABSOLUTE RULES:
- The theme below is only a general subject. Never mention news, events, celebrities or anyone real. Never name any person.
- No real private message, no quote attributed to a real person.
- Never invent a source, a study, a statistic or a "buzz". Never mention a platform such as Reddit or a forum.
- NEVER write a percentage or a score: the score is added automatically.
- Do not say "every morning". Miryx Check decodes the subtext of a message; Text of the Day is a free daily game where you guess the intensity of a fictional ambiguous message from 0 to 100.

THEME: {THEMES[theme]["desc"]}

PICK ONE example message (exemple_id) that best illustrates the theme:
{menu}

RETURN strict JSON with these fields (plain text, NO HTML tags):
- "titre": 40-90 characters, tense and concrete, makes people want to click without lying. May quote the chosen message between « ». Forbidden: starting with "When"/"Quand"/"عندما", the phrase "decode ambiguous messages", any digit or percentage.
- "meta_description": 130-158 characters with the reader's benefit.
- "accroche": 3-5 sentences starting straight from a lived situation (the reader recognises themselves in 5 seconds). No "recently", no "we often see".
- "exemple_id": the number you chose.
- "lecture": 2 plausible hypotheses about what this message can mean, worded as hypotheses ("it can mean…"), with no digit.
- "reformulation": a clearer, more direct version of the message the person could send instead, same register.
- "conseils": exactly 3 very concrete tips applicable to the next text, 1-2 sentences each. No generalities.
Impeccable spelling and grammar."""
    base = {"model": GROQ_MODEL, "temperature": 0.7, "max_tokens": 2500,
            # mêmes réglages que l'app (vibecheck_main.py) : sans eux, le raisonnement interne
            # de gpt-oss pollue la réponse et casse l'extraction JSON.
            "reasoning_format": "hidden", "reasoning_effort": "low",
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": "Return the JSON now."}]}
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    url = "https://api.groq.com/openai/v1/chat/completions"
    try:
        r = requests.post(url, headers=headers, timeout=90, json={**base, "response_format": {"type": "json_object"}})
        if r.status_code == 400:  # ce combo de paramètres refusé : on retente sans response_format
            r = requests.post(url, headers=headers, timeout=90, json=base)
        r.raise_for_status()
        data = _extract_json(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"[WARN] Génération Groq échouée ({lang}/{theme}): {e}")
        return None
    return validate_article(lang, data, allowed_ids)


# ── Rendu ─────────────────────────────────────────────────────────────────────
def json_for_script(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def index_path(lang: str) -> str:
    return "index.html" if lang == "fr" else f"{lang}/index.html"


def index_url(lang: str) -> str:
    return f"{BLOG_BASE_URL}/" if lang == "fr" else f"{BLOG_BASE_URL}/{lang}/"


CSS = """:root{--bg:#0B0B0F;--text:#fff;--accent:#00E5FF;--muted:#888;}
*{box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:-apple-system,system-ui,sans-serif;margin:0;padding:32px 20px 60px;max-width:680px;margin-inline:auto;line-height:1.7;}
h1{font-size:1.7rem;line-height:1.3;} h2{font-size:1.25rem;margin-top:1.8em;}
p,li{color:#ddd;font-size:1.05rem;}
.back{color:var(--accent);text-decoration:none;font-weight:700;font-size:0.9rem;}
.cta{display:block;text-align:center;margin-top:14px;padding:16px;background:var(--accent);color:#000;border-radius:12px;font-weight:800;text-decoration:none;}
.cta.alt{background:transparent;color:var(--accent);border:2px solid var(--accent);}
.cta.soft{background:transparent;color:#aaa;font-weight:600;}
.brand{font-weight:900;margin-bottom:24px;} .brand span{color:var(--accent);}
.miryx-box{background:#14141C;border:1px solid var(--accent);border-radius:14px;padding:18px 20px;margin:28px 0;}
.miryx-box .kicker{color:var(--accent);font-size:0.75rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;margin-bottom:8px;}
.miryx-box .msg{font-size:1.3rem;font-weight:800;color:#fff;margin:6px 0;}
.miryx-box .score{color:var(--accent);margin:4px 0 12px;}
.note{color:var(--muted);font-size:0.85rem;}
.langs a{color:#777;text-decoration:none;font-weight:700;margin:0 4px;font-size:0.8rem;}
footer{margin-top:40px;font-size:0.8rem;color:var(--muted);} footer a{color:var(--muted);}"""


def article_page(lang: str, art: dict, meta: dict, url: str) -> str:
    ui, e = UI[lang], html.escape
    challenge = next(x["challenge"] for x in EXEMPLES[lang] if x["id"] == meta["exemple_id"])
    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{ui['dir']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(art['titre'])} — Miryx Academy</title>
<meta name="description" content="{e(art['meta_description'])}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Miryx Academy">
<meta property="og:title" content="{e(art['titre'])}">
<meta property="og:description" content="{e(art['meta_description'])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{APP_URL}/api/og-image">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="675">
<meta property="article:published_time" content="{meta['date']}">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "inLanguage": "{lang}",
  "headline": {json_for_script(art['titre'])},
  "description": {json_for_script(art['meta_description'])},
  "datePublished": "{meta['date']}",
  "dateModified": "{meta['date']}",
  "mainEntityOfPage": "{url}",
  "author": {{"@type": "Organization", "name": "Miryx Check"}},
  "publisher": {{"@type": "Organization", "name": "Miryx Check", "url": "{APP_URL}"}}
}}
</script>
<style>
{CSS}
</style>
</head>
<body>
<div class="brand">Miryx<span>Check</span> — Academy</div>
<a class="back" href="{index_url(lang)}">{ui['back']}</a>
<h1>{e(art['titre'])}</h1>
{art['corps_html']}
<a class="cta" href="{APP_URL}/d/{challenge}?src=blog-defi">{ui['cta_defi']}</a>
<a class="cta alt" href="{APP_URL}/app?src=blog-app&amp;lang={lang}">{ui['cta_app']}</a>
<a class="cta soft" href="{APP_URL}/texto-du-jour?src=blog-jeu&amp;lang={lang}">{ui['cta_game']}</a>
<footer><a href="{APP_URL}/mentions-legales">{ui['legal']}</a> · <a href="{APP_URL}/confidentialite">{ui['priv']}</a></footer>
</body>
</html>"""


def build_index(lang: str, metas: list[dict]) -> str:
    ui, e = UI[lang], html.escape
    mine = sorted([m for m in metas if m["lang"] == lang], key=lambda m: (m["date"], m["slug"]), reverse=True)
    items = "\n".join(f'<li><a href="/articles/{lang}/{m["slug"]}.html">{e(m["titre"])}</a><span>{e(m["date"])}</span></li>'
                      for m in mine) or f'<li>{ui["empty"]}</li>'
    switch = " · ".join(f'<a href="{index_url(l)}">{l.upper()}</a>' for l in LANGS)
    return f"""<!DOCTYPE html>
<html lang="{lang}" dir="{ui['dir']}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(ui['idx_title'])}</title>
<meta name="description" content="{e(ui['idx_desc'])}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{index_url(lang)}">
<style>
{CSS}
ul{{list-style:none;padding:0;}}
li{{padding:16px 0;border-bottom:1px solid #232330;display:flex;justify-content:space-between;gap:12px;}}
li a{{color:var(--text);text-decoration:none;font-weight:600;}} li a:hover{{color:var(--accent);}}
li span{{color:#666;font-size:0.85rem;white-space:nowrap;}}
</style></head><body>
<div class="brand">Miryx<span>Check</span> Academy</div>
<div class="langs">{switch}</div>
<ul>
{items}
</ul>
</body></html>"""


def build_sitemap(metas: list[dict]) -> str:
    urls = [f"  <url><loc>{index_url(l)}</loc></url>" for l in LANGS]
    for m in sorted(metas, key=lambda m: (m["lang"], m["slug"])):
        urls.append(f'  <url><loc>{BLOG_BASE_URL}/articles/{m["lang"]}/{m["slug"]}.html</loc><lastmod>{m["date"]}</lastmod></url>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>\n")


ROBOTS = f"User-agent: *\nAllow: /\n\nSitemap: {BLOG_BASE_URL}/sitemap.xml\n"


def request_indexing(url: str) -> None:
    """Best-effort. L'API d'indexation est officiellement prévue pour JobPosting / BroadcastEvent :
    ne pas compter dessus. Le sitemap.xml est le vrai mécanisme."""
    if not GCP_SA_JSON:
        return
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        creds = service_account.Credentials.from_service_account_info(
            json.loads(GCP_SA_JSON), scopes=["https://www.googleapis.com/auth/indexing"])
        resp = AuthorizedSession(creds).post(
            "https://indexing.googleapis.com/v3/urlNotifications:publish",
            json={"url": url, "type": "URL_UPDATED"}, timeout=20)
        print(f"[{'OK' if resp.status_code == 200 else 'WARN'}] Indexing API {resp.status_code} pour {url}")
    except Exception as e:
        print(f"[WARN] Indexation échouée (non bloquant): {e}")


def publish(lang: str, art: dict) -> dict:
    date = today_iso()
    slug = slugify(art["titre"]) or f"{art['theme']}-{art['exemple_id']}-{date}"  # titres arabes : pas de latin -> slug neutre
    d = os.path.join("articles", lang)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, f"{slug}.html")):
        slug = f"{slug[:60]}-{date}"
    meta = {"titre": art["titre"], "date": date, "exemple_id": art["exemple_id"], "theme": art["theme"]}
    url = f"{BLOG_BASE_URL}/articles/{lang}/{slug}.html"
    with open(os.path.join(d, f"{slug}.html"), "w", encoding="utf-8") as f:
        f.write(article_page(lang, art, meta, url))
    with open(os.path.join(d, f"{slug}.meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"[OK] Article publié ({lang}) : {slug}")
    request_indexing(url)
    return {**meta, "lang": lang, "slug": slug}


def main() -> int:
    if not GROQ_API_KEY:
        print("[ERREUR] GROQ_API_KEY absent — ajoute-le dans Settings → Secrets → Actions de CE dépôt")
        return 1
    any_source, created = False, 0
    for lang in LANGS:
        metas = read_metas()
        mine = [m for m in metas if m["lang"] == lang]
        if sum(m.get("date") == today_iso() for m in mine) >= DAILY_CAP_PER_LANG:
            print(f"[INFO] {lang}: plafond quotidien atteint ({DAILY_CAP_PER_LANG}).")
            any_source = True
            continue
        texts, ok = fetch_texts(lang)
        any_source = any_source or ok
        counts = detect_themes(lang, texts)
        print(f"[INFO] {lang}: {len(texts)} actualités lues, thèmes détectés: {counts or 'aucun'}")
        cutoff = (datetime.date.today() - datetime.timedelta(days=THEME_COOLDOWN_DAYS)).isoformat()
        made = calls = 0
        for theme in sorted(counts, key=lambda t: -counts[t]):
            if made >= MAX_PER_RUN_PER_LANG or calls >= MAX_GROQ_CALLS_PER_LANG:
                break
            if any(m.get("theme") == theme and m.get("date", "") >= cutoff for m in mine):
                continue
            used = {m.get("exemple_id") for m in mine if m.get("theme") == theme}
            allowed = [x["id"] for x in EXEMPLES[lang] if x["id"] not in used]
            if not allowed:
                continue
            calls += 1
            art = generate_article(lang, theme, allowed)
            if art is None:
                continue
            art["theme"] = theme
            publish(lang, art)
            made += 1
            created += 1
            time.sleep(2)
    if created:
        metas = read_metas()
        for lang in LANGS:
            os.makedirs(os.path.dirname(index_path(lang)) or ".", exist_ok=True)
            with open(index_path(lang), "w", encoding="utf-8") as f:
                f.write(build_index(lang, metas))
        with open("sitemap.xml", "w", encoding="utf-8") as f:
            f.write(build_sitemap(metas))
    else:
        print("[INFO] Aucun nouvel article ce passage — pas une erreur (pas de thème d'actualité, cooldown, ou garde-fou).")
    if not os.path.exists("robots.txt"):
        with open("robots.txt", "w", encoding="utf-8") as f:
            f.write(ROBOTS)
    if not any_source:
        print("[ERREUR] Aucune source joignable — run en échec volontaire pour que ça se voie")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
