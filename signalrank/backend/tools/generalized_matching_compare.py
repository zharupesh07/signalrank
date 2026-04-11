from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.config import settings
from api.database import AsyncSessionLocal
from api.models import JobRaw, Profile, User
from experiment_cleanup import delete_user_ids
from api.routes.onboarding import _extract_text_from_pdf
from batch.context import build_context, load_base_config
from batch.query_builder import SearchQuery
from batch.query_plan_cache import get_cached_queries
from ranking.v4.db_scorer import score_jobs_for_user
from batch.scraper import ScraperConfig, raw_job_to_dict, scrape
from domain.additive_scoring import location_score_5tier, recency_score_0_100
from domain.candidate_profile import build_candidate_profile
from domain.career_intent import build_career_intent_profile
from domain.embed_math import cosine_similarity
from domain.embeddings import (
    EmbeddingEngine,
    build_job_embedding_text,
    build_resume_embedding_text,
    unload_embedding_engine,
)
from domain.job_profile import build_job_profile
from domain.role_clusters import infer_clusters_from_job_text
from domain.title_relevance import title_relevance_score_0_100
from domain.skills import extract_skills_from_texts
from llm.resume_parser import ResumeParseResult


logger = logging.getLogger(__name__)

RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "generalized_matching_compare"


@dataclass(frozen=True)
class ResumeTarget:
    key: str
    pdf_name: str


TARGETS = {
    "abhijeet": ResumeTarget("abhijeet", "Abhijeet_CV.pdf"),
    "aditya": ResumeTarget("aditya", "aditya.pdf"),
    "ayush": ResumeTarget("ayush", "ayush_resume_new.pdf"),
    "vivek": ResumeTarget("vivek", "Vivek-Gupta-Emerging-Technologies.pdf"),
    "example": ResumeTarget("example", "Example_Candidate_Resume_V2_2.pdf"),
}

SENIORITY_ORDER = {
    "junior": 0,
    "mid": 1,
    "senior": 2,
    "staff": 3,
    "principal": 4,
}

LANE_PRESETS: dict[str, dict[str, Any]] = {
    "ai_platform": {
        "title_aliases": [
            "AI Platform Engineer",
            "MLOps Engineer",
            "ML Platform Engineer",
            "Machine Learning Engineer",
            "LLMOps Engineer",
        ],
        "skill_keywords": ["Kubernetes", "Terraform", "CI/CD", "AWS", "GCP", "LangGraph", "LangChain"],
        "positive_terms": ["ai", "ml", "llm", "mlops", "platform", "genai", "agentic", "rag"],
        "negative_terms": ["qa", "sdet", "helpdesk", "support", "sales", "frontend", "java fullstack"],
        "negative_roles": ["QA", "SDET", "Support", "Helpdesk", "Sales Engineer", "Frontend Developer"],
    },
    "sap_erp": {
        "title_aliases": [
            "SAP SD Consultant",
            "SAP Functional Consultant",
            "SAP S/4HANA Consultant",
            "SAP OTC Functional Consultant",
            "SAP GTS Consultant",
        ],
        "skill_keywords": [
            "SAP SD",
            "SAP MM",
            "SAP GTS",
            "SAP ABAP",
            "SAP S/4HANA",
            "Order to Cash",
            "Sales and Distribution",
            "Material Management",
        ],
        "positive_terms": [
            "sap",
            "s/4hana",
            "sales and distribution",
            "order to cash",
            "otc",
            "functional consultant",
            "gts",
            "abap",
            "material management",
        ],
        "negative_terms": [
            "devops",
            "sre",
            "data engineer",
            "data scientist",
            "machine learning",
            "ai",
            "support",
            "qa",
            "frontend",
            "software engineer",
        ],
        "negative_roles": [
            "DevOps Engineer",
            "SRE",
            "Data Engineer",
            "Data Scientist",
            "QA Engineer",
            "Software Engineer",
            "Support Engineer",
        ],
    },
    "innovation": {
        "title_aliases": [
            "Innovation Engineer",
            "Emerging Technologies Engineer",
            "Prototype Engineer",
            "R&D Engineer",
            "Creative Technologist",
            "Technical Innovation Engineer",
        ],
        "skill_keywords": ["IoT", "Robotics", "Conversational AI", "Blockchain", "AR/VR", "Rapid Prototyping"],
        "positive_terms": [
            "innovation", "emerging", "prototype", "prototyp", "r&d", "research", "creative technologist",
            "iot", "robotics", "ar/vr", "conversational ai", "mvp", "poc", "pot",
        ],
        "negative_terms": [
            "procurement", "buyer", "sales", "program manager", "data engineer", "outsystems",
            "platform lead", "gen ai engineer", "ml engineer", "asic", "semiconductor",
            "hardware", "embedded", "firmware", "analog", "digital design", "verification",
            "vlsi", "electrical", "electronics", "manufacturing", "test engineer",
        ],
        "negative_roles": [
            "Buyer",
            "Sales Engineer",
            "Program Manager",
            "Data Engineer",
            "Outsystems",
            "Procurement",
            "Hardware Engineer",
            "ASIC Engineer",
            "Embedded Engineer",
            "Verification Engineer",
        ],
    },
    "network_automation": {
        "title_aliases": [
            "Network Automation Engineer",
            "Infrastructure Automation Engineer",
            "Cloud Network Engineer",
            "Network Engineer Automation",
            "Firewall Automation Engineer",
        ],
        "skill_keywords": ["Python", "Groovy", "Shell Scripting", "Firewall", "SSL", "ServiceNow", "Resolve.io"],
        "positive_terms": [
            "network automation", "network engineer", "cloud network", "network operations", "firewall",
            "load balancer", "ssl", "routing", "switching", "infrastructure automation",
        ],
        "negative_terms": ["sales", "hardware", "ivr", "frontend", "cyber security", "firmware", "technical writer"],
        "negative_roles": ["Sales Engineer", "Hardware Engineer", "IVR Engineer", "Cyber Security Engineer", "Firmware Engineer", "Technical Writer"],
    },
}


@dataclass
class PipelineArtifacts:
    profile: dict[str, Any]
    queries: list[dict[str, str]]
    top_jobs: list[dict[str, Any]]
    summary: dict[str, Any]
    cleanup_user_ids: list[str]


def _load_spec(target: ResumeTarget) -> dict:
    return json.loads((RESUMES_DIR / target.pdf_name).with_suffix(".json").read_text())


def _parse_from_spec(spec: dict) -> ResumeParseResult:
    skills: list[str] = []
    for group in spec.get("skills") or []:
        skills.extend([str(item).strip() for item in group.get("items", []) if str(item).strip()])
    recent_titles = [exp.get("title", "") for exp in (spec.get("experiences") or [])[:3] if exp.get("title")]
    education = [edu.get("degree", "") for edu in (spec.get("education") or []) if edu.get("degree")]
    location = str(spec.get("location") or "").strip()
    location_city = location.split(",")[0].strip() if location else ""
    headline = str(spec.get("position") or spec.get("label") or "").strip()
    suggested_roles = [headline] if headline else recent_titles[:1]
    return ResumeParseResult(
        skills=skills,
        years_of_experience=None,
        recent_titles=recent_titles,
        industries=[],
        education=education,
        suggested_roles=suggested_roles,
        suggested_locations=[location_city] if location_city else [],
        suggested_exclusions=[],
        suggested_search_queries=[],
        career_archetypes=[],
        target_roles=[],
        domains=[],
        negative_targets=[],
        false_friend_terms=[],
        query_plan={},
        ambiguities=[],
        follow_up_questions=[],
    )


