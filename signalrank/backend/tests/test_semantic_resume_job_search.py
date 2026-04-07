from __future__ import annotations

import json
from pathlib import Path

from tools import semantic_resume_job_search as script


def test_collect_jobs_from_scrape_cache_dedupes_and_filters(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    payload = {
        "query": {"term": "Innovation Lead", "location": "Bangalore", "country": "India"},
        "jobs": [
            {
                "job_url": "https://example.com/1",
                "title": "Innovation Lead",
                "company": "Example",
                "location": "Bangalore",
                "description": "IoT and rapid prototyping",
                "date_posted": "2026-04-05",
            },
            {
                "job_url": "https://example.com/1",
                "title": "Innovation Lead",
                "company": "Example",
                "location": "Bangalore",
                "description": "IoT and rapid prototyping",
                "date_posted": "2026-04-05",
            },
            {
                "job_url": "https://example.com/2",
                "title": "Old Role",
                "company": "OldCo",
                "location": "Bangalore",
                "description": "Old role",
                "date_posted": "2025-01-01",
            },
        ],
    }
    (cache_dir / "a.json").write_text(json.dumps(payload))

    jobs, meta = script._collect_jobs_from_scrape_cache(cache_dir, lookback_hours=24 * 30)

    assert [job.job_url for job in jobs] == ["https://example.com/1"]
    assert jobs[0].source_terms == ("Innovation Lead",)
    assert meta["jobs_skipped_old"] == 1


def test_build_query_probes_includes_manual_and_keyword_queries(tmp_path: Path):
    resume_path = tmp_path / "vivek.json"
    resume_path.write_text(json.dumps({
        "name": "Vivek Gupta",
        "position": "Innovation and R&D Lead",
        "summary": "IoT, Conversational AI, Robotics, and Rapid Prototyping specialist.",
        "location": "Bengaluru, India",
        "experiences": [{"title": "Innovation Lead", "company": "Example", "tech": "IoT, Conversational AI"}],
        "skills": [{"category": "Hardware", "items": ["ESP32", "Raspberry Pi", "Arduino"]}],
    }))

    resume_text = script._load_resume_text(resume_path)
    probes, profile = script._build_query_probes(resume_text, resume_path, ["innovation lab"])

    probe_texts = [probe.text for probe in probes]
    assert "innovation lab" in probe_texts
    assert any("IoT" in probe.text or "R&D" in probe.text for probe in probes)
    assert profile["matching_signals"]["preferred_locations"] == ["Bangalore"]


def test_resolve_model_specs_includes_embeddinggemma():
    specs = script._resolve_model_specs(["minilm", "embeddinggemma"])

    assert [spec.name for spec in specs] == ["minilm", "embeddinggemma"]
    assert specs[1].repo_id == "onnx-community/embeddinggemma-300m-ONNX"


def test_resolve_model_specs_defaults_skip_embeddinggemma():
    specs = script._resolve_model_specs(None)

    assert [spec.name for spec in specs] == ["minilm", "bge-small"]


def test_build_job_text_truncates_description():
    job = script.JobDoc(
        job_url="https://example.com/1",
        title="Innovation Lead",
        company="Example",
        location="Bangalore",
        description="x" * 100,
        date_posted="2026-04-05",
        source_terms=("Innovation Lead",),
    )

    text = script._build_job_text(job, max_description_chars=20)

    assert "DESCRIPTION: " + ("x" * 20) in text
    assert "x" * 21 not in text


def test_prefilter_jobs_for_profile_keeps_role_relevant_slice():
    profile = {
        "matching_signals": {
            "primary_roles": ["AI Engineer"],
            "adjacent_roles": ["Platform Engineer"],
            "broadened_roles": ["Software Engineer"],
            "must_have_skills": ["Python", "Kubernetes"],
            "supporting_skills": ["AWS"],
        }
    }
    jobs = [
        script.JobDoc(
            job_url="https://example.com/ai",
            title="AI Platform Engineer",
            company="Example",
            location="Bangalore",
            description="Python Kubernetes AWS ML platform",
            date_posted="2026-04-05",
            source_terms=("AI Engineer",),
        ),
        script.JobDoc(
            job_url="https://example.com/network",
            title="Network Firewall Engineer",
            company="Example",
            location="Bangalore",
            description="Routing switching firewall operations",
            date_posted="2026-04-05",
            source_terms=("Network Engineer",),
        ),
    ]

    filtered, meta = script._prefilter_jobs_for_profile(jobs, profile, max_jobs=10)

    assert [job.job_url for job in filtered] == ["https://example.com/ai"]
    assert meta["matched_jobs"] == 1


def test_prefilter_jobs_for_network_profile_keeps_network_jobs():
    profile = {
        "matching_signals": {
            "primary_roles": ["Network Engineer"],
            "adjacent_roles": ["Network Automation Engineer"],
            "broadened_roles": ["Systems Engineer"],
            "must_have_skills": ["Firewall", "Routing"],
            "supporting_skills": ["Python"],
        }
    }
    jobs = [
        script.JobDoc(
            job_url="https://example.com/network",
            title="Senior Network Firewall Engineer",
            company="Example",
            location="Pune",
            description="Firewall routing switching and Python automation",
            date_posted="2026-04-05",
            source_terms=("Network Engineer",),
        ),
        script.JobDoc(
            job_url="https://example.com/ml",
            title="Machine Learning Engineer",
            company="Example",
            location="Pune",
            description="PyTorch model development",
            date_posted="2026-04-05",
            source_terms=("AI Engineer",),
        ),
    ]

    filtered, meta = script._prefilter_jobs_for_profile(jobs, profile, max_jobs=10)

    assert [job.job_url for job in filtered] == ["https://example.com/network"]
    assert meta["matched_jobs"] == 1
