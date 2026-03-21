# job_ranker/domain/description_quality.py

import re

# Common recruiter boilerplate phrases (lowercase)
_BOILERPLATE_PHRASES = [
    "fast paced environment",
    "dynamic environment",
    "cross functional teams",
    "stakeholders",
    "self starter",
    "good communication skills",
    "work independently",
    "work collaboratively",
    "various ad hoc",
    "as assigned",
]

_TECH_TOKEN_RE = re.compile(r"\b[a-zA-Z_]{4,}\b")


def description_quality_multiplier(description: str) -> float:
    """
    Returns a bounded multiplier in [0.70, 1.0].

    Penalizes:
    - very short descriptions
    - recruiter boilerplate dominance
    - low technical specificity

    Conservative by design.
    """
    if not isinstance(description, str):
        return 0.70

    text = description.lower()
    length = len(text)

    # ----------------------------
    # Length signal
    # ----------------------------
    if length < 200:
        length_penalty = 0.75
    elif length < 400:
        length_penalty = 0.85
    else:
        length_penalty = 1.0

    # ----------------------------
    # Boilerplate density
    # ----------------------------
    boilerplate_hits = sum(1 for p in _BOILERPLATE_PHRASES if p in text)
    boilerplate_penalty = max(0.85, 1.0 - 0.05 * boilerplate_hits)

    # ----------------------------
    # Technical specificity proxy
    # ----------------------------
    tokens = set(_TECH_TOKEN_RE.findall(text))
    tech_density = len(tokens) / max(length / 1000.0, 1.0)

    if tech_density < 8:
        tech_penalty = 0.85
    elif tech_density < 12:
        tech_penalty = 0.92
    else:
        tech_penalty = 1.0

    return round(length_penalty * boilerplate_penalty * tech_penalty, 3)
