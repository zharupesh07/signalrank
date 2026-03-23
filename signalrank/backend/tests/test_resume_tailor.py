import io
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.resume_tailor import (
    TailoredContent,
    _fit_to_one_page,
    _typst_bold,
    check_page_count,
    load_resume_yaml,
    render_typst,
    resume_yaml_to_text,
    tailor_and_compile,
)

SAMPLE_RESUME_DATA = {
    "name": "Test User",
    "email": "test@example.com",
    "phone": "+1 555 0000",
    "location": "Remote",
    "linkedin": "linkedin.com/in/testuser",
    "github": "github.com/testuser",
    "homepage": "",
    "position": "Senior ML Engineer",
    "summary": "ML engineer with 5 years experience.",
    "skills": [
        {"category": "ML", "items": ["PyTorch", "TensorFlow"]},
        {"category": "Cloud", "items": ["AWS", "GCP"]},
    ],
    "experiences": [
        {
            "title": "ML Engineer",
            "company": "Acme Corp",
            "location": "NYC",
            "dates": "2021-2024",
            "tech": "Python, PyTorch",
            "bullets": [
                "Built training pipeline handling 1M+ samples/day",
                "Reduced model latency by 40%",
                "Led team of 3 engineers",
            ],
        }
    ],
    "projects": [{"name": "MyProject", "url": "github.com/tp", "description": "A cool project"}],
    "education": [{"degree": "B.Tech CS", "institution": "IIT", "year": "2019"}],
}


def test_resume_yaml_to_text():
    text = resume_yaml_to_text(SAMPLE_RESUME_DATA)
    assert "Test User" in text
    assert "ML Engineer" in text
    assert "Built training pipeline" in text
    assert "PyTorch" in text


def test_resume_yaml_to_text_loads_from_file(tmp_path):
    import yaml

    p = tmp_path / "resume.yaml"
    p.write_text(yaml.dump(SAMPLE_RESUME_DATA), encoding="utf-8")
    data = load_resume_yaml(p)
    assert data["name"] == "Test User"


def test_typst_bold_converts_markdown():
    assert _typst_bold("**Platform Architecture:** Built stuff") == "*Platform Architecture:* Built stuff"

def test_typst_bold_no_markers():
    assert _typst_bold("plain text") == "plain text"

def test_typst_bold_multiple():
    assert _typst_bold("**A:** x and **B:** y") == "*A:* x and *B:* y"

def test_fit_to_one_page_trims_summary():
    content = TailoredContent(
        summary="Sentence one. Sentence two. Sentence three. Sentence four.",
        experiences=[{"title": "X", "company": "Y", "dates": "2024", "bullets": ["a", "b", "c"]}],
    )
    _fit_to_one_page(content, current_pages=2)
    sentences = [s.strip() for s in content.summary.split(".") if s.strip()]
    assert len(sentences) <= 2

def test_certifications_field_default_empty():
    c = TailoredContent()
    assert c.certifications == []

def test_fit_to_one_page_trims_bullets():
    content = TailoredContent(
        summary="Short.",
        experiences=[
            {"title": "New", "company": "A", "dates": "2024", "bullets": ["a", "b", "c", "d"]},
            {"title": "Old", "company": "B", "dates": "2020", "bullets": ["x", "y", "z", "w"]},
        ],
    )
    result = _fit_to_one_page(content, current_pages=2)
    assert result is True
    assert len(content.experiences[1]["bullets"]) == 3

def test_fit_to_one_page_stops_at_floor():
    content = TailoredContent(
        summary="Short.",
        experiences=[{"title": "X", "company": "Y", "dates": "2024", "bullets": ["a", "b"]}],
    )
    result = _fit_to_one_page(content, current_pages=2)
    assert result is False


def test_fit_to_one_page_trims_oldest_role_first():
    """Oldest role (last in list) should lose bullets before newer roles."""
    content = TailoredContent(
        summary="Short summary.",
        experiences=[
            {"title": "New Role", "company": "A", "dates": "2024", "bullets": ["a", "b", "c", "d", "e"]},
            {"title": "Old Role", "company": "B", "dates": "2020", "bullets": ["x", "y", "z", "w"]},
        ],
    )
    trimmed = _fit_to_one_page(content, current_pages=2)
    assert trimmed is True
    assert len(content.experiences[1]["bullets"]) == 3
    assert len(content.experiences[0]["bullets"]) == 5  # untouched


