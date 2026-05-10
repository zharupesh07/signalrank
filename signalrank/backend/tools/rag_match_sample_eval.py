from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import asc, desc, func, select

from api.database import AsyncSessionLocal, engine
from api.models import JobRaw, JobResult, Profile, Run, User

DEFAULT_EMAIL = "examplecandidate@gmail.com"
DEFAULT_OUTPUT_ROOT = (
    Path(__file__).resolve().parents[1] / "tmp" / "rag_match_sample_eval"
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "our",
    "the",
    "their",
    "this",
    "to",
    "with",
    "you",
    "your",
}

GENERIC_ROLE_TERMS = {
    "engineer",
    "developer",
    "lead",
    "senior",
    "staff",
    "principal",
    "manager",
    "architect",
    "specialist",
    "consultant",
}

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "AI platform": ("ai platform", "ml platform", "llm platform"),
    "Agentic AI": ("agentic ai", "agentic", "ai agents", "agent systems"),
    "LLM": ("llm", "large language model", "genai", "generative ai"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "MLOps": ("mlops", "ml ops", "model deployment", "model lifecycle"),
    "LLMOps": ("llmops", "llm ops"),
    "Machine Learning": ("machine learning", "ml ", "ai/ml", "ai ml"),
    "Python": ("python",),
    "FastAPI": ("fastapi",),
    "SQL": ("sql", "postgres", "postgresql", "mysql"),
    "Spark": ("spark", "pyspark"),
    "Docker": ("docker", "containerization"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Terraform": ("terraform", "infrastructure as code", "iac"),
    "AWS": ("aws", "amazon web services"),
    "GCP": ("gcp", "google cloud", "cloud run"),
    "CI/CD": ("ci/cd", "cicd", "continuous integration", "github actions"),
    "Microservices": ("microservices", "distributed systems"),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "Hugging Face": ("hugging face", "huggingface"),
    "LangChain": ("langchain",),
    "LangGraph": ("langgraph",),
    "Vector database": ("vector database", "vector db", "embeddings"),
    "Java": ("java",),
    "C#": ("c#", ".net", "dotnet"),
    "QA": ("qa", "quality assurance", "testing", "test automation", "selenium"),
    "Project management": (
        "project management",
        "program management",
        "scrum",
        "agile",
    ),
    "Sales": ("sales", "b2b sales", "business development"),
    "Hardware": ("pcb", "hardware", "electronics", "embedded"),
    "Customer support": ("support engineer", "technical support", "customer support"),
}

RELATED_SKILLS: dict[str, tuple[str, ...]] = {
    "AI platform": ("MLOps", "LLMOps", "Kubernetes", "Docker", "GCP", "AWS"),
    "Agentic AI": ("LLM", "RAG", "LangChain", "LangGraph", "Vector database"),
    "LLM": ("Agentic AI", "RAG", "LLMOps", "Hugging Face"),
    "RAG": ("LLM", "Agentic AI", "Vector database", "LangChain", "LangGraph"),
    "MLOps": ("AI platform", "Docker", "Kubernetes", "FastAPI", "CI/CD"),
    "LLMOps": ("AI platform", "LLM", "Agentic AI", "MLOps"),
    "Machine Learning": ("MLOps", "PyTorch", "TensorFlow", "Python"),
    "Docker": ("Kubernetes", "MLOps", "CI/CD"),
    "Kubernetes": ("Docker", "AI platform", "MLOps"),
    "AWS": ("GCP", "Docker", "Kubernetes"),
    "GCP": ("AWS", "Docker", "Kubernetes"),
    "FastAPI": ("Python", "Microservices"),
    "Microservices": ("FastAPI", "Docker", "Kubernetes"),
    "PyTorch": ("Machine Learning", "Python", "Hugging Face"),
    "TensorFlow": ("Machine Learning", "Python"),
    "LangChain": ("LLM", "RAG", "Agentic AI"),
    "LangGraph": ("LLM", "RAG", "Agentic AI"),
    "Vector database": ("RAG", "LLM", "Agentic AI"),
}

ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "BI / Analytics Management",
        ("bie manager", "business intelligence manager", "analytics manager"),
    ),
    (
        "Director / Engineering Management",
        ("director", "engineering manager", "head of engineering"),
    ),
    ("Full Stack Development", ("full stack", "full-stack", "fullstack")),
    (
        "RAG / Agentic AI Engineering",
        (
            "rag",
            "agentic",
            "ai agents",
            "llm tooling",
            "llm engineer",
            "applied ai",
            "ai integration",
        ),
    ),
    (
        "AI / ML Engineering",
        (
            "ai engineer",
            "ai application engineer",
            "ai/ml",
            "machine learning",
            "ml engineer",
            "gen ai",
            "genai",
        ),
    ),
    (
        "AI Platform / MLOps",
        ("ai platform", "ml platform", "mlops", "llmops", "ai/ml platform"),
    ),
    (
        "Backend / Software Engineering",
        ("backend", "software engineer", "python developer", "java/python"),
    ),
    ("Data Engineering", ("data engineer", "knowledge engineer", "data platform")),
    (
        "Cloud / DevOps / SRE",
        ("devops", "sre", "site reliability", "cloud engineer", "cloud devops"),
    ),
    (
        "QA / Test Engineering",
        ("qa", "quality assurance", "test engineer", "test automation"),
    ),
    (
        "Project / Program Management",
        ("project manager", "program manager", "technical program manager"),
    ),
    ("Sales Engineering", ("sales engineer", "presales", "pre-sales")),
    (
        "Hardware / Electronics",
        ("pcb", "hardware design", "electronics engineer", "embedded"),
    ),
    (
        "Support / Account Management",
        ("support engineer", "technical account manager", "customer support"),
    ),
)

