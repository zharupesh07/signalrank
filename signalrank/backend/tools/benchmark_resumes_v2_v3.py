"""
Compare V2 vs V3 ranking for all resumes against the last-30-day job corpus from Railway DB.

V2 = score_jobs_for_user (DB-based, embedding + keyword scorer)
V3 = rank_jobs_v3 (standalone, lane+scorer pipeline)

Users with DB profiles: Example, Aditya, Ayush  (V2 + V3)
PDF-only (no DB profile): Abhijeet, Vivek     (V3 only)

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


async def _run_v2(session_factory, user_id: str, resume_text: str) -> list[dict]:
    from batch.ranker import score_jobs_for_user
    # Disable LLM agentic matching for benchmark — pure deterministic scoring only
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
    top = df.head(30)
    return top.to_dict(orient="records")


def _run_v3(resume_text: str, jobs: list[dict], candidate_name: str) -> list[dict]:
    from ranking.v3.pipeline import rank_jobs_v3
    return rank_jobs_v3(resume_text, jobs, candidate_name=candidate_name, top_k=30)


def _fmt(job: dict, rank: int) -> str:
    title = job.get("title") or job.get("job_title") or "?"
    company = job.get("company") or job.get("company_name") or "?"
    location = job.get("location") or "?"
    score = job.get("score") or job.get("final_score") or job.get("composite_score") or 0
    date = str(job.get("date_posted") or "")[:10]
    return f"  {rank:2d}. [{float(score):.3f}] {title} @ {company} ({location}) [{date}]"


def _write_report(name: str, v2: list[dict], v3: list[dict]) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{name}_{ts}.txt"

    def job_key(j):
        return (j.get("title") or j.get("job_title") or "", j.get("company") or j.get("company_name") or "")

    v2_keys = {job_key(j) for j in v2}
    v3_keys = {job_key(j) for j in v3}
    overlap = v2_keys & v3_keys

    lines = [
        "=" * 70,
        f"CANDIDATE: {name}",
        f"Generated: {datetime.now().isoformat()}",
        f"Jobs compared: V2={len(v2)}  V3={len(v3)}",
        "=" * 70,
        "",
    ]

    if v3:
        lines += ["V3 TOP 30:", "-" * 70]
        for i, j in enumerate(v3, 1):
            lines.append(_fmt(j, i))
        lines.append("")

    if v2:
        lines += ["V2 TOP 30:", "-" * 70]
        for i, j in enumerate(v2, 1):
            lines.append(_fmt(j, i))
        lines.append("")

    lines += [
        f"OVERLAP (both V2 and V3 top 30): {len(overlap)}/30",
        "-" * 70,
        *[f"  = {t} @ {c}" for t, c in sorted(overlap)],
        "",
        f"NEW in V3 (not in V2):",
        "-" * 70,
        *[f"  + {t} @ {c}" for t, c in sorted(v3_keys - v2_keys)],
        "",
        f"DROPPED by V3 (in V2 but not V3):",
        "-" * 70,
        *[f"  - {t} @ {c}" for t, c in sorted(v2_keys - v3_keys)],
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

        v3 = []
        print(f"  V3...", end="", flush=True)
        try:
            v3 = _run_v3(resume_text, jobs, name)
            print(f" {len(v3)} results")
        except Exception as e:
            print(f" FAILED: {e}")

        v2 = []
        if user_id:
            print(f"  V2...", end="", flush=True)
            try:
                v2 = await _run_v2(session_factory, user_id, resume_text)
                print(f" {len(v2)} results")
            except Exception as e:
                print(f" FAILED: {e}")

        report = _write_report(name, v2, v3)
        print(f"  Report: {report.name}")

        print(f"\n  V3 Top 10:")
        for i, j in enumerate(v3[:10], 1):
            print(_fmt(j, i))

        if v2:
            print(f"\n  V2 Top 10:")
            for i, j in enumerate(v2[:10], 1):
                print(_fmt(j, i))

        if v2 and v3:
            def job_key(j):
                return (j.get("title") or j.get("job_title") or "", j.get("company") or j.get("company_name") or "")
            overlap = {job_key(j) for j in v2} & {job_key(j) for j in v3}
            print(f"\n  Overlap V2∩V3: {len(overlap)}/30")

    await engine.dispose()
    print(f"\n\nAll reports saved to: {REPORTS_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
