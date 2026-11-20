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
- [~] 10. Dataset v0: 50 candidati dev scritti (`reviewed: false`), schema, CHANGELOG e foglio di revisione fatti; **mancano la tua revisione e i run baseline** (servono Docker e `make index`)

### Metriche attuali
- BEIR SciFact BM25 (backend Qdrant in-memory): nDCG@10 = 0.6886, CI95 [0.6472, 0.7317], n = 300 (il CI contiene 0.665) → `evals/results/20261109-1432_d425b8574451_beir-scifact.json`. Riferimento 0.665 (arXiv:2104.08663v4, Tab. 2): Δ = +0.0236, **fuori dalla tolleranza ±0.02** (più alto del valore pubblicato).
- **Baseline preliminari** su reglens_v0 dev, **dataset NON ancora revisionato** (41 query con target di retrieval; indice in Qdrant locale embedded):
  - BM25: recall@5 0.5915 [0.4674, 0.7236], recall@10 0.8293, MRR@10 0.5824, nDCG@10 0.5939 → `evals/results/20261109-1500_36dc321b4fc2_275a452f_dev.json`
  - Dense e5-large: recall@5 0.7642 [0.6585, 0.8618], recall@10 0.8537, MRR@10 0.6943, nDCG@10 0.6902 → `evals/results/20261109-1500_36dc321b4fc2_70b5c872_dev.json`
  - Soglia M2 recall@5 ≥ 0.85 non ancora raggiunta da nessuna configurazione. Errori ricorrenti: definizioni (art. 3/4, spezzati in più chunk), art. 113 (date), art. 53(1); i considerando "rubano" posizioni agli articoli. Da rifare dopo la revisione del dataset.

### Decisioni prese (con data)
- 2026-11-09: corpus AIA = consolidato 02024R1689-20260727 (articoli/allegati) + GU 32024R1689 (considerando). Conteggi attesi aggiornati rispetto al brief.
- 2026-11-09: hosting rinviato a M5 (HF Spaces Docker probabilmente non più gratuito).
- 2026-11-09: Qdrant locale via Docker (da installare: OrbStack o Docker Desktop).

### Problemi aperti
- Docker non installato (e niente Homebrew): per ora l'indice usa Qdrant locale embedded (`QDRANT_URL=path:qdrant_local`). Integration test e BEIR sul server restano da fare.
- Nei chunk IT i titoli di considerando e allegati sono in inglese ("Recital 57", "Annex III"): da localizzare (richiede reindicizzazione, ~12 min).
- BEIR SciFact +0.0236 sopra il valore pubblicato (criterio M1: ±0.02). Ipotesi, da verificare senza fare tuning per centrare il numero:
  1. BEIR usa Elasticsearch multi_match su title e text come campi separati; noi concateniamo title + text in un solo campo.
  2. Analyzer diverso: Snowball english di FastEmbed con le sue stopword vs l'analyzer ES di BEIR.
  3. avg_len calcolato sui token dopo stopword e stemming (come FastEmbed) vs la lunghezza dei campi Lucene.
  **Esperimento fatto (2026-11-20, Qdrant in-memory, file `evals/results/20261120-*_beir-scifact-*.json`):** senza titolo 0.6762 (+0.011), senza stemming 0.6617 (−0.003), senza entrambi 0.6472 (−0.018). Il gap è spiegato dal preprocessing (stemming ≈ +0.027, titolo ≈ +0.012), non da un errore nel calcolo di BM25/IDF/nDCG. La configurazione ufficiale **non** viene modificata per centrare il valore. Da decidere con te: accettare il gap documentato oppure allineare il preprocessing a quello di BEIR dopo averne verificato l'analyzer Elasticsearch nel codice di BEIR. Va rieseguito sul server Qdrant quando Docker è disponibile.

### Prossimo passo
1. **Tu:** installa Docker (`brew install --cask orbstack`, poi apri OrbStack una volta).
2. **Tu:** rivedi `evals/datasets/review/reglens_v0_review.md` (50 candidati) e segna correzioni e approvazioni.
3. **Io, dopo i passi 1–2:** `make qdrant && make index`, `make test-integration`, `make beir` sul server Qdrant, applico le tue correzioni al dataset (`reviewed: true` solo sui record approvati), poi `make eval CONFIG=configs/bm25.yaml` e `make eval CONFIG=configs/dense.yaml`.
4. Esperimenti diagnostici sul gap BEIR (vedi Problemi aperti), poi `/preflight`, creazione del repo GitHub e PR della M1 (con conferma prima del push).

### Note per M2
- FastEmbed 0.9.1 include solo `multilingual-e5-large` tra gli e5 (niente small/base, niente bge-m3 dense): per l'ablation sugli embedding serve `TextEmbedding.add_custom_model` con gli ONNX di e5-small/base.
- Il chunker baseline divide l'art. 3 dell'AIA (70 definizioni in un solo paragrafo) su più chunk: per le domande sulle definizioni è un candidato naturale per la strategia article-aware.
- `run_eval` rifiuta già `--split test` senza `--final`; resta da fare il log degli accessi (`test_access.log`).

## Log sessioni
- 2026-11-09: piano M1 approvato; passi 1–7 e 9 completati; passo 8 completato tranne il run reale (manca Docker); passo 10 in bozza. 174 unit test e 13 test sui dati verdi.
