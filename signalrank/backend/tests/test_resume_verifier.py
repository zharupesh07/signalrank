from domain.resume_verifier import (
    _fix_mashed_words,
    _build_vocab,
    _verify_certifications,
    _verify_contact,
    _verify_experiences,
    _verify_skills,
    _correct_date_string,
    _extract_ref_dates,
    verify_against_reference,
)


REF_TEXT = """\
Example Candidate
Senior AI Platform Engineer | Cloud Infrastructure | MLOps | Agentic Systems
(+91) 7020901969 | examplecandidate@gmail.com | examplecandidate.github.io

Senior AI Platform Engineer (GenAI, LLMOps, CI/CD) – Fractal Analytics  Nov 2024 – Present
Architected a centralized Agentic Factory, standardizing the lifecycle for 300+ AI agents.

Senior Machine Learning Engineer – HCL  Apr 2024 – Jun 2024
Architected human-in-the-loop evaluation frameworks for enterprise models.

Machine Learning Engineer – Chugani  Feb 2022 – May 2023
Engineered a real-time liveness detection system.

Machine Learning Engineer – Yang  Apr 2019 – Jan 2022
Built an automated AI audit system processing real-time factory data streams.

AppliedAI Course, Pyspark and Data Engineering
"""

VIVEK_REF = """\
Vivek Shivbachanprasad Gupta
(+91) 8796142757 | vikkey321@gmail.com

Technical Expert Innovation & Research Engineer – Havells  Feb 2023 – Present
Led and contributed to the development of IoT-based sensor and home automation projects.

Tech Lead at Digital Technology Office – Cognizant Technology Solutions  Sep 2016 – Mar 2021
Directed and individually contributed to more than 200+ Proof of Concepts.
"""


def test_verify_contact_overrides_wrong_email():
    editor = {"email": "wrong@example.com", "phone": "+1 555-1234", "name": "Example Candidate"}
    result = _verify_contact(dict(editor), REF_TEXT)
    assert result["email"] == "examplecandidate@gmail.com"


def test_verify_contact_preserves_correct_email():
    editor = {"email": "examplecandidate@gmail.com", "phone": "(+91) 7020901969", "name": "Example Candidate"}
    result = _verify_contact(dict(editor), REF_TEXT)
    assert result["email"] == "examplecandidate@gmail.com"
    assert "7020901969" in result["phone"]


def test_verify_contact_overrides_wrong_phone():
    editor = {"email": "examplecandidate@gmail.com", "phone": "+91 9999999999", "name": "Example Candidate"}
    result = _verify_contact(dict(editor), REF_TEXT)
    assert "7020901969" in result["phone"]


def test_verify_certifications_removes_hallucinated():
    certs = [
        "AppliedAI Course",
        "Google Cloud Certified Professional Cloud Architect",
        "AWS Certified Machine Learning – Specialty",
    ]
    result = _verify_certifications(certs, REF_TEXT)
    assert "AppliedAI Course" in result
    assert len(result) == 1


def test_verify_certifications_keeps_real():
    certs = ["AppliedAI Course", "Pyspark and Data Engineering"]
    result = _verify_certifications(certs, REF_TEXT)
    assert len(result) == 2


def test_verify_certifications_keeps_partial_word_overlap():
    ref = "Certified Design Sprint Master by AJ&Smart Company Berlin"
    certs = ["Certified Design Sprint Master"]
    result = _verify_certifications(certs, ref)
    assert len(result) == 1


def test_verify_dates_corrects_wrong_year():
    ref_dates = _extract_ref_dates(VIVEK_REF)
    corrected = _correct_date_string("Sep 2019 – Mar 2021", ref_dates, VIVEK_REF)
    assert "Sep 2016" in corrected
    assert "Mar 2021" in corrected


def test_verify_dates_preserves_correct():
    ref_dates = _extract_ref_dates(REF_TEXT)
    corrected = _correct_date_string("Nov 2024 – Present", ref_dates, REF_TEXT)
    assert corrected == "Nov 2024 – Present"


def test_fix_mashed_words_splits_correctly():
    ref = "Led and contributed to the development of IoT based sensor and home automation projects"
    vocab = _build_vocab(ref)
    text = "Ledandcontributedtothedevelopmentof IoT based sensor"
    result = _fix_mashed_words(text, vocab)
    assert "led and contributed to the development of" in result.lower()


