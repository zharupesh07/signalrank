"""Email verification: MX record lookup + SMTP RCPT TO probe.

No guessing — this only verifies emails that are already known.

Verification levels:
  1. Format check (basic)
  2. MX record exists for domain (DNS)
  3. SMTP RCPT TO accepted by the mail server (deliverability)

SMTP probing works well for self-hosted / company domains.
Gmail, Outlook, Yahoo all block RCPT TO probing and return 250 regardless
(catch-all), so for those we stop at MX and return reason="catchall_suspected".
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import socket

import dns.resolver

logger = logging.getLogger(__name__)

# Providers that silently accept any RCPT TO — probing them is meaningless
_CATCHALL_PROVIDERS = {
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "yahoo.in", "yahoo.co.in",
    "protonmail.com", "icloud.com", "me.com",
}

# SMTP probe timeout in seconds
_SMTP_TIMEOUT = 10


def _get_mx_host(domain: str) -> str | None:
    """Return the highest-priority MX hostname for *domain*, or None."""
    try:
        records = dns.resolver.resolve(domain, "MX", lifetime=8)
        sorted_records = sorted(records, key=lambda r: r.preference)
        return str(sorted_records[0].exchange).rstrip(".")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return None
    except Exception as exc:
        logger.debug("MX lookup failed for %s: %s", domain, exc)
        return None


def _smtp_probe(email: str, mx_host: str) -> dict:
    """
    Connect to mx_host:25, issue MAIL FROM + RCPT TO, return result dict.
    Never actually sends mail — quits after RCPT TO response.
    """
    try:
        with smtplib.SMTP(timeout=_SMTP_TIMEOUT) as smtp:
            smtp.connect(mx_host, 25)
            smtp.ehlo("signalrank.app")
            smtp.mail("noreply@signalrank.app")
            code, msg = smtp.rcpt(email)
            smtp.quit()

        msg_str = msg.decode(errors="replace") if isinstance(msg, bytes) else str(msg)

        if code == 250:
            return {"valid": True, "reason": "smtp_accepted"}
        elif code in (550, 551, 553):
            return {"valid": False, "reason": f"user_not_found ({code})"}
        elif code in (421, 450, 451, 452):
            return {"valid": None, "reason": f"temporary_failure ({code})"}
        else:
            return {"valid": None, "reason": f"smtp_{code}: {msg_str[:80]}"}

    except smtplib.SMTPConnectError as exc:
        return {"valid": None, "reason": f"connect_failed: {exc}"}
    except smtplib.SMTPServerDisconnected:
        return {"valid": None, "reason": "server_disconnected"}
    except (socket.timeout, TimeoutError):
        return {"valid": None, "reason": "timeout"}
    except OSError as exc:
        return {"valid": None, "reason": f"network_error: {exc}"}
    except Exception as exc:
        return {"valid": None, "reason": f"unexpected: {exc}"}


async def verify_email(email: str) -> dict:
    """
    Verify a single email address.

    Returns:
        {
            "email": str,
            "valid": True | False | None,  # None = inconclusive
            "reason": str,
        }
    """
    email = email.strip().lower()

    # 1. Format
    if "@" not in email or email.count("@") != 1:
        return {"email": email, "valid": False, "reason": "invalid_format"}

    local, domain = email.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        return {"email": email, "valid": False, "reason": "invalid_format"}

    # 2. Known catch-all providers — skip SMTP, report inconclusive
    if domain in _CATCHALL_PROVIDERS:
        mx = await asyncio.to_thread(_get_mx_host, domain)
        if mx is None:
            return {"email": email, "valid": False, "reason": "no_mx_record"}
        return {"email": email, "valid": None, "reason": "catchall_provider"}

    # 3. MX lookup
    mx = await asyncio.to_thread(_get_mx_host, domain)
    if mx is None:
        return {"email": email, "valid": False, "reason": "no_mx_record"}

    # 4. SMTP probe
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_smtp_probe, email, mx),
            timeout=15,
        )
    except asyncio.TimeoutError:
        return {"email": email, "valid": None, "reason": "timeout"}

    return {"email": email, **result}


async def verify_emails(emails: list[str], concurrency: int = 3) -> list[dict]:
    """Verify multiple emails with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(email: str) -> dict:
        async with sem:
            return await verify_email(email)

    return await asyncio.gather(*[_bounded(e) for e in emails])
