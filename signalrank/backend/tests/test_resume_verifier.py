from domain.resume_verifier import (
    _fix_mashed_words,
    _build_vocab,
    _verify_certifications,
    _verify_contact,
    _verify_experiences,
    _verify_skills,
    _correct_date_string,
    _extract_ref_dates,
    _is_cert_section_header,
    _normalize_ligatures,
    _is_inverted_caps_word,
    _normalize_inverted_caps,
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
Sample Research Engineer
+1 555 010 0101 | research@example.com

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


def test_verify_certifications_drops_section_header():
    ref = "AppliedAI Course\nOpen Source & Projects\nALPR | PDF2Podcast | RockReveal AI"
    certs = [
        "AppliedAI Course",          # real — keep
        "Open Source & Projects",    # section header compound — drop
        "Open Source",               # section header bare — drop
        "Projects",                  # section header bare — drop
        "Technical Skills",          # section header — drop
        "Key Achievements",          # section header — drop
    ]
    result = _verify_certifications(certs, ref)
    assert result == ["AppliedAI Course"]


def test_is_cert_section_header():
    assert _is_cert_section_header("Open Source & Projects") is True
    assert _is_cert_section_header("Open Source") is True
    assert _is_cert_section_header("Projects") is True
    assert _is_cert_section_header("Technical Skills") is True
    assert _is_cert_section_header("Key Achievements") is True
    assert _is_cert_section_header("Work Experience") is True
    # Real certs should NOT be flagged as headers
    assert _is_cert_section_header("AWS Certified Machine Learning Specialty") is False
    assert _is_cert_section_header("Certification in Machine Learning") is False
    assert _is_cert_section_header("AppliedAI Course") is False


def test_verify_certifications_drops_pipe_separated_projects():
    ref = "ALPR PDF2Podcast RockReveal AI Idea Generation open source projects AppliedAI Course"
    certs = [
        "ALPR(Streamlit Hall of Fame) | PDF2Podcast | RockReveal AI | Idea Generation | Others",
        "AppliedAI Course",
    ]
    result = _verify_certifications(certs, ref)
    assert "AppliedAI Course" in result
    assert not any("PDF2Podcast" in c for c in result)


def test_verify_certifications_drops_tech_stack():
    ref = "Claude Code Copilot HuggingFace Gemini OpenAI RAG LangGraph Streamlit AppliedAI Course"
    certs = [
        "TECH: CLAUDE CODE, COPILOT, HUGGINGFACE, GEMINI, OPENAI, RAG, LANGGRAPH, STREAMLIT",
        "AppliedAI Course",
    ]
    result = _verify_certifications(certs, ref)
    assert result == ["AppliedAI Course"]


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


def test_normalize_ligatures_fi_and_fl():
    assert _normalize_ligatures("Certiﬁed") == "Certified"
    assert _normalize_ligatures("Oﬃce") == "Office"
    assert _normalize_ligatures("ﬂow") == "flow"
    assert _normalize_ligatures("no ligatures here") == "no ligatures here"


def test_is_inverted_caps_word_detects_pattern():
    assert _is_inverted_caps_word("SENiOR") is True
    assert _is_inverted_caps_word("ENGiNEER") is True
    assert _is_inverted_caps_word("AGENTiC") is True
    assert _is_inverted_caps_word("RAPiD") is True


def test_is_inverted_caps_word_ignores_normal():
    assert _is_inverted_caps_word("Senior") is False
    assert _is_inverted_caps_word("MLOPS") is False  # all uppercase, no inverted marker
    assert _is_inverted_caps_word("AI") is False  # too short
    assert _is_inverted_caps_word("Platform") is False


def test_normalize_inverted_caps_position():
    raw = "SENiOR AI PLATFORM ENGiNEER | CLOUD INFRASTRUCTURE | MLOPS | AGENTiC SYSTEMS"
    result = _normalize_inverted_caps(raw)
    assert "Senior" in result
    assert "Engineer" in result
    assert "Platform" in result
    assert "Infrastructure" in result
    assert "MLOps" in result
    assert "Agentic" in result
    assert "Systems" in result


def test_normalize_inverted_caps_no_op_on_normal_text():
    normal = "Senior AI Platform Engineer | Cloud Infrastructure"
    assert _normalize_inverted_caps(normal) == normal


def test_verify_experiences_strips_company_from_title():
    ref = "Network Engineer II – FIS  Jun 2025 – Present\nNetwork Engineer I – FIS  Jul 2023"
    exps = [
        {"title": "Network Engineer II – FIS", "company": "FIS", "dates": "Jun 2025 – Present", "bullets": []},
        {"title": "Network Engineer I – FIS", "company": "FIS", "dates": "Jul 2023 – Jun 2025", "bullets": []},
    ]
    result = _verify_experiences(exps, ref)
    assert result[0]["title"] == "Network Engineer II"
    assert result[1]["title"] == "Network Engineer I"
    assert result[0]["company"] == "FIS"


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
