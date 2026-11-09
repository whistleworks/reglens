# Dataset changelog

Every change to `evals/datasets/` needs the explicit OK of the project owner and a dedicated commit.
The dataset version used in results is `<file stem>@<sha256[:8]>` (see `evals/dataset.py`).

## reglens_v0 — 2026-11-09 (M1, draft)
- 50 dev candidates drafted by Claude Code from the parsed corpus (AI Act consolidated 27.07.2026 + GDPR); every gold id checked to exist in `data/processed/`.
- Composition: single_hop 18 (12 EN / 6 IT), multi_hop 8, definitional 5, scenario 7, unanswerable 5, adversarial 4, ambiguous 3; 32 EN / 18 IT.
- `source: synthetic_reviewed`, **`reviewed: false` on every record until the human review** (review sheet: `evals/datasets/review/reglens_v0_review.md`).
- No test split yet (comes in M2 with the 150-query v1).
