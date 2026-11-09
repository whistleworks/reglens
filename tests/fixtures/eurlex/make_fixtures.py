"""Cut the small test fixtures out of the real raw sources.

Usage: uv run python -I tests/fixtures/eurlex/make_fixtures.py data/raw tests/fixtures/eurlex
"""

import copy
import sys
from pathlib import Path

from lxml import etree, html

raw = Path(sys.argv[1])
out = Path(sys.argv[2])


def trimmed_chapter(root, cpt, sct, art):
    c = copy.deepcopy(root.get_element_by_id(cpt))
    for child in list(c):
        cid = child.get("id") or ""
        if (
            cid.startswith(("art_", "cpt_"))
            and not cid.endswith(".tit_1")
            and cid not in (sct, art)
        ):
            c.remove(child)
    s = c.get_element_by_id(sct) if sct else c
    for child in list(s):
        cid = child.get("id") or ""
        if cid.startswith("art_") and cid != art:
            s.remove(child)
    return c


def write(name, nodes):
    body = "".join(etree.tostring(n, encoding="unicode") for n in nodes)
    (out / name).write_text(
        '<html><head><meta charset="utf-8"/></head><body>'
        f'<div class="eli-container">{body}</div></body></html>\n'
    )


for lang in ("en", "it"):
    r = html.parse(str(raw / f"aia_consolidated_{lang}.html")).getroot()
    nodes = [trimmed_chapter(r, "cpt_III", "cpt_III.sct_1", "art_6")]
    nodes += [
        copy.deepcopy(r.get_element_by_id(i))
        for i in ("art_3", "art_4a", "art_51", "art_105", "anx_III")
    ]
    write(f"aia_consolidated_{lang}.html", nodes)
    o = html.parse(str(raw / f"aia_oj_{lang}.html")).getroot()
    write(
        f"aia_oj_{lang}.html", [copy.deepcopy(o.get_element_by_id(i)) for i in ("rct_1", "rct_53")]
    )
    g = html.parse(str(raw / f"gdpr_oj_{lang}.html")).getroot()
    nodes = [trimmed_chapter(g, "cpt_II", None, "art_6")]
    nodes += [copy.deepcopy(g.get_element_by_id(i)) for i in ("art_4", "art_38", "rct_1")]
    write(f"gdpr_oj_{lang}.html", nodes)
