from domain.job_profile import build_job_profile


def test_build_job_profile_captures_family_skills_and_quality():
    profile = build_job_profile(
        title="Senior ML Platform Engineer",
        company="Acme",
        description=(
            "Build machine learning infrastructure with Python, Kubernetes, and Terraform. "
            "Remote role. Preferred: MLflow, Docker. 5-8 years experience."
        ),
        location="Remote",
        role_clusters=["ai_ml"],
        cfg={
            "skills": {
                "equivalence_groups": {
                    "python": {"canonical": "python", "variants": ["python"]},
                    "kubernetes": {"canonical": "kubernetes", "variants": ["kubernetes"]},
                    "terraform": {"canonical": "terraform", "variants": ["terraform"]},
                    "mlflow": {"canonical": "mlflow", "variants": ["mlflow"]},
                    "docker": {"canonical": "docker", "variants": ["docker"]},
                }
            }
        },
    )

    assert profile["role_family"] == "AI / ML"
    assert profile["domain"] == "AI / ML"
    assert profile["seniority_band"] == "senior"
    assert profile["work_mode"] == "remote"
    assert profile["location_normalized"] == "Remote"
    assert "python" in profile["required_skills"]
    assert "mlflow" in profile["preferred_skills"]
    assert "5-8 years experience" in profile["must_have_constraints"]
    assert "low_description_quality" in profile["red_flags"]
    assert profile["description_quality"] > 0.7
    assert profile["artifact_version"].startswith("job_profile_")
    assert profile["schema_version"] == 1
    assert len(profile["job_fingerprint"]) == 64
    assert len(profile["job_cache_key"]) == 64
    assert profile["evidence_snippets"][0]["source"] == "title"
