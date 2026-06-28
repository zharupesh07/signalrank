"""Scoring smoke test — do real clock/STA jobs rise and noise sink?

Scrapes a small LinkedIn batch, then scores each job against a resume using
signalrank's OWN match judge (Anthropic), and prints results ranked by fit.
Proves the resume-matching stage works before we wire the full pipeline.

Prereqs (Codespace):
  export ANTHROPIC_API_KEY='sk-ant-...'
Run from backend/:
  python -m jobdigest.smoke_score
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import json

from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig
from batch.sources import jobspy_source
from domain.match_judge import judge_match_report
from llm.providers import build_llm_client

logging.basicConfig(level=logging.WARNING)

RESUME_JSON = "jobdigest/resumes/rtl.json"   # the RTL resume profile
TERMS = ["ASIC Design Engineer", "RTL Design Engineer", "Physical Design Engineer",
         "Digital Design Engineer", "CPU RTL Engineer", "GPU RTL Engineer",
         "Clock Design Engineer", "Timing Engineer"]

# fit_band -> sort order (best first)
BAND_ORDER = {"strong_fit": 0, "adjacent_fit": 1, "weak_fit": 2, "misleading_fit": 3, "reject": 4}


def load_profile(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Resume JSON not found at {p} — paste rtl.json there.")
    return json.loads(p.read_text())


def profile_to_text(profile: dict) -> str:
    parts = [
        "Titles: " + ", ".join(profile.get("recent_titles", []) + profile.get("suggested_roles", [])),
        "Skills: " + ", ".join(profile.get("skills", [])),
        "Domains: " + ", ".join(d.get("name", "") for d in profile.get("domains", [])),
        "Years of experience: " + str(profile.get("years_of_experience", "")),
        "Industries: " + ", ".join(profile.get("industries", [])),
    ]
    return "\n".join(parts)


async def scrape() -> list:
    cfg = ScraperConfig(hours_old=72, default_country="USA", max_results_per_query=15,
                        linkedin_max_queries=1, sources=["linkedin"], jobspy_delay=1.0)
    seen, jobs = set(), []
    for term in TERMS:
        q = [SearchQuery(term=term, location="United States", country="USA")]
        for j in await jobspy_source.search(q, cfg, site="linkedin", db=None):
            if j.job_url not in seen and j.description:
                seen.add(j.job_url)
                jobs.append(j)
    return jobs


def prefilter(jobs: list, profile: dict) -> list:
    """Cheap keyword pre-filter: drop obvious non-matches BEFORE paying for LLM.

    High-recall, zero-cost first pass. Keep a job if its title shows any IC-design
    signal, OR shows no negative signal (ambiguous -> let the LLM judge). Only drop
    when the title clearly hits a negative keyword and has no positive signal.
    """
    neg = {k.lower() for k in profile.get("query_plan", {}).get("negative_keywords", [])}
    pos = {"asic", "rtl", "soc", "vlsi", "clock", "clocking", "cdc", "sta", "timing",
           "cpu", "gpu", "tpu", "npu", "physical design", "digital design",
           "ic design", "silicon", "verification", "microarchitecture"}
    kept = []
    for j in jobs:
        title = (j.title or "").lower()
        has_pos = any(p in title for p in pos)
        has_neg = any(n in title for n in neg)
        if has_pos or not has_neg:
            kept.append(j)
    return kept


async def main() -> None:
    profile = load_profile(RESUME_JSON)
    resume_text = profile_to_text(profile)
    print(f"Resume profile loaded ({len(profile.get('skills', []))} skills). Scraping LinkedIn...")
    jobs = await scrape()
    kept = prefilter(jobs, profile)
    print(f"Scraped {len(jobs)} jobs -> {len(kept)} survive pre-filter. Scoring those against resume...\n")

    client = build_llm_client(provider="anthropic")  # uses ANTHROPIC_API_KEY
    client.models = ["claude-haiku-4-5-20251001"]  # pin Haiku (cheapest current gen)

    sem = asyncio.Semaphore(8)  # score up to 8 in parallel (fast, polite to rate limits)

    async def score(j):
        async with sem:
            report = await judge_match_report(
                candidate_profile=profile,
                job_profile={"title": j.title, "company": j.company},
                resume_text=resume_text,
                job_text=j.description or "",
                llm_client=client,
            )
            band = report.get("verdict") or report.get("fit_band") or "reject"
            return (band, j, report)

    results = await asyncio.gather(*(score(j) for j in kept))

    results.sort(key=lambda r: BAND_ORDER.get(r[0], 5))
    for band, j, report in results:
        why = (report.get("summary") or report.get("explanation_summary") or "")[:120]
        print(f"[{band:14}] {j.title}  @ {j.company}  [{j.location}]")
        if why:
            print(f"                 ↳ {why}")
    print(f"\nScored {len(results)} jobs. Top of list = best resume fit.")


if __name__ == "__main__":
    asyncio.run(main())