"""Recruiter finder: DuckDuckGo search → free OpenRouter LLM validation.

Pipeline:
  1. DDG HTML search for site:linkedin.com/in "Company" recruiter India
  2. Parse raw LinkedIn slugs + title snippets from results
  3. Send raw snippets to openrouter/free (batch) to extract clean names,
     confirm recruiter role, discard non-HR profiles

Emails are NOT guessed. They must be entered manually and verified separately
via batch.email_verifier.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_LI_URL_RE = re.compile(
    r"https?://(?:www\.|[a-z]{2}\.)?linkedin\.com/in/([a-z0-9\-]+)",
    re.IGNORECASE,
)
_VALID_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,100}$")

from llm.openrouter import FALLBACK_MODELS


# ---------------------------------------------------------------------------
# Helpers (pure — easy to unit-test)
# ---------------------------------------------------------------------------

def _slug_to_name(slug: str) -> str | None:
    """'john-doe-12ab34' → 'John Doe'. Drops trailing hex suffix."""
    parts = slug.split("-")
    if parts and re.fullmatch(r"[0-9a-f]{4,}", parts[-1]):
        parts = parts[:-1]
    if not parts:
        return None
    name_parts = [p.capitalize() for p in parts if len(p) > 1]
    return " ".join(name_parts) if name_parts else None


def _is_recruiter_title(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in [
        "recruiter", "talent acquisition", "sourcer", "talent partner",
        "hr ", "human resources", "people operations", "staffing", "hiring",
    ])


def _parse_ddg_html(html: str) -> list[dict]:
    """Extract LinkedIn slugs + title snippets from DDG HTML response."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    results = []
    seen: set[str] = set()

    for link in soup.select("a.result__url, a.result__a"):
        href = link.get("href", "")
        m = _LI_URL_RE.search(href) or _LI_URL_RE.search(link.get_text())
        if not m:
            continue

        slug = m.group(1).lower()
        if slug in seen:
            continue
        seen.add(slug)

        title_text = ""
        parent = link.find_parent("div", class_=re.compile(r"result"))
        if parent:
            title_el = parent.select_one(".result__title, .result__a")
            if title_el:
                title_text = title_el.get_text(" ", strip=True)

        results.append({"slug": slug, "snippet": title_text})

    return results


# ---------------------------------------------------------------------------
# Network (injectable for tests)
# ---------------------------------------------------------------------------

def _ddg_search_sync(query: str, retries: int = 3) -> str:
    import time
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
        client.get(_DDG_URL)
        time.sleep(1)
        for attempt in range(retries):
            resp = client.post(_DDG_URL, data={"q": query, "b": "", "kl": "in-en"})
            if resp.status_code == 200 and "result" in resp.text:
                return resp.text
            time.sleep(2 * (attempt + 1))
        resp.raise_for_status()
        return resp.text


