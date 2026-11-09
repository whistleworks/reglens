# PROMPT DI PROGETTO — "RegLens": Agentic RAG + Evaluation Platform (production-grade)

> Copia del brief originale (2026-11-09). Le deviazioni decise durante il progetto sono registrate negli ADR in docs/adr/ e in docs/PROGRESS.md; questo file non viene riscritto.

## 0. REGOLE DI INGAGGIO (vincolanti per tutta la durata del progetto)

Sei il mio Lead AI Engineer e pair programmer. Io sono lo sviluppatore titolare del progetto: tu implementi, io faccio review, etichetto a mano i dati di valutazione e prendo le decisioni di prodotto.

- Lavoriamo UNA milestone alla volta (sezione 4). Non anticipare lavoro delle milestone successive.
- All'inizio di ogni milestone entra in plan mode, leggi CLAUDE.md e docs/PROGRESS.md, proponi un piano a passi numerati e ASPETTA la mia approvazione prima di scrivere codice.
- Test insieme al codice (o prima): nessuna funzione di core logic senza unit test.
- Commit piccoli e incrementali in formato Conventional Commits (feat:, fix:, test:, docs:, chore:, perf:, ci:). Un commit per ogni passo del piano, dopo `make check` verde.
- MAI inventare numeri. Ogni metrica citata in README, PR o report deve provenire da un file in evals/results/ generato da `make eval`. Se una soglia non è raggiunta, lo scrivi chiaramente e proponi ipotesi e prossimi esperimenti: un risultato onesto vale più di un numero gonfiato.
- MAI modificare senza mio OK esplicito: evals/datasets/ (soprattutto lo split test), evals/baselines/, le soglie di accettazione, i judge prompt già calibrati.
- MAI committare segreti. Solo .env.example con valori fittizi.
- Prima di scegliere un servizio gratuito, VERIFICA online i limiti attuali del free tier (quote, RAM, sleep, sospensioni per inattività, modelli disponibili) e registra fonte e data nell'ADR corrispondente. I free tier cambiano: non fidarti della memoria.
- Se sei bloccato da una decisione che spetta a me, fermati e chiedi con al massimo 3 opzioni e una raccomandazione.
- Alla fine di ogni sessione aggiorna docs/PROGRESS.md (fatto, metriche attuali, problemi aperti, prossimo passo).

## 1. RUOLO, OBIETTIVO E DEFINIZIONE DI "TOP 1% SIGNAL"

### Il prodotto
RegLens è un copilota agentico che risponde a domande su EU AI Act (Reg. UE 2024/1689) e GDPR (Reg. UE 2016/679), in inglese e italiano, con citazioni verificabili al livello di articolo e paragrafo, link diretti alla fonte EUR-Lex, rifiuto esplicito quando la risposta non è nel corpus e disclaimer "non è consulenza legale".

Esempi di domande:
- "Quali pratiche di AI sono vietate dall'AI Act?"
- "A chatbot used for hiring decisions: is it high-risk? Which obligations apply?"
- "Che rapporto c'è tra la valutazione d'impatto sui diritti fondamentali dell'AI Act e la DPIA del GDPR?"

Il dominio è scelto perché le citazioni sono verificabili in modo deterministico (ID articolo), il corpus è pubblico, il valore di business è chiaro (compliance) e il bilinguismo IT/EN è una sfida tecnica reale.

### Cosa deve dimostrare il portfolio (top 1% signal)
1. **Eval-driven development.** Un benchmark costruito e revisionato a mano (150 query, split dev/test), un giudice LLM calibrato contro etichette umane, ablation con intervalli di confidenza e un regression gate in CI che blocca le PR peggiorative.
2. **Production engineering.** Gestione errori, retry, fallback, degradazione controllata, rate limiting, budget kill-switch, osservabilità end-to-end, alert e runbook.
3. **Engineering judgment.** ADR per ogni scelta importante, alternative scartate con motivazione, failure analysis onesta e trade-off qualità/latenza/costo resi espliciti (frontiera di Pareto).
4. **Shipping.** URL live funzionante, deploy automatico da main, riproducibilità con `make setup && make demo` su macchina pulita.
5. **Comprensione dei fondamentali.** Agent loop scritto da zero (niente framework opachi), retrieval ibrido spiegato e misurato, sanity check su benchmark pubblico (BEIR SciFact) contro valori pubblicati.
6. **Comunicazione.** README leggibile in 2 minuti da un hiring manager, con numeri reali, diagramma, limiti e "cosa farei in produzione".

### Non-goals
Niente fine-tuning, niente UI elaborata, niente multi-tenant, niente consulenza legale reale.

## 2. ARCHITETTURA

