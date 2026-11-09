# ADR-0001 — Stack e limiti dei free tier

- **Stato:** accettato (con una decisione aperta: hosting, da chiudere in M5)
- **Data:** 2026-11-09
- **Autori:** Alessio Fischetti (decisioni), Claude Code (ricerca e stesura)

## Contesto

RegLens deve girare a costo reale ≈ $0, essere riproducibile e mostrare scelte motivate. I free tier cambiano spesso: questo ADR registra **cosa è stato verificato, dove e quando**. Ogni valore qui sotto è stato letto il 2026-11-09. Dove la fonte ufficiale non pubblica i numeri, lo dichiariamo invece di stimarli.

## Decisione

| Area | Scelta | Motivazione |
|---|---|---|
| Linguaggio e packaging | Python 3.12 + uv (lockfile `uv.lock`) | install veloci e lockfile cross-platform affidabile; poetry/pip scartati (più lenti, risoluzione meno deterministica) |
| API | FastAPI + Uvicorn (M4) | async nativo, OpenAPI automatica, SSE; Flask scartato |
| Gateway LLM | LiteLLM (M3) | un'interfaccia sola sopra più provider gratuiti, con fallback; SDK diretto scartato (lock-in) |
| Generatore (ipotesi per M3) | Groq `openai/gpt-oss-120b` | il modello più capace sul free tier Groq, con tool calling |
| Giudice (ipotesi per M3) | Gemini `gemini-3.8-flash` | famiglia diversa dal generatore (riduce il self-preference bias), free tier |
| Fallback LLM (ipotesi per M3) | Groq `qwen/qwen3.8-27b` → Gemini Flash-Lite → OpenRouter `:free` | quote separate per modello e per provider |
| Embedding dense | `intfloat/multilingual-e5-large` via FastEmbed/ONNX su CPU (baseline M1; ablation in M2 contro e5-small/base e bge-m3) | multilingue EN/IT, licenza MIT, nessun costo API |
| Sparse | BM25 tramite vettori sparsi Qdrant (`Qdrant/bm25`, Apache-2.0, modifier IDF) | ibrido nativo nello stesso DB; Elasticsearch scartato (un servizio in più) |
| Vector DB | Qdrant: Docker in dev, Qdrant Cloud free in prod, snapshot nell'immagine come fallback | ibrido dense+sparse nativo; pgvector (ibrido meno nativo), Chroma (meno maturo per prod) e Pinecone (chiuso) scartati |
| Reranker (opzionale, M2) | `BAAI/bge-reranker-v2-m3` (Apache-2.0, multilingue, ~0.6B parametri) | licenza permissiva; si attiva solo se l'ablation giustifica la latenza su CPU |
| Tracing | Langfuse Cloud Hobby + OpenTelemetry (M4) | free senza carta; LangSmith scartato (centrato su LangChain); Arize Phoenix è un'alternativa valida (self-host) |
| Metriche e alert | OTel → Grafana Cloud Free (M4) | free senza carta; Prometheus self-hosted scartato (nessun hosting gratuito stabile) |
| Registry e CI | GHCR + GitHub Actions | gratuiti per repository pubblici |
| Hosting | **APERTO, decisione in M5** (vedi sotto) | — |

## Free tier verificati (2026-11-09)

### LLM

