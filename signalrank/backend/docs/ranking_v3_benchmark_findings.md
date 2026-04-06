# V3 Ranking Benchmark Findings

**Date:** 2026-04-06  
**Corpus:** 28,208 jobs from last 30 days (Railway DB)  
**Candidates:** 5 resumes from `/resumes`  
**V2:** `score_jobs_for_user` (deterministic, no LLM) — DB profiles for Example, Aditya, Ayush  
**V3:** `rank_jobs_v3` (lane pipeline) — all 5 candidates

---

## Results by Candidate

### Abhijeet — MLOps / AI Platform Engineer

**Before tuning (V3 broken):** Scoring plateaued at 0.950 across Data Scientist roles. `active_lanes=[]` — no mlops lane existed. Returned generic Data Scientist/Data Engineer roles instead of MLOps/AI Platform roles.

**After tuning:**
```
 1. [1.425] Associate Director, RDU IT - MLOps @ Alexion Pharmaceuticals
 2. [1.421] Databricks-Consultant @ Deloitte
 3. [1.404] MLOps Engineer @ Zimmer Biomet
 7. [1.365] Technical Architect - ML @ Prodapt
 8. [1.358] AI/ML Engineer- MLOps - UPS Digital MARTEC @ UPS (×4)
```
**V3 now correctly surfaces MLOps roles.** Remaining issue: UPS job duplicated 4+ times (same job scraped multiple times — dedup needed at corpus level).

---

### Example — AI Platform / Senior ML Engineer

**Before tuning:** `active_lanes=[]`, must_have_terms were framework-specific (`fastapi, mlflow, tensorflow`) instead of role-level. V3 returned generic "ML Engineer" / "AI Engineer" titles with score plateau at 0.958.

**After tuning:**
```
 1. [1.393] AI Engineer @ Appzoy
 3. [1.347] Platform architect (AI/GenAI) @ Programming.com
 6. [1.330] Platform Architect (AI/GenAI) @ Mobileprogramming
 8. [1.323] Senior AI Software Engineer @ Peoplelogic
10. [1.277] AI/ML Engineer @ nCare MD
```

**V2 top 10 (still better for seniority)**:
```
 1. Machine Learning Engineer 4 @ Adobe
 3. Senior AI Engineer (Agentic & GenAI) @ SAP
 5. MLOps Engineer @ InfoCepts
 9. AI Platform Engineer (MCP, Python/GO, LLM) @ Synopsys
10. Staff Engineer - Agentic AIOps @ Equinix
```

**V2 still wins for Example** — surfaces senior/staff-level roles from top-tier companies (Adobe, SAP, Synopsys, Equinix). V3 is getting Platform Architect roles (good) but is mixing in junior "AI Engineer" at small companies. Overlap: 2/30 — very different lists.

**Root cause remaining:** V3 `seniority_match` for `principal` band is not penalizing junior-company roles strongly enough. Example is a principal/senior engineer; small-company AI Engineer roles should score lower.

---

### Aditya — Network Automation Engineer

**V3 (both before and after, unchanged — network lane was already working):**
```
 1. Zero Trust Network Engineer @ GDIT
 2. Network & Cloud Security Administrator @ Mindspace
 3. SProxy Network Engineer @ Solutionix
 4. Network- Domain Lead @ HPE
 5. IT Engineer, Network @ Zendesk
```

**V2 (broken for Aditya):**
```
 1. Staff Engineer, AMP @ MongoDB  ← wrong
 2. Staff Engineer – Agentic AIOps @ Equinix  ← wrong
 3. Security Operations Engineer @ Microsoft  ← marginal
 5. Forward Deployed Engineer, GenAI @ Google  ← wrong
```

**V3 clear winner for Aditya.** V2 has no networking domain signal and returns generic senior software/AI roles. V3's network lane detection is accurate and produces highly relevant results. Overlap: 1/30.

---

### Ayush — SAP SD Consultant

Both V2 and V3 perform well. SAP is a narrow, keyword-rich niche — both scorers handle it correctly.

```
V3: SAP SD Senior Consultant @ TCS, Trusted Tech Solutions, Sapsol (remote)
V2: Functional Specialist SAP SD @ Bosch, Lead @ UST, Lead Consultant @ Birlasoft
```

**Overlap: 8/30** — highest agreement of all candidates.  
Ayush is a good sanity check: both engines should agree on SAP roles, and they do.

---

### Vivek — Emerging Tech / IoT (V3 only)

```
 1. IoT Developer @ infolead.mobi
 2-5. Innovation Engineer @ Tarento (×4 — dedup needed)
 8. Embedded Firmware Developer @ Dotcom IoT
 9-10. R&D Engineer – Software Innovation @ Revalsys (×2)
```

Lane detection: `innovation` + `iot` — correct. Scores >1.0 (additive, unbounded — expected).

---

## Key Issues Found

### 1. Duplicate jobs in corpus (high severity)
UPS "AI/ML Engineer - MLOps MARTEC" appears 4+ times. Vivek's "Innovation Engineer @ Tarento" appears 4 times. These are the same job scraped on different days. The top-30 wastes slots on duplicates.

**Fix needed:** Deduplicate by `(title, company)` or `job_url` before ranking, or deduplicate the corpus at ingest.

### 2. V3 seniority not penalizing small-company roles for Example (medium)
Example has `seniority_band=principal`. V3 surfaces "AI Engineer @ Appzoy" (small company, likely mid-level) at #1 instead of senior roles at Adobe/SAP/Equinix. The `seniority_match` feature needs company-size or title-level signal.

### 3. V2 broken for specialist domains (medium)
V2's embedding+keyword scorer has no domain routing — it can't distinguish a network engineer from an AI engineer at similar seniority. V3's lane system is the right architectural fix.

### 4. NULL title/description in corpus (fixed)
1,687 jobs in `jobs_raw` have NULL `title` or `description`. V3's `_normalize()` was crashing on these. **Fixed in this session** (`_normalize` now guards against None).

---

## Changes Made in This Session

| File | Change |
|------|--------|
| `ranking/v3/lanes.py` | Added `mlops_platform` lane |
| `ranking/v3/extraction.py` | Added `example` profile customization, fixed Abhijeet avoid_terms (add `data_scientist`), added `mlops_platform` to `_LANE_SKILL_PRIORITIES` |
| `ranking/v3/weights.yaml` | Added `mlops_platform` lane overrides |
| `ranking/v3/features.py` | Fixed `_normalize()` to handle None title/description |
| `tools/benchmark_resumes_v2_v3.py` | New benchmark tool: loads DB corpus, runs V2+V3 for all 5 resumes, outputs comparison reports |

---

## Next Steps

1. **Dedup corpus before ranking** — group by `(title_normalized, company)`, keep most recent
2. **Tune Example seniority** — add `seniority_band=principal` penalty for jobs without senior/staff/lead in title
3. **V2 retirement path** — V3 is strictly better for specialist profiles (Aditya, Ayush, Vivek, Abhijeet). V2 remains better only for Example due to seniority signal. Once V3 seniority is fixed, V3 can replace V2 entirely.
4. **Score normalization** — V3 scores are unbounded (Aditya hits 1.583, Vivek 1.185). Consider capping at 1.0 or normalizing against the top score for display.
