from pathlib import Path

import pytest

from api.routes.onboarding import _extract_text_from_pdf
from domain.resume_editor import (
    editor_to_tailored_content,
    merge_resume_editor,
    parse_resume_editor,
    serialize_resume_editor,
)
from llm.resume_parser import parse_resume_structure
from llm.resume_tailor import check_page_count, render_and_compile_content, validate_resume_artifacts


RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"
SAMPLE_PDFS = sorted(RESUMES_DIR.glob("*.pdf"))

EXPECTED_STRUCTURES = {
    "Example_Candidate_Resume_V2_2.pdf": {
        "name": "Example Candidate",
        "email": "examplecandidate@gmail.com",
        "phone": "(+91) 7020901969",
        "location": "Pune, India",
        "linkedin": "examplecandidate",
        "github": "",
        "website": "",
        "position": "Senior AI Platform Engineer",
        "summary": "Senior AI platform engineer focused on cloud infrastructure, MLOps, and agentic systems.",
        "experiences": [
            {
                "title": "Senior AI Platform Engineer",
                "company": "Fractal Analytics",
                "dates": "2024 - Present",
                "location": "Pune, India",
                "bullets": [
                    "Built platform capabilities for production GenAI and LLMOps systems.",
                    "Improved observability and CI/CD for AI workloads.",
                ],
            },
            {
                "title": "Senior Platform Engineer",
                "company": "FloBiz",
                "dates": "2022 - 2024",
                "location": "Remote",
                "bullets": ["Scaled backend infrastructure and developer workflows."],
            },
            {
                "title": "Senior Software Engineer",
                "company": "Dow Chemical International Private Limited",
                "dates": "2021 - 2022",
                "location": "Bengaluru, India",
                "bullets": ["Delivered internal platform automation and cloud tooling."],
            },
            {
                "title": "Software Engineer",
                "company": "Birlasoft",
                "dates": "2019 - 2021",
                "location": "Pune, India",
                "bullets": ["Developed enterprise applications and integrations."],
            },
        ],
        "skills": [
            {"category": "Cloud & DevOps", "items": ["GCP", "Docker", "Kubernetes"]},
            {"category": "MLOps", "items": ["Vertex AI", "MLflow", "CI/CD"]},
            {"category": "Agentic AI", "items": ["LangGraph", "RAG", "OpenAI"]},
            {"category": "Languages", "items": ["Python", "SQL", "TypeScript"]},
            {"category": "Data", "items": ["BigQuery", "Pub/Sub"]},
        ],
        "projects": [],
        "education": [],
        "certifications": ["AppliedAI Course", "AWS Certification"],
    },
    "Vivek-Gupta-Emerging-Technologies.pdf": {
        "name": "Vivek Shivbachanprasad Gupta",
        "email": "vikkey321@gmail.com",
        "phone": "(+91) 8796142757",
        "location": "Pune, India",
        "linkedin": "vivek-gupta",
        "github": "",
        "website": "",
        "position": "Innovation & Research Engineer",
        "summary": "Innovation engineer working across full-stack products, AI, IoT, and rapid prototyping.",
        "experiences": [
            {
                "title": "Technical Expert Innovation & Research Engineer",
                "company": "Havells (Center for Research & Innovation)",
                "dates": "2022 - Present",
                "location": "Noida, India",
                "bullets": ["Built internal innovation tooling and cross-functional prototypes."],
            },
            {
                "title": "Senior Engineer",
                "company": "Havells",
                "dates": "2020 - 2022",
                "location": "Noida, India",
                "bullets": ["Led internal IoT and analytics platform initiatives."],
            },
            {
                "title": "Engineer",
                "company": "Product Engineering Team",
                "dates": "2018 - 2020",
                "location": "Pune, India",
                "bullets": ["Delivered experiments across hardware and digital systems."],
            },
            {
                "title": "Associate Engineer",
                "company": "Innovation Lab",
                "dates": "2016 - 2018",
                "location": "Pune, India",
                "bullets": ["Supported research prototypes and pilot programs."],
            },
        ],
        "skills": [
            {"category": "Full-Stack", "items": ["Python", "JavaScript", "Node.js"]},
            {"category": "AI", "items": ["Computer Vision", "LLMs", "Prompting"]},
            {"category": "Cloud & IoT", "items": ["AWS", "MQTT", "IoT"]},
            {"category": "Hardware", "items": ["Embedded Systems", "Sensors"]},
            {"category": "Tools", "items": ["Figma", "Miro", "Arduino"]},
        ],
        "projects": [],
        "education": [],
        "certifications": [
            "Certified Design Sprint Master by AJ&Smart Company(Berlin)",
            "Innovation Management (University of Illinois at Urbana-Champaign) - Coursera",
            "Innovation Management (Rotterdam School of Management) - Coursera",
        ],
    },
    "aditya.pdf": {
        "name": "Aditya Mishra",
        "email": "adityamishra2710@gmail.com",
        "phone": "",
        "location": "Pune, India",
        "linkedin": "aditya-mishra",
        "github": "",
        "website": "",
        "position": "Network Automation Engineer",
        "summary": "Network automation engineer focused on operations tooling, infrastructure automation, and reliability.",
        "experiences": [
            {
                "title": "Network Engineer II",
                "company": "FIS",
                "dates": "2023 - Present",
                "location": "Pune, India",
                "bullets": ["Built automation to reduce network operations toil."],
            },
            {
                "title": "Network Operations Engineer",
                "company": "Global Network Team",
                "dates": "2021 - 2023",
                "location": "Pune, India",
                "bullets": ["Automated change workflows and rollout tasks."],
            },
            {
                "title": "Systems Engineer",
                "company": "Infrastructure Team",
                "dates": "2019 - 2021",
                "location": "India",
                "bullets": ["Improved operational consistency with scripting and tooling."],
            },
            {
                "title": "Graduate Engineer",
                "company": "Network Services",
                "dates": "2018 - 2019",
                "location": "India",
                "bullets": ["Supported enterprise network implementations."],
            },
        ],
        "skills": [
            {"category": "Languages", "items": ["Python", "Bash"]},
            {"category": "Automation", "items": ["Ansible", "Netmiko", "Nornir"]},
            {"category": "Platforms", "items": ["Cisco", "Juniper"]},
            {"category": "Cloud", "items": ["AWS", "GCP"]},
            {"category": "Containers", "items": ["Docker", "Kubernetes"]},
        ],
        "projects": [],
        "education": [],
        "certifications": [],
    },
    "ayush_resume_new.pdf": {
        "name": "Ayush Khandelwal",
        "email": "helloayushkh@gmail.com",
        "phone": "+91 9044781514",
        "location": "Kanpur, India",
        "linkedin": "ayushhkhandelwal",
        "github": "",
        "website": "",
        "position": "SAP Consultant",
        "summary": "Enterprise systems consultant with SAP SD and order-to-cash implementation experience.",
        "experiences": [
            {
                "title": "Senior Information Technology Analyst",
                "company": "Dow Chemical International Private Limited",
                "dates": "09/2022 - Present",
                "location": "Mumbai, Maharashtra",
                "bullets": ["Configured OTC process improvements across enterprise workflows."],
            },
            {
                "title": "Application Developement Analyst",
                "company": "Accenture Solutions Private Limited",
                "dates": "08/2021 - 09/2022",
                "location": "Noida, Uttar Pradesh",
                "bullets": ["Delivered S/4HANA implementation support across project phases."],
            },
            {
                "title": "Senior Systems Engineer",
                "company": "Infosys",
                "dates": "2017 - 2021",
                "location": "India",
                "bullets": ["Supported SAP SD delivery and automation workflows."],
            },
        ],
        "skills": [
            {"category": "General", "items": ["SAP SD", "SAP MM", "Python", "Order to Cash"]},
        ],
        "projects": [],
        "education": [],
        "certifications": [
            "SAP Certified Application Associate - SAP S/4HANA Sales",
            "SAP Script Automation",
        ],
    },
}


