from __future__ import annotations

from datetime import datetime, timezone

DIRECT_SOURCE_SITES = {"greenhouse", "ashby", "lever"}
SPECIALIST_FEED_SITES = {"himalayas", "remotive", "jobicy", "manual"}
AGGREGATOR_SITES = {
    "indeed",
    "linkedin",
    "google",
    "jsearch",
    "li_jobsearch",
    "li_7d",
    "jobs_scanner",
    "li_bulk",
}

_SOURCE_PRIORITY = {
    "greenhouse": 4,
    "ashby": 4,
    "lever": 4,
    "manual": 3,
    "himalayas": 2,
    "remotive": 2,
    "jobicy": 2,
    "indeed": 1,
    "linkedin": 1,
    "google": 1,
    "jsearch": 1,
    "li_jobsearch": 1,
    "li_7d": 1,
    "jobs_scanner": 1,
    "li_bulk": 1,
}


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_direct_source(site: str | None) -> bool:
    return str(site or "").lower() in DIRECT_SOURCE_SITES


def is_aggregator_source(site: str | None) -> bool:
    return str(site or "").lower() in AGGREGATOR_SITES


def source_priority(site: str | None) -> int:
    return _SOURCE_PRIORITY.get(str(site or "").lower(), 1)


def source_quality_score(site: str | None) -> float:
    priority = source_priority(site)
    return {
        4: 1.0,
        3: 0.8,
        2: 0.55,
        1: 0.18,
    }.get(priority, 0.18)


def compute_freshness_bucket(
    date_posted,
    ingested_at,
    site: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    posted = parse_datetime(date_posted)
    if posted is not None:
        age_days = max(0.0, (now - posted).total_seconds() / 86400)
        if age_days <= 3:
            return "fresh"
        if age_days <= 14:
            return "recent"
        if age_days <= 30:
            return "aging"
        return "stale"

    ingested = parse_datetime(ingested_at)
    if ingested is None:
        return "unknown"

    ingest_days = max(0.0, (now - ingested).total_seconds() / 86400)
    if is_direct_source(site):
        if ingest_days <= 3:
            return "fresh"
        if ingest_days <= 10:
            return "recent"
    else:
        if ingest_days <= 1:
            return "recent"
    if ingest_days <= 21:
        return "aging"
    return "unknown"
