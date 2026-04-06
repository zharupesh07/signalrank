"""Tests for ranking/v4/scorer.py — score quality and normalization correctness."""
from datetime import datetime, timezone

import pytest

from ranking.v4.profile import CandidateProfile, WeightedSkill
from ranking.v4.scorer import load_weights, score_job, score_jobs


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _mlops_profile(**overrides) -> CandidateProfile:
    """Canonical MLOps/AI Platform candidate profile for Example-like user."""
    defaults = dict(
        target_roles=["MLOps Engineer", "AI Platform Engineer", "ML Infrastructure Engineer"],
        weighted_skills=[
            WeightedSkill("mlflow", 1.0),
            WeightedSkill("kubeflow", 1.0),
            WeightedSkill("python", 1.0),
            WeightedSkill("kubernetes", 0.9),
            WeightedSkill("airflow", 0.8),
            WeightedSkill("spark", 0.7),
        ],
        domains=["mlops", "machine learning", "data engineering"],
        industries=["tech", "fintech"],
        seniority_band="senior",
        preferred_locations=["Pune", "Bangalore", "Remote"],
        must_have_terms=["mlops", "ml platform", "model deployment", "kubeflow", "mlflow"],
        avoid_terms=["qa", "testing", "manual testing", "support engineer", "helpdesk"],
        active_lanes=["mlops_platform"],
        current_focus="mlops",
    )
    defaults.update(overrides)
    return CandidateProfile(**defaults)


def _job(title: str, company: str, description: str, **overrides) -> dict:
    return {
        "id": "test-id",
        "job_url": "https://example.com/job",
        "title": title,
        "company": company,
        "description": description,
        "location": overrides.get("location", "Pune"),
        "site": "linkedin",
        "date_posted": datetime.now(timezone.utc).isoformat(),
        "role_clusters": overrides.get("role_clusters", []),
        "job_profile": overrides.get("job_profile", {"company_tier": "tier_b", "is_contract": False}),
        "embedding": None,
    }


MLOPS_JOB = _job(
    title="Senior MLOps Engineer",
    company="Fractal Analytics",
    description=(
        "We are looking for a Senior MLOps Engineer to build and maintain our ML platform. "
        "You will work with MLflow, Kubeflow, model deployment pipelines, and Kubernetes. "
        "Experience with Python, Airflow, and Spark is required. "
        "You will design ML infrastructure to support our data science teams. "
        "This is a senior role for candidates with 5+ years of MLOps experience. "
        "Remote-friendly position based in Pune."
    ),
    job_profile={"company_tier": "tier_a", "is_contract": False},
)

PYTHON_DEV_MICHELIN = _job(
    title="Python Developer (AI Evaluation Frameworks)",
    company="Michelin",
    description=(
        "Michelin is looking for a Python Developer to work on AI evaluation frameworks. "
        "You will write Python scripts to evaluate AI systems and generate reports. "
        "Experience with Python and basic machine learning libraries is expected. "
        "Good knowledge of data structures and algorithms required. "
        "This is a software development position focused on Python scripting and evaluation."
    ),
    job_profile={"company_tier": "tier_b", "is_contract": False},
)

QA_ENGINEER_JOB = _job(
    title="QA Engineer",
    company="Infosys",
    description=(
        "Looking for QA Engineer for manual testing and automated testing. "
        "Support engineer role with helpdesk responsibilities. "
        "Selenium, JIRA, test case writing. No ML or Python required."
    ),
    job_profile={"company_tier": "tier_c", "is_contract": False},
)

PERFECT_MATCH_JOB = _job(
    title="Senior MLOps Engineer - ML Platform",
    company="Google",
    description=(
        "Build and scale our ML platform using Kubeflow and MLflow. "
        "MLOps, model deployment, Kubernetes, Airflow, Spark, Python. "
        "ML platform engineering for production ML systems. "
        "Senior role requiring 5+ years MLOps experience in Pune or remote. "
        "Work on kubeflow pipelines, mlflow tracking, model deployment automation."
    ),
    job_profile={"company_tier": "tier_ss", "is_contract": False},
)


# ── Normalization tests ───────────────────────────────────────────────────────

def test_score_is_absolute_not_relative():
    """Top job should NOT always get 1.0 — scores are absolute against theoretical max."""
    profile = _mlops_profile()
    results = score_jobs([PYTHON_DEV_MICHELIN, QA_ENGINEER_JOB], profile)
    # Both jobs are bad matches; top score should be well below 1.0
    assert results[0]["score"] < 0.70, (
        f"Top score {results[0]['score']:.3f} is too high for a mismatched batch. "
        "Relative normalization is producing inflated scores."
    )


def test_scores_bounded_zero_to_one():
    """All scores must be in [0, 1]."""
    profile = _mlops_profile()
    jobs = [MLOPS_JOB, PYTHON_DEV_MICHELIN, QA_ENGINEER_JOB, PERFECT_MATCH_JOB]
    results = score_jobs(jobs, profile)
    for r in results:
        assert 0.0 <= r["score"] <= 1.0, f"Score out of bounds: {r['score']}"


def test_michelin_python_dev_scores_below_60():
    """'Python Developer (AI Evaluation Frameworks)' at Michelin should score < 0.60 for MLOps profile."""
    profile = _mlops_profile()
    weights = load_weights(active_lanes=profile.active_lanes)
    max_possible = sum(w for w in weights.values() if w > 0)
    raw = score_job(PYTHON_DEV_MICHELIN, profile, weights)
    absolute = max(0.0, min(1.0, raw / max_possible))
    assert absolute < 0.60, (
        f"Michelin Python Developer scored {absolute:.3f} — should be below 0.60 for MLOps profile. "
        "This job has no MLOps terms and doesn't match the target role."
    )


