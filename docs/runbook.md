# Runbook

Ogni alert in `dashboards/alerts.yaml` ha una voce qui con **sintomo, diagnosi e azione**. I log sono JSON (structlog) con `request_id`. Le trace stanno su Langfuse e le metriche su `/metrics` o su Grafana Cloud.

## high-error-rate
Error rate sopra il 5% per 10 minuti.

- **Sintomo:** risposte 5xx o `errors_total` in crescita.
- **Diagnosi:**
  1. Pannello "Error rate by type": quale `type`?
     - `retrieval_unavailable` vuol dire indice irraggiungibile (vedi *health-ko*);
     - `http_500` vuol dire bug: cercare `api.unhandled_error` nei log.
  2. Prendere un `request_id` dai log e aprire la trace corrispondente su Langfuse.
- **Azione:**
  - se il problema segue un deploy, fare rollback (`gh workflow run deploy.yml` sul tag precedente, oppure puntare lo Space al tag `ghcr.io/<repo>:<sha>` precedente);
  - se l'indice è giù, vedi *health-ko*.

## slow-p95
p95 end-to-end sopra 8 s per 15 minuti.

- **Sintomo:** UI lenta, `latency_seconds` p95 alto.
- **Diagnosi:**
  1. Trace lente: quale span domina?
     - `llm.generate` con molti step indica che il router manda troppo all'agente;
     - `rerank` indica CPU satura;
     - `retrieval.dense` indica il cold start del modello.
  2. Pannello "Agent steps distribution".
- **Azione:**
  - disattivare il reranker (`RERANK_ENABLED=false`): le prestazioni degradano in modo controllato;
  - ridurre `AGENT_MAX_STEPS`;
  - verificare le quote del provider (vedi *provider-throttling*).

## budget
Costo giornaliero oltre l'80% di `DAILY_BUDGET_USD`.

- **Sintomo:** `budget_remaining_usd` basso. Al 100% l'API passa da sola alla modalità "solo fonti".
- **Diagnosi:** pannello "Cost per query", da confrontare con il traffico. Abuso? Controllare `requests_total` per route e i 429 del rate limit.
- **Azione:**
  - abbassare `RATE_LIMIT_PER_MIN` o rendere temporaneamente obbligatoria la chiave per la UI;
  - accettare la modalità "solo fonti" fino a mezzanotte UTC, quando il contatore si azzera.

## provider-throttling
429 o fallback sopra il 20% per 15 minuti.

- **Sintomo:** molte risposte con `mode=sources_only`, `provider_429_total` in crescita.
- **Diagnosi:**
  - limiti del free tier (Groq: 30 RPM, 1K RPD, 8K TPM su gpt-oss-120b; ADR-0001);
  - verificare la console del provider.
- **Azione:**
  - attendere il reset (RPM al minuto, RPD a mezzanotte);
  - aggiungere un fallback in `LLM_FALLBACK_MODELS`;
  - ridurre i token per richiesta (`AGENT_MAX_TOKENS`).

## health-ko
`/health` KO per 2 controlli consecutivi (`uptime.yml` apre una issue).

- **Sintomo:** issue "Live /health failing".
- **Diagnosi:**
  - lo Space dorme o è in build? Controllare la pagina dello Space; il cold start atteso è registrato in M5;
  - log del container: `docker logs` o la pagina Logs dello Space;
  - `INDEX_MODE`:
    - `local_snapshot` non dipende da servizi esterni;
    - `cloud` può fallire perché il cluster Qdrant Cloud free viene sospeso dopo 1 settimana di inattività (ADR-0001).
- **Azione:**
  - riavviare lo Space;
  - riattivare il cluster dalla console Qdrant, oppure passare a `INDEX_MODE=local_snapshot`;
  - chiudere la issue con la causa.

## eval-regression
L'eval notturno peggiora oltre la tolleranza rispetto alla baseline.

- **Sintomo:** job `eval-full` rosso, oppure `/eval-report` con ▼ oltre 0.03.
- **Diagnosi:**
  1. `make compare A=evals/baselines/main.json B=<run>`.
  2. I 10 `per_query` peggiori: retrieval miss? citazioni? rifiuti?
  3. Cosa è cambiato: commit, versione dei prompt, modello del provider (registrato in `model_ids`).
- **Azione:**
  - revert della modifica responsabile;
  - se il provider ha cambiato modello, aprire un'issue e ricalibrare il giudice se coinvolto.
  - **Non aggiornare la baseline senza l'OK del titolare.**

## online-faithfulness
Media mobile a 7 giorni della faithfulness online sotto 0.85.

- **Sintomo:** gli score dell'online eval su Langfuse calano.
- **Diagnosi:**
  - campionare le trace con score basso: risposte senza supporto nelle fonti?
  - sono cambiate le domande degli utenti (drift)? Pannello "Retrieval top score".
- **Azione:**
  - rafforzare il prompt di sistema (con bump di versione);
  - aggiungere al dataset le domande reali che falliscono, solo dopo la revisione del titolare.
