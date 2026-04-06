from __future__ import annotations

import re

ROLE_CLUSTERS: dict[str, set[str]] = {
    "sap_erp": {
        "SAP SD Consultant",
        "SAP OTC Functional Consultant",
        "SAP MM Consultant",
        "SAP Functional Consultant",
        "SAP Technical Consultant",
        "SAP ABAP Developer",
        "SAP Basis Consultant",
        "SAP S/4HANA Consultant",
        "SAP FI/CO Consultant",
        "SAP HCM Consultant",
        "SAP CRM Consultant",
        "ERP Consultant",
        "Oracle ERP Consultant",
    },
    "ai_ml": {
        "AI/ML Engineer",
        "Data Scientist",
        "MLOps/Platform Engineer",
        "GenAI / LLM Engineer",
        "AI Platform Engineer",
        "Research Scientist",
        "Data Engineer",
        "Analytics Engineer",
    },
    "innovation": {
        "Innovation Engineer",
        "Emerging Technologies Engineer",
        "R&D Engineer",
        "Prototype Engineer",
        "Innovation Technologist",
        "Creative Technologist",
        "Research and Development Engineer",
    },
    "network_auto": {
        "Network Automation Engineer",
        "Infrastructure Automation Engineer",
        "Cloud Network Engineer",
        "Network Reliability Engineer",
        "Network DevOps Engineer",
        "Network Operations Automation Engineer",
        "Systems and Network Automation Engineer",
        "Firewall Engineer",
        "Cloud Networking Engineer",
    },
    "backend": {
        "Backend Engineer",
        "Full-Stack Engineer",
        "API / Integrations Engineer",
        "Mobile Engineer",
    },
    "infra": {
        "DevOps/SRE",
        "Security Engineer",
        "Platform Engineer",
        "Cloud Infrastructure Engineer",
        "Embedded / Systems Engineer",
    },
    "product_eng": {
        "Frontend Engineer",
        "Product Engineer",
        "QA / Test Engineer",
    },
}

_ROLE_TO_CLUSTER: dict[str, str] = {}
for _cluster, _roles in ROLE_CLUSTERS.items():
    for _role in _roles:
        _ROLE_TO_CLUSTER[_role.lower()] = _cluster

_CLUSTER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sap_erp": (
        "sap sd",
        "sap mm",
        "sap fico",
        "sap fi/co",
        "sap basis",
        "sap ps",
        "sap pp",
        "sap wm",
        "sap ewm",
        "sap tm",
        "sap ariba",
        "sap mdg",
        "sap bw",
        "sap bpc",
        "sap crm",
        "sap hcm",
        "sap functional",
        "sap technical consultant",
        "s/4hana",
        "sales and distribution",
        "sales & distribution",
        "abap",
        "otc",
        "order to cash",
        "order-to-cash",
        "functional consultant",
        "sales distribution",
        "material management",
        "procure to pay",
        "ptp",
        "mm consultant",
        "fico consultant",
    ),
    "ai_ml": (
        "machine learning",
        "ml engineer",
        "ai engineer",
        "llm",
        "genai",
        "data scientist",
        "applied scientist",
        "mlops",
    ),
    "innovation": (
        "innovation engineer",
        "innovation technologist",
        "emerging technologies",
        "emerging tech",
        "prototype engineer",
        "creative technologist",
        "r&d engineer",
        "research and development engineer",
        "rapid poc",
        "mvp",
        "prototype",
        "iot",
        "robotics",
    ),
    "network_auto": (
        "network automation",
        "network automation engineer",
        "infrastructure automation",
        "cloud network",
        "cloud networking",
        "network engineer",
        "network operations",
        "network reliability",
        "firewall",
        "routing",
        "switching",
        "load balancer",
        "zero trust network",
        "network platform",
        "network devops",
        "ssl",
    ),
    "backend": (
        "backend engineer",
        "full-stack engineer",
        "full stack engineer",
        "software engineer",
        "api engineer",
        "integrations engineer",
        "mobile engineer",
    ),
    "infra": (
        "devops",
        "sre",
        "site reliability",
        "platform engineer",
        "cloud infrastructure",
        "security engineer",
        "embedded",
        "systems engineer",
    ),
    "product_eng": (
        "qa",
        "test engineer",
        "quality assurance",
        "qa automation",
        "sdet",
        "frontend engineer",
        "product engineer",
    ),
}


def _compile_keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword)
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.I)


_CLUSTER_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    cluster: tuple(_compile_keyword_pattern(keyword) for keyword in keywords)
    for cluster, keywords in _CLUSTER_KEYWORDS.items()
}


def roles_to_clusters(target_roles: list[str]) -> set[str]:
    clusters: set[str] = set()
    for role in target_roles:
        normalized_role = role.strip().lower()
        cluster = _ROLE_TO_CLUSTER.get(normalized_role)
        if cluster:
            clusters.add(cluster)
            continue
        for inferred_cluster, patterns in _CLUSTER_PATTERNS.items():
            if any(pattern.search(normalized_role) for pattern in patterns):
                clusters.add(inferred_cluster)
                break
    return clusters or {"general"}


def infer_clusters_from_job_text(title: str | None, description: str | None) -> set[str]:
    text = f"{title or ''} {description or ''}".lower()
    clusters = {
        cluster
        for cluster, patterns in _CLUSTER_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    }
    return clusters or {"general"}
