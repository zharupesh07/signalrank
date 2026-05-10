from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import asc, desc, func, select

from api.database import AsyncSessionLocal, engine
from api.models import JobRaw, JobResult, Profile, Run, User
from tools import rag_match_sample_eval as matcher

DEFAULT_EMAIL = "examplecandidate@gmail.com"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "hybrid_match_eval"
DEFAULT_LABELS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "evals" / "example_job_fit_gold.jsonl"
)
LABEL_ORDER = {
    "reject": 0,
    "hard_violation": 0,
    "maybe_adjacent": 1,
    "strong_pursue": 2,
}


@dataclass(frozen=True)
class EvalJob:
    label: str
    label_reason: str
    current_score: float
    current_fit_band: str | None
    title: str
    company: str
    location: str | None
    job_url: str
    description: str


@dataclass(frozen=True)
class SimpleScore:
    score: float
    band: str
    gate_failed: bool
    gate_reasons: list[str]


@dataclass(frozen=True)
class LaneDecision:
    gate_reasons: list[str]
    score_cap: float | None


@dataclass(frozen=True)
class MatchPolicy:
    active_lanes: tuple[str, ...]
    direct_title_terms: tuple[str, ...]
    direct_context_terms: tuple[str, ...]
    adjacent_title_terms: tuple[str, ...]
    negative_title_terms: tuple[str, ...]
    hard_negative_title_terms: tuple[str, ...]
    data_only_terms: tuple[str, ...]
    data_platform_title_terms: tuple[str, ...]


NETWORK_AUTOMATION_EVIDENCE = (
    "ansible",
    "automate",
    "automated",
    "automation",
    "bash",
    "configuration management",
    "github",
    "gnmi",
    "infrastructure as code",
    "network automation",
    "orchestration",
    "powershell",
    "puppet",
    "python",
    "resolve.io",
    "script",
    "scripting",
    "servicenow",
    "yang",
)

NETWORK_DOMAIN_EVIDENCE = (
    "acl",
    "bgp",
    "cloud network",
    "network",
    "network operations",
    "routing",
    "sd-wan",
    "servicenow",
    "switching",
    "vlan",
    "vpn",
)

EMERGING_TECH_SOLUTION_EVIDENCE = (
    "3d printing",
    "alexa skills kit",
    "arduino",
    "augmented reality",
    "chatbot",
    "computer vision",
    "conversational ai",
    "creative technologist",
    "dialogflow",
    "edge computing",
    "embedded",
    "firefly",
    "firmware",
    "industrial automation",
    "iot",
    "lex",
    "microsoft bot framework",
    "microcontroller",
    "mqtt",
    "proof of concept",
    "raspberry pi",
    "robotics",
    "sensors",
    "smart building",
    "smart buildings",
    "voice ai",
    "virtual reality",
)

GENERIC_EMERGING_TITLES = (
    "ai developer",
    "ai engineer",
    "data scientist",
    "machine learning engineer",
    "ml engineer",
    "r&d engineer",
    "research engineer",
)

SPECIFIC_EMERGING_TITLES = (
    "chatbot developer",
    "computer vision",
    "conversational ai",
    "creative technologist",
    "edge computing engineer",
    "embedded systems engineer",
    "iot engineer",
    "iot solutions architect",
    "llm application engineer",
    "nlp engineer",
    "voice ai engineer",
)

EMERGING_STRONG_TITLE_TERMS = (
    *SPECIFIC_EMERGING_TITLES,
    "lead ai",
    "lead ai engr",
    "lead ai engineer",
)

SAP_EVIDENCE_TERMS = (
    "abap",
    "erp",
    "sap",
    "s/4hana",
    "s4hana",
)

SAP_ADJACENT_TITLE_TERMS = ("functional consultant",)


