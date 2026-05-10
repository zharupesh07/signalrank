from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from batch.query_builder import build_query_plan_debug
from domain.intent_matching import PROFILE_INTENT_KEY, build_profile_intent
from tools import build_profile_eval_sets

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "query_plan_eval"


def _intent_profile(
    *,
    name: str,
    target_roles: list[str],
    role_families: list[str],
    skills: list[str],
    confidence: float = 0.86,
) -> SimpleNamespace:
    candidate_profile = {
        "target_roles_primary": target_roles,
        "target_roles_adjacent": [],
        "negative_roles": [],
        "must_have_skills": skills,
        "good_to_have_skills": [],
        "domains": role_families,
        "seniority_band": "senior",
    }
    intent = build_profile_intent(
        candidate_profile,
        resume_text=" ".join([*target_roles, *skills, *role_families]),
    )
    intent["primary_role_families"] = role_families
    intent["role_families"] = role_families
    intent["confidence"] = confidence
    candidate_profile[PROFILE_INTENT_KEY] = intent
    return SimpleNamespace(
        name=name,
        target_roles=target_roles,
        preferred_locations=["Pune"],
        custom_search_queries=[],
        candidate_profile=candidate_profile,
        config_overrides={
            "scraping": {
                "intent_query_planner": {
                    "shadow_enabled": True,
                    "use_for_scrape": False,
                    "default_max_terms": 8,
                }
            }
        },
    )


def _synthetic_profiles() -> list[SimpleNamespace]:
    return [
        _intent_profile(
            name="synthetic_cybersecurity",
            target_roles=["Cybersecurity Engineer"],
            role_families=["cybersecurity"],
            skills=["zero trust", "IAM", "SIEM"],
        ),
        _intent_profile(
            name="synthetic_sap",
            target_roles=["SAP SD Consultant"],
            role_families=["sap_erp"],
            skills=["SAP SD", "S/4HANA", "ABAP"],
        ),
        _intent_profile(
            name="synthetic_frontend",
            target_roles=["Frontend Engineer"],
            role_families=["frontend"],
            skills=["React", "TypeScript"],
        ),
        _intent_profile(
            name="synthetic_ai_platform",
            target_roles=["AI Platform Engineer"],
            role_families=["ai_platform"],
            skills=["MLOps", "LLMOps", "Kubernetes"],
        ),
        _intent_profile(
            name="synthetic_network_automation",
            target_roles=["Network Automation Engineer"],
            role_families=["network_automation"],
            skills=["ServiceNow", "firewall", "routing"],
        ),
        _intent_profile(
            name="synthetic_unknown",
            target_roles=["Widget Orchestration Specialist"],
            role_families=["general"],
            skills=["Python", "Kubernetes"],
            confidence=0.5,
        ),
    ]


def _profile_from_gold_key(profile_key: str) -> SimpleNamespace:
    candidate_profile, _resume_text = build_profile_eval_sets.build_profile(profile_key)
    intent = candidate_profile.get(PROFILE_INTENT_KEY)
    target_roles = (
        list(intent.get("target_roles") or [])
        if isinstance(intent, dict)
        else list(candidate_profile.get("target_roles_primary") or [])
    )
    locations = list(candidate_profile.get("preferred_locations") or ["Pune"])
    return SimpleNamespace(
        name=profile_key,
        target_roles=target_roles,
        preferred_locations=locations,
        custom_search_queries=[],
        candidate_profile=candidate_profile,
        config_overrides={
            "scraping": {
                "intent_query_planner": {
                    "shadow_enabled": True,
                    "use_for_scrape": False,
                    "default_max_terms": 8,
                }
            }
        },
    )


def _gate_report(debug: dict[str, Any]) -> dict[str, Any]:
    accepted = debug.get("accepted_candidates") or []
    rejected = debug.get("rejected_candidates") or []
    person_specific_terms = [
        term
        for term in debug.get("intent_terms") or []
        if any(
            name in str(term).lower() for name in ("example", "vivek", "aditya", "ayush")
        )
    ]
    checks = {
        "planner_gates_pass": bool((debug.get("gates") or {}).get("passes")),
        "has_intent_terms": bool(debug.get("intent_terms")),
        "no_person_specific_terms": not person_specific_terms,
        "accepted_have_no_risk_flags": not any(
            item.get("risk_flags") for item in accepted
        ),
        "rejected_candidates_captured": isinstance(rejected, list),
    }
    return {
        "passes": all(checks.values()),
        "checks": checks,
        "person_specific_terms": person_specific_terms,
    }


def _render_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Query Plan Eval",
        "",
        f"- profiles: `{len(report['profiles'])}`",
        f"- passes: `{report['passes']}`",
        "",
        "| Profile | Passes | Current Terms | Intent Terms | Rejected | Risk Flags |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in report["profiles"]:
        counts = item["debug"].get("counts") or {}
        lines.append(
            "| {profile} | {passes} | {current_terms} | {intent_terms} | {rejected_candidates} | {risk_flags} |".format(
                profile=item["profile"],
                passes=item["gates"]["passes"],
                current_terms=counts.get("current_terms", 0),
                intent_terms=counts.get("intent_terms", 0),
                rejected_candidates=counts.get("rejected_candidates", 0),
                risk_flags=", ".join(item["debug"].get("risk_flags") or []),
            )
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate intent query plans")
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output-dir")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    profiles = [_profile_from_gold_key(profile) for profile in args.profile]
    if args.synthetic:
        profiles.extend(_synthetic_profiles())
    rows = []
    for profile in profiles:
        debug = build_query_plan_debug(profile)
        rows.append(
            {
                "profile": profile.name,
                "debug": debug,
                "gates": _gate_report(debug),
            }
        )
    report = {
        "passes": all(item["gates"]["passes"] for item in rows),
        "profiles": rows,
    }
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else DEFAULT_OUTPUT_DIR
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output_dir / "summary.md").write_text(_render_summary(report) + "\n")
    print(json.dumps({"output_dir": str(output_dir), "passes": report["passes"]}))
    if not report["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
