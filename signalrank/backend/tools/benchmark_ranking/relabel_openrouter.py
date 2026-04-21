"""
Relabel benchmark snapshots using OpenRouter free models with consensus checks.

Usage:
    set -a && source /Users/examplecandidate/Projects/job_ranker/signalrank/backend/.env && set +a
    uv run python tools/benchmark_ranking/relabel_openrouter.py \
      --snapshot tools/benchmark_ranking/snapshots/candidate_<sha>_<resume>.json \
      --resume <resume> \
      --labels tools/benchmark_ranking/labels/labels.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from llm.openrouter import OpenRouterClient, _extract_json
from tools.benchmark_ranking.score_labeled import _job_id

LABELS = ("good", "adjacent", "bad")
CONSENSUS_MODELS = [
    "google/gemma-4-31b-it:free",
    "arcee-ai/trinity-large-preview:free",
    "openai/gpt-oss-120b:free",
]

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(LABELS)},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 4,
        },
    },
    "required": ["label", "confidence", "reasons"],
    "additionalProperties": False,
}


def _job_prompt(resume_text: str, job: dict) -> str:
    return f"""You are labeling job relevance for a resume benchmark.
Use the full resume and the full job description together.
Return one label only:
- good: strong fit for the resume
- adjacent: plausible but weaker/indirect fit
- bad: poor fit or clearly mismatched

Be strict. Consider role family, skills, seniority, and domain.
Do not infer fit from title alone.

Resume:
{resume_text}

Job title:
{job.get('title', '')}

Job description:
{job.get('description', '')}

Job metadata:
{json.dumps({k: job.get(k) for k in ('company', 'location', 'seniority_band', 'domain', 'date_posted')}, ensure_ascii=False)}
"""


async def _label_with_model(
    client: OpenRouterClient,
    model: str,
    resume_text: str,
    job: dict,
) -> dict:
    messages = [
        {"role": "system", "content": "Return valid JSON only."},
        {"role": "user", "content": _job_prompt(resume_text, job)},
    ]
    raw = await client._call(
        model,
        messages,
        700,
        0.0,
        extra_body={"response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "job_relevance_label",
                "strict": True,
                "schema": JSON_SCHEMA,
            },
        }},
        max_retries=1,
    )
    if raw is None:
        return {"label": "bad", "confidence": 0.0, "reasons": ["no response"]}
    parsed = _extract_json(raw)
    return parsed if isinstance(parsed, dict) else {"label": "bad", "confidence": 0.0, "reasons": ["unparseable"]}


async def _label_job(resume_text: str, job: dict, api_key: str) -> tuple[dict, str]:
    model_votes: list[tuple[str, dict]] = []
    client = OpenRouterClient(api_key=api_key, models=CONSENSUS_MODELS)
    client._probe_cache = {}  # type: ignore[attr-defined]
    for model in CONSENSUS_MODELS[:2]:
        result = await _label_with_model(client, model, resume_text, job)
        model_votes.append((model, result))

    labels = [vote.get("label", "bad") for _, vote in model_votes]
    counts = Counter(labels)
    if counts:
        top_label, top_count = counts.most_common(1)[0]
    else:
        top_label, top_count = "bad", 0

    status = "agreement" if len(set(labels)) == 1 else "split"
    if top_count < 2 and len(CONSENSUS_MODELS) >= 3:
        tiebreak = await _label_with_model(client, CONSENSUS_MODELS[2], resume_text, job)
        labels.append(tiebreak.get("label", "bad"))
        counts = Counter(labels)
        top_label, top_count = counts.most_common(1)[0]
        status = "split_resolved" if top_count >= 2 else "unresolved"
    elif top_count < 2:
        status = "unresolved"

    if not top_label:
        top_label = "bad"
        status = "fallback"

    if status == "split" and top_count >= 2:
        status = "split_resolved"
    elif status == "split":
        status = "unresolved"

    await client.close()
    return {"label": top_label, "status": status, "votes": model_votes}, top_label


async def relabel_snapshot(snapshot: Path, resume: str, labels_path: Path, api_key: str, limit: int | None = None) -> None:
    raw = snapshot.read_text(encoding="utf-8")
    jobs = json.loads(raw)
    resume_dir = Path("/Users/examplecandidate/Projects/job_ranker/resumes")
    resume_pdf = resume_dir / f"{resume}.pdf"
    resume_txt = resume_dir / f"{resume}.json"
    if resume_pdf.exists():
        from tools.rank_resume_existing_corpus import _load_resume_text

        resume_text = _load_resume_text(resume_pdf)
    elif resume_txt.exists():
        resume_text = resume_txt.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"Missing resume source for {resume}")

    labels_by_resume: dict[str, dict[str, str]] = {}
    if labels_path.exists():
        labels_by_resume = json.loads(labels_path.read_text(encoding="utf-8"))

    resume_labels: dict[str, str] = dict(labels_by_resume.get(resume, {}))
    status_counts: Counter[str] = Counter()
    start_idx = len(resume_labels)
    end_idx = min(len(jobs), limit) if limit is not None else len(jobs)
    for idx, job in enumerate(jobs[start_idx:end_idx], start=start_idx + 1):
        result, label = await _label_job(resume_text, job, api_key)
        resume_labels[_job_id(job)] = label
        status_counts[result["status"]] += 1
        labels_by_resume[resume] = resume_labels
        labels_path.write_text(json.dumps(labels_by_resume, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[{idx:02d}/30] {job.get('title','')[:80]} -> {label} ({result['status']})")
    print("Status counts:", dict(status_counts))


def main() -> None:
    parser = argparse.ArgumentParser(description="Relabel a benchmark snapshot using OpenRouter consensus.")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--resume", required=True, type=str)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required")
    asyncio.run(relabel_snapshot(args.snapshot, args.resume, args.labels, api_key, args.limit))


if __name__ == "__main__":
    main()