def test_fit_to_one_page_protects_newest_role():
    """Newest role (index 0) must keep at least 3 bullets."""
    content = TailoredContent(
        summary="Short.",
        experiences=[
            {"title": "New", "company": "A", "dates": "2024", "bullets": ["a", "b", "c"]},
        ],
    )
    trimmed = _fit_to_one_page(content, current_pages=2)
    assert len(content.experiences[0]["bullets"]) == 3  # floor respected


def test_check_page_count_single_page():
    try:
        import pypdf

        writer = pypdf.PdfWriter()
        writer.add_blank_page(612, 792)
        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()
        assert check_page_count(pdf_bytes) == 1
    except ImportError:
        pytest.skip("pypdf not installed")


def test_render_typst_runs():
    content = TailoredContent(
        name="Test User",
        email="t@t.com",
        position="Engineer",
        summary="Summary here.",
        skills=[{"category": "ML", "items": ["Python"]}],
        experiences=[
            {
                "title": "Engineer",
                "company": "Acme",
                "location": "NYC",
                "dates": "2021-2024",
                "tech": "Python",
                "bullets": ["Did stuff"],
            }
        ],
        projects=[],
        education=[{"degree": "B.Tech", "institution": "IIT", "year": "2019"}],
    )
    src = render_typst(content)
    assert "Test User" in src
    assert "Engineer" in src


@pytest.mark.asyncio
async def test_tailor_and_compile_one_page():
    mock_content = {
        "name": "Test User",
        "email": "t@t.com",
        "phone": "",
        "location": "",
        "homepage": "",
        "linkedin": "",
        "github": "",
        "position": "ML Engineer",
        "summary": "Summary.",
        "skills": [{"category": "ML", "items": ["Python"]}],
        "experiences": [
            {
                "title": "Engineer",
                "company": "Acme",
                "location": "NYC",
                "dates": "2021-2024",
                "tech": "Python",
                "bullets": ["Built things"],
            }
        ],
        "projects": [],
        "education": [{"degree": "B.Tech", "institution": "IIT", "year": "2019"}],
    }

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock(return_value=mock_content)

    with patch("llm.resume_tailor.compile_pdf") as mock_compile, \
         patch("llm.resume_tailor.check_page_count", return_value=1):
        mock_compile.return_value = b"%PDF-1.4 fake"
        content, pdf = await tailor_and_compile(
            resume_data=SAMPLE_RESUME_DATA,
            job_title="ML Engineer",
            job_description="We need a great ML engineer.",
            llm=mock_llm,
        )

    assert content.name == "Test User"
    assert pdf == b"%PDF-1.4 fake"


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "tailor@test.com", "password": "pass"})
    r = await client.post("/api/auth/login", json={"email": "tailor@test.com", "password": "pass"})
    return r.json()["access_token"]


async def test_list_templates(client, auth_token):
    r = await client.get("/api/resume/templates", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    assert "templates" in r.json()
    assert "classic" in r.json()["templates"]


async def test_tailor_no_resume_returns_404(client, auth_token):
    r = await client.post(
        "/api/resume/tailor",
        json={"job_id": "00000000-0000-0000-0000-000000000000", "template": "classic"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 404


async def test_tailor_invalid_template(client, auth_token, monkeypatch):
    import llm.resume_parser as rp
    from llm.resume_parser import ResumeParseResult

    async def mock_parse(text, llm_client):
        return ResumeParseResult(skills=["python"], years_of_experience=2)

    monkeypatch.setattr(rp, "parse_resume", mock_parse)

    await client.post(
        "/api/onboarding/resume",
        files={"file": ("r.txt", b"Python dev", "text/plain")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    r = await client.post(
        "/api/resume/tailor",
        json={"job_id": "00000000-0000-0000-0000-000000000000", "template": "badtemplate"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 422
