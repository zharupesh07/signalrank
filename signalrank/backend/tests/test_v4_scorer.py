"""Tests for ranking/v4/scorer.py — score quality and normalization correctness."""
from datetime import datetime, timedelta, timezone

import pytest

from api.models import JobRaw, Profile, User
from ranking.v4.db_scorer import score_jobs_for_user
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


def test_location_match_accepts_city_inside_long_location_string():
    from ranking.v4.features import location_match

    profile = _mlops_profile(preferred_locations=["Pune", "Bangalore"])
    job = _job(
        title="MLOps Engineer",
        company="Acme",
        description="MLOps role",
        location="Pune, Maharashtra, India",
    )
    assert location_match(job, profile) == 1.0


def test_location_match_accepts_india_state_aliases():
    from ranking.v4.features import location_match

    profile = _mlops_profile(preferred_locations=["Pune", "Bangalore"])
    pune_job = _job(
        title="MLOps Engineer",
        company="Acme",
        description="MLOps role",
        location="MH, IN",
    )
    bangalore_job = _job(
        title="AI Platform Engineer",
        company="Acme",
        description="AI platform role",
        location="KA, IN",
    )
    assert location_match(pune_job, profile) == 1.0
    assert location_match(bangalore_job, profile) == 1.0


def test_extract_profile_v4_accepts_bengaluru_and_location_overrides():
    from ranking.v4.extraction import extract_profile_v4

    extracted = extract_profile_v4("Worked in Bengaluru and Pune on AI platform systems.")
    assert "Bangalore" in extracted.preferred_locations
    assert "Pune" in extracted.preferred_locations

    overridden = extract_profile_v4(
        "Worked in London only.",
        config_overrides={"v4_profile": {"preferred_locations": ["Pune", "Bangalore"]}},
    )
    assert overridden.preferred_locations == ["Pune", "Bangalore"]


def test_extract_profile_v4_merges_structured_resume_json():
    from ranking.v4.extraction import extract_profile_v4

    structured_resume = {
        "position": "Senior AI Platform Engineer | Cloud Infrastructure | MLOps | Agentic Systems",
        "location": "Pune, India",
        "summary": "Senior AI Platform Engineer working on AWS, GCP, Terraform, Kubernetes, LangGraph, MLflow, and CI/CD.",
        "experiences": [
            {
                "title": "Senior AI Platform Engineer (GenAI, LLMOps, CI/CD)",
                "company": "Fractal Analytics",
                "dates": "Nov 2024 – Present",
                "location": "Pune",
                "tech": "Python, GCP, LangGraph, FastAPI, Jenkins, Docker, Terraform",
                "bullets": [
                    "Built internal developer platforms and agentic AI systems with RBAC and OIDC.",
                    "Standardized CI/CD and infrastructure as code for AI services.",
                ],
            },
            {
                "title": "Senior Machine Learning Engineer",
                "company": "HCL",
                "dates": "Apr 2024 – Jun 2024",
                "location": "Bengaluru",
                "tech": "Python, GCP, MLflow, Seldon Core, TensorFlow, Label Studio, Flask",
                "bullets": [],
            },
        ],
        "skills": [
            {"category": "Cloud & DevOps", "items": ["AWS", "GCP", "Cloud Run", "Docker", "Kubernetes", "Terraform", "Jenkins", "GitHub Actions"]},
            {"category": "Agentic AI & RAG", "items": ["LangGraph", "LangChain", "Vector Databases (Chroma/FAISS)", "Function Calling", "MCP (Model Context Protocol)"]},
        ],
    }

    profile = extract_profile_v4(
        "Minimal resume text",
        config_overrides={
            "v4_profile": {
                "structured_resume_json": structured_resume,
                "preferred_company_tiers": ["tier_ss", "tier_s", "tier_a"],
                "company_preference_strength": 1.4,
            }
        },
    )

    skills = {ws.name for ws in profile.weighted_skills}
    assert "langgraph" in skills
    assert "terraform" in skills
    assert "mlflow" in skills
    assert "AI Platform Engineer" in profile.target_roles
    assert "MLOps Engineer" in profile.target_roles
    assert all("Intern" not in role for role in profile.target_roles)
    assert "Pune" in profile.preferred_locations
    assert "Bangalore" in profile.preferred_locations
    assert profile.preferred_company_tiers == ["tier_ss", "tier_s", "tier_a"]
    assert profile.company_preference_strength == pytest.approx(1.4)
    assert profile.years_of_experience is not None
    assert "oidc" not in profile.must_have_terms
    assert "rbac" not in profile.must_have_terms


