from __future__ import annotations

CANONICAL_ROLE_OPTIONS = [
    "AI/ML Engineer",
    "GenAI / LLM Engineer",
    "AI Platform Engineer",
    "Data Scientist",
    "Data Engineer",
    "Analytics Engineer",
    "MLOps/Platform Engineer",
    "Research Scientist",
    "Backend Engineer",
    "Full-Stack Engineer",
    "Frontend Engineer",
    "Mobile Engineer",
    "API / Integrations Engineer",
    "DevOps/SRE",
    "Platform Engineer",
    "Cloud Infrastructure Engineer",
    "Network Automation Engineer",
    "Infrastructure Automation Engineer",
    "Security Engineer",
    "Embedded / Systems Engineer",
    "Product Engineer",
    "Innovation Engineer",
    "Emerging Technologies Engineer",
    "R&D Engineer",
    "QA / Test Engineer",
    "SAP SD Consultant",
]

ROLE_UI_ALIASES = [
    "SAP Functional Consultant",
    "SAP S/4HANA Consultant",
    "QA Automation Engineer",
    "SDET",
]

ROLE_UI_OPTIONS = list(dict.fromkeys([
    "SAP SD Consultant",
    "SAP Functional Consultant",
    "SAP S/4HANA Consultant",
    "QA / Test Engineer",
    "QA Automation Engineer",
    "SDET",
    *CANONICAL_ROLE_OPTIONS,
]))

LOCATION_OPTIONS = [
    "Remote only",
    "Bangalore",
    "Hyderabad",
    "Mumbai",
    "Delhi/NCR",
    "Pune",
    "Any India",
    "Open to relocation",
]

TIER_OPTIONS = [
    {"label": "S-tier (FAANG, top startups)", "value": "tier_s"},
    {"label": "A-tier (strong tech companies)", "value": "tier_a"},
    {"label": "B-tier (good companies)", "value": "tier_b"},
    {"label": "Any company", "value": "any"},
]

ROLE_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "sap sd consultant": (
        "SAP SD Consultant",
        "SAP S/4HANA SD Consultant",
        "SAP SD Functional Consultant",
        "SAP OTC Functional Consultant",
    ),
    "sap functional consultant": (
        "SAP Functional Consultant",
        "SAP SD Consultant",
        "SAP MM Consultant",
        "SAP S/4HANA Consultant",
    ),
    "sap s/4hana consultant": (
        "SAP S/4HANA Consultant",
        "SAP S/4HANA SD Consultant",
        "SAP SD Consultant",
    ),
    "qa / test engineer": ("QA Engineer", "QA Automation Engineer", "SDET", "Test Automation Engineer"),
    "qa automation engineer": ("QA Automation Engineer", "QA Engineer", "SDET", "Test Engineer"),
    "sdet": ("SDET", "QA Automation Engineer", "Test Engineer"),
    "ai/ml engineer": ("AI/ML Engineer", "ML Engineer", "Machine Learning Engineer"),
    "genai / llm engineer": ("GenAI Engineer", "LLM Engineer", "Generative AI Engineer"),
    "ai platform engineer": ("AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"),
    "mlops/platform engineer": ("MLOps Engineer", "Platform Engineer", "ML Platform Engineer"),
    "data scientist": ("Data Scientist", "Applied Scientist"),
    "data engineer": ("Data Engineer", "Analytics Engineer"),
    "backend engineer": ("Backend Engineer", "Software Engineer"),
    "full-stack engineer": ("Full Stack Engineer", "Full-Stack Engineer"),
    "devops/sre": ("DevOps Engineer", "SRE", "Platform Engineer"),
    "network automation engineer": (
        "Network Automation Engineer",
        "Network Engineer Automation",
        "Cloud Network Engineer",
    ),
    "infrastructure automation engineer": (
        "Infrastructure Automation Engineer",
        "Platform Automation Engineer",
        "Cloud Infrastructure Automation Engineer",
    ),
    "innovation engineer": (
        "Innovation Engineer",
        "Emerging Technologies Engineer",
        "R&D Engineer",
        "Prototype Engineer",
    ),
    "emerging technologies engineer": (
        "Emerging Technologies Engineer",
        "Innovation Engineer",
        "R&D Engineer",
    ),
    "r&d engineer": ("R&D Engineer", "Innovation Engineer", "Prototype Engineer"),
}

# Taxonomy is intentionally "lite" now: prompt outputs are primary.
# These aliases only normalize raw LLM role titles into a small set of
# expansion buckets so query generation stays stable without forcing the
# parser into a preset ontology.
ROLE_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "sap sd consultant": (
        "sap functional consultant",
        "sap sd functional consultant",
        "sap s/4hana sales and distribution consultant",
        "sap sales and distribution consultant",
        "sap otc functional consultant",
    ),
    "network automation engineer": (
        "network operations automation engineer",
        "network engineer with automation focus",
        "network automation specialist",
        "firewall automation engineer",
    ),
    "infrastructure automation engineer": (
        "platform automation engineer",
        "cloud infrastructure automation engineer",
    ),
    "innovation engineer": (
        "innovation and r&d lead",
        "innovation manager",
        "innovation technologist",
        "technical innovation manager",
        "technical innovation consultant",
    ),
    "emerging technologies engineer": (
        "emerging technology consultant",
        "emerging technologies specialist",
        "emerging tech consultant",
        "emerging tech r&d engineer",
    ),
    "r&d engineer": (
        "r&d lead",
        "innovation and r&d consultant",
        "rapid prototyping lead",
        "rapid prototyping engineer",
    ),
    "embedded / systems engineer": (
        "iot solutions architect",
        "iot automation engineer",
        "iot hardware developer",
    ),
    "ai/ml engineer": (
        "applied scientist",
        "machine learning scientist",
    ),
    "ai platform engineer": (
        "ml platform engineer",
        "ai infrastructure engineer",
    ),
}

ENTERPRISE_ROLE_KEYWORDS = (
    "sap sd",
    "sales and distribution",
    "s/4hana",
    "sap s/4hana",
    "sap sd consultant",
)
