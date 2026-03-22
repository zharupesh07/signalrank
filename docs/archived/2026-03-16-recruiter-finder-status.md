# Recruiter Finder — Current Status

**Date:** 2026-03-16
**Status:** In Progress — 200 contacts, 69 companies. 8 companies still missing.

---

## What Was Built This Session

### 1. Recruiter Quality Scoring (`recruiter_finder.py`)
Three pure functions added to `job_ranker/scrapers/recruiter_finder.py`:

- **`_clean_title(raw)`** — truncates DDG snippet noise at first `\n`, `|`, or ` - `; caps at 120 chars
- **`score_recruiter(recruiter_title, job_title)`** — returns 0.0–1.0; 0=not recruiter, 0.3=baseline, 0.5=technical affinity, 0.7=domain keyword match
- **`dedup_top_n(contacts, n=2)`** — groups by `job_url`, scores+sorts, returns top-2 most relevant per job

### 2. Dashboard: Recruiter Columns (`dashboard.py`)
`job_ranker/app/pages/dashboard.py` now shows recruiter info joined by company name:
- Table view: **Recruiter** (name) + **Recruiter LinkedIn** (clickable) columns
- Cards view: `🤝 [Name](linkedin_url)` inline under score

Join is by `company.strip().lower()` — not `job_url` — since manually-run batches use placeholder URLs.

New helper: `load_recruiter_map()` — cached, returns `{company_lower: {name, linkedin_url}}`.

### 3. New Search Fallbacks (`recruiter_finder.py`)
Added to strategy stack after DDG → SerpAPI:

- **Strategy 2d: Brave Search API** (`BRAVE_API_KEY`) — `search_linkedin_brave()` — $5/mo min, NOT actually free
- **Strategy 2e: Bing Web Search API** (`BING_SEARCH_KEY`) — `search_linkedin_bing()` — free 1k/month via Azure

### 4. SerpAPI Feature Flag
`SERPAPI_ENABLED=false` in `.env` disables SerpAPI even if key is present.
Set in `RecruiterFinder.__init__` — reads `os.getenv("SERPAPI_ENABLED", "true")`.

---

## Current DB State

**200 contacts, 69 companies** (as of 2026-03-16)

### Target Companies Found
| Company | Contacts |
|---------|----------|
| Microsoft, Google, Meta, Apple, Netflix | 2 each |
| Mastercard, Visa, Deutsche Bank, BNY Mellon | 2 each |
| FIS, Fiserv, Paytm, Razorpay | 2 each |
| Uber, Salesforce, Airbnb, Postman, PhonePe | 2 each |
| Druva, Red Hat, Siemens, Amdocs | 2 each (Druva: 1) |
| VMware, Atlassian, Barclays, Cisco, JetBrains | 1-2 each |
| Icertis, Akamai, Helpshift | 1-2 each |

### Still Missing (8 companies — DDG consistently returns empty)
- Elastic
- Intuit
- Rippling
- NICE
- PubMatic
- Searce
- NielsenIQ
- Avalara

---

## Pending Next Step

**Implement Apollo.io strategy** for the 8 missing companies.

Apollo.io is purpose-built for finding recruiters:
- Free tier: 50 exports/month (no card needed)
- Returns: name, title, verified email, LinkedIn URL
- API: `https://api.apollo.io/v1/mixed_people/search`
- Filter by: `organization_names`, `person_titles` (recruiter/talent), `person_locations` (India)

### Apollo Implementation Plan

**New function** in `recruiter_finder.py`:
```python
APOLLO_SEARCH = "https://api.apollo.io/v1/mixed_people/search"

def search_linkedin_apollo(
    company: str, apollo_key: str, domain: Optional[str],
    job_url: str, job_title: str, job_score: str,
    location: str = "india",
) -> List[RecruiterContact]:
    """Apollo.io people search — free 50 exports/month (APOLLO_API_KEY)."""
    ...
    payload = {
        "api_key": apollo_key,
        "q_organization_name": company,
        "person_titles": ["recruiter", "talent acquisition", "hr manager", "people partner"],
        "person_locations": ["India"],
        "page": 1,
        "per_page": MAX_RESULTS,
    }
    # POST to APOLLO_SEARCH
    # Parse: item["name"], item["title"], item["linkedin_url"], item["email"]
```

**Wire into `RecruiterFinder.__init__`:**
```python
self.apollo_key = os.getenv("APOLLO_API_KEY", "")
```

**Wire into `find()` as Strategy 2f** (after Bing, only if all others return 0):
```python
if not all_contacts and self.apollo_key:
    all_contacts.extend(search_linkedin_apollo(...))
```

**Add to `.env.example`:**
```
# Apollo.io API key — recruiter search, free 50 exports/month
# https://app.apollo.io/#/settings/integrations/api
APOLLO_API_KEY=
```

**To use:** Sign up at apollo.io → Settings → Integrations → API → copy key → add to `.env`

### Missing Companies CSV (ready to run after Apollo is implemented)
File: `/tmp/apollo_missing.csv`
```
company,job_title,job_score,job_url
Elastic,Senior Software Engineer - ML,0.80,https://www.elastic.co/careers
Intuit,Senior AI/ML Engineer,0.82,https://jobs.intuit.com
Rippling,Senior Software Engineer - ML,0.77,https://rippling.com/careers
NICE,Senior Data/ML Engineer,0.70,https://careers.nice.com
PubMatic,Senior Data/ML Engineer,0.71,https://pubmatic.com/careers
Searce,Senior AI/Cloud Engineer,0.72,https://searce.com/careers
NielsenIQ,Senior Data/ML Engineer,0.69,https://nielseniq.com/careers
Avalara,Senior Software Engineer - Data,0.68,https://avalara.com/careers
```

---

## File Inventory (Changes This Session)

| File | Change |
|------|--------|
| `job_ranker/scrapers/recruiter_finder.py` | Added `_clean_title`, `score_recruiter`, `dedup_top_n`; Brave + Bing strategies; `SERPAPI_ENABLED` flag |
| `job_ranker/app/pages/dashboard.py` | Added `load_recruiter_map()`, Recruiter + Recruiter LinkedIn columns in Table + Cards views |
| `.env.example` | Added `SERPAPI_KEY`, `SERPAPI_ENABLED`, `BRAVE_API_KEY`, `BING_SEARCH_KEY` |
| `job_ranker/tests/test_recruiter_finder.py` | Full replacement — 31 tests covering `_clean_title`, `score_recruiter`, `dedup_top_n`, integration |

---

## Key Design Decisions

- **Join by company name** (not `job_url`) in dashboard — manually-run batches use placeholder URLs that don't match scraped job URLs
- **DDG is unreliable as primary** — silently returns empty after ~3 queries per IP session; workaround is long gaps (15+ min) between batches of 2-3 companies
- **Brave Search is NOT free** — contrary to initial assumption; requires paid plan ($5/mo min)
- **Apollo.io is the best free alternative** — purpose-built contact DB, 50 free exports/month, no card needed
