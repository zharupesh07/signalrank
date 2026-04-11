from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WeightedSkill:
    name: str
    weight: float  # [0.0, 1.0]; 1.0 = used in last 18 months

    def __post_init__(self) -> None:
        self.weight = max(0.0, min(1.0, self.weight))


@dataclass
class CandidateProfile:
    """Unified candidate profile for V4 scorer.

    Generalizes V3's ProfileV3 by:
    - Removing hardcoded candidate_name-based customizations
    - Adding resume_embedding for semantic similarity feature
    - Adding company_tier_map for company_tier_score feature
    - must_have_terms and avoid_terms come from config_overrides / onboarding
    """

    target_roles: list[str]
    weighted_skills: list[WeightedSkill]
    domains: list[str]
    industries: list[str]
    seniority_band: str  # "junior" | "mid" | "senior" | "principal"
    preferred_locations: list[str]
    must_have_terms: list[str]
    avoid_terms: list[str]
    active_lanes: list[str]  # lane names from lanes.py registry
    current_focus: str | None = field(default=None)
    years_of_experience: int | None = field(default=None)
    resume_embedding: list[float] | None = field(default=None)
    company_tier_map: dict[str, str] = field(default_factory=dict)  # company_name → tier
    preferred_company_tiers: list[str] = field(default_factory=list)
    company_preference_strength: float = field(default=1.0)
