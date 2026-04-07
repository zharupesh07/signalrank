# Standalone Ranker Refactor Plan

## Goal

Build a self-contained standalone resume ranker that:

- works for any resume and any domain
- does not depend on the backend DB
- remains deterministic by default
- uses LLMs only at controlled boundaries
- produces versioned benchmark artifacts so each change can be evaluated

## Design Principles

- No DB dependency.
- No hardcoded domain branches such as SAP, network automation, or similar special cases.
- Deterministic retrieval and ranking is the default.
- LLM usage is optional, bounded, schema-constrained, and never the core retrieval mechanism.
- Every run must emit benchmark artifacts that are comparable version to version.

## Pipeline

1. Resume ingestion
- Input formats: `.pdf`, `.docx`, `.txt`, `.md`
- Output: normalized `resume_text`

2. Profile extraction
- Deterministic mode extracts:
  - recent titles
  - target roles
  - skills
  - domains
  - industries
  - seniority hints
  - locations
  - must-have terms
  - avoid terms
  - query candidates
- Optional LLM mode returns the exact same schema as strict JSON.

3. Query generation
- Deterministic:
  - derive search queries from target roles, titles, and high-signal phrases
  - dedupe aggressively
  - apply configurable caps
- Optional LLM:
  - may propose extra candidates
  - deterministic filtering decides the final query set

4. Job scraping
- Use pluggable source adapters such as JobSpy
- Normalize all results into a common `JobRecord`

5. Job normalization
- tokenize title, description, company, and location
- build reusable feature text
- compute reusable vectors once per run

6. Deterministic ranking
- Feature-based score made from:
  - semantic similarity
  - title-role similarity
  - skill overlap
  - location compatibility
  - recency
  - seniority compatibility
  - negative-term penalties
- All weights configurable.
- All feature values written to artifacts for inspection.

7. Optional verifier
- Only runs on top `N` jobs.
- Returns strict JSON labels such as:
  - `strong_fit`
  - `adjacent_fit`
  - `weak_fit`
  - `reject`
- Must cite grounded evidence from the resume and job text.
- Can rerank within top `N`, but must not retrieve new jobs.

## Supported Approaches

1. `det_profile__det_rank`
- deterministic profile extraction
- deterministic ranking
- cheapest and most reproducible baseline

2. `llm_profile__det_rank`
- LLM profile extraction
- deterministic ranking
- likely best general-purpose mode for quality

3. `det_profile__det_rank__llm_verify_topn`
- deterministic profile and ranking
- LLM verification on top `N`

4. `llm_profile__det_rank__llm_verify_topn`
- highest-quality evaluation mode
- slowest and most expensive

## Non-Goals

- No end-to-end LLM ranking across all jobs.
- No hidden hardcoded domain boosts in scoring.
- No requirement that the output match the backend exactly.
- No backend DB reads or writes.

## Versioned Roadmap

### Version 0
- current standalone baseline
- known issue: domain-biased parsing and scoring

### Version 1
- generic deterministic profile extractor
- remove hardcoded domain branches
- preserve simple deterministic scoring

### Version 2
- generic query builder
- remove hardcoded query defaults
- add deterministic query dedupe and caps

### Version 3
- deterministic scorer rewrite
- explicit feature columns
- configurable weights
- vectorized NumPy implementation

### Version 4
- optional LLM profile extraction
- strict JSON schema
- deterministic fallback on failure

### Version 5
- optional LLM verifier for top `N`
- grounded evidence-only reranking

### Version 6
- performance pass
- multithreading or multiprocessing where safe:
  - scrape queries in parallel
  - parse pages in parallel where useful
  - verify top `N` concurrently with bounded parallelism
- cache reusable vectors/features inside run artifacts

## Benchmark Plan

## Resume Set

Primary benchmark resumes:

- `Ayush`
- `Aditya`
- `Abhijeet`
- `Vivek`

Optional additional benchmark:

- `Example`

## Benchmark Matrix

For every version:

- run each resume
- run each supported approach
- use the same scrape source set
- use the same scrape window, for example `168h`
- use the same result caps
- fix any random seed when randomness is present

## Metrics

Performance metrics:

- total runtime
- runtime by stage:
  - parse
  - query generation
  - scrape
  - feature build
  - rank
  - verify

Corpus metrics:

- jobs scraped
- jobs deduped
- jobs ranked

Quality metrics:

- top 5 precision by manual review
- top 10 precision by manual review
- number of obvious outliers in top 20
- overlap between approaches
- rank stability across reruns

## Artifacts Per Run

- `config.json`
- `profile.<approach>.json`
- `queries.<approach>.json`
- `jobs.raw.json`
- `jobs.normalized.json`
- `ranked.<approach>.json`
- `summary.<approach>.md`
- `benchmark.json`
- `comparison.json`
- `comparison.md`

## Directory Layout

- `signalrank/backend/tmp/standalone_ranker/<version>/<timestamp>-<resume>-<approach>/...`
- `signalrank/backend/tmp/standalone_ranker/<version>/<timestamp>-comparison/...`

## Decision Criteria

A new version is accepted only if:

- top 10 quality improves or stays equal
- obvious outliers decrease
- runtime remains within acceptable bounds
- behavior remains stable across reruns

If complexity rises and quality does not improve, reject the change.

## Immediate Next Step

Implement Version 1:

- replace hardcoded domain parsing with a generic deterministic profile extractor
- keep deterministic ranking
- preserve the current four-approach evaluation shape
- emit benchmark artifacts consistently for every run
