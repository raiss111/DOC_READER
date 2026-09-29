# PDF Intelligence API — MVP de référence (v1.0)

API FastAPI pour **importer, lister, remplacer, supprimer et interroger des PDF contenant du texte**.

> Projet pédagogique de référence pour un deuxième passage où Raïssa recodera elle-même les composants, guidée par `docs/PLAN_RECONSTRUCTION.md`. Aucune clé payante n'est nécessaire pour démarrer.

## 1. Deux modes distincts (important)

Au démarrage, **tout fonctionne localement** : `RETRIEVAL_MODE=lexical` (recherche BM25, sensible aux mots-clés mais robuste aux accents) et `LLM_MODE=extractive` (présentation de passages sourcés). Ce mode NE PRÉTEND PAS reformuler intelligemment la réponse à la question : il affiche les preuves trouvées.

Pour un vrai **RAG sémantique génératif**, installer l'option ML (`requirements-semantic.txt`), choisir `RETRIEVAL_MODE=semantic`, configurer `LLM_MODE=openai_compatible` et l'URL/la clé/le modèle d'un fournisseur compatible OpenAI (Groq, service OpenAI compatible ou serveur local). Le modèle d'embeddings est multilingue. Le modèle est téléchargé au premier usage si absent du cache (internet requis lors de ce téléchargement). Le LLM externe reçoit les passages récupérés : ne pas l'activer avec des documents confidentiels sans autorisation.

### Architecture

```
                         FastAPI  /api/v1
                        /              \
                Upload / CRUD        /questions
                    |                     |
            Validation PDF            Recherche BM25
                    |                  ou sémantique
               PyMuPDF                    |
                    |               Passages + pages
               Pages + chunks              |
                    |                Réponse extraite
               Embeddings (option)    ou LLM (option)
                    |                     |
        PDF dans data/files/       Citations + passages
        Métadonnées, chunks et
        vecteurs dans SQLite
```

L'index sémantique repose sur SQLite + similarité cosinus, et non sur ChromaDB : adapté à un **MVP mono-instance avec corpus modeste**. Il évite une base supplémentaire mais n'est pas dimensionné pour des millions de segments. Une migration vers un moteur vectoriel sera un exercice futur.

## 2. Installation locale (Windows / PowerShell)

Prérequis : Python 3.11+ et un terminal ouvert **dans ce dossier**, qui contient `requirements.txt`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Si ta version est Python 3.12/3.13, remplacer `py -3.11` par `py -3` si nécessaire. Si PowerShell interdit l'activation, utilise directement `.\.venv\Scripts\python.exe -m pip ...` puis `.\.venv\Scripts\python.exe -m uvicorn ...`. La commande `--reload` est réservée au développement.

**Linux / macOS :**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Accès : http://127.0.0.1:8000/docs (Swagger interactif), http://127.0.0.1:8000/redoc et http://127.0.0.1:8000/api/v1/health.

## 3. Tester en 5 minutes avec Swagger

