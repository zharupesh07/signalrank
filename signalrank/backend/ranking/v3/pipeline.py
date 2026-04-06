from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timezone

from ranking.v3.extraction import extract_profile_v3
from ranking.v3.scorer import score_jobs

_STALENESS_DAYS = 90


def _is_stale(job: dict) -> bool:
    date_str = job.get("date_posted")
    if not date_str:
        return False
    try:
        posted = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        age = (datetime.now(tz=timezone.utc) - posted).days
        return age > _STALENESS_DAYS
    except ValueError:
        return False


def _dedup_key(job: dict) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", (job.get("title") or "").lower().strip())
    company = re.sub(r"\s+", " ", (job.get("company") or "").lower().strip())
    return (title, company)


def _dedup_jobs(jobs: list[dict]) -> list[dict]:
    """Keep most recent job per (title_normalized, company_normalized)."""
    seen: dict[tuple[str, str], dict] = {}
    for job in jobs:
        key = _dedup_key(job)
        if key not in seen:
            seen[key] = job
        else:
            existing_date = seen[key].get("date_posted") or ""
            new_date = job.get("date_posted") or ""
            if new_date > existing_date:
                seen[key] = job
    return list(seen.values())


def rank_jobs_v3(
    resume_text: str,
    jobs: list[dict],
    *,
    candidate_name: str = "",
    current_focus: str | None = None,
    top_k: int = 30,
) -> list[dict]:
    """
    End-to-end V3 pipeline: resume text + jobs -> sorted top-k with features.

    Each result dict contains the original job fields plus:
      - score: float (normalized to [0, 1] relative to top result)
      - features: dict[str, float]
      - profile: dict (serialized ProfileV3 for audit)
    """
    profile = extract_profile_v3(resume_text, candidate_name=candidate_name, current_focus=current_focus)
    fresh_jobs = _dedup_jobs([j for j in jobs if not _is_stale(j)])
    scored = score_jobs(fresh_jobs, profile)

    # Normalize scores to [0, 1] relative to top result
    if scored:
        max_score = scored[0]["score"]
        if max_score > 0:
            for result in scored:
                result["score"] = result["score"] / max_score

    profile_dict = dataclasses.asdict(profile)
    for result in scored:
        result["profile"] = profile_dict
    return scored[:top_k]
