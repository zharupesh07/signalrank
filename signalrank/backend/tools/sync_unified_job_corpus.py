from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import semantic_resume_job_search as semantic


DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / "tmp" / "resume_existing_corpus_rank" / "_scrape_cache"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "unified_job_corpus"
DEFAULT_DB_PATH = DEFAULT_OUTPUT_DIR / "unified_job_corpus.sqlite"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "unified_jobs.csv"
DEFAULT_EMBEDDING_INDEX_DIR = DEFAULT_OUTPUT_DIR / "embeddings"


@dataclass(frozen=True)
class BackupArtifacts:
    backup_dir: Path
    db_backup: Path | None
    csv_backup: Path | None
    embedding_backups: list[Path]
    signalrank_db_backup: Path | None


def _parse_date(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:10] if len(raw) >= 10 else raw


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs (
            job_url TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            description TEXT,
            date_posted TEXT,
            source_terms_json TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            latest_query_term TEXT,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL,
            cache_key TEXT,
            query_term TEXT,
            query_location TEXT,
            country TEXT,
            fetched_at TEXT,
            hours_old INTEGER,
            max_results INTEGER,
            source_file TEXT NOT NULL,
            inserted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_job_sources_job_url ON job_sources(job_url);
        CREATE TABLE IF NOT EXISTS corpus_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _backup_existing_artifacts(output_dir: Path) -> BackupArtifacts:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = output_dir / "backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    def _copy_if_exists(path: Path) -> Path | None:
        if not path.exists():
            return None
        dest = backup_dir / path.name
        shutil.copy2(path, dest)
        return dest

    embedding_backups: list[Path] = []
    embeddings_dir = output_dir / "embeddings"
    if embeddings_dir.exists():
        for path in sorted(embeddings_dir.glob("*")):
            if path.is_file():
                dest = backup_dir / path.name
                shutil.copy2(path, dest)
                embedding_backups.append(dest)

    signalrank_db = Path(__file__).resolve().parents[1] / "signalrank.db"
    return BackupArtifacts(
        backup_dir=backup_dir,
        db_backup=_copy_if_exists(output_dir / "unified_job_corpus.sqlite"),
        csv_backup=_copy_if_exists(output_dir / "unified_jobs.csv"),
        embedding_backups=embedding_backups,
        signalrank_db_backup=_copy_if_exists(signalrank_db),
    )


def _load_cache_payloads(cache_dir: Path) -> tuple[dict[str, semantic.JobDoc], list[dict[str, Any]]]:
    jobs_by_url: dict[str, semantic.JobDoc] = {}
    source_rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for path in sorted(cache_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        query = payload.get("query") or {}
        cache_key = path.stem
        fetched_at = str(payload.get("fetched_at") or "")
        hours_old = int(payload.get("hours_old") or 0)
        max_results = int(payload.get("max_results") or 0)
        for item in payload.get("jobs") or []:
            if not isinstance(item, dict):
                continue
            job_url = str(item.get("job_url") or "").strip()
            if not job_url:
                continue
            existing = jobs_by_url.get(job_url)
            source_term = str(query.get("term") or "").strip()
            source_terms = semantic._dedupe_strs(
                ([*existing.source_terms] if existing else []) + ([source_term] if source_term else []),
                limit=20,
            )
            jobs_by_url[job_url] = semantic.JobDoc(
                job_url=job_url,
                title=str(item.get("title") or (existing.title if existing else "") or ""),
                company=str(item.get("company") or (existing.company if existing else "") or ""),
                location=str(item.get("location") or (existing.location if existing else "") or ""),
                description=str(item.get("description") or (existing.description if existing else "") or ""),
                date_posted=_parse_date(str(item.get("date_posted") or (existing.date_posted if existing else "") or "")),
                source_terms=tuple(source_terms),
            )
            source_rows.append({
                "job_url": job_url,
                "cache_key": cache_key,
                "query_term": source_term,
                "query_location": str(query.get("location") or ""),
                "country": str(query.get("country") or ""),
                "fetched_at": fetched_at,
                "hours_old": hours_old,
                "max_results": max_results,
                "source_file": str(path),
                "inserted_at": now,
            })
    return jobs_by_url, source_rows


def _write_corpus_db(
    *,
    db_path: Path,
    jobs_by_url: dict[str, semantic.JobDoc],
    source_rows: list[dict[str, Any]],
    backup: BackupArtifacts,
) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    conn.execute("DELETE FROM job_sources")
    conn.execute("DELETE FROM jobs")
    now = datetime.now(timezone.utc).isoformat()
    job_rows = [
        (
            job.job_url,
            job.title,
            job.company,
            job.location,
            job.description,
            job.date_posted,
            json.dumps(list(job.source_terms)),
            len(job.source_terms),
            now,
            now,
            job.source_terms[0] if job.source_terms else None,
            json.dumps({
                "source_terms": list(job.source_terms),
                "description_chars": len(job.description or ""),
            }),
        )
        for job in jobs_by_url.values()
    ]
    conn.executemany(
        """
        INSERT INTO jobs (
            job_url, title, company, location, description, date_posted,
            source_terms_json, source_count, first_seen_at, last_seen_at,
            latest_query_term, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        job_rows,
    )
    conn.executemany(
        """
        INSERT INTO job_sources (
            job_url, cache_key, query_term, query_location, country,
            fetched_at, hours_old, max_results, source_file, inserted_at
        ) VALUES (
            :job_url, :cache_key, :query_term, :query_location, :country,
            :fetched_at, :hours_old, :max_results, :source_file, :inserted_at
        )
        """,
        source_rows,
    )
    meta = {
        "updated_at": now,
        "job_count": len(job_rows),
        "source_row_count": len(source_rows),
        "backup_dir": str(backup.backup_dir),
        "signalrank_db_backup": str(backup.signalrank_db_backup) if backup.signalrank_db_backup else "",
    }
    conn.execute("DELETE FROM corpus_meta")
    conn.executemany(
        "INSERT INTO corpus_meta(key, value) VALUES(?, ?)",
        [(key, json.dumps(value) if not isinstance(value, str) else value) for key, value in meta.items()],
    )
    conn.commit()
    conn.close()
    return meta


def _write_csv(csv_path: Path, jobs_by_url: dict[str, semantic.JobDoc]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "job_url",
                "title",
                "company",
                "location",
                "date_posted",
                "source_count",
                "source_terms",
                "description",
            ],
        )
        writer.writeheader()
        for job in sorted(jobs_by_url.values(), key=lambda item: (item.date_posted or "", item.title.lower(), item.job_url), reverse=True):
            writer.writerow({
                "job_url": job.job_url,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "date_posted": job.date_posted or "",
                "source_count": len(job.source_terms),
                "source_terms": " | ".join(job.source_terms),
                "description": job.description,
            })


def _build_unified_embedding_index(
    *,
    jobs_by_url: dict[str, semantic.JobDoc],
    output_dir: Path,
    allow_remote_model_download: bool,
    cpu_threads: int,
    batch_size: int,
    max_description_chars: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs = list(jobs_by_url.values())
    spec = semantic.MODEL_CATALOG["minilm"]
    vectors, meta = semantic._load_or_build_job_embeddings(
        jobs,
        spec,
        index_dir=output_dir,
        refresh=True,
        allow_remote_download=allow_remote_model_download,
        cpu_threads=cpu_threads,
        batch_size=batch_size,
        max_description_chars=max_description_chars,
    )
    return {
        "model": spec.name,
        "repo_id": spec.repo_id,
        "embedding_dim": int(vectors.shape[1]) if vectors.size else 0,
        "jobs_indexed": len(jobs),
        "cache_hit": bool(meta.get("cache_hit")),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up and sync a unified job corpus database, CSV, and embedding index")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--embedding-index-dir", default=str(DEFAULT_EMBEDDING_INDEX_DIR))
    parser.add_argument("--allow-remote-model-download", action="store_true")
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-description-chars", type=int, default=1800)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    db_path = Path(args.db_path).expanduser().resolve()
    csv_path = Path(args.csv_path).expanduser().resolve()
    embedding_index_dir = Path(args.embedding_index_dir).expanduser().resolve()
    if not cache_dir.exists():
        raise FileNotFoundError(cache_dir)

    backup = _backup_existing_artifacts(output_dir)
    jobs_by_url, source_rows = _load_cache_payloads(cache_dir)
    corpus_meta = _write_corpus_db(db_path=db_path, jobs_by_url=jobs_by_url, source_rows=source_rows, backup=backup)
    _write_csv(csv_path, jobs_by_url)
    embedding_meta = _build_unified_embedding_index(
        jobs_by_url=jobs_by_url,
        output_dir=embedding_index_dir,
        allow_remote_model_download=bool(args.allow_remote_model_download),
        cpu_threads=int(args.cpu_threads),
        batch_size=int(args.batch_size),
        max_description_chars=int(args.max_description_chars),
    )
    print(json.dumps({
        "backup_dir": str(backup.backup_dir),
        "db_path": str(db_path),
        "csv_path": str(csv_path),
        "jobs": len(jobs_by_url),
        "source_rows": len(source_rows),
        "embedding": embedding_meta,
    }, indent=2))


if __name__ == "__main__":
    main()
