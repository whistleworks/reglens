"""Export one collection into a fresh embedded-Qdrant directory (the `local_snapshot` index).

    QDRANT_URL=path:qdrant_local uv run python scripts/export_index.py \
        --collection reglens_7d05c4cd_e5large_paragraph --out index_snapshot

The output directory is copied into the Docker image; with INDEX_MODE=local_snapshot the
API serves from it in-process, so the live demo does not depend on Qdrant Cloud (whose
free clusters are suspended after one week of inactivity, ADR-0001).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from qdrant_client import QdrantClient, models

from reglens.config import get_settings
from reglens.ingestion.index import PAYLOAD_INDEXES
from reglens.retrieval.qdrant import make_client


def export(source: QdrantClient, name: str, out: Path, batch: int = 256) -> int:
    if out.exists():
        shutil.rmtree(out)
    target = QdrantClient(path=str(out))
    info = source.get_collection(name)
    target.create_collection(
        name,
        vectors_config=info.config.params.vectors,
        sparse_vectors_config=info.config.params.sparse_vectors,
    )
    for field in PAYLOAD_INDEXES:
        target.create_payload_index(name, field, field_schema=models.PayloadSchemaType.KEYWORD)
    offset = None
    copied = 0
    while True:
        points, offset = source.scroll(
            name, limit=batch, offset=offset, with_payload=True, with_vectors=True
        )
        target.upsert(
            name,
            points=[
                models.PointStruct(id=p.id, vector=p.vector or {}, payload=p.payload)
                for p in points
            ],
        )
        copied += len(points)
        if offset is None:
            break
    target.close()
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", required=True)
    parser.add_argument("--out", type=Path, default=Path("index_snapshot"))
    args = parser.parse_args()
    copied = export(make_client(get_settings()), args.collection, args.out)
    sys.stderr.write(f"exported {copied} points of {args.collection} to {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
