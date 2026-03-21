"""
PORT FROM v1:
- skills/canonicalizer.py
- llm/normalize_skills.py
"""

# domain/skills.py
from __future__ import annotations

from typing import Dict, Iterable, List, Set


def _build_variant_lookup(groups: dict) -> Dict[str, str]:
    lookup: Dict[str, str] = {}

    for group in groups.values():
        canonical = group.get("canonical")
        variants = group.get("variants", [])
        if not canonical:
            continue

        canon = canonical.lower().strip()
        lookup[canon] = canon

        for v in variants:
            if isinstance(v, str):
                lookup[v.lower().strip()] = canon

    return lookup


class SkillCanonicalizer:
    """
    Deterministic skill canonicalization.

    RULES:
    - config-driven only
    - no ML
    - canonicalize → dedupe (order matters)
    """

    def __init__(self, cfg: dict):
        skills_cfg = cfg.get("skills", {})
        groups = skills_cfg.get("equivalence_groups", {})
        self.lookup = _build_variant_lookup(groups)

    def canonicalize(self, raw: Iterable[str]) -> Set[str]:
        out: Set[str] = set()

        for s in raw or []:
            if not isinstance(s, str):
                continue
            key = s.lower().strip()
            out.add(self.lookup.get(key, key))

        return out

    def canonicalize_and_join(self, raw: Iterable[str]) -> str:
        return " ".join(sorted(self.canonicalize(raw)))


def extract_skills_from_texts(
    texts: List[str],
    cfg: dict,
) -> List[List[str]]:
    """
    Exact phrase matching only.
    """
    groups = cfg.get("skills", {}).get("equivalence_groups", {})
    if not groups:
        return [[] for _ in texts]

    phrases: Dict[str, str] = {}
    for g in groups.values():
        canon = g.get("canonical", "").lower()
        for v in g.get("variants", []):
            phrases[v.lower()] = canon
        if canon:
            phrases[canon] = canon

    results = []
    for t in texts:
        if not isinstance(t, str):
            results.append([])
            continue

        tl = t.lower()
        found = {canon for phrase, canon in phrases.items() if phrase in tl}
        results.append(sorted(found))

    return results
