from __future__ import annotations

from dataclasses import dataclass
import re

from api.config import settings
from domain.role_taxonomy import ROLE_QUERY_ALIASES, ROLE_QUERY_EXPANSIONS


@dataclass
class SearchQuery:
    term: str
    location: str
    country: str


def _expand_role_terms(role: str) -> list[str]:
    normalized = role.strip().lower()
    expansions = ROLE_QUERY_EXPANSIONS.get(normalized)
    if expansions:
        ordered = [role.strip()]
        ordered.extend(expanded for expanded in expansions if expanded.strip().lower() != normalized)
        return ordered
    # Prompt-first mode: raw LLM roles may not exactly match our buckets.
    # Use alias matching as a lightweight normalization layer for search.
    for canonical, aliases in ROLE_QUERY_ALIASES.items():
        alias_values = (canonical, *aliases)
        if any(alias in normalized or normalized in alias for alias in alias_values):
            expansions = list(ROLE_QUERY_EXPANSIONS.get(canonical, (role.strip(),)))
            return [role.strip(), *[expanded for expanded in expansions if expanded.strip().lower() != normalized]]

    normalized_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    best_canonical: str | None = None
    best_score = 0
    for canonical, aliases in ROLE_QUERY_ALIASES.items():
        for alias in (canonical, *aliases):
            alias_tokens = set(re.findall(r"[a-z0-9]+", alias))
            score = len(normalized_tokens & alias_tokens)
            if score > best_score and score >= 2:
                best_score = score
                best_canonical = canonical
    if best_canonical:
        expansions = list(ROLE_QUERY_EXPANSIONS.get(best_canonical, (role.strip(),)))
        return [role.strip(), *[expanded for expanded in expansions if expanded.strip().lower() != normalized]]
    return [role.strip()]


def build_queries(profile, *, max_terms: int | None = None) -> list[SearchQuery]:
    career_intent = {}
    if profile.config_overrides:
        career_intent = (profile.config_overrides.get("career_intent") or {})
    query_plan = career_intent.get("query_plan") or {}
    roles = profile.target_roles
    if not roles and profile.config_overrides:
        roles = (profile.config_overrides.get("profile_intent") or {}).get("roles")
    roles = roles or []

    custom = list(profile.custom_search_queries or [])
    custom = list(query_plan.get("title_queries") or []) + list(query_plan.get("skill_queries") or []) + list(query_plan.get("domain_queries") or []) + custom
    negative_terms = [str(term).strip().lower() for term in (query_plan.get("negative_keywords") or []) if str(term).strip()]
    seen: set[str] = set()
    terms: list[str] = []
    for t in roles:
        for expanded in _expand_role_terms(t):
            key = expanded.strip().lower()
            if key and key not in seen:
                if any(neg in key for neg in negative_terms):
                    continue
                seen.add(key)
                terms.append(expanded.strip())
    for t in custom:
        key = t.strip().lower()
        if key and key not in seen:
            if any(neg in key for neg in negative_terms):
                continue
            seen.add(key)
            terms.append(t.strip())

    locations = profile.preferred_locations
    if not locations and profile.config_overrides:
        locations = (profile.config_overrides.get("scraping") or {}).get("locations")

    default_country = settings.scraper_default_country
    if not locations:
        locations = [default_country]

    # Normalize: "Remote" and country-level entries pass as city="" so jobspy
    # searches country-wide. City-level entries (Pune, Bangalore) pass as city.
    _country_like = {default_country.lower(), "remote", "india", "worldwide"}

    limit = max_terms or settings.scraper_max_terms
    terms = terms[:limit]

    queries: list[SearchQuery] = []
    seen_query_keys: set[tuple[str, str]] = set()
    for term in terms:
        for loc in locations:
            city = "" if loc.lower() in _country_like else loc
            key = (term.lower(), city.lower())
            if key in seen_query_keys:
                continue
            seen_query_keys.add(key)
            queries.append(SearchQuery(term=term, location=city, country=default_country))
            if len(queries) >= 50:
                return queries
    return queries
