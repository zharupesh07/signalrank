import argparse
import pytest

from batch.worker_main import build_parser, resolve_db_url


def test_build_parser_poll_mode():
    parser = build_parser()
    args = parser.parse_args(["poll"])
    assert args.mode == "poll"
    assert args.once is False


def test_build_parser_run_once_flag():
    parser = build_parser()
    args = parser.parse_args(["poll", "--once"])
    assert args.once is True


def test_build_parser_enqueue_cron_mode():
    parser = build_parser()
    args = parser.parse_args(["enqueue-cron"])
    assert args.mode == "enqueue-cron"


def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["poll"])
    assert args.scan_modes == ["quick", "full"]
    assert args.concurrency == 1


def test_build_parser_custom_scan_modes():
    parser = build_parser()
    args = parser.parse_args(["poll", "--scan-modes", "full"])
    assert args.scan_modes == ["full"]


def test_resolve_db_url_uses_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@host/db")
    monkeypatch.delenv("DATABASE_URL_RAILWAY", raising=False)
    url = resolve_db_url()
    assert "host/db" in url


def test_resolve_db_url_prefers_railway(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://fallback/db")
    monkeypatch.setenv("DATABASE_URL_RAILWAY", "postgresql+asyncpg://railway/prod")
    url = resolve_db_url()
    assert "railway/prod" in url
