# Data: sources, licence, checksums

## Sources

| Key | Act | CELEX | Role | Languages |
|---|---|---|---|---|
| `aia_consolidated` | Regulation (EU) 2024/1689 (AI Act), consolidated text of **27.07.2026**, including the amendments of Regulation (EU) 2026/1744 ("Digital Omnibus on AI") | `02024R1689-20260727` | articles and annexes | EN, IT |
| `aia_oj` | Regulation (EU) 2024/1689 as published in the Official Journal (OJ L, 12.7.2024) | `32024R1689` | the 180 recitals only (consolidated texts do not include recitals) | EN, IT |
| `gdpr_oj` | Regulation (EU) 2016/679 (GDPR) as published in the Official Journal (OJ L 119, 4.5.2016) | `32016R0679` | full text | EN, IT |

Why this mix (decision of 2026-11-09, see ADR-0001):
- The AI Act was amended in July 2026, so the original text is out of date on Article 5, application dates and sandboxes.
- Recitals are not part of consolidated texts and were not amended in place, so they come from the original OJ text.
- The GDPR has corrigenda (OJ L 127, 23.5.2018 and later), which the 2016 OJ text does not include. This is a known limitation; the corrigenda can be integrated later.

### Download method
- `eur-lex.europa.eu/legal-content/...` answers `HTTP 202` with an empty body to non-browser clients (WAF challenge, tested 2026-11-09).
- `src/reglens/ingestion/fetch.py` therefore uses the Publications Office **Cellar** with content negotiation:

  ```
  GET http://publications.europa.eu/resource/celex/{CELEX}
  Accept: application/xhtml+xml
  Accept-Language: eng | ita
  → 303 → .../resource/cellar/{uuid}.{manifestation}/DOC_1 (200, XHTML)
  ```

- If Cellar fails, `make ingest` prints step-by-step instructions to download the page once by hand from EUR-Lex. The manual file is accepted only if its sha256 matches the pin in `data/sources.lock.json`. If you deliberately want a newer version, use `--update-lock` and record the change here.
- Links shown to users (`url_eurlex`) always point to the human-readable EUR-Lex page.

## Checksums

Pinned in [`sources.lock.json`](sources.lock.json) (sha256 of the raw XHTML and the resolved Cellar URL). Files downloaded on 2026-11-09.

## Licence and attribution

- Legal acts published in EUR-Lex and the Cellar are made available by the Publications Office of the European Union. Their reuse is governed by **Commission Decision 2011/833/EU of 12 December 2011 on the reuse of Commission documents** (OJ L 330, 14.12.2011, p. 39): https://eur-lex.europa.eu/eli/dec/2011/833/oj
- Reuse, including commercial reuse, is authorised **provided the source is acknowledged** and modifications are indicated. Reuse must not distort the original meaning or message.
- Only the official OJ texts are authentic. Consolidated texts are "a documentation tool and [have] no legal effect" (disclaimer printed in the consolidated text itself).
- Attribution used in this project: **Source: EUR-Lex / Publications Office of the European Union, © European Union, 1998–2026. Texts parsed and restructured by RegLens; the original wording is not altered.**
- Verified 2026-11-09 through the Commission legal notice (https://commission.europa.eu/legal-notice_en) and the Interoperable Europe summary of the Europa legal notice (https://interoperable-europe.ec.europa.eu/licence/europa-legal-notice). The EUR-Lex HTML pages could not be fetched automatically (WAF), so the decision's text is linked and not quoted.

## Layout

```
data/
├── README.md                 this file
├── sources.lock.json         pinned sha256 of the raw sources (committed)
├── raw/                      downloaded XHTML (gitignored, recreated by `make ingest`)
└── processed/                corpus_{en,it}.json, glossary.json, xrefs.json, chunks, manifest.json
```