def test_fix_mashed_words_handles_ocr_misread():
    ref = "Led and contributed to the development of IoT based sensor and home automation projects"
    vocab = _build_vocab(ref)
    # LLM misread "IoT" as "lot" — the "l" isn't in vocab but skip allows recovery
    text = "lot-basedsensorsandhomeautomationprojects"
    result = _fix_mashed_words(text, vocab)
    assert "based" in result.lower()
    assert "sensor" in result.lower()
    assert "automation" in result.lower()


def test_fix_mashed_words_ignores_short_tokens():
    vocab = _build_vocab("some reference text with words")
    text = "Normal short tokens here"
    result = _fix_mashed_words(text, vocab)
    assert result == text


def test_verify_no_op_when_reference_empty():
    editor = {"name": "Test", "email": "t@t.com", "certifications": ["Fake Cert"]}
    result = verify_against_reference(dict(editor), "")
    assert result["certifications"] == ["Fake Cert"]
    assert result["name"] == "Test"


def test_verify_experiences_fixes_bullets_and_dates():
    experiences = [
        {
            "title": "Tech Lead",
            "company": "Cognizant Technology Solutions",
            "dates": "Sep 2019 – Mar 2021",
            "location": "Bengaluru",
            "bullets": [
                "Ledandcontributedtothedevelopmentof IoT based sensor and home automation projects",
                "Directed and individually contributed to more than 200+ Proof of Concepts.",
            ],
        }
    ]
    result = _verify_experiences(experiences, VIVEK_REF)
    assert "Sep 2016" in result[0]["dates"]
    first_bullet = result[0]["bullets"][0].lower()
    assert "led" in first_bullet
    assert "contributed" in first_bullet


def test_verify_contact_fixes_mashed_name():
    editor = {"name": "ExampleCandidate", "email": "examplecandidate@gmail.com"}
    result = _verify_contact(dict(editor), REF_TEXT)
    assert result["name"] == "Example Candidate"


def test_verify_contact_keeps_spaced_name():
    editor = {"name": "Example Candidate", "email": "examplecandidate@gmail.com"}
    result = _verify_contact(dict(editor), REF_TEXT)
    assert result["name"] == "Example Candidate"


def test_verify_contact_extracts_social_handles_and_website():
    ref = """\
Example Candidate
Github : example_user
LinkedIn : example-user
www.example.dev
"""
    result = _verify_contact({"name": "Example Candidate"}, ref)
    assert result["github"] == "example_user"
    assert result["linkedin"] == "example-user"
    assert result["website"] == "example.dev"


def test_verify_contact_replaces_obviously_junk_location_and_infers_position():
    ref = """\
Example Candidate
Remote, India
Summary
Systems Consultant with 8 years of experience delivering ERP transformations.
"""
    result = _verify_contact({"location": "Last Updated on 18th November 2024", "position": ""}, ref)
    assert result["location"] == "Remote, India"
    assert result["position"] == "Systems Consultant"


def test_verify_skills_drops_garbled_groups():
    skills = [
        {"category": "Languages", "items": ["G", "R", "O", "O", "V", "Y"]},
        {"category": "Cloud", "items": ["AWS", "GCP", "Docker"]},
    ]
    result = _verify_skills(skills, REF_TEXT)
    assert len(result) == 1
    assert result[0]["category"] == "Cloud"


def test_verify_skills_keeps_valid_groups():
    skills = [
        {"category": "Cloud", "items": ["AWS", "GCP", "Docker"]},
        {"category": "Languages", "items": ["Python", "SQL", "Bash"]},
    ]
    result = _verify_skills(skills, REF_TEXT)
    assert len(result) == 2


def test_expand_to_fill_page_increases_spacing():
    from llm.resume_tailor import TailoredContent, _fit_to_one_page

    content = TailoredContent(
        name="Test",
        par_leading="0.48em",
        list_spacing="0.25em",
        experiences=[{"title": "Eng", "company": "Co", "bullets": ["Did stuff"]}],
    )
    assert content.par_leading == "0.48em"
    assert content.list_spacing == "0.25em"
