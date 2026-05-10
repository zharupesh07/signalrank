from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import or_, select

from api.database import AsyncSessionLocal, ensure_runtime_schema_compatibility
from api.models import Application, JobRaw, JobResult
from batch.job_availability import (
    EXPIRED_REASON,
    AvailabilityDecision,
    JobAvailability,
    MAX_AVAILABILITY_CANDIDATE_URLS,
    availability_candidate_urls,
    check_job_availability,
    is_job_board_url,
    reliable_job_availability,
)

OUT_DIR = Path("tmp/job_availability")


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _location_tokens(value: str | None) -> set[str]:
    raw = _norm(value)
    return {
        token
        for token in raw.split()
        if len(token) >= 3 and token not in {"india", "remote", "hybrid", "onsite"}
    }


def _locations_compatible(left: str | None, right: str | None) -> bool:
    left_tokens = _location_tokens(left)
    right_tokens = _location_tokens(right)
    if not left_tokens or not right_tokens:
        return True
    return bool(left_tokens & right_tokens)


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        text = str(url or "").strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped


async def backfill_availability_urls(*, apply: bool) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        jobs = (await db.execute(select(JobRaw))).scalars().all()
        direct_by_key: dict[
            tuple[str, str],
            list[tuple[str | None, str]],
        ] = defaultdict(list)
        for job in jobs:
            key = (_norm(job.company), _norm(job.title))
            if not key[0] or not key[1]:
                continue
            candidates = availability_candidate_urls(
                job.job_url,
                availability_urls=job.availability_urls,
            )
            direct_candidates = [
                url for url in candidates if not is_job_board_url(url)
            ][:MAX_AVAILABILITY_CANDIDATE_URLS]
            for url in direct_candidates:
                direct_by_key[key].append((job.location, url))

        updated = 0
        with_direct_candidate = 0
        added_from_duplicate = 0
        for job in jobs:
            key = (_norm(job.company), _norm(job.title))
            candidates = availability_candidate_urls(
                job.job_url,
                availability_urls=job.availability_urls,
            )
            before = set(candidates)
            for location, url in direct_by_key.get(key, []):
                if _locations_compatible(job.location, location):
                    candidates.append(url)
            candidates = availability_candidate_urls(
                job.job_url,
                availability_urls=_dedupe_urls(candidates),
            )
            if any(not is_job_board_url(url) for url in candidates):
                with_direct_candidate += 1
            if len(set(candidates) - before) > 0:
                added_from_duplicate += 1
            if candidates != (job.availability_urls or []):
                updated += 1
                if apply:
                    job.availability_urls = candidates

        if apply and updated:
            await db.commit()

    return {
        "jobs_seen": len(jobs),
        "jobs_updated": updated,
        "jobs_with_direct_candidate": with_direct_candidate,
        "jobs_with_duplicate_direct_candidate_added": added_from_duplicate,
        "applied": apply,
    }


async def _load_sweep_rows(limit: int | None) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(JobResult, JobRaw)
            .join(JobRaw, JobRaw.id == JobResult.job_id)
            .where(
                or_(
                    JobResult.archived_by_llm.is_(None),
                    JobResult.archived_by_llm.is_(False),
                )
            )
            .order_by(
                JobRaw.ingested_at.asc(),
                JobResult.final_score.desc().nulls_last(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "job_result_id": result.id,
                "user_id": result.user_id,
                "job_id": job.id,
                "job_url": job.job_url,
                "availability_urls": job.availability_urls or [],
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "site": job.site,
                "final_score": result.final_score,
                "ingested_at": job.ingested_at.isoformat() if job.ingested_at else None,
                "date_posted": job.date_posted.isoformat() if job.date_posted else None,
            }
            for result, job in rows
        ]