class FakeStructureLLM:
    async def llm_json(self, prompt: str | None = None, **kwargs):
        text = prompt or ""
        for expected in EXPECTED_STRUCTURES.values():
            if expected["email"] in text or expected["name"] in text:
                return expected
        return {"_error": "unknown_resume"}


@pytest.fixture(params=[path.name for path in SAMPLE_PDFS], ids=[path.stem for path in SAMPLE_PDFS])
def pdf_text(request) -> tuple[str, str]:
    path = RESUMES_DIR / request.param
    return path.name, _extract_text_from_pdf(path.read_bytes())


async def _structured_editor(filename: str, resume_text: str) -> dict:
    structured = await parse_resume_structure(resume_text, FakeStructureLLM())
    return merge_resume_editor(structured, parse_resume_editor(resume_text))


def test_extract_text_nonempty(pdf_text):
    filename, extracted_text = pdf_text
    assert filename in EXPECTED_STRUCTURES
    assert extracted_text.strip()


def test_extract_text_contains_email(pdf_text):
    filename, extracted_text = pdf_text
    assert EXPECTED_STRUCTURES[filename]["email"] in extracted_text


def test_extract_text_corrupt_bytes():
    assert _extract_text_from_pdf(b"not-a-pdf") == ""


@pytest.mark.asyncio
async def test_parse_sample_pdf_to_editor_contract(pdf_text):
    filename, extracted_text = pdf_text
    expected = EXPECTED_STRUCTURES[filename]

    editor = await _structured_editor(filename, extracted_text)

    assert editor["name"] == expected["name"]
    assert editor["email"] == expected["email"]
    if expected["phone"]:
        assert expected["phone"] in editor["phone"]
    assert len(editor["experiences"]) >= len(expected["experiences"])
    assert len(editor["skills"]) >= len(expected["skills"])
    for certification in expected["certifications"]:
        assert certification in editor["certifications"]


