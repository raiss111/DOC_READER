# Matrice de test manuel / test de résistance

Lancer `python -m pytest -q` **avant** les tests manuels ci-dessous ; démarrer le serveur sur localhost, tester via `/docs`. Ne pas utiliser de vrais documents confidentiels.

| ID | Manipulation | Résultat attendu |
| --- | --- | --- |
| T01 | Importer `examples/guide_procedures.pdf` | HTTP 201, 2 pages, `chunk_count > 0`, ID et hash présents |
| T02 | Demander le délai de déclaration | source page 1, `15 jours ouvrables` dans l'extrait |
| T03 | Demander les documents à joindre | passage page 2 de `guide_procedures.pdf` |
| T04 | Ajouter `conditions_transport.pdf` et demander la garantie | source du second PDF, `30 jours` |
| T05 | `document_ids` limité au premier PDF, question sur la garantie | aucune preuve de la deuxième pièce ; éventuellement `no_evidence` |
| T06 | Poser une question sans aucun mot du corpus, ex. `Quelle couleur ont les girafes ?` | `no_evidence`, aucune source |
| T07 | Importer `notes.txt` déguisé en PDF | HTTP 422 |
| T08 | Importer un PDF scanné sans couche texte | HTTP 422 avec explication OCR |
| T09 | Importer un PDF chiffré | HTTP 422 |
| T10 | Importer un PDF dépassant `MAX_PDF_BYTES` | HTTP 413 |
| T11 | Importer un PDF dépassant `MAX_PAGES` | HTTP 422 |
| T12 | Remplacer un PDF par un autre valide | ID inchangé, version +1, ancien texte non interrogeable |
| T13 | Remplacer un PDF par un faux PDF | 422, ancienne version toujours utilisable |
| T14 | Supprimer un PDF | 204, 404 sur consultation, ses passages absents des questions |
| T15 | Redémarrer l'API | documents restants et réponses toujours disponibles |
| T16 | Activer `APP_API_KEY`, tester sans clé / mauvaise clé / bonne clé | 401 / 401 / accès normal |
| T17 | Utiliser `top_k=99` ou une question vide | HTTP 422 |
| T18 | Mode LLM : couper le réseau ou fournir un modèle invalide | réponse extractive de secours + warning, sans faux succès LLM |
| T19 | Exécuter `python scripts/audit_storage.py` serveur arrêté | fichiers orphelins ou manquants détectés sans effacement |
| T20 | Documents très longs et PDF à colonnes | noter exactitude des pages et passages, documenter les échecs réels |

**Campagne sémantique (optionnelle)** : comparer pour dix questions les passages BM25 et sémantiques, notamment des paraphrases sans mot commun ; évaluer manuellement si la page citée apporte réellement la réponse. Ne pas prendre un score de similarité pour une vérité.

**Ne sont pas vérifiés automatiquement :** disponibilité réelle d'un fournisseur LLM, installation/téléchargement du modèle Sentence Transformers sur la machine de l'utilisateur, débit en forte charge, résistance à toutes les injections de prompt et OCR.
