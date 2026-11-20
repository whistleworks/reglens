# Commit SHA map

On 2026-11-20, before the first push, the history was rewritten to set the author email to the GitHub noreply address of the publishing account (whistleworks) (`git filter-branch --env-filter`; no file content changed). Result files created before that keep the **old** sha in `run_id` / `git_sha`. This table maps them to the published commits.

| old sha (in result files) | new sha | commit |
|---|---|---|
| `5bbb36e741d2` | `cbc1b9d1128e` | chore: scaffold repo, tooling, CI and Claude Code config |
| `d97d09ce2173` | `7a64c704c962` | docs: ADR-0001 stack and verified free-tier limits |
| `f759a845d75f` | `9d811a7a3cb3` | feat(ids): canonical identifiers with parsing, validation and natural  |
| `7e3e25030fe9` | `f9ce1e91fc46` | feat(ingestion): fetch sources from Cellar with retry, cache and hash  |
| `aff7d4149783` | `64c3970cbbbb` | feat(ingestion): structured parser for consolidated and OJ layouts |
| `1813f1a4cfc5` | `bf88492bd01a` | feat(ingestion): bilingual cross-reference extraction and glossary |
| `157474e1d12f` | `b5c98fa7cc0d` | feat(ingestion): paragraph-level chunking, manifest and idempotent ing |
| `d425b8574451` | `b43fa68b8062` | feat(retrieval): dense e5 + BM25 sparse indexing in Qdrant, dense/spar |
| `ed685b377cce` | `3539d8a0ea53` | feat(evals): article-level retrieval metrics, bootstrap CI, run_eval a |
| `8c36ce775b29` | `a4ff2eb87c01` | feat(evals): dataset v0 draft (50 dev candidates), JSON schema and rev |
| `36dc321b4fc2` | `c9500a90b509` | docs: update PROGRESS and CLAUDE.md at end of session |
| `4cf503d13b7c` | `f5aaa0bfe31b` | feat(retrieval): embedded local Qdrant mode, ask.py demo and first bas |
| `a3960be3851a` | `6952fc2bbb01` | feat(evals): BEIR diagnostic variants; localize IT chunk labels |
| `c1f47a25334e` | `c51dc15c0821` | feat(retrieval): hybrid RRF pipeline, cross-encoder rerank, 3 chunking |
| `00af7ae12544` | `9044aad5f47f` | feat(evals): paired-bootstrap run comparison and ablation report; hybr |
| `2404c7295951` | `5a81a1aa934e` | docs: ADR-0004 embedded Qdrant local mode for dev and as future fallba |
| `e320a623c64d` | `49da63a6cfd6` | feat(evals): dataset reglens_v1 draft - 150 queries, 100 dev / 50 test |
| `3540d6aeaea8` | `b49d9f6cb561` | chore(evals): default dataset is reglens_v1 |
| `29584a91fe7a` | `73942d5cfef9` | docs: evaluation methodology |
| `19d64a3e1041` | `01d3beb71ece` | docs: ADR-0005 own OpenAI-compatible LLM gateway instead of LiteLLM |
| `5798e366ca1f` | `56f3d9219fdb` | feat(llm): OpenAI-compatible gateway with retry, circuit breaker, fall |
| `1c4eb0dfa561` | `c71d3f040c1b` | feat(agent): from-scratch tool-calling loop, tools, citation validator |
| `0e744b7006e7` | `99f54c0052a7` | feat(evals): generation/agent metrics, versioned LLM judge, judge cali |
| `fbf307e53967` | `96955fea25b9` | feat(evals): end-to-end eval stage (router + agent + citations + judge |
| `1e2274a41d3a` | `f2953a7b98b1` | feat(api): FastAPI with SSE, RFC 7807 errors, API-key auth, rate limit |
| `e199c4924c35` | `963d9bfede33` | ci: Docker image with embedded index, CI gate, nightly eval, deploy, s |
| `58177745725b` | `abc17728c5a4` | feat(observability): OpenTelemetry tracing to Langfuse (OTLP), metrics |
| `f8c77a2c5c4f` | `be21f05766ea` | docs: architecture, runbook for every alert, alert rules and 14-panel  |
| `28c7d8af9d18` | `c4b857999f97` | feat(retrieval): recital exclusion filter, weighted RRF, paragraph_def |
| `de563b47bb35` | `778702e44ba2` | feat(retrieval): units chunking (annex points), serving config chosen  |

Old shas referenced by result files: `28c7d8af9d18`, `36dc321b4fc2`, `4cf503d13b7c`, `c1f47a25334e`, `d425b8574451`, `f8c77a2c5c4f`.
