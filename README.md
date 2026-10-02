# PDF Intelligence API — RAG hybride multilingue avec conversations et observabilité

API FastAPI pour **importer, gérer et interroger des PDF textuels** avec recherche lexicale FTS5, recherche sémantique multilingue, fusion hybride RRF, conversations isolées par documents, réponses LLM sourcées et diagnostic détaillé des fallbacks.

> **État actuel du projet** : architecture V4.2 en cours de stabilisation. Le champ `version` exposé par FastAPI reste encore `4.0.0` tant que la validation finale n'est pas terminée. Les 49 tests historiques passent avec les dernières modifications. Des tests dédiés à l'observabilité ont également été ajoutés et doivent être exécutés avant de considérer la V4.2 entièrement validée.

---

## 1. Objectif

Le projet fournit une bibliothèque PDF locale capable de :

- importer, lister, remplacer et supprimer des PDF ;
- extraire le texte et le découper en chunks paginés ;
- indexer lexicalement les chunks avec SQLite FTS5 ;
- calculer des embeddings multilingues avec `intfloat/multilingual-e5-small` ;
- combiner recherche lexicale et sémantique avec **Reciprocal Rank Fusion (RRF)** ;
- répondre à partir des seuls passages retrouvés ;
- conserver des conversations et leur historique ;
- isoler chaque conversation à ses propres documents ;
- répondre dans la langue de la question, même si le PDF est dans une autre langue ;
- expliquer pourquoi une réponse LLM a été rejetée ou pourquoi le fournisseur LLM était indisponible ;
- relier chaque réponse API aux logs serveur grâce à un `request_id`.

Le système est conçu comme un **RAG local mono-instance pour corpus modeste**, avec SQLite comme source de vérité. Il n'utilise pas encore de base vectorielle externe.

---

## 2. Architecture actuelle

```text
                         Utilisateur
                              |
                              v
                    FastAPI /api/v1
                              |
                 +------------+------------+
                 |                         |
          Bibliothèque PDF            Conversations
                 |                         |
                 |                  document_ids autorisés
                 |                         |
                 +------------+------------+
                              |
                    Construction requête
                 + contexte de follow-up
                              |
              +---------------+---------------+
              |                               |
              v                               v
        SQLite FTS5                    Embeddings E5
      recherche lexicale             multilingues locaux
              |                               |
              +---------------+---------------+
                              |
                    Weighted RRF fusion
                              |
                        Reranking final
                              |
                     Passages + pages
                              |
                    Evidence / citations
                              |
                     Answerer multilingue
                              |
                 +------------+-------------+
                 |                          |
                 v                          v
           Réponse LLM                Fallback extractif
          avec citations              + diagnostic précis
                 |                          |
                 +------------+-------------+
                              |
                         JSON + logs
                         request_id
```

---

## 3. Modes de retrieval

La variable principale est :

```dotenv
RETRIEVAL_MODE=lexical
```

Trois modes sont acceptés.

### `lexical`

Recherche FTS5/BM25 dans SQLite.

```text
Question
  -> tokenisation
  -> FTS5
  -> reranking Python
  -> top_k
```

Avantages : rapide, local, robuste sur les correspondances exactes.

Limite : moins performant pour les paraphrases et les questions dans une langue différente du document.

### `semantic`

Recherche par similarité d'embeddings multilingues.

```text
Question
  -> embedding E5 query
  -> comparaison aux embeddings des chunks
  -> top_k
```

Modèle actuel :

```text
intfloat/multilingual-e5-small
```

Les préfixes E5 `query:` et `passage:` sont utilisés par le retriever.

### `hybrid`

Mode recommandé pour les tests V4.2.

```text
FTS5 lexical
     +
semantic E5
     |
     v
weighted Reciprocal Rank Fusion
     |
     v
reranking
     |
     v
meilleurs passages
```

Le système **ne mélange pas directement un score BM25 et une cosine similarity**, car leurs échelles ne sont pas comparables. Il fusionne les classements avec RRF.

