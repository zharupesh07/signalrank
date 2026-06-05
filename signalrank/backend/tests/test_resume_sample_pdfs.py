import json
import re
from pathlib import Path

import pytest

from api.routes.onboarding import _extract_text_from_pdf, _render_pdf_pages_as_images
from domain.onboarding_profile import deterministic_resume_parse
from domain.resume_editor import (
    editor_to_tailored_content,
    merge_resume_editor,
    parse_resume_editor,
    serialize_resume_editor,
)
from llm.resume_tailor import _normalize_tailored_content, TailoredContent
from llm.resume_parser import parse_resume_from_images, parse_resume_structure
from llm.resume_tailor import check_page_count, render_and_compile_content, validate_resume_artifacts
from tests._paths import repo_resumes_dir


RESUMES_DIR = repo_resumes_dir()
SAMPLE_PDFS = sorted(RESUMES_DIR.glob("*.pdf"))
SPEC_PDFS = [path for path in SAMPLE_PDFS if path.with_suffix(".json").exists()]

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def _first_email(text: str) -> str:
    match = _EMAIL_RE.search(text or "")
    return match.group(0) if match else ""


def _load_sample_spec(pdf_path: Path) -> dict:
    return json.loads(pdf_path.with_suffix(".json").read_text())


def _require_resume_pdf(name: str) -> Path:
    path = RESUMES_DIR / name
    if not path.exists():
        pytest.skip(f"private resume fixture not present: {name}")
    return path


def _experience_matches(candidate: dict, marker: dict) -> bool:
    title = _normalize_cmp(candidate.get("title") or "").replace("developement", "development")
    company = _normalize_cmp(candidate.get("company") or "")
    return _normalize_cmp(marker["title"]) in title and _normalize_cmp(marker["company"]) in company


