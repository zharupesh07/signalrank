from ranking.v3.pipeline import rank_jobs_v3


_SAMPLE_RESUME = """
Example Candidate  — Senior ML Engineer
Jan 2023 – Present: ML Platform Engineer at Fractal
Skills: PyTorch, Python, LLM, Transformers, MLflow, AWS, FastAPI
2019 – 2022: Data Scientist at TCS
Skills: Python, Spark, SQL, Kafka
"""

_SAMPLE_JOBS = [
    {
        "id": "job_001",
        "title": "Machine Learning Engineer",
        "description": "Senior ML engineer role requiring PyTorch, Python, and LLM experience. AWS preferred.",
        "location": "Remote",
        "seniority_band": "senior",
        "domain": "AI / ML",
        "date_posted": "2026-03-15",
    },
    {
        "id": "job_002",
        "title": "QA Automation Engineer",
        "description": "QA testing, Selenium, regression testing, support.",
        "location": "London",
        "seniority_band": "junior",
        "domain": "QA",
        "date_posted": "2026-03-10",
    },
    {
        "id": "job_003",
        "title": "Data Scientist",
        "description": "Python, Spark, SQL data science role.",
        "location": "Remote",
        "seniority_band": "senior",
        "domain": "AI / ML",
        "date_posted": "2026-03-20",
    },
]


def test_rank_jobs_v3_returns_sorted_with_features():
    results = rank_jobs_v3(_SAMPLE_RESUME, _SAMPLE_JOBS, candidate_name="example")
    assert len(results) <= len(_SAMPLE_JOBS)
    assert results[0]["id"] != "job_002"  # QA job should not rank first
    assert results[0]["score"] >= results[-1]["score"]
    assert "features" in results[0]
    assert "profile" in results[0]


def test_rank_jobs_v3_drops_stale_jobs():
    stale_jobs = [
        {
            "id": "stale_001",
            "title": "ML Engineer",
            "description": "pytorch python",
            "location": "Remote",
            "seniority_band": "senior",
            "domain": "AI / ML",
            "date_posted": "2025-01-01",  # older than 90 days from 2026-04-05
        }
    ]
    results = rank_jobs_v3(_SAMPLE_RESUME, stale_jobs, candidate_name="example")
    assert len(results) == 0


def test_rank_jobs_v3_with_current_focus():
    results = rank_jobs_v3(
        _SAMPLE_RESUME, _SAMPLE_JOBS,
        candidate_name="example",
        current_focus="ML pytorch transformers"
    )
    assert len(results) > 0
    assert results[0]["profile"]["current_focus"] == "ML pytorch transformers"
