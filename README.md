# miryx-blog — Trend-Jacking FR / EN / AR (v4, 24/09/2026)

Publie des articles sur `blog.miryxcheck.com` dans les 3 langues de Miryx. Google Trends + Google Actualités (éditions locales) servent **uniquement à détecter un thème** (ghosting, rupture, jalousie…). Le modèle ne voit jamais un titre d'actualité : aucun nom de personne ne peut entrer dans un article.

## Arborescence exacte du dépôt (pas de dossier en double)
```
.github/workflows/trendjacking.yml
scripts/trendjacking.py
requirements.txt
README.md
CNAME                (blog.miryxcheck.com)
articles/{fr,en,ar}/ (généré)
index.html, en/index.html, ar/index.html, sitemap.xml, robots.txt   (générés)
```
`published.json` n'est plus utilisé : tu peux le supprimer. **Supprime aussi les 6 anciens articles** (`articles/*.html` et `articles/*.meta.json` à la racine de `articles/`, ils venaient de Reddit).

## Secrets (Settings → Secrets and variables → Actions **de ce dépôt**)
- `GROQ_API_KEY` — obligatoire.
- `GCP_SERVICE_ACCOUNT_JSON` — optionnel (Indexing API, best-effort).
- `DAILY_CAP` — optionnel (défaut 3 articles/jour/langue).

## Format d'un article
Accroche vécue → encadré « Lecture Miryx » (message fictif, signal, 2 hypothèses, version plus claire) → 3 réflexes → note « le score mesure l'intensité ». Le modèle ne renvoie que du texte ; la page est assemblée par le code.
Le **score affiché vient de `EXEMPLES`** (fourchettes de la table de calibration de l'app), jamais du modèle. Si le prompt de l'app change, mettre `EXEMPLES` à jour.
3 CTA : **Challenge sur ce message** (`/d/{id}?src=blog-defi`, défis créés dans la table `challenges`, `created_by='miryx-blog'`), analyse gratuite (`?src=blog-app`), Texto du Jour (`?src=blog-jeu`).

## Premier lancement
Actions → « Miryx Trend-Jacking » → **Run workflow**, puis lire les logs :
- `[INFO] fr/en/ar: N actualités lues, thèmes détectés: …` → les sources répondent ;
- `[OK] Article publié (xx)` → ça marche ;
- « Aucun nouvel article » → normal (pas de thème d'actualité, cooldown, ou garde-fou) ;
- **rouge** = aucune source joignable ou `GROQ_API_KEY` absent.
Puis Search Console → Sitemaps → `https://blog.miryxcheck.com/sitemap.xml`.

## Mesurer le Challenge du blog
```sql
select lang, id, message, views, completions from challenges where created_by='miryx-blog' order by views desc;
```

## Garde-fous (dans le code)
- Le modèle ne voit aucune actualité ; sujets sensibles (santé grave, mort, violences, mineurs) écartés dans les 3 langues.
- Aucun HTML du modèle publié ; tout est échappé. Rejet si le modèle écrit un pourcentage.
- Rejet si source citée, fausse étude/« buzz », « chaque matin », titre trop proche d'un titre récent, nom propre (FR/EN).
- Modèle `openai/gpt-oss-120b`, mêmes réglages que l'app.