LANE_POLICIES: dict[str, dict[str, tuple[str, ...]]] = {
    "ai_platform": {
        "detect": (
            "ai platform",
            "ml platform",
            "mlops",
            "llmops",
            "llm",
            "rag",
            "agentic",
            "genai",
            "machine learning",
            "deep learning",
            "model serving",
        ),
        "direct_titles": (
            "ai platform engineer",
            "ml platform engineer",
            "mlops engineer",
            "llmops engineer",
            "machine learning engineer",
            "ml engineer",
            "ai engineer",
            "gen ai engineer",
            "applied ai engineer",
            "llm engineer",
            "rag engineer",
        ),
        "direct_context": (
            "artificial intelligence",
            "ai/ml",
            "ai ml",
            "machine learning",
            "ml engineer",
            "ai engineer",
            "llm",
            "rag",
            "agentic",
            "genai",
            "gen ai",
            "mlops",
            "llmops",
            "ai platform",
            "ml platform",
            "production ai",
        ),
        "adjacent_titles": (
            "backend",
            "software engineer",
            "software development engineer",
            "platform engineer",
            "core platform",
            "sre",
            "site reliability",
            "devops",
            "cloud engineer",
            "data platform",
        ),
        "negative_titles": (
            "android",
            "ios developer",
            "mobile developer",
            "security engineer",
            "microsoft sentinel",
            "zero trust",
            "network engineer",
            "power systems",
            "ux design",
            "design engineer",
            "mern",
            "full stack",
            "frontend",
            "front-end",
            "web developer",
            "application engineer",
            "application developer",
            "operations automation",
            "operational excellence",
            "ai detections",
            "ai analyst",
        ),
    },
    "sap_erp": {
        "detect": (
            "sap",
            "s/4hana",
            "s4hana",
            "order to cash",
            "otc",
            "sap sd",
            "sap mm",
            "sap gts",
            "abap",
            "erp",
        ),
        "direct_titles": (
            "sap sd consultant",
            "sap functional consultant",
            "sap s/4hana consultant",
            "sap s4hana consultant",
            "sap otc consultant",
            "sap gts consultant",
            "sap mm consultant",
            "sap abap consultant",
        ),
        "direct_context": (
            "sap",
            "s/4hana",
            "s4hana",
            "sales and distribution",
            "order to cash",
            "otc",
            "sap sd",
            "sap mm",
            "sap gts",
            "abap",
            "erp",
        ),
        "adjacent_titles": (
            "erp consultant",
            "business analyst",
            "functional consultant",
        ),
        "negative_titles": (
            "machine learning engineer",
            "ai engineer",
            "mlops",
            "devops",
            "sre",
            "data engineer",
            "software engineer",
            "frontend",
            "full stack",
        ),
    },
    "network_automation": {
        "detect": (
            "network automation",
            "network engineer",
            "firewall",
            "routing",
            "switching",
            "ssl",
            "servicenow",
            "resolve.io",
            "network infrastructure",
        ),
        "direct_titles": (
            "network automation engineer",
            "infrastructure automation engineer",
            "cloud network engineer",
            "network engineer automation",
            "firewall automation engineer",
            "network engineer",
        ),
        "direct_context": (
            "network automation",
            "network engineer",
            "cloud network",
            "network operations",
            "firewall",
            "load balancer",
            "ssl",
            "routing",
            "switching",
            "infrastructure automation",
        ),
        "adjacent_titles": (
            "devops engineer",
            "cloud engineer",
            "infrastructure engineer",
            "site reliability engineer",
        ),
        "negative_titles": (
            "machine learning",
            "ai engineer",
            "backend",
            "back end",
            "data engineer",
            "data scientist",
            "frontend",
            "full stack",
            "full-stack",
            "mern",
            "firmware",
            "hardware",
            "sales engineer",
        ),
    },
    "backend_product": {
        "detect": (
            "backend",
            "api",
            "microservices",
            "distributed systems",
            "java",
            "python",
            "node.js",
            "full stack",
            "frontend",
            "react",
        ),
        "direct_titles": (
            "backend engineer",
            "software engineer",
            "software development engineer",
            "full stack developer",
            "full-stack developer",
            "full stack engineer",
            "platform engineer",
        ),
        "direct_context": (
            "backend",
            "api",
            "microservices",
            "distributed systems",
            "full stack",
            "full-stack",
            "frontend",
            "react",
            "node.js",
        ),
        "adjacent_titles": ("devops engineer", "sre", "cloud engineer"),
        "negative_titles": (
            "sales engineer",
            "support engineer",
            "data scientist",
            "business analyst",
        ),
    },
    "qa_automation": {
        "detect": ("qa", "sdet", "test automation", "selenium", "quality assurance"),
        "direct_titles": (
            "qa engineer",
            "sdet",
            "test engineer",
            "software engineer in test",
            "automation engineer",
        ),
        "direct_context": (
            "qa",
            "quality assurance",
            "test automation",
            "selenium",
            "automation testing",
        ),
        "adjacent_titles": ("software engineer", "devops engineer"),
        "negative_titles": ("sales engineer", "support engineer"),
    },
    "innovation": {
        "detect": (
            "innovation",
            "emerging technologies",
            "prototype",
            "prototyping",
            "r&d",
            "creative technologist",
            "rapid poc",
        ),
        "direct_titles": (
            "innovation engineer",
            "emerging technologies engineer",
            "prototype engineer",
            "r&d engineer",
            "creative technologist",
            "technical innovation engineer",
        ),
        "direct_context": (
            "innovation",
            "emerging",
            "prototype",
            "prototyping",
            "r&d",
            "research",
            "creative technologist",
            "mvp",
            "poc",
        ),
        "adjacent_titles": (
            "iot engineer",
            "conversational ai engineer",
            "research engineer",
        ),
        "negative_titles": ("buyer", "procurement", "sales", "support"),
    },
    "iot": {
        "detect": (
            "iot",
            "embedded",
            "sensors",
            "edge computing",
            "firmware",
            "microcontroller",
            "arduino",
            "raspberry pi",
            "mqtt",
        ),
        "direct_titles": (
            "iot engineer",
            "embedded systems engineer",
            "edge computing engineer",
            "iot solutions architect",
            "smart devices engineer",
        ),
        "direct_context": (
            "iot",
            "embedded",
            "edge computing",
            "sensors",
            "firmware",
            "microcontroller",
            "arduino",
            "raspberry pi",
            "mqtt",
        ),
        "adjacent_titles": ("innovation engineer", "r&d engineer"),
        "negative_titles": ("support", "qa", "sales"),
    },
    "conversational_ai": {
        "detect": (
            "chatbot",
            "voice agent",
            "conversational ai",
            "nlp",
            "dialogflow",
            "lex",
            "alexa skills kit",
            "microsoft bot framework",
        ),
        "direct_titles": (
            "conversational ai engineer",
            "chatbot developer",
            "nlp engineer",
            "llm application engineer",
            "voice ai engineer",
        ),
        "direct_context": (
            "conversational ai",
            "chatbot",
            "nlp",
            "voice",
            "dialogflow",
            "lex",
            "alexa skills kit",
            "microsoft bot framework",
        ),
        "adjacent_titles": ("ai engineer",),
        "negative_titles": ("support", "qa", "sales"),
    },
}