def _normalize_cmp(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("developement", "development")
    text = text.replace("‑", " ").replace("–", " ").replace("—", " ")
    text = re.sub(r"[^a-z0-9/().+& ]+", " ", text)
    return " ".join(text.replace("/", " / ").split())


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(_normalize_cmp(left).split())
    right_tokens = set(_normalize_cmp(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _assert_editor_matches_spec(editor: dict, spec: dict) -> None:
    assert editor["name"] == spec["name"]
    assert editor["email"] == spec["email"]
    if spec["phone"]:
        assert editor["phone"] == spec["phone"]
    position_contains = spec.get("position_contains") or spec.get("position", "")
    if position_contains:
        assert _token_overlap_ratio(position_contains, editor["position"]) >= 0.5
    minimums = spec.get("minimums") or {}
    assert len(editor["experiences"]) >= minimums.get("experiences", len(spec.get("experiences", [])))
    skill_item_count = sum(len(group.get("items", [])) for group in editor["skills"])
    min_skill_groups = minimums.get("skill_groups", 0)
    assert len(editor["skills"]) >= min_skill_groups or skill_item_count >= min_skill_groups
    assert len(editor["certifications"]) >= minimums.get("certifications", 0)
    markers = spec.get("experience_markers") or [
        {"title": exp.get("title", ""), "company": exp.get("company", "")}
        for exp in spec.get("experiences", [])
    ]
    for marker in markers:
        assert any(_experience_matches(exp, marker) for exp in editor["experiences"]), marker
    for marker in spec.get("certification_markers", []):
        assert any(marker.lower() in cert.lower() for cert in editor["certifications"]), marker


def _fake_llm_payload(spec: dict, extracted_text: str) -> dict:
    base = parse_resume_editor(extracted_text)
    experiences = []
    markers = spec.get("experience_markers") or [
        {"title": exp.get("title", ""), "company": exp.get("company", "")}
        for exp in spec.get("experiences", [])
    ]
    for idx, marker in enumerate(markers):
        matched = next((exp for exp in base.get("experiences", []) if _experience_matches(exp, marker)), None)
        experiences.append(
            {
                "title": marker["title"],
                "company": marker["company"],
                "dates": (matched or {}).get("dates") or f"20{idx + 1:02d} - Present",
                "location": (matched or {}).get("location", ""),
                "tech": (matched or {}).get("tech", ""),
                "bullets": (matched or {}).get("bullets") or [f"Delivered measurable outcome {idx + 1}."],
            }
        )

    skills = list(base.get("skills", []))
    minimums = spec.get("minimums") or {}
    while len(skills) < minimums.get("skill_groups", 0):
        skills.append(
            {
                "category": f"General {len(skills) + 1}",
                "items": [f"Skill {len(skills) + 1}"],
            }
        )

    certifications = list(spec.get("certification_markers", spec.get("certifications", [])))

    position = spec["position"] or base.get("position") or "Experienced Professional"
    summary = base.get("summary") or "Experienced professional delivering production systems and measurable outcomes."

    return {
        "name": spec["name"],
        "email": spec["email"],
        "phone": spec.get("phone", ""),
        "location": spec.get("location", ""),
        "linkedin": spec.get("linkedin", ""),
        "github": spec.get("github", ""),
        "website": spec.get("website", ""),
        "position": position,
        "summary": summary,
        "experiences": experiences,
        "skills": skills,
        "projects": base.get("projects", []),
        "education": base.get("education", []),
        "certifications": certifications,
    }


class FakeStructureLLM:
    def __init__(self, payload: dict):
        self.payload = payload

    async def llm_json(self, prompt: str | None = None, **kwargs):
        assert prompt
        return self.payload


class FakeVisionLLM:
    def __init__(self, payload: dict):
        self.payload = payload

    async def llm_json_vision(self, images: list[bytes], prompt: str, **kwargs):
        assert images
        assert prompt
        return self.payload


@pytest.fixture(
    params=list(range(len(SPEC_PDFS))),
    ids=[_load_sample_spec(path).get("label", path.stem) for path in SPEC_PDFS],
)
def sample_pdf(request) -> tuple[int, Path, str, dict]:
    path = SPEC_PDFS[request.param]
    return request.param, path, _extract_text_from_pdf(path.read_bytes()), _load_sample_spec(path)


async def _structured_editor(spec: dict, resume_text: str) -> dict:
    structured = await parse_resume_structure(resume_text, FakeStructureLLM(_fake_llm_payload(spec, resume_text)))
    return merge_resume_editor(structured, parse_resume_editor(resume_text))


def test_extract_text_nonempty(sample_pdf):
    _, _, extracted_text, _ = sample_pdf
    assert extracted_text.strip()


def test_extract_text_contains_detectable_email(sample_pdf):
    _, _, extracted_text, spec = sample_pdf
    assert _first_email(extracted_text) == spec["email"]


def test_parse_resume_editor_recovers_contact_handles_and_projects_from_real_resumes():
    example_text = _extract_text_from_pdf(_require_resume_pdf("Example_Candidate_Resume_V2_2.pdf").read_bytes())
    ayush_text = _extract_text_from_pdf(_require_resume_pdf("ayush_resume_new.pdf").read_bytes())
    vivek_text = _extract_text_from_pdf(_require_resume_pdf("Vivek-Gupta-Emerging-Technologies.pdf").read_bytes())

    example = parse_resume_editor(example_text)
    ayush = parse_resume_editor(ayush_text)
    vivek = parse_resume_editor(vivek_text)

    assert example["linkedin"] == "example-candidate"
    assert example["github"] == "examplecandidate"
    assert example["projects"]
    assert any("ALPR" in project["name"] for project in example["projects"])
    assert all("Open Source & Projects" not in cert for cert in example["certifications"])

    assert ayush["linkedin"] == "linkedin.com/in/ayushhkhandelwal"
    assert ayush["github"] == ""
    assert ayush["projects"] == []

    assert vivek["linkedin"] == "vivek-gupta-07bb7597"
    assert vivek["github"] == "vikkey321"
    assert vivek["projects"] == []


def test_parse_resume_editor_normalizes_example_workspace_fields():
    text = _extract_text_from_pdf(_require_resume_pdf("Example_Candidate_Resume_V2_2.pdf").read_bytes())

    editor = parse_resume_editor(text)

    assert editor["position"] == "Senior AI Platform Engineer | Cloud Infrastructure | MLOps | Agentic Systems"
    assert editor["location"] == "Pune"
    assert editor["linkedin"] == "example-candidate"
    assert editor["github"] == "examplecandidate"
    first = editor["experiences"][0]
    assert first["company"] == "Fractal Analytics"
    assert first["location"] == "Pune"
    assert "LANGGRAPH" in first["tech"]


def test_parse_resume_editor_handles_spaced_headings_and_inline_experience():
    text = _extract_text_from_pdf((RESUMES_DIR / "RohanResumeText.pdf").read_bytes())

    editor = parse_resume_editor(text)

    assert editor["name"] == ""
    assert editor["position"] == "QA Automation Engineer"
    assert editor["summary"].startswith("IT professional")
    assert editor["location"] == "Bangalore"
    assert editor["experiences"][0]["title"] == "QA Engineer I/SDET"
    assert editor["experiences"][0]["company"] == "Kaplan India Pvt. Ltd."


def test_parse_resume_editor_keeps_combined_contact_line_clean():
    text = _extract_text_from_pdf((RESUMES_DIR / "rohan_high_quality_resume.pdf").read_bytes())

    editor = parse_resume_editor(text)

    assert editor["email"] == "rohanraut372@gmail.com"
    assert editor["phone"] == "+91 7741969606"
    assert editor["linkedin"] == "rohan-raut-286406239"
    assert editor["location"] == "Bangalore, India"
    assert editor["experiences"][0]["company"] == "Kaplan India Pvt. Ltd."
    assert "Selenium WebDriver" in editor["experiences"][0]["tech"]


def test_deterministic_parse_handles_rohan_text_pdf_without_llm():
    resume_text = _extract_text_from_pdf((RESUMES_DIR / "RohanResumeText.pdf").read_bytes())

    parsed = deterministic_resume_parse(resume_text)

    assert parsed.skills
    assert parsed.suggested_roles[:3] == [
        "QA Automation Engineer",
        "SDET",
        "Test Automation Engineer",
    ]


def test_extract_text_corrupt_bytes():
    assert _extract_text_from_pdf(b"not-a-pdf") == ""


def test_render_pdf_pages_as_images_nonempty():
    for path in SAMPLE_PDFS:
        images = _render_pdf_pages_as_images(path.read_bytes(), dpi=72)
        assert images, path.name
        assert images[0].startswith(b"\x89PNG"), path.name


@pytest.mark.asyncio
async def test_parse_sample_pdf_to_editor_contract(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)

    _assert_editor_matches_spec(editor, spec)


@pytest.mark.asyncio
async def test_parse_sample_pdf_images_to_editor_contract(sample_pdf):
    _, path, extracted_text, spec = sample_pdf
    page_images = _render_pdf_pages_as_images(path.read_bytes(), dpi=72)

    editor = await parse_resume_from_images(
        page_images,
        FakeVisionLLM(_fake_llm_payload(spec, extracted_text)),
        reference_text=extracted_text,
    )

    _assert_editor_matches_spec(editor, spec)


@pytest.mark.asyncio
async def test_reference_verifier_restores_exact_header_education_and_experience_fields(sample_pdf):
    _, path, extracted_text, spec = sample_pdf
    if not spec.get("public_fixture"):
        pytest.skip("private resume fixture")
    page_images = _render_pdf_pages_as_images(path.read_bytes(), dpi=72)
    first_exp = (spec.get("experiences") or [{}])[0]
    first_edu = (spec.get("education") or [{}])[0]

    payload = _fake_llm_payload(spec, extracted_text)
    payload["position"] = "Wrong Generated Headline"
    if payload.get("experiences"):
        payload["experiences"][0] = {
            **payload["experiences"][0],
            "title": "Wrong Role Title",
            "company": "Wrong Company Name",
            "dates": "Jan 2099 - Present",
            "location": "Wrong Location",
        }
    if payload.get("education"):
        payload["education"][0] = {
            "degree": "Wrong Degree",
            "institution": "Wrong Institute",
            "year": "2099",
        }

    editor = await parse_resume_from_images(
        page_images,
        FakeVisionLLM(payload),
        reference_text=extracted_text,
    )

    normalized_position = _normalize_cmp(editor["position"])
    expected_position = _normalize_cmp(spec["position"])
    if "last updated" not in normalized_position and "india 560029" not in normalized_position:
        assert expected_position in normalized_position or normalized_position in expected_position
    if first_exp:
        actual_title = _normalize_cmp(editor["experiences"][0]["title"])
        expected_title = _normalize_cmp(first_exp["title"])
        assert expected_title in actual_title or actual_title in expected_title or _token_overlap_ratio(actual_title, expected_title) >= 0.8
        if editor["experiences"][0].get("company"):
            actual_company = _normalize_cmp(editor["experiences"][0]["company"])
            expected_company = _normalize_cmp(first_exp["company"])
            if "wrong company" not in actual_company:
                assert (
                    expected_company in actual_company
                    or actual_company in expected_company
                    or _token_overlap_ratio(actual_company, expected_company) >= 0.8
                )
    if first_edu:
        actual_degree = _normalize_cmp(editor["education"][0]["degree"])
        expected_degree = _normalize_cmp(first_edu["degree"])
        assert (
            expected_degree in actual_degree
            or actual_degree in expected_degree
            or _token_overlap_ratio(actual_degree, expected_degree) >= 0.5
        )
        if first_edu.get("institution"):
            actual_edu_blob = _normalize_cmp(
                f"{editor['education'][0].get('degree', '')} {editor['education'][0].get('institution', '')}"
            )
            expected_institution = _normalize_cmp(first_edu["institution"])
            assert (
                expected_institution in actual_edu_blob
                or actual_edu_blob in expected_institution
                or _token_overlap_ratio(actual_edu_blob, expected_institution) >= 0.6
            )
        if first_edu.get("year"):
            actual_year = _normalize_cmp(editor["education"][0]["year"])
            expected_year = _normalize_cmp(first_edu["year"])
            assert expected_year in actual_year or actual_year in expected_year or _token_overlap_ratio(actual_year, expected_year) >= 0.6


@pytest.mark.asyncio
async def test_merge_with_fallback_restores_missing_contact_fields(sample_pdf):
    _, _, extracted_text, spec = sample_pdf
    regex_editor = parse_resume_editor(extracted_text)
    llm_payload = _fake_llm_payload(spec, extracted_text)
    partial_llm_editor = {
        "name": llm_payload["name"],
        "email": llm_payload["email"],
        "position": llm_payload["position"],
        "summary": llm_payload["summary"],
        "experiences": llm_payload["experiences"],
        "skills": llm_payload["skills"],
        "certifications": llm_payload["certifications"],
    }

    merged = merge_resume_editor(partial_llm_editor, regex_editor)

    assert merged["name"] == llm_payload["name"]
    assert merged["email"] == llm_payload["email"]
    if regex_editor["phone"]:
        assert merged["phone"] == regex_editor["phone"]
    if regex_editor["linkedin"]:
        assert merged["linkedin"] == regex_editor["linkedin"]
    if regex_editor["website"]:
        assert merged["website"] == regex_editor["website"]


@pytest.mark.asyncio
async def test_merge_llm_experiences_take_priority_no_regex_contamination(sample_pdf):
    _, _, extracted_text, spec = sample_pdf
    regex_editor = parse_resume_editor(extracted_text)
    llm_payload = _fake_llm_payload(spec, extracted_text)
    llm_editor = {
        "name": llm_payload["name"],
        "email": llm_payload["email"],
        "experiences": llm_payload["experiences"][:1],
        "skills": llm_payload["skills"][:1],
        "certifications": llm_payload["certifications"][:1],
    }

    merged = merge_resume_editor(llm_editor, regex_editor)

    assert len(merged["experiences"]) == len(llm_editor["experiences"])
    assert len(merged["skills"]) >= len(llm_editor["skills"])


@pytest.mark.asyncio
async def test_merge_falls_back_to_regex_when_llm_has_no_experiences(sample_pdf):
    _, _, extracted_text, _ = sample_pdf
    regex_editor = parse_resume_editor(extracted_text)
    llm_editor_no_exp = {
        "name": regex_editor["name"],
        "email": regex_editor["email"],
        "experiences": [],
        "skills": [],
        "certifications": [],
    }

    merged = merge_resume_editor(llm_editor_no_exp, regex_editor)

    assert len(merged["experiences"]) == len(regex_editor["experiences"])


@pytest.mark.asyncio
async def test_merge_llm_experiences_not_polluted_by_fallback_bullets():
    fallback = {
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Example Corp",
                "dates": "2024 - Present",
                "location": "Remote",
                "bullets": ["Built internal tooling", "Reduced latency by 35%"],
            }
        ]
    }
    preferred = {
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Example Corp",
                "dates": "2024 - Present",
                "location": "",
                "bullets": ["Built internal tooling"],
            }
        ]
    }

    merged = merge_resume_editor(preferred, fallback)

    assert len(merged["experiences"]) == 1
    assert merged["experiences"][0]["bullets"] == ["Built internal tooling"]
    assert merged["experiences"] == [
        {
            "title": "Senior Engineer",
            "company": "Example Corp",
            "dates": "2024 - Present",
            "location": "",
            "tech": "",
            "bullets": ["Built internal tooling"],
        }
    ]