Les scores RRF retournés dans les sources sont des **scores de classement**, pas des probabilités de vérité ni des pourcentages de confiance.

---

## 4. Recherche multilingue

Le retrieval sémantique permet à une question et à son document source d'être dans des langues différentes.

Exemples attendus :

```text
PDF anglais + question française
-> passage anglais retrouvé
-> réponse française

PDF français + question anglaise
-> passage français retrouvé
-> réponse anglaise

PDF anglais + question russe
-> passage anglais retrouvé
-> réponse russe
```

La langue de la réponse dépend de la **question actuelle**, pas de la langue du PDF.

La détection de langue utilise `lingua-language-detector`.

Le chemin LLM est conçu pour répondre dans la langue détectée de la question. Les fallbacks locaux ont été explicitement travaillés pour le français, l'anglais et le russe ; les autres langues doivent encore être couvertes par des tests de régression avant d'être considérées comme garanties.

---

## 5. Conversations et isolation documentaire

Une conversation possède sa propre liste de documents :

```json
{
  "id": "...",
  "title": "Test AI Agents",
  "document_ids": [
    "5604ee0e-74d2-4a38-81eb-47c482ea68c9"
  ]
}
```

La route recommandée pour le chat est :

```text
POST /api/v1/conversations/{conversation_id}/questions
```

Le backend limite alors le retrieval aux `document_ids` de cette conversation.

Si la requête contient aussi `document_ids`, ceux-ci doivent être un sous-ensemble des documents déjà associés à la conversation. Sinon l'API retourne une erreur `422`.

### Conversation sans document

Une question substantielle dans une conversation vide est refusée :

```text
Associer au moins un document à la conversation.
```

Les salutations ou remerciements restent autorisés.

### Route historique `/questions`

La route :

```text
POST /api/v1/questions
```

est conservée pour compatibilité.

**Attention :** si `document_ids` est omis sur cette route, elle peut interroger toute la bibliothèque. Le frontend conversationnel ne doit donc pas utiliser cette route pour le chat principal.

---

## 6. Follow-ups conversationnels

L'historique aide à résoudre des questions comme :

```text
"Et lequel est recommandé ?"
"Et lesquelles sont les plus importantes ?"
"Donne un exemple."
```

Le texte de la conversation est utilisé uniquement pour **résoudre les références**, jamais comme preuve documentaire.

Les seules preuves factuelles envoyées au LLM sont les chunks récupérés depuis les PDF autorisés.

Le système nettoie les anciennes références `[1]`, `[2]`, etc. et le boilerplate `Source:` avant de réutiliser une réponse précédente comme contexte de retrieval.

---

## 7. Réponse LLM et grounding

Le LLM est appelé en mode OpenAI-compatible.

Exemple :

```dotenv
LLM_MODE=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=VOTRE_CLE_DANS_LE_ENV
LLM_MODEL=votre-modele-compatible
LLM_TIMEOUT_SECONDS=25
```

Ne jamais mettre la clé dans le code, dans Git ou dans le README réel du dépôt.

Le LLM doit :

- utiliser uniquement les extraits fournis comme preuve ;
- répondre dans la langue de la question actuelle ;
- citer les passages au format `[1]`, `[2]`, etc. ;
- éviter de compléter avec ses connaissances générales lorsque les extraits sont insuffisants.

Une réponse sans citation valide est rejetée et le système passe en fallback extractif.

---

## 8. Observabilité LLM

L'API distingue maintenant plusieurs causes de fallback.

### Exemple de succès

```json
{
  "request_id": "0adf9b8e-...",
  "answer": "Un agent IA est ... [1]",
  "response_mode": "llm",
  "fallback_reason": null,
  "generation": {
    "attempted": true,
    "status": "success",
    "provider": "openai_compatible",
    "model": "...",
    "http_status": 200,
    "error_type": null,
    "rejected_answer": null
  },
  "sources": []
}
```

### Exemple : réponse LLM rejetée car sans citation

