from unittest.mock import AsyncMock

import pytest

from llm.resume_parser import (
    EXTRACTION_PROMPT,
    ResumeParseResult,
    _build_extraction_prompt,
    _validate_extraction,
    parse_resume,
)


def test_validate_extraction_with_valid_data():
    data = {
        "skills": ["python", "ml", "pytorch"],
        "years_of_experience": 5,
        "recent_titles": ["ML Engineer", "Data Scientist"],
        "industries": ["tech", "finance"],
        "education": ["MS Computer Science"],
    }
    result = _validate_extraction(data)
    assert isinstance(result, ResumeParseResult)
    assert result.skills == ["python", "ml", "pytorch"]
    assert result.years_of_experience == 5


def test_validate_extraction_with_missing_keys():
    data = {"skills": ["python"]}
    result = _validate_extraction(data)
    assert result.skills == ["python"]
    assert result.years_of_experience is None
    assert result.recent_titles == []


def test_validate_extraction_with_garbage():
    data = {"_error": "llm_failed"}
    result = _validate_extraction(data)
    assert result.skills == []


def test_validate_extraction_coerces_types():
    data = {
        "skills": "python, ml",
        "years_of_experience": "5",
        "recent_titles": "ML Engineer",
    }
    result = _validate_extraction(data)
    assert result.skills == ["python, ml"]
    assert result.years_of_experience == 5
    assert result.recent_titles == ["ML Engineer"]


@pytest.mark.asyncio
async def test_parse_resume_returns_result():
    mock_client = AsyncMock()
    mock_client.llm_json.return_value = {
        "skills": ["python", "tensorflow"],
        "years_of_experience": 3,
        "recent_titles": ["Software Engineer"],
        "industries": ["tech"],
        "education": ["BS CS"],
    }

    result = await parse_resume(
        resume_text="I am a software engineer with 3 years of Python experience.",
        llm_client=mock_client,
    )
    assert isinstance(result, ResumeParseResult)
    assert "python" in result.skills
    mock_client.llm_json.assert_called_once()
    called_prompt = mock_client.llm_json.await_args.args[0]
    assert "I am a software engineer" in called_prompt
    assert "{resume_text}" not in called_prompt


@pytest.mark.asyncio
async def test_parse_resume_fails_open():
    mock_client = AsyncMock()
    mock_client.llm_json.return_value = {"_error": "llm_failed"}

    result = await parse_resume(
        resume_text="Some resume text",
        llm_client=mock_client,
    )
    assert isinstance(result, ResumeParseResult)
    assert result.skills == []


def test_build_extraction_prompt_includes_resume_text():
    prompt = _build_extraction_prompt("HELLO WORLD")
    assert "HELLO WORLD" in prompt
    assert "{resume_text}" not in prompt
