# Evaluation methodology

Questo documento descrive *come* si misura RegLens. I numeri stanno solo nei file di `evals/results/` e nelle tabelle generate da `evals/report.py`.

## Dataset (`evals/datasets/reglens_v1.jsonl`)

- **Dimensione:** 150 query in EN e IT. Composizione per categoria:

  | Categoria | N | Cosa misura |
  |---|---|---|
  | single_hop | 55 (35 EN / 20 IT) | un fatto in un articolo |
  | multi_hop | 25 | più articoli, anche AIA ↔ GDPR |
  | definitional | 15 | glossario (AIA art. 3, GDPR art. 4) |
  | scenario | 20 | applicazione a un caso concreto |
  | unanswerable | 15 | fuori corpus: va rifiutata |
  | adversarial | 10 | prompt injection, jailbreak, false premesse |
  | ambiguous | 10 | sottospecificata: chiarimento o assunzioni esplicite |

- **Split:** 100 dev / 50 test, campionamento stratificato per categoria (e per lingua nei single_hop) con seed fisso. Lo split test si usa **una sola volta**, con `make eval-final` in M6: `run_eval` rifiuta `--split test` senza `--final` e registra ogni accesso in `evals/results/test_access.log`.
- **Provenienza:**
  - i candidati sono scritti a partire dal testo vigente estratto dal corpus, e ogni `gold_id` esiste in `data/processed/` (controllo automatico);
  - il titolare rivede il 100% dei record (`reviewed: true` solo dopo l'approvazione) e scrive a mano almeno 30 query (`source: handwritten`);
  - finché un record non è revisionato, ogni metrica calcolata su di esso è **preliminare**.
- **Versione:** ogni run registra `dataset_version = <nome>@<sha256[:8]>` del file, quindi qualunque modifica, anche di un solo byte, cambia la versione. Il confronto tra due run (`evals/compare.py`) rifiuta versioni diverse.

## Corpus e unità di valutazione

- **Fonti:** AI Act consolidato al 27.07.2026 (con il Digital Omnibus, Reg. 2026/1744) più i considerando della GU, e GDPR (GU 2016). Dettagli in `data/README.md`.
- **Livello di articolo:** il retrieval si valuta per articolo. I chunk recuperati vengono proiettati sul loro articolo (o considerando, o allegato) e deduplicati mantenendo il primo rank. Lo stesso vale per i gold id: `AIA:art:6:par:2` conta come `AIA:art:6`. In questo modo le strategie di chunking diverse restano confrontabili.

## Metriche di retrieval (deterministiche, `evals/metrics/retrieval.py`)

| Metrica | Definizione |
|---|---|
| recall@k | quota degli articoli gold presenti tra i primi k articoli recuperati |
| MRR@10 | 1 / rank del primo articolo gold entro 10 (0 se assente) |
| nDCG@10 | guadagno `2^rel − 1`, sconto `log2(rank + 1)`; rilevanza binaria per RegLens, graduata per BEIR |

- **Query incluse:** solo quelle con `expected_behavior = answer` e almeno un gold id. Refuse e clarify si valutano in M3 con metriche generative.
- **Lingua per BM25:** BM25 sceglie lo stemmer dalla lingua rilevata dalla query, come in produzione (`query_lang: detect`), non dalla lingua gold.

## Rigore statistico (`evals/metrics/stats.py`)

- **Intervallo di confidenza:** CI 95% bootstrap percentile con 1000 ricampionamenti e seed fisso, per ogni metrica.
- **Confronto tra configurazioni:** paired bootstrap sulle stesse query, che dà Δ, CI 95% di Δ e p-value one-sided (`make compare A=… B=…`).
- **Breakdown:** per categoria e per lingua in ogni file di risultati.
- **Latenza:** p50/p95/p99 per stadio (dense, sparse, fusion, rerank, total). Le latenze misurate con Qdrant embedded sono latenze di sviluppo (ADR-0004).

## Sanity check su benchmark pubblico

- **Benchmark:** BEIR SciFact con BM25 (`make beir`). Riferimento nDCG@10 = 0.665, tolleranza ±0.02 (Thakur et al. 2021, arXiv:2104.08663v4, Tab. 2).
- **Varianti diagnostiche:** senza titolo e senza stemming spiegano lo scostamento. Non vengono mai usate per tarare la configurazione ufficiale (vedi PROGRESS.md).

## Regole di integrità

- Le metriche citate in README o PR devono comparire in un JSON di `evals/results/`.
- Dataset, baseline, soglie e prompt del giudice si cambiano solo con l'OK del titolare, in un commit dedicato con voce nel CHANGELOG.
- Il subagente `eval-auditor` controlla questi punti prima dei merge che toccano `evals/` o i prompt.
