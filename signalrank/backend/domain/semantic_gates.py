# domain/semantic_gates.py


def passes_semantic_gate(
    role: str,
    semantic_score: float,
    description_quality: float,
    role_thresholds: dict[str, float],
) -> bool:
    """
    Absolute semantic gates. No multipliers here.
    """

    threshold = role_thresholds.get(role)
    if threshold is None:
        return True

    if role == "software_general":
        # Generic SWE roles must also be high quality
        return semantic_score >= threshold and description_quality >= 0.9

    return semantic_score >= threshold
