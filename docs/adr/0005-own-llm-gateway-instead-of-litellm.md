# ADR-0005 — Gateway LLM proprio (httpx, API OpenAI-compatibili) al posto di LiteLLM

- **Stato:** accettato
- **Data:** 2026-11-20
- **Sostituisce:** la riga "LLM: LiteLLM" del brief (sezione 2) e di ADR-0001

## Contesto
- Il brief prevedeva LiteLLM come gateway multi-provider. Verificando la dipendenza prima di aggiungerla (2026-11-20), sono emersi due incidenti di supply chain nel 2026:
  - **marzo 2026:** versioni 1.82.7 e 1.82.8 pubblicate su PyPI con un credential stealer, rimaste online circa 40 minuti. Versione pulita: 1.82.6; release pulita successiva: 1.83.0. Fonti: https://docs.litellm.ai/blog/security-update-march-2026, https://snyk.io/articles/poisoned-security-scanner-backdooring-litellm
  - **ottobre 2026:** versione 1.107.0 malevola su PyPI e nei registry di container, dopo la compromissione di account dei maintainer; ultima release pulita indicata: 1.106.2. Fonti: https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-docker.md, https://bleepingcomputer.com/news/security/litellm-release-pipeline-hacked-to-distribute-info-stealer-malware, https://www.mend.io/?p=26750
- RegLens gestisce chiavi API di provider LLM, Qdrant e Langfuse: un malware che ruba credenziali nella dipendenza più vicina a quelle chiavi è il rischio peggiore possibile.
- I provider scelti in ADR-0001 (Groq, Gemini, OpenRouter) espongono tutti un endpoint **OpenAI-compatibile** `/chat/completions` con tool calling.

## Decisione
Un gateway proprio in `src/reglens/llm/`, senza SDK dei provider, basato su `httpx` (già una dipendenza) e organizzato così:
- `client.py`: client OpenAI-compatibile con modelli Pydantic per richiesta e risposta, tool calling, timeout, classificazione degli errori (429, 5xx e timeout ritentabili; gli altri 4xx no);
- `fallback.py`: retry con backoff esponenziale e jitter (tenacity), circuit breaker per provider, catena di fallback;
- `cache.py`: cache su disco indicizzata dallo sha256 della richiesta canonica, che è anche la *replay cache* per lo smoke eval in CI senza segreti;
- `pricing.py` e `budget.py`: conteggio token, costo ombra con listino datato, kill-switch giornaliero.

## Alternative scartate
- **LiteLLM con versione pinnata (1.106.2):** riduce il rischio ma lascia una dipendenza grande, con una superficie d'attacco ampia e una catena di rilascio compromessa due volte in otto mesi.
- **SDK ufficiali di ogni provider:** tre dipendenze in più e lock-in, con un'interfaccia diversa per ciascuno.
- **Framework di agenti (LangChain, LlamaIndex):** esclusi già dal brief.

## Conseguenze
- Circa 300 righe di codice da mantenere, interamente testate con un trasporto finto (`httpx.MockTransport`), senza rete né chiavi.
- Aggiungere un provider OpenAI-compatibile richiede solo configurazione. Uno non compatibile richiederebbe un adattatore: nessuno dei provider scelti oggi.
- Il percorso di migrazione resta aperto: tutto il codice usa il protocollo `ChatClient`, quindi passare a LiteLLM o a un SDK dopo un audit richiede solo un altro adattatore.
- Il lockfile `uv.lock` resta obbligatorio (`uv sync --frozen` in CI) e Dependabot e pip-audit sono pianificati in M5.
