import io
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.resume_tailor import (
    TailoredContent,
    _apply_resume_facts,
    _normalize_tailored_content,
    _fit_to_one_page,
    _typst_bold,
    check_page_count,
    load_resume_yaml,
    render_typst,
    resume_yaml_to_text,
    tailor_and_compile,
    validate_resume_artifacts,
    compile_pdf,
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
    assert "Test" in src and "User" in src
    assert "Engineer" in src


def test_normalize_tailored_content_normalizes_handles_and_homepage():
    content = TailoredContent(
        email=" hello@test.com ",
        linkedin="https://www.linkedin.com/in/test-user/",
        github="github.com/test-user/",
        homepage="https://www.test-user.dev/",
    )

    normalized = _normalize_tailored_content(content)
    assert normalized.email == "hello@test.com"
    assert normalized.linkedin == "test-user"
    assert normalized.github == "test-user"
    assert normalized.homepage == "test-user.dev"


def test_normalize_tailored_content_dedupes_skills_projects_and_certifications():
    content = TailoredContent(
        skills=[
            {"category": "Programming", "items": ["Python", "SQL", "Python"]},
            {"category": "programming", "items": ["SQL", "Go"]},
            {"category": "Cloud", "items": ["AWS", "AWS"]},
        ],
        projects=[
            {"name": "Toolkit", "url": "github.com/test/toolkit", "description": "One"},
            {"name": "Toolkit", "url": "https://github.com/test/toolkit", "description": "Duplicate"},
        ],
        certifications=[
            {"name": "AWS SAA", "url": "https://example.com/aws"},
            {"name": "AWS SAA", "url": "https://example.com/aws"},
            "CKA",
            "CKA",
        ],
    )

    normalized = _normalize_tailored_content(content)
    assert normalized.skills == [
        {"category": "Programming", "items": ["Python", "SQL", "Go"]},
        {"category": "Cloud", "items": ["AWS"]},
    ]
    assert len(normalized.projects) == 1
    assert len(normalized.certifications) == 2


def test_render_and_validate_resume_artifacts_for_special_chars_and_links():
    content = TailoredContent(
        name="Ayush Khandelwal",
        email="helloayushkh@gmail.com",
        phone="+91 9044781514",
        location="Kanpur, India",
        linkedin="https://www.linkedin.com/in/ayushhkhandelwal/",
        github="github.com/ayushhkhandelwal",
        homepage="ayush.dev",
        position="Senior Information Technology Analyst",
        summary="Senior enterprise applications analyst with SAP SD and OTC experience.",
        skills=[
            {"category": "Programming", "items": ["C#", "JavaScript", "SQL", "Oracle"]},
            {"category": "Platforms", "items": ["SAP S/4HANA", "SAP SD", "Order to Cash"]},
        ],
        experiences=[
            {
                "title": "Senior Information Technology Analyst",
                "company": "Dow Chemical International Private Limited",
                "company_url": "www.dow.com",
                "location": "Mumbai, Maharashtra",
                "dates": "09/2022 - Present",
                "tech": "SAP SD, OTC, S/4HANA",
                "bullets": [
                    "Configured OTC process improvements across enterprise workflows.",
                    "Supported customer service and planning workstreams for Dow.",
                    "Collaborated with cross-functional teams on SAP enhancements.",
                ],
            }
        ],
        projects=[{"name": "Automation Toolkit", "url": "github.com/ayushhkhandelwal/automation-toolkit", "description": "Internal tooling"}],
        certifications=[{"name": "SAP Certified Application Associate - SAP S/4HANA Sales", "url": "https://www.credly.com/badges/example"}],
    )

    src = render_typst(content)
    pdf = compile_pdf(src)
    validation = validate_resume_artifacts(content, src, pdf)

    assert check_page_count(pdf) == 1
    assert validation.page_count == 1
    assert validation.missing_links == []
    assert "mailto:helloayushkh@gmail.com" in validation.pdf_links
    assert "https://www.linkedin.com/in/ayushhkhandelwal" in validation.pdf_links
    assert validation.vertical_fill_pct is not None
    assert validation.ink_fill_pct is not None


def test_validate_resume_artifacts_warns_on_fragmented_bullets():
    content = TailoredContent(
        name="Ayush Khandelwal",
        experiences=[
            {
                "title": "Senior Information Technology Analyst",
                "company": "Dow Chemical International Private Limited",
                "dates": "09/2022 - Present",
                "bullets": [
                    "Working as a senior analyst in Dow's Enterprise",
                    "segment aligned to the",
                    "order to cash workstream.",
                    "Configured delivery processing, shipping point, output",
                    "determination and storage location determination.",
                    "Consignment and scheduling agreement support.",
                ],
            }
        ],
    )

    with patch("llm.resume_tailor._pdf_annotation_links", return_value=[]), \
         patch("llm.resume_tailor._render_first_page_png", return_value=None), \
         patch("llm.resume_tailor.check_page_count", return_value=1):
        validation = validate_resume_artifacts(content, "#typst", b"%PDF-1.4 fake")

    assert "Resume contains fragmented bullet lines that should be merged before rendering" in validation.warnings


def test_apply_resume_facts_restores_name_and_current_employer():
    resume_text = """Ayush Khandelwal
helloayushkh@gmail.com
+91 9044781514
Kanpur, India
linkedin.com/in/ayushhkhandelwal
WORK EXPERIENCE
Senior Information Technology Analyst
Dow Chemical International Private Limited
09/2022 - Present
Mumbai, Maharashtra
Application Development Associate - SAP SD Consultant
Accenture
08/2018 - 09/2022
"""
    content = TailoredContent(
        name="",
        email="helloayushkh@gmail.com",
        experiences=[
            {
                "title": "Senior SAP SD Consultant",
                "company": "SAP",
                "dates": "Sep 2022 - Present",
                "location": "Bangalore",
                "bullets": ["Did things"],
            }
        ],
    )

    updated = _apply_resume_facts(content, resume_text)
    assert updated.name == "Ayush Khandelwal"
    assert updated.phone == "+91 9044781514"
    assert updated.experiences[0]["title"] == "Senior Information Technology Analyst"
    assert updated.experiences[0]["company"] == "Dow Chemical International Private Limited"
    assert updated.experiences[0]["dates"] == "09/2022 - Present"


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


def test_compile_pdf_passes_font_path():
    """compile_pdf must pass --font-path to typst compile when fonts dir exists."""
    from llm.resume_tailor import FONTS_DIR

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        m = MagicMock()
        m.returncode = 0
        return m

    with patch("llm.resume_tailor.subprocess.run", side_effect=fake_run), \
         patch("pathlib.Path.read_bytes", return_value=b"%PDF-1.4"):
        from llm.resume_tailor import compile_pdf
        compile_pdf("#set page() Hello")

    assert "--font-path" in captured["cmd"]
    font_path_idx = captured["cmd"].index("--font-path")
    assert str(FONTS_DIR) in captured["cmd"][font_path_idx + 1]


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "tailor@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "tailor@test.com", "password": "password123"})
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
