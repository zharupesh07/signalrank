import pytest

from domain.resume_editor import editor_to_tailored_content, parse_resume_editor, serialize_resume_editor

pytestmark = pytest.mark.unit


def test_serialize_resume_editor_emits_structured_resume_text():
    editor = {
        "name": "Example Candidate",
        "position": "Senior Software Engineer",
        "email": "candidate@example.com",
        "phone": "+91 90000 00000",
        "location": "Remote",
        "linkedin": "https://linkedin.com/in/example-candidate",
        "github": "https://github.com/example-candidate",
        "website": "https://candidate.dev",
        "summary": "Platform engineer with **Python** and cloud systems experience.",
        "experiences": [
            {
                "title": "Senior Engineer",
                "company": "Example Enterprise",
                "dates": "Jan 2024 - Present",
                "location": "Remote",
                "bullets": ["Built internal tooling", "Reduced latency by 35%"],
            }
        ],
        "projects": [
            {"name": "Example Project", "url": "https://github.com/example-candidate/example-project", "description": "Job search copilot"}
        ],
        "skills": [{"category": "Programming", "items": ["Python", "SQL"]}],
        "certifications": ["AWS Certified Developer"],
    }

    text = serialize_resume_editor(editor)

    assert "Example Candidate" in text
    assert "Example Enterprise" in text
    assert "Summary" in text
    assert "Work Experience" in text
    assert "Technical Skills" in text
    assert "Certifications" in text
    assert "- Built internal tooling" in text


def test_parse_resume_editor_reads_serialized_sections():
    resume_text = """Example Candidate
Senior Software Engineer
candidate@example.com
+91 90000 00000
Remote
https://linkedin.com/in/example-candidate
https://github.com/example-candidate
https://candidate.dev

Summary
Platform engineer with **Python** and cloud systems experience.

Work Experience
Senior Engineer - Example Enterprise
Jan 2024 - Present
Remote
- Built internal tooling
- Reduced latency by 35%

Projects
Example Project
https://github.com/example-candidate/example-project
- Job search copilot

Technical Skills
Programming: Python, SQL

Certifications
AWS Certified Developer
"""

    parsed = parse_resume_editor(resume_text)

    assert parsed["name"] == "Example Candidate"
    assert parsed["email"] == "candidate@example.com"
    assert parsed["experiences"][0]["company"] == "Example Enterprise"
    assert parsed["experiences"][0]["bullets"] == ["Built internal tooling", "Reduced latency by 35%"]
    assert parsed["projects"][0]["name"] == "Example Project"
    assert parsed["skills"][0]["items"] == ["Python", "SQL"]
    assert parsed["certifications"] == ["AWS Certified Developer"]


def test_parse_resume_editor_handles_dense_resume_layout():
    resume_text = """Example Candidate
Systems Certification
A hard working and dynamic professional with almost 7 years of working experience as enterprise
systems consultant with complete understanding of supply chain and business process delivery
module
candidate@example.com
+91 9044781514
Remote
linkedin.com/in/example-candidate
WORK EXPERIENCE
Senior Technology Analyst
Example Enterprise
09/2022 - Present
Remote
Working as a Senior Analyst in the enterprise delivery segment - accelerated capability team.
Configured delivery processing, shipping point, output determination and storage location determination.
Application Development Analyst
Example Consulting
08/2021 - 09/2022
Remote
Involved in all aspects of S/4 HANA implementation process from project planning, business requirement gathering.
SKILLS AND ABILITIES
ERP Delivery
Process Design
Python
CERTIFICATION AND INNOVATION
Systems Certification
Automation Toolkit
"""

    parsed = parse_resume_editor(resume_text)

    assert parsed["name"] == "Example Candidate"
    assert parsed["email"] == "candidate@example.com"
    assert parsed["summary"].startswith("A hard working and dynamic professional")
    assert parsed["experiences"][0]["company"] == "Example Enterprise"
    assert parsed["experiences"][0]["bullets"] == [
        "Working as a Senior Analyst in the enterprise delivery segment - accelerated capability team.",
        "Configured delivery processing, shipping point, output determination and storage location determination.",
    ]
    assert parsed["experiences"][1]["bullets"] == [
        "Involved in all aspects of S/4 HANA implementation process from project planning, business requirement gathering.",
    ]
    assert parsed["skills"][0]["items"] == ["ERP Delivery", "Process Design", "Python"]
    assert parsed["certifications"] == ["Systems Certification Automation Toolkit"]


def test_parse_resume_editor_merges_wrapped_experience_lines_into_dense_bullets():
    resume_text = """Example Candidate
candidate@example.com
+91 9044781514
Remote
linkedin.com/in/example-candidate
WORK EXPERIENCE
Senior Technology Analyst
Example Enterprise
09/2022 - Present
Remote
Working as a Senior Analyst in the enterprise
Delivery Capability Team. Aligned to the
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
        "Working as a Senior Analyst in the enterprise Delivery Capability Team. Aligned to the Order to Cash (OTC) workstream focusing on the Customer Service and Planning work process.",
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
        "name": "Example Candidate",
        "email": "candidate@example.com",
        "linkedin": "https://linkedin.com/in/example-candidate",
        "website": "candidate.dev",
        "summary": "Enterprise systems engineer.",
        "experiences": [{"title": "Analyst", "company": "Example Enterprise", "dates": "2022 - Present", "location": "Remote", "bullets": ["Built workflows"]}],
        "projects": [],
        "skills": [{"category": "General", "items": ["ERP", "Python"]}],
        "certifications": ["Systems Certification"],
    })

    assert content.homepage == "candidate.dev"
    assert content.linkedin == "example-candidate"
    assert content.certifications == ["Systems Certification"]
