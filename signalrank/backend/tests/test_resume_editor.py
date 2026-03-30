import pytest

from domain.resume_editor import editor_to_tailored_content, parse_resume_editor, serialize_resume_editor

pytestmark = pytest.mark.unit


def test_serialize_resume_editor_emits_structured_resume_text():
    editor = {
        "name": "Example Candidate",
        "position": "Senior Software Engineer",
        "email": "example@example.com",
        "phone": "+91 90000 00000",
        "location": "Bengaluru, India",
        "linkedin": "https://linkedin.com/in/example",
        "github": "https://github.com/example",
        "website": "https://example.dev",
        "summary": "Platform engineer with **Python** and cloud systems experience.",
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Dow Chemical International Private Limited",
                "dates": "Jan 2024 - Present",
                "location": "Bengaluru, India",
                "bullets": ["Built internal tooling", "Reduced latency by 35%"],
            }
        ],
        "projects": [
            {"name": "SignalRank", "url": "https://github.com/example/signalrank", "description": "Job search copilot"}
        ],
        "skills": [{"category": "Programming", "items": ["Python", "SQL"]}],
        "certifications": ["AWS Certified Developer"],
    }

    text = serialize_resume_editor(editor)

    assert "Example Candidate" in text
    assert "Dow Chemical International Private Limited" in text
    assert "Summary" in text
    assert "Work Experience" in text
    assert "Technical Skills" in text
    assert "Certifications" in text
    assert "- Built internal tooling" in text


def test_parse_resume_editor_reads_serialized_sections():
    resume_text = """Example Candidate
Senior Software Engineer
example@example.com
+91 90000 00000
Bengaluru, India
https://linkedin.com/in/example
https://github.com/example
https://example.dev

Summary
Platform engineer with **Python** and cloud systems experience.

Work Experience
Senior Engineer - Dow Chemical International Private Limited
Jan 2024 - Present
Bengaluru, India
- Built internal tooling
- Reduced latency by 35%

Projects
SignalRank
https://github.com/example/signalrank
- Job search copilot

Technical Skills
Programming: Python, SQL

Certifications
AWS Certified Developer
"""

    parsed = parse_resume_editor(resume_text)

    assert parsed["name"] == "Example Candidate"
    assert parsed["email"] == "example@example.com"
    assert parsed["experiences"][0]["company"] == "Dow Chemical International Private Limited"
    assert parsed["experiences"][0]["bullets"] == ["Built internal tooling", "Reduced latency by 35%"]
    assert parsed["projects"][0]["name"] == "SignalRank"
    assert parsed["skills"][0]["items"] == ["Python", "SQL"]
    assert parsed["certifications"] == ["AWS Certified Developer"]


def test_parse_resume_editor_handles_ayush_pdf_layout():
    resume_text = """Ayush Khandelwal
SAP Certified Application Associate - SAP S/4HANA Sales
A hard working and dynamic professional with almost 7 years of working experience as Sales
and Distribution Functional Consultant with complete understanding of Material Management
module
helloayushkh@gmail.com
+91 9044781514
Kanpur, India
linkedin.com/in/ayushhkhandelwal
WORK EXPERIENCE
Senior Information Technology Analyst
Dow Chemical International Private Limited
09/2022 - Present
Mumbai, Maharashtra
Working as an Senior Analyst in Dow's Enterprise Segment - Accelerated Capability Team.
Configured delivery processing, shipping point, output determination and storage location determination.
Application Developement Analyst
Accenture Solutions Private Limited
08/2021 - 09/2022
Noida, Uttar Pradesh
Involved in all aspects of S/4 HANA implementation process from project planning, business requirement gathering.
SKILLS AND ABILITIES
SAP SD
SAP MM
Python
CERTIFICATION AND INNOVATION
SAP Certified Application Associate - SAP S/4HANA Sales
SAP Script Automation
"""

    parsed = parse_resume_editor(resume_text)

    assert parsed["name"] == "Ayush Khandelwal"
    assert parsed["email"] == "helloayushkh@gmail.com"
    assert parsed["summary"].startswith("A hard working and dynamic professional")
    assert parsed["experiences"][0]["company"] == "Dow Chemical International Private Limited"
    assert parsed["experiences"][0]["bullets"] == [
        "Working as an Senior Analyst in Dow's Enterprise Segment - Accelerated Capability Team.",
        "Configured delivery processing, shipping point, output determination and storage location determination.",
    ]
    assert parsed["experiences"][1]["bullets"] == [
        "Involved in all aspects of S/4 HANA implementation process from project planning, business requirement gathering.",
    ]
    assert parsed["skills"][0]["items"] == ["SAP SD", "SAP MM", "Python"]
    assert parsed["certifications"] == [
        "SAP Certified Application Associate - SAP S/4HANA Sales",
        "SAP Script Automation",
    ]


def test_parse_resume_editor_merges_wrapped_experience_lines_into_dense_bullets():
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
Working as a Senior Analyst in Dow's Enterprise
Segment - Accelerated Capability Team. Aligned to the
Order to Cash (OTC) workstream focusing on the
Customer Service and Planning work process.
Configured delivery processing, shipping point, output
determination and storage location determination.
Deep understanding of special business process - Third
Party Process, Inter-company Billing & Stock Transfer,
Consignment, Scheduling agreement, Contracts etc.
"""

    parsed = parse_resume_editor(resume_text)

    assert parsed["experiences"][0]["bullets"] == [
        "Working as a Senior Analyst in Dow's Enterprise Segment - Accelerated Capability Team. Aligned to the Order to Cash (OTC) workstream focusing on the Customer Service and Planning work process.",
        "Configured delivery processing, shipping point, output determination and storage location determination.",
        "Deep understanding of special business process - Third Party Process, Inter-company Billing & Stock Transfer, Consignment, Scheduling agreement, Contracts etc.",
    ]


def test_parse_resume_editor_stops_certifications_before_education_and_awards():
    resume_text = """CERTIFICATION AND INNOVATION
SAP Certiﬁed Application Associate - SAP
S/4HANA Sales
This certiﬁcation exam validates fundamental and core
knowledge required of the SAP S/4HANA Sales and
Distribution proﬁle.
SAP Script Automation
Designed and programmed various SAP Scripts in form of
tools to carry out repetitive tasks and automate the way of
working in SAP GUI.
EDUCATION
Engineering (B. Tech) - Electronics and
Communication Engineering
AWARDS AND ACHIEVEMENTS
Infosys Insta Award
"""

    parsed = parse_resume_editor(resume_text)

    assert parsed["certifications"] == [
        "SAP Certiﬁed Application Associate - SAP S/4HANA Sales",
        "SAP Script Automation",
    ]


def test_editor_to_tailored_content_preserves_certifications_and_links():
    content = editor_to_tailored_content({
        "name": "Ayush Khandelwal",
        "email": "helloayushkh@gmail.com",
        "linkedin": "https://linkedin.com/in/ayushhkhandelwal",
        "website": "ayush.dev",
        "summary": "SAP and enterprise systems engineer.",
        "experiences": [{"title": "Analyst", "company": "Dow", "dates": "2022 - Present", "location": "Mumbai", "bullets": ["Built workflows"]}],
        "projects": [],
        "skills": [{"category": "General", "items": ["SAP SD", "Python"]}],
        "certifications": ["SAP Certified Application Associate - SAP S/4HANA Sales"],
    })

    assert content.homepage == "ayush.dev"
    assert content.linkedin == "ayushhkhandelwal"
    assert content.certifications == ["SAP Certified Application Associate - SAP S/4HANA Sales"]
