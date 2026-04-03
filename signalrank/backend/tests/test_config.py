import pytest

from api import config as config_mod


pytestmark = pytest.mark.unit


def test_normalize_origin_candidate_handles_urls_and_domains():
    assert config_mod._normalize_origin_candidate("https://app.example.com/path") == "https://app.example.com"
    assert config_mod._normalize_origin_candidate("frontend.up.railway.app") == "https://frontend.up.railway.app"
    assert config_mod._normalize_origin_candidate("localhost:3000") == "http://localhost:3000"
    assert config_mod._normalize_origin_candidate("not a url") is None


def test_effective_allowed_origins_merges_deployment_frontend_urls(monkeypatch):
    monkeypatch.setattr(config_mod.settings, "allowed_origins", ["http://localhost:3000"])
    monkeypatch.setenv("NEXTAUTH_URL", "https://signalrank-web.up.railway.app")
    monkeypatch.setenv("VERCEL_URL", "signalrank.vercel.app")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "signalrank-web-production.up.railway.app")

    origins = config_mod.effective_allowed_origins()

    assert "http://localhost:3000" in origins
    assert "https://signalrank-web.up.railway.app" in origins
    assert "https://signalrank.vercel.app" in origins
    assert "https://signalrank-web-production.up.railway.app" in origins
