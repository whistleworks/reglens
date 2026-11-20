# PROGRESS

## Stato attuale (2026-11-20)
- **Branch:** `m1-fondamenta`, con il lavoro di M1–M5 in commit separati. Non ancora pubblicato su GitHub.
- **Su richiesta esplicita del titolare ("finiscilo al meglio")** si è proseguito oltre M1 senza le approvazioni per milestone, implementando il codice delle milestone successive. Le decisioni che spettano al titolare restano aperte (vedi sotto).
- **Test:** 285 unit test, 21 test sui dati e gli integration test con marcatore; `make check` verde.

| Milestone | Stato |
|---|---|
| M1 Fondamenta, ingestion, baseline | ✅ codice; ⏳ revisione del dataset da parte del titolare |
| M2 Retrieval ottimizzato e dataset completo | ✅ ibrido, RRF pesato, reranker, 4 strategie di chunking, arricchimento, filtri, 150 query in bozza, ablation; ⏳ revisione, baseline ufficiale (serve l'OK) |
| M3 Agente e valutazione generativa | ✅ gateway LLM, tool, loop, router, citazioni, giudice, stadio e2e (tutto testato con fake); ⏳ chiavi API, run reali, 40 etichette umane per il kappa |
| M4 API e osservabilità | ✅ FastAPI, SSE, RFC 7807, auth, rate limit, modalità degradate, UI, OTel → Langfuse, metriche, dashboard (14 pannelli), alert e runbook; ⏳ account Langfuse e Grafana |
| M5 Docker, CI/CD, deploy | ✅ Dockerfile, indice nell'immagine, workflow ci/eval-full/deploy/security/uptime, smoke gate; ⏳ repo GitHub, decisione sull'hosting, deploy, PR di prova bloccata dal gate |
| M6 Ottimizzazione e packaging | ⏳ run finale sul test (una volta sola), failure analysis, README finale, demo |

## Metriche attuali (tutte dev, dataset **non revisionato**: preliminari)
Dataset `reglens_v1@cdebd13e`, 83 query dev con target di retrieval. Tabella completa in `docs/ablation_v1_draft.md`.

| Config | recall@5 | MRR@10 | Run |
|---|---|---|---|
| bm25 | 0.565 | 0.525 | `evals/results/20261120-0844_f8c77a2c5c4f_8498a86c_dev.json` |
| dense | 0.747 | 0.657 | `evals/results/20261120-0844_f8c77a2c5c4f_d1e4efd9_dev.json` |
| hybrid_hier | 0.747 | 0.715 | `evals/results/20261120-0852_f8c77a2c5c4f_caaefbff_dev.json` |
| exp_norec (hybrid_hier senza considerando) | 0.825 | 0.801 | `evals/results/20261120-0853_f8c77a2c5c4f_399fb4a7_dev.json` |
| exp_norec_w05 (+ peso BM25 0.5) | 0.831 | 0.815 | `evals/results/20261120-0854_f8c77a2c5c4f_b6efad2b_dev.json` |
| exp_defs_norec_w05 (E3: definizioni come unità) | 0.868 | 0.852 | `evals/results/20261120-0910_28c7d8af9d18_164cbd59_dev.json` |
| **exp_units_norec_w05 = serving** (E4: + punti degli allegati) | **0.868** [0.81–0.93] | **0.858** | `evals/results/20261120-0939_28c7d8af9d18_a8537e7c_dev.json` |
| E3 + reranker | 0.837 | 0.833 | `evals/results/20261120-0916_28c7d8af9d18_050742e1_dev.json` |

- **BEIR SciFact BM25:** nDCG@10 0.6886 (+0.024 rispetto a 0.665, fuori tolleranza). Il gap è spiegato dal preprocessing: senza stemming 0.6617. Run in `evals/results/20261120-0748_*`.
- **Soglia M2 (recall@5 ≥ 0.85):** **raggiunta su dev** dalla configurazione servita (0.868); MRR 0.858 è sopra il target top 1% (0.80). Restano numeri preliminari finché il dataset non è revisionato.
- **Load test locale** (solo fonti, 5 utenti × 30 s): 17 req/s, p95 367 ms, 0 errori → `evals/results/20261120-0945_28c7d8af9d18_loadtest-local.json`.
- **Smoke test live locale** (`scripts/smoke_live.py`): 3 domande golden su 3 superate con indice snapshot e API key, e anche dalla UI pubblica.

## Esperimenti (ipotesi → risultato)
- **E1:** i considerando occupano il 44% delle posizioni top-5 ma quasi mai sono gold. Escluderli dal retrieval: recall@5 da 0.747 a 0.825 su hybrid_hier. **Confermato.**
- **E2:** BM25 più debole del dense, quindi meno peso nell'RRF. Peso 0.5: +0.006 recall@5 con i considerando esclusi; da solo ininfluente. **Effetto piccolo**, entro il CI.
- **E3:** le definizioni falliscono (recall@5 0.50 nella categoria definitional) perché l'art. 3 AIA e l'art. 4 GDPR sono spezzati in blocchi da 500 token con decine di definizioni. Strategia `paragraph_defs`, una definizione per chunk: recall@5 +0.036 (p = 0.047), MRR +0.038 (p = 0.007), categoria definitional a 0.90. **Confermato.**
- **E4:** i punti degli allegati diventano unità (strategia `units`). **Neutro** su dev (MRR +0.006, p = 0.37), ma risolve la domanda golden sul reclutamento (`AIA:annex:III:pt:4` al primo posto) e rende citabile il punto preciso. Adottato.
- **Reranker:** −0.030 recall@5 (CI [−0.056, −0.010]) e latenza p50 da 67 ms a 4480 ms: **scartato** (ADR-0003).
- **Prossimo esperimento:** la categoria scenario è ferma a 0.68. Ipotesi: riscrittura della query con l'LLM (servono le chiavi).

## Decisioni prese (con data)
- **2026-11-09:** corpus AIA = consolidato 27.07.2026 + considerando della GU; hosting rinviato a M5.
- **2026-11-20:**
  - Qdrant embedded (`QDRANT_URL=path:...`) in dev al posto di Docker, che non è installato (ADR-0004);
  - indice incluso nell'immagine (`INDEX_MODE=local_snapshot`);
  - LiteLLM sostituito da un gateway proprio per i due incidenti di supply chain del 2026 (ADR-0005);
  - FastAPI pinnata a 0.162.0 (release con più di due settimane);
  - dataset v1 con 150 query aggiunto con l'OK del titolare, tutte `reviewed: false`.

## Cosa serve dal titolare (bloccanti)
1. **Revisione delle 150 query:** `evals/datasets/review/reglens_v1_review.md`, più almeno 30 domande scritte a mano.
2. **OK per creare la baseline ufficiale** (`evals/baselines/main.json`) dopo la revisione.
3. **Chiavi API gratuite:** Groq e Google AI Studio (Gemini), in `.env`, per i run e2e reali.
4. **Etichettare 40 risposte** (pass/fail) per calibrare il giudice: `evals/human_labels/calibration.jsonl`.
5. **Hosting:** HF Spaces PRO ($9/mese) oppure Google Cloud Run (carta), vedi ADR-0001.
6. **Repo GitHub pubblico** e OK al push.
7. **Account Langfuse e Grafana Cloud** (gratuiti), facoltativi ma richiesti dal brief.

## Problemi aperti
- Docker non installato: integration test e BEIR su server Qdrant da fare in CI.
- Gap BEIR documentato (vedi sopra).
- Latenze misurate in modalità embedded: non sono latenze di produzione.

## Log sessioni
- **2026-11-09:** M1 passi 1–10 (bozza del dataset v0).
- **2026-11-20:** M2 (retrieval, chunking, dataset v1, ablation di 16 configurazioni, esperimenti E1–E4, ADR-0002 e 0003), codice di M3, M4 e M5, README, smoke test live e load test locali.
