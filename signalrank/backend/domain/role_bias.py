# domain/role_bias.py

from typing import Tuple

CONSULTING_KEYWORDS = {
    "consultant",
    "consulting",
    "engagement",
    "advisory",
    "client",
    "manager",
    "director",
    "assistant manager",
    "senior manager",
}

STRONG_IC_KEYWORDS = {
    "engineer",
    "developer",
    "architect",
    "platform",
    "systems",
    "backend",
    "ml",
    "ai",
}


def consulting_bias_multiplier(title: str) -> Tuple[float, str | None]:
    """
    Soft dampener for consulting / managerial gravity.
    Never a hard veto.
    """
    t = title.lower()

    has_consulting = any(k in t for k in CONSULTING_KEYWORDS)
    has_ic_signal = any(k in t for k in STRONG_IC_KEYWORDS)

    if has_consulting and not has_ic_signal:
        return 0.8, "consulting_role_dampener"

    return 1.0, None