| Provider | Stato free | Limiti verificati | Fonte |
|---|---|---|---|
| **Groq** | ✅ Free plan | `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`: 30 RPM, 1K RPD, 8K TPM, 200K TPD ciascuno. Limiti per organizzazione, non per chiave. La pagina dice che i valori esatti dell'account sono nella console. | https://console.groq.com/docs/rate-limits |
| **Gemini (Google AI Studio)** | ✅ Free tier su `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite` e altri | RPM/RPD **non pubblicati** nella documentazione: si leggono solo in AI Studio (https://aistudio.google.com/rate-limit). `gemini-2.5-flash` e `gemini-2.5-pro` sono deprecati e dal 2026-12-01 vengono reindirizzati. **I dati del free tier sono usati per migliorare i prodotti Google.** | https://aistudio.google.com/docs/pricing, https://aistudio.google.com/docs/rate-limits |
| **OpenRouter** (`:free`) | ✅ | 20 RPM; 50 RPD con meno di $10 di credito acquistato, 1000 RPD con almeno $10 | https://openrouter.ai/docs/api-reference/limits |
| **Mistral** (piano free / "Experiment") | ⚠️ esiste, ma i limiti non sono pubblicati | Limiti visibili solo dalla console. Le richieste del piano free possono essere usate per il training. | https://help.mistral.ai/en/articles/450104-how-can-i-try-the-api-for-free-with-the-experiment-plan, https://docs.mistral.ai/deployment/laplateforme/tier |
| **Cerebras** | ❌ niente free tier permanente | Da luglio 2026 c'è solo un trial da $5 con carta, che scade dopo 30 giorni (fonti secondarie che citano la documentazione ufficiale). **Escluso dalla catena di fallback.** | https://www.developersdigest.tech/models/free-api/cerebras, https://www.usagepricing.com/blueprint/activity/cerebras-2026-07-21-free-tier-credit-trial |

**Implicazioni per M3:**
- Il TPM del free tier Groq (8K) è il collo di bottiglia per l'agente a più step e per gli eval completi. Servono cache su disco, throttling lato client e fallback.
- I numeri effettivi del nostro account vanno letti nelle console all'inizio della M3 e annotati qui.
- La privacy pesa: Gemini (free) e Mistral (free) possono usare i dati per migliorare o addestrare i modelli. Le query degli utenti sulla demo vanno dichiarate nella nota privacy della UI (M4).

### Infrastruttura

| Servizio | Limiti verificati | Fonte |
|---|---|---|
| **Qdrant Cloud Free** | 1 nodo, 1 GB RAM, 0.5 vCPU, 4 GB disco (circa 1M vettori a 768 dimensioni). Nessuna carta. **Cluster sospeso dopo 1 settimana di inattività, cancellato dopo altre 4** se non viene riattivato. | https://qdrant.tech/documentation/cloud/create-cluster/ |
| **Langfuse Cloud Hobby** | 50k unità al mese (trace, osservazioni e score), 30 giorni di dati, 2 utenti, nessuna carta | https://langfuse.com/pricing |
| **Grafana Cloud Free** | 10k serie di metriche attive al mese, 50 GB di log, 50 GB di trace, 14 giorni di retention, 3 utenti attivi, nessuna carta. Limiti dell'alerting non dettagliati in pagina. | https://grafana.com/pricing/ |
| **Hugging Face Spaces** | La pagina prezzi indica CPU Basic (2 vCPU, 16 GB) come FREE, ma elenca "Host ZeroGPU, Gradio & Docker Spaces" tra i benefit di **PRO ($9/mese)**. Report della community da luglio 2026, senza conferma ufficiale, dicono che i nuovi Space Docker e Gradio su CPU Basic richiedono PRO ("Static Spaces are free for everyone, but hosting Gradio and Docker Spaces on free cpu-basic requires a PRO subscription"). Su CPU Basic lo Space va in sleep dopo 48 ore di inattività. | https://huggingface.co/pricing, https://discuss.huggingface.co/t/official-community-complaint-revert-free-cpu-basic-spaces-and-remove-anti-developer-sdk-restrictions/177703, https://huggingface.co/docs/huggingface_hub/package_reference/space_runtime |

**Implicazioni:**
- **Qdrant Cloud:** la sospensione per inattività rende obbligatori due accorgimenti: (a) il fallback `INDEX_MODE=local_snapshot`, (b) uptime e online eval che generano traffico reale. La frequenza va scelta in M5.
- **Langfuse:** 50k unità al mese bastano per circa 1–2k richieste tracciate al mese, con circa 20–30 osservazioni per richiesta. Gli eval completi vanno tracciati in sampling.

### Fonti del corpus
- La pagina HTML di EUR-Lex (`eur-lex.europa.eu/legal-content/...`) risponde **HTTP 202 con body vuoto** a client non browser (challenge WAF, test del 2026-11-09).
- Il repository Cellar dell'Ufficio delle pubblicazioni risponde **200** con content negotiation:

  ```
  GET http://publications.europa.eu/resource/celex/{CELEX}
  Accept: application/xhtml+xml
  Accept-Language: eng|ita
  ```

- Il dettaglio è in `data/README.md`.

### Benchmark di sanity
- BEIR SciFact, BM25: nDCG@10 = 0.665 secondo fonti secondarie (tabella Vespa "BM25 from BEIR Paper", riepilogo Emergent Mind).
- Il valore va verificato sulla tabella del paper (Thakur et al., 2021, arXiv:2104.08663) prima di usarlo come target (M1, passo 9).

## Decisione aperta: hosting (da chiudere in M5)

Il brief prevedeva HF Spaces Docker su CPU free, ma oggi quella opzione non è garantita. Opzioni registrate:

| Opzione | Pro | Contro |
|---|---|---|
| HF Spaces con PRO ($9/mese) | stesso piano del brief, 16 GB di RAM | costo reale non più ≈ $0 (va dichiarato nel README) |
| Google Cloud Run | free tier permanente, scale-to-zero | richiede la carta; cold start lungo con i modelli ONNX caricati; il free tier copre circa 50 ore al mese a 2 GiB (stima dai limiti riportati, da riverificare) |
| Oracle Cloud Always Free (VM ARM) | molta RAM | VM da gestire, carta richiesta, limiti ridotti a giugno 2026 secondo fonti secondarie |
| Render free (512 MB) con modello di embedding small | gratis | RAM insufficiente per e5-large e il reranker; spin-down dopo 15 minuti |

**Conseguenza già da M1:** in M2 l'ablation sugli embedding include modelli small/base, così da avere numeri sul costo qualità/RAM se la scelta finale cade su un host con poca memoria.

## Conseguenze
- Cerebras esce dalla catena LLM. Il brief lo citava; la deviazione è registrata qui.
- Le quote di Gemini e Mistral vanno lette in console all'inizio della M3 e aggiunte a questo ADR.
- I limiti dei free tier vanno riverificati a ogni milestone che li usa (M3 LLM, M4 osservabilità, M5 hosting).
