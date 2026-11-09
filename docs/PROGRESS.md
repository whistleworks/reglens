# PROGRESS

## Stato attuale
- Milestone: **M1 — Fondamenta, ingestion, baseline di retrieval** (in corso, branch `m1-fondamenta`)
- Piano approvato: 10 passi (vedi sezione M1 sotto).

## M1

### Fatto
- [x] 1. Scaffold (pyproject, Makefile, CI, CLAUDE.md, .claude/, config, logging)
- [x] 2. ADR-0001 stack e free tier
- [x] 3. ids.py
- [x] 4. fetch.py (Cellar)
- [x] 5. parse.py
- [x] 6. xrefs.py + glossario
- [x] 7. chunk + manifest + idempotenza
- [~] 8. Qdrant + indicizzazione dense/sparse — codice e unit test (Qdrant in-memory) fatti; integration test e `make index` in attesa di Docker
- [x] 9. Metriche retrieval + run_eval + BEIR sanity (BEIR fuori tolleranza, vedi Problemi aperti)
- [ ] 10. Dataset v0 (50 dev, revisione umana) + baseline

### Metriche attuali
- BEIR SciFact BM25 (backend Qdrant in-memory): nDCG@10 = 0.6886, CI95 [vedi JSON], n = 300 → `evals/results/20261109-1432_d425b8574451_beir-scifact.json`. Riferimento 0.665 (arXiv:2104.08663v4, Tab. 2): Δ = +0.0236, **fuori dalla tolleranza ±0.02** (più alto del valore pubblicato).
- Nessun run sul dataset RegLens ancora (serve il dataset v0 e l'indice).

### Decisioni prese (con data)
- 2026-11-09: corpus AIA = consolidato 02024R1689-20260727 (articoli/allegati) + GU 32024R1689 (considerando). Conteggi attesi aggiornati rispetto al brief.
- 2026-11-09: hosting rinviato a M5 (HF Spaces Docker probabilmente non più gratuito).
- 2026-11-09: Qdrant locale via Docker (da installare: OrbStack o Docker Desktop).

### Problemi aperti
- Docker non installato sul Mac di sviluppo: bloccano `make index`, l'integration test e i run di eval sul corpus.
- BEIR SciFact +0.0236 sopra il valore pubblicato (criterio M1: ±0.02). Ipotesi, da verificare senza fare tuning per centrare il numero:
  1. BEIR usa Elasticsearch multi_match su title e text come campi separati; noi concateniamo title + text in un solo campo.
  2. Analyzer diverso: Snowball english di FastEmbed con le sue stopword vs l'analyzer ES di BEIR.
  3. avg_len calcolato sui token dopo stopword e stemming (come FastEmbed) vs la lunghezza dei campi Lucene.
  Esperimento proposto: due run diagnostici (solo `text` senza titolo; stemmer disabilitato) per misurare la sensibilità, più un confronto con `rank_bm25` sullo stesso preprocessing. Va rieseguito anche sul server Qdrant, quando Docker è disponibile.

### Prossimo passo
Passo 2: ADR-0001.
