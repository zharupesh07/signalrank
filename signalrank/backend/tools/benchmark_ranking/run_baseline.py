"""
Run the V2 pipeline against a frozen corpus for each benchmark resume.
Writes top-30 JSON snapshots.

Usage:
    uv run python tools/benchmark_ranking/run_baseline.py \
        --frozen-path tools/benchmark_ranking/frozen/2026-04-05_abc12345.parquet \
        --resume-dir tools/benchmark_ranking/resumes/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
sys.path.insert(0, str(Path(__file__).parents[2]))


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _normalize_job_record(job: dict[str, Any]):
    from tools.rank_resume_existing_corpus import JobRecord

    return JobRecord(
        job_url=str(job.get("job_url") or job.get("url") or job.get("id") or ""),
        title=str(job.get("title") or ""),
        company=str(job.get("company") or ""),
        location=str(job.get("location") or ""),
        site=str(job.get("site") or job.get("source") or ""),
        description=str(job.get("description") or ""),
        date_posted=str(job.get("date_posted")) if job.get("date_posted") is not None else None,
    )


def run_baseline(frozen_path: Path, resume_dir: Path) -> list[Path]:
    from tools.rank_resume_existing_corpus import _extract_generic_profile, _load_resume_text, _score_jobs

    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    sha = _git_sha()
    jobs = pd.read_parquet(frozen_path).to_dict(orient="records")

    resume_files = sorted(resume_dir.glob("*.txt")) + sorted(resume_dir.glob("*.pdf"))
    if not resume_files:
        print(f"No resumes found in {resume_dir}")
        return []

    written: list[Path] = []
    for resume_path in resume_files:
        name = resume_path.stem
        print(f"Running V2 baseline for {name} ...")
        resume_text = _load_resume_text(resume_path)
        profile = _extract_generic_profile(resume_text, resume_name=name)
        job_records = [_normalize_job_record(job) for job in jobs]
        scored = _score_jobs(profile, job_records, agentic=False)[:30]

        out_path = SNAPSHOTS_DIR / f"baseline_{sha}_{name}.json"
        out_path.write_text(json.dumps(scored, indent=2, default=str) + "\n", encoding="utf-8")
        written.append(out_path)
        print(f"  -> {out_path} ({len(scored)} jobs)")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the V2 baseline against a frozen corpus.")
    parser.add_argument("--frozen-path", required=True, type=Path)
    parser.add_argument("--resume-dir", required=True, type=Path)
    args = parser.parse_args()
    run_baseline(args.frozen_path, args.resume_dir)


if __name__ == "__main__":
    main()
