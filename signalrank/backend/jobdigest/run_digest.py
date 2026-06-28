"""Headless digest runner — the daily entrypoint.

scrape (LinkedIn) -> pre-filter -> score (Anthropic, with backoff) ->
keep strong+adjacent -> group by domain -> render HTML -> send via Gmail.

Run from backend/:
  python -m jobdigest.run_digest            # send the email
  python -m jobdigest.run_digest --dry-run  # render + print, do NOT send

Secrets come from env (ANTHROPIC_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD).
Non-secret config from jobdigest/jobdigest.yaml.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from datetime import datetime
from pathlib import Path

from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig
from batch.sources import jobspy_source
from domain.match_judge import judge_match_report
from llm.providers import build_llm_client

from jobdigest.config import load_config
from jobdigest.digest import render_digest, send_email

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jobdigest")

KEEP_BANDS = {"strong_fit", "adjacent_fit"}  # what makes the email
POS = {"asic", "rtl", "soc", "vlsi", "clock", "clocking", "cdc", "sta", "timing",
       "cpu", "gpu", "tpu", "npu", "physical design", "digital design",
       "ic design", "silicon", "verification", "microarchitecture"}


def profile_text(profile: dict) -> str:
    return "\n".join([
        "Titles: " + ", ".join(profile.get("recent_titles", []) + profile.get("suggested_roles", [])),
        "Skills: " + ", ".join(profile.get("skills", [])),
        "Domains: " + ", ".join(d.get("name", "") for d in profile.get("domains", [])),
        "Years of experience: " + str(profile.get("years_of_experience", "")),
        "Industries: " + ", ".join(profile.get("industries", [])),
    ])


async def scrape(cfg, terms: list[str]) -> list:
    sc = ScraperConfig(hours_old=cfg.search.hours_old, default_country=cfg.search.country,
                       max_results_per_query=20, linkedin_max_queries=1,
                       sources=["linkedin"], jobspy_delay=1.0)
    seen, jobs = set(), []
    for term in terms:
        q = [SearchQuery(term=term, location="United States", country=cfg.search.country)]
        for j in await jobspy_source.search(q, sc, site="linkedin", db=None):
            if j.job_url not in seen and j.description:
                seen.add(j.job_url)
                jobs.append(j)
    return jobs


def prefilter(jobs: list, profile: dict) -> list:
    neg = {k.lower() for k in profile.get("query_plan", {}).get("negative_keywords", [])}
    # Seniority: candidate is ~4 yrs. Target mid + senior (some stretch).
    # Drop clearly-junior (new grad/intern) AND clearly-too-senior (staff/principal/director/manager).
    too_junior = ["new grad", "new college grad", "intern", "internship", "co-op",
                  "graduate", "entry level", "entry-level", "early career", "university grad"]
    too_senior = ["principal", "director", "vp ", "head of", "fellow", "distinguished",
                  "sr. staff", "sr staff", "senior staff", "staff ", "manager"]
    exclude_companies = {c.lower() for c in profile.get("exclude_companies", [])}
    kept = []
    for j in jobs:
        t = (j.title or "").lower()
        company = (j.company or "").lower()
        if exclude_companies and any(ex in company for ex in exclude_companies):
            continue  # e.g. current employer
        if any(x in t for x in too_junior):
            continue
        if any(x in t for x in too_senior):
            continue
        if any(p in t for p in POS) or not any(n in t for n in neg):
            kept.append(j)
    return kept


def _is_fallback(report: dict) -> bool:
    s = report.get("summary") or report.get("explanation_summary") or ""
    return s.startswith("verdict=") and "skills=none" in s


async def score_all(jobs: list, profile: dict, client) -> list:
    sem = asyncio.Semaphore(3)  # Tier-1 safe
    resume_text = profile_text(profile)

    async def score(j):
        async with sem:
            for attempt in range(4):
                report = await judge_match_report(
                    candidate_profile={**profile, "seniority_band": "mid"},
                    job_profile={"title": j.title, "company": j.company},
                    resume_text=resume_text, job_text=j.description or "",
                    llm_client=client,
                )
                if not _is_fallback(report):
                    return (report.get("verdict") or "reject", j, report)
                await asyncio.sleep(min(2 ** attempt, 8) + random.uniform(0.2, 1.0))
            return (report.get("verdict") or "reject", j, report)

    return await asyncio.gather(*(score(j) for j in jobs))


async def run_one_profile(cfg, profile_entry, profile_json: dict, client, dry_run: bool, no_llm: bool,
                          already_sent: set):
    terms = profile_entry.titles
    label = profile_entry.id
    print(f"\n[{label}] scraping {len(terms)} title queries...")
    jobs = await scrape(cfg, terms)
    # inject config-level company excludes (e.g. current employer) into the profile
    profile_json = {**profile_json, "exclude_companies": getattr(cfg, "exclude_companies", []) or []}
    kept = prefilter(jobs, profile_json)
    # DEDUP: drop jobs already emailed in a previous run (also saves scoring cost)
    before = len(kept)
    kept = [j for j in kept if j.job_url not in already_sent]
    skipped = before - len(kept)
    if skipped:
        print(f"[{label}] skipped {skipped} already-emailed jobs (dedup)")
    if no_llm:
        print(f"[{label}] {len(jobs)} scraped -> {len(kept)} new pre-filtered -> NO-LLM (skipping scoring)")
        deduped, seen = [], set()
        for j in kept:
            if j.job_url not in seen:
                seen.add(j.job_url)
                deduped.append(("adjacent_fit", j, {"summary": "(no-llm preview — not scored)"}))
        print(f"[{label}] {len(deduped)} jobs (unscored preview).")
        return label, deduped

    print(f"[{label}] {len(jobs)} scraped -> {len(kept)} new pre-filtered -> scoring...")
    scored = await score_all(kept, profile_json, client)
    matches = [(b, j, r) for (b, j, r) in scored if b in KEEP_BANDS]
    # de-dupe by url, best band first
    order = {"strong_fit": 0, "adjacent_fit": 1}
    seen, deduped = set(), []
    for b, j, r in sorted(matches, key=lambda x: order.get(x[0], 9)):
        if j.job_url not in seen:
            seen.add(j.job_url)
            deduped.append((b, j, r))
    print(f"[{label}] {len(deduped)} strong/adjacent matches.")
    return label, deduped


async def main(dry_run: bool, no_llm: bool = False) -> None:
    cfg = load_config()
    date_str = datetime.now().strftime("%a %b %d, %Y")

    # secrets check
    missing = []
    import os
    if not dry_run:
        if not os.getenv("ANTHROPIC_API_KEY"):
            missing.append("ANTHROPIC_API_KEY")
        if not cfg.secrets.gmail_user:
            missing.append("GMAIL_USER")
        if not cfg.secrets.gmail_app_password:
            missing.append("GMAIL_APP_PASSWORD")
    if missing:
        print(f"ERROR: missing env: {missing}. Set them and retry.")
        sys.exit(1)

    # --dry-run implies no LLM: free scrape+render preview, no email.
    no_llm = dry_run

    client = None
    if not no_llm:
        client = build_llm_client(provider="anthropic")
        client.models = ["claude-haiku-4-5-20251001"]

    # DEDUP: load URLs already emailed in past runs (skip in dry-run / when no DB)
    already_sent: set = set()
    if not dry_run and os.getenv("DATABASE_URL"):
        from jobdigest import dedup
        already_sent = await dedup.load_sent_urls()
        print(f"Dedup: {len(already_sent)} jobs previously emailed will be skipped.")

    # load each profile's JSON (resume path is e.g. resumes/rtl.pdf -> resumes/rtl.json)
    resume_dir = Path(__file__).parent / "resumes"
    all_sections = []
    for p in cfg.profiles:
        jpath = resume_dir / f"{p.id}.json"
        if not jpath.exists():
            print(f"WARNING: {jpath} missing, skipping profile {p.id}")
            continue
        import json
        pjson = json.loads(jpath.read_text())
        label, matches = await run_one_profile(cfg, p, pjson, client, dry_run, no_llm, already_sent)
        all_sections.append((label, matches))

    # combine (routing=combined) into one digest
    combined = []
    labels = []
    for label, matches in all_sections:
        labels.append(label)
        combined.extend(matches)
    # de-dupe across profiles by url
    seen, final = set(), []
    order = {"strong_fit": 0, "adjacent_fit": 1}
    for b, j, r in sorted(combined, key=lambda x: order.get(x[0], 9)):
        if j.job_url not in seen:
            seen.add(j.job_url)
            final.append((b, j, r))

    subject, html = render_digest(final, profile_label="+".join(labels) or "all", date_str=date_str)
    print(f"\nDigest: {len(final)} total matches. Subject: {subject}")

    if dry_run:
        out = Path("jobdigest_preview.html")
        out.write_text(html)
        print(f"DRY RUN — wrote {out.resolve()} (open it to preview). No email sent.")
        return

    send_email(subject=subject, html=html,
               sender=cfg.secrets.gmail_user, app_password=cfg.secrets.gmail_app_password,
               recipients=[str(r) for r in cfg.recipients])
    print(f"Sent digest to {[str(r) for r in cfg.recipients]}")

    # DEDUP: record what we just emailed so tomorrow's run skips them
    if os.getenv("DATABASE_URL"):
        from jobdigest import dedup
        n = await dedup.record_sent(final)
        print(f"Dedup: recorded {n} emailed jobs.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="free preview: scrape + render HTML, NO LLM scoring, NO email")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))