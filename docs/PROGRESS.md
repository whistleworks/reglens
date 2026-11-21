# PROGRESS

## Stato attuale (2026-11-21)
- **Repo:** pubblico su https://github.com/whistleworks/reglens. Il branch `m1-fondamenta` (M1–M5 in commit separati) è stato unito in `main` con la PR #1 il 2026-11-20, con CI verde: check, integration, smoke-eval-gate, pip-audit, gitleaks e trivy.
- **Su richiesta esplicita del titolare ("finiscilo al meglio")** si è proseguito oltre M1 senza le approvazioni per milestone, implementando il codice delle milestone successive. Le decisioni che spettano al titolare restano aperte (vedi sotto).
- **Test:** 291 unit test, 21 test sui dati e gli integration test con marcatore; `make check` verde.

| Milestone | Stato |
|---|---|
| M1 Fondamenta, ingestion, baseline | ✅ codice; ⏳ revisione del dataset da parte del titolare |
| M2 Retrieval ottimizzato e dataset completo | ✅ ibrido, RRF pesato, reranker, 4 strategie di chunking, arricchimento, filtri, 150 query in bozza, ablation; ⏳ revisione, baseline ufficiale (serve l'OK) |
| M3 Agente e valutazione generativa | ✅ gateway LLM, tool, loop, router, citazioni, giudice, stadio e2e; **primo run reale e2e su dev (Gemini, 2026-11-21)**; ⏳ chiave Groq (giudice di un'altra famiglia), rerun dopo i fix, 40 etichette umane per il kappa |
| M4 API e osservabilità | ✅ FastAPI, SSE, RFC 7807, auth, rate limit, modalità degradate, UI, OTel → Langfuse, metriche, dashboard (14 pannelli), alert e runbook; ⏳ account Langfuse e Grafana |
| M5 Docker, CI/CD, deploy | ✅ Dockerfile, indice nell'immagine, workflow ci/eval-full/deploy/security/uptime, smoke gate; ⏳ repo GitHub, decisione sull'hosting, deploy, PR di prova bloccata dal gate |
| M6 Ottimizzazione e packaging | 🟡 failure analysis del retrieval su dev (18 errori, `docs/failure-analysis.md`); ⏳ parte generativa, run finale sul test (una volta sola), README finale, demo |

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

## Run e2e reale (2026-11-21, preliminare)
Run `evals/results/20261121-1324_d24fee8de0ab_e2e_hybrid_dev.json`: 100 query dev, generatore **e giudice** `gemini/gemini-3.5-flash-lite` (stesso modello: rischio di self-preference, da rifare con un giudice di un'altra famiglia), dataset non revisionato. 5 query finite in `llm_error` per la quota giornaliera free tier (500 richieste/giorno per modello), contate in error_rate.

| Metrica | Valore [CI95] | n |
|---|---|---|
| task_success | 0.966 [0.91–1.00] | 58 |
| faithfulness | 0.910 [0.85–0.96] | 59 |
| citation_precision | 0.841 [0.78–0.90] | 63 |
| citation_recall | 0.635 [0.54–0.72] | 89 |
| citation_validity | 1.000 | 63 |
| refusal_accuracy | 0.700 [0.61–0.79] | 100 |
| step_limit_hit | 0.160 [0.10–0.23] | 100 |
| injection_success | 0.571 [0.14–0.86] | 7 |
| error_rate | 0.050 [0.01–0.09] | 100 |

- Latenze del file non significative (risposte in gran parte dalla cache LLM).
- **Dopo questo run** è stato corretto lo step limit (commit c6fc6a3: ultimo passo solo `final_answer`, max_tokens 4096): il 16% di `step_limit` va rimisurato. Verificato a mano sulla domanda del reclutamento: risposta con 5 citazioni corrette.
- **Da guardare:** injection_success 4/7 sulle domande avversarie, scenario e multi_hop con citation_recall basso (0.35/0.39).

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
3. ~~Chiave Gemini~~: fatto il 2026-11-21. **Manca la chiave Groq** (giudice indipendente e generatore previsto).
4. **Etichettare 40 risposte** (pass/fail) per calibrare il giudice: `evals/human_labels/calibration.jsonl`.
5. **Hosting:** HF Spaces PRO ($9/mese) oppure Google Cloud Run (carta), vedi ADR-0001.
6. ~~Repo GitHub pubblico~~: fatto il 2026-11-20 su whistleworks, PR #1 unita.
7. **Account Langfuse e Grafana Cloud** (gratuiti), facoltativi ma richiesti dal brief.

## Problemi aperti
- Docker non installato in locale: gli integration test su server Qdrant girano in CI (verdi sulla PR #1).
- Su 5vjf9ffgdw-max resta un repo `reglens` privato e vuoto, creato per errore. Si cancella solo entrando con quell'account; il titolare usa solo whistleworks, quindi si può lasciare.
- `gemini-3.8-flash` (modello previsto) restituiva 503 "high demand" il 2026-11-21; in uso `gemini-3.5-flash` per l'app locale e `gemini-3.5-flash-lite` per il run.
- Free tier Gemini: limite al minuto e 500 richieste/giorno per modello; il run e2e va fatto a blocchi (la cache LLM evita di ripetere le chiamate riuscite).
- Gap BEIR documentato (vedi sopra).
- Latenze misurate in modalità embedded: non sono latenze di produzione.

## Log sessioni
- **2026-11-09:** M1 passi 1–10 (bozza del dataset v0).
- **2026-11-20:** M2 (retrieval, chunking, dataset v1, ablation di 16 configurazioni, esperimenti E1–E4, ADR-0002 e 0003), codice di M3, M4 e M5, README, smoke test live e load test locali; pubblicazione su GitHub (whistleworks), fix del workflow security (trivy-action fissata per sha, pip-audit senza il progetto stesso).
- **2026-11-21:** PR #10 (provider Ollama). Primi run reali con Gemini: corretti 4 bug che i test con fake non vedevano (`seed` rifiutato da Gemini, `thought_signature` da rimandare nei tool call, error_rate che ignorava `llm_error`, ultimo passo senza `final_answer` + max_tokens). Run e2e su 100 query dev. App locale avviabile dalla Scrivania (`~/Desktop/RegLens.command`, porta 8000). Cache del modello di embedding spostata in `.cache/fastembed` (prima in una cartella temporanea svuotata al riavvio). Modelli Ollama rimossi dal Mac (16 GB) su richiesta del titolare.
