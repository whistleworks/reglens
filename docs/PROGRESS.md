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
- [ ] 7. chunk + manifest + idempotenza
- [ ] 8. Qdrant + indicizzazione dense/sparse
- [ ] 9. Metriche retrieval + run_eval + BEIR sanity
- [ ] 10. Dataset v0 (50 dev, revisione umana) + baseline

### Metriche attuali
Nessun run di eval ancora.

### Decisioni prese (con data)
- 2026-11-09: corpus AIA = consolidato 02024R1689-20260727 (articoli/allegati) + GU 32024R1689 (considerando). Conteggi attesi aggiornati rispetto al brief.
- 2026-11-09: hosting rinviato a M5 (HF Spaces Docker probabilmente non più gratuito).
- 2026-11-09: Qdrant locale via Docker (da installare: OrbStack o Docker Desktop).

### Problemi aperti
- Docker non installato sul Mac di sviluppo (blocca il passo 8).

### Prossimo passo
Passo 2: ADR-0001.
