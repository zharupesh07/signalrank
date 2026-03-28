from __future__ import annotations

ROLE_CLUSTERS: dict[str, set[str]] = {
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


def roles_to_clusters(target_roles: list[str]) -> set[str]:
    clusters: set[str] = set()
    for role in target_roles:
        c = _ROLE_TO_CLUSTER.get(role.strip().lower())
        if c:
            clusters.add(c)
    return clusters or {"general"}
