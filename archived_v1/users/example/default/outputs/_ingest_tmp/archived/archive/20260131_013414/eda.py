#!/usr/bin/env python3
import argparse

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

    df["norm_title"] = df["title"].str.lower().str.strip()
    df["norm_company"] = df["company"].str.lower().str.strip()

    grouped = df.loc[df.groupby(["norm_title", "norm_company"])["final_score"].idxmax()]

    top5 = grouped.sort_values("final_score", ascending=False).head(5)

    for _, row in top5.iterrows():
        print(f"{row['company']} | {row['title']} | {row['final_score']:.3f}")


if __name__ == "__main__":
    main()
