# RegLens — istruzioni per Claude Code
## Progetto
Agentic RAG su EU AI Act + GDPR (EN/IT) con eval, tracing e deploy. Dettagli: docs/architecture.md. Stato: docs/PROGRESS.md. Brief completo: docs/PROJECT_BRIEF.md.
## Comandi
make setup | make check (lint+typecheck+test, OBBLIGATORIO prima di ogni commit) | make ingest | make eval SPLIT=dev | make eval-smoke | make serve
## Regole
- Una milestone alla volta; plan mode e approvazione prima del codice.
- Test con il codice; mypy --strict su src/; niente print, solo structlog; config solo da config.py.
- Conventional Commits, un commit per passo.
- NON toccare evals/datasets/, evals/baselines/, soglie e judge prompt calibrati senza OK esplicito.
- NON usare lo split test (solo `make eval-final`, solo in M6).
- Mai inventare metriche: solo numeri da evals/results/.
- Mai segreti nel repo; .env è ignorato.
- ID canonici: vedi src/reglens/ids.py.
- Prompt in src/reglens/agent/prompts/ con header di versione; bump di versione a ogni modifica.
## Corpus (decisione M1, vedi ADR-0001 e data/README.md)
- AI Act: articoli e allegati dal consolidato 02024R1689-20260727 (incluso Digital Omnibus, Reg. 2026/1744); considerando dalla GU originale 32024R1689.
- GDPR: GU originale 32016R0679.
- Download via Cellar (publications.europa.eu) con content negotiation: l'HTML di EUR-Lex è dietro challenge WAF.
## Fine sessione
Aggiorna docs/PROGRESS.md: fatto, metriche attuali con path del run, problemi aperti, prossimo passo.
