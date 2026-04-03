from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, Profile, User
from api.routes.onboarding import _extract_text_from_pdf
from batch.ranker import score_jobs_for_user


RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"
SAMPLE_PDFS = sorted(RESUMES_DIR.glob("*.pdf"))

CASES = (
    {"key": "abhijeet", "pdf_name": "Abhijeet_CV.pdf", "top_job_titles": ("AI/Machine Learning Engineer", "Machine Learning Engineer II", "Data Scientist - Machine Learning")},
    {"key": "example", "pdf_name": "Example_Candidate_Resume_V2_2.pdf", "top_job_titles": ("AI Platform Engineer", "MLOps Engineer", "Forward Deployed Engineer, AI Platform")},
    {"key": "vivek", "pdf_name": "Vivek-Gupta-Emerging-Technologies.pdf", "top_job_titles": ("Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer")},
    {"key": "aditya", "pdf_name": "aditya.pdf", "top_job_titles": ("Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer")},
    {"key": "ayush", "pdf_name": "ayush_resume_new.pdf", "top_job_titles": ("SAP SD Consultant", "SAP OTC Functional Consultant", "SAP S/4HANA SD Consultant")},
)

TOP10_CASES = {
    "vivek": {
        "relevant_titles": (
            "Innovation Engineer",
            "Emerging Technologies Engineer",
            "R&D Engineer",
            "Technical Innovation Consultant",
            "Innovation Technologist",
            "Prototype Engineer",
            "IoT Innovation Engineer",
            "Research and Development Engineer",
            "Emerging Tech Product Engineer",
            "Innovation Lab Engineer",
        ),
        "distractor_titles": (
            "Generic Software Engineer",
            "AI Engineer",
            "Data Engineer",
            "Solutions Engineer",
            "Customer Engineer",
            "Site Reliability Engineer",
            "QA Automation Engineer",
            "Support Engineer",
            "Sales Engineer",
            "DevOps Engineer",
        ),
        "relevant_description": (
            "Drive innovation programs, rapid POCs, prototypes, MVPs, IoT experiments, "
            "robotics exploration, workshop facilitation, and go-to-market validation."
        ),
        "distractor_description": (
            "Own standard delivery engineering, customer support, operational troubleshooting, "
            "incident response, and general software feature work."
        ),
        "min_relevant_in_top_10": 10,
    },
    "aditya": {
        "relevant_titles": (
            "Network Automation Engineer",
            "Infrastructure Automation Engineer",
            "Cloud Network Engineer",
            "Network Reliability Engineer",
            "Network DevOps Engineer",
            "Infrastructure Platform Engineer",
            "Cloud Infrastructure Automation Engineer",
            "Network Operations Automation Engineer",
            "Systems and Network Automation Engineer",
            "Site Reliability Engineer - Network",
        ),
        "distractor_titles": (
            "Frontend Engineer",
            "QA Automation Engineer",
            "Product Manager",
            "Business Analyst",
            "Data Analyst",
            "Customer Support Engineer",
            "WordPress Developer",
            "Shopify Developer",
            "SAP SD Consultant",
            "Manual Tester",
        ),
        "relevant_description": (
            "Build network automation, infrastructure automation, cloud networking, Python tooling, "
            "IaC, observability, and reliability workflows for production systems."
        ),
        "distractor_description": (
            "Focus on unrelated front-end delivery, QA, support, analysis, and packaged business applications."
        ),
        "min_relevant_in_top_10": 5,
    },
    "ayush": {
        "relevant_titles": (
            "SAP SD Consultant",
            "SAP OTC Functional Consultant",
            "SAP S/4HANA SD Consultant",
            "SAP Sales and Distribution Consultant",
            "SAP Order to Cash Consultant",
            "SAP GTS Consultant",
            "SAP SD Functional Analyst",
            "SAP OTC Solution Consultant",
            "SAP SD Implementation Consultant",
            "SAP SD Lead Consultant",
        ),
        "distractor_titles": (
            "Salesforce Administrator",
            "SAP Basis Engineer",
            "ABAP Developer",
            "Data Engineer",
            "AI Engineer",
            "Product Manager",
            "Security Consultant",
            "QA Engineer",
            "Support Specialist",
            "Linux Administrator",
        ),
        "relevant_description": (
            "Lead SAP SD, OTC, sales and distribution, pricing, order-to-cash, S/4HANA SD, "
            "GTS, and functional consulting engagements."
        ),
        "distractor_description": (
            "Work on unrelated SAP technical administration, ABAP development, platform tooling, QA, and support."
        ),
        "min_relevant_in_top_10": 9,
    },
}


def _load_spec(pdf_path: Path) -> dict:
    return json.loads(pdf_path.with_suffix(".json").read_text())


EMAIL_TO_CASE = {
    str(_load_spec(RESUMES_DIR / case["pdf_name"])["email"]).lower(): case for case in CASES
}


def _case_for_spec(spec: dict):
    email = str(spec.get("email") or "").lower()
    if email not in EMAIL_TO_CASE:
        raise KeyError(email)
    return EMAIL_TO_CASE[email]


def _top_titles(case_key: str) -> tuple[str, ...]:
    for case in CASES:
        if case["key"] == case_key:
            return case["top_job_titles"]
    raise KeyError(case_key)


