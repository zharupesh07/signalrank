"""
Compare V4 DB scorer vs V4 standalone scorer for all resumes against last-30-day DB corpus.

DB-profile users: compare V4 DB vs V4 standalone.
PDF-only users: run V4 standalone only.

Usage:
    cd signalrank/backend
    set -a && source .env && set +a
    DATABASE_URL="$DATABASE_URL_RAILWAY" uv run python -m tools.benchmark_resumes_v2_v3
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz  # pymupdf

RESUMES_DIR = Path("/Users/examplecandidate/Projects/job_ranker/resumes")
REPORTS_DIR = Path(__file__).parent / "benchmark_ranking" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

RESUME_MAP = {
    "Abhijeet_CV":                     {"name": "Abhijeet",  "user_id": None},
    "Example_Candidate_Resume_V2_2":        {"name": "Example",      "user_id": "9b16ef56-7cc3-4f96-b076-347ee2e37924"},
    "Vivek-Gupta-Emerging-Technologies":{"name": "Vivek",    "user_id": None},
    "aditya":                          {"name": "Aditya",    "user_id": "a849e48f-51ef-4276-a140-d8790edaa76d"},
    "ayush_resume_new":                {"name": "Ayush",     "user_id": "428483a5-3044-4132-b129-8b79ea2beb67"},
}


def _read_pdf(path: Path) -> str:
    doc = fitz.open(str(path))
    return "\n".join(page.get_text() for page in doc).strip()


async def _fetch_jobs_from_db(engine, hours_old: int = 720) -> list[dict]:
    from sqlalchemy import text
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_old)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT id::text, title, company, location, description,
                   date_posted, job_url, site
            FROM jobs_raw
            WHERE date_posted >= :cutoff
            ORDER BY date_posted DESC
        """), {"cutoff": cutoff})
        rows = result.fetchall()
        keys = list(result.keys())
    jobs = [dict(zip(keys, row)) for row in rows]
    for j in jobs:
        if isinstance(j.get("date_posted"), datetime):
            j["date_posted"] = j["date_posted"].isoformat()
    return jobs


def _run_v4_standalone(resume_text: str, jobs: list[dict]) -> list[dict]:
    from ranking.v4.scorer import rank_jobs_v4
    return rank_jobs_v4(resume_text, jobs, top_k=30)


async def _run_v4_db(session_factory, user_id: str, resume_text: str) -> list[dict]:
    from ranking.v4.db_scorer import score_jobs_for_user
    config_overrides = {"ranking": {"agentic_matching": {"enabled": False}}}
    async with session_factory() as db:
        df = await score_jobs_for_user(
            db=db,
            user_id=user_id,
            resume_text=resume_text,
            config_overrides=config_overrides,
        )
    if df is None or df.empty:
        return []
    return df.head(30).to_dict(orient="records")


def _fmt(job: dict, rank: int) -> str:
    title = job.get("title") or job.get("job_title") or "?"
    company = job.get("company") or job.get("company_name") or "?"
    location = job.get("location") or "?"
    score = job.get("score") or job.get("final_score") or job.get("composite_score") or 0
    date = str(job.get("date_posted") or "")[:10]
    return f"  {rank:2d}. [{float(score):.3f}] {title} @ {company} ({location}) [{date}]"


def _write_report(name: str, v4_db: list[dict], v4_standalone: list[dict]) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{name}_{ts}.txt"

    def job_key(j):
        return (j.get("title") or j.get("job_title") or "", j.get("company") or j.get("company_name") or "")

    v4_db_keys = {job_key(j) for j in v4_db}
    v4_standalone_keys = {job_key(j) for j in v4_standalone}

    lines = [
        "=" * 70,
        f"CANDIDATE: {name}",
        f"Generated: {datetime.now().isoformat()}",
        f"Jobs compared: V4_DB={len(v4_db)}  V4_STANDALONE={len(v4_standalone)}",
        "=" * 70,
        "",
    ]

    if v4_db:
        lines += ["V4 DB TOP 30:", "-" * 70]
        for i, j in enumerate(v4_db, 1):
            lines.append(_fmt(j, i))
        lines.append("")

    if v4_standalone:
        lines += ["V4 STANDALONE TOP 30:", "-" * 70]
        for i, j in enumerate(v4_standalone, 1):
            lines.append(_fmt(j, i))
        lines.append("")

    if v4_db and v4_standalone:
        overlap = v4_db_keys & v4_standalone_keys
        lines += [
            f"OVERLAP V4_DB∩V4_STANDALONE: {len(overlap)}/30",
            "-" * 70,
            *[f"  = {t} @ {c}" for t, c in sorted(overlap)],
            "",
            "NEW in V4 DB vs standalone:",
            "-" * 70,
            *[f"  + {t} @ {c}" for t, c in sorted(v4_db_keys - v4_standalone_keys)],
            "",
            "Only in standalone vs V4 DB:",
            "-" * 70,
            *[f"  - {t} @ {c}" for t, c in sorted(v4_standalone_keys - v4_db_keys)],
            "",
        ]

    path.write_text("\n".join(lines))
    return path


async def main():
    from api.database import _build_engine
    from batch.worker_main import resolve_db_url

    url = resolve_db_url()
    engine, session_factory = _build_engine(url)

    print("Fetching jobs from last 30 days...")
    jobs = await _fetch_jobs_from_db(engine, hours_old=720)
    print(f"  {len(jobs)} jobs loaded")

    pdfs = sorted(RESUMES_DIR.glob("*.pdf"))

    for pdf_path in pdfs:
        stem = pdf_path.stem
        meta = RESUME_MAP.get(stem)
        if not meta:
            print(f"\nSkipping {stem} (not in RESUME_MAP)")
            continue

        name = meta["name"]
        user_id = meta["user_id"]
        print(f"\n{'='*60}")
        print(f"Candidate: {name}  (DB user: {'yes' if user_id else 'no'})")

        resume_text = _read_pdf(pdf_path)
        print(f"  Resume text: {len(resume_text)} chars")

        v4_standalone = []
        print("  V4 standalone...", end="", flush=True)
        try:
            v4_standalone = _run_v4_standalone(resume_text, jobs)
            print(f" {len(v4_standalone)} results")
        except Exception as e:
            print(f" FAILED: {e}")

        v4_db = []
        if user_id:
            print("  V4 DB...", end="", flush=True)
            try:
                v4_db = await _run_v4_db(session_factory, user_id, resume_text)
                print(f" {len(v4_db)} results")
            except Exception as e:
                print(f" FAILED: {e}")

        report = _write_report(name, v4_db, v4_standalone)
        print(f"  Report: {report.name}")

        print("\n  V4 standalone Top 10:")
        for i, j in enumerate(v4_standalone[:10], 1):
            print(_fmt(j, i))

        if v4_db:
            print("\n  V4 DB Top 10:")
            for i, j in enumerate(v4_db[:10], 1):
                print(_fmt(j, i))

        def job_key(j):
            return (j.get("title") or j.get("job_title") or "", j.get("company") or j.get("company_name") or "")

        if v4_db and v4_standalone:
            overlap = {job_key(j) for j in v4_db} & {job_key(j) for j in v4_standalone}
            print(f"\n  Overlap V4 DB∩V4 standalone: {len(overlap)}/30")

    await engine.dispose()
    print(f"\n\nAll reports saved to: {REPORTS_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
