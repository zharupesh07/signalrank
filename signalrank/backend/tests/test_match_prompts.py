import pytest

from domain.match_judge import MATCH_REPORT_SCHEMA, _build_prompt as build_match_prompt
from domain.match_verifier import _build_prompt as build_verify_prompt


pytestmark = pytest.mark.unit


def test_match_prompt_requires_json_only_and_grounded_evidence():
    system, user = build_match_prompt(
        {"target_roles_primary": ["Engineer"], "evidence_snippets": [{"source": "resume", "text": "Python"}]},
        {"required_skills": ["Python"], "evidence_snippets": [{"source": "job", "text": "Python"}]},
        "resume",
        "job",
    )

    assert "JSON object only" in system
    assert "no markdown" in system
    assert "strong_fit requires grounded evidence from both the resume and the job description" in system
    assert "at least one grounded item each" in user
    assert MATCH_REPORT_SCHEMA["properties"]["cited_resume_evidence"]["minItems"] == 1
    assert MATCH_REPORT_SCHEMA["properties"]["cited_job_evidence"]["minItems"] == 1


def test_verifier_prompt_requires_json_only_and_no_new_evidence():
    system, user = build_verify_prompt(
        {"verdict": "strong_fit"},
        {"target_roles_primary": ["Engineer"], "evidence_snippets": [{"source": "resume", "text": "Python"}]},
        {"required_skills": ["Python"], "evidence_snippets": [{"source": "job", "text": "Python"}]},
    )

    assert "JSON object only" in system
    assert "no markdown" in system
    assert "Do not invent new evidence" in user
