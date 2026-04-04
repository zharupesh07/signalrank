from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import JobRaw, Profile
from api.routes.onboarding import _extract_text_from_pdf
from domain.resume_editor import has_resume_editor_content
from batch.scraper import RawJob
from batch.worker import process_run
from llm.resume_parser import ResumeParseResult


RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


@dataclass(frozen=True)
class ResumeFlowCase:
    key: str
    pdf_name: str
    expected_role: str
    expected_archetype: str
    expected_query_keywords: tuple[str, ...]
    expected_exclusion: str | None
    top_job_titles: tuple[str, ...]


CASES: tuple[ResumeFlowCase, ...] = (
    ResumeFlowCase(
        key="abhijeet",
        pdf_name="Abhijeet_CV.pdf",
        expected_role="AI/Machine Learning Engineer",
        expected_archetype="ai_ml_engineer",
        expected_query_keywords=("machine learning", "ai/ml"),
        expected_exclusion="QA Automation",
        top_job_titles=(
            "AI/Machine Learning Engineer",
            "Machine Learning Engineer II",
            "Data Scientist - Machine Learning",
        ),
    ),
    ResumeFlowCase(
        key="example",
        pdf_name="Example_Candidate_Resume_V2_2.pdf",
        expected_role="AI Platform Engineer",
        expected_archetype="ai_platform_engineer",
        expected_query_keywords=("ai platform", "mlops", "platform"),
        expected_exclusion="QA Automation",
        top_job_titles=(
            "AI Platform Engineer",
            "MLOps Engineer",
            "Forward Deployed Engineer, AI Platform",
        ),
    ),
    ResumeFlowCase(
        key="vivek",
        pdf_name="Vivek-Gupta-Emerging-Technologies.pdf",
        expected_role="Innovation Engineer",
        expected_archetype="innovation_rd_engineer",
        expected_query_keywords=("innovation", "emerging technologies", "r&d"),
        expected_exclusion="Generic Software Engineer",
        top_job_titles=(
            "Innovation Engineer",
            "Emerging Technologies Engineer",
            "R&D Engineer",
        ),
    ),
    ResumeFlowCase(
        key="aditya",
        pdf_name="aditya.pdf",
        expected_role="Network Automation Engineer",
        expected_archetype="network_automation_engineer",
        expected_query_keywords=("network automation", "infrastructure automation", "cloud network"),
        expected_exclusion="AI Platform Engineer",
        top_job_titles=(
            "Network Automation Engineer",
            "Infrastructure Automation Engineer",
            "Cloud Network Engineer",
        ),
    ),
    ResumeFlowCase(
        key="ayush",
        pdf_name="ayush_resume_new.pdf",
        expected_role="SAP SD Consultant",
        expected_archetype="erp_functional_consultant",
        expected_query_keywords=("sap sd", "sap otc", "s/4hana"),
        expected_exclusion="QA Automation",
        top_job_titles=(
            "SAP SD Consultant",
            "SAP OTC Functional Consultant",
            "SAP S/4HANA SD Consultant",
        ),
    ),
)


def _load_spec(case: ResumeFlowCase) -> dict:
    return json.loads((RESUMES_DIR / case.pdf_name).with_suffix(".json").read_text())


def _editor_from_spec(spec: dict) -> dict:
    return {
        "name": spec["name"],
        "email": spec["email"],
        "phone": spec["phone"],
        "location": spec["location"],
        "linkedin": spec["linkedin"],
        "github": spec["github"],
        "website": spec["website"],
        "position": spec.get("position") or spec.get("label") or "",
        "summary": spec.get("summary") or "",
        "experiences": spec.get("experiences") or [],
        "skills": spec.get("skills") or [],
        "projects": spec.get("projects") or [],
        "education": spec.get("education") or [],
        "certifications": spec.get("certifications") or [],
    }


def _flatten_skill_items(spec: dict) -> list[str]:
    skills: list[str] = []
    for group in spec.get("skills") or []:
        skills.extend([str(item).strip() for item in group.get("items", []) if str(item).strip()])
    return skills[:12]


def _years_for_case(case: ResumeFlowCase) -> int:
    return {
        "abhijeet": 4,
        "example": 7,
        "vivek": 10,
        "aditya": 8,
        "ayush": 9,
    }[case.key]


def _locations_for_spec(spec: dict) -> list[str]:
    location = str(spec.get("location") or "").strip()
    if not location:
        return []
    primary = location.split(",")[0].strip()
    return [primary] if primary else [location]


