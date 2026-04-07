from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from tools import rank_resume_existing_corpus as script


def test_extract_generic_profile_infers_roles_skills_locations_and_avoid_terms():
    resume_text = """
    Senior Software Engineer
    Bangalore, India

    8+ years of experience building Python, React, AWS, and Kubernetes systems.
    Led backend services, APIs, and CI/CD pipelines.
    """

    profile = script._extract_generic_profile(resume_text, "candidate")

    assert "Software Engineer" in profile["suggested_roles"]
    assert "Python" in profile["skills"]
    assert "React" in profile["skills"]
    assert "AWS" in profile["skills"]
    assert "Kubernetes" in profile["skills"]
    assert profile["suggested_locations"] == ["Bangalore"]
    assert profile["seniority_band"] == "senior"
    assert "Intern" in profile["avoid_terms"]
    assert profile["query_plan"]["title_queries"][0] == "Software Engineer"


def test_extract_generic_profile_infers_innovation_iot_roles_and_skills():
    resume_text = """
    Innovation and R&D Lead
    Bengaluru, India

    10+ years building IoT prototypes, Conversational AI demos, Robotics PoCs, and 3D printing workflows.
    Led rapid prototyping labs with ESP32, Raspberry Pi, Arduino, MQTT, and Python.
    """

    profile = script._extract_generic_profile(resume_text, "vivek-like")

    assert "Innovation Lead" in profile["suggested_roles"]
    assert "IoT Solutions Lead" in profile["suggested_roles"] or "IoT Engineer" in profile["suggested_roles"]
    assert "IoT" in profile["skills"]
    assert "3D Printing" in profile["skills"]
    assert "Rapid Prototyping" in profile["skills"]
    assert profile["suggested_locations"] == ["Bangalore"]


def test_extract_locations_prioritizes_explicit_header_location_over_certification_city():
    resume_text = """
    Vivek Gupta
    Location: Bengaluru, India

    Certified Design Sprint Master by AJ&Smart Company (Berlin)
    Led innovation workshops across Europe.
    """

    locations = script._extract_locations(resume_text)

    assert locations == ["Bangalore"]


def test_score_jobs_prefers_generic_overlap_without_domain_boost():
    profile = {
        "suggested_roles": ["Software Engineer"],
        "recent_titles": ["Software Engineer"],
        "skills": ["Python", "Kubernetes", "AWS"],
        "suggested_locations": ["Bangalore"],
        "suggested_exclusions": ["Intern", "Junior"],
        "avoid_terms": ["Intern", "Junior"],
        "domains": [{"name": "Software Engineering", "confidence": 0.9, "evidence": ["software engineer"]}],
        "industries": [],
        "seniority_band": "senior",
        "years_of_experience": 8,
    }
    jobs = [
        script.JobRecord(
            job_url="https://example.com/sap",
            title="SAP SD Consultant",
            company="Example SAP",
            location="Bangalore",
            site="indeed",
            description="ERP delivery and process consulting with no platform overlap.",
        ),
        script.JobRecord(
            job_url="https://example.com/platform",
            title="Platform Engineer",
            company="Example Cloud",
            location="Bangalore",
            site="indeed",
            description="Python, Kubernetes, AWS, Terraform, and APIs.",
        ),
    ]

    scores = script._score_jobs(profile, jobs, agentic=False)

    assert scores[0]["title"] == "Platform Engineer"
    assert scores[0]["final_score"] > scores[1]["final_score"]


def test_apply_llm_suggestions_merges_role_skills_and_queries():
    profile = {
        "suggested_roles": ["Consultant"],
        "skills": ["Python"],
        "query_plan": {
            "title_queries": ["Consultant"],
            "skill_queries": ["Python"],
            "domain_queries": ["Platform"],
            "negative_keywords": ["Intern"],
        },
        "suggested_search_queries": ["Consultant"],
    }
    hints = {
        "role_phrases": ["AI Strategist"],
        "skill_highlights": ["Terraform"],
        "domain_labels": ["Strategy"],
        "industry_labels": ["Finance"],
        "search_queries": ["AI Strategist Terraform"],
        "negative_keywords": ["Junior"],
    }
    enriched = script._apply_llm_suggestions(profile, hints)
    assert "AI Strategist" in enriched["suggested_roles"]
    assert "Terraform" in enriched["skills"]
    assert "Strategy" in [item["name"] for item in enriched["domains"]]
    assert "Finance" in enriched["industries"]
    assert "AI Strategist Terraform" in enriched["suggested_search_queries"]


