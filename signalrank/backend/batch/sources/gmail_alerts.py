from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)


def _extract_jobs_from_email(msg: email.message.Message) -> list[RawJob]:
    jobs = []
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                break
            elif ct == "text/plain" and not body:
                body = part.get_payload(decode=True).decode("utf-8", errors="replace")
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

    if not body:
        return []

    date_sent = None
    date_str = msg.get("Date")
    if date_str:
        try:
            date_sent = parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            pass

    soup = BeautifulSoup(body, "lxml")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("http"):
            continue
        if any(skip in href for skip in ["unsubscribe", "mailto:", "google.com/alerts", "support."]):
            continue
        text = link.get_text(strip=True)
        if len(text) < 5:
            continue
        jobs.append(RawJob(
            job_url=href, title=text[:200], company=None, description=None,
            location=None, site="gmail", date_posted=date_sent,
        ))
    return jobs


def _fetch_sync(config: ScraperConfig) -> list[RawJob]:
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(config.gmail_user, config.gmail_app_password)
        conn.select("INBOX", readonly=True)

        _, data = conn.search(None, '(FROM "action@google.com" UNSEEN)')
        msg_ids = data[0].split()[-20:]

        all_jobs = []
        for mid in msg_ids:
            _, msg_data = conn.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            all_jobs.extend(_extract_jobs_from_email(msg))

        conn.close()
        conn.logout()
        return all_jobs
    except Exception:
        logger.exception("Gmail IMAP fetch failed")
        return []


async def search(queries: list[SearchQuery], config: ScraperConfig) -> list[RawJob]:
    if not config.gmail_user or not config.gmail_app_password:
        logger.info("Gmail credentials not set, skipping Phase 5")
        return []

    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch_sync, config), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("Gmail fetch timed out")
        return []
