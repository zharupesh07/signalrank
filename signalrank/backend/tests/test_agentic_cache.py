import pytest
from types import SimpleNamespace

from batch.ranker import _is_valid_match_report, _is_valid_verification_report, _llm_model_version
from domain.artifact_versions import (
    MATCH_JUDGE_PROMPT_VERSION,
    MATCH_REPORT_VERSION,
    MATCH_VERIFIER_PROMPT_VERSION,
    SCHEMA_VERSION,
    VERIFICATION_REPORT_VERSION,
    match_report_cache_key,
    verification_report_cache_key,
)

pytestmark = pytest.mark.unit


def _candidate():
    return {"profile_fingerprint": "cand-fp", "profile_cache_key": "cand-cache"}


def _job():
    return {"job_fingerprint": "job-fp", "job_cache_key": "job-cache"}


def test_llm_model_version_fingerprints_model_list():
    client = SimpleNamespace(models=["model-a", "model-b"], preferred_models=["model-a"])
    assert _llm_model_version(client) != "heuristic"


def test_match_report_cache_validation_checks_versions_and_key():
    candidate = _candidate()
    job = _job()
    key = match_report_cache_key(
        candidate_profile_fingerprint=candidate["profile_fingerprint"],
        job_profile_fingerprint=job["job_fingerprint"],
        judge_model_version="model-v1",
        prompt_version=MATCH_JUDGE_PROMPT_VERSION,
    )
    report = {
        "artifact_version": MATCH_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_JUDGE_PROMPT_VERSION,
        "match_cache_key": key,
    }
    assert _is_valid_match_report(report, candidate, job, "model-v1")
    assert not _is_valid_match_report(report, candidate, job, "model-v2")


def test_verification_report_cache_validation_checks_versions_and_key():
    candidate = _candidate()
    job = _job()
    key = verification_report_cache_key(
        candidate_profile_fingerprint=candidate["profile_fingerprint"],
        job_profile_fingerprint=job["job_fingerprint"],
        verifier_model_version="model-v1",
        prompt_version=MATCH_VERIFIER_PROMPT_VERSION,
    )
    report = {
        "artifact_version": VERIFICATION_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_VERIFIER_PROMPT_VERSION,
        "verification_cache_key": key,
    }
    assert _is_valid_verification_report(report, candidate, job, "model-v1")
    assert not _is_valid_verification_report(report, candidate, job, "model-v2")
