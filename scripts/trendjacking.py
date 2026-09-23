#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trendjacking.py — Miryx Check
Scanne Google Trends (FR) + Reddit (relations/dating), filtre les sujets
pertinents pour Miryx (rupture, ghosting, texto ambigu, couple), génère un
article via Groq avec l'angle produit, publie sur le blog (fichiers HTML
statiques dans ce même dépôt) et force l'indexation Google.

REGLES NON NEGOCIABLES (héritées des principes produit Miryx, voir
MIRYX_REFERENCE.md) :
  - Jamais de vrai message privé d'un tiers, même dans un article sur une
    actualité people. L'article parle du TYPE de situation (ex: "après une
    rupture très médiatisée"), jamais de contenu de message qu'on n'a pas
    et qu'on ne doit pas inventer comme si c'était réel.
  - Jamais de citation inventée attribuée à une vraie personne.
  - Français uniquement (décision produit : fr-only tant que le Texto du
    Jour n'a pas atteint son signal J+60).
  - Un article par sujet déjà publié : jamais de republication.

Lancé par .github/workflows/trendjacking.yml, toutes les 6h.
"""
import os
import re
import json
import time
import hashlib
import datetime
import urllib.request
import xml.etree.ElementTree as ET

import feedparser  # lecture RSS (Google Trends + Reddit)
import requests

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GCP_SA_JSON = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
BLOG_BASE_URL = "https://blog.miryxcheck.com"
APP_URL = "https://miryxcheck.com"
PUBLISHED_FILE = "published.json"
MAX_ARTICLES_PER_RUN = 2  # jamais plus de 2 articles par passage — pas de spam de contenu

# Filtre volontairement plus large que celui de JAMILA (qui a produit 0 article
# sur 499 exécutions en filtrant trop strict sur la finance perso, un sujet qui
# ne trend jamais). Les sujets relationnels trendent en continu — inutile de
# sur-filtrer, le risque ici est l'inverse : rater un vrai pic d'actualité.
KEYWORDS = [
    "rupture", "romptu", "rompu", "ex petit", "ex copain", "ex copine",
    "ghosting", "ghost", "texto", "message ambigu", "sms",
    "couple", "en couple", "célibataire", "divorce", "séparation",
    "infidélité", "tromper", "trompé", "jalousie", "ne répond plus",
    "friendzone", "red flag", "situationship", "dating",
]

STATE_LABEL = "trendjacking-bot"


def load_published() -> set[str]:
    if not os.path.exists(PUBLISHED_FILE):
        return set()
    with open(PUBLISHED_FILE, encoding="utf-8") as f:
        return set(json.load(f))


def save_published(published: set[str]) -> None:
    with open(PUBLISHED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(published), f, ensure_ascii=False, indent=2)


def slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[àâä]", "a", s)
    s = re.sub(r"[éèêë]", "e", s)
    s = re.sub(r"[îï]", "i", s)
    s = re.sub(r"[ôö]", "o", s)
    s = re.sub(r"[ùûü]", "u", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80]


def matches_keywords(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in KEYWORDS)


def fetch_google_trends() -> list[dict]:
    """Flux RSS des tendances quotidiennes Google, France."""
    url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=FR"
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            items.append({"title": title, "summary": summary, "source": "google_trends"})
        return items
    except Exception as e:
        print(f"[WARN] Google Trends indisponible: {e}")
        return []


def fetch_reddit() -> list[dict]:
    """Flux RSS de 2 subreddits relations/dating, posts récents."""
    subs = ["relationships", "dating_advice"]
    items = []
    for sub in subs:
        url = f"https://www.reddit.com/r/{sub}/new/.rss?limit=20"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MiryxTrendBot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            feed = feedparser.parse(data)
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or ""
                items.append({"title": title, "summary": summary, "source": f"reddit_{sub}"})
        except Exception as e:
            print(f"[WARN] Reddit r/{sub} indisponible: {e}")
    return items


def generate_article(topic_title: str, topic_summary: str, source: str) -> dict | None:
    """Génère un article via Groq. Retourne None si le modèle refuse ou si la
    sortie n'est pas exploitable (jamais de fallback qui invente du contenu)."""
    system_prompt = """Tu écris pour le blog de Miryx Check (miryxcheck.com), une app qui aide à décoder le sous-texte des messages ambigus.

RÈGLES ABSOLUES :
- Français uniquement.
- Ne JAMAIS inventer ou citer un message privé réel de qui que ce soit, même une personnalité publique. Tu peux évoquer QU'UNE situation (rupture, silence radio, ghosting) fait l'actualité, jamais reconstituer un texto que tu n'as pas.
- Ne JAMAIS inventer de citation attribuée à une vraie personne.
- L'article part d'une actualité ou d'un sujet qui trend, l'utilise comme accroche, puis bascule vers un conseil général et intemporel sur les messages ambigus (le vrai sujet de Miryx) — jamais un article de gossip sur la personne elle-même.
- Ton : direct, chaleureux, jamais moralisateur. Public : jeunes adultes francophones.
- 300 à 450 mots. Un titre accrocheur (pas de clickbait mensonger). Une conclusion qui mentionne naturellement Miryx Check et son Texto du Jour (miryxcheck.com/texto-du-jour), sans être une pub lourde.
- Réponds UNIQUEMENT en JSON strict : {"titre": "...", "meta_description": "...(150-160 caractères)...", "corps_html": "...(paragraphes <p>, pas de <html>/<body>)..."}"""

    user_prompt = f"""Sujet qui trend (source: {source}) :
Titre : {topic_title}
Contexte : {topic_summary[:500]}

Écris l'article maintenant."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        if not all(k in data for k in ("titre", "meta_description", "corps_html")):
            print("[WARN] Réponse Groq incomplète, article ignoré")
            return None
        return data
    except Exception as e:
        print(f"[WARN] Génération Groq échouée: {e}")
        return None


ARTICLE_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre} — Miryx Academy</title>
<meta name="description" content="{meta_description}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:title" content="{titre}">
<meta property="og:description" content="{meta_description}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{app_url}/api/og-image">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": {titre_json},
  "description": {meta_description_json},
  "datePublished": "{date_iso}",
  "author": {{"@type": "Organization", "name": "Miryx Check"}},
  "publisher": {{"@type": "Organization", "name": "Miryx Check"}}
}}
</script>
<style>
:root{{--bg:#0B0B0F;--card:#1A1A24;--text:#fff;--accent:#00E5FF;--muted:#888;}}
*{{box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,system-ui,sans-serif;margin:0;padding:32px 20px 60px;max-width:680px;margin-inline:auto;line-height:1.7;}}
h1{{font-size:1.7rem;line-height:1.3;}}
p{{color:#ddd;font-size:1.05rem;}}
.back{{color:var(--accent);text-decoration:none;font-weight:700;font-size:0.9rem;}}
.cta{{display:block;text-align:center;margin-top:36px;padding:16px;background:var(--accent);color:#000;border-radius:12px;font-weight:800;text-decoration:none;}}
.brand{{font-weight:900;margin-bottom:24px;}}
.brand span{{color:var(--accent);}}
</style>
</head>
<body>
<div class="brand">Miryx<span>Check</span> — Academy</div>
<a class="back" href="{blog_base}/">&larr; Tous les articles</a>
<h1>{titre}</h1>
{corps_html}
<a class="cta" href="{app_url}/texto-du-jour">Joue au Texto du Jour &rarr;</a>
</body>
</html>"""


def build_index(published: set[str]) -> str:
    """Régénère la page d'accueil du blog à partir des articles publiés."""
    items = []
    for slug in sorted(published, reverse=True):
        meta_path = f"articles/{slug}.meta.json"
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        items.append(f'<li><a href="/articles/{slug}.html">{meta["titre"]}</a><span>{meta["date"]}</span></li>')
    items_html = "\n".join(items) if items else "<li>Premiers articles bientôt.</li>"
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Miryx Academy — Décoder les messages ambigus</title>
<meta name="description" content="Articles sur les textos ambigus, le ghosting, les ruptures et comment décoder ce que les gens veulent vraiment dire.">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{BLOG_BASE_URL}/">
<style>
:root{{--bg:#0B0B0F;--card:#1A1A24;--text:#fff;--accent:#00E5FF;}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,system-ui,sans-serif;margin:0;padding:32px 20px 60px;max-width:680px;margin-inline:auto;}}
.brand{{font-weight:900;font-size:1.4rem;margin-bottom:24px;}} .brand span{{color:var(--accent);}}
ul{{list-style:none;padding:0;}}
li{{padding:16px 0;border-bottom:1px solid #232330;display:flex;justify-content:space-between;gap:12px;}}
a{{color:var(--text);text-decoration:none;font-weight:600;}}
a:hover{{color:var(--accent);}}
span{{color:#666;font-size:0.85rem;white-space:nowrap;}}
</style></head><body>
<div class="brand">Miryx<span>Check</span> Academy</div>
<ul>
{items_html}
</ul>
</body></html>"""


def request_indexing(url: str) -> None:
    """Notifie Google Indexing API. Ne bloque jamais la publication si ça échoue."""
    if not GCP_SA_JSON:
        print("[INFO] Pas de service account configuré, indexation ignorée")
        return
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        creds_info = json.loads(GCP_SA_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/indexing"]
        )
        session = AuthorizedSession(creds)
        resp = session.post(
            "https://indexing.googleapis.com/v3/urlNotifications:publish",
            json={"url": url, "type": "URL_UPDATED"},
        )
        if resp.status_code == 200:
            print(f"[OK] Indexation demandée pour {url}")
        else:
            print(f"[WARN] Indexing API a répondu {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] Indexation échouée (non bloquant): {e}")


def main():
    published = load_published()
    candidates = fetch_google_trends() + fetch_reddit()
    print(f"[INFO] {len(candidates)} sujets récupérés au total")

    matched = [c for c in candidates if matches_keywords(c["title"] + " " + c["summary"])]
    print(f"[INFO] {len(matched)} sujets correspondent au filtre relationnel")

    created = 0
    for item in matched:
        if created >= MAX_ARTICLES_PER_RUN:
            break
        slug = slugify(item["title"])
        if not slug or slug in published:
            continue

        article = generate_article(item["title"], item["summary"], item["source"])
        if article is None:
            continue

        date_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        url = f"{BLOG_BASE_URL}/articles/{slug}.html"
        html = ARTICLE_TEMPLATE.format(
            titre=article["titre"],
            titre_json=json.dumps(article["titre"], ensure_ascii=False),
            meta_description=article["meta_description"],
            meta_description_json=json.dumps(article["meta_description"], ensure_ascii=False),
            corps_html=article["corps_html"],
            url=url,
            app_url=APP_URL,
            blog_base=BLOG_BASE_URL,
            date_iso=date_iso,
        )
        os.makedirs("articles", exist_ok=True)
        with open(f"articles/{slug}.html", "w", encoding="utf-8") as f:
            f.write(html)
        with open(f"articles/{slug}.meta.json", "w", encoding="utf-8") as f:
            json.dump({"titre": article["titre"], "date": date_iso, "source": item["source"]}, f, ensure_ascii=False)

        published.add(slug)
        request_indexing(url)
        created += 1
        print(f"[OK] Article publié : {slug}")
        time.sleep(2)  # ne pas rafaler l'API Groq/Indexing

    if created > 0:
        save_published(published)
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(build_index(published))
        request_indexing(f"{BLOG_BASE_URL}/")
    else:
        print("[INFO] Aucun nouvel article ce passage — rien à publier, c'est normal, pas une erreur.")


if __name__ == "__main__":
    main()
