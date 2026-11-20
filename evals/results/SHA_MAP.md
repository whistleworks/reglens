# Commit SHA map

On 2026-11-20, before the first push, the history was rewritten once to replace the author email with the GitHub noreply address (`git filter-branch --env-filter`; no file content changed). Result files created before that keep the **old** sha in `run_id` / `git_sha`. This table maps them to the published commits.

| old sha (in result files) | new sha | commit |
|---|---|---|
| `5bbb36e741d2` | `7e4dddee4ff0` | chore: scaffold repo, tooling, CI and Claude Code config |
| `d97d09ce2173` | `8d4617ad3010` | docs: ADR-0001 stack and verified free-tier limits |
| `f759a845d75f` | `0f8a821596c2` | feat(ids): canonical identifiers with parsing, validation and natural  |
| `7e3e25030fe9` | `c85db7e1287f` | feat(ingestion): fetch sources from Cellar with retry, cache and hash  |
| `aff7d4149783` | `13d6fb40791a` | feat(ingestion): structured parser for consolidated and OJ layouts |
| `1813f1a4cfc5` | `df1ed4d262bf` | feat(ingestion): bilingual cross-reference extraction and glossary |
| `157474e1d12f` | `b0b91c5fcbad` | feat(ingestion): paragraph-level chunking, manifest and idempotent ing |
| `d425b8574451` | `c6f6271b64a7` | feat(retrieval): dense e5 + BM25 sparse indexing in Qdrant, dense/spar |
| `ed685b377cce` | `e8afc564aaca` | feat(evals): article-level retrieval metrics, bootstrap CI, run_eval a |
| `8c36ce775b29` | `29d6a9e24f43` | feat(evals): dataset v0 draft (50 dev candidates), JSON schema and rev |
| `36dc321b4fc2` | `cd564f4f4446` | docs: update PROGRESS and CLAUDE.md at end of session |
| `4cf503d13b7c` | `4fd199b0de5b` | feat(retrieval): embedded local Qdrant mode, ask.py demo and first bas |
| `a3960be3851a` | `614b67ccbdaf` | feat(evals): BEIR diagnostic variants; localize IT chunk labels |
| `c1f47a25334e` | `d682216a34c5` | feat(retrieval): hybrid RRF pipeline, cross-encoder rerank, 3 chunking |
| `00af7ae12544` | `e46f4a54dacc` | feat(evals): paired-bootstrap run comparison and ablation report; hybr |
| `2404c7295951` | `cc4c9230c336` | docs: ADR-0004 embedded Qdrant local mode for dev and as future fallba |
| `e320a623c64d` | `51650bdac225` | feat(evals): dataset reglens_v1 draft - 150 queries, 100 dev / 50 test |
| `3540d6aeaea8` | `b5637ee3f761` | chore(evals): default dataset is reglens_v1 |
| `29584a91fe7a` | `a7cb3a4a627f` | docs: evaluation methodology |
| `19d64a3e1041` | `183e1954efd3` | docs: ADR-0005 own OpenAI-compatible LLM gateway instead of LiteLLM |
| `5798e366ca1f` | `cd8412827255` | feat(llm): OpenAI-compatible gateway with retry, circuit breaker, fall |
| `1c4eb0dfa561` | `b6f7a2f86a61` | feat(agent): from-scratch tool-calling loop, tools, citation validator |
| `0e744b7006e7` | `7e8655da09c8` | feat(evals): generation/agent metrics, versioned LLM judge, judge cali |
| `fbf307e53967` | `38d698042154` | feat(evals): end-to-end eval stage (router + agent + citations + judge |
| `1e2274a41d3a` | `684661d888aa` | feat(api): FastAPI with SSE, RFC 7807 errors, API-key auth, rate limit |
| `e199c4924c35` | `7de812584bcf` | ci: Docker image with embedded index, CI gate, nightly eval, deploy, s |
| `58177745725b` | `0498777db768` | feat(observability): OpenTelemetry tracing to Langfuse (OTLP), metrics |
| `f8c77a2c5c4f` | `158893637921` | docs: architecture, runbook for every alert, alert rules and 14-panel  |
| `28c7d8af9d18` | `6b57566b74fe` | feat(retrieval): recital exclusion filter, weighted RRF, paragraph_def |
| `de563b47bb35` | `8ca704cc3852` | feat(retrieval): units chunking (annex points), serving config chosen  |

Old shas referenced by result files: `28c7d8af9d18`, `36dc321b4fc2`, `4cf503d13b7c`, `c1f47a25334e`, `d425b8574451`, `f8c77a2c5c4f`.
