# Journal du projet

## Version 1.0 — Prototype de référence

**Hypothèses :** API seule ; PDF textuels ; usage local mono-instance ; pas d'OCR ; pas de compte utilisateur ; 10 Mio / 200 pages par défaut.

**Décisions :** import synchrone, stockage SQLite + fichiers, BM25 hors ligne, embeddings multilingues optionnels, génération via API compatible OpenAI optionnelle. JSON et documentation Swagger constituent le contrat public. Les références `[n]` relient chaque réponse à un extrait original et à une page.

**Risques connus :** pas de garantie sémantique absolue, pas de preuve formelle d'absence d'hallucination, extraction difficile des PDF complexes, suppression de binaire non transactionnelle par rapport à SQLite, pas conçu pour exposition Internet sans configuration et protections supplémentaires.

**Passage 2 :** reproduire le besoin, pas le code. Ouvrir `PLAN_RECONSTRUCTION.md` et commencer par une route `/health` écrite par Raïssa.
