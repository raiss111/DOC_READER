# Deuxième passage : c'est Raïssa qui construit

Règle : ne pas recopier le code de référence ligne par ligne. Partir du besoin, écrire une hypothèse, prévoir un test, implémenter, puis confronter à cette version seulement après avoir essayé. L'assistant donne des indices, fait la revue, et corrige **après** tes propositions. Conserver un journal des décisions et des erreurs.

| Étape | Ton livrable | Démonstration avant passage |
| --- | --- | --- |
| 0. Reformuler le besoin | fonctionnalités, exclus et 5 critères d'acceptation | expliquer le parcours ajout → question → réponse |
| 1. Squelette FastAPI | `/health`, Swagger, schémas Pydantic | réponse HTTP 200 et validation 422 |
| 2. Extraction PDF | fonction `(bytes) → pages + texte` | document valide, faux PDF, scan et chiffré |
| 3. Chunking | fonction testée, pages préservées | comprendre la fenêtre et son chevauchement |
| 4. Persistance | tables documents/chunks, fichiers nommés UUID | redémarrage sans perte des documents |
| 5. CRUD | POST/GET/PUT/DELETE | remplacement valide et invalide, suppression totale |
| 6. Recherche | BM25 local | question pertinente et question sans réponse |
| 7. RAG | embeddings et LLM (options) | sources précises et gestion des erreurs du fournisseur |
| 8. Qualité | pytest et tests d'intégration | tous les tests critiques réussissent |
| 9. Livraison | README, .env.example, scripts de test | installation par quelqu'un qui n'a pas codé le projet |

**Questions que tu devras savoir expliquer :** Qu'est-ce qu'un chunk ? Pourquoi garder le numéro de page ? Pourquoi ne pas entraîner le modèle sur chaque PDF ? Quelle différence entre moteur de recherche et LLM ? Pourquoi un remplacement ne doit-il pas supprimer l'ancien fichier avant d'avoir validé le nouveau ? Où vont les secrets ? Comment tester le fait qu'un modèle invente une citation ?

**Méthode pour nos séances :** (1) tu annonces le prochain petit objectif, (2) tu proposes architecture/code/test, (3) je fais revue et questions, (4) tu appliques toi-même les corrections, (5) on valide puis on note ce qu'on a appris. L'objectif n'est pas de reproduire le dépôt à l'identique : c'est de pouvoir défendre chaque choix et le faire évoluer.
