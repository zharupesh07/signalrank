import re
from typing import Dict, List

# Capability-level normalization map
SKILL_GROUPS: Dict[str, List[str]] = {
    "cloud platform": [
        "aws",
        "gcp",
        "google cloud",
        "azure",
        "amazon web services",
        "microsoft azure",
    ],
    "container orchestration": [
        "kubernetes",
        "k8s",
        "eks",
        "aks",
        "gke",
    ],
    "object storage": [
        "s3",
        "gcs",
        "blob storage",
    ],
    "data warehouse": [
        "bigquery",
        "redshift",
        "snowflake",
    ],
    "ml platform": [
        "vertex ai",
        "sagemaker",
        "azure ml",
    ],
    "llm framework": [
        "langchain",
        "langgraph",
        "llamaindex",
    ],
}


def normalize_text(text: str) -> str:
    lowered = text.lower()

    for canonical, variants in SKILL_GROUPS.items():
        for v in variants:
            pattern = r"\b" + re.escape(v) + r"\b"
            lowered = re.sub(pattern, canonical, lowered)

    return lowered