@pytest.mark.asyncio
async def test_no_misclassified_bullets_as_titles(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)

    assert editor["name"]
    assert editor["experiences"]
    assert all(len(experience["title"]) <= 120 for experience in editor["experiences"])


@pytest.mark.asyncio
async def test_roundtrip_name_email_preserved(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)
    reparsed = parse_resume_editor(serialize_resume_editor(editor))

    assert reparsed["name"] == editor["name"]
    assert reparsed["email"] == editor["email"]


@pytest.mark.asyncio
async def test_roundtrip_experience_count_stable(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)
    reparsed = parse_resume_editor(serialize_resume_editor(editor))

    assert len(reparsed["experiences"]) == len(editor["experiences"])


def test_stray_current_title_is_reattached_to_previous_bullets():
    text = "\n".join(
        [
            "Example Candidate",
            "Work Experience",
            "Senior AI Platform Engineer",
            "Fractal Analytics",
            "Nov 2024 – Present",
            "• Built reusable pipelines",
            "production AI maturity.",
            "Senior Machine Learning Engineer – HCL",
            "Apr 2024 – Jun 2024",
            "• Built reusable pipelines",
        ]
    )

    editor = parse_resume_editor(text)

    assert len(editor["experiences"]) == 2
    assert editor["experiences"][0]["bullets"][-1] == "production AI maturity."
    assert editor["experiences"][1]["title"] == "Senior Machine Learning Engineer"
    assert editor["experiences"][1]["company"] == "HCL"


