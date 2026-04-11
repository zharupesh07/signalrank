from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from api.database import AsyncSessionLocal
from api.models import JobRaw
from batch.context import build_context
from domain.embeddings import EmbeddingEngine, build_resume_embedding_text, unload_embedding_engine
from ranking.v4.db_scorer import _apply_structured_comparison
from ranking.v4.extraction import extract_profile_v4
from ranking.v4.scorer import score_jobs

logger = logging.getLogger(__name__)


def _extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _strip_latex_commands(text: str) -> str:
    text = re.sub(r"(?m)^\s*%.*$", "", text)
    text = text.replace(r"\item", "\n- ")
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)

    simple_macros = [
        "textbf",
        "underline",
        "emph",
        "position",
        "cvsection",
        "cvparagraph",
        "mobile",
        "email",
        "homepage",
        "github",
        "linkedin",
        "twitter",
        "name",
        "cventry",
    ]
    for macro in simple_macros:
        text = re.sub(rf"\\{macro}\{{([^}}]*)\}}", r"\1", text)

    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", lambda m: f" {m.group(1) or ''} ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("&", " and ")
    text = text.replace("\\", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _load_resume_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".tex":
        return _strip_latex_commands(text)
    return text


async def _load_jobs(days: int | None) -> list[dict]:
    cutoff = None
    if days is not None and days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    cols = (
        JobRaw.id,
        JobRaw.job_url,
        JobRaw.title,
        JobRaw.company,
        JobRaw.description,
        JobRaw.location,
        JobRaw.site,
        JobRaw.date_posted,
        JobRaw.role_clusters,
        JobRaw.job_profile,
        JobRaw.embedding,
        JobRaw.ingested_at,
    )
    jobs: list[dict] = []
    async with AsyncSessionLocal() as db:
        stmt = select(*cols).order_by(JobRaw.ingested_at.desc())
        if cutoff is not None:
            stmt = stmt.where(JobRaw.ingested_at >= cutoff)
        rows = (await db.execute(stmt)).all()
        for row in rows:
            jobs.append(
                {
                    "id": str(row.id),
                    "job_url": row.job_url,
                    "title": row.title,
                    "company": row.company,
                    "description": row.description,
                    "location": row.location,
                    "site": row.site,
                    "date_posted": row.date_posted.isoformat() if isinstance(row.date_posted, datetime) else row.date_posted,
                    "role_clusters": row.role_clusters,
                    "job_profile": row.job_profile,
                    "embedding": list(row.embedding) if row.embedding is not None else None,
                    "ingested_at": row.ingested_at.isoformat() if isinstance(row.ingested_at, datetime) else row.ingested_at,
                }
            )
    return jobs


def _profile_override(structured_resume_json: Path | None) -> dict:
    if structured_resume_json is None:
        return {}
    return {"v4_profile": {"structured_resume_json_path": str(structured_resume_json)}}


async def _rank(args: argparse.Namespace) -> Path:
    resume_path = Path(args.resume_path).expanduser().resolve()
    structured_resume_json = (
        Path(args.structured_resume_json).expanduser().resolve()
        if args.structured_resume_json
        else None
    )
    resume_text = _load_resume_text(resume_path)
    cfg = build_context(user_id="standalone", resume_text=resume_text, config_overrides=_profile_override(structured_resume_json)).config
    profile = extract_profile_v4(
        resume_text,
        config_overrides=_profile_override(structured_resume_json),
    )

    engine = EmbeddingEngine(cfg)
    resume_embedding_text = build_resume_embedding_text(
        resume_text=resume_text,
        distilled=None,
        cfg=cfg,
        use_case="ranking",
    )
    profile.resume_embedding = engine.embed([resume_embedding_text])[0].tolist()

    jobs = await _load_jobs(args.days)
    logger.info("Loaded %d jobs from local corpus", len(jobs))
    scored = score_jobs(jobs, profile, dedupe=args.dedupe_display)
    scored = _apply_structured_comparison(scored, profile, resume_text)

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = resume_path.stem
    json_path = out_dir / f"{stem}_standalone_rank_{stamp}.json"
    tsv_path = out_dir / f"{stem}_standalone_rank_{stamp}.tsv"

    top = scored[: args.limit]
    json_path.write_text(json.dumps(top, indent=2, default=str), encoding="utf-8")

    with tsv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            [
                "rank",
                "title",
                "company",
                "location",
                "site",
                "final_score",
                "fit_band",
                "confidence_band",
                "title_score",
                "skills_score",
                "location_score",
                "company_score",
                "summary",
            ]
        )
        for idx, item in enumerate(top, 1):
            features = item.get("features", {})
            writer.writerow(
                [
                    idx,
                    item.get("title"),
                    item.get("company"),
                    item.get("location"),
                    item.get("site"),
                    round(float(item.get("final_score", 0.0)), 4),
                    item.get("fit_band"),
                    item.get("confidence_band"),
                    round(float(features.get("title_similarity", 0.0) * 100), 2),
                    round(float(features.get("skill_overlap", 0.0) * 100), 2),
                    round(float(features.get("location_match", 0.0) * 100), 2),
                    round(float(features.get("company_tier_score", 0.0) * 100), 2),
                    item.get("explanation_summary"),
                ]
            )

    print(
        json.dumps(
            {
                "resume_path": str(resume_path),
                "structured_resume_json": str(structured_resume_json) if structured_resume_json else None,
                "jobs_loaded": len(jobs),
                "jobs_scored": len(scored),
                "top_limit": args.limit,
                "output_json": str(json_path),
                "output_tsv": str(tsv_path),
            },
            indent=2,
        )
    )
    for idx, item in enumerate(top[:20], 1):
        print(
            json.dumps(
                {
                    "rank": idx,
                    "title": item.get("title"),
                    "company": item.get("company"),
                    "final_score": round(float(item.get("final_score", 0.0)), 2),
                    "fit_band": item.get("fit_band"),
                    "summary": item.get("explanation_summary"),
                }
            )
        )

    unload_embedding_engine()
    return tsv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone v4 ranking over the full local jobs corpus.")
    parser.add_argument("--resume-path", required=True)
    parser.add_argument("--structured-resume-json")
    parser.add_argument("--days", type=int, default=None, help="Optional ingested_at lookback in days")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "tmp" / "standalone_rank_local_corpus"),
    )
    parser.add_argument(
        "--dedupe-display",
        action="store_true",
        help="Deduplicate same title/company pairs before ranking output",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_rank(args))


if __name__ == "__main__":
    main()
