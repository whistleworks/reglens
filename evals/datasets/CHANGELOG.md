# Dataset changelog

Every change to `evals/datasets/` needs the explicit OK of the project owner and a dedicated commit.
The dataset version used in results is `<file stem>@<sha256[:8]>` (see `evals/dataset.py`).

## reglens_v1 — 2026-11-20 (M2, draft, OK del titolare per l'inserimento)
- 150 records = the 50 of v0 (all dev, unchanged) + 100 new candidates q051–q150 drafted by Claude Code from the parsed corpus; every gold id checked to exist in `data/processed/`.
- Composition exactly as in the brief: single_hop 55 (35 EN / 20 IT), multi_hop 25, definitional 15, scenario 20, unanswerable 15, adversarial 10, ambiguous 10.
- Split: 100 dev / 50 test. The 50 test records were drawn from the new 100 with a stratified, seeded sample (seed 20261120) per category (single_hop also per language): 18/8/5/7/5/3/4. **The test split must never be used before `make eval-final` (M6).**
- **`reviewed: false` on every record until the human review** (`evals/datasets/review/reglens_v1_review.md`). At least 30 handwritten queries by the owner are still to be added (`source: handwritten`).

## reglens_v0 — 2026-11-09 (M1, draft)
- 50 dev candidates drafted by Claude Code from the parsed corpus (AI Act consolidated 27.07.2026 + GDPR); every gold id checked to exist in `data/processed/`.
- Composition: single_hop 18 (12 EN / 6 IT), multi_hop 8, definitional 5, scenario 7, unanswerable 5, adversarial 4, ambiguous 3; 32 EN / 18 IT.
- `source: synthetic_reviewed`, **`reviewed: false` on every record until the human review** (review sheet: `evals/datasets/review/reglens_v0_review.md`).
- No test split yet (comes in M2 with the 150-query v1).
