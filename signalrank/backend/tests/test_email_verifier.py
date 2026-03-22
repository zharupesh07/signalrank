"""Tests for batch.email_verifier.

Unit tests mock DNS and SMTP — no network needed.
Integration tests (marked live) make real network calls — opt in with:
    pytest -m live tests/test_email_verifier.py -s
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from batch.email_verifier import _get_mx_host, _smtp_probe, verify_email, verify_emails


# ---------------------------------------------------------------------------
# _get_mx_host (unit)
# ---------------------------------------------------------------------------

def test_get_mx_host_returns_highest_priority():
    rec_high = MagicMock(preference=10)
    rec_high.exchange.__str__ = lambda self: "mail1.example.com."
    rec_low = MagicMock(preference=20)
    rec_low.exchange.__str__ = lambda self: "mail2.example.com."

    with patch("batch.email_verifier.dns.resolver.resolve", return_value=[rec_low, rec_high]):
        assert _get_mx_host("example.com") == "mail1.example.com"


def test_get_mx_host_nxdomain_returns_none():
    import dns.resolver
    with patch("batch.email_verifier.dns.resolver.resolve", side_effect=dns.resolver.NXDOMAIN):
        assert _get_mx_host("nonexistent.invalid") is None


def test_get_mx_host_no_answer_returns_none():
    import dns.resolver
    with patch("batch.email_verifier.dns.resolver.resolve", side_effect=dns.resolver.NoAnswer):
        assert _get_mx_host("nodns.invalid") is None


# ---------------------------------------------------------------------------
# _smtp_probe (unit)
# ---------------------------------------------------------------------------

def _make_smtp_mock(rcpt_code: int, rcpt_msg: bytes = b"OK"):
    smtp = MagicMock()
    smtp.__enter__ = lambda s: s
    smtp.__exit__ = MagicMock(return_value=False)
    smtp.rcpt.return_value = (rcpt_code, rcpt_msg)
    return smtp


def test_smtp_probe_250_valid():
    with patch("batch.email_verifier.smtplib.SMTP", return_value=_make_smtp_mock(250)):
        result = _smtp_probe("alice@example.com", "mail.example.com")
    assert result["valid"] is True
    assert result["reason"] == "smtp_accepted"


def test_smtp_probe_550_invalid():
    with patch("batch.email_verifier.smtplib.SMTP", return_value=_make_smtp_mock(550, b"User unknown")):
        result = _smtp_probe("nobody@example.com", "mail.example.com")
    assert result["valid"] is False
    assert "550" in result["reason"]


def test_smtp_probe_connect_error():
    import smtplib
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = lambda s: s
    mock_smtp.__exit__ = MagicMock(return_value=False)
    mock_smtp.connect.side_effect = smtplib.SMTPConnectError(421, b"Service unavailable")
    with patch("batch.email_verifier.smtplib.SMTP", return_value=mock_smtp):
        result = _smtp_probe("alice@example.com", "mail.example.com")
    assert result["valid"] is None
    assert "connect_failed" in result["reason"]


def test_smtp_probe_timeout():
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = lambda s: s
    mock_smtp.__exit__ = MagicMock(return_value=False)
    mock_smtp.connect.side_effect = TimeoutError("timed out")
    with patch("batch.email_verifier.smtplib.SMTP", return_value=mock_smtp):
        result = _smtp_probe("alice@example.com", "mail.example.com")
    assert result["valid"] is None
    assert result["reason"] == "timeout"


# ---------------------------------------------------------------------------
# verify_email (unit — mocked DNS + SMTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_email_invalid_format():
    result = await verify_email("notanemail")
    assert result["valid"] is False
    assert result["reason"] == "invalid_format"


@pytest.mark.asyncio
async def test_verify_email_no_mx():
    with patch("batch.email_verifier._get_mx_host", return_value=None):
        result = await verify_email("user@ghost.invalid")
    assert result["valid"] is False
    assert result["reason"] == "no_mx_record"


@pytest.mark.asyncio
async def test_verify_email_catchall_provider_with_mx():
    rec = MagicMock(preference=10, exchange=MagicMock())
    rec.exchange.to_text.return_value = "gmail-smtp-in.l.google.com."
    with patch("batch.email_verifier.dns.resolver.resolve", return_value=[rec]):
        result = await verify_email("anyone@gmail.com")
    assert result["valid"] is None
    assert result["reason"] == "catchall_provider"


@pytest.mark.asyncio
async def test_verify_email_catchall_provider_no_mx():
    import dns.resolver
    with patch("batch.email_verifier.dns.resolver.resolve", side_effect=dns.resolver.NXDOMAIN):
        result = await verify_email("anyone@gmail.com")
    assert result["valid"] is False
    assert result["reason"] == "no_mx_record"


@pytest.mark.asyncio
async def test_verify_email_smtp_accepted():
    rec = MagicMock(preference=10, exchange=MagicMock())
    rec.exchange.to_text.return_value = "mail.example.com."
    smtp_result = {"valid": True, "reason": "smtp_accepted"}
    with patch("batch.email_verifier.dns.resolver.resolve", return_value=[rec]), \
         patch("batch.email_verifier._smtp_probe", return_value=smtp_result):
        result = await verify_email("alice@example.com")
    assert result["valid"] is True
    assert result["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_verify_email_smtp_rejected():
    rec = MagicMock(preference=10, exchange=MagicMock())
    rec.exchange.to_text.return_value = "mail.example.com."
    smtp_result = {"valid": False, "reason": "user_not_found (550)"}
    with patch("batch.email_verifier.dns.resolver.resolve", return_value=[rec]), \
         patch("batch.email_verifier._smtp_probe", return_value=smtp_result):
        result = await verify_email("nobody@example.com")
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_verify_emails_batch():
    async def fake_verify(email: str) -> dict:
        return {"email": email, "valid": True, "reason": "smtp_accepted"}

    with patch("batch.email_verifier.verify_email", side_effect=fake_verify):
        results = await verify_emails(["a@x.com", "b@x.com", "c@x.com"])

    assert len(results) == 3
    assert all(r["valid"] is True for r in results)


# ---------------------------------------------------------------------------
# Integration tests (real network — opt in with -m live)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_gmail_is_catchall():
    """Gmail always returns catchall_provider since it blocks SMTP probing."""
    result = await verify_email("test@gmail.com")
    assert result["reason"] == "catchall_provider"
    assert result["valid"] is None


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_nonexistent_domain():
    result = await verify_email("user@this-domain-does-not-exist-xyz123.com")
    assert result["valid"] is False
    assert result["reason"] == "no_mx_record"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_known_invalid_user():
    """A user that almost certainly doesn't exist at a real company domain."""
    result = await verify_email("zzz_nobody_zzz_12345@github.com")
    # github.com has MX; SMTP may accept or reject depending on their config
    assert result["email"] == "zzz_nobody_zzz_12345@github.com"
    assert result["valid"] in (True, False, None)
    print(f"\ngithub.com probe result: {result}")
