from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, JobResult, Profile, Run, User
from batch import career_ops_import
from batch.career_ops_import import (
    CareerOpsCandidate,
    EnrichedCareerOpsJob,
    _extract_job_posting_fields,
    _parse_job_url_hints,
    enrich_career_ops_candidates,
    import_career_ops_workspace,
    parse_career_ops_pipeline,
)
from domain.job_profile import build_job_profile


def _write_pipeline(workspace: Path, lines: list[str]) -> None:
    data_dir = workspace / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pipeline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_career_ops_pipeline_supports_urls_and_local_refs(tmp_path: Path):
    _write_pipeline(
        tmp_path,
        [
            "- [ ] https://example.com/jobs/1 | Example | Senior ML Engineer",
            "- [x] https://jobs.ashbyhq.com/acme/123 | Acme | Applied AI Engineer",
            "- [ ] local:jds/acme-ml.md | Acme | Saved JD",
            "not a pipeline row",
        ],
    )

    all_rows = parse_career_ops_pipeline(tmp_path, pending_only=False)
    pending_rows = parse_career_ops_pipeline(tmp_path, pending_only=True)

    assert len(all_rows) == 3
    assert len(pending_rows) == 2
    assert all_rows[1].checked is True
    assert all_rows[2].is_local_jd is True
    assert all_rows[2].local_path == tmp_path / "jds" / "acme-ml.md"
    assert all_rows[2].canonical_job_url.startswith("manual://career-ops/")


def test_parse_job_url_hints_recovers_title_and_location():
    hints = _parse_job_url_hints(
        "https://careers.fisglobal.com/job/IND-PUNE-FL7/Engineer-Lead--Artificial-Intelligence---Machine-Learning--GitHub-Copilot-_JR0305474"
    )

    assert hints["location"] == "Pune, India"
    assert hints["title"] == "Engineer Lead Artificial Intelligence Machine Learning GitHub Copilot"


def test_extract_job_posting_fields_falls_back_from_generic_careers_shell():
    html = """
    <html>
      <head>
        <title>Careers at Mastercard</title>
        <meta name="description" content="Explore exciting career opportunities with jobs at Mastercard. Find your dream job and kickstart your Mastercard career today!">
      </head>
      <body>Homepage shell only</body>
    </html>
    """

    fields = _extract_job_posting_fields(
        html,
        "Lead AI Engineer",
        "Mastercard",
        "https://careers.mastercard.com/job/Pune-India/Lead-AI-Engineer_R-274562",
    )

    assert fields["title"] == "Lead AI Engineer"
    assert fields["location"] == "Pune, India"
    assert "Company: Mastercard" in fields["description"]


@pytest.mark.asyncio
async def test_enrich_career_ops_candidates_reads_local_jd(tmp_path: Path):
    jd_dir = tmp_path / "jds"
    jd_dir.mkdir(parents=True, exist_ok=True)
    jd_path = jd_dir / "agentic-ai.md"
    jd_path.write_text(
        "\n".join(
            [
                "Agentic AI Engineer",
                "Bengaluru, India",
                "Remote option available",
                "Build machine learning systems with Python, Kubernetes, and LLM orchestration.",
            ]
        ),
        encoding="utf-8",
    )

    candidate = CareerOpsCandidate(
        source_ref="local:jds/agentic-ai.md",
        canonical_job_url="manual://career-ops/test/jds/agentic-ai.md",
        title="Agentic AI Engineer",
        company="Acme AI",
        checked=False,
        is_local_jd=True,
        local_path=jd_path,
    )

    enriched, errors = await enrich_career_ops_candidates([candidate], workspace_path=tmp_path)

    assert errors == []
    assert len(enriched) == 1
    assert enriched[0].site == "manual"
    assert "Python" in enriched[0].description
    assert enriched[0].job_profile["role_family"] == "AI / ML"
    assert enriched[0].job_profile["work_mode"] == "remote"


