def test_domain_imports():
    from domain.additive_scoring import compute_weighted_score
    from domain.company import CompanyScorer
    from domain.embed_math import cosine_similarity
    from domain.embeddings import EmbeddingEngine, fingerprint_text
    from domain.roles import classify_functional_role
    from domain.scoring import calculate_seniority_score
    from domain.skills import SkillCanonicalizer


def test_weighted_score():
    from domain.additive_scoring import compute_weighted_score

    scores = {
        "skills_match": 80.0,
        "company_fit": 60.0,
        "seniority": 70.0,
        "location": 100.0,
        "recency": 50.0,
    }
    result = compute_weighted_score(scores, None)
    assert 60 < result < 90


def test_company_scorer():
    from domain.company import CompanyScorer

    cfg = {
        "company_scoring": {
            "default_weight": 1.0,
            "tier_s": ["Google"],
            "tier_a": ["Infosys"],
        },
    }
    scorer = CompanyScorer(cfg)
    assert scorer.classify("Google") == "tier_s"


def test_fingerprint():
    from domain.embeddings import fingerprint_text

    fp = fingerprint_text("hello world")
    assert isinstance(fp, str)
    assert len(fp) == 64
    assert fp == fingerprint_text("hello world")


def test_build_job_embedding_text_skills_before_responsibilities():
    """Skills must appear before responsibilities so they fit within BGE-small's 256-token limit."""
    from domain.embeddings import build_job_embedding_text

    cfg = {"embeddings": {"text": {"max_chars": 2000}}}
    text = build_job_embedding_text(
        title="ML Engineer",
        description="build models " * 200,  # long description that would push skills past token limit
        canonical_skills=["python", "pytorch", "mlflow"],
        cfg=cfg,
    )
    assert text.index("REQUIRED_SKILLS") < text.index("RESPONSIBILITIES"), (
        "Skills must appear before responsibilities so they fit within the 256-token BGE-small limit"
    )


def test_build_job_and_resume_embedding_text_supports_prefixes():
    from domain.embeddings import build_job_embedding_text, build_resume_embedding_text

    cfg = {
        "embeddings": {
            "text": {
                "max_chars": 2000,
                "query_prefix": "query: ",
                "passage_prefix": "passage: ",
            }
        },
        "resume": {"embedding_prefix": "candidate: "},
    }
    job_text = build_job_embedding_text(
        title="ML Engineer",
        description="build models",
        canonical_skills=["python"],
        cfg=cfg,
    )
    resume_text = build_resume_embedding_text(
        resume_text="Platform engineer",
        distilled=None,
        cfg=cfg,
        use_case="default",
    )
    assert job_text.startswith("passage: ")
    assert "ROLE: ML Engineer" in job_text
    assert resume_text.startswith("query: ")