def _parse_payload_for_case(case: ResumeFlowCase, spec: dict) -> ResumeParseResult:
    exclusions = [case.expected_exclusion] if case.expected_exclusion else []
    return ResumeParseResult(
        skills=_flatten_skill_items(spec),
        years_of_experience=_years_for_case(case),
        recent_titles=[exp["title"] for exp in (spec.get("experiences") or [])[:2] if exp.get("title")],
        industries=[],
        education=[edu.get("degree", "") for edu in (spec.get("education") or []) if edu.get("degree")],
        suggested_roles=[case.expected_role],
        suggested_locations=_locations_for_spec(spec),
        salary_lpa=24,
        suggested_exclusions=exclusions,
        suggested_search_queries=list(case.expected_query_keywords[:3]),
        career_archetypes=[
            {
                "id": case.expected_archetype,
                "label": case.expected_role,
                "priority": "primary",
                "confidence": 0.95,
                "evidence": [case.expected_role],
            }
        ],
        target_roles=[
            {
                "title": case.expected_role,
                "priority": "primary",
                "confidence": 0.98,
                "evidence": [case.expected_role],
            }
        ],
        domains=[],
        negative_targets=(
            [
                {
                    "label": case.expected_exclusion,
                    "reason": "Fixture-driven exclusion to preserve role precision.",
                    "confidence": 0.9,
                }
            ]
            if case.expected_exclusion
            else []
        ),
        false_friend_terms=[],
        query_plan={
            "title_queries": [case.expected_role, *case.top_job_titles[:2]],
            "skill_queries": list(case.expected_query_keywords[:2]),
            "domain_queries": [],
            "negative_keywords": exclusions,
        },
        ambiguities=[],
        follow_up_questions=[],
    )


def _email_to_case_map() -> dict[str, ResumeFlowCase]:
    mapping: dict[str, ResumeFlowCase] = {}
    for case in CASES:
        spec = _load_spec(case)
        mapping[str(spec["email"]).lower()] = case
    return mapping


EMAIL_TO_CASE = _email_to_case_map()
CASE_TO_SPEC = {case.key: _load_spec(case) for case in CASES}


def _detect_case_from_resume_text(resume_text: str) -> ResumeFlowCase:
    match = _EMAIL_RE.search(resume_text or "")
    if not match:
        raise AssertionError("Could not identify resume fixture from extracted text")
    email = match.group(0).lower()
    if email not in EMAIL_TO_CASE:
        raise AssertionError(f"Unexpected fixture email in resume text: {email}")
    return EMAIL_TO_CASE[email]


def _scraped_jobs_for_case(case: ResumeFlowCase) -> list[RawJob]:
    now = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
    jobs: list[RawJob] = []
    for idx, title in enumerate(case.top_job_titles, start=1):
        jobs.append(
            RawJob(
                job_url=f"https://example.com/{case.key}/{idx}",
                title=title,
                company=f"{case.key.title()} Corp {idx}",
                description=f"{title} role aligned to {case.expected_role}.",
                location="Remote",
                site="indeed",
                date_posted=now,
            )
        )
    jobs.append(
        RawJob(
            job_url=f"https://example.com/{case.key}/irrelevant",
            title="Unrelated Generalist Role",
            company="Noise Inc",
            description="Low relevance control job.",
            location="Remote",
            site="indeed",
            date_posted=now,
        )
    )
    return jobs


def _ranked_df_for_case(case: ResumeFlowCase, job_ids_by_url: dict[str, str]) -> pd.DataFrame:
    rows: list[dict] = []
    ranked_urls = [f"https://example.com/{case.key}/{idx}" for idx in range(1, 4)]
    ranked_scores = [96.0, 90.0, 84.0]
    for url, score in zip(ranked_urls, ranked_scores):
        rows.append(
            {
                "id": job_ids_by_url[url],
                "semantic_score": round(score / 100, 2),
                "skills_score": score - 8,
                "company_score": score - 10,
                "seniority_score_dim": score - 12,
                "location_score": 100.0,
                "recency_score": 92.0,
                "final_score": score,
                "title_relevance_score": score - 4,
                "company_tier": "tier_a",
                "is_contract": False,
            }
        )
    rows.append(
        {
            "id": job_ids_by_url[f"https://example.com/{case.key}/irrelevant"],
            "semantic_score": 0.22,
            "skills_score": 18.0,
            "company_score": 20.0,
            "seniority_score_dim": 15.0,
            "location_score": 100.0,
            "recency_score": 88.0,
            "final_score": 28.0,
            "title_relevance_score": 12.0,
            "company_tier": "tier_c",
            "is_contract": False,
        }
    )
    return pd.DataFrame(rows)


