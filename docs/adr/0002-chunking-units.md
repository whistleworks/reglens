# ADR-0002 — Chunking: paragrafi, con definizioni e punti degli allegati come unità

- **Stato:** accettato (su dev non ancora revisionato: da riconfermare dopo la revisione)
- **Data:** 2026-11-20
- **Dati:** `reglens_v1@cdebd13e`, dev, 83 query con target. Run in `evals/results/`.

## Contesto
Il brief chiede tre strategie di chunking (fixed 512 con overlap, article-aware, paragraph-level con il contesto del parent) e l'arricchimento con il percorso gerarchico, da confrontare con un'ablation. Il retrieval si valuta per articolo, così le strategie restano confrontabili.

## Evidenze (ibrido, stessi pesi; recall@5 / MRR@10)

| Strategia | Arricchimento | recall@5 | MRR@10 | Run |
|---|---|---|---|---|
| fixed (500 token, overlap 64) | — | 0.610 | 0.461 | `20261120-0852_f8c77a2c5c4f_fd04c820_dev` |
| article | — | 0.682 | 0.559 | `20261120-0852_f8c77a2c5c4f_686e5c4a_dev` |
| paragraph | — | 0.675 | 0.621 | `20261120-0845_f8c77a2c5c4f_503dc7f5_dev` |
| article | hierarchy | 0.755 | 0.628 | `20261120-0852_f8c77a2c5c4f_2e809755_dev` |
| paragraph | hierarchy | 0.747 | 0.715 | `20261120-0852_f8c77a2c5c4f_caaefbff_dev` |
| paragraph, considerando esclusi, BM25 0.5 | hierarchy | 0.831 | 0.815 | `20261120-0854_f8c77a2c5c4f_b6efad2b_dev` |
| **paragraph_defs** (E3) | hierarchy | 0.868 | 0.852 | `20261120-0910_28c7d8af9d18_164cbd59_dev` |
| **units** (E4) | hierarchy | 0.868 | 0.858 | `20261120-0939_28c7d8af9d18_a8537e7c_dev` |

## Diagnosi che hanno guidato le scelte
- **Fixed:** è la strategia peggiore. Le finestre ignorano i confini giuridici e vengono attribuite all'articolo da cui partono.
- **Arricchimento gerarchico** (es. "GDPR > Capo III > Articolo 17 … > par. 1" prima del testo): migliora tutte le strategie. Un paragrafo isolato ("Paragraph 1 shall not apply…") non dice di cosa parla.
- **E3, definizioni:** la categoria definitional era a recall@5 0.50, perché l'art. 3 AIA (70 definizioni) e l'art. 4 GDPR (26) finivano in blocchi da 500 token con decine di definizioni insieme. Una definizione per chunk:
  - recall@5 +0.036 (CI [0.000, +0.084], p = 0.047) e MRR +0.038 (p = 0.007) rispetto alla stessa configurazione senza E3;
  - la categoria definitional sale a 0.90.
- **E4, punti degli allegati come unità:** **neutro** sulle metriche dev (recall@5 invariato, MRR +0.006, p = 0.37). Però risolve il caso golden "Are AI systems for recruitment high-risk?", che ora trova `AIA:annex:III:pt:4` al primo posto invece di nessun allegato tra i primi 5. Inoltre rende citabile il punto preciso dell'allegato.

## Decisione
- **Strategia servita:** `units` = un chunk per paragrafo e per considerando, una definizione per chunk (AIA art. 3, GDPR art. 4), un chunk per punto di primo livello degli allegati, con arricchimento gerarchico (`configs/serving.yaml`).
- **Altre strategie:** restano nel codice e nell'ingestion per le ablation.

## Conseguenze
- 3090 chunk (EN + IT) contro i 2814 di paragraph; indicizzazione di circa 16 minuti su CPU.
- Le citazioni possono puntare a `GDPR:art:4:def:11` o a `AIA:annex:III:pt:4`, non solo all'articolo.
- Limite: la categoria scenario resta debole (recall@5 0.68). Ipotesi per il prossimo esperimento: le domande-scenario descrivono casi concreti con parole diverse dal testo di legge. Da provare la riscrittura o espansione della query tramite LLM (M3), da misurare.
