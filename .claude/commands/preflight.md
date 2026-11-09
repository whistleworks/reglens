---
description: Pre-PR checks (check, smoke eval, baseline diff, TODOs, untraceable numbers)
---
Esegui in ordine e riporta un riepilogo a punti (✅/❌):

1. `make check`.
2. `make eval-smoke` (se già implementato in questa milestone, altrimenti segnalalo) e confronto con `evals/baselines/main.json` se esiste.
3. `git diff main...HEAD` → elenca ogni `TODO`, `FIXME`, `XXX` introdotto, con file:riga.
4. Cerca in README.md, docs/PROGRESS.md e nel testo della PR ogni numero che sembra una metrica (es. 0.87, 92%, p95 3.1s). Per ciascuno verifica che compaia in un file di `evals/results/` e riporta il path; segnala come ❌ ogni numero non tracciabile.
5. Verifica che `evals/datasets/`, `evals/baselines/`, soglie e `evals/judge_prompts/` non siano cambiati nel diff, oppure che il cambiamento sia stato approvato esplicitamente (chiedimelo se non sei sicuro).
6. Nessun segreto nel diff (pattern di chiavi, `.env`).
