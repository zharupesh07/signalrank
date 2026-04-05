from __future__ import annotations

from dataclasses import dataclass, field


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
            "applied ai", "smart systems", "r&d", "research and development",
            "labs", "emerging technologies",
        ],
        query_templates=[
            "innovation lead", "emerging technology lead", "applied AI researcher",
            "creative technologist", "innovation engineer", "R&D engineer",
            "technical innovation manager",
        ],
        must_have_terms=["innovation", "prototype", "r&d", "applied", "emerging"],
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
            "research", "applied research", "labs", "r&d", "publications",
            "patents", "experimental", "proof of concept", "poc",
        ],
        query_templates=[
            "research engineer", "applied researcher", "R&D engineer",
            "research scientist", "technology research lead",
        ],
        must_have_terms=["research", "applied", "experimental", "poc"],
        negative_terms=["support", "qa", "junior", "entry level"],
        weight_overrides={"role_family_match": 0.4, "description_role_family_terms": 0.2},
    ),
}


def detect_active_lanes(
    resume_text: str,
    target_roles: list[str],
    current_focus: str | None,
) -> list[str]:
    """Return list of lane names whose detection_keywords match the profile."""
    search_corpus = " ".join([
        resume_text.lower(),
        " ".join(target_roles).lower(),
        (current_focus or "").lower(),
    ])
    active: list[str] = []
    for name, lane in LANE_REGISTRY.items():
        if any(kw.lower() in search_corpus for kw in lane.detection_keywords):
            active.append(name)
    return active
