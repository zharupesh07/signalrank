from __future__ import annotations

import asyncio
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from api.config import settings
from api.models import Profile
from api.routes.onboarding import _apply_parsed_profile_updates, _extract_text_from_pdf
from domain.career_intent import build_career_intent_profile
import llm.openrouter as openrouter_mod
from llm.openrouter import OpenRouterClient
from llm.resume_parser import ResumeParseResult, parse_resume


ROOT = Path(__file__).resolve().parents[3]
RESUME_DIR = ROOT / "resumes"


@dataclass
class ResumeCase:
    name: str
    pdf_name: str
    expected_roles: list[str]
    forbidden_terms: list[str]


CASES = [
    ResumeCase(
        name="abhijeet",
        pdf_name="Abhijeet_CV.pdf",
        expected_roles=["AI/Machine Learning Engineer", "Machine Learning Engineer", "Data Scientist"],
        forbidden_terms=["QA", "SAP", "Network Automation"],
    ),
    ResumeCase(
        name="example",
        pdf_name="Example_Candidate_Resume_V2_2.pdf",
        expected_roles=["AI Platform Engineer", "MLOps Engineer", "Platform Engineer"],
        forbidden_terms=["QA", "SAP", "Test Automation"],
    ),
    ResumeCase(
        name="vivek",
        pdf_name="Vivek-Gupta-Emerging-Technologies.pdf",
        expected_roles=["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"],
        forbidden_terms=["QA", "SAP"],
    ),
    ResumeCase(
        name="aditya",
        pdf_name="aditya.pdf",
        expected_roles=["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Infrastructure Engineer"],
        forbidden_terms=["QA", "SAP", "Data Scientist"],
    ),
    ResumeCase(
        name="ayush",
        pdf_name="ayush_resume_new.pdf",
        expected_roles=["SAP SD Consultant", "SAP OTC Functional Consultant"],
        forbidden_terms=["QA", "Test Automation", "SDET"],
    ),
]


