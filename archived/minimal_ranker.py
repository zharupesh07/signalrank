import csv
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from jobspy import scrape_jobs
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ============================================================
# CONFIG
# ============================================================

SEARCH_QUERY = "ai platform engineer|ml platform engineer|mlops|llmops|genai|agentic systems|ai infrastructure|forward deployed engineer|developer productivity engineer"

TITLE_BLOCKLIST = {"trainee", "manager", "sales", "trainer", "junior"}

PREFERRED_COMPANIES = {
    "microsoft", "google", "openai", "nvidia", "databricks",
    "snowflake", "meta", "anthropic", "cohere"
}

DEPRIORITIZED_COMPANIES = {
    "amazon", "uber", "wipro", "infosys", "tcs",
    "accenture", "genpact", "ntt", "deloitte", "ey", "pwc"
}

PREFERRED_LOCATIONS = {
    "pune", "bangalore", "bengaluru", "hyderabad", "remote"
}

ROLE_WEIGHTS = {
    "agentic": 1.25,
    "mlops": 1.25,
    "platform": 1.2,
    "software": 0.75
}

SITE_WEIGHTS = {
    "linkedin": 1.1,
    "indeed": 1.0
}

MAX_DESC_WORDS = 3000

# ============================================================
# RESUME
# ============================================================

def load_resume():
    return """
    AI Platform Engineer, MLOps, LLM systems, LLMOps,
    production ML platforms, AI infrastructure,
    agent orchestration, CI/CD, Kubernetes, Terraform,
    cloud-native ML systems.
    """

# ============================================================
# SCRAPING
# ============================================================

def scrape_all_queries():
    queries = [q.strip() for q in SEARCH_QUERY.split("|") if q.strip()]
    all_rows = []

    for q in queries:
        print(f"[SCRAPE] Running query: {q}")

        try:
            jobs = scrape_jobs(
                site_name=["indeed", "linkedin"],
                search_term=q,
                location="India",
                results_wanted=1000,
                hours_old=360,
                country_indeed="India",
            )

            print(f"[SCRAPE] Found {len(jobs)} jobs for '{q}'")

            if isinstance(jobs, pd.DataFrame):
                all_rows.append(jobs)

        except Exception as e:
            print(f"[SCRAPE] Failed for '{q}': {e}")

    if not all_rows:
        return pd.DataFrame()

    df = pd.concat(all_rows, ignore_index=True)

    if "job_url" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=["job_url"])
        print(f"[SCRAPE] Deduplicated: {before} → {len(df)}")

    return df.reset_index(drop=True)

# ============================================================
# FILTERING
# ============================================================

def filter_jobs(df):
    df = df.copy()

    df["title"] = df["title"].fillna("").str.lower()
    df["company"] = df["company"].fillna("").str.lower()
    df["location"] = df["location"].fillna("").str.lower()
    df["description"] = df["description"].fillna("")
    df["site"] = df.get("site", "").fillna("").str.lower()

    df = df[~df["title"].apply(lambda t: any(b in t for b in TITLE_BLOCKLIST))]

    return df.reset_index(drop=True)

# ============================================================
# ROLE CLASSIFICATION (Improved)
# ============================================================

def classify_role(text):
    t = text.lower()

    agent_signals = sum(x in t for x in ["agent", "rag"])
    llm_signals = sum(x in t for x in ["llm", "ai"])

    if agent_signals >= 1 and llm_signals >= 1:
        return "agentic"

    if "mlops" in t or "llmops" in t:
        return "mlops"

    if "platform" in t or "infrastructure" in t:
        return "platform"

    return "software"

# ============================================================
# EXPERIENCE REGEX (Fixed)
# ============================================================

def extract_yoe(text):
    matches = re.findall(r"\b([1-9]\d?)\+?\s*(?:years|yrs)\b", str(text).lower())
    return [int(m) for m in matches]

# ============================================================
# RANKING
# ============================================================

def rank_jobs(df, resume_text):
    df = df.copy()

    # Limit description length
    df["short_desc"] = df["description"].apply(
        lambda x: " ".join(str(x).split()[:MAX_DESC_WORDS])
    )

    # Boost title by repeating it
    df["semantic_text"] = (
        df["title"] + " " + df["title"] + " " + df["short_desc"]
    )

    corpus = [resume_text] + df["semantic_text"].tolist()

    vectorizer = TfidfVectorizer(max_features=6000, stop_words="english")
    matrix = vectorizer.fit_transform(corpus)

    resume_vec = matrix[0]
    job_vecs = matrix[1:]

    similarities = cosine_similarity(resume_vec, job_vecs)[0]
    df["semantic_score"] = similarities

    # Role weight
    df["role"] = df["semantic_text"].apply(classify_role)
    df["role_weight"] = df["role"].map(ROLE_WEIGHTS)

    # Company weight
    def company_weight(c):
        if any(p in c for p in PREFERRED_COMPANIES):
            return 1.5
        if any(d in c for d in DEPRIORITIZED_COMPANIES):
            return 0.6
        return 1.0

    df["company_weight"] = df["company"].apply(company_weight)

    # Location weight
    df["location_weight"] = df["location"].apply(
        lambda l: 1.2 if any(p in l for p in PREFERRED_LOCATIONS) else 1.0
    )

    # Site weight
    df["site_weight"] = df["site"].apply(
        lambda s: SITE_WEIGHTS.get(s, 1.0)
    )

    df["final_score"] = (
        df["semantic_score"]
        * df["role_weight"]
        * df["company_weight"]
        * df["location_weight"]
        * df["site_weight"]
    )

    df = df.sort_values("final_score", ascending=False)

    return df.reset_index(drop=True)

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    resume_text = load_resume()

    jobs = scrape_all_queries()

    if jobs.empty:
        print("No jobs found.")
        exit()

    df = filter_jobs(jobs)

    ranked = rank_jobs(df, resume_text)

    print("\nTop 20 ranked jobs:\n")
    print(ranked[["title", "company", "location", "site", "final_score"]].head(20))

    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = outputs_dir / f"ranked_jobs_{timestamp}.csv"

    ranked.to_csv(
        filename,
        quoting=csv.QUOTE_NONNUMERIC,
        escapechar="\\",
        index=False,
    )

    print(f"\nSaved {filename}")