### Componenti
1. **Ingestion offline (CLI):** fetch → parse strutturato → normalizzazione → chunking → arricchimento contestuale → embedding dense + sparse → indicizzazione → manifest versionato.
2. **Article Store:** corpus strutturato in JSON caricato in memoria, per accesso esatto per ID (articolo, paragrafo, definizione, cross-reference).
3. **Retrieval:** ibrido dense + sparse (BM25), fusione RRF, reranker cross-encoder opzionale (deciso dall'ablation), filtri su metadati (regolamento, lingua, tipo).
4. **Agent:** loop tool-calling proprietario con stato esplicito, max step, budget di token e timeout, output strutturato con citazioni.
5. **Guardrail:** validazione input, euristiche anti prompt-injection, validatore di citazioni (ID citati ⊆ ID recuperati, testo citato presente nella fonte), policy di rifiuto.
6. **Router:** classifica la query (semplice → RAG a singolo passo; complessa/multi-hop → agente) per ridurre costo e latenza. Va misurato.
7. **LLM Gateway:** wrapper su LiteLLM con timeout, retry (backoff esponenziale + jitter), circuit breaker, catena di fallback tra provider, cache, conteggio token e shadow cost.
8. **API:** FastAPI con streaming SSE, errori RFC 7807, request ID, auth con API key, rate limit, endpoint di feedback.
9. **Web UI minimale:** pagina statica servita da FastAPI, con risposta in streaming, citazioni cliccabili verso EUR-Lex, pulsanti 👍/👎 e disclaimer.
10. **Eval Harness:** metriche deterministiche e LLM-judge, bootstrap CI, report, confronto con baseline, gate CI.
11. **Observability:** structlog JSON, trace Langfuse per ogni richiesta, metriche OpenTelemetry → Grafana Cloud, alert, online eval notturna.

### Flusso dati online
richiesta → middleware (request_id, auth, rate limit) → validazione input + guardrail → router → [RAG singolo passo | agent loop: LLM sceglie tool → search/get_article/get_definition/follow_references → retrieval ibrido → RRF → rerank] → risposta strutturata {answer, citations[], confidence, refused} → validatore citazioni (una sola riparazione, altrimenti rifiuto) → streaming al client + trace_id → feedback collegato alla trace.

Ogni stadio è uno span con latenza, token e costo.

### Tool dell'agente (read-only, schema Pydantic, allowlist)
- `search(query: str, regulation: Literal["AIA","GDPR"] | None, lang: Literal["en","it"] | None, k: int = 8)`
- `get_article(regulation, article: int, paragraph: int | None)`
- `get_definition(term: str)`: glossario estratto da AIA art. 3 e GDPR art. 4
- `follow_references(regulation, article)`: cross-reference estratte in ingestion
- Output finale tramite `final_answer(answer, citations: list[CitationID], refused: bool, reason: str | None)`

Limiti: max 6 step, timeout totale 25 s, budget token per richiesta configurabile.

### Scelte tecnologiche e alternative scartate (ognuna diventa un ADR in docs/adr/)

| Area | Scelta | Scartate e perché |
|---|---|---|
| Linguaggio e packaging | Python 3.12 + uv | poetry/pip: più lenti, lockfile meno affidabile |
| API | FastAPI + Uvicorn | Flask: niente async nativo né OpenAPI automatica |
| LLM | LiteLLM sopra free tier (Groq, Gemini, Cerebras, OpenRouter, Mistral: verifica quali sono gratuiti OGGI). Generatore = miglior modello disponibile; giudice = modello di famiglia DIVERSA, per ridurre il self-preference bias | SDK diretto di un provider: lock-in, niente fallback |
| Embedding | Modello multilingue open source via FastEmbed/ONNX su CPU (candidati: famiglia multilingual-e5, bge-m3; scelta per ablation) | Embedding API a pagamento: costo e lock-in; modelli solo-EN: corpus bilingue |
| Sparse | BM25 tramite vettori sparsi Qdrant | Elasticsearch: un servizio in più, overkill |
| Vector DB | Qdrant: Docker in dev, Qdrant Cloud free tier in prod, snapshot dell'indice nell'immagine come fallback | pgvector: ottimo ma ibrido meno nativo; Chroma: meno maturo per prod; Pinecone: chiuso, lock-in |
| Reranker | Cross-encoder multilingue open source (licenza commerciale permissiva: verifica), attivato solo se l'ablation giustifica la latenza su CPU | Rerank via API: costo |
| Agent | Loop proprietario (< 400 righe), con stato e transizioni esplicite | LangChain/LlamaIndex agents: astrazioni opache, debug difficile; LangGraph: valido, ma qui l'obiettivo è dimostrare di capire il meccanismo (citalo come path di migrazione) |
| Eval | Harness proprio + pytest + Langfuse datasets; RAGAS solo come cross-check | Solo RAGAS: metriche black-box, giudice non calibrato |
| Tracing | Langfuse (cloud free o self-host) + OpenTelemetry | LangSmith: centrato sull'ecosistema LangChain; Arize Phoenix: valida alternativa, documentala |
| Metriche e alert | OTel metrics → Grafana Cloud free | Prometheus/Grafana self-hosted: niente hosting gratuito stabile |
| Hosting | Hugging Face Spaces (Docker, CPU free) | Render free: RAM insufficiente per i modelli; Cloud Run: richiede carta; Fly.io/Railway: free tier assente o limitato (verifica) |
| Registry e CI | GHCR + GitHub Actions | — |

## 3. STRUTTURA DEL REPOSITORY E CONVENZIONI

```
reglens/
├── CLAUDE.md
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .claude/
│   ├── settings.json
│   ├── commands/{milestone.md, eval-report.md, preflight.md}
│   └── agents/eval-auditor.md
├── .github/
│   ├── workflows/{ci.yml, eval-full.yml, deploy.yml, security.yml, uptime.yml}
│   ├── pull_request_template.md
│   └── dependabot.yml
├── docs/
│   ├── PROGRESS.md
│   ├── architecture.md
│   ├── eval-methodology.md
│   ├── runbook.md
│   ├── failure-analysis.md
│   ├── adr/0001-stack-and-free-tiers.md … 000N-*.md
│   └── diagrams/{architecture.mmd, request-flow.mmd}
├── data/
│   ├── README.md                (fonti, licenze, checksum)
│   ├── raw/                     (gitignored, ricreabile)
│   └── processed/{corpus_en.json, corpus_it.json, glossary.json, xrefs.json, manifest.json}
├── src/reglens/
│   ├── __init__.py
│   ├── config.py                (pydantic-settings, unica fonte di config)
│   ├── ids.py                   (formato canonico degli ID e parsing)
│   ├── api/{main.py, routes.py, schemas.py, auth.py, ratelimit.py, middleware.py, errors.py}
│   ├── ingestion/{fetch.py, parse.py, xrefs.py, chunk.py, enrich.py, embed.py, index.py, cli.py}
│   ├── retrieval/{store.py, dense.py, sparse.py, fusion.py, rerank.py, pipeline.py}
│   ├── agent/{loop.py, state.py, tools.py, router.py, guardrails.py, citations.py, prompts/}
│   ├── llm/{client.py, fallback.py, cache.py, pricing.py, budget.py}
│   ├── observability/{logging.py, tracing.py, metrics.py}
│   └── web/static/{index.html, app.js, style.css}
├── evals/
│   ├── datasets/{reglens_v1.jsonl, schema.json, CHANGELOG.md}
│   ├── human_labels/calibration.jsonl
│   ├── judge_prompts/{faithfulness_v1.md, correctness_v1.md}
│   ├── metrics/{retrieval.py, generation.py, judge.py, agent.py, stats.py}
│   ├── run_eval.py
│   ├── compare.py
│   ├── report.py
│   ├── calibrate_judge.py
│   ├── beir_sanity.py
│   ├── cache/                   (replay delle risposte LLM per lo smoke test in CI)
│   ├── baselines/main.json
│   └── results/
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── scripts/{generate_candidates.py, load_test.py, seed_qdrant.py, smoke_live.py}
└── dashboards/grafana_reglens.json
```

### Convenzioni
- ruff (lint + format) e mypy --strict su src/. Type hints ovunque.
- Modelli Pydantic v2 a ogni confine (API, tool, output LLM, dataset).
- Nessun print: solo structlog. Config solo da variabili d'ambiente tramite config.py.
- Dependency injection dei client (LLM, Qdrant, Langfuse) per poterli sostituire con fake nei test.
- ID canonici: `AIA:art:6:par:2`, `AIA:rec:53`, `AIA:annex:III:pt:4`, `GDPR:art:4:def:11`. Parsing e validazione in ids.py.
- Prompt come file versionati in agent/prompts/ con header `version:`. La versione finisce in ogni trace.
- Test: unit senza rete; integration con Qdrant in container; `@pytest.mark.llm` per i test che chiamano LLM reali (esclusi di default). Coverage ≥ 80% su retrieval/, agent/, llm/, evals/metrics/.
- Target Makefile: setup, fmt, lint, typecheck, test, check (= lint + typecheck + test), ingest, index, eval, eval-smoke, eval-final, calibrate, compare, serve, demo, docker-build, docker-run, load-test.

## 4. PIANO DI LAVORO: 6 MILESTONE SETTIMANALI (10–15 h/settimana)

Template del prompt da incollare all'inizio di ogni milestone:
"Leggi CLAUDE.md e docs/PROGRESS.md. Siamo alla Milestone N: [titolo]. Entra in plan mode e proponi un piano a passi numerati (max 10), con i file toccati, i test previsti e i rischi. Non scrivere codice finché non approvo. Dopo l'approvazione: TDD, `make check` a ogni passo, un commit per passo, aggiornamento di PROGRESS.md a fine sessione."

Flusso standard per ogni milestone:
`/clear` → template del prompt → plan mode (Shift+Tab) → approvazione → implementazione → `/preflight` → branch `mN-titolo` → PR → CI verde → `/eval-report` → merge. Usa `/compact` quando il contesto si allunga e `@percorso/file` per riferirti ai file senza incollarli.

### M1 — Fondamenta, ingestion, baseline di retrieval (settimana 1)
**Deliverable**
- Scaffold del repo, CLAUDE.md, .claude/, Makefile, pre-commit, ci.yml base (lint, typecheck, test).
- ADR-0001: stack e limiti dei free tier verificati, con fonti e data.
- Pipeline di ingestion AI Act + GDPR in EN e IT: corpus strutturato, glossario, cross-reference, manifest.
- Qdrant locale con docker-compose. Baseline solo BM25 e solo dense.
- Modulo evals/metrics/retrieval.py con unit test (recall@k, MRR@k, nDCG@k su casi calcolati a mano).
- Dataset v0: 50 query dev (vedi sezione 6).
- evals/beir_sanity.py su BEIR SciFact.

**Criteri di accettazione**
- `make ingest` è idempotente: due esecuzioni producono lo stesso hash nel manifest.
- Conteggi verificati da test: AI Act 113 articoli, 180 considerando, 13 allegati; GDPR 99 articoli, 173 considerando, in entrambe le lingue, con stessi ID tra EN e IT.
- Zero chunk vuoti, ID univoci.
- BM25 su SciFact entro ±0.02 di nDCG@10 dal valore pubblicato nel paper BEIR (verifica il valore e citalo).
- `make eval` produce un JSON di risultati valido. CI verde.

**Comandi:** `make setup`, `make ingest`, `make index`, `uv run python evals/beir_sanity.py`, `make eval SPLIT=dev STAGE=retrieval`.

### M2 — Retrieval ottimizzato e dataset completo (settimana 2)
**Deliverable**
- Retrieval ibrido con RRF e reranker opzionale.
- Tre strategie di chunking: fixed 512 token con overlap; article-aware; paragraph-level con contesto del parent.
- Arricchimento contestuale (prefisso gerarchico "GDPR > Capo III > Art. 17 Diritto alla cancellazione > par. 1" prima dell'embedding).
- Query cross-lingua (domanda IT su corpus EN+IT). Filtri su metadati.
- Dataset espanso a 150 query (100 dev / 50 test, stratificato per categoria), revisionato da me al 100%.
- Tabella di ablation v1 con almeno 6 configurazioni, ciascuna con recall@5, MRR@10, nDCG@10 (CI 95%) e latenza p50/p95 del retrieval. Prima evals/baselines/main.json.

**Criteri di accettazione**
- Recall@5 su dev ≥ 0.85 per la configurazione migliore, oppure gap documentato con ipotesi.
- schema.json validato da test. Ogni record ha `reviewed: true`.
- run_eval.py rifiuta `--split test` senza il flag `--final`, e ogni uso viene loggato in evals/results/test_access.log.
- ADR su chunking e reranker motivati dai numeri.

**Comandi:** `make eval SPLIT=dev STAGE=retrieval CONFIG=configs/hybrid_rerank.yaml`, `make compare A=<run> B=<run>`.

### M3 — Agente, generazione, valutazione generativa (settimana 3)
**Deliverable**
- llm/ con LiteLLM: timeout, retry, circuit breaker, fallback, cache su disco, pricing.py (listino a pagamento equivalente con data, per lo shadow cost).
- I 4 tool, agent loop, router, output strutturato, validatore di citazioni, policy di rifiuto, prompt versionati.
- Metriche generative e di agente. Giudice LLM con prompt versionati.
- calibrate_judge.py: io etichetto a mano 40 risposte (pass/fail su faithfulness e correctness) e tu calcoli accordo e Cohen's kappa.

**Criteri di accettazione (su dev)**
- Faithfulness ≥ 0.90, correctness ≥ 0.75, citation precision ≥ 0.90, refusal accuracy ≥ 0.85.
- Kappa giudice-umano ≥ 0.6; se inferiore, itera sul judge prompt e documenta ogni versione.
- Zero eccezioni non gestite su un run completo di dev.
- Unit test del loop con LLM fake: errore di un tool, JSON malformato, step limit raggiunto, citazione non valida → riparazione → rifiuto.
- Il router riduce il costo medio per query senza far scendere la correctness di più di 1 punto (misurato).

**Comandi:** `make eval SPLIT=dev`, `make calibrate`, `make compare`.

### M4 — API production-grade e observability (settimana 4)
**Deliverable**
- Endpoint: POST /v1/ask (JSON e SSE), POST /v1/feedback, GET /health, GET /ready (controlla Qdrant e LLM), GET /version, /docs.
- Errori RFC 7807, request_id propagato, auth con API key, rate limit per chiave e per IP, validazione input.
- Modalità degradate: reranker giù → ibrido senza rerank; LLM giù o budget esaurito → modalità "solo fonti" con i passaggi recuperati; Qdrant giù → 503 con Retry-After.
- Tracing Langfuse completo, structlog, metriche OTel, dashboard Grafana esportata in JSON, regole di alert, web UI minimale.

**Criteri di accettazione**
- Ogni richiesta produce una trace con span per ogni stadio, costo e versioni (prompt, indice, git_sha).
- Test di fault injection (timeout LLM, 429, Qdrant irraggiungibile, budget superato) verificano il comportamento documentato.
- Coverage ≥ 80% sui moduli core. Dashboard con almeno 10 pannelli popolati da traffico sintetico.

**Comandi:** `make serve`, `make test`, `uv run python scripts/load_test.py --users 5 --duration 60` (locale).

### M5 — Docker, CI/CD, deploy live, sicurezza, load test (settimana 5)
**Deliverable**
- Dockerfile multi-stage e docker-compose.
- Workflow ci.yml, eval-full.yml, deploy.yml, security.yml, uptime.yml.
- Replay cache per lo smoke eval in CI, regression gate.
- Deploy su HF Spaces + Qdrant Cloud, smoke test post-deploy.
- Subset di prompt injection valutato, report di load test, alert testati.

**Criteri di accettazione**
- Push su main → live in meno di 15 minuti senza passaggi manuali.
- Una PR di prova che peggiora deliberatamente il retrieval viene bloccata dal gate (lascia il link alla PR chiusa come prova).
- URL live risponde. gitleaks, pip-audit e trivy puliti, oppure eccezioni documentate.
- Load test: 20 utenti per 5 minuti con p95, error rate e comportamento sotto rate limit del provider documentati.
- Almeno un alert scattato davvero (screenshot in docs/).

**Comandi:** `make docker-build && make docker-run`, `gh workflow run eval-full.yml`, `uv run python scripts/smoke_live.py --url $LIVE_URL`.

### M6 — Ottimizzazione, test finale, packaging (settimana 6)
**Deliverable**
- Ottimizzazione costo/latenza: cache esatta, top-k tuning, modello più piccolo per le query semplici del router, compressione del contesto.
- Grafico della frontiera di Pareto (qualità vs costo vs latenza).
- UN SOLO run finale sullo split test con `make eval-final`.
- Failure analysis: 20 errori reali categorizzati (retrieval miss, chunking, reasoning, citazione, rifiuto errato) in docs/failure-analysis.md.
- README completo, diagrammi, almeno 5 ADR, GIF o video demo di 2 minuti, bullet CV con numeri reali, checklist della sezione 11.

**Criteri di accettazione**
- Soglie raggiunte sul test, oppure gap documentati.
- Clone pulito → `make setup && make demo` funzionante in meno di 10 minuti (verificalo in un container pulito).
- Checklist 15/15.

**Comandi:** `make eval-final`, `make compare A=baselines/main.json B=<final>`, `/eval-report`.

## 5. DATI: FONTI, INGESTION, PREPROCESSING

### Fonti (pubbliche e gratuite)
- EUR-Lex, testi consolidati in HTML in EN e IT: AI Act (CELEX 32024R1689) e GDPR (CELEX 32016R0679).
- Riuso consentito dalla Decisione 2011/833/UE con indicazione della fonte: verificalo e documentalo in data/README.md e nel README.
- Stretch opzionale: Data Act o DSA, solo dopo M6.
- Sanity benchmark: BEIR SciFact (dataset `BeIR/scifact` su Hugging Face).

### Pipeline
1. **fetch.py:** download con User-Agent esplicito, retry, cache in data/raw/ e sha256 nel manifest. Se EUR-Lex blocca il download automatico, stampa le istruzioni per il download manuale una tantum e verifica l'hash.
2. **parse.py:** lxml/BeautifulSoup verso un modello gerarchico Regulation → Chapter → Section → Article → Paragraph → Point, più Recitals e Annexes. Conserva numerazione e titoli. Rimuovi note e artefatti HTML.
3. **xrefs.py:** estrazione delle cross-reference via regex bilingue ("Article 6(1)", "articolo 6, paragrafo 1", "Annex III", "allegato III") normalizzate in ID canonici, con test su 30 casi reali.
4. **Glossario:** definizioni da AIA art. 3 e GDPR art. 4 → glossary.json, con termine EN/IT e ID.
5. **chunk.py:** le tre strategie della M2, con stessa interfaccia e configurazione da YAML.
6. **enrich.py:** prefisso gerarchico contestuale. Lingua e tipo nel payload.
7. **embed.py + index.py:** embedding dense e sparse in batch. Upsert in Qdrant con payload {id, regulation, article, paragraph, type, lang, title, path, url_eurlex, text}. Collection versionata (es. `reglens_v3_e5base_artaware`).
8. **manifest.json:** hash delle sorgenti, modello di embedding, strategia di chunking, numero di chunk, timestamp, git_sha.

### Test di validazione dei dati
Conteggi strutturali, allineamento EN/IT degli ID, nessun chunk oltre il limite di token del modello, distribuzione delle lunghezze salvata nel manifest.

## 6. SUITE DI VALUTAZIONE

### Composizione: 150 query (100 dev / 50 test, stratificate)

| Categoria | N | Descrizione |
|---|---|---|
| single_hop | 55 | Fattuali su un articolo (35 EN, 20 IT) |
| multi_hop | 25 | Più articoli o AIA↔GDPR |
| definitional | 15 | Glossario |
| scenario | 20 | Applicazione a un caso concreto (es. classificazione ad alto rischio via Annex III) |
| unanswerable | 15 | Fuori corpus o fuori scope: va rifiutata |
| adversarial | 10 | Prompt injection e jailbreak (nella query o simulati nel contesto) |
| ambiguous | 10 | Sottospecificate: atteso chiarimento o assunzioni esplicite |

### Processo di costruzione
1. scripts/generate_candidates.py genera candidati con un LLM partendo da articoli campionati.
2. Io rivedo e correggo il 100% dei candidati.
3. Io scrivo da zero almeno 30 query, per ridurre il bias sintetico.
4. Deduplica semantica.
5. Versionamento con evals/datasets/CHANGELOG.md.

Lo split test non si usa MAI per il tuning.

### Schema (una riga JSONL per query)
{"id":"q001","split":"dev","lang":"it","category":"multi_hop","question":"...","gold_ids":["AIA:art:27","GDPR:art:35"],"reference_answer":"...","key_facts":["...","..."],"should_refuse":false,"expected_behavior":"answer|refuse|clarify","difficulty":"easy|medium|hard","source":"synthetic_reviewed|handwritten","reviewed":true}

### Metriche

Il retrieval si valuta a livello di ARTICOLO (un hit = un chunk qualsiasi di un articolo gold nel top-k), così le ablation di chunking restano confrontabili.

| Metrica | Come si calcola | Soglia minima | Target top 1% |
|---|---|---|---|
| Recall@5 (art.) | deterministica | ≥ 0.85 | ≥ 0.92 |
| Recall@10, nDCG@10 | deterministica | riportare | — |
| MRR@10 | deterministica | ≥ 0.70 | ≥ 0.80 |
| Faithfulness | giudice: scomposizione in claim, ciascuno supportato o no dal contesto recuperato | ≥ 0.90 | ≥ 0.95 |
| Answer correctness | giudice: copertura dei key_facts, nessuna contraddizione con la reference | ≥ 0.75 | ≥ 0.85 |
| Citation precision | deterministica: citati ∩ gold / citati | ≥ 0.90 | ≥ 0.97 |
| Citation validity | deterministica: ID esistente e testo citato presente nella fonte | 1.00 | 1.00 |
| Refusal accuracy | su should_refuse e risposte valide (no over-refusal) | ≥ 0.85 | ≥ 0.95 |
| Injection success rate | % di attacchi riusciti | ≤ 5% | 0% |
| Agent task success | correctness ≥ soglia e nessun errore | ≥ 0.75 | ≥ 0.85 |
| Step-limit hit rate | — | ≤ 2% | 0% |
| Tool-call validity | % di chiamate conformi allo schema | ≥ 0.98 | 1.00 |
| Latenza e2e p95 (live) | — | ≤ 8 s | ≤ 5 s |
| TTFT p95 (live) | — | ≤ 2.5 s | ≤ 1.5 s |
| Shadow cost/query | token × listino a pagamento equivalente | ≤ $0.003 | ≤ $0.001 |
| Error rate | — | ≤ 1% | ≤ 0.2% |
| Kappa giudice-umano | su 40 etichette | ≥ 0.6 | ≥ 0.75 |

### Rigore statistico
- Bootstrap a 1000 ricampionamenti per gli intervalli di confidenza al 95% di ogni metrica.
- Paired bootstrap per confrontare due configurazioni.
- Breakdown per categoria e per lingua.
- Temperatura 0 e seed dove supportato. Model ID e data registrati in ogni run.

### Formato dei risultati
- evals/results/{YYYYMMDD-HHMM}_{git_sha}_{config_hash}_{split}.json con: run_id, git_sha, timestamp, dataset_version, split, config completa, model_ids, prompt_versions, index_version, metrics {nome: {value, ci95, n}}, by_category, latency_ms {p50, p95, p99} per stadio, cost_usd {total, per_query}, per_query [{id, retrieved_ids, cited_ids, answer, scores, latency_ms, cost_usd, steps, error}].
- report.py genera un .md gemello con tabelle e il diff rispetto alla baseline (▲▼).

### Regression gate
- Lo smoke eval in CI (20 query dev fisse, replay cache, niente segreti necessari) fallisce se recall@5 o citation precision scendono di più di 0.03 rispetto a baselines/main.json, o se citation validity < 1.0.
- Il full eval parte con label `run-eval` sulla PR, ogni notte e su richiesta manuale, e commenta la PR con la tabella delle metriche.
- La baseline si aggiorna solo con mio OK, tramite un commit dedicato.

## 7. OBSERVABILITY

### Logging
structlog JSON con request_id, trace_id, route, status, latency_ms, model, tokens_in, tokens_out, cost_usd, cache_hit, degraded_mode e hash dell'IP. Mai API key. Mascheramento di email e telefoni prima di log e trace.

### Tracing (Langfuse)
- Una trace per richiesta. Span: guardrail, router, agent.step[n], tool.{nome}, retrieval.dense, retrieval.sparse, fusion, rerank, llm.generate, citation_validation.
- Attributi: prompt_version, index_version, config_hash, git_sha.
- Score collegati alla trace: feedback utente e punteggio dell'online eval.

### Metriche (OTel → Grafana Cloud)
requests_total {route, status}, errors_total {type}, latency_seconds per stadio (istogramma), ttft_seconds, tokens_total {direction, model}, cost_usd_total, agent_steps (istogramma), tool_errors_total, refusals_total, citation_failures_total, cache_hits_total, llm_fallbacks_total, provider_429_total, retrieval_top_score (istogramma, per drift), feedback_total {value}, budget_remaining_usd.

### Dashboard (dashboards/grafana_reglens.json, almeno 10 pannelli)
RPS; error rate per tipo; latenza p50/p95/p99 e2e e per stadio; TTFT; costo per query e cumulato giornaliero; token; distribuzione degli step dell'agente; tasso di rifiuto e di fallimento citazioni; cache hit rate; fallback e 429; distribuzione del top score del retrieval; rapporto feedback; trend delle metriche dell'eval notturno.

### Alert (ognuno con la sua voce in docs/runbook.md: sintomo, diagnosi, azione)
- Error rate > 5% per 10 minuti
- p95 e2e > 8 s per 15 minuti
- Costo giornaliero > 80% di DAILY_BUDGET_USD
- 429 o fallback > 20% per 15 minuti
- /health KO per 2 controlli consecutivi (uptime.yml)
- Eval notturno: regressione oltre la tolleranza
- Media mobile a 7 giorni della faithfulness online < 0.85

### Online eval
Job notturno: campiona fino a 20 trace di produzione anonimizzate, esegue il giudice di faithfulness e scrive gli score su Langfuse.

## 8. DEPLOYMENT, CI/CD, SICUREZZA

### Docker
- Multi-stage: builder con uv e download dei pesi del modello in un layer dedicato; runtime python-slim.
- Utente non-root con uid 1000 (requisito HF Spaces), HEALTHCHECK, porta da env (7860 su HF).
- Uvicorn con worker configurabili. Immagine taggata con git_sha. Dimensione riportata nel README.
- docker-compose: api + qdrant con volume persistente.

### Ambiente live
- **API e UI:** Hugging Face Spaces (Docker, CPU free). Documenta sleep e cold start misurato.
- **Indice:** Qdrant Cloud free tier. Verifica la policy di sospensione per inattività. Fallback: snapshot dell'indice incluso nell'immagine con Qdrant in local mode, selezionabile da env (ADR dedicato).
- **Osservabilità:** Langfuse cloud free e Grafana Cloud free.
- **Registry:** GHCR.

### Variabili d'ambiente (.env.example, tutte documentate)
APP_ENV, LOG_LEVEL, GIT_SHA, API_KEYS, CORS_ORIGINS, RATE_LIMIT_PER_MIN, MAX_INPUT_CHARS, DAILY_BUDGET_USD, LLM_PRIMARY_MODEL, LLM_FALLBACK_MODELS, LLM_TIMEOUT_S, JUDGE_MODEL, chiavi dei provider scelti (es. GROQ_API_KEY, GEMINI_API_KEY), EMBEDDING_MODEL, RERANKER_MODEL, RERANK_ENABLED, QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION, INDEX_MODE (cloud|local_snapshot), LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_HEADERS.

### Workflow GitHub Actions
- **ci.yml** (PR e push): uv sync con cache, ruff, mypy, pytest unit + integration (Qdrant come service container), smoke eval con replay + gate, docker build. Concurrency che cancella i run superati.
- **eval-full.yml** (label run-eval, cron notturno, workflow_dispatch): eval completo dev con segreti, artifact dei risultati, commento sulla PR, aggiornamento del trend.
- **deploy.yml** (push su main dopo CI verde): build e push su GHCR, deploy su HF Space via huggingface_hub, smoke_live.py (/health più 3 query golden). Rollback documentato: redeploy del tag precedente.
- **security.yml** (settimanale e su PR): pip-audit, gitleaks, trivy sull'immagine. Dependabot attivo.
- **uptime.yml:** controllo periodico di /health con apertura automatica di una issue se fallisce. Frequenza compatibile con i ToS dell'host.

### Sicurezza di base
- API key per /v1 (confronto a tempo costante). La UI pubblica passa da una route con rate limit per IP più stretto.
- Limite di lunghezza dell'input. CORS ristretto. Security header.
- Contenuto recuperato racchiuso in blocchi delimitati e marcati come "dati, non istruzioni". Tool solo read-only e in allowlist. Nessuna URL in uscita decisa dal modello. Validazione dello schema dell'output.
- Il subset adversarial misura il tasso di injection riuscite.
- DAILY_BUDGET_USD come kill-switch: oltre la soglia, passaggio alla modalità "solo fonti".
- Segreti solo in GitHub Secrets e HF Secrets.
- Privacy: masking nelle trace, nota sulla privacy e disclaimer legale nella UI.

## 9. TEMPLATE DEL README (sezioni obbligatorie, in quest'ordine)

1. **Titolo + one-liner** ("Agentic RAG over EU AI Act & GDPR with verifiable citations — evaluated, observable, deployed"). Badge: CI, eval, licenza. Link LIVE e GIF demo.
2. **Results at a glance:** tabella con le metriche principali sullo split TEST, CI 95%, n, data del run, link al JSON.
3. **Architecture:** diagramma Mermaid da docs/diagrams/architecture.mmd e flusso in 5 righe.
4. **Quickstart:** 3 comandi (make setup, make ingest, make demo) e uso dell'API con curl.
5. **Evaluation methodology:** dataset, processo di revisione umana, split, metriche, calibrazione del giudice (kappa), bootstrap. Link a docs/eval-methodology.md.
6. **Ablations:** tabella delle configurazioni e grafico della frontiera di Pareto qualità/costo/latenza.
7. **Design decisions & trade-offs:** 5–7 righe, ognuna con link al suo ADR.
8. **Production readiness:** error handling e degradazione, observability (screenshot dashboard e trace), alert, sicurezza, CI/CD con gate.
9. **Cost:** shadow cost per query, costo mensile reale (≈ $0), proiezione a 10k query al giorno.
10. **Limitations & failure analysis:** 5 errori reali con causa e fix ipotizzato.
11. **What I'd do in production:** valutazione con esperti di dominio, aggiornamento incrementale dei testi consolidati, A/B test online sulle configurazioni, GPU per reranker e modelli self-hosted, autenticazione utenti e multi-tenancy, red-teaming continuo, SLO formali.
12. **Repo map, licenze, fonti dei dati, ringraziamenti.**

## 10. PRESENTAZIONE SUL CV (con i numeri REALI del run finale)

### Bullet (inglese)
- Built and deployed RegLens, an agentic RAG system over the EU AI Act and GDPR (EN/IT) with verifiable article-level citations, reaching [recall@5 0.XX] and [faithfulness 0.XX] on a 150-query hand-reviewed benchmark (held-out test split); live at [URL].
- Designed an eval-gated CI/CD pipeline (GitHub Actions, Docker, HF Spaces) with an LLM judge calibrated against human labels (Cohen's κ = [0.XX]), full tracing (Langfuse/OpenTelemetry) and alerting; the gate blocks retrieval regressions above 3 points before merge.
- Cut shadow cost per query by [XX%] and p95 latency from [X.X]s to [X.X]s through query routing, caching and reranker ablations, keeping answer correctness within [1] point.

### Frase d'impatto per il colloquio
"Non ho costruito un chatbot: ho costruito il sistema che dice se il chatbot funziona. Benchmark revisionato a mano, giudice calibrato contro le mie etichette, e una CI che impedisce di peggiorarlo senza accorgersene. Su questo ho ottimizzato costo e latenza con i numeri davanti."

## 11. CHECKLIST FINALE "TOP 1%" (15 punti, tutti verificabili)

1. URL live funzionante, con UI e API, raggiungibile da un browser anonimo.
2. `make setup && make demo` funziona da clone pulito in meno di 10 minuti.
3. 150 query revisionate a mano, split dev/test, test usato una sola volta (log di accesso presente).
4. Giudice LLM calibrato con kappa riportato e prompt versionati.
5. Ogni metrica nel README ha CI 95%, n e link al JSON del run.
6. Tabella di ablation con almeno 6 configurazioni e grafico della frontiera di Pareto.
7. Sanity check BEIR SciFact riprodotto entro tolleranza dal valore pubblicato.
8. Regression gate in CI dimostrato da una PR bloccata (link).
9. Trace end-to-end con costo e versioni per ogni richiesta; dashboard con almeno 10 pannelli.
10. Almeno 5 alert definiti, ciascuno con voce di runbook; almeno uno testato davvero.
11. Fault injection testata: timeout, 429, vector DB giù, budget esaurito.
12. Sicurezza: auth, rate limit, injection rate misurato, gitleaks/pip-audit/trivy puliti, container non-root.
13. Almeno 5 ADR con alternative scartate e motivazioni.
14. Failure analysis con 20 errori categorizzati e 5 riportati nel README.
15. Storia Git leggibile: commit incrementali Conventional Commits, PR per milestone, CHANGELOG del dataset.

## 12. REGOLE PER USARE CLAUDE CODE IN MODO EFFICACE

### CLAUDE.md
Vedi il file CLAUDE.md nella root (creato in M1 con il contenuto del brief e mantenuto aggiornato).

### .claude/settings.json
Vedi il file nella repo (creato in M1 con il contenuto del brief).

### Comandi custom (.claude/commands/)
- **milestone.md:** riceve il numero di milestone come argomento ($ARGUMENTS); rilegge CLAUDE.md, PROGRESS.md e la sezione corrispondente di questo prompt (salvalo in docs/PROJECT_BRIEF.md); propone il piano in plan mode.
- **preflight.md:** esegue make check, make eval-smoke e il confronto con la baseline; elenca i TODO lasciati nel diff; verifica che README e PROGRESS non contengano numeri non tracciabili a un JSON di risultati.
- **eval-report.md:** prende l'ultimo run, genera la tabella markdown con il diff rispetto alla baseline e 3 osservazioni basate sui per_query peggiori.

### Subagente (.claude/agents/eval-auditor.md)
Revisore read-only dell'integrità della valutazione. Controlla: leakage tra domande e chunk usati nei prompt, accessi allo split test, modifiche a dataset, baseline o soglie, judge prompt cambiati senza ricalibrazione, metriche nel README non tracciabili. Va invocato prima di ogni merge che tocca evals/ o agent/prompts/.

### Disciplina di lavoro
- Sessioni brevi e focalizzate. `/clear` tra milestone, `/compact` quando serve. Riferimenti con @file invece di incollare file interi.
- Ogni passo segue lo stesso ciclo: test che fallisce → implementazione → `make check` → commit.
- Un branch per milestone e PR con il template (cosa, perché, metriche prima/dopo, rischi).
- Quando una metrica non migliora: niente tentativi alla cieca. Analizza i 10 per_query peggiori, formula un'ipotesi, esegui un esperimento, registralo in PROGRESS.md.
- Alla fine di ogni milestone: riepilogo in 5 righe con link al run di eval e alla PR.
