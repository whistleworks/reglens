# ADR-0003 — Retrieval ibrido con RRF pesato, considerando esclusi, nessun reranker

- **Stato:** accettato (su dev non ancora revisionato: da riconfermare dopo la revisione)
- **Data:** 2026-11-20
- **Dati:** dataset `reglens_v1@cdebd13e`, split dev, 83 query con target, CI 95% bootstrap, confronti con paired bootstrap (`make compare`). I run citati sono in `evals/results/`.

## Contesto
Il brief chiede un retrieval ibrido (dense + BM25, RRF) con un reranker cross-encoder opzionale, da attivare "solo se l'ablation giustifica la latenza su CPU".

## Evidenze (recall@5 / MRR@10)

| Config | recall@5 | MRR@10 | Run |
|---|---|---|---|
| BM25 (paragraph) | 0.565 | 0.525 | `20261120-0844_f8c77a2c5c4f_8498a86c_dev` |
| Dense e5-large (paragraph) | 0.747 | 0.657 | `20261120-0844_f8c77a2c5c4f_d1e4efd9_dev` |
| Hybrid RRF (paragraph) | 0.675 | 0.621 | `20261120-0845_f8c77a2c5c4f_503dc7f5_dev` |
| Hybrid + hierarchy | 0.747 | 0.715 | `20261120-0852_f8c77a2c5c4f_caaefbff_dev` |
| + considerando esclusi | 0.825 | 0.801 | `20261120-0853_f8c77a2c5c4f_399fb4a7_dev` |
| + BM25 pesato 0.5 | 0.831 | 0.815 | `20261120-0854_f8c77a2c5c4f_b6efad2b_dev` |
| + definizioni come unità (ADR-0002) | 0.868 | 0.852 | `20261120-0910_28c7d8af9d18_164cbd59_dev` |
| … + reranker bge-reranker-v2-m3-int8 (top 20) | 0.837 | 0.833 | `20261120-0916_28c7d8af9d18_050742e1_dev` |

**Effetti delle singole scelte:**
- **Ibrido con pesi uguali:** peggiora rispetto al solo dense (0.675 contro 0.747), perché il BM25 è molto più debole. Diventa utile solo dopo l'arricchimento gerarchico.
- **Esclusione dei considerando:** è l'effetto singolo più grande. Prima occupavano il 44% delle posizioni top-5 (184 su 415), mentre i gold sono quasi sempre articoli o allegati.
- **BM25 pesato 0.5:** effetto piccolo e non significativo da solo; lo teniamo perché non peggiora nessuna metrica.
- **Reranker:** **peggiora** recall@5 di −0.030 (CI [−0.056, −0.010], p = 1.000 per "il reranker è meglio"). La latenza p50 del retrieval passa da 67 ms a 4480 ms (p95 da 82 ms a 6302 ms) su CPU, Mac M-series, ONNX INT8.

## Decisione
- **Configurazione servita** (`configs/serving.yaml`): ibrido dense e5-large + BM25, con
  - RRF k = 60 e pesi dense 1.0, BM25 0.5;
  - arricchimento gerarchico;
  - considerando esclusi dal retrieval;
  - **nessun reranker**.
- **Considerando ancora disponibili:** restano indicizzati. Il filtro è di configurazione (`exclude_types`), quindi si possono riattivare per domande interpretative in futuro.

## Alternative scartate
- **Reranker attivo:** peggiora la qualità e aumenta la latenza di circa 67 volte.
- **Dense puro:** a parità di chunking, l'ibrido con l'arricchimento ha un MRR migliore (+0.058, p = 0.043).
- **RRF con pesi uguali:** stesso recall, MRR inferiore.

## Conseguenze
- **Latenza:** su CPU il retrieval resta sotto i 100 ms p95 in modalità embedded (non rappresentativa del server).
- **Da rivalutare:** la scelta sul reranker va riconsiderata con un reranker più adatto al dominio legale o con una GPU, e comunque su un dataset revisionato.
- **Prerequisito per i numeri ufficiali:** dopo la revisione del dataset da parte del titolare tutta la tabella va rieseguita. I numeri qui sopra sono preliminari.
