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
import json
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
                       max_results_per_query=50, linkedin_max_queries=1,
                       sources=["linkedin"], jobspy_delay=1.0)
    seen, jobs = set(), []
    cap = 50
    # LinkedIn's own hours_old filter is unreliable (serves stale/reposted jobs to fill
    # the quota), so we ENFORCE freshness ourselves on date_posted.
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.search.hours_old)
    stale_dropped = 0
    for term in terms:
        q = [SearchQuery(term=term, location="United States", country=cfg.search.country)]
        try:
            results = await jobspy_source.search(q, sc, site="linkedin", db=None)
        except Exception as exc:  # noqa: BLE001 — one flaky query shouldn't kill the run
            log.warning("scrape failed for '%s': %s — skipping this query", term, exc)
            continue
        n = len(results)
        if n >= cap:
            log.warning("query '%s' returned %d (hit the %d cap)", term, n, cap)
        for j in results:
            if j.job_url in seen or not j.description:
                continue
            # Enforce real freshness. Keep jobs with no date (LinkedIn sometimes omits it)
            # rather than risk dropping a genuinely-new posting.
            if j.date_posted is not None and j.date_posted < cutoff:
                stale_dropped += 1
                continue
            seen.add(j.job_url)
            jobs.append(j)
    if stale_dropped:
        log.info("dropped %d jobs older than %dh (LinkedIn's filter let them through)",
                 stale_dropped, cfg.search.hours_old)
    return jobs


def _positive_signals(profile: dict) -> set:
    """Build the 'keep' keyword set from THIS profile's own roles/skills/queries,
    so the pre-filter works for any person (IC, software, etc.), not a hardcoded list."""
    sig = set()
    titles = profile.get("suggested_roles", []) + [r.get("title", "") for r in profile.get("target_roles", [])]
    for t in titles:
        for w in t.lower().split():
            if len(w) > 2:
                sig.add(w)
    for d in profile.get("domains", []):
        for w in d.get("name", "").lower().replace("/", " ").split():
            if len(w) > 2:
                sig.add(w)
    for q in profile.get("query_plan", {}).get("title_queries", []):
        sig.add(q.lower())
    return sig


def prefilter(jobs: list, profile: dict) -> list:
    neg = {k.lower() for k in profile.get("query_plan", {}).get("negative_keywords", [])}
    pos = _positive_signals(profile)
    # Seniority: target mid + senior. Drop clearly-junior (new grad/intern) and
    # clearly-too-senior (principal/director/manager). 'staff' is NOT dropped — it's a
    # normal senior IC level (esp. in software); the LLM judges the stretch.
    too_junior = ["new grad", "new college grad", "intern", "internship", "co-op",
                  "graduate", "entry level", "entry-level", "early career", "university grad"]
    too_senior = ["principal", "director", "vp ", "head of", "fellow", "distinguished", "manager"]
    exclude_companies = {c.lower() for c in profile.get("exclude_companies", [])}
    kept = []
    for j in jobs:
        t = (j.title or "").lower()
        company = (j.company or "").lower()
        if exclude_companies and any(ex in company for ex in exclude_companies):
            continue
        if any(x in t for x in too_junior):
            continue
        if any(x in t for x in too_senior):
            continue
        if any(p in t for p in pos) or not any(n in t for n in neg):
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
    # SKIP anything we've EVER scored before (emailed or rejected) — never re-score.
    before = len(kept)
    kept = [j for j in kept if j.job_url not in already_seen]
    skipped = before - len(kept)
    if skipped:
        print(f"[{label}] skipped {skipped} already-scored jobs (won't re-score)")
    if no_llm:
        print(f"[{label}] {len(jobs)} scraped -> {len(kept)} new pre-filtered -> NO-LLM (skipping scoring)")
        deduped, seen = [], set()
        for j in kept:
            if j.job_url not in seen:
                seen.add(j.job_url)
                deduped.append(("adjacent_fit", j, {"summary": "(no-llm preview — not scored)"}))
        print(f"[{label}] {len(deduped)} jobs (unscored preview).")
        return label, deduped, []

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
    return label, deduped, scored  # scored = ALL judged jobs, for recording as seen


