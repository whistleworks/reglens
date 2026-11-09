---
description: Report on the latest eval run vs baseline
---
1. Trova il file più recente in `evals/results/*.json` (o usa $ARGUMENTS se è un path).
2. Genera una tabella markdown: metrica | valore | CI95 | n | baseline | Δ (▲/▼). Se `evals/baselines/main.json` non esiste, ometti le colonne baseline e dillo.
3. Aggiungi il breakdown per categoria e per lingua se presente.
4. Analizza i 10 `per_query` peggiori e scrivi 3 osservazioni concrete (con id delle query), ognuna con un'ipotesi verificabile e il prossimo esperimento.
5. Non citare numeri che non sono nel JSON.