async def sweep_availability(
    *,
    limit: int | None,
    concurrency: int,
    timeout: float,
    decision_timeout: float,
    archive: bool,
) -> dict[str, Any]:
    rows = await _load_sweep_rows(limit)
    started = time.monotonic()
    checked = 0
    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[dict[str, Any]] = []
    decision_tasks: dict[tuple[str, tuple[str, ...]], asyncio.Task] = {}
    decision_lock = asyncio.Lock()

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:

        async def checker(url: str):
            return await check_job_availability(url, client=client)

        async def classify_row(row: dict[str, Any]) -> AvailabilityDecision:
            try:
                return await asyncio.wait_for(
                    reliable_job_availability(
                        row["job_url"],
                        availability_urls=row["availability_urls"],
                        checker=checker,
                    ),
                    timeout=decision_timeout,
                )
            except TimeoutError:
                return AvailabilityDecision(
                    availability=JobAvailability(
                        url=row["job_url"],
                        status="unknown",
                        reason="Availability decision timed out",
                    ),
                    checked_urls=tuple(
                        availability_candidate_urls(
                            row["job_url"],
                            availability_urls=row["availability_urls"],
                        )
                    ),
                )

        async def get_decision(row: dict[str, Any]):
            key = (row["job_url"], tuple(row["availability_urls"]))
            async with decision_lock:
                task = decision_tasks.get(key)
                if task is None:
                    task = asyncio.create_task(classify_row(row))
                    decision_tasks[key] = task
            return await task

        async def one(row: dict[str, Any]) -> dict[str, Any]:
            nonlocal checked
            async with sem:
                decision = await get_decision(row)
                availability = decision.availability
                checked += 1
                if checked % 250 == 0 or checked == len(rows):
                    elapsed = time.monotonic() - started
                    print(
                        f"checked {checked}/{len(rows)} in {elapsed:.1f}s",
                        flush=True,
                    )
                return {
                    **row,
                    "checked_url": availability.url,
                    "checked_urls": list(decision.checked_urls),
                    "status": availability.status,
                    "reason": availability.reason,
                    "status_code": availability.status_code,
                    "final_url": availability.final_url,
                    "confirm_status": (
                        decision.confirmation.status if decision.confirmation else None
                    ),
                    "confirm_reason": (
                        decision.confirmation.reason if decision.confirmation else None
                    ),
                    "confirm_status_code": (
                        decision.confirmation.status_code
                        if decision.confirmation
                        else None
                    ),
                    "confirm_final_url": (
                        decision.confirmation.final_url
                        if decision.confirmation
                        else None
                    ),
                }

        results = await asyncio.gather(*(one(row) for row in rows))

    tracker_archived = 0
    archiveable = [row for row in results if row["status"] == "expired"]
    if archive and archiveable:
        async with AsyncSessionLocal() as db:
            for row in archiveable:
                result = await db.get(JobResult, row["job_result_id"])
                if result is None:
                    continue
                result.archived_by_llm = True
                result.archival_reason = (row["reason"] or EXPIRED_REASON)[:500]
                tracker_rows = (
                    await db.execute(
                        select(Application).where(
                            Application.user_id == row["user_id"],
                            Application.job_id == row["job_id"],
                            Application.status != "archived",
                        )
                    )
                ).scalars().all()
                for tracker_row in tracker_rows:
                    tracker_row.status = "archived"
                    tracker_archived += 1
            await db.commit()

    status_counts = Counter(row["status"] for row in results)
    site_counts = Counter(row["site"] or "unknown" for row in results)
    status_by_site = {
        site: dict(Counter(row["status"] for row in results if row["site"] == site))
        for site in sorted(site_counts)
    }
    direct_candidate_count = sum(
        1
        for row in results
        if any(not is_job_board_url(url) for url in row["checked_urls"])
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not archive,
        "limit": limit,
        "concurrency": concurrency,
        "timeout": timeout,
        "decision_timeout": decision_timeout,
        "checked": len(results),
        "unique_decisions_checked": len(decision_tasks),
        "archiveable_expired": len(archiveable),
        "archived": len(archiveable) if archive else 0,
        "tracker_archived": tracker_archived,
        "status_counts": dict(status_counts),
        "site_counts": dict(site_counts),
        "status_by_site": status_by_site,
        "jobs_with_direct_candidate_checked": direct_candidate_count,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    return {"summary": summary, "jobs": results}


def _write_report(payload: dict[str, Any], *, archive: bool) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mode = "archive" if archive else "dry_run"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"full_db_availability_{mode}_{stamp}.json"
    csv_path = OUT_DIR / f"full_db_availability_{mode}_{stamp}.csv"
    summary_path = OUT_DIR / f"full_db_availability_{mode}_summary_{stamp}.json"
    jobs = payload["jobs"]

    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    summary_path.write_text(
        json.dumps(payload["summary"], indent=2, default=str) + "\n"
    )
    if jobs:
        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(jobs[0].keys()))
            writer.writeheader()
            writer.writerows(jobs)
    return {
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "summary_path": str(summary_path),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill and check deterministic job availability."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--decision-timeout", type=float, default=30.0)
    parser.add_argument("--skip-backfill", action="store_true")
    parser.add_argument("--apply-backfill", action="store_true")
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()

    await ensure_runtime_schema_compatibility()
    backfill = None
    if not args.skip_backfill:
        backfill = await backfill_availability_urls(apply=args.apply_backfill)
        print(json.dumps({"backfill": backfill}, indent=2), flush=True)

    payload = await sweep_availability(
        limit=args.limit,
        concurrency=args.concurrency,
        timeout=args.timeout,
        decision_timeout=args.decision_timeout,
        archive=args.archive,
    )
    if backfill is not None:
        payload["summary"]["backfill"] = backfill
    paths = _write_report(payload, archive=args.archive)
    print(json.dumps({"summary": payload["summary"], **paths}, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
