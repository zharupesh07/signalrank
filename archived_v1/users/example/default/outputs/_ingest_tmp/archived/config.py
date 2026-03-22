# config.py

# ---------- Ranking ----------
MIN_SEMANTIC_SCORE = 0.15
UNKNOWN_COMPANY_PENALTY = 0.6
YOE_MISMATCH_PENALTY = 0.6
JOB_DESC_MIN_LEN = 500

# ---------- LLM ----------
USE_LLM_SKILL_NORM = True
USE_LLM_EXPLANATIONS = True
SKILL_NORM_BATCH_SIZE = 8
TOP_K_EXPLAIN = 5

# ---------- Job quality ----------
QUALITY_SHORT_DESC_PENALTY = 0.85

# ---------- Scraping ----------
CACHE_TTL_HOURS = 6
MAX_RETRIES = 3
BASE_BACKOFF = 2.0
JITTER_RANGE = (0.3, 1.5)

# ---------- Defaults ----------
DEFAULT_COUNTRY = "India"
DEFAULT_HOURS_OLD = 168