def _make_jobs(case_spec: dict) -> list[JobRaw]:
    now = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
    case = _case_for_spec(case_spec)
    top_titles = _top_titles(case["key"])
    jobs: list[JobRaw] = []
    for idx, title in enumerate(top_titles, start=1):
        jobs.append(
            JobRaw(
                job_url=f"https://example.com/rank/{case_spec['email']}/{idx}",
                title=title,
                company=f"{case['key'].title()} Co {idx}",
                description=(
                    f"{title} role aligned to {case_spec.get('position') or case_spec.get('label')}. "
                    "Build production systems, collaborate cross-functionally, and ship measurable outcomes."
                ),
                location="Remote",
                site="indeed",
                date_posted=now,
                ingested_at=now,
                role_clusters=["ai_ml_data", "software_general"],
            )
        )
    jobs.append(
        JobRaw(
            job_url=f"https://example.com/rank/{case_spec['email']}/noise",
            title="Generic Support Engineer",
            company="Noise Inc",
            description="Low relevance control job.",
            location="Remote",
            site="indeed",
            date_posted=now,
            ingested_at=now,
            role_clusters=["software_general"],
        )
    )
    return jobs


def _make_top10_jobs(case_key: str, case_spec: dict) -> list[JobRaw]:
    now = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
    fixture = TOP10_CASES[case_key]
    jobs: list[JobRaw] = []

    for idx, title in enumerate(fixture["relevant_titles"], start=1):
        jobs.append(
            JobRaw(
                job_url=f"https://example.com/top10/{case_key}/relevant/{idx}",
                title=title,
                company=f"{case_key.title()} Relevant {idx}",
                description=f"{fixture['relevant_description']} Role: {title}.",
                location="Remote",
                site="indeed",
                date_posted=now,
                ingested_at=now,
                role_clusters=["software_general", "ai_ml_data"],
            )
        )

    for idx, title in enumerate(fixture["distractor_titles"], start=1):
        jobs.append(
            JobRaw(
                job_url=f"https://example.com/top10/{case_key}/distractor/{idx}",
                title=title,
                company=f"{case_key.title()} Distractor {idx}",
                description=f"{fixture['distractor_description']} Role: {title}.",
                location="Remote",
                site="indeed",
                date_posted=now,
                ingested_at=now,
                role_clusters=["software_general"],
            )
        )

    return jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("pdf_path", SAMPLE_PDFS, ids=[path.stem for path in SAMPLE_PDFS])
async def test_resume_ranking_quality_matches_expected_top_jobs(
    pdf_path: Path,
    db: AsyncSession,
):
    spec = _load_spec(pdf_path)
    resume_text = _extract_text_from_pdf(pdf_path.read_bytes())

    user = User(
        email=f"quality-{spec['email']}",
        password_hash="mock",
        provider="credentials",
    )
    db.add(user)
    await db.flush()

    expected_role = str(spec.get("position") or spec.get("label") or "").strip()
    profile = Profile(
        user_id=user.id,
        resume_text=resume_text,
        target_roles=[expected_role] if expected_role else [],
        preferred_locations=[str(spec.get("location") or "").split(",")[0].strip()] if spec.get("location") else [],
        role_intent="software_general",
        onboarding_complete=True,
        scraper_max_terms=1,
        scraper_hours_old=24,
        config_overrides={
            "profile_intent": {"roles": [expected_role] if expected_role else []},
            "ranking": {"agentic_matching": {"enabled": False}},
        },
    )
    db.add(profile)
    db.add_all(_make_jobs(spec))
    await db.commit()

    ranked = await score_jobs_for_user(
        db=db,
        user_id=user.id,
        resume_text=resume_text,
        config_overrides=profile.config_overrides,
    )

    ranked = ranked.sort_values("final_score", ascending=False).reset_index(drop=True)
    top_titles = list(ranked["title"].head(3))
    expected_titles = set(_top_titles(_case_for_spec(spec)["key"]))

    assert set(top_titles) == expected_titles
    assert ranked.iloc[0]["title"] in expected_titles
    assert ranked.iloc[0]["final_score"] > ranked.iloc[-1]["final_score"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_key", ["vivek", "aditya", "ayush"])
async def test_resume_ranking_quality_keeps_relevant_jobs_in_top_10(
    case_key: str,
    db: AsyncSession,
):
    case = next(case for case in CASES if case["key"] == case_key)
    pdf_path = RESUMES_DIR / case["pdf_name"]
    spec = _load_spec(pdf_path)
    resume_text = _extract_text_from_pdf(pdf_path.read_bytes())

    user = User(
        email=f"top10-{spec['email']}",
        password_hash="mock",
        provider="credentials",
    )
    db.add(user)
    await db.flush()

    expected_role = str(spec.get("position") or spec.get("label") or "").strip()
    profile = Profile(
        user_id=user.id,
        resume_text=resume_text,
        target_roles=[expected_role] if expected_role else [],
        preferred_locations=[str(spec.get("location") or "").split(",")[0].strip()] if spec.get("location") else [],
        role_intent="software_general",
        onboarding_complete=True,
        scraper_max_terms=1,
        scraper_hours_old=24,
        config_overrides={
            "profile_intent": {"roles": [expected_role] if expected_role else []},
            "ranking": {"agentic_matching": {"enabled": False}},
        },
    )
    db.add(profile)
    db.add_all(_make_top10_jobs(case_key, spec))
    await db.commit()

    ranked = await score_jobs_for_user(
        db=db,
        user_id=user.id,
        resume_text=resume_text,
        config_overrides=profile.config_overrides,
    )

    ranked = ranked.sort_values("final_score", ascending=False).reset_index(drop=True)
    top_10_titles = set(ranked["title"].head(10))
    expected_titles = set(TOP10_CASES[case_key]["relevant_titles"])
    distractor_titles = set(TOP10_CASES[case_key]["distractor_titles"])
    min_relevant = int(TOP10_CASES[case_key]["min_relevant_in_top_10"])

    assert top_10_titles.issubset(expected_titles)
    assert top_10_titles.isdisjoint(distractor_titles)
    assert len(top_10_titles) >= min_relevant