# ── Ranking order tests ───────────────────────────────────────────────────────

def test_strong_mlops_job_outranks_python_dev():
    """Senior MLOps Engineer should rank above generic Python Developer."""
    profile = _mlops_profile()
    results = score_jobs([PYTHON_DEV_MICHELIN, MLOPS_JOB], profile)
    top_title = results[0]["title"]
    assert "MLOps" in top_title, (
        f"Expected MLOps job on top, got: {top_title!r}. "
        f"Scores: {[(r['title'], round(r['score'], 3)) for r in results]}"
    )


def test_perfect_match_scores_above_70():
    """A job matching all must_have_terms at a tier_ss company should score > 0.70."""
    profile = _mlops_profile()
    weights = load_weights(active_lanes=profile.active_lanes)
    max_possible = sum(w for w in weights.values() if w > 0)
    raw = score_job(PERFECT_MATCH_JOB, profile, weights)
    absolute = max(0.0, min(1.0, raw / max_possible))
    assert absolute > 0.70, (
        f"Perfect match job scored {absolute:.3f} — expected > 0.70. "
        "Check must_have_hits, skill_overlap, title_similarity weights."
    )


def test_qa_job_scores_below_python_dev():
    """QA/testing job with avoid_terms should score lower than a generic Python job."""
    profile = _mlops_profile()
    results = score_jobs([PYTHON_DEV_MICHELIN, QA_ENGINEER_JOB], profile)
    python_score = next(r["score"] for r in results if "Python" in r["title"])
    qa_score = next(r["score"] for r in results if "QA" in r["title"])
    assert qa_score < python_score, (
        f"QA job ({qa_score:.3f}) should score lower than Python job ({python_score:.3f}) "
        "due to avoid_terms penalty."
    )


# ── Feature-level tests ───────────────────────────────────────────────────────

def test_negative_hits_reduce_score():
    """A job with avoid_terms should score lower than same job without them."""
    from ranking.v4.features import compute_features

    profile = _mlops_profile()

    clean_job = _job(
        title="Senior MLOps Engineer",
        company="Fractal",
        description="MLOps, Kubeflow, MLflow, Kubernetes, Python, model deployment.",
    )
    dirty_job = _job(
        title="Senior MLOps Engineer",
        company="Fractal",
        description="MLOps, Kubeflow, MLflow, Kubernetes, Python, model deployment. "
                    "QA testing, manual testing, support engineer responsibilities.",
    )

    clean_features = compute_features(clean_job, profile)
    dirty_features = compute_features(dirty_job, profile)

    assert dirty_features["negative_hits"] > clean_features["negative_hits"], (
        "Job with avoid_terms should have higher negative_hits fraction."
    )

    weights = load_weights(active_lanes=profile.active_lanes)
    clean_raw = score_job(clean_job, profile, weights)
    dirty_raw = score_job(dirty_job, profile, weights)
    assert dirty_raw < clean_raw, "Avoid_terms should reduce score."


def test_must_have_hits_zero_limits_max_score():
    """A job with no must_have_terms should not reach 0.90 score."""
    from ranking.v4.features import compute_features

    profile = _mlops_profile()
    weights = load_weights(active_lanes=profile.active_lanes)
    max_possible = sum(w for w in weights.values() if w > 0)

    features = compute_features(PYTHON_DEV_MICHELIN, profile)
    assert features["must_have_hits"] == 0.0, (
        "Michelin Python job should have 0 must_have_hits (no MLOps terms)."
    )

    raw = score_job(PYTHON_DEV_MICHELIN, profile, weights)
    absolute = raw / max_possible
    # must_have_hits weight in mlops_platform is 0.25 out of max_possible
    # So a 0 must_have_hits job loses at least 0.25/max_possible ≈ 22% of max
    must_have_weight = weights["must_have_hits"]
    ceiling = 1.0 - must_have_weight / max_possible
    assert absolute < ceiling, (
        f"Job with must_have_hits=0 scored {absolute:.3f}, expected < {ceiling:.3f}. "
        "Missing must_have_terms should impose a meaningful ceiling."
    )


def test_batch_ranking_order_with_mixed_jobs():
    """MLOps jobs outrank Python dev, which outranks QA. Scores are descending."""
    profile = _mlops_profile()
    results = score_jobs(
        [QA_ENGINEER_JOB, PYTHON_DEV_MICHELIN, MLOPS_JOB, PERFECT_MATCH_JOB],
        profile,
    )
    titles = [r["title"] for r in results]
    scores = [r["score"] for r in results]

    # Both MLOps jobs must outscore the Python dev job (without embeddings they may tie each other)
    mlops_scores = [r["score"] for r in results if "MLOps" in r["title"]]
    python_score = next(r["score"] for r in results if "Python Developer" in r["title"])
    qa_score = next(r["score"] for r in results if "QA" in r["title"])

    assert all(s > python_score for s in mlops_scores), (
        f"MLOps jobs should outscore Python dev. "
        f"MLOps: {mlops_scores}, Python: {python_score:.3f}"
    )
    assert python_score > qa_score, (
        f"Python dev ({python_score:.3f}) should outscore QA ({qa_score:.3f})."
    )
    # QA job must be last
    assert "QA" in titles[-1], (
        f"Expected QA job last, got: {list(zip(titles, [round(s, 3) for s in scores]))}"
    )
    # Scores should be descending (ties allowed)
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)), (
        f"Scores not descending: {scores}"
    )