def test_company_tier_score_respects_preferred_company_tiers():
    from ranking.v4.features import company_tier_score

    profile = _mlops_profile(
        company_tier_map={
            "google": "tier_ss",
            "infosys": "tier_b",
            "some startup": "default",
        },
        preferred_company_tiers=["tier_ss", "tier_s", "tier_a"],
        company_preference_strength=1.5,
    )

    google_job = _job("Senior MLOps Engineer", "Google", "MLOps role", job_profile={"company_tier": "tier_ss", "is_contract": False})
    infosys_job = _job("Senior MLOps Engineer", "Infosys", "MLOps role", job_profile={"company_tier": "tier_b", "is_contract": False})
    startup_job = _job("Senior MLOps Engineer", "Some Startup", "MLOps role", job_profile={"company_tier": "default", "is_contract": False})

    google_score = company_tier_score(google_job, profile)
    infosys_score = company_tier_score(infosys_job, profile)
    startup_score = company_tier_score(startup_job, profile)

    assert google_score >= 1.0 - 1e-6
    assert infosys_score < 0.65
    assert startup_score < 0.40


def test_structured_comparison_adds_fit_summary_for_top_jobs():
    from ranking.v4.db_scorer import _apply_structured_comparison

    profile = _mlops_profile()
    scored = _apply_structured_comparison(
        [
            {
                **PERFECT_MATCH_JOB,
                "job_profile": {
                    "role_titles_normalized": ["Senior MLOps Engineer - ML Platform"],
                    "required_skills": ["Kubernetes", "MLflow", "Kubeflow", "Python"],
                    "preferred_skills": ["Airflow", "Spark"],
                    "location_normalized": "Pune",
                    "domain": "AI / ML",
                    "role_family": "Platform / Infrastructure",
                    "seniority_band": "senior",
                    "work_mode": "remote",
                    "red_flags": [],
                    "evidence_snippets": [{"source": "title", "text": "Senior MLOps Engineer - ML Platform"}],
                },
                "score": 0.82,
                "features": {
                    "semantic_similarity": 0.7,
                    "skill_overlap": 0.8,
                    "company_tier_score": 1.0,
                    "seniority_match": 1.0,
                    "location_match": 1.0,
                    "recency_score": 0.8,
                    "title_similarity": 1.0,
                },
            },
            {
                **QA_ENGINEER_JOB,
                "score": 0.40,
                "features": {
                    "semantic_similarity": 0.2,
                    "skill_overlap": 0.0,
                    "company_tier_score": 0.45,
                    "seniority_match": 0.0,
                    "location_match": 1.0,
                    "recency_score": 0.8,
                    "title_similarity": 0.2,
                },
            },
        ],
        profile,
        "Senior AI platform and MLOps engineer with Kubernetes, MLflow, Kubeflow, Airflow, and Python experience.",
    )

    top = scored[0]
    bottom = scored[-1]
    assert top["match_report"] is not None
    assert top["fit_band"] == "strong_fit"
    assert top["explanation_summary"]
    assert any("stack fit" in item.lower() for item in top["match_report"]["why_rank_up"])
    assert bottom["match_report"] is not None
    assert bottom["final_score"] < top["final_score"]