DEFAULT_HARD_NEGATIVE_TITLE_TERMS = (
    "manager",
    "mgr",
    "director",
    "principal",
    "test engineer",
    "engineer in test",
    "sdet",
    "quality assurance",
    "qa engineer",
    "associate",
    "junior",
    "intern",
    "cto",
    "vp",
    "head",
)

DEFAULT_DATA_ONLY_TERMS = (
    "etl",
    "databricks",
    "data centre",
    "data center",
    "data warehouse",
    "seller growth",
)

DEFAULT_DATA_PLATFORM_TITLE_TERMS = (
    "ai platform",
    "ml platform",
    "mlops",
    "llmops",
    "llm serving",
    "gpu infrastructure",
    "production ai",
    "agentic",
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _title_has_any(title: str, phrases: set[str]) -> bool:
    normalized = _normalize(title)
    return any(phrase in normalized for phrase in phrases)


def _has_phrase(text: str, phrase: str) -> bool:
    normalized = _normalize(text)
    if phrase.isalnum():
        return bool(
            re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", normalized)
        )
    return phrase in normalized


def _has_any_phrase(text: str, terms: tuple[str, ...]) -> bool:
    return any(_has_phrase(text, term) for term in terms)


def _has_network_automation_evidence(text: str) -> bool:
    return _has_any_phrase(text, NETWORK_DOMAIN_EVIDENCE) and _has_any_phrase(
        text, NETWORK_AUTOMATION_EVIDENCE
    )


def _has_sap_evidence(text: str) -> bool:
    return _has_any_phrase(text, SAP_EVIDENCE_TERMS)


def _dedupe_terms(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        term = _normalize(value)
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return tuple(result)


def _profile_values(candidate_profile: dict[str, Any] | None, *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = (candidate_profile or {}).get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
    return values


def _detected_policy_lanes(profile_text: str) -> tuple[str, ...]:
    detected: list[str] = []
    for lane, definition in LANE_POLICIES.items():
        hits = sum(
            1
            for term in definition.get("detect", ())
            if _has_phrase(profile_text, term)
        )
        if hits >= 2 or (
            hits >= 1
            and any(
                _has_phrase(profile_text, title)
                for title in definition.get("direct_titles", ())
            )
        ):
            detected.append(lane)
    return tuple(detected)


def _term_allowed_by_direct(term: str, direct_title_terms: tuple[str, ...]) -> bool:
    return any(
        term == direct or term in direct or direct in term
        for direct in direct_title_terms
    )


def _build_match_policy(candidate_profile: dict[str, Any] | None) -> MatchPolicy:
    direct_roles = _profile_values(candidate_profile, "target_roles_primary")
    adjacent_roles = _profile_values(candidate_profile, "target_roles_adjacent")
    negative_roles = _profile_values(candidate_profile, "negative_roles")
    positive_profile_text = _normalize(
        " ".join(
            [
                *direct_roles,
                *adjacent_roles,
                *_profile_values(
                    candidate_profile,
                    "domains",
                    "career_archetypes",
                    "must_have_skills",
                    "good_to_have_skills",
                ),
            ]
        )
    )
    active_lanes = _detected_policy_lanes(positive_profile_text)
    direct_role_text = _normalize(" ".join(direct_roles + adjacent_roles))
    specialized_lanes = {
        lane
        for lane in active_lanes
        if lane not in {"backend_product", "qa_automation"}
    }
    if specialized_lanes:
        if not any(
            _has_phrase(direct_role_text, term)
            for term in ("backend", "software engineer", "developer", "full stack")
        ):
            active_lanes = tuple(
                lane for lane in active_lanes if lane != "backend_product"
            )
        if not any(
            _has_phrase(direct_role_text, term)
            for term in ("qa", "sdet", "test engineer", "test automation")
        ):
            active_lanes = tuple(
                lane for lane in active_lanes if lane != "qa_automation"
            )
    if not active_lanes and not candidate_profile:
        active_lanes = ("ai_platform",)
    if not active_lanes and any(
        _has_phrase(positive_profile_text, term)
        for term in ("software engineer", "developer", "backend", "api")
    ):
        active_lanes = ("backend_product",)

    direct_title_terms = list(direct_roles)
    direct_context_terms: list[str] = []
    adjacent_title_terms = list(adjacent_roles)
    negative_title_terms = list(negative_roles)
    for lane in active_lanes:
        definition = LANE_POLICIES[lane]
        direct_title_terms.extend(definition.get("direct_titles", ()))
        direct_context_terms.extend(definition.get("direct_context", ()))
        adjacent_title_terms.extend(definition.get("adjacent_titles", ()))
        negative_title_terms.extend(definition.get("negative_titles", ()))

    direct_title_terms_tuple = _dedupe_terms(direct_title_terms)
    hard_negative_terms = tuple(
        term
        for term in DEFAULT_HARD_NEGATIVE_TITLE_TERMS
        if not _term_allowed_by_direct(term, direct_title_terms_tuple)
    )
    negative_title_terms_tuple = tuple(
        term
        for term in _dedupe_terms(negative_title_terms)
        if not _term_allowed_by_direct(term, direct_title_terms_tuple)
    )

    return MatchPolicy(
        active_lanes=active_lanes,
        direct_title_terms=direct_title_terms_tuple,
        direct_context_terms=_dedupe_terms(direct_context_terms + direct_roles),
        adjacent_title_terms=_dedupe_terms(adjacent_title_terms),
        negative_title_terms=negative_title_terms_tuple,
        hard_negative_title_terms=hard_negative_terms,
        data_only_terms=DEFAULT_DATA_ONLY_TERMS,
        data_platform_title_terms=DEFAULT_DATA_PLATFORM_TITLE_TERMS,
    )


def silver_label_job(job: JobRaw, current_score: float) -> tuple[str, str]:
    title = str(job.title or "")
    description = str(job.description or "")
    combined = _normalize(f"{title}\n{description[:1000]}")

    hard_negative_titles = {
        "project manager",
        "program manager",
        "technical program manager",
        "director",
        "qa engineer",
        "quality assurance",
        "test engineer",
        "support engineer",
        "technical support",
        "sales engineer",
        "business intelligence",
        "bie manager",
        "front office",
        "associate - ap",
        "internship",
        "entry level",
        "junior",
        "pcb",
        "hardware design",
    }
    if _title_has_any(title, hard_negative_titles):
        return "hard_violation", "title_lane_hard_negative"

    strong_titles = {
        "rag",
        "agentic",
        "ai engineer",
        "ai application",
        "ai developer",
        "applied ai",
        "ai/ml",
        "ai ml",
        "machine learning engineer",
        "ml engineer",
        "llm engineer",
        "mlops",
        "llm",
        "ai platform",
        "ml platform",
    }
    platform_titles = {
        "platform engineer",
        "backend",
        "python developer",
        "software engineer",
        "devops",
        "site reliability",
        "sre",
        "cloud engineer",
        "data engineer",
    }
    strong_context = {
        "rag",
        "agentic",
        "llm",
        "mlops",
        "ai platform",
        "machine learning",
        "genai",
    }
    if _title_has_any(title, strong_titles):
        return "strong_pursue", "title_primary_ai_platform_or_ml"
    if _title_has_any(title, platform_titles) and any(
        phrase in combined for phrase in strong_context
    ):
        return "strong_pursue", "platform_title_with_ai_context"
    if _title_has_any(title, platform_titles):
        return "maybe_adjacent", "engineering_platform_adjacent"
    if current_score >= 70 and any(phrase in combined for phrase in strong_context):
        return "maybe_adjacent", "high_current_score_with_ai_context"
    return "reject", "no_primary_role_or_context_match"


def _load_label_overrides(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    labels: dict[str, tuple[str, str]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        job_url = str(item.get("job_url") or "").strip()
        label = str(item.get("label") or "").strip()
        reason = str(item.get("label_reason") or item.get("reason") or "manual")
        if job_url and label:
            labels[job_url] = (label, reason)
    return labels


async def _fetch_eval_jobs(
    email: str,
    *,
    sample_size: int,
    min_description_chars: int,
    labels_path: Path | None,
) -> tuple[Profile, list[EvalJob]]:
    label_overrides = _load_label_overrides(labels_path) if labels_path else {}
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        profile = (
            await db.execute(select(Profile).where(Profile.user_id == user.id))
        ).scalar_one()
        base_stmt = (
            select(JobResult, JobRaw)
            .join(JobRaw, JobRaw.id == JobResult.job_id)
            .join(Run, Run.id == JobResult.run_id)
            .where(
                JobResult.user_id == user.id,
                Run.status == "success",
                JobResult.final_score.is_not(None),
                func.length(JobRaw.description) >= min_description_chars,
            )
        )
        top_rows = (
            await db.execute(
                base_stmt.order_by(desc(JobResult.final_score), JobRaw.title).limit(
                    max(10, sample_size // 2)
                )
            )
        ).all()
        bottom_rows = (
            await db.execute(
                base_stmt.order_by(asc(JobResult.final_score), JobRaw.title).limit(
                    max(10, sample_size // 4)
                )
            )
        ).all()
        mid_rows = (
            await db.execute(
                base_stmt.where(JobResult.final_score.between(35, 75))
                .order_by(desc(JobResult.final_score), JobRaw.title)
                .limit(max(10, sample_size))
            )
        ).all()

    rows_by_url: dict[str, tuple[JobResult, JobRaw]] = {}
    for row in [*top_rows, *mid_rows, *bottom_rows]:
        rows_by_url.setdefault(str(row[1].job_url or ""), row)

    eval_jobs: list[EvalJob] = []
    label_counts: dict[str, int] = {}
    per_label_cap = max(8, sample_size // 3)
    for jr, job in rows_by_url.values():
        current_score = round(float(jr.final_score or 0.0), 2)
        job_url = str(job.job_url or "")
        label, reason = label_overrides.get(job_url) or silver_label_job(
            job, current_score
        )
        if (
            label_counts.get(label, 0) >= per_label_cap
            and len(eval_jobs) >= sample_size
        ):
            continue
        label_counts[label] = label_counts.get(label, 0) + 1
        eval_jobs.append(
            EvalJob(
                label=label,
                label_reason=reason,
                current_score=current_score,
                current_fit_band=jr.fit_band,
                title=str(job.title or ""),
                company=str(job.company or ""),
                location=str(job.location or "") or None,
                job_url=job_url,
                description=str(job.description or ""),
            )
        )
        if len(eval_jobs) >= sample_size and all(
            label_counts.get(label, 0) >= 3
            for label in ("strong_pursue", "maybe_adjacent", "hard_violation", "reject")
        ):
            break
    return profile, eval_jobs[:sample_size]


def _current_band(score: float) -> str:
    if score >= 75:
        return "strong_fit"
    if score >= 55:
        return "adjacent_fit"
    if score >= 35:
        return "weak_fit"
    return "reject"


def _is_positive(label: str) -> bool:
    return label in {"strong_pursue", "maybe_adjacent"}


def _score_metrics(
    rows: list[dict[str, Any]],
    *,
    score_key: str,
    band_key: str,
    top_k: int,
) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda item: item[score_key], reverse=True)
    top = ranked[:top_k]
    positives = sum(1 for item in top if _is_positive(item["label"]))
    hard_violations = sum(1 for item in top if item["label"] == "hard_violation")
    rejects_promoted = sum(
        1
        for item in top
        if item["label"] in {"reject", "hard_violation"}
        and item[band_key] in {"strong_fit", "adjacent_fit"}
    )
    pair_total = 0
    pair_correct = 0
    for left in rows:
        for right in rows:
            if LABEL_ORDER[left["label"]] <= LABEL_ORDER[right["label"]]:
                continue
            pair_total += 1
            if left[score_key] > right[score_key]:
                pair_correct += 1
    promoted_bad = [
        {
            "label": item["label"],
            "score": item[score_key],
            "band": item[band_key],
            "title": item["title"],
            "company": item["company"],
        }
        for item in ranked
        if item["label"] in {"reject", "hard_violation"}
        and item[band_key] in {"strong_fit", "adjacent_fit"}
    ]
    return {
        "precision_at_k": round(positives / max(1, len(top)), 3),
        "hard_violation_at_k": round(hard_violations / max(1, len(top)), 3),
        "rejects_promoted_at_k": round(rejects_promoted / max(1, len(top)), 3),
        "pairwise_preference_accuracy": (
            round(pair_correct / pair_total, 3) if pair_total else None
        ),
        "ndcg_at_10": _ndcg_at_k(ranked, 10),
        "ndcg_at_25": _ndcg_at_k(ranked, 25),
        "ndcg_at_50": _ndcg_at_k(ranked, 50),
        "top_k": top_k,
        "promoted_bad": promoted_bad[:20],
        "top_jobs": [
            {
                "label": item["label"],
                "score": item[score_key],
                "band": item[band_key],
                "title": item["title"],
                "company": item["company"],
            }
            for item in top
        ],
    }


def _relevance(label: str) -> int:
    if label == "strong_pursue":
        return 3
    if label == "maybe_adjacent":
        return 1
    return 0


def _dcg(items: list[dict[str, Any]]) -> float:
    return sum(
        (2 ** _relevance(item["label"]) - 1) / math.log2(index + 2)
        for index, item in enumerate(items)
    )


def _ndcg_at_k(ranked: list[dict[str, Any]], k: int) -> float:
    if not ranked:
        return 0.0
    top = ranked[: min(k, len(ranked))]
    ideal = sorted(ranked, key=lambda item: _relevance(item["label"]), reverse=True)[
        : len(top)
    ]
    ideal_dcg = _dcg(ideal)
    if not ideal_dcg:
        return 0.0
    return round(_dcg(top) / ideal_dcg, 3)


def _band_from_score(score: float) -> str:
    if score >= 75:
        return "strong_fit"
    if score >= 55:
        return "adjacent_fit"
    if score >= 35:
        return "weak_fit"
    return "reject"


def _lane_decision(title: str, context: str, policy: MatchPolicy) -> LaneDecision:
    direct_title_hit = any(
        _has_phrase(title, term) for term in policy.direct_title_terms
    )
    direct_context_hits = tuple(
        term for term in policy.direct_context_terms if _has_phrase(context, term)
    )
    weak_innovation_context = {
        "emerging",
        "innovation",
        "mvp",
        "poc",
        "prototype",
        "prototyping",
        "research",
    }
    has_direct_context = bool(direct_context_hits) and not all(
        term in weak_innovation_context for term in direct_context_hits
    )
    direct_context_in_title = any(
        _has_phrase(title, term) for term in direct_context_hits
    )
    generic_software_title = any(
        _has_phrase(title, term)
        for term in (
            "software engineer",
            "backend",
            "back end",
            "cloud/api",
            "cloud api",
        )
    )
    has_direct_target = (
        direct_title_hit
        or direct_context_in_title
        or (has_direct_context and not generic_software_title)
    )
    has_data_platform_context = any(
        _has_phrase(title, term) for term in policy.data_platform_title_terms
    )
    has_adjacent = any(_has_phrase(title, term) for term in policy.adjacent_title_terms)
    gate_reasons: list[str] = []
    sap_active = "sap_erp" in policy.active_lanes
    network_automation_active = "network_automation" in policy.active_lanes
    emerging_tech_active = any(
        lane in policy.active_lanes
        for lane in ("innovation", "iot", "conversational_ai")
    )

    if any(_has_phrase(title, term) for term in policy.hard_negative_title_terms):
        gate_reasons.append("hard_negative_title_lane")
    if any(_has_phrase(title, term) for term in policy.negative_title_terms):
        gate_reasons.append("non_target_engineering_lane")
    if (
        any(_has_phrase(title, term) for term in policy.data_only_terms)
        and not has_data_platform_context
    ):
        gate_reasons.append("data_pipeline_without_ai_platform_context")
    if re.search(r"^data engineer\s+i\b", title):
        gate_reasons.append("junior_or_entry_data_lane")

    if gate_reasons:
        return LaneDecision(gate_reasons=gate_reasons, score_cap=34.0)
    if sap_active:
        has_sap_evidence = _has_sap_evidence(context)
        if _has_any_phrase(title, SAP_ADJACENT_TITLE_TERMS):
            return LaneDecision(gate_reasons=[], score_cap=54.9)
        if direct_context_in_title and not (direct_title_hit or has_sap_evidence):
            return LaneDecision(
                gate_reasons=["sap_context_title_without_sap_evidence"],
                score_cap=49.9,
            )
        if has_adjacent and not (direct_title_hit or has_sap_evidence):
            return LaneDecision(
                gate_reasons=["sap_adjacent_title_without_sap_evidence"],
                score_cap=49.9,
            )
    if network_automation_active:
        has_network_automation_evidence = _has_network_automation_evidence(context)
        if has_adjacent and not (direct_title_hit or direct_context_in_title):
            return LaneDecision(
                gate_reasons=["network_adjacent_title_without_direct_network_role"],
                score_cap=54.9,
            )
        if (
            direct_title_hit or direct_context_in_title
        ) and not has_network_automation_evidence:
            return LaneDecision(gate_reasons=[], score_cap=74.9)
    if (
        emerging_tech_active
        and _has_any_phrase(title, GENERIC_EMERGING_TITLES)
        and not _has_any_phrase(title, SPECIFIC_EMERGING_TITLES)
        and not _has_any_phrase(context, EMERGING_TECH_SOLUTION_EVIDENCE)
    ):
        return LaneDecision(
            gate_reasons=["generic_emerging_title_without_solution_evidence"],
            score_cap=54.9,
        )
    if (
        emerging_tech_active
        and direct_context_in_title
        and not _has_any_phrase(title, EMERGING_STRONG_TITLE_TERMS)
        and not _has_any_phrase(context, EMERGING_TECH_SOLUTION_EVIDENCE)
    ):
        return LaneDecision(gate_reasons=[], score_cap=74.9)
    if has_direct_target:
        return LaneDecision(gate_reasons=[], score_cap=None)
    if has_adjacent:
        return LaneDecision(gate_reasons=[], score_cap=74.9)
    return LaneDecision(gate_reasons=["generic_or_unknown_lane"], score_cap=49.9)


def _target_score_floor(title: str, context: str, policy: MatchPolicy) -> float | None:
    direct_title_hit = any(
        _has_phrase(title, term) for term in policy.direct_title_terms
    )
    direct_context_in_title = any(
        _has_phrase(title, term) for term in policy.direct_context_terms
    )
    if (
        "sap_erp" in policy.active_lanes
        and direct_title_hit
        and _has_sap_evidence(context)
    ):
        return 76.0
    if "sap_erp" in policy.active_lanes and _has_any_phrase(
        title, SAP_ADJACENT_TITLE_TERMS
    ):
        return 50.0
    if (
        "network_automation" in policy.active_lanes
        and (direct_title_hit or direct_context_in_title)
        and _has_network_automation_evidence(context)
    ):
        return 76.0
    if any(
        lane in policy.active_lanes
        for lane in ("innovation", "iot", "conversational_ai")
    ) and (
        _has_any_phrase(title, EMERGING_STRONG_TITLE_TERMS)
        or (
            _has_any_phrase(context, EMERGING_TECH_SOLUTION_EVIDENCE)
            and _has_any_phrase(title, EMERGING_STRONG_TITLE_TERMS)
        )
    ):
        return 76.0
    if direct_title_hit or direct_context_in_title:
        return 62.0
    return None


def _simplified_score(
    factors: matcher.MatchFactors,
    *,
    job: EvalJob,
    current_score: float,
    candidate_profile: dict[str, Any] | None = None,
    match_policy: MatchPolicy | None = None,
) -> SimpleScore:
    gate_reasons = list(factors.hard_constraints)
    title = _normalize(job.title)
    context = _normalize(f"{job.title}\n{job.description[:1200]}")
    policy = match_policy or _build_match_policy(candidate_profile)
    lane = _lane_decision(title, context, policy)
    gate_reasons.extend(lane.gate_reasons)
    gate_failed = bool(gate_reasons)
    score = (
        0.35 * factors.role_score
        + 0.35 * factors.evidence_score
        + 0.15 * factors.skill_score
        + 0.10 * factors.location_score
        + 0.05 * min(100.0, max(0.0, current_score))
    )
    score = round(score, 1)
    if not lane.gate_reasons:
        target_floor = _target_score_floor(title, context, policy)
        if target_floor is not None:
            score = max(score, target_floor)
    if lane.score_cap is not None:
        score = round(min(score, lane.score_cap), 1)
    return SimpleScore(
        score=score,
        band=_band_from_score(score),
        gate_failed=gate_failed,
        gate_reasons=gate_reasons,
    )


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hybrid Match Eval",
        "",
        f"- email: `{report['email']}`",
        f"- generated_at: `{report['generated_at']}`",
        f"- label_source: `{report['label_source']}`",
        f"- sample_size: `{len(report['rows'])}`",
        "",
        "## Metrics",
        "",
        "| Approach | Precision@K | Hard violation@K | Rejects promoted@K | Pairwise | NDCG@10 | NDCG@25 | NDCG@50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("current", "hybrid", "simplified"):
        metrics = report["metrics"][name]
        lines.append(
            "| {name} | {precision:.3f} | {hard:.3f} | {promoted:.3f} | {pairwise} | {ndcg10:.3f} | {ndcg25:.3f} | {ndcg50:.3f} |".format(
                name=name,
                precision=metrics["precision_at_k"],
                hard=metrics["hard_violation_at_k"],
                promoted=metrics["rejects_promoted_at_k"],
                pairwise=metrics["pairwise_preference_accuracy"],
                ndcg10=metrics["ndcg_at_10"],
                ndcg25=metrics["ndcg_at_25"],
                ndcg50=metrics["ndcg_at_50"],
            )
        )
    lines.extend(["", "## Promoted Bad Diagnostics", ""])
    for name in ("current", "hybrid", "simplified"):
        promoted_bad = report["metrics"][name]["promoted_bad"]
        lines.append(f"### {name}")
        if not promoted_bad:
            lines.append("")
            lines.append("None.")
            lines.append("")
            continue
        lines.extend(
            [
                "",
                "| Label | Score | Band | Title |",
                "|---|---:|---|---|",
            ]
        )
        for item in promoted_bad[:10]:
            lines.append(
                "| {label} | {score:.1f} | {band} | {title} / {company} |".format(
                    label=item["label"],
                    score=item["score"],
                    band=item["band"],
                    title=item["title"],
                    company=item["company"],
                )
            )
        lines.append("")
    lines.extend(
        [
            "## Rows",
            "",
            "| Label | Current | Hybrid | Simple | Gate | Role | Evidence | Skill | Title |",
            "|---|---:|---:|---:|---|---:|---:|---:|---|",
        ]
    )
    for item in sorted(
        report["rows"], key=lambda row: row["simplified_score"], reverse=True
    ):
        factors = item["factors"]
        lines.append(
            "| {label} | {current:.2f} | {hybrid:.1f} | {simple:.1f} | {gate} | {role:.1f} | {evidence:.1f} | {skill:.1f} | {title} / {company} |".format(
                label=item["label"],
                current=item["current_score"],
                hybrid=item["hybrid_score"],
                simple=item["simplified_score"],
                gate="yes" if item["simple_gate_failed"] else "no",
                role=factors["role_score"],
                evidence=factors["evidence_score"],
                skill=factors["skill_score"],
                title=item["title"],
                company=item["company"],
            )
        )
    return "\n".join(lines)


async def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    labels_path = (
        Path(args.labels_path).expanduser().resolve() if args.labels_path else None
    )
    profile, eval_jobs = await _fetch_eval_jobs(
        args.email,
        sample_size=args.sample_size,
        min_description_chars=args.min_description_chars,
        labels_path=labels_path,
    )
    resume_text = profile.resume_text or ""
    candidate_profile = profile.candidate_profile or {}
    match_policy = _build_match_policy(candidate_profile)
    chunks = matcher._resume_chunks(resume_text, candidate_profile)
    rows: list[dict[str, Any]] = []
    for eval_job in eval_jobs:
        sample = matcher.SampleJob(
            expected=eval_job.label,
            current_score=eval_job.current_score,
            current_fit_band=eval_job.current_fit_band,
            title=eval_job.title,
            company=eval_job.company,
            location=eval_job.location,
            job_url=eval_job.job_url,
            description=eval_job.description,
        )
        requirements = matcher.extract_requirements(sample)
        requirement_results = matcher.evaluate_requirements(requirements, chunks)
        factors = matcher.synthesize_hybrid_score(
            requirements,
            requirement_results,
            chunks,
            resume_text,
            candidate_profile,
            sample,
        )
        simplified = _simplified_score(
            factors,
            job=eval_job,
            current_score=eval_job.current_score,
            match_policy=match_policy,
        )
        rows.append(
            {
                **asdict(eval_job),
                "description": "",
                "current_band": _current_band(eval_job.current_score),
                "hybrid_score": factors.final_score,
                "hybrid_band": factors.band,
                "simplified_score": simplified.score,
                "simplified_band": simplified.band,
                "simple_gate_failed": simplified.gate_failed,
                "simple_gate_reasons": simplified.gate_reasons,
                "factors": {
                    key: value
                    for key, value in asdict(factors).items()
                    if key not in {"band", "hard_constraints"}
                },
                "hard_constraints": factors.hard_constraints,
                "requirements": [
                    {
                        **asdict(result),
                        "evidence": [asdict(item) for item in result.evidence],
                    }
                    for result in requirement_results
                ],
            }
        )

    top_k = min(args.top_k, len(rows))
    return {
        "email": args.email,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_source": (
            "labels_path"
            if labels_path and labels_path.exists()
            else "silver_title_and_context_rules"
        ),
        "selection": {
            "sample_size": args.sample_size,
            "min_description_chars": args.min_description_chars,
            "top_k": top_k,
            "labels_path": str(labels_path) if labels_path else None,
            "labels_loaded": bool(labels_path and labels_path.exists()),
        },
        "match_policy": asdict(match_policy),
        "metrics": {
            "current": _score_metrics(
                rows,
                score_key="current_score",
                band_key="current_band",
                top_k=top_k,
            ),
            "hybrid": _score_metrics(
                rows,
                score_key="hybrid_score",
                band_key="hybrid_band",
                top_k=top_k,
            ),
            "simplified": _score_metrics(
                rows,
                score_key="simplified_score",
                band_key="simplified_band",
                top_k=top_k,
            ),
        },
        "rows": rows,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare current SignalRank score with hybrid evidence matcher on a silver-labeled DB eval set"
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--min-description-chars", type=int, default=800)
    parser.add_argument("--labels-path", default=str(DEFAULT_LABELS_PATH))
    parser.add_argument("--output-dir")
    return parser


async def _async_main() -> None:
    args = _build_parser().parse_args()
    report = await run_eval(args)
    out_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else DEFAULT_OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "summary.md").write_text(_render_markdown(report) + "\n")
    print(
        json.dumps(
            {
                "output_dir": str(out_dir),
                "sample_size": len(report["rows"]),
                "current": report["metrics"]["current"],
                "hybrid": report["metrics"]["hybrid"],
                "simplified": report["metrics"]["simplified"],
            },
            indent=2,
        )
    )
    await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
