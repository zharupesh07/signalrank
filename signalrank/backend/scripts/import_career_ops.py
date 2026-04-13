from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.database import AsyncSessionLocal
from batch.career_ops_import import import_career_ops_workspace


async def _run(args) -> None:
    async with AsyncSessionLocal() as db:
        summary = await import_career_ops_workspace(
            db,
            workspace_path=args.workspace_path,
            user_email=args.user_email,
            pending_only=args.pending_only,
            limit=args.limit,
            dry_run=args.dry_run,
        )

    print(
        json.dumps(
            {
                "workspace_path": summary.workspace_path,
                "user_email": summary.user_email,
                "candidate_count": summary.candidate_count,
                "imported_count": summary.imported_count,
                "inserted_count": summary.inserted_count,
                "updated_count": summary.updated_count,
                "scored_count": summary.scored_count,
                "skipped_count": summary.skipped_count,
                "run_id": summary.run_id,
                "error_count": len(summary.errors),
                "errors": summary.errors,
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Career-Ops candidates into SignalRank")
    parser.add_argument("--workspace-path", required=True)
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--pending-only", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
