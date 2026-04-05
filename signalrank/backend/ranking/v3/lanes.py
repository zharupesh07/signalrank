from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class Lane:
    name: str
    detection_keywords: list[str]
    query_templates: list[str]
    must_have_terms: list[str]
    negative_terms: list[str]
    weight_overrides: dict[str, float]


LANE_REGISTRY: dict[str, Lane] = {
    "innovation": Lane(
        name="innovation",
        detection_keywords=[
            "innovation", "prototyping", "prototype", "emerging tech",
            "innovation strategy", "innovation program", "emerging technologies",
            "rapid poc", "mvp", "creative technologist",
        ],
        query_templates=[
            "innovation lead", "emerging technology lead", "applied AI researcher",
            "creative technologist", "innovation engineer", "R&D engineer",
            "technical innovation manager",
        ],
        must_have_terms=["innovation", "prototype", "prototyping", "innovation lab", "mvp"],
        negative_terms=["support engineer", "qa engineer", "full stack developer", "generic consultant"],
        weight_overrides={"role_family_match": 0.5, "description_role_family_terms": 0.3},
    ),
    "iot": Lane(
        name="iot",
        detection_keywords=[
            "iot", "embedded", "sensors", "edge computing", "smart devices",
            "firmware", "microcontroller", "arduino", "raspberry pi", "mqtt",
        ],
        query_templates=[
            "IoT engineer", "embedded systems engineer", "edge computing engineer",
            "IoT solutions architect", "smart devices engineer",
        ],
        must_have_terms=["iot", "embedded", "edge", "sensors", "firmware"],
        negative_terms=["support", "qa", "full stack"],
        weight_overrides={"role_family_match": 0.4, "skill_overlap": 0.2},
    ),
    "conversational_ai": Lane(
        name="conversational_ai",
        detection_keywords=[
            "chatbot", "voice agent", "conversational ai", "llm app", "nlp",
            "dialogue system", "virtual assistant", "rasa", "dialogflow",
        ],
        query_templates=[
            "conversational AI engineer", "chatbot developer", "NLP engineer",
            "LLM application engineer", "voice AI engineer",
        ],
        must_have_terms=["conversational", "chatbot", "nlp", "voice", "dialogue"],
        negative_terms=["support", "qa", "sales"],
        weight_overrides={"role_family_match": 0.4, "skill_overlap": 0.3},
    ),
    "network": Lane(
        name="network",
        detection_keywords=[
            "firewall", "routing", "network automation", "cisco", "juniper",
            "bgp", "ospf", "network engineer", "infra", "sdn", "nfv",
            "network infrastructure",
        ],
        query_templates=[
            "network engineer", "network automation engineer", "firewall engineer",
            "network infrastructure engineer", "SDN engineer", "network architect",
        ],
        must_have_terms=["network", "firewall", "routing", "cisco", "infrastructure"],
        negative_terms=["software engineer", "full stack", "qa", "support"],
        weight_overrides={"role_family_match": 0.5, "must_have_hits": 0.3},
    ),
    "r_and_d": Lane(
        name="r_and_d",
        detection_keywords=[
            "applied research", "r&d", "research and development", "proof of concept",
            "poc", "prototype", "experimental", "lab",
        ],
        query_templates=[
            "research engineer", "applied researcher", "R&D engineer",
            "research scientist", "technology research lead",
        ],
        must_have_terms=["research", "r&d", "proof of concept", "poc", "experimental"],
        negative_terms=["support", "qa", "junior", "entry level"],
        weight_overrides={"role_family_match": 0.4, "description_role_family_terms": 0.2},
    ),
    "sap_erp": Lane(
        name="sap_erp",
        detection_keywords=[
            "sap", "s/4hana", "order to cash", "otc", "sap sd",
            "sap mm", "sap gts", "abap", "sales and distribution",
        ],
        query_templates=[
            "SAP SD Consultant", "SAP Functional Consultant", "SAP OTC Consultant",
            "SAP GTS Consultant", "SAP MM Consultant",
        ],
        must_have_terms=["sap", "s/4hana", "sap sd", "sap mm", "sap gts"],
        negative_terms=["machine learning engineer", "ai engineer", "research", "full stack"],
        weight_overrides={"role_family_match": 0.5, "must_have_hits": 0.45},
    ),
}


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    hits = 0
    for keyword in keywords:
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
        if re.search(pattern, text):
            hits += 1
    return hits


def detect_active_lanes(
    resume_text: str,
    target_roles: list[str],
    current_focus: str | None,
) -> list[str]:
    """Return lane names when there is enough evidence across resume, target roles, or focus."""
    search_corpus = " ".join([
        resume_text.lower(),
        " ".join(target_roles).lower(),
        (current_focus or "").lower(),
    ])
    active: list[str] = []
    for name, lane in LANE_REGISTRY.items():
        hits = _count_keyword_hits(search_corpus, lane.detection_keywords)
        role_hits = _count_keyword_hits(" ".join(target_roles).lower(), lane.query_templates)
        focus_hits = _count_keyword_hits((current_focus or "").lower(), lane.detection_keywords)
        if hits >= 2 or role_hits >= 1 or focus_hits >= 1:
            active.append(name)
    return active
