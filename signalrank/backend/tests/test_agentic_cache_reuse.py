import pandas as pd
import pytest
from unittest.mock import AsyncMock, patch

from batch.ranker import _judge_selected_jobs, _verify_selected_jobs
from domain.artifact_versions import (
    MATCH_JUDGE_PROMPT_VERSION,
    MATCH_VERIFIER_PROMPT_VERSION,
    MATCH_REPORT_VERSION,
    SCHEMA_VERSION,
    VERIFICATION_REPORT_VERSION,
    match_report_cache_key,
    verification_report_cache_key,
)

pytestmark = pytest.mark.unit


def _candidate_profile() -> dict:
    return {"profile_fingerprint": "cand-fp", "profile_cache_key": "cand-cache"}


def _job_profile() -> dict:
    return {"job_fingerprint": "job-fp", "job_cache_key": "job-cache"}


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": "job-1",
                "title": "AI Platform Engineer",
                "company": "Example",
                "description": "Build ML platform systems",
                "location": "Remote",
                "site": "indeed",
                "job_profile": _job_profile(),
            }
        ]
    )


@pytest.mark.asyncio
async def test_judge_selected_jobs_uses_cached_match_report():
    candidate = _candidate_profile()
    job = _job_profile()
    cache_key = match_report_cache_key(
        candidate_profile_fingerprint=candidate["profile_fingerprint"],
        job_profile_fingerprint=job["job_fingerprint"],
        judge_model_version="model-v1",
        prompt_version=MATCH_JUDGE_PROMPT_VERSION,
    )
    cached_match = {
        "artifact_version": MATCH_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_JUDGE_PROMPT_VERSION,
        "match_cache_key": cache_key,
        "verdict": "strong_fit",
        "confidence": 0.9,
        "skill_evidence_present": True,
        "skill_gaps": [],
        "seniority_fit": "aligned",
        "location_fit": "aligned",
        "risk_flags": [],
        "why_rank_up": [],
        "why_rank_down": [],
        "target_lane_fit": "direct",
        "cited_resume_evidence": [{"source": "resume", "text": "ML"}],
        "cited_job_evidence": [{"source": "job", "text": "platform"}],
        "explanation_summary": "cached",
    }
    df = _df()

    with patch("batch.ranker.judge_match_report", AsyncMock()) as mocked_judge:
        reports = await _judge_selected_jobs(
            df,
            selected_indices=[0],
            candidate_profile=candidate,
            resume_text="resume text",
            cfg={"ranking": {"agentic_matching": {"max_judge_tokens": 100}}},
            llm_client=None,
            model_version="model-v1",
            persisted_job_profiles={"job-1": job},
            cached_match_reports={"job-1": cached_match},
        )

    assert reports[0]["cache_hit"] is True
    mocked_judge.assert_not_called()


@pytest.mark.asyncio
async def test_verify_selected_jobs_uses_cached_verification_only_for_cached_match():
    candidate = _candidate_profile()
    job = _job_profile()
    match_key = match_report_cache_key(
        candidate_profile_fingerprint=candidate["profile_fingerprint"],
        job_profile_fingerprint=job["job_fingerprint"],
        judge_model_version="model-v1",
        prompt_version=MATCH_JUDGE_PROMPT_VERSION,
    )
    ver_key = verification_report_cache_key(
        candidate_profile_fingerprint=candidate["profile_fingerprint"],
        job_profile_fingerprint=job["job_fingerprint"],
        verifier_model_version="model-v1",
        prompt_version=MATCH_VERIFIER_PROMPT_VERSION,
    )
    match_report = {
        "artifact_version": MATCH_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_JUDGE_PROMPT_VERSION,
        "match_cache_key": match_key,
        "cache_hit": True,
        "verdict": "strong_fit",
        "confidence": 0.9,
        "skill_evidence_present": True,
        "skill_gaps": [],
        "seniority_fit": "aligned",
        "location_fit": "aligned",
        "risk_flags": [],
        "why_rank_up": [],
        "why_rank_down": [],
        "target_lane_fit": "direct",
        "cited_resume_evidence": [{"source": "resume", "text": "ML"}],
        "cited_job_evidence": [{"source": "job", "text": "platform"}],
        "explanation_summary": "cached",
    }
    cached_verification = {
        "artifact_version": VERIFICATION_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_VERIFIER_PROMPT_VERSION,
        "verification_cache_key": ver_key,
        "evidence_grounded": True,
        "unsupported_claims": [],
        "final_confidence_adjustment": 0.0,
        "status": "pass",
    }
    df = _df()
    selected_rows = [df.loc[0]]

    with patch("batch.ranker.verify_match_report", AsyncMock()) as mocked_verify:
        reports = await _verify_selected_jobs(
            [match_report],
            selected_rows,
            candidate_profile=candidate,
            cfg={"ranking": {"agentic_matching": {"max_verifier_tokens": 100}}},
            llm_client=None,
            model_version="model-v1",
            persisted_job_profiles={"job-1": job},
            verifier_indices=[0],
            cached_verification_reports={"job-1": cached_verification},
        )

    assert reports[0]["cache_hit"] is True
    mocked_verify.assert_not_called()


@pytest.mark.asyncio
async def test_verify_selected_jobs_recomputes_when_match_is_not_cached():
    candidate = _candidate_profile()
    job = _job_profile()
    match_report = {
        "artifact_version": MATCH_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_JUDGE_PROMPT_VERSION,
        "match_cache_key": "stale",
        "cache_hit": False,
        "verdict": "strong_fit",
        "confidence": 0.9,
        "skill_evidence_present": True,
        "skill_gaps": [],
        "seniority_fit": "aligned",
        "location_fit": "aligned",
        "risk_flags": [],
        "why_rank_up": [],
        "why_rank_down": [],
        "target_lane_fit": "direct",
        "cited_resume_evidence": [{"source": "resume", "text": "ML"}],
        "cited_job_evidence": [{"source": "job", "text": "platform"}],
        "explanation_summary": "fresh",
    }
    df = _df()
    selected_rows = [df.loc[0]]

    mocked_verify = AsyncMock(
        return_value={
            "artifact_version": VERIFICATION_REPORT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "prompt_version": MATCH_VERIFIER_PROMPT_VERSION,
            "verification_cache_key": "new",
            "evidence_grounded": True,
            "unsupported_claims": [],
            "final_confidence_adjustment": 0.0,
            "status": "pass",
        }
    )
    with patch("batch.ranker.verify_match_report", mocked_verify):
        reports = await _verify_selected_jobs(
            [match_report],
            selected_rows,
            candidate_profile=candidate,
            cfg={"ranking": {"agentic_matching": {"max_verifier_tokens": 100}}},
            llm_client=None,
            model_version="model-v1",
            persisted_job_profiles={"job-1": job},
            verifier_indices=[0],
            cached_verification_reports={"job-1": {"verification_cache_key": "new"}},
        )

    assert reports[0]["verification_cache_key"] == "new"
    mocked_verify.assert_awaited_once()
