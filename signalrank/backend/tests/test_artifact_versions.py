import pytest

from domain.artifact_versions import (
    CANDIDATE_PROFILE_VERSION,
    JOB_PROFILE_VERSION,
    MATCH_JUDGE_PROMPT_VERSION,
    MATCH_REPORT_VERSION,
    MATCH_VERIFIER_PROMPT_VERSION,
    SCHEMA_VERSION,
    VERIFICATION_REPORT_VERSION,
    candidate_profile_cache_key,
    job_profile_cache_key,
    match_report_cache_key,
    query_plan_cache_key,
    stable_digest,
    verification_report_cache_key,
)


pytestmark = pytest.mark.unit


def test_stable_digest_is_deterministic():
    payload = {"b": 2, "a": 1}
    assert stable_digest(payload) == stable_digest({"a": 1, "b": 2})
    assert len(stable_digest(payload)) == 64


def test_candidate_and_job_cache_keys_are_versioned():
    candidate_key = candidate_profile_cache_key(resume_fingerprint="resume-fp")
    job_key = job_profile_cache_key(job_fingerprint="job-fp")

    assert len(candidate_key) == 64
    assert len(job_key) == 64
    assert candidate_key != job_key
    assert CANDIDATE_PROFILE_VERSION.startswith("candidate_profile_")
    assert JOB_PROFILE_VERSION.startswith("job_profile_")
    assert SCHEMA_VERSION == 1


def test_match_and_verification_cache_keys_include_model_and_prompt_versions():
    match_key = match_report_cache_key(
        candidate_profile_fingerprint="candidate-fp",
        job_profile_fingerprint="job-fp",
        judge_model_version="model-v1",
        prompt_version=MATCH_JUDGE_PROMPT_VERSION,
    )
    verification_key = verification_report_cache_key(
        candidate_profile_fingerprint="candidate-fp",
        job_profile_fingerprint="job-fp",
        verifier_model_version="model-v1",
        prompt_version=MATCH_VERIFIER_PROMPT_VERSION,
    )
    query_key = query_plan_cache_key(
        profile_fingerprint="profile-fp",
        search_window_days=15,
        source_filter="jobspy_indeed",
    )

    assert len(match_key) == 64
    assert len(verification_key) == 64
    assert len(query_key) == 64
    assert match_key != verification_key
    assert MATCH_REPORT_VERSION.startswith("match_report_")
    assert VERIFICATION_REPORT_VERSION.startswith("verification_report_")
