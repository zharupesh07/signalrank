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
    parse_resume_from_images,
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
    called_kwargs = mock_client.llm_json.await_args.kwargs
    assert "I am a software engineer" in called_prompt
    assert "{resume_text}" not in called_prompt
    assert called_kwargs["schema_name"] == "resume_parse"
    assert called_kwargs["json_schema"]["type"] == "object"


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
        "email": " candidate@example.com ",
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
    assert result["email"] == "candidate@example.com"
    assert result["experiences"] == [
        {
            "title": "Senior Engineer",
            "company": "Dow",
            "dates": "2024 - Present",
            "location": "",
            "tech": "",
            "bullets": ["Built tools"],
        }
    ]
    assert result["skills"] == [
        {"category": "Programming", "items": ["Python", "SQL"]},
        {"category": "Other", "items": ["Docker"]},
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
            "tech": "",
            "bullets": ["Built systems"],
        }
    ]
    assert result["projects"][0]["name"] == "Toolkit"
    assert result["education"][0]["institution"] == "IIT"


@pytest.mark.asyncio
async def test_parse_resume_structure_returns_validated_editor_dict():
    mock_client = AsyncMock()
    mock_client.llm_json.return_value = {
        "name": "Example Candidate",
        "email": " candidate+wrong@example.com ",
        "position": "",
        "experiences": [
            {
                "title": "Senior Technology Analyst",
                "company": "Example Enterprise",
                "dates": "09/2022 - Present",
                "location": "Remote",
                "bullets": [" configured otc process improvements "],
            }
        ],
        "skills": [{"category": "Platforms", "items": [" ERP ", "S/4HANA"]}],
        "certifications": [" Systems Certification "],
    }

    result = await parse_resume_structure(
        resume_text="Example Candidate\ncandidate@example.com\nSummary\nSystems Consultant with 8 years of experience",
        llm_client=mock_client,
    )

    assert result["name"] == "Example Candidate"
    assert result["email"] == "candidate@example.com"
    assert result["position"] == "Systems Consultant"
    assert result["experiences"][0]["bullets"] == ["configured otc process improvements"]
    assert result["skills"] == [{"category": "Platforms", "items": ["ERP", "S/4HANA"]}]
    mock_client.llm_json.assert_called_once()
    called_kwargs = mock_client.llm_json.await_args.kwargs
    assert called_kwargs["schema_name"] == "resume_structure"
    assert called_kwargs["json_schema"]["properties"]["experiences"]["type"] == "array"


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
    assert called_prompt.endswith("A" * 12000)
    assert "A" * 12001 not in called_prompt
    assert mock_client.llm_json.await_args.kwargs["schema_name"] == "resume_structure"


@pytest.mark.asyncio
async def test_parse_resume_from_images_returns_validated_editor_dict():
    mock_client = AsyncMock()
    mock_client.llm_json_vision.return_value = {
        "name": "Vision Candidate",
        "email": " vision+wrong@example.com ",
        "linkedin": "https://www.linkedin.com/in/vision-candidate/",
        "github": "github.com/vision-user",
        "experiences": {
            "title": "Machine Learning Engineer",
            "company": "Example Labs",
            "dates": "02/2022 - 07/2023",
            "bullets": [" built ml pipelines "],
        },
        "skills": [{"category": "General", "items": [" Python ", "PyTorch"]}],
    }

    result = await parse_resume_from_images(
        [b"page-1", b"page-2"],
        mock_client,
        reference_text="Vision Candidate\nvision@example.com\nLinkedIn: vision-candidate\nGithub: vision-user",
    )

    assert result["name"] == "Vision Candidate"
    assert result["email"] == "vision@example.com"
    assert result["linkedin"] == "vision-candidate"
    assert result["github"] == "vision-user"
    assert result["experiences"][0]["bullets"] == ["built ml pipelines"]
    mock_client.llm_json_vision.assert_awaited_once()


@pytest.mark.asyncio
async def test_parse_resume_from_images_passes_live_tuning_args():
    mock_client = AsyncMock()
    mock_client.llm_json_vision.return_value = {"name": "Vision Candidate"}

    await parse_resume_from_images(
        [b"page-1"],
        mock_client,
        vision_models=["vision-fast"],
        max_tokens=1800,
        reference_text="Reference resume text",
        request_timeout=45.0,
        max_retries=1,
    )

    assert "Reference resume text" in mock_client.llm_json_vision.await_args.args[1]
    assert mock_client.llm_json_vision.await_args.kwargs["vision_models"] == ["vision-fast"]
    assert mock_client.llm_json_vision.await_args.kwargs["max_tokens"] == 1800
    assert mock_client.llm_json_vision.await_args.kwargs["request_timeout"] == 45.0
    assert mock_client.llm_json_vision.await_args.kwargs["max_retries"] == 1


@pytest.mark.asyncio
async def test_parse_resume_from_images_fails_open():
    mock_client = AsyncMock()
    mock_client.llm_json_vision.return_value = {"_error": "vision_llm_failed"}

    result = await parse_resume_from_images([b"page-1"], mock_client)

    assert result == {}


@pytest.mark.asyncio
async def test_parse_resume_from_images_skips_blank_input():
    mock_client = AsyncMock()

    result = await parse_resume_from_images([], mock_client)

    assert result == {}
    mock_client.llm_json_vision.assert_not_called()