def test_structured_comparison_downgrades_architecture_drift_without_enough_skill_evidence():
    from ranking.v4.db_scorer import _apply_structured_comparison

    profile = _mlops_profile()
    architect_job = {
        **_job(
            title="Data Architect",
            company="Acme",
            description="Architecture leadership for data strategy and governance.",
            location="Bangalore",
            job_profile={
                "role_titles_normalized": ["Data Architect"],
                "required_skills": ["Data governance", "Enterprise architecture"],
                "preferred_skills": ["Stakeholder management"],
                "location_normalized": "Bangalore",
                "domain": "Data",
                "role_family": "Architecture",
                "seniority_band": "senior",
                "work_mode": "onsite",
                "red_flags": [],
                "evidence_snippets": [{"source": "title", "text": "Data Architect"}],
            },
        ),
        "score": 0.78,
        "features": {
            "semantic_similarity": 0.7,
            "skill_overlap": 0.1,
            "company_tier_score": 0.65,
            "seniority_match": 1.0,
            "location_match": 1.0,
            "recency_score": 0.8,
            "title_similarity": 0.45,
        },
    }
    mlops_job = {
        **PERFECT_MATCH_JOB,
        "job_profile": {
            "role_titles_normalized": ["Senior MLOps Engineer - ML Platform"],
            "required_skills": ["Kubernetes", "MLflow", "Kubeflow", "Python"],
            "preferred_skills": ["Airflow", "Spark"],
            "location_normalized": "Pune",
            "domain": "AI / ML",
            "role_family": "Platform / Infrastructure",
            "seniority_band": "senior",
            "work_mode": "remote",
            "red_flags": [],
            "evidence_snippets": [{"source": "title", "text": "Senior MLOps Engineer - ML Platform"}],
        },
        "score": 0.74,
        "features": {
            "semantic_similarity": 0.8,
            "skill_overlap": 0.9,
            "company_tier_score": 1.0,
            "seniority_match": 1.0,
            "location_match": 1.0,
            "recency_score": 0.8,
            "title_similarity": 1.0,
        },
    }

    scored = _apply_structured_comparison(
        [architect_job, mlops_job],
        profile,
        "Senior AI platform and MLOps engineer with Kubernetes, MLflow, Kubeflow, Airflow, and Python experience.",
    )

    by_title = {item["title"]: item for item in scored}
    assert by_title["Data Architect"]["fit_band"] in {"misleading_fit", "weak_fit", "reject"}
    assert by_title["Senior MLOps Engineer - ML Platform"]["fit_band"] == "strong_fit"
    assert scored[0]["title"] == "Senior MLOps Engineer - ML Platform"


def test_structured_comparison_requires_shared_specialist_stack_terms_for_strong_fit():
    from ranking.v4.db_scorer import _apply_structured_comparison

    profile = _mlops_profile()
    architect_job = {
        **_job(
            title="Technical Architect - ML",
            company="Acme",
            description=(
                "Lead architecture for ML systems with Kubernetes, data pipelines, inference services, "
                "and stakeholder reviews. Strong architecture leadership required."
            ),
            location="Bangalore",
            job_profile={
                "role_titles_normalized": ["Technical Architect - ML"],
                "required_skills": ["Kubernetes", "Data pipelines", "Inference services"],
                "preferred_skills": ["Stakeholder management", "Architecture reviews"],
                "location_normalized": "Bangalore",
                "domain": "AI / ML",
                "role_family": "Architecture",
                "seniority_band": "senior",
                "work_mode": "onsite",
                "red_flags": [],
                "evidence_snippets": [{"source": "title", "text": "Technical Architect - ML"}],
            },
        ),
        "score": 0.82,
        "features": {
            "semantic_similarity": 0.72,
            "skill_overlap": 0.25,
            "company_tier_score": 0.7,
            "seniority_match": 1.0,
            "location_match": 1.0,
            "recency_score": 0.8,
            "title_similarity": 0.85,
        },
    }

    scored = _apply_structured_comparison(
        [architect_job],
        profile,
        "Senior AI platform and MLOps engineer with Kubernetes, MLflow, Kubeflow, Airflow, and Python experience.",
    )

    top = scored[0]
    assert top["fit_band"] in {"adjacent_fit", "misleading_fit", "weak_fit"}
    assert top["match_report"] is not None
    assert "strong_fit" != top["match_report"]["verdict"]


