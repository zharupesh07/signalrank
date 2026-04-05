"""
Side-by-side diff of baseline vs candidate top-30 snapshots.

Usage:
    uv run python tools/benchmark_ranking/diff.py \
        --baseline snapshots/baseline_<sha>_<resume>.json \
        --candidate snapshots/candidate_<sha>_<resume>.json \
        --output reports/2026-04-05_diff.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / "reports"


def load_snapshot(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _job_id(job: dict) -> str:
    return str(job.get("id") or job.get("job_url") or job.get("url") or job.get("title") or "")


def diff_snapshots(baseline: list[dict], candidate: list[dict], resume_name: str) -> str:
    baseline_ids = {_job_id(job): idx + 1 for idx, job in enumerate(baseline[:30])}
    candidate_ids = {_job_id(job): idx + 1 for idx, job in enumerate(candidate[:30])}

    lines: list[str] = [f"## {resume_name}", ""]
    lines.append("| Rank | Candidate Title | Score | Baseline Rank | Delta |")
    lines.append("|------|------------------|-------|---------------|-------|")

    for idx, job in enumerate(candidate[:30], start=1):
        jid = _job_id(job)
        title = str(job.get("title") or "")
        score = f"{float(job.get('score', 0.0)):.3f}"
        baseline_rank = baseline_ids.get(jid, "-")
        if isinstance(baseline_rank, int):
            delta = baseline_rank - idx
            delta_str = f"+{delta}" if delta > 0 else str(delta)
        else:
            delta_str = "NEW"
        lines.append(f"| {idx} | {title} | {score} | {baseline_rank} | {delta_str} |")

    dropped = [job for job in baseline[:30] if _job_id(job) not in candidate_ids]
    if dropped:
        lines.append("")
        lines.append(f"**Dropped from baseline top-30:** {len(dropped)}")
        for job in dropped:
            lines.append(f"- {job.get('title', '')} (was #{baseline_ids.get(_job_id(job), '-')})")

    return "\n".join(lines) + "\n"


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser(description="Diff baseline and candidate benchmark snapshots.")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--resume-name", type=str, default="resume")
    args = parser.parse_args()

    baseline = load_snapshot(args.baseline)
    candidate = load_snapshot(args.candidate)
    report = diff_snapshots(baseline, candidate, args.resume_name)
    print(report, end="")

    out = args.output or (REPORTS_DIR / f"diff_{args.resume_name}.md")
    out.write_text(report, encoding="utf-8")
    print(f"\nReport saved -> {out}")


if __name__ == "__main__":
    main()
