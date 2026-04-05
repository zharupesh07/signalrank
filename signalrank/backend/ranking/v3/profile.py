from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WeightedSkill:
    name: str
    weight: float  # [0.0, 1.0]; 1.0 = used in last 18 months

    def __post_init__(self) -> None:
        self.weight = max(0.0, min(1.0, self.weight))


@dataclass
class ProfileV3:
    candidate_name: str
    target_roles: list[str]
    weighted_skills: list[WeightedSkill]
    domains: list[str]
    industries: list[str]
    seniority_band: str  # "junior" | "mid" | "senior" | "principal" | "unknown"
    preferred_locations: list[str]
    must_have_terms: list[str]
    avoid_terms: list[str]
    current_focus: str | None  # user-confirmed intent string, or None
    active_lanes: list[str]  # lane names from lanes.py registry
    years_of_experience: int | None = field(default=None)