def test_structured_comparison_does_not_grant_strong_fit_for_generic_anchor_terms_only():
    from ranking.v4.db_scorer import _apply_structured_comparison

    profile = _mlops_profile(
        weighted_skills=[
            WeightedSkill("kubernetes", 1.0),
            WeightedSkill("llmops", 1.0),
            WeightedSkill("mlflow", 0.9),
            WeightedSkill("terraform", 0.9),
            WeightedSkill("langgraph", 0.9),
        ],
        must_have_terms=["llmops", "kubernetes", "mlflow", "terraform"],
        target_roles=["AI Platform Engineer", "MLOps Engineer", "LLMOps Engineer"],
    )

    generic_anchor_job = {
        **_job(
            title="AI/ML Ops Engineer / Cloud Ops Engineer",
            company="Acme",
            description="Build AI/ML Ops workflows with Kubernetes and LLMOps for cloud operations.",
            location="Bangalore",
            job_profile={
                "role_titles_normalized": ["AI/ML Ops Engineer / Cloud Ops Engineer"],
                "required_skills": ["Kubernetes", "LLMOps"],
                "preferred_skills": ["Cloud Operations"],
                "location_normalized": "Bangalore",
                "domain": "AI / ML",
                "role_family": "Platform / Infrastructure",
                "seniority_band": "senior",
                "work_mode": "hybrid",
                "red_flags": [],
                "evidence_snippets": [{"source": "title", "text": "AI/ML Ops Engineer / Cloud Ops Engineer"}],
            },
        ),
        "score": 0.82,
        "features": {
            "semantic_similarity": 0.82,
            "skill_overlap": 0.55,
            "company_tier_score": 0.8,
            "seniority_match": 1.0,
            "location_match": 1.0,
            "recency_score": 0.8,
            "title_similarity": 0.9,
        },
    }

    scored = _apply_structured_comparison(
        [generic_anchor_job],
        profile,
        "Senior AI platform and MLOps engineer with Kubernetes, MLflow, Terraform, LangGraph, and LLMOps experience.",
    )

    top = scored[0]
    assert top["fit_band"] in {"adjacent_fit", "weak_fit"}
    assert "strong_fit" != top["match_report"]["verdict"]
    assert "generic_anchor_only" in (top["match_report"]["risk_flags"] or [])


def test_structured_comparison_penalizes_hard_negative_role_drift():
    from ranking.v4.db_scorer import _apply_structured_comparison

    profile = _mlops_profile(
        weighted_skills=[
            WeightedSkill("mlflow", 1.0),
            WeightedSkill("terraform", 0.95),
            WeightedSkill("kubernetes", 0.9),
            WeightedSkill("python", 0.8),
        ],
        must_have_terms=["mlflow", "terraform", "kubernetes"],
        target_roles=["AI Platform Engineer", "MLOps Engineer"],
    )

    automation_architect_job = {
        **_job(
            title="Automation Architect",
            company="Acme",
            description="Lead automation strategy with Python and Kubernetes across enterprise systems.",
            location="Bangalore",
            job_profile={
                "role_titles_normalized": ["Automation Architect"],
                "required_skills": ["Python", "Kubernetes", "Automation"],
                "preferred_skills": ["Enterprise Architecture"],
                "location_normalized": "Bangalore",
                "domain": "Automation",
                "role_family": "Architecture",
                "seniority_band": "senior",
                "work_mode": "hybrid",
                "red_flags": [],
                "evidence_snippets": [{"source": "title", "text": "Automation Architect"}],
            },
        ),
        "score": 0.84,
        "features": {
            "semantic_similarity": 0.8,
            "skill_overlap": 0.45,
            "company_tier_score": 0.8,
            "seniority_match": 1.0,
            "location_match": 1.0,
            "recency_score": 0.8,
            "title_similarity": 0.85,
        },
    }

    scored = _apply_structured_comparison(
        [automation_architect_job],
        profile,
        "Senior AI platform and MLOps engineer with MLflow, Terraform, Kubernetes, and Python experience.",
    )

    top = scored[0]
    assert top["fit_band"] in {"misleading_fit", "weak_fit", "reject"}
    assert "hard_negative_role" in (top["match_report"]["risk_flags"] or [])


