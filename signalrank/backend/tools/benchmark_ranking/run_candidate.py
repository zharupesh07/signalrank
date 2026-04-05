"""
Run the V3 pipeline against a frozen corpus for each benchmark resume.
Writes top-30 JSON snapshots.

Usage:
    uv run python tools/benchmark_ranking/run_candidate.py \
        --frozen-path tools/benchmark_ranking/frozen/2026-04-05_abc12345.parquet \
        --resume-dir tools/benchmark_ranking/resumes/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
sys.path.insert(0, str(Path(__file__).parents[2]))


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run_candidate(frozen_path: Path, resume_dir: Path, current_focus_map: dict[str, str] | None = None) -> list[Path]:
    from ranking.v3.pipeline import rank_jobs_v3
    from tools.rank_resume_existing_corpus import _load_resume_text

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
        focus = (current_focus_map or {}).get(name)
        print(f"Running V3 candidate for {name} (focus={focus!r}) ...")
        resume_text = _load_resume_text(resume_path)
        results = rank_jobs_v3(
            resume_text,
            jobs,
            candidate_name=name,
            current_focus=focus,
            top_k=30,
        )

        out_path = SNAPSHOTS_DIR / f"candidate_{sha}_{name}.json"
        out_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
        written.append(out_path)
        print(f"  -> {out_path} ({len(results)} jobs)")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the V3 candidate against a frozen corpus.")
    parser.add_argument("--frozen-path", required=True, type=Path)
    parser.add_argument("--resume-dir", required=True, type=Path)
    parser.add_argument(
        "--focus-json",
        type=Path,
        default=None,
        help="JSON file mapping resume stem to current_focus string.",
    )
    args = parser.parse_args()
    focus_map = json.loads(args.focus_json.read_text(encoding="utf-8")) if args.focus_json else None
    run_candidate(args.frozen_path, args.resume_dir, focus_map)


if __name__ == "__main__":
    main()