POSITIVE_ROLE_LABELS = {
    "RAG / Agentic AI Engineering",
    "AI / ML Engineering",
    "AI Platform / MLOps",
    "Backend / Software Engineering",
    "Data Engineering",
    "Cloud / DevOps / SRE",
}

HARD_NEGATIVE_ROLE_LABELS = {
    "BI / Analytics Management",
    "Director / Engineering Management",
    "Full Stack Development",
    "QA / Test Engineering",
    "Project / Program Management",
    "Sales Engineering",
    "Hardware / Electronics",
    "Support / Account Management",
}


@dataclass(frozen=True)
class EvidenceChunk:
    source: str
    text: str


@dataclass(frozen=True)
class Requirement:
    label: str
    query: str
    category: str
    weight: float
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceMatch:
    source: str
    text: str
    score: float


@dataclass(frozen=True)
class RequirementResult:
    label: str
    category: str
    weight: float
    band: str
    score: float
    evidence: list[EvidenceMatch]


@dataclass(frozen=True)
class MatchFactors:
    role_score: float
    evidence_score: float
    skill_score: float
    semantic_score: float
    location_score: float
    constraint_score: float
    final_score: float
    band: str
    hard_constraints: list[str]


@dataclass(frozen=True)
class SampleJob:
    expected: str
    current_score: float
    current_fit_band: str | None
    title: str
    company: str
    location: str | None
    job_url: str
    description: str


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9+#./-]+", _normalize(value))
        if len(token) > 1 and token not in STOPWORDS
    }


