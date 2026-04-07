# Standalone Resume Ranker

This document describes the standalone existing-corpus ranking tool at [tools/rank_resume_existing_corpus.py](/Users/examplecandidate/Projects/job_ranker/signalrank/backend/tools/rank_resume_existing_corpus.py).

## What It Is

This script ranks a resume against the jobs already stored in the backend database.

It is meant for:
- comparing ranking approaches without scraping again
- debugging ranking quality for a specific resume
- checking top 50 results and analyzing the top 20
- testing deterministic vs LLM-assisted ranking behavior on the same persisted corpus

It does not scrape new jobs.

## What It Does

Given a resume file, the script:

1. extracts resume text from `.pdf`, `.docx`, `.txt`, or `.md`
2. builds a parsed profile from the resume
3. creates a temporary user/profile in the backend DB
4. runs ranking against the existing persisted jobs corpus only
5. saves structured outputs for later analysis

## Supported Approaches

The script supports 4 ranking approaches:

- `deterministic_baseline`
  deterministic resume parse, agentic matching disabled
- `llm_parse_only`
  OpenRouter resume parse merged into deterministic parse, agentic matching disabled
- `agentic_only`
  deterministic resume parse, agentic matching enabled
- `llm_parse_plus_agentic`
  OpenRouter resume parse merged into deterministic parse, agentic matching enabled

## Default Behavior

If you run the script without choosing an approach, it uses:

- `deterministic_baseline`

This is the cheapest and safest mode for initial ranking checks.

## Requirements

Run from [signalrank/backend](/Users/examplecandidate/Projects/job_ranker/signalrank/backend).

Minimum requirements:

- backend dependencies installed via `uv`
- database configured and reachable
- existing jobs already present in `jobs_raw`

For LLM-backed approaches, you also need:

- `OPENROUTER_API_KEY` set in the backend environment

## Basic Usage

Run a single deterministic ranking pass:

```bash
uv run python tools/rank_resume_existing_corpus.py \
  --resume /absolute/path/to/resume.pdf \
  --approach deterministic_baseline
```

Run only LLM parsing without agentic reranking:

```bash
uv run python tools/rank_resume_existing_corpus.py \
  --resume /absolute/path/to/resume.pdf \
  --approach llm_parse_only
```

Run deterministic parse with agentic matching:

```bash
uv run python tools/rank_resume_existing_corpus.py \
  --resume /absolute/path/to/resume.pdf \
  --approach agentic_only
```

Run full LLM parse plus agentic matching:

```bash
uv run python tools/rank_resume_existing_corpus.py \
  --resume /absolute/path/to/resume.pdf \
  --approach llm_parse_plus_agentic
```

Run all 4 approaches and compare them in one shot:

```bash
uv run python tools/rank_resume_existing_corpus.py \
  --resume /absolute/path/to/resume.pdf \
  --compare-all
```

## Important Flags

- `--resume`
  path to the resume file
- `--approach`
  run exactly one approach
- `--compare-all`
  run all 4 approaches and write a combined comparison report
- `--top-k`
  how many ranked jobs to save, default `50`
- `--analysis-k`
  how many top jobs to expand in markdown summaries, default `20`
- `--output-dir`
  optional custom output directory
- `--label`
  optional label used in output naming

Backward-compatible alias:

- `--enable-llm`
  maps to `llm_parse_plus_agentic`

## Output Files

The script writes artifacts under:

- [tmp/resume_existing_corpus_rank](/Users/examplecandidate/Projects/job_ranker/signalrank/backend/tmp/resume_existing_corpus_rank)

For a single-approach run, it writes:

- `parsed_profile.<approach>.json`
- `top50.<approach>.json`
- `summary.<approach>.md`

For `--compare-all`, it also writes:

- `comparison.json`
- `comparison.md`

## What Each File Means

- `parsed_profile.<approach>.json`
  the parsed resume profile, parse metadata, and derived career intent used for ranking
- `top50.<approach>.json`
  the saved top ranked jobs for that approach
- `summary.<approach>.md`
  a readable markdown summary with parsed intent and expanded top 20 jobs
- `comparison.json`
  structured cross-approach comparison output
- `comparison.md`
  human-readable comparison report with top-title overlap and unique results per approach

## When To Use This

Use this tool when:

- you want to compare ranking approaches fairly on the same corpus
- you want to debug why a resume is getting weak matches
- you want to inspect ranking quality without waiting for scraping
- you want repeatable top 50 / top 20 artifacts for analysis

Do not use this tool when:

- you need fresh jobs scraped from providers
- you want to validate scraping quality or query generation quality

## Notes

- all approaches rank against the same persisted corpus
- the script creates temporary DB users/profiles for ranking and cleans them up afterward
- LLM-backed approaches can be much slower than deterministic ranking
- if an LLM-backed approach fails, the error is recorded in that approach’s output instead of silently falling back