async def _register_and_login(client, case: ResumeFlowCase) -> str:
    spec = CASE_TO_SPEC[case.key]
    password = "password123"
    register = await client.post(
        "/api/auth/register",
        json={"email": spec["email"], "password": password},
    )
    assert register.status_code == 201
    login = await client.post(
        "/api/auth/login",
        json={"email": spec["email"], "password": password},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


async def _wait_for_prefill(client, token: str, db: AsyncSession) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(10):
        db.expire_all()
        response = await client.get("/api/onboarding/parsed", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        if payload["parsing"] is False:
            return payload["prefill"]
        await asyncio.sleep(0)
    raise AssertionError("Timed out waiting for onboarding parse to finish")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
async def test_resume_fixture_backend_chain_allows_results_and_tracker_import(
    case: ResumeFlowCase,
    client,
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    import api.routes.onboarding as onboarding_route
    import api.routes.runs as runs_route
    import batch.ranker as ranker
    import batch.scraper as scraper
    import batch.worker as worker_mod

    token = await _register_and_login(client, case)
    headers = {"Authorization": f"Bearer {token}"}

    async def fake_parse_resume(resume_text: str, _llm_client):
        detected = _detect_case_from_resume_text(resume_text)
        return _parse_payload_for_case(detected, CASE_TO_SPEC[detected.key])

    async def fake_parse_resume_structure(resume_text: str, _llm_client):
        detected = _detect_case_from_resume_text(resume_text)
        return _editor_from_spec(CASE_TO_SPEC[detected.key])

    async def fake_parse_resume_from_images(_images, _llm_client, reference_text=None, **_kwargs):
        detected = _detect_case_from_resume_text(reference_text or "")
        return _editor_from_spec(CASE_TO_SPEC[detected.key])

    async def noop_embed_resume(*_args, **_kwargs):
        return None

    async def fake_embed_new_jobs(*_args, **_kwargs):
        return None

    async def fake_scrape(queries, _config, on_progress=None, on_persist=None, *, return_mode="jobs", db=None, **_kwargs):
        del db
        assert return_mode == "urls"
        assert queries, f"{case.key}: query builder returned no queries"
        query_terms = [q.term.lower() for q in queries]
        assert any(
            keyword.lower() in term
            for keyword in case.expected_query_keywords
            for term in query_terms
        ), f"{case.key}: queries {query_terms} did not include expected intent markers"
        jobs = _scraped_jobs_for_case(case)
        if on_progress:
            await on_progress(
                phase="jobspy_indeed",
                phase_num=1,
                total_phases=1,
                jobs_found=len(jobs),
                message="Fixture scrape",
            )
        if on_persist:
            await on_persist(jobs)
        return [job.job_url for job in jobs]

    async def fake_score_jobs_for_user(*, db, user_id, resume_text, distilled_text, config_overrides, job_urls=None):
        del user_id, resume_text, distilled_text, config_overrides
        assert job_urls, f"{case.key}: worker did not pass freshly scraped URLs to ranker"
        result = await db.execute(select(JobRaw.id, JobRaw.job_url).where(JobRaw.job_url.in_(list(job_urls))))
        rows = result.all()
        job_ids_by_url = {row.job_url: str(row.id) for row in rows}
        assert len(job_ids_by_url) == len(job_urls), f"{case.key}: expected persisted jobs for all scraped URLs"
        return _ranked_df_for_case(case, job_ids_by_url)

    async def noop_parse_and_update_profile(*_args, **_kwargs):
        return None

    monkeypatch.setattr(onboarding_route, "parse_resume", fake_parse_resume)
    monkeypatch.setattr(onboarding_route, "parse_resume_structure", fake_parse_resume_structure)
    monkeypatch.setattr(onboarding_route, "parse_resume_from_images", fake_parse_resume_from_images)
    monkeypatch.setattr(onboarding_route, "_parse_and_update_profile", noop_parse_and_update_profile)
    monkeypatch.setattr(onboarding_route, "_embed_resume", noop_embed_resume)
    monkeypatch.setattr(worker_mod, "_embed_new_jobs", fake_embed_new_jobs)
    monkeypatch.setattr(scraper, "scrape", fake_scrape)
    monkeypatch.setattr(ranker, "score_jobs_for_user", fake_score_jobs_for_user)
    monkeypatch.setattr(runs_route, "api_runtime_flags", lambda: {"run_api_worker": False})

    pdf_bytes = (RESUMES_DIR / case.pdf_name).read_bytes()
    upload = await client.post(
        "/api/onboarding/resume",
        files={"file": (case.pdf_name, pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 200
    assert upload.json()["parsing"] is False

    db.expire_all()
    profile_result = await client.get("/api/profile", headers=headers)
    assert profile_result.status_code == 200
    uploaded_profile = profile_result.json()
    parsed = await fake_parse_resume(uploaded_profile["resume_text"], None)
    editor = await fake_parse_resume_structure(uploaded_profile["resume_text"], None)
    profile = (
        await db.execute(select(Profile).where(Profile.user_id == uploaded_profile["user_id"]))
    ).scalar_one()
    onboarding_route._apply_parsed_profile_updates(profile, parsed)
    overrides = dict(profile.config_overrides or {})
    if has_resume_editor_content(editor):
        overrides["resume_editor"] = editor
    profile.config_overrides = overrides
    onboarding_route._set_onboarding_parse_status(profile, "done")
    await db.commit()

    prefill = await _wait_for_prefill(client, token, db)
    assert prefill["target_roles"], f"{case.key}: onboarding prefill missing target roles"
    assert prefill["target_roles"][0] == case.expected_role
    assert prefill["career_intent"]["career_archetypes"][0]["id"] == case.expected_archetype
    if case.expected_exclusion:
        assert case.expected_exclusion in prefill["exclusions"]

    profile_before = await client.get("/api/profile", headers=headers)
    assert profile_before.status_code == 200
    assert profile_before.json()["onboarding_complete"] is False

    refine_roles = await client.post(
        "/api/onboarding/refine",
        json={"question_id": "target_roles", "answer": prefill["target_roles"]},
        headers=headers,
    )
    assert refine_roles.status_code == 200

    if prefill["preferred_locations"]:
        refine_locations = await client.post(
            "/api/onboarding/refine",
            json={"question_id": "preferred_locations", "answer": prefill["preferred_locations"]},
            headers=headers,
        )
        assert refine_locations.status_code == 200

    if prefill["exclusions"]:
        refine_exclusions = await client.post(
            "/api/onboarding/refine",
            json={"question_id": "exclusions", "answer": prefill["exclusions"]},
            headers=headers,
        )
        assert refine_exclusions.status_code == 200

    finish_onboarding = await client.post(
        "/api/onboarding/refine",
        json={"question_id": "onboarding_complete", "answer": "true"},
        headers=headers,
    )
    assert finish_onboarding.status_code == 200

    profile_after = await client.get("/api/profile", headers=headers)
    assert profile_after.status_code == 200
    profile_payload = profile_after.json()
    assert profile_payload["onboarding_complete"] is True
    assert profile_payload["career_intent"]["target_roles"][0]["title"] == case.expected_role

    trigger = await client.post(
        "/api/runs/trigger",
        json={"mode": "quick"},
        headers=headers,
    )
    assert trigger.status_code == 202
    run_id = trigger.json()["run_id"]

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    await process_run(run_id, profile_payload["user_id"], session_factory, mode="quick")
    db.expire_all()

    status_response = await client.get(f"/api/runs/{run_id}/status", headers=headers)
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "done"
    assert status_payload["job_count"] == 4

    jobs_response = await client.get("/api/jobs?limit=10", headers=headers)
    assert jobs_response.status_code == 200
    jobs_payload = jobs_response.json()
    assert jobs_payload["total"] == 4
    assert [job["title"] for job in jobs_payload["jobs"][:3]] == list(case.top_job_titles)
    assert jobs_payload["jobs"][0]["final_score"] == pytest.approx(0.96)

    import_response = await client.post(
        "/api/applications/import-from-run",
        json={"run_id": run_id, "min_score": 0.6, "limit": 10},
        headers=headers,
    )
    assert import_response.status_code == 200
    assert import_response.json()["created"] == 3
    assert import_response.json()["skipped"] == 0

    applications_response = await client.get("/api/applications", headers=headers)
    assert applications_response.status_code == 200
    applications = applications_response.json()["applications"]
    assert len(applications) == 3
    assert {app["title"] for app in applications} == set(case.top_job_titles)

    refreshed = (
        await db.execute(select(Profile).where(Profile.user_id == profile_payload["user_id"]))
    ).scalar_one()
    assert refreshed is not None
    assert refreshed.onboarding_complete is True
