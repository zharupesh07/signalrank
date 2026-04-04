# domain/company.py
import re
from typing import Dict


def _norm(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


class CompanyScorer:
    """
    Deterministic, tiered company preference scorer.

    Supports 5 tiers: tier_s, tier_a, tier_b, tier_c, tier_d.
    Falls back to legacy preferred/deprioritized if tiers not configured.
    Alias-aware, no hard filtering.
    """

    # Ordered highest to lowest priority
    _TIERS = ["tier_ss", "tier_s", "tier_a", "tier_b", "tier_c", "tier_d"]

    def __init__(self, cfg: dict):
        c = cfg.get("company_scoring", {})

        self.default_weight = float(c.get("default_weight", 1.0))

        raw_aliases = c.get("aliases", {})
        self.aliases: Dict[str, str] = {
            _norm(k): _norm(v)
            for k, v in raw_aliases.items()
            if isinstance(k, str) and isinstance(v, str)
        }

        # Build tier lookup: {normalized_name: tier_name}
        self._tier_lookup: Dict[str, str] = {}
        has_tiers = any(c.get(t) for t in self._TIERS)

        if has_tiers:
            for tier in self._TIERS:
                for name in c.get(tier, []):
                    self._tier_lookup[_norm(name)] = tier
        else:
            # Legacy fallback: preferred → tier_a, deprioritized → tier_d
            for name in c.get("preferred_companies", []):
                self._tier_lookup[_norm(name)] = "tier_a"
            for name in c.get("deprioritized_companies", []):
                self._tier_lookup[_norm(name)] = "tier_d"

    def _canonical(self, company: str) -> str:
        name = _norm(company)
        return self.aliases.get(name, name)

    def classify(self, company: str) -> str:
        """Returns tier name or 'default'.

        Matching is exact on normalized company strings after alias resolution.
        This avoids broad substring hits like matching unrelated companies that
        merely contain a tiered brand token.
        """
        name = self._canonical(company)
        return self._tier_lookup.get(name, "default")

    def score(self, company: str) -> float:
        """Legacy weight for backward compatibility."""
        tier = self.classify(company)
        return {
            "tier_ss": 1.6,
            "tier_s": 1.5,
            "tier_a": 1.3,
            "tier_b": 1.1,
            "tier_c": 0.95,
            "tier_d": 0.85,
        }.get(tier, self.default_weight)
