# import duckdb

# con = duckdb.connect("users/example/default/jobs.duckdb")

# df = con.execute("""
# SELECT
#     COUNT(*) AS total,
#     COUNT(*) FILTER (WHERE date_posted = TIMESTAMP '1970-01-01 00:00:00') AS bad_dates
# FROM jobs_raw
# """).df()

# print(df)

# import duckdb

# con = duckdb.connect("users/example/default/jobs.duckdb")

# df = con.execute("""
# UPDATE jobs_raw
# SET date_posted = NULL
# WHERE date_posted = TIMESTAMP '1970-01-01 00:00:00'
# """)
# print(df)
# print("Bad epoch dates cleared")


# import duckdb

# con = duckdb.connect("users/example/default/jobs.duckdb")

# con.execute("""
# DELETE FROM ranked_snapshots
# WHERE user = 'example' AND use_case = 'default'
# """)

# print("Old ranked snapshots deleted")

from pathlib import Path

import pandas as pd
from storage.db import JobStore

store = JobStore(Path("users/example/default/jobs.duckdb"))

frames = []
for p in Path("cache").glob("query_*.csv"):
    frames.append(pd.read_csv(p))

df = pd.concat(frames, ignore_index=True)
df = df.drop_duplicates(subset=["job_url"])

store.upsert_raw_jobs(
    df,
    user="example",
    use_case="default",
)
