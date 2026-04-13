from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import md5
from typing import Any

from api.models import JobRaw, JobResult, Profile
from llm.cache import PromptCache


BUCKETS = [
    ("top_fit", "Top fit", 88.0),
    ("strong_fit", "Strong fit", 76.0),
    ("possible_fit", "Possible fit", 62.0),
    ("stretch", "Stretch", 45.0),
    ("hide", "Hide", float("-inf")),
]

QUICK_ACTIONS = {
    "good_fit",
    "bad_fit",
    "too_junior",
    "wrong_role",
    "wrong_location",
    "prefer_more_like_this",
    "hide_company",
    "prefer_remote",
    "prefer_pune",
}

_LOCATION_HINTS = {
    "remote",
    "hybrid",
    "onsite",
    "on-site",
    "pune",
    "bangalore",
    "bengaluru",
    "mumbai",
    "delhi",
    "gurgaon",
    "noida",
    "hyderabad",
    "chennai",
    "india",
    "singapore",
    "london",
    "new york",
    "san francisco",
}
_ROLE_HINTS = {
    "ai",
    "ml",
    "llm",
    "genai",
    "agentic",
    "copilot",
    "platform",
    "devops",
    "sre",
    "infra",
    "infrastructure",
    "engineer",
    "engineering",
    "scientist",
    "data scientist",
    "mlops",
    "llmops",
}
_TOKEN_RE = re.compile(r"[a-z0-9\+\#][a-z0-9\+\#\-/ ]{1,40}")
_CITY_SPLIT_RE = re.compile(r"[,/|]|\b(?:or|and)\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


@dataclass
class PreferenceContext:
    state: dict[str, Any]
    summary_chips: list[str]
    has_learned_preferences: bool


def normalize_text(value: str | None) -> str:
    return _SPACE_RE.sub(" ", str(value or "").replace("_", " ").strip())


def normalize_key(value: str | None) -> str:
    return normalize_text(value).lower()


def _empty_state() -> dict[str, Any]:
    return {
        "location_preferences": [],
        "role_preferences": [],
        "positive_tags": [],
        "negative_tags": [],
        "hidden_companies": [],
        "preferred_sources": [],
        "work_mode_preferences": [],
        "positive_examples": [],
        "negative_examples": [],
        "explanation_snippets": [],
    }


def _listify_profile_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_text(item) for item in value if normalize_text(item)]
    if isinstance(value, dict):
        values: list[str] = []
        for key in ("ordered", "preferred", "include", "items", "values"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                values.extend(normalize_text(item) for item in candidate if normalize_text(item))
        if values:
            return values
        for item in value.values():
            if isinstance(item, str) and normalize_text(item):
                values.append(normalize_text(item))
        return values
    if isinstance(value, str) and normalize_text(value):
        return [normalize_text(value)]
    return []


def seed_state_from_profile(profile: Profile | None) -> dict[str, Any]:
    state = _empty_state()
    if profile is None:
        return state

    locations = _listify_profile_values(profile.preferred_locations)
    for idx, location in enumerate(locations[:5]):
        state["location_preferences"].append(
            {
                "value": normalize_key(location),
                "label": location,
                "weight": round(max(0.8, 1.8 - idx * 0.2), 2),
            }
        )
        if normalize_key(location) in {"remote", "hybrid", "onsite", "on-site"}:
            state["work_mode_preferences"].append(
                {
                    "value": normalize_key(location).replace("on-site", "onsite"),
                    "label": location,
                    "weight": round(max(0.7, 1.5 - idx * 0.2), 2),
                }
            )

    roles = _listify_profile_values(profile.target_roles)
    for idx, role in enumerate(roles[:6]):
        state["role_preferences"].append(
            {
                "value": normalize_key(role),
                "label": role,
                "weight": round(max(0.8, 1.7 - idx * 0.15), 2),
            }
        )

    return state


def merge_preference_state(base: dict[str, Any] | None, delta: dict[str, Any] | None) -> dict[str, Any]:
    state = canonicalize_state(base)
    if not delta:
        return state

    for bucket in (
        "location_preferences",
        "role_preferences",
        "positive_tags",
        "negative_tags",
        "preferred_sources",
        "work_mode_preferences",
    ):
        merged: dict[str, dict[str, Any]] = {
            item["value"]: dict(item)
            for item in state.get(bucket, [])
            if isinstance(item, dict) and normalize_key(item.get("value"))
        }
        for raw in delta.get(bucket, []) or []:
            if not isinstance(raw, dict):
                continue
            value = normalize_key(raw.get("value") or raw.get("label"))
            if not value:
                continue
            current = merged.get(value, {"value": value, "label": normalize_text(raw.get("label") or value), "weight": 0.0})
            current["label"] = normalize_text(raw.get("label") or current.get("label") or value)
            current["weight"] = round(float(current.get("weight") or 0.0) + float(raw.get("weight") or 0.0), 2)
            merged[value] = current
        state[bucket] = sorted(
            [item for item in merged.values() if float(item.get("weight") or 0.0) > -4.0],
            key=lambda item: float(item.get("weight") or 0.0),
            reverse=True,
        )[:10]

    hidden_companies = {normalize_key(item) for item in state.get("hidden_companies", []) if normalize_key(item)}
    for company in delta.get("hidden_companies", []) or []:
        key = normalize_key(company)
        if key:
            hidden_companies.add(key)
    state["hidden_companies"] = sorted(hidden_companies)

    for bucket, limit in (("positive_examples", 12), ("negative_examples", 12)):
        existing = [item for item in state.get(bucket, []) if isinstance(item, dict)]
        seen = {
            (
                normalize_key(item.get("company")),
                normalize_key(item.get("title")),
                normalize_key(item.get("location")),
            )
            for item in existing
        }
        for raw in delta.get(bucket, []) or []:
            if not isinstance(raw, dict):
                continue
            signature = (
                normalize_key(raw.get("company")),
                normalize_key(raw.get("title")),
                normalize_key(raw.get("location")),
            )
            if not any(signature):
                continue
            if signature in seen:
                continue
            existing.append(
                {
                    "job_id": raw.get("job_id"),
                    "company": normalize_text(raw.get("company")),
                    "title": normalize_text(raw.get("title")),
                    "location": normalize_text(raw.get("location")),
                    "site": normalize_text(raw.get("site")),
                    "keywords": dedupe_strings(raw.get("keywords") or []),
                }
            )
            seen.add(signature)
        state[bucket] = existing[-limit:]

    explanation_snippets = dedupe_strings(
        [*state.get("explanation_snippets", []), *(delta.get("explanation_snippets") or [])]
    )
    state["explanation_snippets"] = explanation_snippets[-20:]
    return state


def canonicalize_state(state: dict[str, Any] | None) -> dict[str, Any]:
    seeded = _empty_state()
    if not state:
        return seeded
    for key in seeded:
        value = state.get(key)
        if isinstance(seeded[key], list):
            seeded[key] = list(value or [])
        else:
            seeded[key] = value
    return seeded


def has_explicit_preferences(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    return any(
        state.get(key)
        for key in (
            "location_preferences",
            "role_preferences",
            "positive_tags",
            "negative_tags",
            "hidden_companies",
            "preferred_sources",
            "work_mode_preferences",
            "positive_examples",
            "negative_examples",
            "explanation_snippets",
        )
    )


def summarize_preferences(state: dict[str, Any]) -> list[str]:
    chips: list[str] = []
    locations = state.get("location_preferences", [])
    if len(locations) >= 2:
        first = normalize_text(locations[0].get("label"))
        second = normalize_text(locations[1].get("label"))
        if first and second:
            chips.append(f"{first} > {second}")
    elif locations:
        first = normalize_text(locations[0].get("label"))
        if first:
            chips.append(f"{first} preferred")

    work_modes = [normalize_text(item.get("label")) for item in state.get("work_mode_preferences", []) if normalize_text(item.get("label"))]
    if work_modes:
        chips.append(f"{work_modes[0]} preferred")

    roles = [normalize_text(item.get("label")) for item in state.get("role_preferences", []) if normalize_text(item.get("label"))]
    if roles:
        chips.append(f"{roles[0]} first")

    negatives = [normalize_text(item.get("label")) for item in state.get("negative_tags", []) if normalize_text(item.get("label"))]
    if negatives:
        chips.append(f"avoid {negatives[0]}")

    for snippet in state.get("explanation_snippets", []) or []:
        text = normalize_text(snippet)
        if text and text not in chips:
            chips.append(text)
        if len(chips) >= 6:
            break
    return chips[:6]


def dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = normalize_text(value)
        key = normalize_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _classify_term(term: str) -> str:
    key = normalize_key(term)
    if not key:
        return "tag"
    if key in {"remote", "hybrid", "onsite", "on-site"}:
        return "work_mode"
    if any(hint in key for hint in _LOCATION_HINTS):
        return "location"
    if any(hint in key for hint in _ROLE_HINTS):
        return "role"
    return "tag"


def _term_entry(term: str, *, weight: float) -> dict[str, Any]:
    return {"value": normalize_key(term), "label": normalize_text(term), "weight": round(weight, 2)}


def _extract_terms_from_phrase(raw: str) -> list[str]:
    text = normalize_text(raw).strip(" .,:;")
    if not text:
        return []
    text = re.sub(r"\bfirst\b$", "", text, flags=re.IGNORECASE).strip(" .,:;")
    text = re.sub(r"\bjobs?\b$", "", text, flags=re.IGNORECASE).strip(" .,:;")
    parts = []
    for piece in _CITY_SPLIT_RE.split(text):
        cleaned = normalize_text(piece).strip(" .,:;")
        if cleaned:
            parts.append(cleaned)
    return dedupe_strings(parts or [text])


def _job_keywords(job: JobRaw) -> list[str]:
    haystacks = [job.title or "", job.description or ""]
    keywords: list[str] = []
    for haystack in haystacks:
        lower = (haystack or "").lower()
        for match in _TOKEN_RE.findall(lower):
            token = normalize_key(match)
            if len(token) < 3:
                continue
            if token in {"with", "from", "that", "this", "your", "team", "work", "role"}:
                continue
            keywords.append(token)
            if len(keywords) >= 20:
                return dedupe_strings(keywords)
    return dedupe_strings(keywords)


def build_feedback_delta(
    *,
    feedback_text: str | None,
    quick_actions: list[str],
    jobs: list[JobRaw],
) -> dict[str, Any]:
    delta = _empty_state()
    text = normalize_text(feedback_text)

    if text:
        matched_prefer_over = False
        pattern = re.search(r"prefer\s+(.+?)\s+over\s+(.+?)(?:$|[.,;])", text, re.IGNORECASE)
        if pattern:
            matched_prefer_over = True
            preferred_terms = _extract_terms_from_phrase(pattern.group(1))
            demoted_terms = _extract_terms_from_phrase(pattern.group(2))
            for idx, term in enumerate(preferred_terms):
                category = _classify_term(term)
                target = {
                    "location": "location_preferences",
                    "role": "role_preferences",
                    "work_mode": "work_mode_preferences",
                }.get(category, "positive_tags")
                delta[target].append(_term_entry(term, weight=max(1.2, 2.2 - idx * 0.2)))
            for idx, term in enumerate(demoted_terms):
                category = _classify_term(term)
                if category == "location":
                    delta["location_preferences"].append(_term_entry(term, weight=max(0.7, 1.2 - idx * 0.1)))
                elif category == "work_mode":
                    delta["work_mode_preferences"].append(_term_entry(term, weight=max(0.6, 1.1 - idx * 0.1)))
                else:
                    target = "negative_tags" if category == "role" else "negative_tags"
                    delta[target].append(_term_entry(term, weight=-max(0.9, 1.6 - idx * 0.1)))
            delta["explanation_snippets"].append(f"{preferred_terms[0]} > {demoted_terms[0]}")

        for pattern_text, bucket, weight in (
            (r"(?:show more|prefer|prioritize)\s+(.+)", "positive", 1.4),
            (r"(?:avoid|deprioritize|less)\s+(.+)", "negative", 1.3),
        ):
            match = re.search(pattern_text, text, re.IGNORECASE)
            if not match:
                continue
            if matched_prefer_over and bucket == "positive":
                continue
            terms = _extract_terms_from_phrase(match.group(1))
            for term in terms:
                category = _classify_term(term)
                if category == "location":
                    target = "location_preferences"
                elif category == "work_mode":
                    target = "work_mode_preferences"
                elif category == "role":
                    target = "role_preferences" if bucket == "positive" else "negative_tags"
                else:
                    target = "positive_tags" if bucket == "positive" else "negative_tags"
                entry_weight = weight if bucket == "positive" else -weight
                delta[target].append(_term_entry(term, weight=entry_weight))

        first_match = re.search(r"(.+?)\s+first(?:$|[.,;])", text, re.IGNORECASE)
        if first_match:
            for term in _extract_terms_from_phrase(first_match.group(1)):
                category = _classify_term(term)
                target = "role_preferences" if category == "role" else "positive_tags"
                delta[target].append(_term_entry(term, weight=1.6))
            cleaned = normalize_text(first_match.group(1))
            if cleaned:
                delta["explanation_snippets"].append(f"{cleaned} first")

    for job in jobs:
        example = {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "site": job.site,
            "keywords": _job_keywords(job),
        }
        for action in quick_actions:
            if action == "good_fit":
                delta["positive_examples"].append(example)
            elif action == "bad_fit":
                delta["negative_examples"].append(example)
            elif action == "too_junior":
                delta["negative_tags"].append(_term_entry("junior", weight=-1.6))
                delta["negative_tags"].append(_term_entry("entry level", weight=-1.2))
                delta["negative_examples"].append(example)
            elif action == "wrong_role":
                if job.title:
                    delta["negative_tags"].append(_term_entry(job.title, weight=-1.5))
                delta["negative_examples"].append(example)
            elif action == "wrong_location":
                if job.location:
                    delta["location_preferences"].append(_term_entry(job.location, weight=-1.2))
            elif action == "prefer_more_like_this":
                delta["positive_examples"].append(example)
                if job.title:
                    delta["role_preferences"].append(_term_entry(job.title, weight=1.0))
            elif action == "hide_company":
                if job.company:
                    delta["hidden_companies"].append(job.company)
            elif action == "prefer_remote":
                delta["work_mode_preferences"].append(_term_entry("remote", weight=1.8))
                delta["location_preferences"].append(_term_entry("remote", weight=1.2))
            elif action == "prefer_pune":
                delta["location_preferences"].append(_term_entry("Pune", weight=1.8))

    for action in quick_actions:
        if action == "good_fit":
            delta["explanation_snippets"].append("reinforce strong matches")
        elif action == "bad_fit":
            delta["explanation_snippets"].append("avoid similar misses")
        elif action == "prefer_remote":
            delta["explanation_snippets"].append("remote preferred")
        elif action == "prefer_pune":
            delta["explanation_snippets"].append("Pune preferred")
    return delta


async def enrich_feedback_delta_with_llm(
    *,
    feedback_text: str | None,
    base_delta: dict[str, Any],
    profile: Profile | None,
    llm,
    db,
) -> dict[str, Any]:
    text = normalize_text(feedback_text)
    if not text or llm is None:
        return base_delta
    api_key = getattr(llm, "api_key", "")
    if not api_key:
        return base_delta

    fingerprint = md5(
        json.dumps(
            {
                "feedback": text.lower(),
                "roles": _listify_profile_values(profile.target_roles if profile else None),
                "locations": _listify_profile_values(profile.preferred_locations if profile else None),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cache = PromptCache(db)
    cached = await cache.get(fingerprint)
    if isinstance(cached, dict):
        return merge_preference_state(base_delta, cached)

    system = (
        "Extract concise hiring preference deltas from user feedback. "
        "Return JSON only. Prefer short normalized phrases. "
        "Use negative weights for dislikes. No prose."
    )
    user = json.dumps(
        {
            "feedback_text": text,
            "existing_delta": base_delta,
            "profile_roles": _listify_profile_values(profile.target_roles if profile else None),
            "profile_locations": _listify_profile_values(profile.preferred_locations if profile else None),
        },
        ensure_ascii=True,
    )
    schema = {
        "type": "object",
        "properties": {
            "location_preferences": {"type": "array", "items": _weighted_entry_schema()},
            "role_preferences": {"type": "array", "items": _weighted_entry_schema()},
            "positive_tags": {"type": "array", "items": _weighted_entry_schema()},
            "negative_tags": {"type": "array", "items": _weighted_entry_schema()},
            "preferred_sources": {"type": "array", "items": _weighted_entry_schema()},
            "work_mode_preferences": {"type": "array", "items": _weighted_entry_schema()},
            "hidden_companies": {"type": "array", "items": {"type": "string"}},
            "explanation_snippets": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "location_preferences",
            "role_preferences",
            "positive_tags",
            "negative_tags",
            "preferred_sources",
            "work_mode_preferences",
            "hidden_companies",
            "explanation_snippets",
        ],
        "additionalProperties": False,
    }
    response = await llm.llm_json(system=system, user=user, json_schema=schema, schema_name="job_feedback_preferences", max_tokens=700)
    if not isinstance(response, dict) or response.get("_error"):
        return base_delta
    await cache.set(fingerprint, response)
    return merge_preference_state(base_delta, response)


def _weighted_entry_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "label": {"type": "string"},
            "weight": {"type": "number"},
        },
        "required": ["value", "label", "weight"],
        "additionalProperties": False,
    }


def effective_preference_context(
    *,
    profile: Profile | None,
    stored_state: dict[str, Any] | None,
) -> PreferenceContext:
    seeded = seed_state_from_profile(profile)
    learned = canonicalize_state(stored_state)
    effective = merge_preference_state(seeded, learned)
    return PreferenceContext(
        state=effective,
        summary_chips=summarize_preferences(effective),
        has_learned_preferences=has_explicit_preferences(learned),
    )


def rerank_rows(
    rows: list[tuple[JobResult, JobRaw]],
    *,
    state: dict[str, Any],
    sort: str,
    sort_dir: str,
) -> list[dict[str, Any]]:
    enriched = [score_job(result, job, state=state) for result, job in rows]
    if sort == "final_score":
        enriched.sort(key=lambda item: item["preference_score"], reverse=(sort_dir != "asc"))
    elif sort == "date_posted":
        enriched.sort(
            key=lambda item: item["job"].date_posted or item["job"].ingested_at,
            reverse=(sort_dir != "asc"),
        )
    elif sort == "title_relevance_score":
        enriched.sort(
            key=lambda item: item["result"].title_relevance_score or 0.0,
            reverse=(sort_dir != "asc"),
        )
    return enriched


def score_job(result: JobResult, job: JobRaw, *, state: dict[str, Any]) -> dict[str, Any]:
    base_score = float(result.final_score or 0.0)
    adjustment = 0.0
    tags: list[str] = []
    location_text = normalize_key(job.location)
    title_text = normalize_key(job.title)
    description_text = normalize_key(job.description)
    company_text = normalize_key(job.company)
    site_text = normalize_key(job.site)
    haystack = " ".join(part for part in [title_text, description_text, location_text, company_text] if part)

    if company_text and company_text in set(state.get("hidden_companies", [])):
        adjustment -= 120.0
        tags.append("hidden company")

    for pref in state.get("location_preferences", []) or []:
        value = normalize_key(pref.get("value"))
        weight = float(pref.get("weight") or 0.0)
        if not value or not location_text:
            continue
        if value in location_text:
            adjustment += weight * 5.5
            label = normalize_text(pref.get("label") or value)
            if value == "remote":
                tags.append("remote match")
            elif weight >= 1.5:
                tags.append(f"prefers {label}")
            elif weight > 0:
                tags.append(label)
            else:
                tags.append(f"avoid {label}")
        elif weight < 0 and value in haystack:
            adjustment += weight * 4.5
            tags.append(f"avoid {normalize_text(pref.get('label') or value)}")

    for pref in state.get("work_mode_preferences", []) or []:
        value = normalize_key(pref.get("value"))
        weight = float(pref.get("weight") or 0.0)
        if value == "remote" and ("remote" in location_text or "remote" in description_text):
            adjustment += weight * 5.0
            tags.append("remote match")
        elif value == "hybrid" and ("hybrid" in location_text or "hybrid" in description_text):
            adjustment += weight * 4.0
            tags.append("hybrid match")
        elif value == "onsite" and ("onsite" in location_text or "on-site" in location_text):
            adjustment += weight * 4.0
            tags.append("onsite match")

    for pref in state.get("role_preferences", []) or []:
        value = normalize_key(pref.get("value"))
        if value and value in haystack:
            adjustment += float(pref.get("weight") or 0.0) * 6.0
            tags.append(normalize_text(pref.get("label") or value))

    for pref in state.get("positive_tags", []) or []:
        value = normalize_key(pref.get("value"))
        if value and value in haystack:
            adjustment += float(pref.get("weight") or 0.0) * 4.5
            tags.append(normalize_text(pref.get("label") or value))

    for pref in state.get("negative_tags", []) or []:
        value = normalize_key(pref.get("value"))
        if value and value in haystack:
            adjustment -= abs(float(pref.get("weight") or 0.0)) * 5.0
            tags.append(f"too {normalize_text(pref.get('label') or value).lower()}")

    for pref in state.get("preferred_sources", []) or []:
        value = normalize_key(pref.get("value"))
        if value and value == site_text:
            adjustment += float(pref.get("weight") or 0.0) * 3.0
            tags.append(f"{normalize_text(pref.get('label') or value)} source")

    keywords = set(_job_keywords(job))
    for example in state.get("positive_examples", []) or []:
        overlap = len(keywords.intersection(set(normalize_key(item) for item in (example.get("keywords") or []))))
        if overlap >= 2:
            adjustment += min(8.0, 2.0 + overlap)
            tags.append("more like liked jobs")
            break
        if company_text and company_text == normalize_key(example.get("company")):
            adjustment += 4.0
            tags.append("liked company pattern")
            break

    for example in state.get("negative_examples", []) or []:
        overlap = len(keywords.intersection(set(normalize_key(item) for item in (example.get("keywords") or []))))
        if overlap >= 2:
            adjustment -= min(8.0, 2.0 + overlap)
            tags.append("similar to rejected jobs")
            break
        if company_text and company_text == normalize_key(example.get("company")):
            adjustment -= 4.5
            tags.append("company previously rejected")
            break

    if job.site in {"greenhouse", "ashby", "lever"}:
        tags.append("direct ATS")
    if result.company_tier in {"tier_ss", "tier_s", "tier_a"}:
        tags.append("company tier boost")
    if result.recency_score and result.recency_score >= 70:
        tags.append("fresh posting")

    preference_score = max(0.0, min(100.0, base_score + adjustment))
    bucket_key, bucket_label = bucket_for_score(preference_score)
    return {
        "result": result,
        "job": job,
        "preference_score": preference_score,
        "preference_bucket_key": bucket_key,
        "preference_bucket": bucket_label,
        "preference_tags": dedupe_strings(tags)[:6],
    }


def bucket_for_score(score: float) -> tuple[str, str]:
    for key, label, threshold in BUCKETS:
        if score >= threshold:
            return key, label
    return "hide", "Hide"
