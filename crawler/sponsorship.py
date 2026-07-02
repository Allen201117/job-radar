import re
from typing import Optional


NONE = [
    re.compile(r"\bdo(?:es)? not sponsor\b", re.I),
    re.compile(r"\bno (?:visa )?sponsorship\b", re.I),
    re.compile(r"\bunable to (?:provide|offer) (?:visa )?sponsorship\b", re.I),
    re.compile(r"without (?:visa )?sponsorship\b", re.I),
    re.compile(r"must be authorized to work in the u\.?s", re.I),
    re.compile(r"u\.?s\.? citizens? only", re.I),
    re.compile(r"security clearance", re.I),
    re.compile(r"not (?:able|eligible) to sponsor\b", re.I),
]

AVAILABLE = [
    re.compile(r"\b(?:visa )?sponsorship (?:is )?available\b", re.I),
    re.compile(r"\bwill sponsor\b", re.I),
    re.compile(r"\bwe sponsor\b", re.I),
    re.compile(r"\bh-?1b sponsorship\b", re.I),
    re.compile(r"sponsorship (?:is )?(?:provided|offered)\b", re.I),
    re.compile(r"relocation and visa (?:support )?(?:provided|available)?\b", re.I),
]


def sponsorship_signal(text: Optional[str]) -> str:
    t = str(text or "")
    if not t.strip():
        return "unknown"
    if any(r.search(t) for r in NONE):
        return "none"
    if any(r.search(t) for r in AVAILABLE):
        return "available"
    return "unknown"
