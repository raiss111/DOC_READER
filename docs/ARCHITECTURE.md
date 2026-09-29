# Architecture : décisions de référence

## Frontières

- **Transport HTTP** (`main.py`) : validation des paramètres, upload, codes d'erreur, clé API optionnelle, découplage du contrat public (`schemas.py`) du stockage.
- **Extraction** (`pdf_processing.py`) : fichier signé PDF, pas de mot de passe, au plus 200 pages, texte trié par page, fenêtres chevauchantes, ordinal conservé.
- **Source de vérité** (`store.py`) : fichier binaire avec nom opaque UUID et métadonnées/segments dans SQLite. `documents.id` stable à travers un remplacement ; `version` incrémentée.
- **Recherche** (`retrieval.py`) : BM25 sans apprentissage en mode hors ligne ; option encodeur multilingue avec vecteurs normalisés et similarité cosinus.
- **Réponse** (`answering.py`) : passages avec référence `[n]`, fichier et page ; LLM optionnel qui n'obtient que la question et les passages sélectionnés ; repli en extraits en cas d'échec.

## Flux de création

1. Lire au plus MAX_PDF_BYTES+1 octets et rejeter l'excédent.
2. Vérifier la signature et l'ouvrabilité par PyMuPDF, refuser document chiffré, vide ou dépassant MAX_PAGES.
3. Extraire pages et chunks ; calculer les embeddings si cette option est active.
4. Écrire un fichier temporaire sur le même volume, `fsync` et remplacer atomiquement son nom par un nom unique.
5. Insérer en transaction SQLite le document et ses chunks. Si la transaction échoue, effacer le nouveau fichier.

## Flux de remplacement

Le nouveau PDF est entièrement préparé **avant** la mutation. Écrire le nouveau binaire sous nom distinct ; une transaction `BEGIN IMMEDIATE` remplace les métadonnées et l'index en conservant l'ID. Après le commit, effacer l'ancien binaire. Si la validation ou la transaction échoue, conserver l'ancienne version. Une panne au moment exact du nettoyage peut laisser un binaire orphelin : l'audit de stockage le détecte.

## Flux de suppression

Une transaction SQLite supprime document et chunks (clé étrangère `ON DELETE CASCADE`), puis le binaire référencé est effacé. Même limite de nettoyage lors d'une panne système. Pour un vrai service contenant des données confidentielles, remplacer ce protocole local par une politique de rétention/destruction auditable.

## Choix et évolutions

| Décision v1 | Raison | Prochaine évolution possible |
| --- | --- | --- |
| Monolithe FastAPI | un seul développeur, peu de complexité | découper si contraintes de charge indépendantes |
| SQLite et fichiers locaux | inspection simple, conservation après redémarrage | PostgreSQL et stockage objet si multi-instance |
| BM25 par défaut | aucune clé, aucun téléchargement ML | embeddings et recherche hybride |
| Vecteurs JSON dans SQLite | petite volumétrie, moins d'infrastructure | moteur vectoriel indexé pour un grand corpus |
| Traitement synchrone | succès = document indexé et prêt | tâches en arrière-plan + statut + reprise |
| LLM OpenAI-compatible optionnel | éviter le verrouillage sur un fournisseur | évaluer plusieurs modèles sur un benchmark fixe |

## Critères d'acceptation v1

- Import produit ID, SHA-256, page_count et chunks.
- `GET /documents` fonctionne après arrêt/redémarrage.
- Question retourne des sources associées à un PDF et une page.
- Scope par document respecté.
- Aucune correspondance lexicale -> `no_evidence`, et ne pas inventer une réponse.
- Remplacement garde l'ID, augmente `version`, retire l'ancien index et l'ancien PDF.
- Remplacement invalide ne touche pas à l'ancien contenu.
- Suppression retire l'entrée, les chunks et le binaire.
- Données d'entrée invalides et accès avec clé incorrecte donnent les bons codes HTTP.
