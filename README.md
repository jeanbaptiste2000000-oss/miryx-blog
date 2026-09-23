# miryx-blog — Trend-Jacking automatisé

Ce dépôt génère et publie automatiquement des articles sur `blog.miryxcheck.com`,
à partir de sujets qui trendent (Google Trends FR + Reddit r/relationships,
r/dating_advice), filtrés sur le thème relationnel/textos ambigus, écrits par
Groq avec l'angle Miryx, puis indexés de force auprès de Google.

## Avant le premier lancement — 2 secrets à ajouter

Dans **Settings → Secrets and variables → Actions** de CE dépôt (`miryx-blog`,
pas celui de l'app principale — les secrets ne se partagent jamais entre
dépôts) :

1. **`GROQ_API_KEY`** — la même clé Groq déjà utilisée sur miryxcheck.com.
2. **`GCP_SERVICE_ACCOUNT_JSON`** — colle le **contenu complet** du fichier
   JSON téléchargé pour le compte de service `miryx-indexing@miryx-trendjacking.iam.gserviceaccount.com`
   (tout le fichier, tel quel, comme valeur du secret).

## Vérifier que ça tourne

Une fois les 2 secrets ajoutés : onglet **Actions** de ce dépôt → workflow
"Miryx Trend-Jacking" → bouton **Run workflow** pour le déclencher tout de
suite sans attendre les 6h. Un vert = un article a peut-être été publié (ou
"rien de nouveau" si aucun sujet ne matchait le filtre à ce moment précis —
c'est normal, pas une erreur). Un rouge = ouvre le run pour voir le message
exact, colle-le à Claude.

## Ce que ça ne fait jamais (rappel des règles produit Miryx)

- Jamais de vrai message privé d'un tiers dans un article, même en évoquant
  une actualité people — uniquement le TYPE de situation.
- Jamais plus de 2 articles par passage.
- Jamais de republication d'un sujet déjà traité (suivi dans `published.json`).
