# domain/non_ic_gate.py

NON_IC_KEYWORDS = {
    "analyst",
    "executive",
    "operations",
    "process",
    "hr",
    "human resource",
    "trainer",
    "talent",
    "sourcing",
    "business systems",
}

IC_ALLOWLIST = {
    "engineer",
    "developer",
    "architect",
    "systems",
}


def requires_high_semantic_floor(title: str) -> bool:
    t = title.lower()

    is_non_ic = any(k in t for k in NON_IC_KEYWORDS)
    has_ic_signal = any(k in t for k in IC_ALLOWLIST)

    return is_non_ic and not has_ic_signal