```json
{
  "request_id": "0adf9b8e-...",
  "response_mode": "extractive",
  "fallback_reason": "missing_citations",
  "generation": {
    "attempted": true,
    "status": "rejected",
    "provider": "openai_compatible",
    "model": "...",
    "http_status": 200,
    "error_type": null,
    "rejected_answer": "Un agent IA est une entité autonome..."
  }
}
```

`rejected_answer` contient le texte réellement produit par le LLM avant rejet.

Cela permet de distinguer :

```text
LLM n'a pas répondu
!=
LLM a répondu mais sa réponse a été rejetée
```

### Causes de fallback actuellement distinguées

| `fallback_reason` | Signification |
| --- | --- |
| `llm_disabled` | Le mode LLM est désactivé |
| `llm_not_configured` | Configuration LLM insuffisante |
| `llm_timeout` | Le fournisseur n'a pas répondu avant le timeout |
| `llm_connection_error` | Connexion impossible au fournisseur |
| `llm_provider_error` | Le fournisseur a retourné une erreur HTTP, par ex. 401/429/500 |
| `llm_invalid_payload` | Réponse HTTP présente mais payload incompatible/invalide |
| `llm_empty_answer` | Le fournisseur a répondu sans texte exploitable |
| `missing_citations` | Le LLM a répondu, mais sans citation valide |
| `invalid_citation_reference` | Le LLM cite une référence inexistante, par ex. `[9]` |
| `insufficient_evidence` | Les preuves disponibles ne permettent pas une réponse fiable |
| `no_document` | Aucun document exploitable n'est associé au contexte concerné |

---

## 9. Logs et `request_id`

Chaque question reçoit un identifiant unique :

```text
request_id=7c0939c1-...
```

Le même ID est présent dans la réponse JSON et dans les logs serveur.

Exemple :

```text
INFO event=question_started request_id=7c09... conversation_id=... retrieval_mode=hybrid language=fr document_count=1
INFO event=retrieval_started request_id=7c09... retrieval_mode=hybrid
INFO event=retrieval_completed request_id=7c09... hit_count=8 top_document=... top_page=1 duration_ms=...
WARNING event=llm_rejected request_id=7c09... reason=missing_citations http_status=200 answer_preview='...'
INFO event=response_completed request_id=7c09... response_mode=extractive fallback_reason=missing_citations
```

Les logs servent à repérer rapidement :

- quelle conversation a reçu la question ;
- combien de documents étaient autorisés ;
- quel mode de retrieval était actif ;
- combien de candidats/hits ont été produits ;
- quel document/page est arrivé en tête ;
- si le LLM a été appelé ;
- pourquoi il a échoué ou été rejeté ;
- quel mode final a été retourné.

### Sécurité des logs

Les logs ne doivent jamais contenir :

- clé API ;
- token ;
- headers d'authentification ;
- prompt système complet ;
- contenu intégral des PDF.

Pour une réponse LLM rejetée, les logs ne gardent qu'un `answer_preview` tronqué. Le texte complet reste disponible dans `generation.rejected_answer` dans la réponse API de diagnostic.

---

## 10. Stockage SQLite

La base par défaut est :

```text
data/metadata.sqlite3
```

Tables principales :

```text
documents
chunks
conversations
conversation_documents
messages
chunks_fts
chunk_embeddings
```

### `chunk_embeddings`

Les embeddings sémantiques sont stockés séparément du champ historique `chunks.embedding_json`.

Chaque entrée associe :

```text
chunk_id
embedding_model
embedding_json
```

Cette séparation évite de mélanger des vecteurs provenant de modèles différents.

Le cache peut être reconstruit à partir des chunks textuels ; il est donc considéré comme une donnée dérivée.

Le schéma principal SQLite reste actuellement en `PRAGMA user_version = 4` afin de préserver la compatibilité des migrations existantes.

---

## 11. Backfill des embeddings

Les documents importés historiquement en mode lexical peuvent ne pas avoir d'embeddings E5.

Lors de la première question `semantic` ou `hybrid` :

```text
chunks sans embedding courant
        |
        v
calcul E5 local
        |
        v
save_embeddings(...)
        |
        v
chunk_embeddings
```