def test_filter_llm_hints_keeps_only_resume_supported_terms():
    resume_text = """
    Senior Network Automation Engineer with Python, AWS, Terraform, and Kubernetes experience.
    Built CI/CD pipelines and infrastructure automation systems.
    """

    hints = {
        "role_phrases": ["Network Automation Engineer", "Product Manager"],
        "skill_highlights": ["Python", "SAP"],
        "domain_labels": ["Automation Systems", "Retail Banking"],
        "industry_labels": ["Cloud Infrastructure", "Healthcare"],
        "search_queries": ["Network Automation Engineer Python", "Product Manager SAP"],
        "negative_keywords": ["Intern"],
    }

    filtered = script._filter_llm_hints(hints, resume_text)

    assert filtered["role_phrases"] == ["Network Automation Engineer"]
    assert filtered["skill_highlights"] == ["Python"]
    assert "Automation Systems" in filtered["domain_labels"]
    assert "Retail Banking" not in filtered["domain_labels"]
    assert filtered["search_queries"] == ["Network Automation Engineer Python"]


def test_build_deterministic_queries_combines_and_caps_terms():
    profile = {
        "query_plan": {
            "title_queries": ["Backend Engineer", "Platform Engineer"],
            "skill_queries": ["Python", "Terraform"],
            "domain_queries": ["AI", "Platform"],
            "search_queries": ["Backend Engineer Python"],
        },
        "suggested_roles": ["Backend Engineer"],
        "skills": ["Python", "Terraform"],
    }
    queries, audit = script._build_deterministic_queries(profile, max_terms=5)
    assert len(queries) <= 5
    assert "Backend Engineer Python" in queries
    assert any("Platform Engineer" in term for term in queries)
    assert "duplicates" in audit
    assert "evaluation" in audit


def test_build_matching_signals_broadens_generic_engineering_titles():
    profile = {
        "target_roles": [{"title": "Backend Engineer", "priority": "primary"}],
        "suggested_roles": ["Backend Engineer"],
        "recent_titles": ["Backend Engineer"],
        "skills": ["Python", "AWS"],
        "must_have_terms": ["Python"],
        "seniority_band": "senior",
    }

    signals = script._build_matching_signals(profile)

    assert "Backend Engineer" in signals["primary_roles"]
    assert "Software Engineer" in signals["broadened_roles"]
    assert "Senior Software Engineer" in signals["broadened_roles"]


def test_build_matching_signals_does_not_force_engineering_broadening_for_consultant_lane():
    profile = {
        "target_roles": [{"title": "Consultant", "priority": "primary"}],
        "suggested_roles": ["Consultant", "Innovation and R&D Consultant"],
        "recent_titles": ["Consultant"],
        "skills": ["IoT", "Python"],
        "must_have_terms": ["IoT"],
        "seniority_band": "lead",
    }

    signals = script._build_matching_signals(profile)

    assert "Consultant" in signals["primary_roles"]
    assert "Software Engineer" not in signals["broadened_roles"]


def test_build_matching_signals_prioritizes_innovation_skills_for_innovation_roles():
    profile = {
        "target_roles": [{"title": "Innovation Lead", "priority": "primary"}],
        "suggested_roles": ["Innovation Lead", "Creative Technologist"],
        "recent_titles": ["Innovation Lead"],
        "skills": ["Python", "Java", "IoT", "Conversational AI", "3D Printing", "Rapid Prototyping"],
        "must_have_terms": [],
        "seniority_band": "lead",
    }

    signals = script._build_matching_signals(profile)

    assert signals["must_have_skills"][:4] == ["3D Printing", "Conversational AI", "IoT", "Rapid Prototyping"]


def test_build_deterministic_queries_adds_innovation_keyword_lane():
    profile = {
        "query_plan": {
            "title_queries": ["Innovation Lead"],
            "skill_queries": ["IoT", "Rapid Prototyping"],
            "domain_queries": ["Innovation"],
            "search_queries": [],
        },
        "matching_signals": {
            "primary_roles": ["Innovation Lead"],
            "adjacent_roles": [],
            "broadened_roles": [],
            "must_have_skills": ["IoT", "Rapid Prototyping"],
            "supporting_skills": ["3D Printing"],
            "domain_terms": ["Innovation"],
        },
    }

    queries, audit = script._build_deterministic_queries(profile, max_terms=8)

    assert any(query in {"IoT", "Rapid Prototyping"} for query in queries)
    assert audit["evaluation"]["keyword_queries"] >= 1
    assert audit["tiers"]["keyword"]


