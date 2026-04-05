from __future__ import annotations

from ranking.v3.lanes import LANE_REGISTRY
from ranking.v3.profile import ProfileV3


def build_query_plan(profile: ProfileV3, *, max_core: int = 5, max_adjacent: int = 4, max_lane: int = 3) -> dict:
    """
    Build a structured query plan from a ProfileV3.

    Returns:
        {
          "core": [...],       # role + must-have skill combos
          "adjacent": [...],   # adjacent role titles
          "exploratory": [...],# broad domain/skill queries
          "lanes": {...},      # {lane_name: [queries]}
          "negative_keywords": [...],
        }
    """
    top_skills = [ws.name for ws in profile.weighted_skills if ws.weight >= 0.7][:5]

    core: list[str] = []
    for role in profile.target_roles[:3]:
        for skill in top_skills[:2]:
            core.append(f"{role} {skill}")
        core.append(role)
    core = _dedupe(core)[:max_core]

    adjacent = _dedupe(profile.target_roles[3:] + [
        f"{role} engineer" for role in profile.domains[:2]
    ])[:max_adjacent]

    exploratory = _dedupe([
        f"{domain} engineer" for domain in profile.domains
    ] + top_skills[:3])[:4]

    lane_queries: dict[str, list[str]] = {}
    for lane_name in profile.active_lanes:
        lane = LANE_REGISTRY.get(lane_name)
        if lane:
            lane_queries[lane_name] = _dedupe(lane.query_templates)[:max_lane]

    return {
        "core": core,
        "adjacent": adjacent,
        "exploratory": exploratory,
        "lanes": lane_queries,
        "negative_keywords": profile.avoid_terms,
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result
