#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone

import pandas as pd
from config_loader import settings
from user_context import resolve_user_context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--use-case", help="Use case (optional)")
    args = parser.parse_args()

    ctx = resolve_user_context(
        user=args.user,
        use_case_override=args.use_case,
        require_resume=False,
    )

    path = ctx.outputs_dir / settings.outputs.ranked_jobs_file
    df = pd.read_csv(path)

    def age_days(d):
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).days
        except Exception:
            return None

    df["age_days"] = df["date_posted"].apply(age_days)

    print(df["age_days"].describe())


if __name__ == "__main__":
    main()
