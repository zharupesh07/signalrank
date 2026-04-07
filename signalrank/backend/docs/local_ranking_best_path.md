# Local Ranking Best Path

## Current Best Local Script

The current best local script is:

- `signalrank/backend/tools/rank_resume_existing_corpus.py`

This is still the best default path because it consistently outperformed the semantic-only experiments on overall top-20/top-30 quality across the benchmark resumes.

The current best operating mode is:

- deterministic-first profile extraction and ranking
- generic query builder with query tiers and caps
- profile-aware broadening
- scrape cache reuse
- optional LLM verification only on the top slice

The semantic sidecar script:

- `signalrank/backend/tools/semantic_resume_job_search.py`

is useful as an additional retrieval lane, but not as the primary ranking path.

## Why This Script Is Best

`rank_resume_existing_corpus.py` is currently the best local path because it has the strongest balance of:

- quality
- determinism
- speed
- debuggability
- operational safety

Observed outcomes from the local runs:

- `Ayush`: strong SAP SD / SAP functional alignment; local and Railway results are both broadly good.
- `Example`: strong AI/ML alignment; local hybrid runs were slightly more precise than Railway because they kept a better mix of AI, ML, platform, and applied roles.
- `Abhijeet`: this profile improved the most under the deterministic-first refactors.
- `Aditya`: partially improved, but still suffers from software-engineering drift when his recent network identity is not weighted strongly enough.
- `Vivek`: improved from very weak results to somewhat usable adjacent roles, but still remains the hardest profile.

## Improvements That Were Made

The most important improvements so far were:

1. Remove domain-specific parsing and scoring branches.
This removed brittle SAP/network-specific logic and forced the pipeline into a more general architecture.

2. Introduce a deterministic profile schema.
The parser now extracts reusable signals such as:

- target roles
- skills
- domains
- industries
- seniority
- locations
- must-have terms
- avoid terms

3. Add a generic deterministic query builder.
This was a major improvement. It introduced:

- query dedupe
- query caps
- `core`, `adjacent`, and `exploratory` query tiers
- more `role + must-have skill` queries

4. Tighten LLM usage.
LLM suggestions now survive only when they have enough textual support from the resume, which reduced hallucinated or weak role suggestions.

5. Add scrape-cache reuse.
This materially improved repeat-run speed and made overlapping windows practical.

6. Add query audit metadata.
This made it possible to diagnose when the search layer was spending too much budget on broad titles instead of targeted queries.

7. Add profile-aware narrowing for semantic retrieval.
This improved semantic-search architecture, but semantic retrieval alone still did not beat the deterministic title-led baseline.

## What Caused the Most Significant Improvement

The most significant improvement came from the deterministic query-builder work, not from LLMs and not from embeddings.

In practice, the biggest gains came from:

- shaping queries into `core`, `adjacent`, and `exploratory`
- capping broad-title exploration
- increasing `role + skill` queries
- penalizing known drift lanes such as generic support, QA, and broad full-stack roles for profiles where those are not the target

This improved:

- `Vivek`: reduced obvious support/full-stack drift
- `Aditya`: moved some results toward network/systems instead of pure software
- `Ayush`: tightened the SAP functional lane
- `Example`: preserved strong AI/ML recall while keeping the profile more explainable

By contrast:

- semantic retrieval alone did not produce better overall rankings
- LLM verification was useful for auditing top results but was not the main driver of retrieval quality

## What Did Not Help Enough

These changes were useful, but not the main quality breakthrough:

- semantic-only retrieval over the cached or unified corpus
- broad LLM-generated query expansion
- very broad generic-title search without stronger filtering

Main lesson:

- the current bottleneck is still retrieval precision and profile intent, not lack of semantic tooling

## Where Results Are Still Weak

The main remaining weak cases are:

### Aditya

Problem:

- too much software-engineering drift
- older backend evidence is still influencing ranking too much

Needed:

- stronger recency weighting
- stronger network/firewall/network-automation role-family matching
- stronger penalties for generic software roles when network evidence is missing

### Vivek

Problem:

- the market uses inconsistent titles for innovation, prototyping, IoT, and applied AI work
- title-led retrieval misses some good jobs
- broadening can quickly drift into generic consultant or software roles

Needed:

- better keyword-lane retrieval for innovation, IoT, rapid prototyping, conversational AI, smart systems, R&D, and labs
- stronger negative penalties for irrelevant consultant/support/software roles
- semantic retrieval used as a sidecar only after deterministic narrowing

## Best Current Architecture

The best current architecture is:

1. Parse the resume into a deterministic profile.
2. Build deterministic queries from the profile.
3. Scrape and cache jobs.
4. Rank with deterministic feature scoring.
5. Optionally run LLM verification only on the top `N`.
6. Optionally union semantic-retrieval candidates with deterministic candidates, then rerank deterministically.

This keeps:

- retrieval and ranking reproducible
- LLM usage bounded
- debugging tractable
- cost and runtime under control

## How To Improve Further

The next wave of improvements should focus on the deterministic core, especially:

1. Recency-weighted profile extraction.
Recent roles should dominate older or training-era roles.

2. Role-family normalization.
Examples:

- `Software Engineer` should only count strongly if the description contains the right family signals.
- For `Example`, that means ML/platform/LLM/data-pipeline evidence.
- For `Aditya`, that means network/firewall/automation/infra evidence.

3. Stronger negative penalties.
Penalize off-lane roles more aggressively when profile intent is clear.

4. Description-aware ranking.
Title similarity is too noisy by itself. The scorer should lean more on:

- required skills overlap
- role-family terms in the description
- must-have evidence
- exclusion terms

5. Better benchmark evaluation.
For each profile, manually label top results as:

- good fit
- adjacent fit
- bad fit

This gives us a real offline tuning set.

## Recommended Next Steps

### Next Step 1

Implement the Version 3 scorer rewrite in `rank_resume_existing_corpus.py`:

- explicit feature columns
- configurable weights
- stronger role-family and negative-term handling
- clearer feature dumps in artifacts

This is the highest-value next step.

### Next Step 2

Add recency-weighted intent extraction:

- recent titles and recent project signals should dominate
- older roles should still contribute, but less

This should help `Aditya` the most.

### Next Step 3

Add a deterministic keyword-lane retrieval path for hard profiles such as `Vivek`:

- innovation
- IoT
- rapid prototyping
- conversational AI
- smart systems
- R&D
- labs

This should remain generic, not resume-specific hardcoding.

### Next Step 4

Keep semantic retrieval as a sidecar retrieval lane only:

- run inside the profile-shaped corpus slice
- union with deterministic hits
- rerank with the deterministic scorer

Do not make semantic retrieval the primary source of truth.

### Next Step 5

Use LLMs only in bounded roles:

- optional schema-constrained profile extraction when the resume is ambiguous
- optional top-`N` verification
- optional explanation generation

Avoid using LLMs as the main retrieval or scoring engine.

## Bottom Line

The best local path today is still `rank_resume_existing_corpus.py`.

The most important quality gains so far came from:

- deterministic profile extraction
- deterministic query shaping
- query dedupe/caps
- profile-aware drift reduction

The next major quality improvement is likely to come from a stronger deterministic scorer with recency-weighted intent, not from adding more LLMs or more embedding-only retrieval.