VARIANT_SCHEMA = {
    "type": "object",
    "properties": {
        "career_archetypes": {"type": "array", "items": {"type": "string"}},
        "target_roles": {"type": "array", "items": {"type": "string"}},
        "negative_targets": {"type": "array", "items": {"type": "string"}},
        "query_titles": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["career_archetypes", "target_roles", "negative_targets", "query_titles", "reasoning"],
    "additionalProperties": False,
}


PROMPT_VARIANTS: dict[str, tuple[str, str]] = {
    "competitor_a_open_identity": (
        "You are an expert career coach. Infer the candidate's actual target job family from the resume. "
        "Do not map them to a generic software role unless the resume is truly generic. Prefer specificity over popularity.",
        """Read the resume and return JSON.

Identify:
- career_archetypes: broad career lanes
- target_roles: the best concrete job titles for job search
- negative_targets: lookalike roles that would be wrong
- query_titles: alternate search titles

Rules:
- No preset taxonomy.
- Use the candidate's real specialization.
- Avoid trendy AI/ML labels unless strongly supported.
- If "automation" means ERP or network automation, do not interpret it as QA.

Resume:
{resume_text}""",
    ),
    "competitor_b_evidence_first": (
        "You are an expert recruiter and career strategist. Extract only role conclusions that are directly supported by resume evidence.",
        """Return JSON only.

Think in this order:
1. What functional identity does this person have?
2. What adjacent identities are valid?
3. What misleading identities should be excluded?

Rules:
- Every target role must be evidence-backed.
- Do not collapse specialists into generic engineer labels.
- Include negative_targets aggressively when false positives are likely.
- Preserve non-standard careers like ERP functional consulting, innovation/R&D, and network automation.

Resume:
{resume_text}""",
    ),
    "competitor_c_search_planner": (
        "You design job-search strategies for technical and business candidates. Your goal is retrieval precision, not generic resume summarization.",
        """Return JSON only.

Produce the best role search plan for this candidate.

Rules:
- target_roles should be the most precise search titles.
- query_titles should expand recall without drifting into a different career.
- negative_targets should block likely false-positive categories.
- When a resume is ambiguous, stay close to the specialized evidence instead of broadening to generic SWE.

Resume:
{resume_text}""",
    ),
}


def _load_resume_text(case: ResumeCase) -> str:
    content = (RESUME_DIR / case.pdf_name).read_bytes()
    return _extract_text_from_pdf(content)


def _contains_forbidden(values: list[str], forbidden_terms: list[str]) -> list[str]:
    joined = " | ".join(values).lower()
    hits: list[str] = []
    for term in forbidden_terms:
        if term.lower() in joined:
            hits.append(term)
    return hits


def _score_output(values: list[str], case: ResumeCase) -> dict:
    expected_hit = any(
        expected.lower() in " | ".join(values).lower()
        for expected in case.expected_roles
    )
    forbidden_hits = _contains_forbidden(values, case.forbidden_terms)
    return {
        "expected_hit": expected_hit,
        "forbidden_hits": forbidden_hits,
        "pass": expected_hit and not forbidden_hits,
    }


async def _run_baseline(client: OpenRouterClient, resume_text: str) -> dict:
    parsed = await parse_resume(resume_text, client)
    profile = Profile(user_id="eval")
    _apply_parsed_profile_updates(profile, parsed)
    career_intent = (profile.config_overrides or {}).get("career_intent") or build_career_intent_profile(parsed)
    values = list(profile.target_roles or [])
    values.extend((profile.custom_search_queries or [])[:3])
    return {
        "target_roles": list(profile.target_roles or []),
        "negative_targets": list((profile.config_overrides or {}).get("title_blocklist") or []),
        "query_titles": list(profile.custom_search_queries or []),
        "career_archetypes": [item.get("id") for item in career_intent.get("career_archetypes", [])],
        "combined_values": values,
    }


async def _run_variant(client: OpenRouterClient, variant_name: str, resume_text: str) -> dict:
    system, user_template = PROMPT_VARIANTS[variant_name]
    payload = await client.llm_json(
        system=system,
        user=user_template.format(resume_text=resume_text[:12000]),
        json_schema=VARIANT_SCHEMA,
        schema_name=f"prompt_variant_{variant_name}",
        max_tokens=1200,
        temperature=0.0,
    )
    target_roles = [str(x).strip() for x in payload.get("target_roles", []) if str(x).strip()]
    negative_targets = [str(x).strip() for x in payload.get("negative_targets", []) if str(x).strip()]
    query_titles = [str(x).strip() for x in payload.get("query_titles", []) if str(x).strip()]
    archetypes = [str(x).strip() for x in payload.get("career_archetypes", []) if str(x).strip()]
    combined = target_roles + query_titles[:3]
    return {
        "target_roles": target_roles,
        "negative_targets": negative_targets,
        "query_titles": query_titles,
        "career_archetypes": archetypes,
        "reasoning": payload.get("reasoning"),
        "combined_values": combined,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()
    client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        timeout=60.0,
    )
    probe_key = tuple(client.models)
    openrouter_mod._probe_cache[probe_key] = list(client.models)
    openrouter_mod._probe_cache_at[probe_key] = openrouter_mod._time.monotonic()
    report: dict[str, dict] = {}

    selected = [case for case in CASES if not args.cases or case.name in set(args.cases)]

    for case in selected:
        resume_text = _load_resume_text(case)
        case_report: dict[str, dict] = {}

        baseline = await _run_baseline(client, resume_text)
        baseline_eval = _score_output(baseline["combined_values"], case)
        case_report["baseline_with_role_taxonomy"] = {
            **baseline,
            "evaluation": baseline_eval,
        }

        for variant_name in PROMPT_VARIANTS:
            result = await _run_variant(client, variant_name, resume_text)
            result_eval = _score_output(result["combined_values"], case)
            case_report[variant_name] = {
                **result,
                "evaluation": result_eval,
            }

        report[case.name] = case_report

    summary: dict[str, dict] = {}
    for variant in ["baseline_with_role_taxonomy", *PROMPT_VARIANTS.keys()]:
        passed = 0
        total_forbidden_hits = 0
        for case in selected:
            evaluation = report[case.name][variant]["evaluation"]
            if evaluation["pass"]:
                passed += 1
            total_forbidden_hits += len(evaluation["forbidden_hits"])
        summary[variant] = {
            "passes": passed,
            "cases": len(selected),
            "forbidden_hits": total_forbidden_hits,
        }

    print(json.dumps({"summary": summary, "report": report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