Le premier appel peut donc être plus lent.

Les appels suivants réutilisent le cache SQLite.

Le modèle peut aussi être téléchargé depuis Hugging Face lors de son premier usage s'il n'est pas déjà présent en cache.

---

## 12. Installation locale — Windows / PowerShell

Prérequis recommandés : Python 3.11+.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-semantic.txt
python -m pip install -r requirements-dev.txt
```

Si certains fichiers de requirements incluent déjà `-r requirements.txt`, `pip` ignorera les dépendances déjà satisfaites.

Créer ensuite `.env` à partir de ton exemple local ou configurer manuellement les variables nécessaires.

---

## 13. Exemple de `.env` hybride

```dotenv
# API
APP_API_KEY=

# Storage / PDF
STORAGE_DIR=./data
MAX_PDF_BYTES=31457280
MAX_PAGES=1000
CHUNK_SIZE=950
CHUNK_OVERLAP=150

# Retrieval
RETRIEVAL_MODE=hybrid
EMBEDDING_MODEL=intfloat/multilingual-e5-small
EMBEDDING_BATCH_SIZE=32
SEMANTIC_THRESHOLD=0.30
HYBRID_RRF_K=60
HYBRID_LEXICAL_WEIGHT=1.0
HYBRID_SEMANTIC_WEIGHT=1.0
HYBRID_LEXICAL_CANDIDATES=80
HYBRID_SEMANTIC_CANDIDATES=80

