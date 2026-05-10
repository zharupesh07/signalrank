from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = 1

CANDIDATE_PROFILE_VERSION = "candidate_profile_v2"
JOB_PROFILE_VERSION = "job_profile_v2"
PROFILE_INTENT_VERSION = "profile_intent_v1"
JOB_INTENT_VERSION = "job_intent_v1"
MATCH_DECISION_VERSION = "match_decision_v1"
MATCH_REPORT_VERSION = "match_report_v2"
VERIFICATION_REPORT_VERSION = "verification_report_v2"

MATCH_JUDGE_PROMPT_VERSION = "match_judge_prompt_v1"
MATCH_VERIFIER_PROMPT_VERSION = "match_verifier_prompt_v1"

QUERY_PLAN_VERSION = "query_plan_v3"


def stable_digest(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def candidate_profile_cache_key(
    *, resume_fingerprint: str, profile_version: str = CANDIDATE_PROFILE_VERSION
) -> str:
    return stable_digest(
        {
            "kind": "candidate_profile",
            "resume_fingerprint": resume_fingerprint,
            "profile_version": profile_version,
            "schema_version": SCHEMA_VERSION,
        }
    )


def job_profile_cache_key(
    *, job_fingerprint: str, profile_version: str = JOB_PROFILE_VERSION
) -> str:
    return stable_digest(
        {
            "kind": "job_profile",
            "job_fingerprint": job_fingerprint,
            "profile_version": profile_version,
            "schema_version": SCHEMA_VERSION,
        }
    )


def match_report_cache_key(
    *,
    candidate_profile_fingerprint: str,
    job_profile_fingerprint: str,
    judge_model_version: str,
    prompt_version: str = MATCH_JUDGE_PROMPT_VERSION,
) -> str:
    return stable_digest(
        {
            "kind": "match_report",
            "candidate_profile_fingerprint": candidate_profile_fingerprint,
            "job_profile_fingerprint": job_profile_fingerprint,
            "judge_model_version": judge_model_version,
            "prompt_version": prompt_version,
            "schema_version": SCHEMA_VERSION,
        }
    )


def verification_report_cache_key(
    *,
    candidate_profile_fingerprint: str,
    job_profile_fingerprint: str,
    verifier_model_version: str,
    prompt_version: str = MATCH_VERIFIER_PROMPT_VERSION,
) -> str:
    return stable_digest(
        {
            "kind": "verification_report",
            "candidate_profile_fingerprint": candidate_profile_fingerprint,
            "job_profile_fingerprint": job_profile_fingerprint,
            "verifier_model_version": verifier_model_version,
            "prompt_version": prompt_version,
            "schema_version": SCHEMA_VERSION,
        }
    )


def query_plan_cache_key(
    *,
    profile_fingerprint: str,
    search_window_days: int,
    source_filter: str,
    query_version: str = QUERY_PLAN_VERSION,
) -> str:
    return stable_digest(
        {
            "kind": "query_plan",
            "profile_fingerprint": profile_fingerprint,
            "search_window_days": search_window_days,
            "source_filter": source_filter,
            "query_version": query_version,
            "schema_version": SCHEMA_VERSION,
        }
    )
