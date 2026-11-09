---
description: Start milestone $ARGUMENTS in plan mode
---
Siamo alla Milestone $ARGUMENTS.

1. Leggi @CLAUDE.md e @docs/PROGRESS.md.
2. Leggi in @docs/PROJECT_BRIEF.md la sezione 4 per la milestone $ARGUMENTS, più le sezioni del brief che quella milestone richiama.
3. Verifica cosa resta aperto dalla milestone precedente (problemi aperti in PROGRESS.md).
4. Entra in plan mode e proponi un piano a passi numerati (max 10) con file toccati, test previsti e rischi.
5. Se servono servizi esterni, verifica online i limiti attuali e annota fonte e data.
6. Non scrivere codice finché non approvo. Dopo l'approvazione: TDD, `make check` a ogni passo, un commit per passo, aggiornamento di PROGRESS.md a fine sessione.
