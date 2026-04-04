from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from domain.artifact_versions import (
    MATCH_JUDGE_PROMPT_VERSION,
    MATCH_REPORT_VERSION,
    SCHEMA_VERSION,
    match_report_cache_key,
)
from domain.score_synthesis import fit_band_from_verdict


MATCH_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["strong_fit", "adjacent_fit", "weak_fit", "misleading_fit", "reject"],
        },
        "target_lane_fit": {"type": "string"},
        "skill_evidence_present": {"type": "boolean"},
        "skill_gaps": {"type": "array", "items": {"type": "string"}},
        "seniority_fit": {"type": "string"},
        "location_fit": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "why_rank_up": {"type": "array", "items": {"type": "string"}},
        "why_rank_down": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "cited_resume_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["source", "text"],
                "additionalProperties": False,
            },
        },
        "cited_job_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["source", "text"],
                "additionalProperties": False,
            },
        },
        "explanation_summary": {"type": "string"},
        "artifact_version": {"type": "string"},
        "schema_version": {"type": "integer"},
        "prompt_version": {"type": "string"},
        "match_cache_key": {"type": "string"},
    },
    "required": [
        "verdict",
        "target_lane_fit",
        "skill_evidence_present",
        "skill_gaps",
        "seniority_fit",
        "location_fit",
        "risk_flags",
        "why_rank_up",
        "why_rank_down",
        "confidence",
        "cited_resume_evidence",
        "cited_job_evidence",
        "explanation_summary",
    ],
    "additionalProperties": False,
}


def _dedupe(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _evidence_list(items: Any, *, limit: int = 3) -> list[dict]:
    if not isinstance(items, list):
        return []
    evidence: list[dict] = []
    for item in items[:limit]:
        if isinstance(item, dict):
            source = _norm(item.get("source")) or "unknown"
            text = _norm(item.get("text"))
            if text:
                evidence.append({"source": source, "text": text[:240]})
        else:
            text = _norm(item)
            if text:
                evidence.append({"source": "unknown", "text": text[:240]})
    return evidence


def _short_text(text: str, limit: int = 240) -> str:
    text = _norm(text)
    return text[:limit]


def _band_to_order(band: str | None) -> int:
    order = {
        "junior": 0,
        "mid": 1,
        "senior": 2,
        "staff": 3,
        "principal": 4,
    }
    return order.get((band or "").lower(), 1)


def _candidate_role_blob(candidate_profile: dict) -> str:
    parts: list[str] = []
    for key in ("target_roles_primary", "target_roles_adjacent", "negative_roles", "domains", "career_archetypes"):
        value = candidate_profile.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts).lower()


def _job_role_blob(job_profile: dict) -> str:
    parts: list[str] = []
    for key in ("role_family", "domain", "seniority_band", "work_mode", "location_normalized"):
        value = job_profile.get(key)
        if value:
            parts.append(str(value))
    for key in ("role_titles_normalized", "required_skills", "preferred_skills", "must_have_constraints", "red_flags"):
        value = job_profile.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts).lower()


def _location_fit(candidate_profile: dict, job_profile: dict) -> tuple[str, bool, list[str]]:
    preferred_locations = {str(loc).lower() for loc in candidate_profile.get("preferred_locations", []) if str(loc).strip()}
    preferred_modes = {str(mode).lower() for mode in candidate_profile.get("preferred_work_modes", []) if str(mode).strip()}
    job_location = _norm(job_profile.get("location_normalized") or job_profile.get("location"))
    job_mode = _norm(job_profile.get("work_mode") or "").lower()
    location_text = job_location.lower()
    fit = "unclear"
    reasons: list[str] = []

    if "remote" in preferred_modes and job_mode == "remote":
        fit = "aligned"
        reasons.append("job is remote and candidate is open to remote")
    elif preferred_locations and any(loc and loc in location_text for loc in preferred_locations):
        fit = "aligned"
        reasons.append("job location matches candidate preference")
    elif job_mode == "remote":
        fit = "remote_ok"
        reasons.append("job is remote")
    elif preferred_modes == {"remote"} and job_mode in {"onsite", "hybrid"}:
        fit = "mismatch"
        reasons.append("candidate prefers remote-only")
    elif job_mode == "onsite" and "remote only" in preferred_locations:
        fit = "mismatch"
        reasons.append("candidate prefers remote-only")
    elif job_mode == "hybrid" and "remote only" in preferred_locations:
        fit = "mismatch"
        reasons.append("candidate prefers remote-only")

    return fit, fit == "mismatch", reasons