def test_structured_comparison_does_not_treat_context_only_matches_as_strong():
    from ranking.v4.db_scorer import _apply_structured_comparison

    profile = _mlops_profile(
        weighted_skills=[
            WeightedSkill("python", 1.0),
            WeightedSkill("gcp", 1.0),
            WeightedSkill("aws", 0.9),
            WeightedSkill("mlflow", 0.8),
            WeightedSkill("terraform", 0.8),
        ],
        must_have_terms=["mlflow", "terraform"],
        target_roles=["AI Platform Engineer", "MLOps Engineer"],
    )

    context_only_job = {
        **_job(
            title="Software Engineer - Cloud",
            company="Acme",
            description="Build cloud services with Python on GCP and AWS.",
            location="Pune",
            job_profile={
                "role_titles_normalized": ["Software Engineer - Cloud"],
                "required_skills": ["Python", "GCP", "AWS"],
                "preferred_skills": ["Cloud Services"],
                "location_normalized": "Pune",
                "domain": "Cloud",
                "role_family": "Software Engineering",
                "seniority_band": "senior",
                "work_mode": "hybrid",
                "red_flags": [],
                "evidence_snippets": [{"source": "title", "text": "Software Engineer - Cloud"}],
            },
        ),
        "score": 0.81,
        "features": {
            "semantic_similarity": 0.76,
            "skill_overlap": 0.4,
            "company_tier_score": 0.8,
            "seniority_match": 1.0,
            "location_match": 1.0,
            "recency_score": 0.8,
            "title_similarity": 0.6,
        },
    }

    scored = _apply_structured_comparison(
        [context_only_job],
        profile,
        "Senior AI platform and MLOps engineer with MLflow, Terraform, Kubernetes, Python, GCP, and AWS experience.",
    )

    top = scored[0]
    assert top["fit_band"] in {"weak_fit", "adjacent_fit"}
    assert "context_only_match" in (top["match_report"]["risk_flags"] or [])


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


@pytest.mark.asyncio
async def test_score_jobs_for_user_preserve_corpus_keeps_older_and_duplicate_title_company_rows(db):
    user = User(email="v4-preserve@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="Senior AI platform and MLOps engineer with Kubernetes, MLflow, Kubeflow, Airflow, Python, and Terraform experience.",
        preferred_locations=["Pune", "Bangalore"],
        target_roles=["MLOps Engineer", "AI Platform Engineer"],
        onboarding_complete=True,
    )
    db.add(profile)
    await db.flush()

    old_posted = datetime.now(timezone.utc) - timedelta(days=45)
    jobs = [
        JobRaw(
            job_url="https://example.com/jobs/older-a",
            title="MLOps Engineer",
            company="Acme",
            description="Kubernetes MLflow Terraform Airflow platform role",
            location="Pune",
            site="indeed",
            ingested_at=old_posted,
            date_posted=old_posted,
            role_clusters=["ai_ml", "infra"],
            job_profile={
                "company_tier": "tier_a",
                "is_contract": False,
                "role_titles_normalized": ["MLOps Engineer"],
                "required_skills": ["Kubernetes", "MLflow", "Terraform"],
                "preferred_skills": ["Airflow", "Python"],
                "location_normalized": "Pune",
                "domain": "AI / ML",
                "role_family": "Platform / Infrastructure",
            },
        ),
        JobRaw(
            job_url="https://example.com/jobs/older-b",
            title="MLOps Engineer",
            company="Acme",
            description="Kubernetes MLflow Terraform Airflow platform role with Bangalore scope",
            location="Bangalore",
            site="indeed",
            ingested_at=old_posted + timedelta(minutes=1),
            date_posted=old_posted + timedelta(minutes=1),
            role_clusters=["ai_ml", "infra"],
            job_profile={
                "company_tier": "tier_a",
                "is_contract": False,
                "role_titles_normalized": ["MLOps Engineer"],
                "required_skills": ["Kubernetes", "MLflow", "Terraform"],
                "preferred_skills": ["Airflow", "Python"],
                "location_normalized": "Bangalore",
                "domain": "AI / ML",
                "role_family": "Platform / Infrastructure",
            },
        ),
    ]
    db.add_all(jobs)
    await db.commit()

    ranked = await score_jobs_for_user(
        db=db,
        user_id=user.id,
        resume_text=profile.resume_text or "",
        distilled_text=None,
        config_overrides=None,
        job_urls=[job.job_url for job in jobs],
        preserve_corpus=True,
    )

    assert len(ranked) == 2
    assert set(ranked["job_url"].tolist()) == {job.job_url for job in jobs}