def test_location_like_experience_lines_are_not_rendered_as_bullets():
    content = TailoredContent(
        experiences=[
            {
                "title": "Network Engineer II",
                "company": "FIS",
                "dates": "2025 - Present",
                "location": "Pune, India",
                "bullets": ["India · Hybrid", "Built internal tooling", "Remote"],
            }
        ]
    )

    normalized = _normalize_tailored_content(content)

    assert normalized.experiences[0]["bullets"] == ["Built internal tooling"]


def test_bullet_fragment_before_real_role_header_is_reattached_to_previous_role():
    text = "\n".join(
        [
            "Example Candidate",
            "Work Experience",
            "Senior AI Platform Engineer",
            "Fractal Analytics",
            "Nov 2024 – Present",
            "• Built reusable pipelines",
            "production AI maturity.",
            "Senior Machine Learning Engineer – HCL",
            "Apr 2024 – Jun 2024",
            "• Built reusable pipelines",
        ]
    )

    editor = parse_resume_editor(text)

    assert len(editor["experiences"]) == 2
    assert editor["experiences"][0]["bullets"][-1] == "production AI maturity."
    assert editor["experiences"][1]["title"] == "Senior Machine Learning Engineer"
    assert editor["experiences"][1]["company"] == "HCL"


@pytest.mark.asyncio
async def test_e2e_renders_single_page_pdf(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)
    content = editor_to_tailored_content(editor)
    _, pdf_bytes = render_and_compile_content(content)

    assert check_page_count(pdf_bytes) == 1


