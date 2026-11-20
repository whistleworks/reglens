# syntax=docker/dockerfile:1.7
# Multi-stage image: builder (uv + deps + model weights) -> slim runtime, non-root uid 1000.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# Model weights in their own layer, so code changes do not re-download ~2.8 GB.
ENV HF_HOME=/models FASTEMBED_CACHE_PATH=/models/fastembed
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-large
ARG RERANKER_MODEL=BAAI/bge-reranker-v2-m3-int8
RUN /app/.venv/bin/python - <<PY
from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
TextEmbedding("${EMBEDDING_MODEL}")
SparseTextEmbedding("Qdrant/bm25", language="english")
SparseTextEmbedding("Qdrant/bm25", language="italian")
TextCrossEncoder("${RERANKER_MODEL}")
from tokenizers import Tokenizer
Tokenizer.from_pretrained("${EMBEDDING_MODEL}")
PY

FROM python:3.12-slim AS runtime
ARG GIT_SHA=unknown
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HF_HOME=/models \
    FASTEMBED_CACHE_PATH=/models/fastembed HF_HUB_OFFLINE=1 \
    APP_ENV=prod GIT_SHA=${GIT_SHA} PORT=7860 WORKERS=1 \
    INDEX_MODE=local_snapshot INDEX_SNAPSHOT_PATH=/app/index_snapshot
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
COPY --from=builder --chown=app:app /models /models
COPY --chown=app:app data/processed ./data/processed
COPY --chown=app:app data/sources.lock.json data/README.md ./data/
COPY --chown=app:app configs ./configs
# Embedded index (INDEX_MODE=local_snapshot): `make export-index` before `docker build`
COPY --chown=app:app index_snapshot ./index_snapshot
USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"
CMD ["sh", "-c", "uvicorn reglens.api.main:create_app --factory --host 0.0.0.0 --port ${PORT} --workers ${WORKERS}"]
