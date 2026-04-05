from ranking.v3.scorer import score_job, score_jobs, load_weights
from ranking.v3.profile import ProfileV3, WeightedSkill


def _make_profile(**kwargs) -> ProfileV3:
    defaults = dict(
        candidate_name="test",
        target_roles=["ML Engineer"],
        weighted_skills=[WeightedSkill("pytorch", 1.0), WeightedSkill("python", 0.8)],
        domains=["AI / ML"],
        industries=["Tech"],
        seniority_band="senior",
        preferred_locations=["Remote"],
        must_have_terms=["pytorch"],
        avoid_terms=["qa"],
        current_focus=None,
        active_lanes=[],
    )
    defaults.update(kwargs)
    return ProfileV3(**defaults)


def test_load_weights_returns_dict():
    weights = load_weights()
    assert isinstance(weights, dict)
    assert "title_similarity" in weights
    assert "negative_hits" in weights
    assert weights["negative_hits"] < 0


def test_score_job_returns_float():
    profile = _make_profile()
    job = {"title": "ML Engineer", "description": "pytorch python", "location": "Remote",
           "seniority_band": "senior", "domain": "AI / ML"}
    score = score_job(job, profile)
    assert isinstance(score, float)


def test_negative_job_scores_lower():
    profile = _make_profile()
    good_job = {"title": "ML Engineer", "description": "pytorch python transformers",
                "location": "Remote", "seniority_band": "senior", "domain": "AI / ML"}
    bad_job = {"title": "QA Engineer", "description": "qa testing support regression",
               "location": "London", "seniority_band": "junior", "domain": "QA"}
    assert score_job(good_job, profile) > score_job(bad_job, profile)


def test_score_jobs_sorted_descending():
    profile = _make_profile()
    jobs = [
        {"title": "QA Engineer", "description": "qa testing", "location": "London",
         "seniority_band": "junior", "domain": "QA"},
        {"title": "ML Engineer", "description": "pytorch python",
         "location": "Remote", "seniority_band": "senior", "domain": "AI / ML"},
    ]
    scored = score_jobs(jobs, profile)
    assert scored[0]["score"] >= scored[1]["score"]
    assert "features" in scored[0]


def test_lane_weight_override_applied():
    weights_default = load_weights(active_lanes=[])
    weights_lane = load_weights(active_lanes=["innovation"])
    assert weights_lane.get("role_family_match", 0) > weights_default.get("role_family_match", 0)