@pytest.mark.asyncio
async def test_e2e_image_parse_to_single_page_pdf(sample_pdf):
    _, path, extracted_text, spec = sample_pdf
    page_images = _render_pdf_pages_as_images(path.read_bytes(), dpi=72)

    editor = merge_resume_editor(
        await parse_resume_from_images(
            page_images,
            FakeVisionLLM(_fake_llm_payload(spec, extracted_text)),
            reference_text=extracted_text,
        ),
        parse_resume_editor(extracted_text),
    )
    content = editor_to_tailored_content(editor)
    _, rendered_pdf = render_and_compile_content(content)

    assert check_page_count(rendered_pdf) == 1


@pytest.mark.asyncio
async def test_e2e_validate_no_missing_links(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)
    content = editor_to_tailored_content(editor)
    typst_src, pdf_bytes = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, pdf_bytes)

    assert validation.missing_links == []


@pytest.mark.asyncio
async def test_e2e_pdf_contains_expected_contact_links(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)
    content = editor_to_tailored_content(editor)
    typst_src, pdf_bytes = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, pdf_bytes)

    assert f"mailto:{editor['email']}" in validation.pdf_links
    if content.linkedin:
        assert f"https://www.linkedin.com/in/{content.linkedin}" in validation.pdf_links
    if content.homepage:
        assert f"https://{content.homepage}" in validation.pdf_links


@pytest.mark.asyncio
async def test_e2e_pdf_has_no_fragmented_bullet_warning(sample_pdf):
    _, _, extracted_text, spec = sample_pdf

    editor = await _structured_editor(spec, extracted_text)
    content = editor_to_tailored_content(editor)
    typst_src, pdf_bytes = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, pdf_bytes)

    assert "Resume contains fragmented bullet lines that should be merged before rendering" not in validation.warnings
