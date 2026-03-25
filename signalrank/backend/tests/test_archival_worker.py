"""Tests for batch.archival_worker — no network calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from batch.archival_worker import (
    _build_user_prompt,
    evaluate_job,
)


def _make_profile(**overrides):
    p = MagicMock()
    p.target_roles = overrides.get("target_roles", ["ML Engineer", "Data Scientist"])
    p.skills = overrides.get("skills", ["Python", "PyTorch", "SQL"])
    p.preferred_locations = overrides.get("preferred_locations", ["Bangalore", "Remote"])
    p.min_yoe = overrides.get("min_yoe", 3)
    p.max_yoe = overrides.get("max_yoe", 12)
    p.role_intent = overrides.get("role_intent", "ML Platform Engineer")
    p.resume_text = "Senior ML engineer with 5 years experience"
    return p


def _make_job(**overrides):
    j = MagicMock()
    j.id = overrides.get("id", "job-1")
    j.title = overrides.get("title", "Senior ML Engineer")
    j.company = overrides.get("company", "Google")
    j.location = overrides.get("location", "Bangalore")
    j.description = overrides.get("description", "Build ML pipelines...")
    return j


def _make_job_result(**overrides):
    jr = MagicMock()
    jr.id = overrides.get("id", "jr-1")
    jr.job_id = overrides.get("job_id", "job-1")
    jr.company_tier = overrides.get("company_tier", "tier_ss")
    jr.is_contract = overrides.get("is_contract", False)
    jr.archived_by_llm = overrides.get("archived_by_llm", None)
    jr.archival_reason = overrides.get("archival_reason", None)
    return jr


def _make_task(**overrides):
    t = MagicMock()
    t.id = overrides.get("id", "task-1")
    t.user_id = overrides.get("user_id", "user-1")
    t.job_result_id = overrides.get("job_result_id", "jr-1")
    t.retry_count = overrides.get("retry_count", 0)
    return t


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------

def test_build_user_prompt_includes_profile_and_job():
    profile = _make_profile()
    job = _make_job()
    jr = _make_job_result()
    prompt = _build_user_prompt(profile, job, jr)
    assert "ML Platform Engineer" in prompt
    assert "ML Engineer" in prompt
    assert "3-12 years" in prompt
    assert "Senior ML Engineer" in prompt
    assert "Google" in prompt
    assert "Bangalore" in prompt


def test_build_user_prompt_handles_empty_profile():
    profile = _make_profile(target_roles=[], skills=[], preferred_locations=[])
    job = _make_job()
    jr = _make_job_result()
    prompt = _build_user_prompt(profile, job, jr)
    assert "CANDIDATE PROFILE" in prompt
    assert "JOB POSTING" in prompt


# ---------------------------------------------------------------------------
# evaluate_job — suitable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_job_suitable():
    task = _make_task()
    jr = _make_job_result()
    profile = _make_profile()
    job = _make_job()

    mock_db = AsyncMock()

    jr_result = MagicMock()
    jr_result.scalar_one_or_none.return_value = jr

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile

    job_result = MagicMock()
    job_result.scalar_one_or_none.return_value = job

    mock_db.execute = AsyncMock(side_effect=[jr_result, profile_result, job_result, MagicMock()])
    mock_db.commit = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock(return_value={"suitable": True, "reason": "Good match for ML engineer role"})

    await evaluate_job(task, mock_db, mock_llm)

    assert jr.archived_by_llm is False
    assert jr.archival_reason == "Good match for ML engineer role"


# ---------------------------------------------------------------------------
# evaluate_job — unsuitable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_job_unsuitable():
    task = _make_task()
    jr = _make_job_result()
    profile = _make_profile()
    job = _make_job(title="VP of Sales", description="Lead enterprise sales team...")

    mock_db = AsyncMock()

    jr_result = MagicMock()
    jr_result.scalar_one_or_none.return_value = jr

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile

    job_result = MagicMock()
    job_result.scalar_one_or_none.return_value = job

    mock_db.execute = AsyncMock(side_effect=[jr_result, profile_result, job_result, MagicMock()])
    mock_db.commit = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock(return_value={"suitable": False, "reason": "Sales role, not engineering"})

    await evaluate_job(task, mock_db, mock_llm)

    assert jr.archived_by_llm is True
    assert jr.archival_reason == "Sales role, not engineering"


# ---------------------------------------------------------------------------
# evaluate_job — already evaluated (idempotent)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_job_already_evaluated_skips():
    task = _make_task()
    jr = _make_job_result(archived_by_llm=False, archival_reason="Previously evaluated")

    mock_db = AsyncMock()
    jr_result = MagicMock()
    jr_result.scalar_one_or_none.return_value = jr
    mock_db.execute = AsyncMock(side_effect=[jr_result, MagicMock()])
    mock_db.commit = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock()

    await evaluate_job(task, mock_db, mock_llm)

    mock_llm.llm_json.assert_not_called()


# ---------------------------------------------------------------------------
# evaluate_job — LLM error triggers retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_job_llm_error_retries():
    task = _make_task(retry_count=0)
    jr = _make_job_result()
    profile = _make_profile()
    job = _make_job()

    mock_db = AsyncMock()

    jr_result = MagicMock()
    jr_result.scalar_one_or_none.return_value = jr
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile
    job_result = MagicMock()
    job_result.scalar_one_or_none.return_value = job

    mock_db.execute = AsyncMock(side_effect=[jr_result, profile_result, job_result, MagicMock()])
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock(return_value={"_error": "llm_failed"})

    await evaluate_job(task, mock_db, mock_llm)

    assert jr.archived_by_llm is None


# ---------------------------------------------------------------------------
# evaluate_job — missing job result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_job_missing_job_result():
    task = _make_task()

    mock_db = AsyncMock()
    jr_result = MagicMock()
    jr_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(side_effect=[jr_result, MagicMock()])
    mock_db.commit = AsyncMock()

    mock_llm = MagicMock()
    await evaluate_job(task, mock_db, mock_llm)
    mock_llm.llm_json.assert_not_called()


# ---------------------------------------------------------------------------
# evaluate_job — missing profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_job_missing_profile():
    task = _make_task()
    jr = _make_job_result()

    mock_db = AsyncMock()
    jr_result = MagicMock()
    jr_result.scalar_one_or_none.return_value = jr
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(side_effect=[jr_result, profile_result, MagicMock()])
    mock_db.commit = AsyncMock()

    mock_llm = MagicMock()
    await evaluate_job(task, mock_db, mock_llm)
    mock_llm.llm_json.assert_not_called()
