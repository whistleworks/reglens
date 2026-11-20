"""Build a Markdown review sheet: each candidate with the text of its gold units.

uv run python scripts/review_sheet.py evals/datasets/reglens_v0.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.dataset import load_dataset
from reglens.config import get_settings
from reglens.ids import parse_id


def unit_texts(lang: str) -> dict[str, str]:
    processed = get_settings().processed_dir
    corpus = json.loads((processed / f"corpus_{lang}.json").read_text())
    texts: dict[str, str] = {}
    for doc in corpus["regulations"]:
        for art in doc["articles"]:
            texts[art["id"]] = f"{art['heading']} — {art['title']}"
            for par in art["paragraphs"]:
                texts[par["id"]] = par["text"]
                for pt in par["points"]:
                    texts[f"{par['id']}:pt:{pt['label']}"] = pt["text"]
        for rec in doc["recitals"]:
            texts[rec["id"]] = rec["text"]
        for annex in doc["annexes"]:
            texts[annex["id"]] = f"Annex {annex['number']} — {annex['title']}"
            for pt in annex["points"]:
                texts[f"{annex['id']}:pt:{pt['label']}"] = pt["text"]
    for entry in json.loads((processed / "glossary.json").read_text()):
        texts[entry["id"]] = entry[f"definition_{lang}"]
    return texts


def excerpt(texts: dict[str, str], gold: str, limit: int = 600) -> str:
    # unknown fine-grained ids fall back to the article header
    fallback = texts.get(str(parse_id(gold).article_level()), "(not found)")
    text = texts.get(gold, fallback)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + " […]"


def main(path: Path) -> None:
    records = load_dataset(path)
    texts = {lang: unit_texts(lang) for lang in ("en", "it")}
    out = [
        f"# Review sheet — {path.name}",
        "",
        "For each record: tick ✅ if question, gold ids, reference answer and key facts",
        "are correct; otherwise write the correction.",
        "Only approved records get `reviewed: true`.",
        "",
    ]
    for r in records:
        out += [
            f"## {r.id} · {r.category} · {r.lang} · {r.difficulty} · "
            f"expected: {r.expected_behavior}",
            "",
            f"**Q:** {r.question}",
            "",
            f"**Reference:** {r.reference_answer}",
            "",
            "**Key facts:** " + ("; ".join(r.key_facts) or "—"),
            "",
            "**Gold:**" if r.gold_ids else "**Gold:** — (no retrieval target)",
        ]
        out += [f"- `{g}`: {excerpt(texts[r.lang], g)}" for g in r.gold_ids]
        out += ["", "- [ ] ✅ approved — notes:", ""]
    target = path.parent / "review" / f"{path.stem}_review.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    sys.stderr.write(f"wrote {target}\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
