# job_ranker/domain/skill_boost.py


def bounded_skill_boost(
    overlap_count: int,
    *,
    max_boost: float = 0.08,
    per_skill: float = 0.02,
) -> float:
    """
    Returns a multiplier in [1.0, 1.0 + max_boost].

    Conservative by design.
    """
    if not overlap_count or overlap_count <= 0:
        return 1.0

    boost = 1.0 + overlap_count * per_skill
    return min(boost, 1.0 + max_boost)