@pytest.mark.asyncio
async def test_import_career_ops_workspace_upserts_and_scores(tmp_path: Path, db: AsyncSession, monkeypatch):
    workspace = tmp_path / "career-ops"
    _write_pipeline(
        workspace,
        [
            "- [ ] https://example.com/jobs/existing | Example | Senior ML Engineer",
            "- [ ] https://example.com/jobs/new | NewCo | Applied AI Engineer",
        ],
    )

    user = User(email="careerops@test.com", password_hash="x")
    db.add(user)
    await db.flush()
    user_id = user.id
    profile = Profile(
        user_id=user_id,
        resume_text="Senior AI platform engineer with Python, LLM, and MLOps experience.",
        distilled_text="AI platform engineer",
        config_overrides={},
        onboarding_complete=True,
    )
    existing_job = JobRaw(
        job_url="https://example.com/jobs/existing",
        title="Old Title",
        company="Example",
        description="Old description",
        location="Remote",
        site="company",
        job_profile=build_job_profile(
            title="Old Title",
            company="Example",
            description="Old description",
            location="Remote",
            site="company",
            cfg={},
        ),
        role_clusters=["general"],
    )
    previous_run = Run(user_id=user_id, status="success", mode="quick")
    db.add_all([profile, existing_job, previous_run])
    await db.flush()
    db.add(
            JobResult(
                run_id=previous_run.id,
                user_id=user_id,
                job_id=existing_job.id,
            final_score=10.0,
            semantic_score=10.0,
        )
    )
    await db.commit()

    enriched_jobs = [
        EnrichedCareerOpsJob(
            source_ref="https://example.com/jobs/existing",
            job_url="https://example.com/jobs/existing",
            title="Senior ML Engineer",
            company="Example",
            location="Bangalore, India",
            description="Build ML systems with Python and Kubernetes.",
            site="company",
            date_posted=None,
            role_clusters=["ai_ml"],
            job_profile=build_job_profile(
                title="Senior ML Engineer",
                company="Example",
                description="Build ML systems with Python and Kubernetes.",
                location="Bangalore, India",
                site="company",
                role_clusters=["ai_ml"],
                cfg={},
            ),
        ),
        EnrichedCareerOpsJob(
            source_ref="https://example.com/jobs/new",
            job_url="https://example.com/jobs/new",
            title="Applied AI Engineer",
            company="NewCo",
            location="Pune, India",
            description="Own applied AI pipelines, agentic systems, and evaluation loops.",
            site="company",
            date_posted=None,
            role_clusters=["ai_ml"],
            job_profile=build_job_profile(
                title="Applied AI Engineer",
                company="NewCo",
                description="Own applied AI pipelines, agentic systems, and evaluation loops.",
                location="Pune, India",
                site="company",
                role_clusters=["ai_ml"],
                cfg={},
            ),
        ),
    ]

    score_calls: dict[str, object] = {}

    async def _fake_enrich(candidates, *, workspace_path, config_overrides=None):
        assert len(candidates) == 2
        return enriched_jobs, []

    async def _fake_embed(db, *, jobs, config_overrides=None):
        return None

    async def _fake_score_jobs_for_user(
        *,
        db,
        user_id,
        resume_text,
        config_overrides,
        distilled_text=None,
        job_urls=None,
        preserve_corpus=False,
    ):
        score_calls["job_urls"] = list(job_urls or [])
        score_calls["preserve_corpus"] = preserve_corpus
        rows = (
            await db.execute(select(JobRaw).where(JobRaw.job_url.in_(job_urls or [])))
        ).scalars().all()
        rows_by_url = {row.job_url: row for row in rows}
        return pd.DataFrame(
            [
                {
                    "id": rows_by_url["https://example.com/jobs/existing"].id,
                    "semantic_score": 82.0,
                    "skills_score": 78.0,
                    "company_score": 70.0,
                    "seniority_score": 75.0,
                    "location_score": 88.0,
                    "recency_score": 60.0,
                    "final_score": 84.0,
                    "title_relevance_score": 91.0,
                    "fit_band": "strong",
                    "confidence_band": "high",
                    "explanation_summary": "Strong match",
                    "match_report": {"why_rank_up": ["AI/ML fit"]},
                    "verification_report": None,
                    "company_tier": "tier_a",
                    "is_contract": False,
                },
                {
                    "id": rows_by_url["https://example.com/jobs/new"].id,
                    "semantic_score": 79.0,
                    "skills_score": 74.0,
                    "company_score": 65.0,
                    "seniority_score": 72.0,
                    "location_score": 90.0,
                    "recency_score": 55.0,
                    "final_score": 81.0,
                    "title_relevance_score": 89.0,
                    "fit_band": "strong",
                    "confidence_band": "high",
                    "explanation_summary": "Good match",
                    "match_report": {"why_rank_up": ["Location fit"]},
                    "verification_report": None,
                    "company_tier": "tier_b",
                    "is_contract": False,
                },
            ]
        )

    monkeypatch.setattr(career_ops_import, "enrich_career_ops_candidates", _fake_enrich)
    monkeypatch.setattr(career_ops_import, "_embed_jobs", _fake_embed)
    monkeypatch.setattr(career_ops_import, "score_jobs_for_user", _fake_score_jobs_for_user)

    summary = await import_career_ops_workspace(
        db,
        workspace_path=workspace,
        user_email="careerops@test.com",
    )

    assert summary.candidate_count == 2
    assert summary.imported_count == 2
    assert summary.inserted_count == 1
    assert summary.updated_count == 1
    assert summary.scored_count == 2
    assert summary.run_id is not None
    assert score_calls["job_urls"] == [
        "https://example.com/jobs/existing",
        "https://example.com/jobs/new",
    ]
    assert score_calls["preserve_corpus"] is True

    jobs = (
        await db.execute(select(JobRaw).order_by(JobRaw.job_url.asc()))
    ).scalars().all()
    assert len(jobs) == 2
    updated_existing = next(job for job in jobs if job.job_url.endswith("/existing"))
    assert updated_existing.title == "Senior ML Engineer"
    assert updated_existing.description == "Build ML systems with Python and Kubernetes."
    assert updated_existing.role_clusters == ["ai_ml"]

    job_results = (
        await db.execute(
            select(JobResult).where(JobResult.user_id == user_id).order_by(JobResult.final_score.desc())
        )
    ).scalars().all()
    assert len(job_results) == 2
    assert job_results[0].final_score == 84.0
    assert job_results[1].final_score == 81.0

    run = (await db.execute(select(Run).where(Run.id == summary.run_id))).scalar_one()
    assert run.status == "success"
    assert run.progress["corpus_source"] == "career_ops_import"
    assert run.progress["import_candidate_count"] == 2
    assert run.progress["import_inserted_count"] == 1
    assert run.progress["import_updated_count"] == 1
    assert run.progress["import_scored_count"] == 2
