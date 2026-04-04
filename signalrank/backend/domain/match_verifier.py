from __future__ import annotations

import json
from typing import Any

from domain.artifact_versions import (
    MATCH_VERIFIER_PROMPT_VERSION,
    SCHEMA_VERSION,
    VERIFICATION_REPORT_VERSION,
    verification_report_cache_key,
)
from domain.match_judge import _build_prompt as _build_judge_prompt


VERIFICATION_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_grounded": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "final_confidence_adjustment": {"type": "number"},
        "status": {"type": "string", "enum": ["pass", "needs_review"]},
        "artifact_version": {"type": "string"},
        "schema_version": {"type": "integer"},
        "prompt_version": {"type": "string"},
        "verification_cache_key": {"type": "string"},
    },
    "required": ["evidence_grounded", "unsupported_claims", "final_confidence_adjustment", "status"],
    "additionalProperties": False,
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _bounded_adjustment(value: float) -> float:
    return max(-0.35, min(value, 0.05))


def heuristic_verification_report(
    *,
    match_report: dict,
    candidate_profile: dict,
    job_profile: dict,
) -> dict:
    verdict = _norm(match_report.get("verdict")).lower()
    skill_evidence_present = bool(match_report.get("skill_evidence_present"))
    cited_resume_evidence = match_report.get("cited_resume_evidence") or []
    cited_job_evidence = match_report.get("cited_job_evidence") or []
    risk_flags = [str(item).lower() for item in match_report.get("risk_flags", []) if str(item).strip()]
    unsupported_claims: list[str] = []
    adjustment = 0.0

    if verdict in {"strong_fit", "adjacent_fit"} and not skill_evidence_present:
        unsupported_claims.append("judge overstated skill coverage")
        adjustment -= 0.2
    if verdict in {"strong_fit", "adjacent_fit"} and (not cited_resume_evidence or not cited_job_evidence):
        unsupported_claims.append("judge lacks grounded resume and job evidence")
        adjustment -= 0.15
    if verdict == "strong_fit" and "skill_gap" in risk_flags:
        unsupported_claims.append("judge ignored the listed skill gaps")
        adjustment -= 0.12
    if verdict == "strong_fit" and "location_mismatch" in risk_flags:
        unsupported_claims.append("judge overstated location fit")
        adjustment -= 0.15
    if verdict == "strong_fit" and "negative_role" in risk_flags:
        unsupported_claims.append("judge ignored explicit negative-role signals")
        adjustment -= 0.2
    if verdict == "misleading_fit":
        unsupported_claims.append("title similarity may be misleading without deeper alignment")
        adjustment -= 0.1
    if verdict == "reject":
        adjustment -= 0.05

    job_quality = float(job_profile.get("description_quality") or 0.0)
    if job_quality < 0.8:
        unsupported_claims.append("job description quality is weak")
        adjustment -= 0.05

    evidence_grounded = not unsupported_claims
    status = "pass" if evidence_grounded else "needs_review"
    candidate_fp = str(candidate_profile.get("profile_fingerprint") or candidate_profile.get("profile_cache_key") or "")
    job_fp = str(job_profile.get("job_fingerprint") or job_profile.get("job_cache_key") or "")
    return {
        "artifact_version": VERIFICATION_REPORT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": MATCH_VERIFIER_PROMPT_VERSION,
        "verification_cache_key": verification_report_cache_key(
            candidate_profile_fingerprint=candidate_fp,
            job_profile_fingerprint=job_fp,
            verifier_model_version="heuristic",
            prompt_version=MATCH_VERIFIER_PROMPT_VERSION,
        ),
        "evidence_grounded": evidence_grounded,
        "unsupported_claims": unsupported_claims,
        "final_confidence_adjustment": _bounded_adjustment(adjustment),
        "status": status,
    }


def _build_prompt(match_report: dict, candidate_profile: dict, job_profile: dict) -> tuple[str, str]:
    system = (
        "You verify a prior match judgment. Return a single JSON object only, with no markdown, no prose, and no code fences. "
        "Be strict about grounding: challenge title-only matches, generic engineering overlap, "
        "and unsupported skill claims. Reduce confidence when the cited evidence does not clearly support the verdict."
    )
    user = json.dumps(
        {
            "match_report": match_report,
            "candidate_profile": candidate_profile,
            "job_profile": job_profile,
            "instructions": [
                "Check whether the cited resume and JD evidence really supports the verdict.",
                "Downgrade judgments that rely mostly on title similarity without JD responsibility or skill alignment.",
                "Treat missing grounded evidence from either side as a verification problem.",
                "Flag unsupported claims or overconfident reasoning.",
                "Return pass only when the judgment is well grounded.",
                "Do not invent new evidence; only assess the provided match report and cited snippets.",
            ],
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return system, user


def _normalize(report: dict, fallback: dict) -> dict:
    output = dict(fallback)
    if not isinstance(report, dict):
        return output

    output["evidence_grounded"] = bool(report.get("evidence_grounded", output["evidence_grounded"]))
    if isinstance(report.get("unsupported_claims"), list):
        output["unsupported_claims"] = [str(item).strip() for item in report["unsupported_claims"] if str(item).strip()]
    try:
        output["final_confidence_adjustment"] = _bounded_adjustment(float(report.get("final_confidence_adjustment", output["final_confidence_adjustment"])))
    except (TypeError, ValueError):
        pass
    status = _norm(report.get("status")).lower()
    if status in {"pass", "needs_review"}:
        output["status"] = status
    return output


async def verify_match_report(
    *,
    match_report: dict,
    candidate_profile: dict,
    job_profile: dict,
    llm_client=None,
    max_tokens: int = 700,
) -> dict:
    fallback = heuristic_verification_report(
        match_report=match_report,
        candidate_profile=candidate_profile,
        job_profile=job_profile,
    )
    if llm_client is None:
        return fallback

    system, user = _build_prompt(match_report, candidate_profile, job_profile)
    try:
        response = await llm_client.llm_json(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=0.0,
            json_schema=VERIFICATION_REPORT_SCHEMA,
            schema_name="verification_report",
        )
    except Exception:
        return fallback

    if not isinstance(response, dict) or response.get("_error"):
        return fallback

    return _normalize(response, fallback)
