from __future__ import annotations

from typing import Any


_VERDICT_MULTIPLIERS = {
    "strong_fit": 1.08,
    "adjacent_fit": 1.00,
    "weak_fit": 0.92,
    "misleading_fit": 0.78,
    "reject": 0.55,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(value, hi))


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def fit_band_from_verdict(verdict: str | None) -> str:
    verdict = (verdict or "").strip().lower()
    return verdict if verdict in _VERDICT_MULTIPLIERS else "weak_fit"


def confidence_band_from_score(confidence: float | None) -> str:
    value = float(confidence or 0.0)
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def explanation_summary_for_report(
    match_report: dict | None,
    verification_report: dict | None,
) -> str:
    match_report = match_report or {}
    verification_report = verification_report or {}

    verdict = _norm_text(match_report.get("verdict")) or "weak_fit"
    target_lane_fit = _norm_text(match_report.get("target_lane_fit"))
    why_rank_up = match_report.get("why_rank_up") or []
    why_rank_down = match_report.get("why_rank_down") or []
    unsupported = verification_report.get("unsupported_claims") or []

    up = _norm_text(why_rank_up[0]) if isinstance(why_rank_up, list) and why_rank_up else ""
    down = _norm_text(why_rank_down[0]) if isinstance(why_rank_down, list) and why_rank_down else ""
    warn = _norm_text(unsupported[0]) if isinstance(unsupported, list) and unsupported else ""

    parts: list[str] = []
    parts.append(verdict.replace("_", " ").capitalize())
    if target_lane_fit:
        parts.append(f"lane: {target_lane_fit}")
    if up:
        parts.append(up)
    if down:
        parts.append(down)
    if warn:
        parts.append(f"Verifier: {warn}")
    return " | ".join(parts)


def synthesize_match_score(
    *,
    deterministic_score: float,
    match_report: dict | None,
    verification_report: dict | None,
) -> dict:
    match_report = match_report or {}
    verification_report = verification_report or {}

    verdict = fit_band_from_verdict(match_report.get("verdict"))
    base_multiplier = _VERDICT_MULTIPLIERS.get(verdict, _VERDICT_MULTIPLIERS["weak_fit"])

    verifier_adjustment = float(verification_report.get("final_confidence_adjustment") or 0.0)
    multiplier = base_multiplier + verifier_adjustment
    multiplier = max(0.45, min(multiplier, 1.15))

    confidence = float(match_report.get("confidence") or 0.0)
    confidence += verifier_adjustment
    confidence = max(0.0, min(confidence, 1.0))

    final_score = _clamp(float(deterministic_score) * multiplier)
    explanation_summary = explanation_summary_for_report(match_report, verification_report)

    return {
        "final_score": final_score,
        "fit_band": verdict,
        "confidence_band": confidence_band_from_score(confidence),
        "explanation_summary": explanation_summary,
        "agentic_multiplier": multiplier,
        "agentic_confidence": confidence,
    }
