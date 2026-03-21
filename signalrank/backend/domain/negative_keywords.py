# job_ranker/domain/negative_keywords.py


def violates_negative_keywords(
    *,
    text: str,
    negative_keywords: list[str],
) -> bool:
    """
    Returns True if text contains any negative keyword.

    Rules:
    - case-insensitive
    - substring match
    - deterministic
    """
    if not text or not negative_keywords:
        return False

    t = text.lower()
    for kw in negative_keywords:
        if kw and kw in t:
            return True

    return False