1. Ouvrir `/docs` puis `POST /api/v1/documents` → **Try it out** → importer `examples/guide_procedures.pdf` → **Execute**. Copier l'`id` renvoyé.
2. `GET /api/v1/documents` pour vérifier que le fichier est présent et prêt à être interrogé (l'import est **synchrone**).
3. `POST /api/v1/questions` → Try it out, envoie :

```json
{
  "question": "Quel est le delai de declaration des marchandises ?",
  "top_k": 3
}
```

Tu dois retrouver le passage sur les **15 jours ouvrables** avec `filename`, `page` et `reference`. La réponse utilise par défaut des extraits, non un LLM.

4. Importe `examples/conditions_transport.pdf`. Pose une question sur la **garantie** puis limite la recherche à un document avec `document_ids: ["<id-du-document>"]`.
5. `PUT /api/v1/documents/{document_id}` pour remplacer un fichier, puis `DELETE` pour supprimer définitivement le PDF enregistré et ses chunks. **Ne pas utiliser un fichier important pour cet exercice.**

Si `APP_API_KEY` est renseigné dans `.env`, cliquer sur le bouton **Authorize** de Swagger et renseigner cette même clé (`X-API-Key`) avant les appels protégés. La santé reste publique.

## 4. Contrats HTTP

| Méthode | URL | Succès | Rôle |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | 200 | Santé de l'API |
| POST | `/api/v1/documents` | 201 | Multipart `file`: importer un PDF |
| GET | `/api/v1/documents?limit=20&offset=0` | 200 | Liste paginée |
| GET | `/api/v1/documents/{id}` | 200 | Métadonnées |
| PUT | `/api/v1/documents/{id}` | 200 | Remplacer tout le contenu + index, ID conservé, version augmentée |
| DELETE | `/api/v1/documents/{id}` | 204 | Supprimer binaire + index + métadonnées |
| POST | `/api/v1/questions` | 200 | Question, scope PDF et sources |

Requête de question :

```json
{
  "question": "Quels documents faut-il fournir ?",
  "document_ids": null,
  "top_k": 4
}
```

`document_ids: null` interroge tous les fichiers, `[]` aucun, et une liste non vide interroge uniquement les IDs existants. `top_k` va de 1 à 8. La réponse contient `answer`, `response_mode` (`no_evidence`, `extractive` ou `llm`), `sources` (nom, page, extrait, score et ID), et `warning`. Le score BM25 **n'est pas une probabilité de véracité**.

Erreurs usuelles : `401` clé API incorrecte (si activée) ; `404` document absent ; `413` PDF trop volumineux ; `422` fichier invalide, chiffré, scanné sans texte, trop de pages, paramètres invalides ; `503` mode sémantique demandé sans sa dépendance.

## 5. Options IA

### Recherche sémantique (ML local)

```powershell
python -m pip install -r requirements-semantic.txt
```

Modifier `.env` :

```dotenv
RETRIEVAL_MODE=semantic
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
SEMANTIC_THRESHOLD=0.38
```

Redémarrer. Les nouveaux PDF reçoivent des embeddings à l'import. Les anciens PDF créés en mode lexical restent interrogeables : leur calcul sémantique sera fait à la volée (moins performant). Le seuil sémantique est heuristique : l'ajuster sur les cas de test du corpus, sans présenter sa valeur comme une garantie de pertinence.

### Réponse reformulée par LLM externe ou local

Modifier `.env`, utiliser **ton propre modèle actuellement disponible chez le fournisseur** :

```dotenv
LLM_MODE=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=COLLER_LA_CLE_DANS_LE_ENV_ET_NON_DANS_LE_CODE
LLM_MODEL=llama-3.3-70b-versatile
```

**Note :** le nom ci-dessus est un exemple configurable, pas une promesse de disponibilité permanente. On peut aussi employer une API locale compatible OpenAI en modifiant l'URL et le modèle. Si le fournisseur échoue ou si sa sortie ne contient aucune citation valide, l'API **revient aux extraits** (`response_mode: extractive` et `warning`). Une citation correcte au format `[1]` est contrôlée, mais le programme ne peut **pas certifier la vérité** d'une formulation produite par le LLM : relire les sources pour les cas sensibles.

Le mode `extractive` et le mode `lexical` sont indépendants : on peut notamment garder BM25 et activer seulement le LLM.

## 6. Tests

```powershell
python -m pytest -q
python -m compileall -q app
```

Les tests utilisent des PDF synthétiques créés en mémoire, une base temporaire et une imitation contrôlée de l'API LLM : **aucun secret et aucun réseau externe nécessaires**. Le plan de tests manuels figure dans `docs/TEST_MATRIX.md`. Un smoke test en véritable HTTP peut être réalisé avec `/docs` ou `scripts/http_smoke.py` (serveur lancé dans un second terminal).

## 7. Limitations et sécurité

- **OCR non inclus**. Un scan sans texte est rejeté clairement ; PDF partiellement scanné : seules les parties textuelles sont exploitées.
- Tableaux complexes, colonnes, formules, graphiques et figures : extraction texte parfois incomplète ou désordonnée. Ne pas supposer que toutes les informations d'un PDF ont été extraites.
- Limites locales par défaut : **10 Mio/PDF** et **200 pages/PDF**. Le framework multipart peut temporairement utiliser mémoire/disque avant la validation applicative ; configurer aussi les limites du proxy pour un déploiement public.
- Les résultats BM25 dépendent des mots partagés ; le mode sémantique améliore certaines paraphrases mais peut renvoyer un passage approximatif. Pas de calibration scientifique de la pertinence dans cette version.
- Par défaut `APP_API_KEY` est vide afin de tester **uniquement sur `127.0.0.1`**. Ne jamais exposer ce serveur publiquement dans cette configuration. Pour une utilisation multi-utilisateur/public : authentification forte, autorisation document par utilisateur, TLS, quotas, surveillance, nettoyage des fichiers orphelins, gestion des traitements longs et sauvegardes sont indispensables.
- Supprimer ou remplacer retire l'ancien index de SQLite et tente d'effacer le binaire. Une interruption système exceptionnelle peut laisser un fichier binaire non référencé ; `scripts/audit_storage.py` les signale **sans rien supprimer**. Sauvegarder l'intégralité du dossier `data/` serveur arrêté (y compris la base SQLite) avant les tests destructifs.
- Les instructions contenues dans un PDF ne doivent jamais être considérées comme des commandes. Le prompt du LLM le rappelle, sans garantir une défense absolue face au prompt injection.
- Les vecteurs éventuels sont stockés en JSON dans SQLite et comparés linéairement : **prototype local**, pas moteur de recherche à grande échelle.

## 8. Organisation du dépôt

```
app/
  config.py          # Variables d'environnement et validation
  main.py            # Routes HTTP et cycle de vie des fichiers
  pdf_processing.py  # Validation PDF et chunks avec numéro de page
  store.py           # Transactions SQLite
  retrieval.py       # BM25 + embeddings multilingues optionnels
  answering.py       # Extraits / LLM OpenAI-compatible + citations
  schemas.py         # Contrats Pydantic
examples/             # Deux PDF de démonstration + questions
scripts/              # Audit de stockage et smoke HTTP
tests/                # Tests d'intégration et unitaires
docs/                 # Architecture, matrice de tests, reconstruction
```

**Documentation de développement :** FastAPI https://fastapi.tiangolo.com/ ; PyMuPDF https://pymupdf.readthedocs.io/ ; Sentence Transformers https://sbert.net/ ; Python sqlite3 https://docs.python.org/3/library/sqlite3.html ; pytest https://docs.pytest.org/.