def test_score_jobs_penalizes_innovation_profile_drift_terms():
    profile = {
        "suggested_roles": ["Innovation Lead", "Creative Technologist"],
        "recent_titles": ["Innovation Lead"],
        "skills": ["IoT", "Conversational AI", "Rapid Prototyping"],
        "must_have_terms": ["IoT", "Conversational AI"],
        "suggested_locations": ["Bangalore"],
        "seniority_band": "lead",
        "domains": [{"name": "Innovation", "confidence": 0.9, "evidence": ["innovation"]}],
        "industries": [],
        "matching_signals": {
            "primary_roles": ["Innovation Lead"],
            "adjacent_roles": ["Creative Technologist"],
            "broadened_roles": [],
            "must_have_skills": ["IoT", "Conversational AI"],
            "supporting_skills": ["Rapid Prototyping"],
            "domain_terms": ["Innovation"],
            "industry_terms": [],
            "preferred_locations": ["Bangalore"],
            "avoid_terms": [],
            "curated_queries": ["Innovation Lead IoT"],
            "seniority_band": "lead",
            "weights": dict(script.DEFAULT_SCORE_WEIGHTS),
        },
    }
    jobs = [
        script.JobRecord(
            job_url="https://example.com/support",
            title="Application Support Engineer",
            company="Example Support",
            location="Bangalore",
            site="indeed",
            description="Application support for enterprise systems with some IoT references.",
        ),
        script.JobRecord(
            job_url="https://example.com/consulting",
            title="Consultant | Conversational AI",
            company="Example Innovation",
            location="Bangalore",
            site="indeed",
            description="Conversational AI, rapid prototyping, IoT workshops, proof of concepts.",
        ),
    ]

    scores = script._score_jobs(profile, jobs, agentic=False)

    assert scores[0]["title"] == "Consultant | Conversational AI"
    assert scores[0]["final_score"] > scores[1]["final_score"]


@pytest.mark.asyncio
async def test_run_for_resume_uses_profile_driven_jobspy_queries(tmp_path, monkeypatch):
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(
        "Senior DevOps Engineer\n"
        "Pune\n\n"
        "7+ years building Python, Kubernetes, Docker, AWS, and Terraform platforms."
    )

    captured = {}

    async def _fake_scrape_jobspy(terms, locations, hours_old, max_results):
        captured["terms"] = terms
        captured["locations"] = locations
        captured["hours_old"] = hours_old
        captured["max_results"] = max_results
        jobs = [
            script.JobRecord(
                job_url="https://example.com/1",
                title="DevOps Engineer",
                company="Example",
                location="Pune",
                site="indeed",
                description="Python Kubernetes AWS Terraform",
            )
        ]
        queries = [{"term": term, "location": location, "country": "India"} for term in terms for location in locations]
        return jobs, queries, {"full_hits": 0, "incremental_hits": 0, "misses": len(queries)}

    monkeypatch.setattr(script, "_scrape_jobspy", _fake_scrape_jobspy)

    args = SimpleNamespace(
        scrape_jobspy=True,
        jobspy_terms=None,
        jobspy_locations=None,
        jobspy_hours_old=168,
        jobspy_max_results_per_query=10,
        top_k=5,
        llm_verify_top=0,
        llm_verify_model=None,
    )

    report = await script._run_for_resume(resume_path, args)

    assert captured["terms"][0] == "DevOps Engineer"
    assert captured["locations"] == ["Pune"]
    assert report["parsed_profile"]["suggested_roles"][0] == "DevOps Engineer"
    assert len(report["approaches"]) == 4
    assert report["ranked_jobs"] == 1