def _seniority_fit(candidate_profile: dict, job_profile: dict) -> tuple[str, list[str]]:
    candidate_band = _norm(candidate_profile.get("seniority_band")).lower()
    job_band = _norm(job_profile.get("seniority_band")).lower()
    candidate_order = _band_to_order(candidate_band)
    job_order = _band_to_order(job_band)
    reasons: list[str] = []

    if candidate_band == job_band:
        return "aligned", reasons
    if candidate_order <= 1 and job_order >= 3:
        reasons.append("job appears too senior for the candidate")
        return "underqualified", reasons
    if candidate_order >= 3 and job_order == 0:
        reasons.append("job appears too junior for the candidate")
        return "overqualified", reasons
    if abs(candidate_order - job_order) == 1:
        return "adjacent", reasons
    return "unclear", reasons


def _skill_signals(candidate_profile: dict, job_profile: dict) -> tuple[bool, list[str], list[str], list[str]]:
    candidate_skills = {
        _norm(skill).lower()
        for key in ("must_have_skills", "good_to_have_skills")
        for skill in candidate_profile.get(key, [])
        if _norm(skill)
    }
    job_required = {_norm(skill).lower() for skill in job_profile.get("required_skills", []) if _norm(skill)}
    job_preferred = {_norm(skill).lower() for skill in job_profile.get("preferred_skills", []) if _norm(skill)}
    overlap = sorted((candidate_skills & job_required) | (candidate_skills & job_preferred))
    missing = sorted((job_required - candidate_skills))[:8]
    extra = sorted(candidate_skills & job_preferred)[:8]
    return bool(overlap), overlap[:8], missing, extra


def _negative_role_hit(candidate_profile: dict, job_profile: dict) -> str | None:
    blob = _candidate_role_blob(candidate_profile)
    job_blob = _job_role_blob(job_profile)
    for role in candidate_profile.get("negative_roles", []) or []:
        term = _norm(role).lower()
        if term and term in job_blob:
            return _norm(role)
    if any(term in job_blob for term in ("qa", "support", "helpdesk")) and any(term in blob for term in ("platform", "ml", "engineer", "backend")):
        return "negative role family overlap"
    return None


