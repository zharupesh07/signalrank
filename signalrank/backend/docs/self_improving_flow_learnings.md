# Self-Improving Job Matching Learnings

## Goal

Build a flow where the user only uploads a resume and the system improves over time without requiring manual query tuning.

The intended path is:

1. Resume upload.
2. Deterministic profile extraction.
3. Retrieval over a shared job corpus.
4. Deterministic ranking.
5. Optional LLM verification on the top slice.
6. Feedback capture and offline tuning.
7. Periodic updates to the profile schema, query planner, and scorer.

## What We Learned

### 1. Deterministic-first is the right default

The best local results still come from the deterministic pipeline in:

- `signalrank/backend/tools/rank_resume_existing_corpus.py`

This path is currently stronger than semantic-only retrieval because it is:

- more reproducible
- easier to debug
- cheaper to run
- less sensitive to noisy titles
- safer to deploy incrementally

Semantic retrieval is useful, but mainly as a sidecar retrieval lane.

### 2. Query shaping matters more than more search volume

The biggest quality improvement came from query shaping, not from adding more jobs or more model calls.

The improvements that mattered most were:

- splitting queries into `core`, `adjacent`, and `exploratory`
- capping broad-title exploration
- forcing more `role + skill` queries
- deduping query candidates
- auditing what gets trimmed
- penalizing obvious drift lanes

This improved results for:

- `Ayush`
- `Example`
- `Aditya`
- `Vivek`

It was especially important for profiles where generic titles are too noisy.

### 3. LLMs are useful only at bounded boundaries

LLMs helped when they were constrained to:

- schema-constrained profile extraction
- top-`N` verification
- suggesting adjacent role phrases with deterministic filtering

LLMs did not help when they were used as the core retrieval engine.

The main failure mode was hallucinated or overly broad role expansion. That is why LLM hints now need strong textual support before they survive into the query plan.

### 4. Semantic search improves recall, not final quality by itself

Embedding-based search was useful for hard-to-title resumes like `Vivek`, but semantic retrieval alone was not better overall than the deterministic title-led baseline.

Observed behavior:

- semantic search surfaced at least one useful `Conversational AI` result for `Vivek`
- it also introduced a lot of consultant and generic software noise
- the deterministic pipeline still ranked stronger adjacent roles more reliably

The best architecture is:

- semantic retrieval inside a profile-shaped corpus slice
- union with deterministic candidates
- deterministic reranking of the union

### 5. Profile-aware narrowing is necessary

Searching the entire corpus for every resume is too broad.

The better pattern is:

1. Build a deterministic profile.
2. Derive profile-specific filters.
3. Narrow the corpus.
4. Search inside the narrowed slice.
5. Rerank deterministically.

This helps especially for mixed resumes:

- `Aditya` should not inherit too much stale backend bias
- `Example` should remain AI/platform-shaped
- `Vivek` should remain innovation/IoT/prototyping-shaped

### 6. Recency weighting is a major gap

The most important remaining improvement is stronger recency weighting in profile extraction and scoring.

We saw this especially in `Aditya`:

- older backend roles still influence retrieval too much
- newer network identity should dominate more

The same idea applies to any resume with a clear career pivot.

### 7. Negative penalties matter

Good ranking is not only about adding positive matches.

We also need explicit penalties for:

- generic support roles
- QA drift
- broad full-stack drift
- off-lane consultant titles

This was especially important for `Vivek`, where broadening too much caused noisy support and generic software matches.

### 8. Caching and incremental refresh are required

Repeated searches should not rescrape the same jobs.

We learned that the system should reuse:

- scrape results
- normalized jobs
- embeddings
- corpus metadata

For overlapping windows, the system should fetch only the missing recent slice, not redo the entire query.

This matters for:

- speed
- cost
- idempotency
- repeatability

### 9. Docker is useful when resource limits are enforced

We saw a local host hang from embedding large corpora. That was resource exhaustion, not an application-layer security issue.

The safe pattern for heavier work is:

- Docker or another container boundary
- explicit CPU and memory limits
- network disabled unless downloads are intentional
- model downloads opt-in only

