"""Quick look at retrieval: which articles does each retriever find for a question?

    PYTHONPATH=. uv run python scripts/ask.py "Quali pratiche di IA sono vietate?" [--lang it]

M1 has no answer generation yet (that is M3): this only shows the retrieved sources.
"""

from __future__ import annotations

import argparse
import json
import sys

from evals.metrics.retrieval import dedup
from reglens.config import get_settings
from reglens.ingestion.embed import FastEmbedBM25, FastEmbedDense
from reglens.retrieval.dense import DenseRetriever
from reglens.retrieval.qdrant import Hit, make_client
from reglens.retrieval.sparse import SparseRetriever


def top_articles(hits: list[Hit], n: int) -> list[Hit]:
    first: dict[str, Hit] = {}
    for hit in hits:
        first.setdefault(hit.article_id, hit)
    return [first[a] for a in dedup(h.article_id for h in hits)][:n]


def show(title: str, hits: list[Hit]) -> None:
    out = [f"\n=== {title} ==="]
    for rank, hit in enumerate(hits, start=1):
        p = hit.payload
        snippet = " ".join(str(p["text"]).split())[:160]
        out.append(f"{rank}. {p['title']}  [{hit.article_id}]  score={hit.score:.3f}")
        out.append(f"   {snippet}…")
        out.append(f"   {p['url_eurlex']}")
    sys.stdout.write("\n".join(out) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--lang", choices=["en", "it"], default="it")
    parser.add_argument("-n", type=int, default=5)
    args = parser.parse_args()

    settings = get_settings()
    index = json.loads((settings.processed_dir / "manifest.json").read_text())["index"]
    client = make_client(settings)
    bm25 = SparseRetriever(client, index["collection"], FastEmbedBM25(index["sparse_model"]))
    dense = DenseRetriever(client, index["collection"], FastEmbedDense(index["dense_model"]))

    sys.stdout.write(f"\nDomanda: {args.question}\n")
    show(
        "BM25 (parole chiave)",
        top_articles(bm25.search(args.question, 50, query_lang=args.lang), args.n),
    )
    show("Dense e5 (significato)", top_articles(dense.search(args.question, 50), args.n))


if __name__ == "__main__":
    main()
