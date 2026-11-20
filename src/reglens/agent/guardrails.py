"""Input guardrails: validation and prompt-injection heuristics.

Suspected injections are not blocked (a legitimate question may follow them): they are
flagged, logged and the agent receives an extra reminder that instructions inside the
user text or in retrieved sources must be ignored. The adversarial subset of the
dataset measures how often this still fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|prior|above) (instructions|rules)",
    r"(dimentica|ignora) (tutte )?le (istruzioni|regole)",
    r"(system|developer) (prompt|override|message)",
    r"(reveal|print|repeat|show).{0,40}(prompt|instructions)",
    r"(mostra|ripeti|stampa).{0,40}(prompt|istruzioni)",
    r"\byou are (now )?(dan|an? unrestricted)\b",
    r"(sei|fai finta di essere).{0,30}(senza (alcuna )?restrizion|senza regole)",
    r"(no|without) (rules|restrictions)",
    r"citations? (are )?(disabled|not required)",
    r"nota per l'assistente|note (to|for) the assistant",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


class InputRejectedError(ValueError):
    pass


@dataclass
class GuardrailResult:
    text: str
    injection_suspected: bool
    signals: list[str] = field(default_factory=list)


def check_input(text: str, max_chars: int = 2000) -> GuardrailResult:
    cleaned = text.replace("\x00", "").strip()
    if not cleaned:
        raise InputRejectedError("empty question")
    if len(cleaned) > max_chars:
        raise InputRejectedError(f"question longer than {max_chars} characters")
    signals = [m.group(0) for m in _INJECTION.finditer(cleaned)]
    return GuardrailResult(text=cleaned, injection_suspected=bool(signals), signals=signals)