def heuristic_match_report(
    *,
    candidate_profile: dict,
    job_profile: dict,
    resume_text: str,
    job_text: str,
) -> dict:
    candidate_blob = _candidate_role_blob(candidate_profile)
    job_blob = _job_role_blob(job_profile)
    title_blob = _norm(job_profile.get("role_titles_normalized", [])[:3]).lower()
    job_text_blob = f"{job_blob} {job_text}".lower()

    negative_hit = _negative_role_hit(candidate_profile, job_profile)
    skill_present, matched_skills, skill_gaps, skill_extras = _skill_signals(candidate_profile, job_profile)
    location_fit, location_mismatch, location_reasons = _location_fit(candidate_profile, job_profile)
    seniority_fit, seniority_reasons = _seniority_fit(candidate_profile, job_profile)

    direct_role_hit = any(
        term in job_text_blob
        for term in (
            "engineer",
            "consultant",
            "architect",
            "developer",
            "scientist",
            "sre",
            "platform",
            "sap",
            "ml",
            "qa",
        )
    ) and any(
        term in candidate_blob
        for term in (
            "engineer",
            "consultant",
            "architect",
            "developer",
            "scientist",
            "platform",
            "ml",
            "sap",
            "qa",
        )
    )
    adjacent_role_hit = any(term in job_blob for term in candidate_profile.get("target_roles_adjacent", []))

    why_rank_up: list[str] = []
    why_rank_down: list[str] = []
    risk_flags: list[str] = []

    if matched_skills:
        why_rank_up.append(f"shares skills: {', '.join(matched_skills[:3])}")
    if direct_role_hit:
        why_rank_up.append("role family looks aligned")
    if location_fit in {"aligned", "remote_ok"}:
        why_rank_up.append(location_reasons[0] if location_reasons else "location is acceptable")
    if seniority_fit in {"aligned", "adjacent"}:
        why_rank_up.append(f"seniority is {seniority_fit}")

    if skill_gaps:
        why_rank_down.append(f"missing core skills: {', '.join(skill_gaps[:3])}")
        risk_flags.append("skill_gap")
    if negative_hit:
        why_rank_down.append(f"negative-role signal: {negative_hit}")
        risk_flags.append("negative_role")
    if location_mismatch:
        why_rank_down.append(location_reasons[0] if location_reasons else "location mismatch")
        risk_flags.append("location_mismatch")
    if seniority_fit in {"underqualified", "overqualified"}:
        why_rank_down.append(seniority_reasons[0] if seniority_reasons else "seniority mismatch")
        risk_flags.append("seniority_mismatch")
    if not skill_present:
        risk_flags.append("weak_skill_evidence")

    if negative_hit or location_mismatch:
        verdict = "reject" if not direct_role_hit else "misleading_fit"
    elif direct_role_hit and skill_present and seniority_fit in {"aligned", "adjacent", "unclear"} and location_fit in {"aligned", "remote_ok", "unclear"}:
        verdict = "strong_fit"
    elif (direct_role_hit or adjacent_role_hit) and skill_present:
        verdict = "adjacent_fit"
    elif skill_present or direct_role_hit:
        verdict = "weak_fit"
    else:
        verdict = "reject"

    confidence = 0.42
    confidence += 0.16 if skill_present else 0.0
    confidence += 0.14 if direct_role_hit else 0.04
    confidence += 0.08 if location_fit in {"aligned", "remote_ok"} else 0.0
    confidence += 0.08 if seniority_fit in {"aligned", "adjacent"} else 0.0
    confidence -= 0.12 if negative_hit else 0.0
    confidence -= 0.10 if location_mismatch else 0.0
    confidence = max(0.05, min(confidence, 0.98))

    cited_resume_evidence = _evidence_list(candidate_profile.get("evidence_snippets"), limit=3)
    if not cited_resume_evidence and resume_text:
        cited_resume_evidence = [{"source": "resume_text", "text": _short_text(resume_text)}]
    cited_job_evidence = _evidence_list(job_profile.get("evidence_snippets"), limit=3)
    if not cited_job_evidence and job_text:
        cited_job_evidence = [{"source": "job_description", "text": _short_text(job_text)}]
    candidate_fp = str(candidate_profile.get("profile_fingerprint") or candidate_profile.get("profile_cache_key") or "")
    job_fp = str(job_profile.get("job_fingerprint") or job_profile.get("job_cache_key") or "")

    explanation_parts = [
        f"verdict={verdict}",
        f"skills={', '.join(matched_skills[:3]) or 'none'}",
        f"seniority={seniority_fit}",
        f"location={location_fit}",
    ]
    if negative_hit:
        explanation_parts.append(f"negative={negative_hit}")
    explanation_summary = "; ".join(explanation_parts)

    return {
        "artifact_version": MATCH_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_JUDGE_PROMPT_VERSION,
        "match_cache_key": match_report_cache_key(
            candidate_profile_fingerprint=candidate_fp,
            job_profile_fingerprint=job_fp,
            judge_model_version="heuristic",
            prompt_version=MATCH_JUDGE_PROMPT_VERSION,
        ),
        "verdict": verdict,
        "target_lane_fit": "direct" if verdict == "strong_fit" else "adjacent" if verdict == "adjacent_fit" else "misleading" if verdict == "misleading_fit" else "weak",
        "skill_evidence_present": skill_present,
        "skill_gaps": skill_gaps,
        "seniority_fit": seniority_fit,
        "location_fit": location_fit,
        "risk_flags": _dedupe(risk_flags),
        "why_rank_up": _dedupe(why_rank_up)[:5],
        "why_rank_down": _dedupe(why_rank_down)[:5],
        "confidence": round(confidence, 3),
        "cited_resume_evidence": cited_resume_evidence[:4],
        "cited_job_evidence": cited_job_evidence[:4],
        "explanation_summary": explanation_summary,
    }