# LLM
LLM_MODE=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=REMPLACER_PAR_VOTRE_CLE_LOCALE
LLM_MODEL=votre-modele
LLM_TIMEOUT_SECONDS=25
```

Ne jamais committer un `.env` contenant une vraie clé.

---

## 14. Démarrage

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger :

```text
http://127.0.0.1:8000/docs
```

Redoc :

```text
http://127.0.0.1:8000/redoc
```

Santé :

```text
GET /api/v1/health
```

Exemple attendu en mode hybride :

```json
{
  "status": "ok",
  "retrieval_mode": "hybrid",
  "llm_mode": "openai_compatible",
  "index_mode": "hybrid_fts5_multilingual_semantic_rrf",
  "max_pdf_bytes": 31457280,
  "max_pages": 1000,
  "embedding_model": "intfloat/multilingual-e5-small"
}
```

Si `Settings.from_env()` affiche `hybrid` mais `/health` affiche encore `lexical`, vérifier qu'un ancien processus Uvicorn n'occupe pas déjà le port utilisé.

---

## 15. Endpoints principaux

| Méthode | URL | Rôle |
| --- | --- | --- |
| GET | `/api/v1/health` | Santé et mode actif |
| POST | `/api/v1/documents` | Importer un PDF |
| GET | `/api/v1/documents` | Lister les PDF |
| GET | `/api/v1/documents/{id}` | Métadonnées d'un PDF |
| PUT | `/api/v1/documents/{id}` | Remplacer un PDF en conservant son ID |
| DELETE | `/api/v1/documents/{id}` | Supprimer PDF + chunks + relations |
| POST | `/api/v1/questions` | Route globale/historique de question |
| POST | `/api/v1/conversations` | Créer une conversation |
| GET | `/api/v1/conversations` | Lister les conversations |
| GET | `/api/v1/conversations/{id}` | Lire une conversation |
| PATCH | `/api/v1/conversations/{id}` | Renommer une conversation |
| PUT | `/api/v1/conversations/{id}/documents` | Définir les PDF autorisés dans la conversation |
| GET | `/api/v1/conversations/{id}/messages` | Lire l'historique |
| POST | `/api/v1/conversations/{id}/questions` | Poser une question dans le scope de la conversation |
| DELETE | `/api/v1/conversations/{id}` | Supprimer une conversation |

---

## 16. Tester avec Swagger

### A. Importer un document

```text
POST /api/v1/documents
```

Envoyer un PDF texte.

Le backend refuse notamment :

- nom non PDF ;
- fichier trop volumineux ;
- PDF invalide ;
- scan sans texte exploitable ;
- nombre de pages supérieur à la limite.

### B. Créer une conversation isolée

```text
POST /api/v1/conversations
```

```json
{
  "title": "Test AI Agents Hybrid",
  "document_ids": [
    "<document_id>"
  ]
}
```

### C. Poser une question cross-language

```text
POST /api/v1/conversations/{conversation_id}/questions
```

```json
{
  "question": "C'est quoi un agent IA ?",
  "top_k": 8,
  "answer_style": "synthese",
  "include_excerpts": true
}
```

Si le PDF est anglais, le système peut retrouver :

```text
An AI agent is an autonomous entity...
```

et répondre en français avec citation.

### D. Tester le russe

```json
{
  "question": "Что такое ИИ-агент?",
  "top_k": 8,
  "answer_style": "synthese",
  "include_excerpts": true
}
```

Pour un test d'isolation, vérifier auparavant que la conversation ne contient que le PDF attendu.

---

## 17. Contrat d'une réponse

Structure simplifiée :

```json
{
  "answer": "...",
  "response_mode": "llm",
  "request_id": "...",
  "fallback_reason": null,
  "generation": {
    "attempted": true,
    "status": "success",
    "provider": "openai_compatible",
    "model": "...",
    "http_status": 200,
    "error_type": null,
    "rejected_answer": null
  },
  "sources": [
    {
      "reference": 1,
      "document_id": "...",
      "filename": "document.pdf",
      "page": 1,
      "page_end": 2,
      "score": 0.016393,
      "excerpt": "..."
    }
  ],
  "warning": null
}
```

### `response_mode`

Valeurs actuellement utilisées :

```text
llm
extractive
no_evidence
```

Des réponses sociales peuvent aussi suivre un chemin sans retrieval documentaire.

---

## 18. Diagnostic rapide d'un fallback

Si l'API affiche des extraits au lieu d'une réponse rédigée :

1. lire `response_mode` ;
2. lire `fallback_reason` ;
3. regarder `generation.status` ;
4. si `status = rejected`, lire `generation.rejected_answer` ;
5. copier `request_id` ;
6. retrouver ce même `request_id` dans le terminal Uvicorn ;
7. vérifier `retrieval_completed`, `top_document`, `top_page` et `llm_*`.

Exemple :

```text
response_mode=extractive
fallback_reason=missing_citations
generation.status=rejected
```

Cela signifie :

```text
le retrieval a fonctionné
+
le LLM a répondu
+
la réponse a été rejetée par le validateur de citations
```

Ce n'est pas équivalent à une panne du fournisseur.

---

## 19. Tests

Baseline actuellement validée sur le dépôt :

```powershell
python -m py_compile app\config.py
python -m py_compile app\retrieval.py
python -m py_compile app\store.py
python -m py_compile app\main.py
python -m py_compile app\answering.py
python -m py_compile app\schemas.py
python -m pytest -q
```

Résultat historique observé après les dernières modifications principales :

```text
49 passed, 1 warning
```

Le warning actuel vient de l'intégration FastAPI/Starlette TestClient avec `httpx` et n'est pas lié au retrieval ou à l'observabilité.

Un fichier supplémentaire de tests d'observabilité est prévu/ajouté :

```text
tests/test_observability.py
```

Il doit couvrir notamment :

- succès LLM avec citation ;
- réponse sans citation ;
- citation inexistante ;
- timeout ;
- HTTP 429 ;
- erreur de connexion ;
- payload fournisseur invalide ;
- réponse vide ;
- présence du `request_id` dans la réponse et les logs.

**Ne considérer la nouvelle suite comme entièrement validée qu'après exécution locale réussie de ces tests.**

---

## 20. Limites actuelles

- OCR non inclus : un PDF scanné sans texte exploitable n'est pas pris en charge.
- Extraction des tableaux, colonnes, graphiques et formules dépend de la qualité du texte PDF.
- SQLite + comparaison locale des embeddings convient à un corpus modeste, pas à des millions de chunks.
- Le semantic retrieval peut être coûteux si beaucoup de chunks doivent être comparés localement.
- Le premier appel hybride peut être lent à cause du téléchargement du modèle ou du backfill d'embeddings.
- RRF ordonne des résultats ; son score n'est pas une probabilité de pertinence.
- Le LLM peut produire une formulation incorrecte malgré un bon retrieval ; les citations restent indispensables.
- La présence d'une citation correcte ne garantit pas automatiquement que chaque mot de la réponse est fidèle à la source.
- Les documents peuvent contenir des instructions malveillantes ; elles doivent rester des données et jamais être considérées comme des commandes système.
- Le projet est actuellement mono-instance/local ; une exposition publique nécessiterait une authentification et autorisation plus fortes, TLS, quotas, monitoring, rotation de secrets et contrôles multi-utilisateurs.

---

## 21. Sécurité

- Ne jamais committer `.env` avec des secrets.
- Ne jamais logger les clés API.
- Utiliser des requêtes SQLite paramétrées.
- Valider les uploads et leurs tailles.
- Restreindre les documents accessibles par conversation.
- Garder l'historique conversationnel séparé des preuves PDF.
- Sauvegarder le dossier `data/` avant toute migration destructive.
- Les réponses rejetées complètes sont utiles en développement ; pour un environnement multi-utilisateur ou contenant des documents sensibles, évaluer leur exposition avant de les afficher au frontend.

---

## 22. Organisation du dépôt

```text
app/
  config.py          # Configuration .env et validation
  main.py            # API FastAPI, orchestration retrieval, conversations, logs
  pdf_processing.py  # Validation/extraction PDF et chunking
  store.py           # SQLite, FTS5, conversations, cache embeddings
  retrieval.py       # BM25, E5 multilingue, RRF, reranking
  answering.py       # LLM grounded, multilingue, citations, fallback, observabilité
  schemas.py         # Contrats Pydantic

