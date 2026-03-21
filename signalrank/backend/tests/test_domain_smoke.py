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
