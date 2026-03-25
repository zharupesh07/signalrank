"""Hunter.io API client for verified email discovery.

Endpoints used:
  - Email Finder: GET /v2/email-finder — find email for a person at a domain
  - Domain Search: GET /v2/domain-search — list emails at a domain

Free tier: 25 searches/month. Results are cached by Hunter server-side
(repeated lookups for the same person don't count against quota).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.hunter.io/v2"


@dataclass
class EmailResult:
    email: str
    confidence: int  # 0-100
    type: str  # "personal" or "generic"
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    sources: int = 0


class HunterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=30.0,
            headers={"User-Agent": "SignalRank/1.0"},
        )
        self._sem = asyncio.Semaphore(2)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def find_email(
        self, domain: str, full_name: str
    ) -> EmailResult | None:
        """Find the email address for a specific person at a domain."""
        if not self.available:
            return None

        parts = full_name.strip().split()
        if len(parts) < 2:
            return None

        first_name = parts[0]
        last_name = " ".join(parts[1:])

        async with self._sem:
            try:
                resp = await self._http.get(
                    "/email-finder",
                    params={
                        "domain": domain,
                        "first_name": first_name,
                        "last_name": last_name,
                        "api_key": self.api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    logger.warning("Hunter.io rate limit hit")
                elif exc.response.status_code == 401:
                    logger.error("Hunter.io API key invalid")
                else:
                    logger.warning("Hunter.io email-finder error: %s", exc)
                return None
            except httpx.HTTPError as exc:
                logger.warning("Hunter.io request failed: %s", exc)
                return None

        email = data.get("email")
        if not email:
            return None

        confidence = data.get("score", 0) or 0
        if confidence < 30:
            logger.debug("Hunter.io low confidence (%d) for %s@%s, skipping", confidence, full_name, domain)
            return None

        return EmailResult(
            email=email,
            confidence=confidence,
            type=data.get("type", "unknown"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            position=data.get("position"),
            sources=len(data.get("sources", [])),
        )

    async def domain_search(
        self, domain: str, limit: int = 10
    ) -> list[EmailResult]:
        """List email addresses found at a domain."""
        if not self.available:
            return []

        async with self._sem:
            try:
                resp = await self._http.get(
                    "/domain-search",
                    params={
                        "domain": domain,
                        "limit": limit,
                        "api_key": self.api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
            except httpx.HTTPError as exc:
                logger.warning("Hunter.io domain-search error: %s", exc)
                return []

        results = []
        for item in data.get("emails", []):
            email = item.get("value")
            if not email:
                continue
            results.append(EmailResult(
                email=email,
                confidence=item.get("confidence", 0) or 0,
                type=item.get("type", "unknown"),
                first_name=item.get("first_name"),
                last_name=item.get("last_name"),
                position=item.get("position"),
                sources=len(item.get("sources", [])),
            ))
        return results

    async def close(self):
        await self._http.aclose()
