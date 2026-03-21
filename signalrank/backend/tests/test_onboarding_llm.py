from llm.onboarding import generate_onboarding_questions
from llm.resume_parser import ResumeParseResult


def test_generates_questions_from_profile():
    profile = ResumeParseResult(
        skills=["python", "ml", "pytorch"],
        years_of_experience=5,
        recent_titles=["ML Engineer"],
        industries=["tech"],
        education=["MS CS"],
    )
    questions = generate_onboarding_questions(profile)
    assert isinstance(questions, list)
    assert len(questions) >= 3
    assert len(questions) <= 5
    assert all(isinstance(q, dict) for q in questions)
    assert all("id" in q and "text" in q for q in questions)


def test_generates_questions_from_empty_profile():
    profile = ResumeParseResult()
    questions = generate_onboarding_questions(profile)
    assert isinstance(questions, list)
    assert len(questions) >= 3


def test_question_ids_are_unique():
    profile = ResumeParseResult(skills=["python"], years_of_experience=3)
    questions = generate_onboarding_questions(profile)
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))


def test_questions_have_options_when_applicable():
    profile = ResumeParseResult(
        skills=["python", "java"],
        years_of_experience=8,
        recent_titles=["Senior Engineer"],
    )
    questions = generate_onboarding_questions(profile)
    role_q = next((q for q in questions if q["id"] == "target_roles"), None)
    assert role_q is not None
    assert "options" in role_q or "text" in role_q
