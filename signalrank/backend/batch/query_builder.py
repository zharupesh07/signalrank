from __future__ import annotations

import os
from dataclasses import dataclass

from domain.role_taxonomy import ROLE_QUERY_EXPANSIONS


@dataclass
class SearchQuery:
    term: str
    location: str
    country: str


def _expand_role_terms(role: str) -> list[str]:
    normalized = role.strip().lower()
    expansions = ROLE_QUERY_EXPANSIONS.get(normalized)
    if expansions:
        return list(expansions)
    return [role.strip()]


def build_queries(profile, *, max_terms: int | None = None) -> list[SearchQuery]:
    roles = profile.target_roles
    if not roles and profile.config_overrides:
        roles = (profile.config_overrides.get("profile_intent") or {}).get("roles")
    roles = roles or []

    custom = profile.custom_search_queries or []
    seen: set[str] = set()
    terms: list[str] = []
    for t in roles:
        for expanded in _expand_role_terms(t):
            key = expanded.strip().lower()
            if key and key not in seen:
                seen.add(key)
                terms.append(expanded.strip())
    for t in custom:
        key = t.strip().lower()
        if key and key not in seen:
            seen.add(key)
            terms.append(t.strip())

    locations = profile.preferred_locations
    if not locations and profile.config_overrides:
        locations = (profile.config_overrides.get("scraping") or {}).get("locations")

    default_country = os.environ.get("SCRAPER_DEFAULT_COUNTRY", "India")
    if not locations:
        locations = [default_country]

    # Normalize: "Remote" and country-level entries pass as city="" so jobspy
    # searches country-wide. City-level entries (Pune, Bangalore) pass as city.
    _country_like = {default_country.lower(), "remote", "india", "worldwide"}

    limit = max_terms or int(os.environ.get("SCRAPER_MAX_TERMS", "1"))
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
