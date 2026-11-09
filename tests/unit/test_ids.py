from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from reglens.ids import (
    CanonicalId,
    CitationID,
    InvalidIdError,
    annex_id,
    article_id,
    from_roman,
    parse_id,
    recital_id,
    to_roman,
)

VALID = [
    "AIA:art:6",
    "AIA:art:4a",
    "AIA:art:75d",
    "AIA:art:6:par:2",
    "AIA:art:6:par:3a",
    "AIA:art:5:par:1:pt:a",
    "AIA:art:5:par:1:pt:ha",
    "AIA:art:3:def:1",
    "GDPR:art:4:def:11",
    "AIA:art:3:pt:44",
    "AIA:rec:53",
    "GDPR:rec:173",
    "AIA:annex:III",
    "AIA:annex:III:pt:4",
    "AIA:annex:XIII:pt:2a",
]


@pytest.mark.parametrize("raw", VALID)
def test_round_trip(raw: str) -> None:
    assert str(parse_id(raw)) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "AIA",
        "DSA:art:1",  # unknown regulation
        "aia:art:6",  # case sensitive
        "AIA:art:0",
        "AIA:art:06",  # no leading zeros
        "AIA:art:6A",
        "AIA:art:6:par:0",
        "AIA:art:6:pt:a:par:1",  # wrong order
        "AIA:art:4:def:0",
        "AIA:art:4:par:1:def:2",  # definitions hang directly off the article
        "AIA:rec:53:par:1",  # recitals have no children
        "AIA:rec:5a",
        "AIA:annex:3",  # annexes are roman
        "AIA:annex:IIII",  # not a canonical roman numeral
        "AIA:annex:III:par:1",
        "AIA:art:6:",
        "AIA:art:6:par",
        " AIA:art:6",
    ],
)
def test_rejects_malformed(raw: str) -> None:
    with pytest.raises(InvalidIdError):
        parse_id(raw)


def test_article_level_projection() -> None:
    assert str(parse_id("AIA:art:6:par:2").article_level()) == "AIA:art:6"
    assert str(parse_id("GDPR:art:4:def:11").article_level()) == "GDPR:art:4"
    assert str(parse_id("AIA:annex:III:pt:4").article_level()) == "AIA:annex:III"
    assert str(parse_id("AIA:rec:53").article_level()) == "AIA:rec:53"


def test_parent_chain() -> None:
    node: CanonicalId | None = parse_id("AIA:art:5:par:1:pt:a")
    chain = []
    while node is not None:
        chain.append(str(node))
        node = node.parent()
    assert chain == ["AIA:art:5:par:1:pt:a", "AIA:art:5:par:1", "AIA:art:5"]


def test_natural_sort() -> None:
    raw = [
        "GDPR:art:1",
        "AIA:annex:II",
        "AIA:art:10",
        "AIA:art:4a",
        "AIA:art:4",
        "AIA:rec:2",
        "AIA:art:4:par:10",
        "AIA:art:4:par:2",
        "AIA:annex:IX",
        "AIA:art:5",
    ]
    ordered = [str(i) for i in sorted(parse_id(r) for r in raw)]
    assert ordered == [
        "AIA:art:4",
        "AIA:art:4:par:2",
        "AIA:art:4:par:10",
        "AIA:art:4a",
        "AIA:art:5",
        "AIA:art:10",
        "AIA:rec:2",
        "AIA:annex:II",
        "AIA:annex:IX",
        "GDPR:art:1",
    ]


def test_builders() -> None:
    assert str(article_id("AIA", "6", paragraph="2")) == "AIA:art:6:par:2"
    assert str(article_id("GDPR", "4", definition=11)) == "GDPR:art:4:def:11"
    assert str(recital_id("AIA", 53)) == "AIA:rec:53"
    assert str(annex_id("AIA", "III", point="4")) == "AIA:annex:III:pt:4"
    with pytest.raises(InvalidIdError):
        article_id("AIA", "6", paragraph="1", definition=2)


@pytest.mark.parametrize(
    ("n", "roman"), [(1, "I"), (4, "IV"), (9, "IX"), (13, "XIII"), (14, "XIV")]
)
def test_roman(n: int, roman: str) -> None:
    assert to_roman(n) == roman
    assert from_roman(roman) == n


def test_pydantic_type() -> None:
    class Model(BaseModel):
        cites: list[CitationID]

    assert Model(cites=["AIA:art:6"]).cites == ["AIA:art:6"]
    with pytest.raises(ValidationError):
        Model(cites=["AIA:article:6"])


def test_hashable_and_equal() -> None:
    assert parse_id("AIA:art:6") == parse_id("AIA:art:6")
    assert len({parse_id("AIA:art:6"), parse_id("AIA:art:6")}) == 1