async def main(dry_run: bool, no_llm: bool = False, config_path: str | None = None) -> None:
    from jobdigest.config import CONFIG_PATH
    cfg = load_config(config_path or CONFIG_PATH)
    date_str = datetime.now().strftime("%a %b %d, %Y")

    # tag = config file name (e.g. "adya" or "jobdigest"); keeps each digest independent
    tag = Path(config_path).stem if config_path else "jobdigest"
    # "today" in the digest's own timezone, so the once-per-day guard rolls over correctly
    tz = ZoneInfo(getattr(cfg.digest, "timezone", "America/Los_Angeles"))
    today = datetime.now(tz).strftime("%Y-%m-%d")

    # ONCE-PER-DAY GUARD: GitHub cron can fire hours late and/or twice (DST double-cron).
    # Instead of a brittle exact-hour check, just ensure we send at most once per day.
    if not dry_run and os.getenv("DATABASE_URL"):
        from jobdigest import dedup
        if await dedup.already_ran_today(tag, today):
            print(f"Already sent '{tag}' digest today ({today}) — skipping.")
            return

    # secrets check
    missing = []
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

    # SKIP-LIST: load URLs we've EVER scored (emailed or rejected) so we never re-score.
    already_seen: set = set()
    if not dry_run and os.getenv("DATABASE_URL"):
        from jobdigest import dedup
        already_seen = await dedup.load_seen_urls()
        print(f"Skip-list: {len(already_seen)} jobs already scored before — won't re-score.")

    # load each profile's JSON (resume path is e.g. resumes/rtl.pdf -> resumes/rtl.json)
    resume_dir = Path(__file__).parent / "resumes"
    all_sections = []
    all_scored = []  # every judged job across profiles, to record as 'seen'
    for p in cfg.profiles:
        jpath = resume_dir / f"{p.id}.json"
        if not jpath.exists():
            print(f"WARNING: {jpath} missing, skipping profile {p.id}")
            continue
        pjson = json.loads(jpath.read_text())
        label, matches, scored = await run_one_profile(cfg, p, pjson, client, dry_run, no_llm, already_seen)
        all_sections.append((label, matches))
        all_scored.extend(scored)

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

    # Skip sending an empty digest (common once skip-list is active and there are no
    # NEW jobs that day) — but still record what we scored + mark the day done.
    if not final:
        print("No new matches today — not sending an empty email.")
        if os.getenv("DATABASE_URL"):
            from jobdigest import dedup
            n = await dedup.record_seen(all_scored)
            print(f"Skip-list: recorded {n} newly-scored jobs.")
            await dedup.mark_ran_today(tag, today)
            print(f"Marked '{tag}' digest as done for {today} (empty).")
        return

    # Send first. Only on success do we record (seen + sent) and mark the day done.
    # Rationale: if the email fails, we'd rather re-score next run (recoverable cost)
    # than mark jobs 'seen' and silently lose matches that never reached the inbox.
    try:
        send_email(subject=subject, html=html,
                   sender=cfg.secrets.gmail_user, app_password=cfg.secrets.gmail_app_password,
                   recipients=[str(r) for r in cfg.recipients])
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: send failed ({exc}). Recording nothing — will retry next run.")
        sys.exit(1)
    print(f"Sent digest to {[str(r) for r in cfg.recipients]}")

    if os.getenv("DATABASE_URL"):
        from jobdigest import dedup
        seen_n = await dedup.record_seen(all_scored)
        sent_n = await dedup.record_sent(final)
        await dedup.mark_ran_today(tag, today)
        print(f"Recorded {seen_n} scored (skip-list), {sent_n} emailed. Marked '{tag}' done for {today}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="free preview: scrape + render HTML, NO LLM scoring, NO email")
    ap.add_argument("--config", default=None,
                    help="path to a config yaml (default: jobdigest.yaml). Use for a second person.")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run, config_path=args.config))