@pytest.mark.asyncio
async def test_run_for_resume_reuses_llm_parse_and_verifies_unique_jobs_once(tmp_path, monkeypatch):
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(
        "Senior Backend Engineer\n"
        "Bangalore\n\n"
        "8+ years building Python APIs on AWS."
    )

    parse_calls = {"count": 0}
    verify_calls = {"count": 0, "jobs": 0}

    async def _fake_scrape_jobspy(terms, locations, hours_old, max_results):
        jobs = [
            script.JobRecord(
                job_url="https://example.com/1",
                title="Backend Engineer",
                company="Example",
                location="Bangalore",
                site="indeed",
                description="Python APIs on AWS",
            )
        ]
        queries = [{"term": term, "location": location, "country": "India"} for term in terms for location in locations]
        return jobs, queries, {"full_hits": 0, "incremental_hits": 0, "misses": len(queries)}

    async def _fake_enrich(profile, resume_text, client):
        return profile

    async def _fake_llm_parse_resume(resume_text, client, model_hint):
        parse_calls["count"] += 1
        return {"skills": ["Python", "AWS"], "suggested_roles": ["Backend Engineer"]}

    async def _fake_llm_verify_top_jobs(top_jobs, resume_text, model_hint, client=None):
        verify_calls["count"] += 1
        verify_calls["jobs"] = len(top_jobs)
        return [
            {
                "job_url": top_jobs[0]["job_url"],
                "title": top_jobs[0]["title"],
                "company": top_jobs[0]["company"],
                "fit_band": "strong_fit",
                "confidence_band": "high",
                "evidence": ["Strong overlap."],
            }
        ]

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(script, "_scrape_jobspy", _fake_scrape_jobspy)
    monkeypatch.setattr(script, "_enrich_profile_with_llm_with_client", _fake_enrich)
    monkeypatch.setattr(script, "_llm_parse_resume", _fake_llm_parse_resume)
    monkeypatch.setattr(script, "_llm_verify_top_jobs", _fake_llm_verify_top_jobs)

    args = SimpleNamespace(
        scrape_jobspy=True,
        jobspy_terms=None,
        jobspy_locations=None,
        jobspy_hours_old=168,
        jobspy_max_results_per_query=10,
        top_k=5,
        llm_verify_top=1,
        llm_verify_model=None,
    )

    report = await script._run_for_resume(resume_path, args)

    assert parse_calls["count"] == 1
    assert verify_calls["count"] == 1
    assert verify_calls["jobs"] == 1
    assert all(app["llm_verification"] for app in report["approaches"])


@pytest.mark.asyncio
async def test_scrape_jobspy_reuses_same_window_cache_with_incremental_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "SCRAPE_CACHE_DIR", tmp_path / "scrape_cache")

    class _FakeFrame:
        def __init__(self, rows):
            self._rows = rows

        def iterrows(self):
            for idx, row in enumerate(self._rows):
                yield idx, row

    calls = []

    def _fake_scrape_jobs(**kwargs):
        calls.append(kwargs["hours_old"])
        if kwargs["hours_old"] == 2:
            return _FakeFrame([
                {
                    "job_url": "https://example.com/new",
                    "title": "New Job",
                    "company": "NewCo",
                    "location": "Pune",
                    "site": "indeed",
                    "description": "fresh",
                    "date_posted": "2026-04-05",
                }
            ])
        return _FakeFrame([
            {
                "job_url": "https://example.com/cached",
                "title": "Cached Job",
                "company": "OldCo",
                "location": "Pune",
                "site": "indeed",
                "description": "cached",
                "date_posted": "2026-04-04",
            }
        ])

    import sys
    sys.modules["jobspy"] = SimpleNamespace(scrape_jobs=_fake_scrape_jobs)

    cache_key = script._scrape_cache_key({"term": "Backend Engineer", "location": "Pune", "country": "India"}, 10)
    script._store_scrape_cache(
        cache_key,
        {
            "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "hours_old": 360,
            "query": {"term": "Backend Engineer", "location": "Pune", "country": "India"},
            "max_results": 10,
            "jobs": [
                {
                    "job_url": "https://example.com/cached",
                    "title": "Cached Job",
                    "company": "OldCo",
                    "location": "Pune",
                    "site": "indeed",
                    "description": "cached",
                    "date_posted": "2026-04-04",
                }
            ],
        },
    )

    jobs, queries, cache_summary = await script._scrape_jobspy(["Backend Engineer"], ["Pune"], 360, 10)

    assert calls == [2]
    assert len(jobs) == 2
    assert queries[0]["cache_mode"] == "incremental"
    assert queries[0]["fetched_hours"] == 2
    assert cache_summary["incremental_hits"] == 1