def _redact_personal(value: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[email]", str(value or ""))
    text = re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", "[phone]", text)
    return text


def _short(value: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", _redact_personal(value)).strip()
    return text[:limit]


def _contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(
        _normalize(alias) and _normalize(alias) in normalized for alias in aliases
    )


def _canonical_skills_from_text(text: str) -> set[str]:
    normalized = _normalize(text)
    skills: set[str] = set()
    for label, aliases in SKILL_ALIASES.items():
        if any(
            _normalize(alias) and _normalize(alias) in normalized for alias in aliases
        ):
            skills.add(label)
    return skills


def _expanded_skills(skills: set[str]) -> set[str]:
    expanded = set(skills)
    for skill in skills:
        expanded.update(RELATED_SKILLS.get(skill, ()))
    return expanded


def _candidate_skill_set(
    resume_text: str, candidate_profile: dict[str, Any] | None
) -> set[str]:
    parts = [resume_text]
    for key in ("must_have_skills", "good_to_have_skills", "domains"):
        values = (candidate_profile or {}).get(key) or []
        if isinstance(values, list):
            parts.extend(str(value) for value in values)
    return _canonical_skills_from_text("\n".join(parts))


def _candidate_role_labels(candidate_profile: dict[str, Any] | None) -> set[str]:
    values: list[str] = []
    for key in ("target_roles_primary", "target_roles_adjacent", "negative_roles"):
        raw = (candidate_profile or {}).get(key) or []
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    role_text = " ".join(values)
    labels: set[str] = set()
    normalized = _normalize(role_text)
    for label, aliases in ROLE_PATTERNS:
        if any(alias in normalized for alias in aliases):
            labels.add(label)
    if "platform" in normalized or "llmops" in normalized or "mlops" in normalized:
        labels.add("AI Platform / MLOps")
    if "machine learning" in normalized or "ai " in f"{normalized} ":
        labels.add("AI / ML Engineering")
    return labels


def _preferred_locations(candidate_profile: dict[str, Any] | None) -> set[str]:
    values = (candidate_profile or {}).get("preferred_locations") or []
    if not isinstance(values, list):
        return set()
    return {_normalize(str(value)) for value in values if str(value).strip()}


def _resume_chunks(
    resume_text: str, candidate_profile: dict[str, Any] | None
) -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    for key in (
        "target_roles_primary",
        "target_roles_adjacent",
        "must_have_skills",
        "good_to_have_skills",
        "domains",
    ):
        values = (candidate_profile or {}).get(key) or []
        if isinstance(values, list) and values:
            chunks.append(
                EvidenceChunk(f"profile:{key}", ", ".join(str(item) for item in values))
            )

    for item in (candidate_profile or {}).get("evidence_snippets") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        source = str(item.get("source") or "profile:evidence")
        if text:
            chunks.append(EvidenceChunk(source, text))

    for idx, raw_line in enumerate(resume_text.splitlines(), start=1):
        line = raw_line.strip(" -•\t")
        if len(line) < 18:
            continue
        if "@" in line or re.search(r"\+?\d[\d\s().-]{7,}\d", line):
            continue
        chunks.append(EvidenceChunk(f"resume:L{idx}", line))

    seen: set[str] = set()
    deduped: list[EvidenceChunk] = []
    for chunk in chunks:
        text = _short(chunk.text, 260)
        key = _normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(EvidenceChunk(chunk.source, text))
    return deduped


def _extract_role_requirements(title: str, description: str) -> list[Requirement]:
    normalized_title = _normalize(title)
    normalized_fallback = _normalize(f"{title}\n{description[:800]}")
    requirements: list[Requirement] = []
    for label, aliases in ROLE_PATTERNS:
        if any(alias in normalized_title for alias in aliases):
            requirements.append(
                Requirement(
                    label=label,
                    query=label,
                    category="role",
                    weight=3.0 if label in POSITIVE_ROLE_LABELS else 3.5,
                    aliases=aliases + (label,),
                )
            )
    if not requirements:
        for label, aliases in ROLE_PATTERNS:
            if any(alias in normalized_fallback for alias in aliases):
                requirements.append(
                    Requirement(
                        label=label,
                        query=label,
                        category="role",
                        weight=3.0 if label in POSITIVE_ROLE_LABELS else 3.5,
                        aliases=aliases + (label,),
                    )
                )
    if not requirements:
        cleaned_title = re.sub(r"[^A-Za-z0-9 /+#.-]+", " ", title).strip()
        if cleaned_title:
            requirements.append(
                Requirement(
                    label=cleaned_title[:80],
                    query=cleaned_title,
                    category="role",
                    weight=2.5,
                    aliases=(cleaned_title,),
                )
            )
    return requirements[:3]


def _extract_skill_requirements(title: str, description: str) -> list[Requirement]:
    text = f"{title}\n{description}"
    normalized = _normalize(text)
    found: list[Requirement] = []
    for label, aliases in SKILL_ALIASES.items():
        if any(
            _normalize(alias) and _normalize(alias) in normalized for alias in aliases
        ):
            title_hit = any(
                _normalize(alias) and _normalize(alias) in _normalize(title)
                for alias in aliases
            )
            found.append(
                Requirement(
                    label=label,
                    query=label,
                    category="skill",
                    weight=2.0 if title_hit else 1.0,
                    aliases=aliases + (label,),
                )
            )
    found.sort(key=lambda item: (-item.weight, item.label.lower()))
    return found[:12]


def extract_requirements(job: SampleJob) -> list[Requirement]:
    requirements = _extract_role_requirements(job.title, job.description)
    requirements.extend(_extract_skill_requirements(job.title, job.description))
    seen: set[str] = set()
    deduped: list[Requirement] = []
    for req in requirements:
        key = req.label.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(req)
    return deduped[:14]


def _score_chunk(requirement: Requirement, chunk: EvidenceChunk) -> float:
    query_tokens = _tokens(requirement.query) - GENERIC_ROLE_TERMS
    chunk_tokens = _tokens(chunk.text)
    overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
    fuzzy = (
        fuzz.partial_ratio(_normalize(requirement.query), _normalize(chunk.text))
        / 100.0
    )
    exact = _contains_alias(chunk.text, requirement.aliases)
    score = max(overlap * 0.78, fuzzy * 0.42)
    if exact:
        score += 0.35
    return min(score, 1.0)


def _band(score: float, evidence: list[EvidenceMatch]) -> str:
    if score >= 0.72 and evidence:
        return "strong"
    if score >= 0.42 and evidence:
        return "partial"
    return "missing"


def evaluate_requirements(
    requirements: list[Requirement],
    chunks: list[EvidenceChunk],
    *,
    top_evidence: int = 3,
) -> list[RequirementResult]:
    results: list[RequirementResult] = []
    for req in requirements:
        scored = [
            EvidenceMatch(chunk.source, chunk.text, round(_score_chunk(req, chunk), 3))
            for chunk in chunks
        ]
        scored = [item for item in scored if item.score >= 0.25]
        scored.sort(key=lambda item: (-item.score, item.source))
        evidence = scored[:top_evidence]
        score = evidence[0].score if evidence else 0.0
        results.append(
            RequirementResult(
                label=req.label,
                category=req.category,
                weight=req.weight,
                band=_band(score, evidence),
                score=score,
                evidence=evidence,
            )
        )
    return results


def synthesize_score(results: list[RequirementResult]) -> tuple[float, str]:
    if not results:
        return 0.0, "reject"
    band_values = {"strong": 1.0, "partial": 0.55, "missing": 0.0}
    weighted = sum(band_values[item.band] * item.weight for item in results)
    total = sum(item.weight for item in results)
    score = round((weighted / total) * 100.0, 1) if total else 0.0
    role_results = [item for item in results if item.category == "role"]
    hard_negative_role = any(
        item.label in HARD_NEGATIVE_ROLE_LABELS for item in role_results
    )
    negative_role_missing = any(
        item.label not in POSITIVE_ROLE_LABELS and item.band == "missing"
        for item in role_results
    )
    if hard_negative_role or negative_role_missing:
        score = round(min(score, 34.0), 1)
    if score >= 75:
        return score, "strong_fit"
    if score >= 55:
        return score, "adjacent_fit"
    if score >= 35:
        return score, "weak_fit"
    return score, "reject"


def _evidence_score(results: list[RequirementResult]) -> float:
    if not results:
        return 0.0
    band_values = {"strong": 1.0, "partial": 0.55, "missing": 0.0}
    weighted = sum(band_values[item.band] * item.weight for item in results)
    total = sum(item.weight for item in results)
    return round((weighted / total) * 100.0, 1) if total else 0.0


def _role_score(
    results: list[RequirementResult], candidate_profile: dict[str, Any] | None
) -> tuple[float, list[str]]:
    role_results = [item for item in results if item.category == "role"]
    if not role_results:
        return 50.0, []

    candidate_roles = _candidate_role_labels(candidate_profile)
    hard_constraints: list[str] = []
    role_scores: list[float] = []
    for result in role_results:
        if result.label in HARD_NEGATIVE_ROLE_LABELS:
            hard_constraints.append(f"title_lane_mismatch:{result.label}")
            role_scores.append(0.0)
        elif result.label in POSITIVE_ROLE_LABELS and (
            result.label in candidate_roles or result.band == "strong"
        ):
            role_scores.append(100.0)
        elif result.label in POSITIVE_ROLE_LABELS and result.band == "partial":
            role_scores.append(65.0)
        elif result.label in POSITIVE_ROLE_LABELS:
            hard_constraints.append(f"missing_role_evidence:{result.label}")
            role_scores.append(20.0)
        elif result.band == "strong":
            hard_constraints.append(f"unverified_role_lane:{result.label}")
            role_scores.append(35.0)
        elif result.band == "partial":
            hard_constraints.append(f"unverified_role_lane:{result.label}")
            role_scores.append(25.0)
        else:
            hard_constraints.append(f"missing_role_evidence:{result.label}")
            role_scores.append(20.0)
    return round(sum(role_scores) / len(role_scores), 1), hard_constraints


def _skill_graph_score(
    requirements: list[Requirement],
    resume_text: str,
    candidate_profile: dict[str, Any] | None,
    job: SampleJob,
) -> float:
    candidate_skills = _candidate_skill_set(resume_text, candidate_profile)
    job_skills = {
        req.label
        for req in requirements
        if req.category == "skill" and req.label in SKILL_ALIASES
    }
    if not job_skills:
        job_skills = _canonical_skills_from_text(f"{job.title}\n{job.description}")
    if not job_skills:
        return 50.0

    direct = len(candidate_skills & job_skills)
    expanded = len(_expanded_skills(candidate_skills) & job_skills) - direct
    score = ((direct + 0.55 * max(0, expanded)) / len(job_skills)) * 100.0
    return round(min(score, 100.0), 1)


def _semantic_score(
    requirements: list[Requirement],
    chunks: list[EvidenceChunk],
) -> float:
    if not requirements or not chunks:
        return 0.0
    query = " ".join(req.query for req in requirements)
    chunk_blob = " ".join(chunk.text for chunk in chunks)
    query_tokens = _tokens(query) - GENERIC_ROLE_TERMS
    chunk_tokens = _tokens(chunk_blob)
    overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
    fuzzy = fuzz.token_set_ratio(_normalize(query), _normalize(chunk_blob)) / 100.0
    return round(min(100.0, max(overlap * 100.0, fuzzy * 70.0)), 1)


def _location_score(job: SampleJob, candidate_profile: dict[str, Any] | None) -> float:
    preferred = _preferred_locations(candidate_profile)
    if not preferred:
        return 50.0
    job_location = _normalize(job.location or "")
    if not job_location:
        return 45.0
    if "remote" in job_location and any("remote" in item for item in preferred):
        return 100.0
    if any(
        item and item in job_location for item in preferred if item != "remote only"
    ):
        return 100.0
    if (
        "india" in job_location
        or job_location.endswith(", in")
        or job_location.endswith(" in")
    ):
        return 70.0
    return 25.0


def synthesize_hybrid_score(
    requirements: list[Requirement],
    results: list[RequirementResult],
    chunks: list[EvidenceChunk],
    resume_text: str,
    candidate_profile: dict[str, Any] | None,
    job: SampleJob,
) -> MatchFactors:
    role_score, hard_constraints = _role_score(results, candidate_profile)
    evidence_score = _evidence_score(results)
    skill_score = _skill_graph_score(requirements, resume_text, candidate_profile, job)
    semantic_score = _semantic_score(requirements, chunks)
    location_score = _location_score(job, candidate_profile)
    constraint_score = 0.0 if hard_constraints else 100.0
    final_score = round(
        0.28 * role_score
        + 0.27 * evidence_score
        + 0.22 * skill_score
        + 0.10 * semantic_score
        + 0.08 * location_score
        + 0.05 * constraint_score,
        1,
    )
    if hard_constraints:
        final_score = round(min(final_score, 34.0), 1)
    if final_score >= 75:
        band = "strong_fit"
    elif final_score >= 55:
        band = "adjacent_fit"
    elif final_score >= 35:
        band = "weak_fit"
    else:
        band = "reject"
    return MatchFactors(
        role_score=role_score,
        evidence_score=evidence_score,
        skill_score=skill_score,
        semantic_score=semantic_score,
        location_score=location_score,
        constraint_score=constraint_score,
        final_score=final_score,
        band=band,
        hard_constraints=hard_constraints,
    )


async def _select_jobs(
    email: str,
    *,
    good_count: int,
    bad_count: int,
    min_description_chars: int,
) -> tuple[Profile, list[SampleJob]]:
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
        good_rows = (
            await db.execute(
                base_stmt.where(JobResult.archived_by_llm.is_not(True))
                .order_by(desc(JobResult.final_score), JobRaw.title)
                .limit(good_count)
            )
        ).all()
        bad_rows = (
            await db.execute(
                base_stmt.order_by(asc(JobResult.final_score), JobRaw.title).limit(
                    bad_count
                )
            )
        ).all()

    def make_sample(expected: str, row: tuple[JobResult, JobRaw]) -> SampleJob:
        jr, job = row
        return SampleJob(
            expected=expected,
            current_score=round(float(jr.final_score or 0.0), 2),
            current_fit_band=jr.fit_band,
            title=str(job.title or ""),
            company=str(job.company or ""),
            location=str(job.location or "") or None,
            job_url=str(job.job_url or ""),
            description=str(job.description or ""),
        )

    samples = [make_sample("good", row) for row in good_rows]
    samples.extend(make_sample("bad", row) for row in bad_rows)
    return profile, samples


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hybrid Evidence Match Sample Evaluation",
        "",
        f"- email: `{report['email']}`",
        f"- generated_at: `{report['generated_at']}`",
        f"- samples: `{len(report['samples'])}`",
        f"- resume_chunks: `{report['resume_chunk_count']}`",
        "",
        "| Expected | Hybrid band | Hybrid score | Evidence | Skill graph | Role | Current score | Job |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for sample in report["samples"]:
        factors = sample["factors"]
        lines.append(
            "| {expected} | {hybrid_band} | {hybrid_score:.1f} | {evidence:.1f} | {skill:.1f} | {role:.1f} | {current_score:.2f} | {job} |".format(
                expected=sample["expected"],
                hybrid_band=sample["hybrid_band"],
                hybrid_score=sample["hybrid_score"],
                evidence=factors["evidence_score"],
                skill=factors["skill_score"],
                role=factors["role_score"],
                current_score=sample["current_score"],
                job=f"{sample['title']} / {sample['company']}",
            )
        )
    lines.append("")
    for sample in report["samples"]:
        lines.extend(
            [
                f"## {sample['expected'].upper()}: {sample['title']} / {sample['company']}",
                "",
                f"- current_score: `{sample['current_score']}`",
                f"- current_fit_band: `{sample['current_fit_band']}`",
                f"- hybrid_score: `{sample['hybrid_score']}`",
                f"- hybrid_band: `{sample['hybrid_band']}`",
                f"- factor_scores: `{sample['factors']}`",
                f"- hard_constraints: `{sample['hard_constraints']}`",
                f"- url: {sample['job_url']}",
                "",
                "| Requirement | Band | Evidence |",
                "|---|---|---|",
            ]
        )
        for result in sample["requirements"]:
            evidence = "; ".join(
                f"{item['source']}: {item['text']}" for item in result["evidence"][:2]
            )
            lines.append(
                f"| {result['label']} | {result['band']} | {evidence or '-'} |"
            )
        lines.append("")
    return "\n".join(lines)


async def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    profile, samples = await _select_jobs(
        args.email,
        good_count=args.good_count,
        bad_count=args.bad_count,
        min_description_chars=args.min_description_chars,
    )
    chunks = _resume_chunks(profile.resume_text or "", profile.candidate_profile or {})
    rendered_samples: list[dict[str, Any]] = []
    for sample in samples:
        requirements = extract_requirements(sample)
        requirement_results = evaluate_requirements(requirements, chunks)
        legacy_rag_score, legacy_rag_band = synthesize_score(requirement_results)
        factors = synthesize_hybrid_score(
            requirements,
            requirement_results,
            chunks,
            profile.resume_text or "",
            profile.candidate_profile or {},
            sample,
        )
        counts = {
            "strong": sum(1 for item in requirement_results if item.band == "strong"),
            "partial": sum(1 for item in requirement_results if item.band == "partial"),
            "missing": sum(1 for item in requirement_results if item.band == "missing"),
        }
        rendered_samples.append(
            {
                **asdict(sample),
                "description": "",
                "rag_score": legacy_rag_score,
                "rag_band": legacy_rag_band,
                "hybrid_score": factors.final_score,
                "hybrid_band": factors.band,
                "factors": {
                    key: value
                    for key, value in asdict(factors).items()
                    if key not in {"band", "hard_constraints"}
                },
                "hard_constraints": factors.hard_constraints,
                "coverage_counts": counts,
                "requirements": [
                    {
                        **asdict(result),
                        "evidence": [asdict(item) for item in result.evidence],
                    }
                    for result in requirement_results
                ],
            }
        )
    return {
        "email": args.email,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "good_count": args.good_count,
            "bad_count": args.bad_count,
            "min_description_chars": args.min_description_chars,
        },
        "profile": {
            "role_intent": profile.role_intent,
            "target_roles": profile.target_roles,
            "preferred_locations": profile.preferred_locations,
            "candidate_profile_summary": {
                key: (profile.candidate_profile or {}).get(key)
                for key in (
                    "target_roles_primary",
                    "target_roles_adjacent",
                    "must_have_skills",
                    "good_to_have_skills",
                    "domains",
                    "negative_roles",
                    "seniority_band",
                )
            },
        },
        "resume_chunk_count": len(chunks),
        "samples": rendered_samples,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG-style resume-to-JD matching on DB samples"
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--good-count", type=int, default=3)
    parser.add_argument("--bad-count", type=int, default=3)
    parser.add_argument("--min-description-chars", type=int, default=800)
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
            {"output_dir": str(out_dir), "samples": len(report["samples"])}, indent=2
        )
    )
    await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