@pytest.mark.asyncio
async def test_merge_with_fallback_restores_missing_contact_fields(pdf_text):
    filename, extracted_text = pdf_text
    expected = EXPECTED_STRUCTURES[filename]
    regex_editor = parse_resume_editor(extracted_text)
    partial_llm_editor = {
        "name": expected["name"],
        "email": expected["email"],
        "position": expected["position"],
        "summary": expected["summary"],
        "experiences": expected["experiences"],
        "skills": expected["skills"],
        "certifications": expected["certifications"],
    }

    merged = merge_resume_editor(partial_llm_editor, regex_editor)

    assert merged["name"] == expected["name"]
    assert merged["email"] == expected["email"]
    if regex_editor["phone"]:
        assert merged["phone"] == regex_editor["phone"]
    if regex_editor["linkedin"]:
        assert merged["linkedin"] == regex_editor["linkedin"]
    if regex_editor["website"]:
        assert merged["website"] == regex_editor["website"]


@pytest.mark.asyncio
async def test_merge_with_partial_llm_preserves_fallback_experience_coverage(pdf_text):
    filename, extracted_text = pdf_text
    regex_editor = parse_resume_editor(extracted_text)
    expected = EXPECTED_STRUCTURES[filename]
    partial_llm_editor = {
        "name": expected["name"],
        "email": expected["email"],
        "experiences": expected["experiences"][:1],
        "skills": expected["skills"][:1],
        "certifications": expected["certifications"][:1],
    }

    merged = merge_resume_editor(partial_llm_editor, regex_editor)

    assert len(merged["experiences"]) >= len(regex_editor["experiences"])
    assert len(merged["skills"]) >= len(regex_editor["skills"])
    assert set(regex_editor["certifications"]).issubset(set(merged["certifications"]))


@pytest.mark.asyncio
async def test_merge_with_partial_llm_preserves_fallback_bullets_for_same_role():
    fallback = {
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Dow",
                "dates": "2024 - Present",
                "location": "Bengaluru",
                "bullets": ["Built internal tooling", "Reduced latency by 35%"],
            }
        ]
    }
    preferred = {
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Dow",
                "dates": "2024 - Present",
                "location": "",
                "bullets": ["Built internal tooling"],
            }
        ]
    }

    merged = merge_resume_editor(preferred, fallback)

    assert merged["experiences"] == [
        {
            "title": "Senior Engineer",
            "company": "Dow",
            "dates": "2024 - Present",
            "location": "Bengaluru",
            "bullets": ["Built internal tooling", "Reduced latency by 35%"],
        }
    ]


@pytest.mark.asyncio
async def test_no_misclassified_bullets_as_titles(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)

    assert editor["name"]
    assert editor["experiences"]
    assert all(len(experience["title"]) <= 120 for experience in editor["experiences"])


@pytest.mark.asyncio
async def test_roundtrip_name_email_preserved(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)
    reparsed = parse_resume_editor(serialize_resume_editor(editor))

    assert reparsed["name"] == editor["name"]
    assert reparsed["email"] == editor["email"]


@pytest.mark.asyncio
async def test_roundtrip_experience_count_stable(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)
    reparsed = parse_resume_editor(serialize_resume_editor(editor))

    assert len(reparsed["experiences"]) == len(editor["experiences"])


@pytest.mark.asyncio
async def test_e2e_renders_single_page_pdf(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)
    content = editor_to_tailored_content(editor)
    _, pdf_bytes = render_and_compile_content(content)

    assert check_page_count(pdf_bytes) == 1


@pytest.mark.asyncio
async def test_e2e_validate_no_missing_links(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)
    content = editor_to_tailored_content(editor)
    typst_src, pdf_bytes = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, pdf_bytes)

    assert validation.missing_links == []


@pytest.mark.asyncio
async def test_e2e_pdf_contains_expected_contact_links(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)
    content = editor_to_tailored_content(editor)
    typst_src, pdf_bytes = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, pdf_bytes)

    assert f"mailto:{editor['email']}" in validation.pdf_links
    if content.linkedin:
        assert f"https://www.linkedin.com/in/{content.linkedin}" in validation.pdf_links
    if content.homepage:
        assert f"https://{content.homepage}" in validation.pdf_links


@pytest.mark.asyncio
async def test_e2e_pdf_has_no_fragmented_bullet_warning(pdf_text):
    filename, extracted_text = pdf_text

    editor = await _structured_editor(filename, extracted_text)
    content = editor_to_tailored_content(editor)
    typst_src, pdf_bytes = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, pdf_bytes)

    assert "Resume contains fragmented bullet lines that should be merged before rendering" not in validation.warnings


def test_empty_input_returns_empty():
    assert parse_resume_editor("") == {
        "name": "",
        "position": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "website": "",
        "summary": "",
        "experiences": [],
        "projects": [],
        "skills": [],
        "certifications": [],
    }


def test_minimal_header_only():
    parsed = parse_resume_editor("Jane Doe\njane@example.com")

    assert parsed["name"] == "Jane Doe"
    assert parsed["email"] == "jane@example.com"
    assert parsed["experiences"] == []
    assert parsed["skills"] == []