static/
  index.html         # Frontend actuel

examples/
  ...

scripts/
  ...

tests/
  ...
  test_observability.py

data/
  metadata.sqlite3
  files/
```

---

## 23. Workflow frontend recommandé

```text
Nouvelle conversation
        |
        v
POST /conversations
        |
        v
conversation_id conservé
        |
        v
Upload / sélection PDF
        |
        v
PUT /conversations/{id}/documents
        |
        v
GET /conversations/{id}
        |
        v
Question utilisateur
        |
        v
POST /conversations/{id}/questions
        |
        v
Réponse + sources + request_id + diagnostic LLM
```

À éviter :

```text
conversation sans document
        |
        v
POST /api/v1/questions
        |
        v
recherche automatique dans toute la bibliothèque
```

---

## 24. Étapes restantes avant de figer la V4.2

1. Exécuter et valider les tests dédiés à l'observabilité.
2. Vérifier manuellement dans Swagger les cas : succès LLM, `missing_citations`, HTTP 429/timeout simulé si possible.
3. Vérifier que les événements `question_started`, `retrieval_completed`, `llm_*` et `response_completed` sont visibles dans le terminal avec le même `request_id`.
4. Corriger le frontend pour qu'il utilise systématiquement les routes conversationnelles et affiche `fallback_reason`, `generation.status` et `rejected_answer`.
5. Refaire les tests multilingues FR/EN/RU avec conversations isolées.
6. Passer la version publique FastAPI de `4.0.0` à `4.2.0` seulement après validation finale.

---

## 25. Principe de conception

Le projet suit une règle simple :

```text
une réponse n'est pas seulement "bonne" ou "mauvaise"
```

Le système doit permettre de savoir :

```text
quels documents ont été autorisés
-> quels passages ont été retrouvés
-> quel passage a été classé premier
-> si le LLM a été appelé
-> s'il a répondu
-> si sa réponse a été rejetée
-> pourquoi elle a été rejetée
-> quelle était cette réponse
-> quelle réponse finale a été montrée à l'utilisateur
```

C'est cette traçabilité qui rend le RAG compréhensible, testable et améliorable.