def _build_prompt(candidate_profile: dict, job_profile: dict, resume_text: str, job_text: str) -> tuple[str, str]:
    system = (
        "You evaluate one candidate-job pair for job ranking. "
        "Return JSON only. Be evidence-first, conservative, and skeptical of title-only similarity. "
        "A strong_fit requires grounded evidence from both the resume and the job description. "
        "If the title looks relevant but the responsibilities, process area, or required skills do not line up, "
        "downgrade to weak_fit, misleading_fit, or reject."
    )
    user = json.dumps(
        {
            "candidate_profile": candidate_profile,
            "job_profile": job_profile,
            "resume_excerpt": _short_text(resume_text, 1800),
            "job_excerpt": _short_text(job_text, 2200),
            "instructions": [
                "Use only the provided structured artifacts, evidence snippets, and excerpts.",
                "Do not infer missing experience, certifications, or domain knowledge that are not explicitly shown.",
                "Title similarity alone cannot justify strong_fit or adjacent_fit.",
                "Judge whether the job is a strong_fit, adjacent_fit, weak_fit, misleading_fit, or reject.",
                "Prefer misleading_fit when the title sounds aligned but the JD evidence points to a different lane.",
                "List missing skills, process gaps, and risk flags explicitly.",
                "Cite grounded evidence from both the resume and the job description.",
                "Keep cited evidence short and exact; do not paraphrase unsupported claims into the evidence fields.",
            ],
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return system, user


def _normalize_match_report(report: dict, fallback: dict) -> dict:
    output = dict(fallback)
    if not isinstance(report, dict):
        return output

    verdict = _norm(report.get("verdict")).lower()
    if verdict in {"strong_fit", "adjacent_fit", "weak_fit", "misleading_fit", "reject"}:
        output["verdict"] = verdict

    target_lane_fit = _norm(report.get("target_lane_fit"))
    if target_lane_fit:
        output["target_lane_fit"] = target_lane_fit

    output["skill_evidence_present"] = bool(report.get("skill_evidence_present", output.get("skill_evidence_present", False)))
    output["skill_gaps"] = _dedupe(report.get("skill_gaps") if isinstance(report.get("skill_gaps"), list) else output.get("skill_gaps"))
    output["seniority_fit"] = _norm(report.get("seniority_fit")) or output.get("seniority_fit")
    output["location_fit"] = _norm(report.get("location_fit")) or output.get("location_fit")
    output["risk_flags"] = _dedupe(report.get("risk_flags") if isinstance(report.get("risk_flags"), list) else output.get("risk_flags"))
    output["why_rank_up"] = _dedupe(report.get("why_rank_up") if isinstance(report.get("why_rank_up"), list) else output.get("why_rank_up"))
    output["why_rank_down"] = _dedupe(report.get("why_rank_down") if isinstance(report.get("why_rank_down"), list) else output.get("why_rank_down"))
    try:
        confidence = float(report.get("confidence", output.get("confidence", 0.0)))
        output["confidence"] = max(0.0, min(confidence, 1.0))
    except (TypeError, ValueError):
        pass

    if isinstance(report.get("cited_resume_evidence"), list):
        output["cited_resume_evidence"] = _evidence_list(report["cited_resume_evidence"], limit=4)
    if isinstance(report.get("cited_job_evidence"), list):
        output["cited_job_evidence"] = _evidence_list(report["cited_job_evidence"], limit=4)

    summary = _norm(report.get("explanation_summary"))
    if summary:
        output["explanation_summary"] = summary
    return output


async def judge_match_report(
    *,
    candidate_profile: dict,
    job_profile: dict,
    resume_text: str,
    job_text: str,
    llm_client=None,
    max_tokens: int = 1200,
) -> dict:
    fallback = heuristic_match_report(
        candidate_profile=candidate_profile,
        job_profile=job_profile,
        resume_text=resume_text,
        job_text=job_text,
    )
    if llm_client is None:
        return fallback

    system, user = _build_prompt(candidate_profile, job_profile, resume_text, job_text)
    try:
        response = await llm_client.llm_json(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=0.0,
            json_schema=MATCH_REPORT_SCHEMA,
            schema_name="match_report",
        )
    except Exception:
        return fallback

    if not isinstance(response, dict) or response.get("_error"):
        return fallback

    return _normalize_match_report(response, fallback)
