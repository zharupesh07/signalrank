# ================================
# FILE: fast_heuristics.py
# ================================
import re
from typing import Dict, Iterable, List, Set


# --------------------------------------------------
# TEXT NORMALIZATION
# --------------------------------------------------
def _normalize_text(text: str) -> str:
    """
    Deterministic text normalization for phrase matching.
    """
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\+\-\. ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --------------------------------------------------
# SKILL PHRASE MATCHER (CONFIG-DRIVEN)
# --------------------------------------------------
def extract_skills_fast(
    text: str,
    *,
    equivalence_groups: Dict,
) -> List[str]:
    """
    Deterministic skill phrase extractor.

    Properties:
    - Phrase-based (not token-based)
    - Config-driven (skills.equivalence_groups)
    - LLM-free
    - High precision
    - Stable across runs

    Returns:
    - List of matched raw skill variants (lowercase)
    """

    if not text or not equivalence_groups:
        return []

    norm_text = _normalize_text(text)

    matched: Set[str] = set()

    for group in equivalence_groups.values():
        variants = group.get("variants", [])
        for v in variants:
            if not isinstance(v, str):
                continue

            phrase = v.strip().lower()
            if not phrase:
                continue

            # Word-boundary safe phrase match
            pattern = r"\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, norm_text):
                matched.add(phrase)

    return sorted(matched)
