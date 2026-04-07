# Semantic Search Learnings

## 2026-04-05

- Host-local semantic indexing over the cached corpus can saturate a laptop CPU and cause the machine to hang if we try to embed a large corpus with multiple models at once.
- The main risk observed so far is resource exhaustion, not an obvious application-layer security vulnerability.
- Remote model downloads are a supply-chain and operational risk; they should be opt-in and ideally happen in a controlled environment.
- The safer defaults for the standalone semantic search flow are:
  - batch ONNX inference
  - low CPU thread count
  - truncated job descriptions
  - lightweight models by default
  - heavier models such as `embeddinggemma` only by explicit opt-in
- Docker is useful here only if it is paired with strict runtime limits. Running the same workload inside an unrestricted container would still risk host contention.
- Current recommended container limits for local experimentation:
  - `--cpus=2`
  - `--memory=6g`
  - `--pids-limit=256`
  - `--read-only` where practical
  - network disabled for normal runs, enabled only when deliberately downloading pinned models
- A dedicated semantic-search Docker image is preferable to reusing the main backend image because it isolates the experimental dependency/runtime profile and makes CPU/memory limits explicit.
- Constrained Docker execution stayed stable on the same machine that previously hung during the host-local run.
- On Vivek's 60-day corpus, `all-MiniLM-L6-v2` semantic retrieval over cached jobs produced one clearly useful top result that the title-led pipeline also hinted at but did not rank first:
  - `Consultant | Conversational AI | Bengaluru | Customer Strategy & Design`
- The same MiniLM semantic run also introduced substantial consultant noise from Genpact (`Data Engineer`, `Power Automate`, `.NET + Azure`, `Java Developer`), so semantic retrieval alone is not better overall than the existing deterministic title-led baseline.
- Compared against the current 60-day title-led baseline for Vivek:
  - semantic retrieval was better at surfacing one resume-specific conversational-AI consulting role
  - deterministic title-led retrieval remained better overall because it surfaced stronger adjacent innovation/AI architecture roles like Honeywell `Lead AI Engr` and `COMPUTER VISION / AI SYSTEMS ARCHITECT`
- `bge-small-en-v1.5` was still too slow for a practical first-pass local comparison inside the constrained Docker container, even after model download. It should be treated as optional, not default, for local experimentation.
- Current practical recommendation:
  - keep deterministic/title-led retrieval as the default source of truth
  - use semantic retrieval as a sidecar retrieval lane
  - union semantic hits with deterministic hits, then rerank with the deterministic scorer

## Unified Corpus Sync

- Added a repeatable sync step that creates:
  - one unified SQLite corpus DB
  - one unified CSV export
  - one unified MiniLM embedding index
- The sync step also creates timestamped backups before rewriting artifacts.
- Current unified artifact set:
  - DB: `tmp/unified_job_corpus/unified_job_corpus.sqlite`
  - CSV: `tmp/unified_job_corpus/unified_jobs.csv`
  - embeddings: `tmp/unified_job_corpus/embeddings/`
- Current synced corpus metadata:
  - `1883` unique jobs in `jobs`
  - `3537` source rows in `job_sources`
- Vivek rerun against the unified SQLite corpus produced the same top semantic/hybrid results as the prior cache-based MiniLM run for the 60-day lookback, which is expected because the 60-day filtered slice was the same `1812` jobs.
- Practical value of the unified corpus is operational consistency:
  - one place to back up
  - one place to inspect source metadata
  - one place to point future semantic retrieval runs

## Profile-Aware Corpus Narrowing

- The semantic retrieval path now applies a deterministic profile-aware corpus prefilter before embedding search.
- This means the unified corpus is still global, but each resume searches inside a role/skill-shaped slice of that corpus rather than across all jobs equally.
- Early examples:
  - Example filter terms centered on `Platform Engineer`, `Machine Learning Engineer`, `Architect`, and related AI/platform roles.
  - Aditya filter terms centered on `Network Automation Engineer`, `Network Engineer`, and related systems roles, but backend drift is still present because the resume retains older backend-engineering evidence.
- This is the right architecture:
  - one shared corpus
  - per-resume deterministic narrowing
  - semantic retrieval inside the narrowed slice
  - union with deterministic candidates
  - final deterministic reranking
- Follow-up improvement likely needed:
  - weight recent titles more heavily than older training roles so resumes like Aditya do not inherit as much stale backend bias.
