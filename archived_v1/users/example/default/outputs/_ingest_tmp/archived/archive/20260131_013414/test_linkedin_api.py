#!/usr/bin/env python3
import http.client
import json
import os
from urllib.parse import quote

import pandas as pd
from dotenv import load_dotenv

# --------------------------------------------------
# ENV
# --------------------------------------------------
load_dotenv()
API_KEY = os.getenv("RAPIDAPI_KEY")

if not API_KEY:
    raise SystemExit("RAPIDAPI_KEY not found in .env")

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
TITLE = "mlops engineer"
LOCATION = "India"
LIMIT = 5  # keep VERY small for testing

title_q = quote(f'"{TITLE}"')
location_q = quote(f'"{LOCATION}"')


# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def fetch(conn, endpoint, headers):
    conn.request("GET", endpoint, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    return json.loads(raw.decode("utf-8"))


def preview(name, payload):
    print(f"\n==============================")
    print(f"{name} – PAYLOAD INSPECTION")
    print("==============================")

    # Case 1: list response (this is what active-jb-7d returns)
    if isinstance(payload, list):
        print("Top-level type: list")
        print(f"Rows: {len(payload)}")

        if not payload:
            print("Empty list")
            return

        df = pd.DataFrame(payload)
        print("\nColumns:")
        print(df.columns.tolist())

        print("\nFirst 2 rows:")
        print(df.head(2).T)
        return

    # Case 2: dict response (some APIs wrap in {data: [...]})
    if isinstance(payload, dict):
        print("Top-level type: dict")
        print("Keys:", payload.keys())

        data = payload.get("data", [])
        print(f"Rows: {len(data)}")

        if not data:
            return

        df = pd.DataFrame(data)
        print("\nColumns:")
        print(df.columns.tolist())

        print("\nFirst 2 rows:")
        print(df.head(2).T)
        return

    print("Unknown payload type:", type(payload))


# --------------------------------------------------
# active-jb-7d (LinkedIn Job Board)
# --------------------------------------------------
conn_jb = http.client.HTTPSConnection(
    "linkedin-job-search-api.p.rapidapi.com",
    timeout=20,
)

headers_jb = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "linkedin-job-search-api.p.rapidapi.com",
}

endpoint_jb = (
    f"/active-jb-7d?"
    f"limit={LIMIT}&offset=0"
    f"&title_filter={title_q}"
    f"&location_filter={location_q}"
    f"&description_type=text"
)

payload_jb = fetch(conn_jb, endpoint_jb, headers_jb)
preview("active-jb-7d", payload_jb)

# --------------------------------------------------
# active-ats-7d (ATS postings)
# --------------------------------------------------
conn_ats = http.client.HTTPSConnection(
    "active-jobs-db.p.rapidapi.com",
    timeout=20,
)

headers_ats = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "active-jobs-db.p.rapidapi.com",
}

endpoint_ats = (
    f"/active-ats-7d?"
    f"limit={LIMIT}&offset=0"
    f"&title_filter={title_q}"
    f"&location_filter={location_q}"
    f"&description_type=text"
)

payload_ats = fetch(conn_ats, endpoint_ats, headers_ats)
preview("active-ats-7d", payload_ats)
