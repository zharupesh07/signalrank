from unittest.mock import AsyncMock

import pytest

from llm.resume_parser import (
    EXTRACTION_PROMPT,
    ResumeParseResult,
    _build_extraction_prompt,
    _STRUCTURE_PROMPT,
    _validate_extraction,
    _validate_structure,
    parse_resume,
    parse_resume_structure,
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


def test_validate_structure_coerces_lists_and_drops_empty_values():
    data = {
        "name": "  Example Candidate ",
        "email": " example@example.com ",
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Dow",
                "dates": "2024 - Present",
                "location": None,
                "bullets": [" Built tools ", "", None],
            },
            "bad-row",
        ],
        "skills": [
            {"category": "Programming", "items": [" Python ", "", "SQL"]},
            {"category": "", "items": ["Docker"]},
        ],
        "projects": [{"name": "SignalRank", "url": " signalrank.dev ", "description": " Job search copilot "}],
        "education": [{"degree": "B.Tech", "institution": "IIT", "year": 2019}],
        "certifications": [" AWS ", "", None],
    }

    result = _validate_structure(data)

    assert result["name"] == "Example Candidate"
    assert result["email"] == "example@example.com"
    assert result["experiences"] == [
        {
            "title": "Senior Engineer",
            "company": "Dow",
            "dates": "2024 - Present",
            "location": "",
            "bullets": ["Built tools"],
        }
    ]
    assert result["skills"] == [
        {"category": "Programming", "items": ["Python", "SQL"]},
        {"category": "General", "items": ["Docker"]},
    ]
    assert result["projects"][0]["name"] == "SignalRank"
    assert result["education"][0]["year"] == "2019"
    assert result["certifications"] == ["AWS"]


def test_validate_structure_accepts_dict_rows_and_normalizes_links():
    data = {
        "linkedin": "https://www.linkedin.com/in/test-user/",
        "github": "github.com/test-user/",
        "website": "https://www.test-user.dev/",
        "experiences": {
            "title": "Engineer",
            "company": "Acme",
            "dates": "2024 - Present",
            "bullets": "Built systems",
        },
        "projects": {
            "name": "Toolkit",
            "url": "https://toolkit.dev",
            "description": "Internal tooling",
        },
        "education": {
            "degree": "B.Tech",
            "institution": "IIT",
            "year": "2019",
        },
    }

    result = _validate_structure(data)

    assert result["linkedin"] == "test-user"
    assert result["github"] == "test-user"
    assert result["website"] == "test-user.dev"
    assert result["experiences"] == [
        {
            "title": "Engineer",
            "company": "Acme",
            "dates": "2024 - Present",
            "location": "",
            "bullets": ["Built systems"],
        }
    ]
    assert result["projects"][0]["name"] == "Toolkit"
    assert result["education"][0]["institution"] == "IIT"


@pytest.mark.asyncio
async def test_parse_resume_structure_returns_validated_editor_dict():
    mock_client = AsyncMock()
    mock_client.llm_json.return_value = {
        "name": "Ayush Khandelwal",
        "email": " helloayushkh@gmail.com ",
        "position": "SAP Consultant",
        "experiences": [
            {
                "title": "Senior Information Technology Analyst",
                "company": "Dow Chemical International Private Limited",
                "dates": "09/2022 - Present",
                "location": "Mumbai, Maharashtra",
                "bullets": [" configured otc process improvements "],
            }
        ],
        "skills": [{"category": "Platforms", "items": [" SAP SD ", "S/4HANA"]}],
        "certifications": [" SAP Certified Application Associate - SAP S/4HANA Sales "],
    }

    result = await parse_resume_structure(
        resume_text="Ayush Khandelwal\nhelloayushkh@gmail.com",
        llm_client=mock_client,
    )

    assert result["name"] == "Ayush Khandelwal"
    assert result["email"] == "helloayushkh@gmail.com"
    assert result["experiences"][0]["bullets"] == ["configured otc process improvements"]
    assert result["skills"] == [{"category": "Platforms", "items": ["SAP SD", "S/4HANA"]}]
    mock_client.llm_json.assert_called_once()


@pytest.mark.asyncio
async def test_parse_resume_structure_fails_open():
    mock_client = AsyncMock()
    mock_client.llm_json.return_value = {"_error": "llm_failed"}

    result = await parse_resume_structure(
        resume_text="Some resume text",
        llm_client=mock_client,
    )

    assert result == {}


@pytest.mark.asyncio
async def test_parse_resume_structure_skips_blank_input():
    mock_client = AsyncMock()

    result = await parse_resume_structure(
        resume_text=" \n\t ",
        llm_client=mock_client,
    )

    assert result == {}
    mock_client.llm_json.assert_not_called()


@pytest.mark.asyncio
async def test_parse_resume_structure_truncates_prompt_to_avoid_token_bloat():
    mock_client = AsyncMock()
    mock_client.llm_json.return_value = {"name": "Long Resume"}
    long_resume = "A" * 15000

    await parse_resume_structure(
        resume_text=long_resume,
        llm_client=mock_client,
    )

    called_prompt = mock_client.llm_json.await_args.args[0]
    prompt_prefix = _STRUCTURE_PROMPT.format(resume_text="")
    assert called_prompt.startswith(prompt_prefix)
    assert called_prompt.endswith("A" * 12000)
    assert len(called_prompt) == len(prompt_prefix) + 12000
