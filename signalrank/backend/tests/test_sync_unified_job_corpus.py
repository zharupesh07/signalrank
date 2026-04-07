from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools import sync_unified_job_corpus as script


def test_sync_unified_job_corpus_loads_cache_and_writes_csv_and_db(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    payload = {
        "fetched_at": "2026-04-05T12:00:00+00:00",
        "hours_old": 360,
        "max_results": 50,
        "query": {"term": "Innovation Lead", "location": "Bangalore", "country": "India"},
        "jobs": [
            {
                "job_url": "https://example.com/1",
                "title": "Innovation Lead",
                "company": "Example",
                "location": "Bangalore",
                "description": "IoT and rapid prototyping",
                "date_posted": "2026-04-05",
            }
        ],
    }
    (cache_dir / "one.json").write_text(json.dumps(payload))

    jobs_by_url, source_rows = script._load_cache_payloads(cache_dir)
    output_dir = tmp_path / "out"
    backup = script._backup_existing_artifacts(output_dir)
    db_path = output_dir / "unified.sqlite"
    csv_path = output_dir / "unified.csv"

    meta = script._write_corpus_db(db_path=db_path, jobs_by_url=jobs_by_url, source_rows=source_rows, backup=backup)
    script._write_csv(csv_path, jobs_by_url)

    assert meta["job_count"] == 1
    assert csv_path.exists()

    conn = sqlite3.connect(db_path)
    job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    source_count = conn.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0]
    conn.close()

    assert job_count == 1
    assert source_count == 1