async def _persist_jobs(db, jobs, cfg):
    if not jobs:
        return []
    values = [raw_job_to_dict(job) for job in jobs]
    for value in values:
        value["role_clusters"] = sorted(
            infer_clusters_from_job_text(value.get("title"), value.get("description")) - {"general"}
        )
        value["job_profile"] = build_job_profile(
            title=value.get("title"),
            company=value.get("company"),
            description=value.get("description"),
            location=value.get("location"),
            site=value.get("site"),
            date_posted=value.get("date_posted"),
            role_clusters=value["role_clusters"],
            cfg=cfg,
        )
    stmt = pg_insert(JobRaw).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["job_url"],
        set_={
            "title": stmt.excluded.title,
            "company": stmt.excluded.company,
            "description": stmt.excluded.description,
            "location": stmt.excluded.location,
            "site": stmt.excluded.site,
            "date_posted": stmt.excluded.date_posted,
            "role_clusters": stmt.excluded.role_clusters,
            "job_profile": stmt.excluded.job_profile,
        },
    )
    await db.execute(stmt)
    await db.commit()

    urls = [job.job_url for job in jobs]
    result = await db.execute(select(JobRaw.id).where(JobRaw.job_url.in_(urls)))
    return [str(row[0]) for row in result.all()]


def _dedupe_strs(values: list[str] | tuple[str, ...] | None, *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        items.append(text)
        if limit and len(items) >= limit:
            break
    return items


def _clean_role_title(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    for sep in (" | ", " / ", " - ", " – ", " — ", "(", ","):
        if sep in text:
            candidate = text.split(sep, 1)[0].strip()
            if len(candidate) >= 6:
                text = candidate
                break
    text = re.sub(r"\b(India|Pune|Bangalore|Hyderabad|Mumbai|Remote)\b", "", text, flags=re.I).strip(" -/,")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_location_text(location: str | None, work_mode: str) -> str:
    loc = re.sub(r"\s+", " ", str(location or "").strip())
    if not loc:
        return "Remote" if work_mode == "remote" else ""
    lowered = loc.lower()
    if work_mode == "remote" and "remote" not in lowered:
        return "Remote"
    if work_mode == "hybrid" and "hybrid" not in lowered:
        return f"{loc} (Hybrid)"
    return loc


def _work_mode_from_text(location: str | None, title: str, description: str) -> str:
    text = f"{location or ''} {title or ''} {description or ''}".lower()
    if any(term in text for term in ("remote", "work from home", "wfh", "fully distributed")):
        return "remote"
    if any(term in text for term in ("hybrid", "2 days", "3 days", "days in office")):
        return "hybrid"
    if location:
        return "onsite"
    return "unknown"


def _required_constraints_from_description(description: str) -> list[str]:
    text = (description or "").lower()
    constraints: list[str] = []
    patterns = [
        (r"\bvisa sponsorship\b", "visa sponsorship"),
        (r"\bsecurity clearance\b", "security clearance"),
        (r"\b(us|u\.s\.) only\b", "US-only"),
        (r"\bindia only\b", "India-only"),
        (r"\b(on[- ]site|onsite|in office)\b", "onsite"),
        (r"\bhybrid\b", "hybrid"),
        (r"\btravel\b", "travel requirement"),
        (r"\bcontract\b", "contract"),
        (r"\bpart[- ]time\b", "part-time"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            constraints.append(label)

    yoe = re.search(r"\b(\d+)\s*[-to]+\s*(\d+)\s*years\b", text)
    if yoe:
        constraints.append(f"{yoe.group(0)} experience")
    else:
        plus = re.search(r"\b(\d+)\+?\s*years\b", text)
        if plus:
            constraints.append(f"{plus.group(0)} experience")
    return _dedupe_strs(constraints)


def _top_skills_from_spec(spec: dict, *, limit: int = 8) -> list[str]:
    preferred_categories = [
        "Programming Languages",
        "Frameworks & Libraries",
        "Cloud & Infrastructure",
        "Data & ML",
        "Databases",
        "Tools",
    ]
    picked: list[str] = []
    for category in preferred_categories:
        for group in spec.get("skills") or []:
            if str(group.get("category") or "").strip() != category:
                continue
            for item in group.get("items") or []:
                text = str(item or "").strip()
                if text:
                    picked.append(text)
    if not picked:
        for group in spec.get("skills") or []:
            for item in group.get("items") or []:
                text = str(item or "").strip()
                if text:
                    picked.append(text)
    return _dedupe_strs(picked, limit=limit)


def _infer_years_of_experience(spec: dict, resume_text: str) -> int | None:
    date_ranges = " ".join(
        str(exp.get("dates") or "")
        for exp in (spec.get("experiences") or [])
        if isinstance(exp, dict)
    )
    text = f"{resume_text}\n{date_ranges}"
    years = [int(match) for match in re.findall(r"(\d{1,2})\+?\s*(?:years?|yrs?)\b", text, flags=re.I)]
    if years:
        return max(years)
    return max(1, min(len(spec.get("experiences") or []), 15)) if spec.get("experiences") else None


def _infer_seniority_band(years: int | None, role_text: str) -> str:
    text = (role_text or "").lower()
    if years is not None:
        if years <= 2:
            return "junior"
        if years <= 5:
            return "mid"
        if years <= 9:
            return "senior"
        if years <= 13:
            return "staff"
        return "principal"
    if any(term in text for term in ("principal", "architect", "distinguished", "head of")):
        return "principal"
    if any(term in text for term in ("staff", "lead", "manager", "director")):
        return "staff"
    if "senior" in text:
        return "senior"
    return "mid"


def _extract_domains(spec: dict, resume_text: str) -> list[str]:
    text = " ".join(
        [
            resume_text,
            str(spec.get("position") or ""),
            " ".join(str(exp.get("title") or "") for exp in (spec.get("experiences") or [])),
            " ".join(str(group.get("category") or "") for group in (spec.get("skills") or [])),
        ]
    ).lower()
    domains: list[str] = []
    if any(term in text for term in ("sap", "s/4hana", "erp", "order to cash", "otc")):
        domains.append("ERP")
    if any(term in text for term in ("machine learning", "genai", "llm", "rag", "agent", "mlops")):
        domains.append("AI / ML")
    if any(term in text for term in ("platform", "devops", "infrastructure", "terraform", "kubernetes", "cloud")):
        domains.append("Platform / Infrastructure")
    if any(term in text for term in ("backend", "api", "microservice", "distributed system")):
        domains.append("Backend Engineering")
    if any(term in text for term in ("network", "firewall", "load balancer", "routing", "switching")):
        domains.append("Networking")
    if any(term in text for term in ("innovation", "prototype", "emerging technologies", "r&d", "iot", "robotics")):
        domains.append("Innovation / Emerging Tech")
    if not domains:
        domains.append("Software")
    return _dedupe_strs(domains, limit=5)


def _detect_dominant_lane(spec: dict, resume_text: str) -> str | None:
    text = " ".join(
        [
            resume_text,
            str(spec.get("position") or ""),
            str(spec.get("summary") or ""),
            " ".join(str(exp.get("title") or "") for exp in (spec.get("experiences") or [])),
            " ".join(
                str(item)
                for group in (spec.get("skills") or [])
                for item in (group.get("items") or [])
            ),
        ]
    ).lower()
    scores: dict[str, int] = {}
    for lane, preset in LANE_PRESETS.items():
        score = 0
        score += sum(2 for term in preset["positive_terms"] if term in text)
        score += sum(1 for term in preset["skill_keywords"] if term.lower() in text)
        score += sum(1 for title in preset["title_aliases"] if title.lower() in text)
        scores[lane] = score
    lane, score = max(scores.items(), key=lambda item: item[1])
    return lane if score >= 3 else None


def _build_generalized_profile(spec: dict, parsed: ResumeParseResult, resume_text: str) -> dict[str, Any]:
    headline = _clean_role_title(str(spec.get("position") or spec.get("label") or "").strip())
    recent_titles = [
        _clean_role_title(str(exp.get("title") or "").strip())
        for exp in (spec.get("experiences") or [])
        if str(exp.get("title") or "").strip()
    ]
    primary_roles = _dedupe_strs(([headline] if headline else []) + recent_titles[:2], limit=4)
    adjacent_roles = _dedupe_strs(recent_titles[1:5], limit=4)
    years = _infer_years_of_experience(spec, resume_text)
    seniority = _infer_seniority_band(years, " ".join(primary_roles))
    skills = _top_skills_from_spec(spec, limit=10)
    domains = _extract_domains(spec, resume_text)
    dominant_lane = _detect_dominant_lane(spec, resume_text)
    lane_preset = LANE_PRESETS.get(dominant_lane or "", {})
    location = str(spec.get("location") or "").strip()
    location_city = location.split(",")[0].strip() if location else ""
    work_modes = ["remote"] if "remote" in location.lower() else ["any"]
    preferred_locations = [location_city] if location_city else []

    if lane_preset:
        primary_roles = _dedupe_strs(primary_roles + list(lane_preset.get("title_aliases") or []), limit=5)
        adjacent_roles = _dedupe_strs(adjacent_roles + list(lane_preset.get("title_aliases") or [])[1:], limit=5)
        skills = _dedupe_strs(list(lane_preset.get("skill_keywords") or []) + skills, limit=10)
        if dominant_lane == "sap_erp":
            major_sap_cities = {
                "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "chennai",
                "delhi", "ncr", "noida", "gurgaon", "gurugram", "kolkata",
            }
            if not location_city or location_city.lower() not in major_sap_cities:
                preferred_locations = []

    negative_roles = ["Intern", "Junior", "Support", "Helpdesk"]
    title_text = " ".join(primary_roles).lower()
    if not any(term in title_text for term in ("qa", "test", "sdet")):
        negative_roles.extend(["QA", "SDET", "Test Engineer"])
    if not any(term in title_text for term in ("data scientist", "applied scientist")):
        negative_roles.append("Data Scientist")
    if any(term in title_text for term in ("ai", "ml", "llm", "platform", "sap", "network", "innovation")):
        negative_roles.extend(["Software Engineer", "Java Developer", "Full Stack Developer"])
    negative_roles.extend(list(lane_preset.get("negative_roles") or []))

    evidence = []
    if headline:
        evidence.append({"source": "headline", "text": headline})
    for exp in (spec.get("experiences") or [])[:2]:
        bullets = exp.get("bullets") or []
        if bullets:
            evidence.append({"source": f"experience:{exp.get('title') or 'role'}", "text": str(bullets[0])[:240]})

    return {
        "target_roles_primary": primary_roles,
        "target_roles_adjacent": adjacent_roles,
        "negative_roles": _dedupe_strs(negative_roles, limit=8),
        "dominant_lane": dominant_lane,
        "domains": domains,
        "industries": [],
        "seniority_band": seniority,
        "years_of_experience": years,
        "preferred_locations": preferred_locations,
        "preferred_work_modes": work_modes,
        "must_have_skills": skills[:8],
        "good_to_have_skills": skills[8:10],
        "tools_and_platforms": skills,
        "evidence_snippets": evidence,
        "ambiguities": [],
        "follow_up_questions": [],
        "confidence_by_field": {
            "roles": 0.7 if primary_roles else 0.4,
            "skills": 0.75 if skills else 0.4,
            "locations": 0.8 if location_city else 0.3,
            "overall": 0.78 if primary_roles and skills and dominant_lane else 0.48,
        },
    }


def _build_generalized_query_plan(profile: dict[str, Any]) -> dict[str, Any]:
    primary = _dedupe_strs(profile.get("target_roles_primary"), limit=4)
    adjacent = _dedupe_strs(profile.get("target_roles_adjacent"), limit=4)
    skills = _dedupe_strs(profile.get("must_have_skills"), limit=6)
    domains = _dedupe_strs(profile.get("domains"), limit=4)
    negative = _dedupe_strs(profile.get("negative_roles"), limit=8)
    lane = str(profile.get("dominant_lane") or "")
    lane_preset = LANE_PRESETS.get(lane, {})

    title_queries = _dedupe_strs(list(lane_preset.get("title_aliases") or []) + primary, limit=6)
    adjacent_title_queries = _dedupe_strs(adjacent + list(lane_preset.get("title_aliases") or [])[1:], limit=5)

    combos: list[str] = []
    combo_skills = _dedupe_strs(list(lane_preset.get("skill_keywords") or []) + skills, limit=4)
    for role in title_queries[:3]:
        for skill in combo_skills[:2]:
            combos.append(f"{role} {skill}")
    title_queries = _dedupe_strs(title_queries + combos, limit=8)
    title_queries = [_clean_role_title(item) for item in title_queries]
    adjacent_title_queries = [_clean_role_title(item) for item in adjacent_title_queries]
    title_queries = _dedupe_strs(title_queries, limit=8)
    adjacent_title_queries = _dedupe_strs(adjacent_title_queries, limit=4)

    return {
        "title_queries": title_queries,
        "adjacent_title_queries": adjacent_title_queries,
        "skill_queries": combo_skills,
        "domain_queries": domains,
        "industry_queries": [],
        "negative_keywords": _dedupe_strs(negative + list(lane_preset.get("negative_roles") or []), limit=12),
        "confidence": profile.get("confidence_by_field", {}).get("overall", 0.5),
        "evidence": profile.get("evidence_snippets", [])[:4],
    }


def _search_queries_from_plan(
    query_plan: dict[str, Any],
    *,
    preferred_locations: list[str],
    max_terms: int,
    default_country: str,
) -> list[SearchQuery]:
    terms = _dedupe_strs(
        list(query_plan.get("title_queries") or [])
        + list(query_plan.get("adjacent_title_queries") or [])
        + [
            f"{title} {skill}"
            for title in list(query_plan.get("title_queries") or [])[:2]
            for skill in list(query_plan.get("skill_queries") or [])[:2]
        ],
        limit=max_terms,
    )
    negative_terms = [str(term).strip().lower() for term in (query_plan.get("negative_keywords") or []) if str(term).strip()]
    locations = preferred_locations or [default_country]
    country_like = {default_country.lower(), "remote", "india", "worldwide", "any"}

    queries: list[SearchQuery] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        lower = term.lower()
        if any(neg in lower for neg in negative_terms):
            continue
        for loc in locations:
            city = "" if str(loc).lower() in country_like else str(loc)
            key = (lower, city.lower())
            if key in seen:
                continue
            seen.add(key)
            queries.append(SearchQuery(term=term, location=city, country=default_country))
            if len(queries) >= 50:
                return queries
    return queries


def _profile_to_stub(profile: dict[str, Any], query_plan: dict[str, Any]) -> SimpleNamespace:
    roles = list(profile.get("target_roles_primary") or [])
    custom_search = _dedupe_strs(
        list(query_plan.get("title_queries") or [])
        + list(query_plan.get("adjacent_title_queries") or [])
        + list(query_plan.get("skill_queries") or [])
        + list(query_plan.get("domain_queries") or []),
        limit=12,
    )
    return SimpleNamespace(
        target_roles=roles,
        preferred_locations=list(profile.get("preferred_locations") or []),
        custom_search_queries=custom_search,
        config_overrides={
            "career_intent": {"query_plan": query_plan},
            "profile_intent": {"roles": roles},
            "scraping": {"locations": list(profile.get("preferred_locations") or [])},
        },
    )


def _serialize_queries(queries: list[SearchQuery]) -> list[dict[str, str]]:
    return [asdict(query) for query in queries]


async def _run_baseline(
    *,
    target: ResumeTarget,
    spec: dict,
    parsed: ResumeParseResult,
    resume_text: str,
    days: int,
    limit: int,
    quick_search: bool,
) -> PipelineArtifacts:
    run_id = uuid.uuid4().hex[:10]
    career_intent = build_career_intent_profile(parsed)
    cleanup_user_id: str | None = None
    success = False

    try:
        async with AsyncSessionLocal() as db:
            user = User(
                email=f"generalized-baseline-{target.key}-{run_id}@test.com",
                password_hash="x",
                provider="credentials",
            )
            db.add(user)
            await db.flush()
            cleanup_user_id = user.id

            profile = Profile(
                user_id=user.id,
                resume_text=resume_text,
                target_roles=[r["title"] for r in career_intent.get("target_roles", []) if r.get("title")],
                preferred_locations=[loc for loc in career_intent.get("suggested_locations", []) if loc],
                onboarding_complete=True,
                scraper_max_terms=8,
                scraper_hours_old=days * 24,
                config_overrides={"career_intent": career_intent},
            )
            db.add(profile)
            await db.commit()

            ctx = build_context(user_id=user.id, resume_text=resume_text, config_overrides=profile.config_overrides)
            cfg = ctx.config
            if quick_search:
                cfg.setdefault("ranking", {}).setdefault("agentic_matching", {})["enabled"] = False
            candidate_profile = build_candidate_profile(
                parsed=parsed,
                profile=profile,
                resume_text=resume_text,
                cfg=cfg,
            )

            scraper_cfg = ScraperConfig.from_env(title_blocklist=(profile.config_overrides or {}).get("title_blocklist", []))
            scraper_cfg.hours_old = days * 24
            scraper_cfg.sources = ["indeed"] if quick_search else ["indeed", "linkedin", "rapidapi", "free_apis", "google_jobs"]

            queries = await get_cached_queries(
                db,
                profile=profile,
                profile_fingerprint=str(candidate_profile.get("profile_fingerprint") or candidate_profile.get("profile_cache_key") or ""),
                search_window_days=days,
                source_filter=",".join(sorted(scraper_cfg.sources or [])),
                max_terms=profile.scraper_max_terms or settings.scraper_max_terms,
            )

            jobs = await scrape(queries, scraper_cfg, db=db, return_mode="jobs")
            job_urls = [job.job_url for job in jobs]
            job_ids = await _persist_jobs(db, jobs, cfg)
            del jobs
            gc.collect()

            ranked = await score_jobs_for_user(
                db=db,
                user_id=user.id,
                resume_text=resume_text,
                job_urls=job_urls,
                config_overrides=profile.config_overrides,
                distilled_text=profile.distilled_text,
            )
            ranked = ranked.sort_values("final_score", ascending=False).head(limit).reset_index(drop=True)

            top_ids = [str(row["id"]) for _, row in ranked.iterrows()]
            job_rows = await db.execute(select(JobRaw).where(JobRaw.id.in_(top_ids)))
            job_map = {str(row.id): row for row in job_rows.scalars().all()}

            top_jobs: list[dict[str, Any]] = []
            for idx, row in ranked.iterrows():
                job = job_map.get(str(row["id"]))
                job_profile = job.job_profile if job else {}
                top_jobs.append(
                    {
                        "rank": idx + 1,
                        "job_id": str(row["id"]),
                        "job_url": str(row.get("job_url") or job.job_url if job else ""),
                        "title": str(row.get("title") or ""),
                        "company": str(row.get("company") or ""),
                        "location": str(row.get("location") or job.location if job else ""),
                        "site": str(row.get("site") or job.site if job else ""),
                        "final_score": round(float(row.get("final_score") or 0.0), 4),
                        "semantic_score": round(float(row.get("semantic_score") or 0.0), 4),
                        "title_relevance_score": round(float(row.get("title_relevance_score") or 0.0), 2),
                        "job_profile": job_profile,
                    }
                )

            success = True
            return PipelineArtifacts(
                profile=candidate_profile,
                queries=_serialize_queries(queries),
                top_jobs=top_jobs,
                summary={
                    "queries": len(queries),
                    "scraped_jobs": len(job_ids),
                    "top_jobs": len(top_jobs),
                },
                cleanup_user_ids=[cleanup_user_id] if cleanup_user_id else [],
            )
    finally:
        if cleanup_user_id and not success:
            await delete_user_ids(AsyncSessionLocal, [cleanup_user_id])



def _job_rows_by_id(rows: list[JobRaw]) -> dict[str, JobRaw]:
    return {str(row.id): row for row in rows}


def _normalize_title_key(title: str, company: str) -> str:
    return f"{title.strip().lower()}|{company.strip().lower()}"


def _job_profile_text(job_profile: dict[str, Any]) -> str:
    return " ".join(
        [
            str(job_profile.get("role_family") or ""),
            str(job_profile.get("domain") or ""),
            " ".join(job_profile.get("role_titles_normalized") or []),
            " ".join(job_profile.get("required_skills") or []),
            " ".join(job_profile.get("preferred_skills") or []),
            " ".join(job_profile.get("must_have_constraints") or []),
            " ".join(job_profile.get("red_flags") or []),
        ]
    ).lower()


def _extract_preferred_section(description: str) -> str:
    text = description or ""
    lower = text.lower()
    markers = ("preferred", "nice to have", "bonus", "plus", "good to have", "desired qualifications")
    positions = [lower.find(marker) for marker in markers if marker in lower]
    if not positions:
        return ""
    idx = min(positions)
    return text[idx: idx + 500]


def _infer_open_role_family(title: str, description: str, job_profile: dict[str, Any]) -> str:
    text = _job_profile_text(job_profile) + f" {title or ''} {description or ''}".lower()
    if any(term in text for term in ("ai", "ml", "llm", "genai", "mlops", "llmops", "rag", "agentic")):
        return "AI / ML Platform"
    if any(term in text for term in ("innovation", "prototype", "prototyp", "r&d", "research", "creative technologist", "emerging")):
        return "Innovation / Emerging Tech"
    if any(term in text for term in ("network automation", "firewall", "cloud network", "network operations", "load balancer", "routing", "switching")):
        return "Network / Infrastructure Automation"
    if any(term in text for term in ("sap", "s/4hana", "erp", "order to cash", "otc")):
        return "SAP / ERP"
    if any(term in text for term in ("platform", "devops", "sre", "cloud", "kubernetes", "terraform", "infrastructure")):
        return "Platform / Infrastructure"
    if any(term in text for term in ("backend", "full stack", "software engineer", "api", "microservice")):
        return "Software Engineering"
    return str(job_profile.get("role_family") or job_profile.get("domain") or "General").strip() or "General"


def _infer_open_domains(title: str, description: str, job_profile: dict[str, Any]) -> list[str]:
    text = f"{title or ''} {description or ''} {_job_profile_text(job_profile)}".lower()
    domains: list[str] = []
    if any(term in text for term in ("ai", "ml", "llm", "genai", "mlops", "rag")):
        domains.append("AI / ML")
    if any(term in text for term in ("platform", "devops", "sre", "cloud", "kubernetes", "terraform", "infrastructure")):
        domains.append("Platform / Infrastructure")
    if any(term in text for term in ("network", "firewall", "routing", "switching", "load balancer", "ssl", "network automation")):
        domains.append("Networking")
    if any(term in text for term in ("innovation", "prototype", "r&d", "research", "emerging", "iot", "robotics")):
        domains.append("Innovation / Emerging Tech")
    if any(term in text for term in ("sap", "erp", "order to cash", "otc", "s/4hana")):
        domains.append("SAP / ERP")
    if any(term in text for term in ("backend", "api", "microservice", "distributed system", "full stack")):
        domains.append("Backend Engineering")
    if not domains:
        domains.append(str(job_profile.get("domain") or "General").strip() or "General")
    return _dedupe_strs(domains, limit=4)


def _open_title_variants(title: str, job_profile: dict[str, Any]) -> list[str]:
    titles = [
        _clean_role_title(title),
        _clean_role_title(str(job_profile.get("role_family") or "")),
    ]
    titles.extend(str(item) for item in job_profile.get("role_titles_normalized") or [])
    return _dedupe_strs(titles, limit=6)


def _build_generalized_job_understanding(
    job: JobRaw,
    job_profile: dict[str, Any],
    cfg: dict,
) -> dict[str, Any]:
    title = str(job.title or "").strip()
    description = str(job.description or "").strip()
    location = str(job.location or "").strip()
    work_mode = str(job_profile.get("work_mode") or "").strip() or _work_mode_from_text(location or None, title, description)
    location_normalized = str(job_profile.get("location_normalized") or "").strip() or _normalize_location_text(location or None, work_mode)
    required_skills = _dedupe_strs(
        list(job_profile.get("required_skills") or [])
        + list(extract_skills_from_texts([f"{title} {description}"], cfg)[0]),
        limit=18,
    )
    preferred_section = _extract_preferred_section(description)
    preferred_skills = _dedupe_strs(
        list(job_profile.get("preferred_skills") or [])
        + list(extract_skills_from_texts([preferred_section], cfg)[0]),
        limit=12,
    )
    role_family_open = _infer_open_role_family(title, description, job_profile)
    role_titles_normalized = _open_title_variants(title, job_profile)
    primary_domain = _infer_open_domains(title, description, job_profile)[0]
    secondary_domains = _dedupe_strs(_infer_open_domains(title, description, job_profile)[1:] + list(job_profile.get("secondary_domains") or []), limit=4)
    seniority_band = str(job_profile.get("seniority_band") or "").strip() or _infer_seniority_band(None, f"{title} {description}")
    must_have_constraints = _dedupe_strs(list(job_profile.get("must_have_constraints") or []) + _required_constraints_from_description(description), limit=10)
    description_quality = float(job_profile.get("description_quality") or 0.0)
    job_quality = max(0.0, min(100.0, description_quality * 100.0))

    evidence_snippets = list(job_profile.get("evidence_snippets") or [])
    if title:
        evidence_snippets.append({"source": "title", "text": title[:240]})
    if location_normalized:
        evidence_snippets.append({"source": "location", "text": location_normalized[:240]})
    if description:
        evidence_snippets.append({"source": "description", "text": description[:240]})
    if preferred_section:
        evidence_snippets.append({"source": "preferred_section", "text": preferred_section[:240]})
    deduped_evidence: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for item in evidence_snippets:
        if not isinstance(item, dict):
            item = {"source": "unknown", "text": str(item)}
        key = json.dumps(item, sort_keys=True)
        if key in seen_evidence:
            continue
        seen_evidence.add(key)
        deduped_evidence.append(item)
        if len(deduped_evidence) >= 8:
            break

    red_flags = _dedupe_strs(list(job_profile.get("red_flags") or []), limit=8)
    if job_quality < 55.0:
        red_flags = _dedupe_strs(red_flags + ["low_description_quality"], limit=8)

    return {
        "role_family_open": role_family_open,
        "role_titles_normalized": role_titles_normalized,
        "normalized_titles": role_titles_normalized,
        "primary_domain": primary_domain,
        "secondary_domains": secondary_domains,
        "domains": _dedupe_strs([primary_domain, *secondary_domains], limit=5),
        "industries": [],
        "seniority_band": seniority_band,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "must_have_constraints": must_have_constraints,
        "work_mode": work_mode,
        "location_normalized": location_normalized,
        "employment_type": "contract" if any(term in " ".join(must_have_constraints).lower() for term in ("contract", "part-time")) else "full-time",
        "job_quality": round(job_quality, 2),
        "description_quality": round(description_quality, 4),
        "red_flags": red_flags,
        "evidence_snippets": deduped_evidence,
    }


def _lane_gate_result(profile: dict[str, Any], understanding: dict[str, Any], title: str, description: str) -> dict[str, Any]:
    lane = str(profile.get("dominant_lane") or "").strip()
    text = " ".join(
        [
            title or "",
            description or "",
            str(understanding.get("primary_domain") or ""),
            " ".join(understanding.get("required_skills") or []),
            " ".join(understanding.get("preferred_skills") or []),
            " ".join(understanding.get("must_have_constraints") or []),
        ]
    ).lower()
    if not lane:
        return {
            "lane": "",
            "passed": True,
            "multiplier": 1.0,
            "evidence_hits": {},
            "required_signals": [],
            "missing_signals": [],
            "reason": "no dominant lane",
        }

    lane_requirements = {
        "ai_platform": {
            "required_groups": [
                ("ai_or_ml", ["ai", "machine learning", "genai", "llm", "llmops", "mlops", "rag", "agentic"]),
                ("infrastructure", ["platform", "infrastructure", "kubernetes", "terraform", "cloud-native", "devops", "sre", "docker", "ml platform", "ai platform"]),
            ],
            "pass_threshold": 2,
            "stricter_terms": ["qa", "support", "sales", "helpdesk", "frontend", "data engineer", "ui developer"],
        },
        "sap_erp": {
            "required_groups": [
                ("sap_core", ["sap", "s/4hana", "otc", "order to cash", "sales and distribution"]),
                ("functional", ["functional consultant", "sap sd", "sap mm", "sap gts", "abap"]),
            ],
            "pass_threshold": 2,
            "stricter_terms": [
                "devops",
                "sre",
                "data engineer",
                "data scientist",
                "qa",
                "support",
                "software engineer",
                "machine learning",
                "ai/ml",
            ],
        },
        "innovation": {
            "required_groups": [
                ("innovation", ["innovation", "prototype", "prototyp", "emerging", "r&d", "research", "creative technologist"]),
                ("emerging_tech", ["iot", "robotics", "ar/vr", "blockchain", "poc", "mvp", "hackathon"]),
            ],
            "pass_threshold": 2,
            "stricter_terms": ["buyer", "procurement", "program manager", "sales", "qa", "asic", "embedded", "hardware", "semiconductor", "verification"],
        },
        "network_automation": {
            "required_groups": [
                ("networking", ["network automation", "cloud network", "network operations", "firewall", "infrastructure automation", "network engineer automation", "network automation engineer"]),
                ("automation", ["automation", "infrastructure automation", "ansible", "python", "terraform", "groovy", "shell scripting", "servicenow", "service now"]),
            ],
            "pass_threshold": 2,
            "stricter_terms": ["security", "sales", "hardware", "firmware", "ivr", "support", "ai/ml", "machine learning"],
        },
    }
    rules = lane_requirements.get(lane)
    if not rules:
        return {
            "lane": lane,
            "passed": True,
            "multiplier": 1.0,
            "evidence_hits": {},
            "required_signals": [],
            "missing_signals": [],
            "reason": "no lane rules",
        }

    evidence_hits: dict[str, list[str]] = {}
    required_signals: list[str] = []
    for key, terms in rules["required_groups"]:
        hits = [term for term in terms if term in text]
        required_signals.append(key)
        evidence_hits[key] = _dedupe_strs(hits, limit=5)

    hit_count = sum(1 for hits in evidence_hits.values() if hits)
    missing_signals = [key for key, hits in evidence_hits.items() if not hits]
    stricter_hits = [term for term in rules["stricter_terms"] if term in text]
    passed = hit_count >= rules["pass_threshold"] and not (lane == "ai_platform" and "machine learning" not in text and "ai" not in text and "genai" not in text and "llm" not in text)
    if lane == "ai_platform":
        passed = passed and any(term in text for term in ("ai", "ml", "machine learning", "genai", "llm", "mlops", "llmops", "rag", "agentic"))
        passed = passed and any(term in text for term in ("platform", "infrastructure", "kubernetes", "terraform", "cloud", "devops", "sre", "docker"))
    elif lane == "sap_erp":
        passed = passed and any(term in text for term in ("sap", "s/4hana", "otc", "order to cash", "sales and distribution"))
        passed = passed and any(term in text for term in ("functional consultant", "sap sd", "sap mm", "sap gts", "abap"))
    elif lane == "innovation":
        passed = passed and any(term in text for term in ("innovation", "prototype", "prototyp", "emerging", "r&d", "research", "creative technologist"))
        passed = passed and any(term in text for term in ("prototype", "emerging", "innovation", "creative technologist", "rapid poc", "rapid pot", "mvp", "poc"))
    elif lane == "network_automation":
        passed = passed and any(term in text for term in ("network automation", "network", "cloud network", "network operations", "routing", "switching", "firewall"))
        passed = passed and any(term in text for term in ("automation", "infrastructure automation", "firewall", "load balancer", "ssl", "ansible", "python"))

    if passed:
        multiplier = 1.0
        reason = "lane evidence present"
    elif hit_count >= 1:
        multiplier = 0.24 if not stricter_hits else 0.14
        reason = "partial lane evidence"
    else:
        multiplier = 0.08 if not stricter_hits else 0.05
        reason = "lane evidence missing"

    return {
        "lane": lane,
        "passed": passed,
        "multiplier": multiplier,
        "evidence_hits": evidence_hits,
        "required_signals": required_signals,
        "missing_signals": missing_signals,
        "stricter_hits": _dedupe_strs(stricter_hits, limit=6),
        "reason": reason,
    }


def _negative_role_penalty_details(
    profile: dict[str, Any],
    title: str,
    description: str,
    understanding: dict[str, Any],
) -> dict[str, Any]:
    lane = str(profile.get("dominant_lane") or "").strip()
    lane_negative_terms = {
        "ai_platform": [
            "qa", "sdet", "support", "helpdesk", "sales", "frontend", "java full stack", "full stack",
            "program manager", "product manager", "business analyst", "data scientist", "data engineer",
            "ui developer", "ux designer", "software engineer", "devops", "sre",
        ],
        "sap_erp": [
            "devops",
            "sre",
            "data engineer",
            "data scientist",
            "software engineer",
            "qa",
            "support",
            "frontend",
            "cloud engineer",
        ],
        "innovation": [
            "buyer", "procurement", "program manager", "sales", "support", "operations manager",
            "data engineer", "software engineer", "full stack", "platform lead", "asic",
            "semiconductor", "hardware", "embedded", "firmware", "analog", "digital design",
            "verification", "vlsi", "electronics", "electrical",
        ],
        "network_automation": [
            "security", "cyber security", "sales", "hardware", "firmware", "ivr", "support",
            "qa", "generic software", "software engineer", "data engineer", "data scientist",
            "ai/ml", "machine learning", "gen ai", "frontend",
        ],
    }
    text = " ".join(
        [
            title or "",
            description or "",
            str(understanding.get("role_family_open") or ""),
            str(understanding.get("primary_domain") or ""),
            " ".join(understanding.get("normalized_titles") or []),
        ]
    ).lower()
    negatives = _dedupe_strs(list(profile.get("negative_roles") or []) + lane_negative_terms.get(lane, []), limit=24)
    matched_terms = [term for term in negatives if term.lower() and term.lower() in text]
    if not matched_terms:
        return {
            "multiplier": 1.0,
            "matched_terms": [],
            "reasons": [],
            "severity": "none",
        }

    title_hit = any(term.lower() in (title or "").lower() for term in matched_terms)
    role_family_hit = any(term.lower() in str(understanding.get("role_family_open") or "").lower() for term in matched_terms)
    domain_hit = any(term.lower() in str(understanding.get("primary_domain") or "").lower() for term in matched_terms)
    unique_count = len({term.lower() for term in matched_terms})
    if unique_count >= 3 or (title_hit and domain_hit):
        multiplier = 0.12
        severity = "critical"
    elif title_hit or role_family_hit:
        multiplier = 0.24
        severity = "high"
    elif domain_hit:
        multiplier = 0.48
        severity = "medium"
    else:
        multiplier = 0.72
        severity = "low"

    reasons = [f"matched negative term: {term}" for term in _dedupe_strs(matched_terms, limit=8)]
    return {
        "multiplier": multiplier,
        "matched_terms": _dedupe_strs(matched_terms, limit=8),
        "reasons": reasons,
        "severity": severity,
    }


def _score_seniority_match(candidate_band: str, job_band: str) -> float:
    cand = SENIORITY_ORDER.get(candidate_band, 1)
    job = SENIORITY_ORDER.get(job_band, 1)
    diff = abs(cand - job)
    if diff == 0:
        return 100.0
    if diff == 1:
        return 80.0
    if diff == 2:
        return 55.0
    return 25.0


def _score_skill_coverage(must_have_skills: list[str], required_skills: list[str], preferred_skills: list[str]) -> tuple[float, list[str]]:
    candidate = {skill.lower(): skill for skill in must_have_skills}
    required = _dedupe_strs(required_skills, limit=12)
    preferred = _dedupe_strs(preferred_skills, limit=10)
    if not required and not preferred:
        return 45.0, []

    req_hits = [skill for skill in required if skill.lower() in candidate]
    pref_hits = [skill for skill in preferred if skill.lower() in candidate]
    if required:
        coverage = len(req_hits) / max(1, len(required))
        score = 35.0 + coverage * 65.0
    else:
        coverage = len(pref_hits) / max(1, len(preferred))
        score = 30.0 + coverage * 45.0
    return min(score, 100.0), _dedupe_strs(req_hits + pref_hits, limit=8)


def _negative_role_penalty(negative_roles: list[str], title: str, description: str) -> float:
    text = f"{title} {description}".lower()
    matches = [term for term in negative_roles if str(term).strip() and str(term).lower() in text]
    if not matches:
        return 1.0
    return 0.6 if len(matches) == 1 else 0.35


def _domain_alignment_score(candidate_domains: list[str], job_profile: dict[str, Any]) -> float:
    desired = {domain.lower() for domain in candidate_domains if str(domain).strip()}
    if not desired:
        return 50.0
    job_text = " ".join(
        [
            str(job_profile.get("primary_domain") or job_profile.get("domain") or ""),
            str(job_profile.get("role_family_open") or job_profile.get("role_family") or ""),
            " ".join(job_profile.get("normalized_titles") or job_profile.get("role_titles_normalized") or []),
        ]
    ).lower()
    if any(domain in job_text for domain in desired):
        return 100.0
    if any(token in job_text for token in ("ai", "ml", "sap", "network", "platform", "backend", "innovation")):
        return 45.0
    return 30.0


def _lane_alignment_score(profile: dict[str, Any], title: str, description: str, job_profile: dict[str, Any]) -> float:
    lane = str(profile.get("dominant_lane") or "")
    if not lane:
        return 50.0
    preset = LANE_PRESETS.get(lane, {})
    text = " ".join(
        [
            title or "",
            description or "",
            str(job_profile.get("primary_domain") or job_profile.get("domain") or ""),
            str(job_profile.get("role_family_open") or job_profile.get("role_family") or ""),
            " ".join(job_profile.get("normalized_titles") or job_profile.get("role_titles_normalized") or []),
            " ".join(job_profile.get("required_skills") or []),
        ]
    ).lower()
    positive_hits = sum(1 for term in preset.get("positive_terms", []) if term in text)
    negative_hits = sum(1 for term in preset.get("negative_terms", []) if term in text)
    alias_hits = sum(1 for term in preset.get("title_aliases", []) if term.lower() in text)
    score = 35.0 + positive_hits * 18.0 + alias_hits * 10.0 - negative_hits * 14.0
    return max(0.0, min(score, 100.0))


def _lane_gate_multiplier(profile: dict[str, Any], title: str, description: str, job_profile: dict[str, Any]) -> float:
    result = _lane_gate_result(profile, job_profile, title, description)
    return float(result.get("multiplier", 1.0))


def _build_generalized_cfg(profile: dict[str, Any]) -> dict:
    cfg = load_base_config()
    cfg = json.loads(json.dumps(cfg))
    preferred_locations = list(profile.get("preferred_locations") or [])
    preferred_work_modes = [str(mode).lower() for mode in (profile.get("preferred_work_modes") or [])]
    cfg.setdefault("location_scoring", {})
    cfg["location_scoring"]["preferred_locations"] = preferred_locations
    cfg["location_scoring"]["want_remote"] = "remote" in preferred_work_modes or not preferred_locations
    return cfg


def _ensure_job_profile(job: JobRaw, cfg: dict) -> dict[str, Any]:
    existing = job.job_profile if isinstance(job.job_profile, dict) else None
    if existing:
        return existing
    return build_job_profile(
        title=job.title,
        company=job.company,
        description=job.description,
        location=job.location,
        site=job.site,
        date_posted=job.date_posted,
        role_clusters=job.role_clusters or [],
        cfg=cfg,
    )


async def _run_generalized(
    *,
    target: ResumeTarget,
    spec: dict,
    parsed: ResumeParseResult,
    resume_text: str,
    days: int,
    limit: int,
    quick_search: bool,
) -> PipelineArtifacts:
    run_id = uuid.uuid4().hex[:10]
    profile = _build_generalized_profile(spec, parsed, resume_text)
    query_plan = _build_generalized_query_plan(profile)
    profile_stub = _profile_to_stub(profile, query_plan)
    queries = _search_queries_from_plan(
        query_plan,
        preferred_locations=list(profile.get("preferred_locations") or []),
        max_terms=8,
        default_country=settings.scraper_default_country,
    )
    cfg = _build_generalized_cfg(profile)
    cleanup_user_id: str | None = None
    success = False

    try:
        async with AsyncSessionLocal() as db:
            user = User(
                email=f"generalized-experiment-{target.key}-{run_id}@test.com",
                password_hash="x",
                provider="credentials",
            )
            db.add(user)
            await db.flush()
            cleanup_user_id = user.id
            db.add(
                Profile(
                    user_id=user.id,
                    resume_text=resume_text,
                    target_roles=list(profile.get("target_roles_primary") or []),
                    preferred_locations=list(profile.get("preferred_locations") or []),
                    onboarding_complete=True,
                    scraper_max_terms=8,
                    scraper_hours_old=days * 24,
                    config_overrides={"generalized_profile": profile, "generalized_query_plan": query_plan},
                )
            )
            await db.commit()

            scraper_cfg = ScraperConfig.from_env(title_blocklist=list(query_plan.get("negative_keywords") or []))
            scraper_cfg.hours_old = days * 24
            scraper_cfg.sources = ["indeed"] if quick_search else ["indeed", "linkedin", "rapidapi", "free_apis", "google_jobs"]

            jobs = await scrape(queries, scraper_cfg, db=db, return_mode="jobs")
            job_ids = await _persist_jobs(db, jobs, cfg)
            del jobs
            gc.collect()

            result = await db.execute(select(JobRaw).where(JobRaw.id.in_(job_ids)))
            job_rows = result.scalars().all()
            if not job_rows:
                success = True
                return PipelineArtifacts(
                    profile={"candidate_profile_generalized": profile, "query_plan_generalized": query_plan},
                    queries=_serialize_queries(queries),
                    top_jobs=[],
                    summary={"queries": len(queries), "scraped_jobs": 0, "top_jobs": 0},
                    cleanup_user_ids=[cleanup_user_id] if cleanup_user_id else [],
                )

            engine = EmbeddingEngine(cfg)
            resume_embedding_text = build_resume_embedding_text(
                resume_text=resume_text,
                distilled="\n".join(
                    _dedupe_strs(
                        list(profile.get("target_roles_primary") or [])
                        + list(profile.get("domains") or [])
                        + list(profile.get("must_have_skills") or []),
                        limit=20,
                    )
                ),
                cfg=cfg,
                use_case="generalized_compare",
            )
            resume_vector = engine.embed([resume_embedding_text])[0]

            job_profiles = [_ensure_job_profile(job, cfg) for job in job_rows]
            generalized_job_profiles = [
                _build_generalized_job_understanding(job, job_profile, cfg)
                for job, job_profile in zip(job_rows, job_profiles)
            ]
            job_texts = [
                build_job_embedding_text(
                    title=str(job.title or ""),
                    description=str(job.description or ""),
                    canonical_skills=list(generalized_profile.get("required_skills") or job_profile.get("required_skills") or []),
                    cfg=cfg,
                )
                for job, job_profile, generalized_profile in zip(job_rows, job_profiles, generalized_job_profiles)
            ]
            job_vectors = engine.embed(job_texts)
            semantic_scores = cosine_similarity(resume_vector, job_vectors)

        role_texts = _dedupe_strs(
            list(profile.get("target_roles_primary") or []) + list(profile.get("target_roles_adjacent") or []),
            limit=8,
        )
        role_vectors = engine.embed(role_texts) if role_texts else np.zeros((0, 0), dtype="float32")
        title_vectors = engine.embed([str(job.title or "") for job in job_rows])
        if len(role_texts):
            title_sims = np.stack([cosine_similarity(role_vec, title_vectors) for role_vec in role_vectors], axis=1).max(axis=1)
        else:
            title_sims = np.zeros(len(job_rows), dtype="float32")

        scored_rows: list[dict[str, Any]] = []
        for idx, (job, job_profile, generalized_profile) in enumerate(zip(job_rows, job_profiles, generalized_job_profiles)):
            skill_score, overlap = _score_skill_coverage(
                list(profile.get("must_have_skills") or []),
                list(generalized_profile.get("required_skills") or []),
                list(generalized_profile.get("preferred_skills") or []),
            )
            domain_score = _domain_alignment_score(list(profile.get("domains") or []), generalized_profile)
            lane_score = _lane_alignment_score(profile, str(job.title or ""), str(job.description or ""), generalized_profile)
            seniority_score = _score_seniority_match(
                str(profile.get("seniority_band") or "mid"),
                str(generalized_profile.get("seniority_band") or "mid"),
            )
            location_score = float(location_score_5tier(str(job.location or ""), str(job.description or ""), cfg))
            recency_score = float(recency_score_0_100(job.date_posted))
            quality_score = float(generalized_profile.get("job_quality") or 0.0)
            semantic_score = max(0.0, float(semantic_scores[idx]))
            role_score = float(title_relevance_score_0_100(title_sims[idx], low=0.18, high=0.75))
            lane_gate = _lane_gate_result(profile, generalized_profile, str(job.title or ""), str(job.description or ""))
            negative_penalty = _negative_role_penalty_details(
                profile,
                str(job.title or ""),
                str(job.description or ""),
                generalized_profile,
            )
            generalized_deterministic_score = (
                role_score * 0.18
                + lane_score * 0.16
                + domain_score * 0.12
                + skill_score * 0.18
                + seniority_score * 0.10
                + location_score * 0.08
                + recency_score * 0.06
                + quality_score * 0.12
            )
            final_score = generalized_deterministic_score * float(lane_gate.get("multiplier") or 1.0) * float(negative_penalty.get("multiplier") or 1.0)
            penalty_reasons = _dedupe_strs(
                [
                    *(str(reason) for reason in (lane_gate.get("missing_signals") or []) if reason),
                    *(str(reason) for reason in (lane_gate.get("stricter_hits") or []) if reason),
                    *(str(reason) for reason in (negative_penalty.get("reasons") or []) if reason),
                ],
                limit=12,
            )
            if quality_score < 35.0:
                penalty_reasons.append("very weak JD quality")
                final_score *= 0.7
            scored_rows.append(
                {
                    "job_id": str(job.id),
                    "job_url": str(job.job_url or ""),
                    "title": str(job.title or ""),
                    "company": str(job.company or ""),
                    "location": str(job.location or ""),
                    "site": str(job.site or ""),
                    "final_score": round(final_score, 4),
                    "generalized_deterministic_score": round(generalized_deterministic_score, 4),
                    "semantic_score": round(semantic_score, 4),
                    "title_relevance_score": round(role_score, 2),
                    "score_breakdown": {
                        "role_score": round(role_score, 2),
                        "lane_score": round(lane_score, 2),
                        "domain_score": round(domain_score, 2),
                        "skill_score": round(skill_score, 2),
                        "seniority_score": round(seniority_score, 2),
                        "location_score": round(location_score, 2),
                        "recency_score": round(recency_score, 2),
                        "quality_score": round(quality_score, 2),
                        "generalized_deterministic_score": round(generalized_deterministic_score, 4),
                        "lane_gate_multiplier": round(float(lane_gate.get("multiplier") or 1.0), 4),
                        "negative_role_penalty": round(float(negative_penalty.get("multiplier") or 1.0), 4),
                        "final_score": round(final_score, 4),
                        "weights": {
                            "role_score": 0.18,
                            "lane_score": 0.16,
                            "domain_score": 0.12,
                            "skill_score": 0.18,
                            "seniority_score": 0.10,
                            "location_score": 0.08,
                            "recency_score": 0.06,
                            "quality_score": 0.12,
                        },
                    },
                    "lane_gate": lane_gate,
                    "penalty_reasons": penalty_reasons,
                    "domain_score": round(domain_score, 2),
                    "lane_score": round(lane_score, 2),
                    "skill_score": round(skill_score, 2),
                    "seniority_score": round(seniority_score, 2),
                    "location_score": round(location_score, 2),
                    "recency_score": round(recency_score, 2),
                    "quality_score": round(quality_score, 2),
                    "skill_overlap": overlap,
                    "generalized_job_profile": generalized_profile,
                    "job_profile": job_profile,
                }
            )

        scored_rows.sort(key=lambda row: row["final_score"], reverse=True)
        deduped: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in scored_rows:
            key = _normalize_title_key(row["title"], row["company"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(row)
            if len(deduped) >= limit:
                break

        for rank, row in enumerate(deduped, start=1):
            row["rank"] = rank

        success = True
        return PipelineArtifacts(
            profile={"candidate_profile_generalized": profile, "query_plan_generalized": query_plan, "profile_stub": {"target_roles": list(profile_stub.target_roles), "preferred_locations": list(profile_stub.preferred_locations)}},
            queries=_serialize_queries(queries),
            top_jobs=deduped,
            summary={
                "queries": len(queries),
                "scraped_jobs": len(job_ids),
                "top_jobs": len(deduped),
            },
            cleanup_user_ids=[cleanup_user_id] if cleanup_user_id else [],
        )
    finally:
        if cleanup_user_id and not success:
            await delete_user_ids(AsyncSessionLocal, [cleanup_user_id])


def _compare_top_jobs(baseline: list[dict[str, Any]], generalized: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_keys = [_normalize_title_key(job["title"], job["company"]) for job in baseline]
    generalized_keys = [_normalize_title_key(job["title"], job["company"]) for job in generalized]
    overlap = sorted(set(baseline_keys) & set(generalized_keys))
    baseline_only = [job for job in baseline if _normalize_title_key(job["title"], job["company"]) not in overlap]
    generalized_only = [job for job in generalized if _normalize_title_key(job["title"], job["company"]) not in overlap]
    generalized_lane_pass = sum(1 for job in generalized if bool((job.get("lane_gate") or {}).get("passed")))
    generalized_lane_fail = len(generalized) - generalized_lane_pass
    generalized_misleading = sum(
        1
        for job in generalized
        if (job.get("lane_gate") or {}).get("passed") is False
        or str((job.get("score_breakdown") or {}).get("negative_role_penalty") or "1.0") in {"0.12", "0.24", "0.48"}
    )
    return {
        "top20_overlap_count": len(overlap),
        "top20_overlap_ratio": round(len(overlap) / max(1, min(len(baseline), len(generalized))), 4),
        "top10_overlap_count": len(set(baseline_keys[:10]) & set(generalized_keys[:10])),
        "top10_overlap_ratio": round(len(set(baseline_keys[:10]) & set(generalized_keys[:10])) / max(1, min(10, len(baseline), len(generalized))), 4),
        "shared_jobs": overlap,
        "baseline_only_top20": [
            {"rank": job["rank"], "title": job["title"], "company": job["company"], "score": job["final_score"]}
            for job in baseline_only[:20]
        ],
        "generalized_only_top20": [
            {"rank": job["rank"], "title": job["title"], "company": job["company"], "score": job["final_score"]}
            for job in generalized_only[:20]
        ],
        "generalized_lane_gate_pass_count": generalized_lane_pass,
        "generalized_lane_gate_fail_count": generalized_lane_fail,
        "generalized_misleading_count": generalized_misleading,
        "generalized_avg_final_score": round(
            sum(float(job.get("final_score") or 0.0) for job in generalized) / max(1, len(generalized)),
            4,
        ),
    }


def _markdown_summary(
    *,
    target: ResumeTarget,
    baseline: PipelineArtifacts,
    generalized: PipelineArtifacts,
    comparison: dict[str, Any],
) -> str:
    lines = [
        f"# {target.key.upper()} Comparison",
        "",
        "## Summary",
        "",
        f"- Baseline queries: {baseline.summary.get('queries', 0)}",
        f"- Generalized queries: {generalized.summary.get('queries', 0)}",
        f"- Baseline scraped jobs: {baseline.summary.get('scraped_jobs', 0)}",
        f"- Generalized scraped jobs: {generalized.summary.get('scraped_jobs', 0)}",
        f"- Top-20 overlap: {comparison.get('top20_overlap_count', 0)}",
        f"- Top-10 overlap: {comparison.get('top10_overlap_count', 0)}",
        f"- Generalized lane gate pass/fail: {comparison.get('generalized_lane_gate_pass_count', 0)}/{comparison.get('generalized_lane_gate_fail_count', 0)}",
        "",
        "## Baseline Top 20",
        "",
    ]
    for job in baseline.top_jobs[:20]:
        lines.append(f"- {job['rank']}. {job['title']} | {job['company']} | {job['final_score']}")
    lines.extend(["", "## Generalized Top 20", ""])
    for job in generalized.top_jobs[:20]:
        lines.append(f"- {job['rank']}. {job['title']} | {job['company']} | {job['final_score']}")
    lines.extend(["", "## Baseline Only", ""])
    for job in comparison.get("baseline_only_top20", []):
        lines.append(f"- {job['rank']}. {job['title']} | {job['company']} | {job['score']}")
    lines.extend(["", "## Generalized Only", ""])
    for job in comparison.get("generalized_only_top20", []):
        lines.append(f"- {job['rank']}. {job['title']} | {job['company']} | {job['score']}")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str))


async def _run_target(
    *,
    target: ResumeTarget,
    days: int,
    limit: int,
    quick_search: bool,
    output_dir: Path,
) -> dict[str, Any]:
    spec = _load_spec(target)
    pdf_path = RESUMES_DIR / target.pdf_name
    resume_text = _extract_text_from_pdf(pdf_path.read_bytes())
    parsed = _parse_from_spec(spec)

    baseline = await _run_baseline(
        target=target,
        spec=spec,
        parsed=parsed,
        resume_text=resume_text,
        days=days,
        limit=limit,
        quick_search=quick_search,
    )
    generalized = await _run_generalized(
        target=target,
        spec=spec,
        parsed=parsed,
        resume_text=resume_text,
        days=days,
        limit=limit,
        quick_search=quick_search,
    )
    comparison = _compare_top_jobs(baseline.top_jobs, generalized.top_jobs)

    _write_json(output_dir / f"{target.key}.baseline_profile.json", baseline.profile)
    _write_json(output_dir / f"{target.key}.generalized_profile.json", generalized.profile)
    _write_json(output_dir / f"{target.key}.baseline_queries.json", baseline.queries)
    _write_json(output_dir / f"{target.key}.generalized_queries.json", generalized.queries)
    _write_json(output_dir / f"{target.key}.baseline_top_jobs.json", baseline.top_jobs)
    _write_json(output_dir / f"{target.key}.generalized_top_jobs.json", generalized.top_jobs)
    _write_json(output_dir / f"{target.key}.comparison.json", comparison)
    (output_dir / f"{target.key}.comparison.md").write_text(
        _markdown_summary(target=target, baseline=baseline, generalized=generalized, comparison=comparison)
    )

    print(f"\n=== {target.key.upper()} ===")
    print(
        json.dumps(
            {
                "baseline_queries": baseline.summary.get("queries", 0),
                "generalized_queries": generalized.summary.get("queries", 0),
                "baseline_scraped": baseline.summary.get("scraped_jobs", 0),
                "generalized_scraped": generalized.summary.get("scraped_jobs", 0),
                "top20_overlap": comparison.get("top20_overlap_count", 0),
            },
            indent=2,
        )
    )
    print("Baseline top 20:")
    for job in baseline.top_jobs[:20]:
        print(f"  {job['rank']:>2}. {job['title']} | {job['company']} | {job['final_score']}")
    print("Generalized top 20:")
    for job in generalized.top_jobs[:20]:
        print(f"  {job['rank']:>2}. {job['title']} | {job['company']} | {job['final_score']}")

    return {
        "target": target.key,
        "comparison": comparison,
        "baseline_summary": baseline.summary,
        "generalized_summary": generalized.summary,
        "cleanup_user_ids": baseline.cleanup_user_ids + generalized.cleanup_user_ids,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline vs generalized matching on sample resumes")
    parser.add_argument("--resume", action="append", choices=sorted(TARGETS.keys()), required=False)
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--quick-search", action="store_true", help="Use Indeed only for faster comparison")
    parser.add_argument("--output-dir", type=str, default="", help="Optional output directory")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else DEFAULT_OUTPUT_ROOT / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = args.resume or ["example", "vivek", "aditya"]
    results = []
    cleanup_user_ids: list[str] = []
    try:
        for key in targets:
            result = (
                await _run_target(
                    target=TARGETS[key],
                    days=args.days,
                    limit=args.limit,
                    quick_search=args.quick_search,
                    output_dir=output_dir,
                )
            )
            results.append(result)
            cleanup_user_ids.extend(result.get("cleanup_user_ids", []))
        _write_json(output_dir / "summary.json", results)
    finally:
        try:
            if cleanup_user_ids:
                await delete_user_ids(AsyncSessionLocal, cleanup_user_ids)
        finally:
            unload_embedding_engine()
    print(f"\nArtifacts written to: {output_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
