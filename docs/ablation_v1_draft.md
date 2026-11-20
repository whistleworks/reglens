| config | setup | recall@5 (CI95) | recall@10 (CI95) | mrr@10 (CI95) | ndcg@10 (CI95) | n | latency ms p50/p95 | run |
|---|---|---|---|---|---|---|---|---|
| `bm25` | bm25 · paragraph | 0.565 [0.47–0.66] | 0.749 [0.67–0.83] | 0.525 [0.44–0.61] | 0.540 [0.47–0.61] | 83 | 17 / 19 | [json](evals/results/20261120-0844_f8c77a2c5c4f_8498a86c_dev.json) |
| `dense` | dense · paragraph | 0.747 [0.66–0.83] | 0.843 [0.78–0.90] | 0.657 [0.58–0.73] | 0.672 [0.60–0.74] | 83 | 27 / 44 | [json](evals/results/20261120-0844_f8c77a2c5c4f_d1e4efd9_dev.json) |
| `hybrid` | hybrid · paragraph | 0.675 [0.59–0.76] | 0.805 [0.73–0.87] | 0.621 [0.54–0.70] | 0.627 [0.55–0.70] | 83 | 44 / 57 | [json](evals/results/20261120-0845_f8c77a2c5c4f_503dc7f5_dev.json) |
| `hybrid_article_hier` | hybrid · article · +hierarchy | 0.755 [0.68–0.83] | 0.825 [0.75–0.89] | 0.628 [0.54–0.71] | 0.647 [0.57–0.71] | 83 | 47 / 65 | [json](evals/results/20261120-0852_f8c77a2c5c4f_2e809755_dev.json) |
| `hybrid_rerank` | hybrid · paragraph · +rerank | 0.751 [0.67–0.83] | 0.829 [0.77–0.90] | 0.578 [0.50–0.65] | 0.622 [0.56–0.69] | 83 | 5265 / 6101 | [json](evals/results/20261120-0852_f8c77a2c5c4f_38a42267_dev.json) |
| `hybrid_article` | hybrid · article | 0.682 [0.59–0.77] | 0.789 [0.71–0.86] | 0.559 [0.48–0.64] | 0.576 [0.51–0.64] | 83 | 44 / 66 | [json](evals/results/20261120-0852_f8c77a2c5c4f_686e5c4a_dev.json) |
| `dense_article` | dense · article | 0.754 [0.68–0.83] | 0.820 [0.75–0.89] | 0.554 [0.48–0.63] | 0.592 [0.53–0.66] | 83 | 27 / 46 | [json](evals/results/20261120-0852_f8c77a2c5c4f_c54c1b05_dev.json) |
| `hybrid_hier` | hybrid · paragraph · +hierarchy | 0.747 [0.66–0.83] | 0.825 [0.76–0.89] | 0.715 [0.63–0.79] | 0.706 [0.63–0.78] | 83 | 55 / 71 | [json](evals/results/20261120-0852_f8c77a2c5c4f_caaefbff_dev.json) |
| `hybrid_fixed` | hybrid · fixed | 0.610 [0.52–0.70] | 0.703 [0.62–0.79] | 0.461 [0.38–0.54] | 0.488 [0.42–0.56] | 83 | 45 / 62 | [json](evals/results/20261120-0852_f8c77a2c5c4f_fd04c820_dev.json) |

Dataset: reglens_v1@cdebd13e. Split: dev.