Without limits, Docker alone does not solve host contention.

### 10. One shared corpus is the right operational model

Instead of many ad hoc CSVs and DBs, the best path is:

- one unified SQLite corpus
- one unified CSV export
- one embedding index
- backups before each sync

That gives us:

- one place to inspect source metadata
- one place to rerun retrieval experiments
- one place to keep embeddings current

## Current Best Architecture

The best end-to-end design is:

1. Resume upload.
2. Build a deterministic profile.
3. Generate profile-aware retrieval queries.
4. Search a shared corpus with both deterministic and semantic retrieval.
5. Rerank with a deterministic feature scorer.
6. Verify only the top slice with an LLM if needed.
7. Store all intermediate artifacts.
8. Capture feedback from user behavior.
9. Tune query rules and scorer weights offline.

This keeps the app:

- deterministic by default
- self-improving over time
- explainable
- operationally safe

## What Should Be Hardcoded

Hardcode:

- the profile schema
- feature definitions
- ranking stages
- artifact layout
- cache keys
- evaluation metrics
- safety limits

Do not hardcode:

- resume-specific branches
- per-candidate special cases
- one-off domain logic like `if SAP then...`
- free-form LLM ranking decisions

## What Should Be Learned Over Time

Learn or tune over time:

- role-family synonyms
- query templates
- feature weights
- negative keyword sets
- semantic probes that improve recall
- ranking thresholds
- recency weighting

These should be updated from evidence, not from manual case-by-case edits.

## How To Self-Improve Safely

The system should improve through controlled feedback loops, not through live self-editing.

Useful feedback signals:

- clicks
- saves
- dismissals
- applications started
- applications completed
- recruiter replies
- thumbs up/down on jobs

Then use those signals in three offline loops:

1. Query tuning
Learn which query families produce accepted results for each profile family.

2. Scoring tuning
Adjust feature weights against labeled outcomes.

3. Taxonomy tuning
Grow role-family and skill mappings from successful jobs and accepted recommendations.

## Main Remaining Weak Spots

### Aditya

Current problem:

- too much generic software drift
- older backend history still over-influences ranking

Fixes needed:

- recency-weighted profile extraction
- stronger network/firewall/network automation role families
- stronger penalties for generic software results

### Vivek

Current problem:

- innovation/IoT/prototyping jobs are harder to retrieve by title alone
- broadening can drift into generic consultant or support roles

Fixes needed:

- keyword-lane retrieval for innovation, IoT, labs, prototyping, conversational AI, R&D
- stronger negative penalties for support/full-stack drift
- semantic retrieval only as a sidecar lane

## Performance Improvements To Keep

Keep these behaviors:

- cache scrape windows
- reuse embeddings
- batch inference
- truncated descriptions
- low thread counts for local embedding work
- top-`N` only LLM verification
- incremental refresh for overlapping time windows

These are the main levers that kept the flow fast enough to iterate on.

## Robustness Improvements To Keep

Keep these safeguards:

- strict JSON boundaries for LLM output
- deterministic fallback on LLM failure
- container limits for heavy work
- backups before corpus sync
- stage-level run artifacts
- versioned benchmark comparisons

These reduce the chance that a bad model call, a large embedding job, or a scrape issue breaks the whole flow.

## Best Next Steps

1. Implement a stronger deterministic scorer rewrite.
The scorer should expose explicit feature columns and configurable weights.

2. Add recency-weighted intent extraction.
This is the highest-value fix for mixed-history resumes.

3. Add stronger role-family normalization.
Generic titles should only count when the description supports the correct lane.

4. Add an offline evaluation set.
Label top-20 results as good, adjacent, or bad for each benchmark resume.

5. Keep semantic retrieval as a sidecar.
Use it to recover recall, not to replace deterministic ranking.

6. Keep LLMs bounded.
Use them for extraction and verification, not for full ranking.

## Bottom Line

The system should be:

- user-simple: upload a resume and wait
- deterministic in the core
- self-improving through logged feedback and offline tuning
- resilient under repeated runs
- fast enough to rerun frequently

That is the right balance between quality, performance, and maintainability.
