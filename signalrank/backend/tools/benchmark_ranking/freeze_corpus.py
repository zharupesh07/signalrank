"""
Snapshot the unified job corpus to a dated parquet file for reproducible benchmarks.

Usage:
    uv run python tools/benchmark_ranking/freeze_corpus.py --corpus-path <path/to/corpus.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

FROZEN_DIR = Path(__file__).parent / "frozen"
MANIFEST_PATH = FROZEN_DIR / "manifest.json"


def freeze(corpus_path: Path) -> Path:
    FROZEN_DIR.mkdir(exist_ok=True)
    raw = corpus_path.read_text(encoding="utf-8")
    sha8 = hashlib.sha256(raw.encode()).hexdigest()[:8]
    jobs = json.loads(raw)
    df = pd.DataFrame(jobs)
    out_path = FROZEN_DIR / f"{date.today().isoformat()}_{sha8}.parquet"
    df.to_parquet(out_path, index=False)

    manifest: dict = {}
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text())
    manifest[sha8] = {"path": str(out_path), "date": date.today().isoformat(), "count": len(jobs)}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"Frozen {len(jobs)} jobs → {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze unified job corpus to parquet.")
    parser.add_argument("--corpus-path", required=True, type=Path)
    args = parser.parse_args()
    freeze(args.corpus_path)


if __name__ == "__main__":
    main()