async def _llm_enrich(
    company: str,
    candidates: list[dict],
    api_key: str,
) -> list[dict]:
    """
    Send raw DDG candidates to a free OpenRouter model.
    Returns filtered+enriched list: [{slug, name, title, is_recruiter}].
    """
    if not candidates or not api_key:
        return []

    items_json = json.dumps(
        [{"slug": c["slug"], "snippet": c["snippet"]} for c in candidates],
        ensure_ascii=False,
    )
    system = (
        "You are a data extraction assistant. "
        "Given a list of LinkedIn profile slugs and their page title snippets, "
        "identify which profiles CURRENTLY work as recruiters or talent acquisition professionals "
        f"at {company}. "
        "IMPORTANT: Exclude anyone who is a FORMER/EX employee of the company. "
        "LinkedIn snippets often say 'Company' even for people who left. "
        "Look for clues like 'ex-', 'former', 'previously at', or past tense. "
        "If the snippet says something like 'Recruiter at OtherCompany' with no mention of "
        f"currently being at {company}, exclude them. "
        "Only include people whose snippet clearly indicates they are CURRENTLY at the company. "
        "When in doubt, exclude. "
        "For each recruiter, extract their full name from the snippet (not the slug). "
        "Return ONLY a JSON array — no markdown, no explanation. "
        'Each item: {"slug": "...", "name": "Full Name", "title": "Current Job Title", "is_recruiter": true}'
    )
    user = f"Candidates:\n{items_json}\n\nReturn only profiles of people CURRENTLY working as recruiters at {company}. Exclude former employees."

    for model in FALLBACK_MODELS:
        try:
            async with httpx.AsyncClient(timeout=40) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "HTTP-Referer": "https://signalrank.app",
                        "X-Title": "SignalRank",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": 1024,
                        "temperature": 0.0,
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"] or ""

            # Extract JSON array
            start, end = raw.find("["), raw.rfind("]")
            if start == -1 or end == -1:
                logger.warning("LLM %s returned no array", model)
                continue

            items = json.loads(raw[start : end + 1])
            enriched = [
                i for i in items
                if isinstance(i, dict) and i.get("is_recruiter") is not False
            ]
            logger.info("LLM %s enriched %d/%d candidates", model, len(enriched), len(candidates))
            return enriched

        except Exception as exc:
            logger.warning("LLM enrichment failed with %s: %s", model, exc)

    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def find_recruiters(
    company: str,
    max_results: int = 10,
    db: "AsyncSession | None" = None,
) -> list[dict]:
    """
    Find India-based recruiters at *company*.

    Pipeline:
      1. DDG HTML search (India locale) → raw LinkedIn slugs + snippets
      2. Free OpenRouter LLM validates/enriches (if OPENROUTER_API_KEY set)
         — falls back to keyword heuristic otherwise

    Returns list of dicts: name, linkedin_url, source, confidence.
    No emails — those must be entered manually and verified via email_verifier.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    from datetime import datetime, timedelta, timezone
    _CACHE_TTL_DAYS = 3

    raw_candidates: list[dict] = []
    cache_hit = False

    if db is not None:
        from sqlalchemy import select
        from api.models import RecruiterSearch
        cutoff = datetime.now(timezone.utc) - timedelta(days=_CACHE_TTL_DAYS)
        result = await db.execute(
            select(RecruiterSearch)
            .where(RecruiterSearch.company == company, RecruiterSearch.searched_at >= cutoff)
            .order_by(RecruiterSearch.searched_at.desc())
            .limit(1)
        )
        cached = result.scalar_one_or_none()
        if cached and cached.raw_candidates:
            raw_candidates = list(cached.raw_candidates)
            cache_hit = True
            logger.info("DDG cache hit for %s (%d candidates)", company, len(raw_candidates))

    if not cache_hit:
        # Step 1 — DDG search (India-scoped, two queries)
        ddg_queries = [
            f'site:linkedin.com/in "{company}" recruiter India',
            f'site:linkedin.com/in "{company}" "talent acquisition" India',
        ]

        seen_slugs: set[str] = set()

        for q in ddg_queries:
            if len(raw_candidates) >= max_results * 2:
                break
            try:
                html = await asyncio.wait_for(
                    asyncio.to_thread(_ddg_search_sync, q),
                    timeout=20,
                )
            except (asyncio.TimeoutError, httpx.HTTPError) as exc:
                logger.warning("DDG search failed for %r: %s", q, exc)
                await asyncio.sleep(1)
                continue

            for r in _parse_ddg_html(html):
                if r["slug"] not in seen_slugs:
                    seen_slugs.add(r["slug"])
                    raw_candidates.append(r)

            await asyncio.sleep(1.5)

        logger.info("DDG found %d raw candidates for %s", len(raw_candidates), company)

        if db is not None and raw_candidates:
            from api.models import RecruiterSearch
            db.add(RecruiterSearch(company=company, raw_candidates=raw_candidates))
            await db.flush()

    # Step 2 — LLM enrichment or keyword fallback
    if api_key and raw_candidates:
        enriched = await _llm_enrich(company, raw_candidates[:max_results * 2], api_key)
        # Map enriched back by slug; fall back to slug-derived name if LLM omitted
        slug_to_enriched = {e["slug"]: e for e in enriched if isinstance(e, dict)}
        confirmed = [
            {
                "slug": c["slug"],
                "name": slug_to_enriched.get(c["slug"], {}).get("name") or _slug_to_name(c["slug"]),
                "title": slug_to_enriched.get(c["slug"], {}).get("title", ""),
                "confidence": "high" if c["slug"] in slug_to_enriched else "low",
                "source": "ddg+llm",
            }
            for c in raw_candidates
            if c["slug"] in slug_to_enriched
        ]
    else:
        # Keyword heuristic fallback (no API key)
        confirmed = [
            {
                "slug": c["slug"],
                "name": _slug_to_name(c["slug"]),
                "title": c["snippet"],
                "confidence": "high" if _is_recruiter_title(c["snippet"]) else "medium",
                "source": "ddg_heuristic",
            }
            for c in raw_candidates
            if _is_recruiter_title(c["snippet"]) or True  # keep all when no LLM
        ]

    # Step 3 — Build output (no email guessing)
    results = []
    for c in confirmed[:max_results]:
        slug = c.get("slug", "")
        if not slug or not _VALID_SLUG_RE.match(slug):
            continue
        name = c.get("name") or ""
        results.append({
            "name": name or None,
            "linkedin_url": f"https://www.linkedin.com/in/{slug}",
            "source": c["source"],
            "confidence": c["confidence"],
        })

    return results
