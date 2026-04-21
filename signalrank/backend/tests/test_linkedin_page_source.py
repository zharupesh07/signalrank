from unittest.mock import AsyncMock

import pytest

from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig
from batch.sources import linkedin_page


HTML = """
<html>
  <body>
    <ul class="jobs-search__results-list">
      <li>
        <div class="job-card-container">
          <a class="base-card__full-link" href="/jobs/view/4401421231">
            <h3 class="base-search-card__title">Agentic AI</h3>
          </a>
          <h4 class="base-search-card__subtitle">Neurealm</h4>
          <span class="job-search-card__location">Pune City (On-site)</span>
          <time datetime="2026-04-15T15:34:00.000Z"></time>
        </div>
      </li>
      <li>
        <div class="job-card-container">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/4401920190">
            <h3 class="base-search-card__title">Agentic AI Engineer</h3>
          </a>
          <h4 class="base-search-card__subtitle">Persistent Systems</h4>
          <span class="job-search-card__location">Pune City, Maharashtra, India</span>
        </div>
      </li>
    </ul>
  </body>
</html>
"""


def test_build_search_url_includes_keywords_and_location():
    url = linkedin_page._build_search_url(SearchQuery(term="agentic ai", location="Pune", country="India"))

    assert "keywords=agentic+ai" in url
    assert "location=Pune" in url


def test_extract_job_cards_parses_expected_fields():
    jobs = linkedin_page._extract_job_cards(HTML)

    assert [job.job_url for job in jobs] == [
        "https://www.linkedin.com/jobs/view/4401421231",
        "https://www.linkedin.com/jobs/view/4401920190",
    ]
    assert jobs[0].title == "Agentic AI"
    assert jobs[0].company == "Neurealm"
    assert jobs[0].location == "Pune City (On-site)"
    assert jobs[0].site == "linkedin_page"
    assert jobs[0].date_posted is not None
    assert jobs[1].title == "Agentic AI Engineer"
    assert jobs[1].company == "Persistent Systems"


@pytest.mark.asyncio
async def test_scrape_url_returns_empty_on_login_redirect(monkeypatch):
    async def fake_fetch(*_args, **_kwargs):
        return "<title>LinkedIn Login, Sign in | LinkedIn</title>", "https://www.linkedin.com/uas/login"

    monkeypatch.setattr(linkedin_page, "_fetch_html", AsyncMock(side_effect=fake_fetch))

    jobs = await linkedin_page.scrape_url("https://www.linkedin.com/jobs/search-results/", ScraperConfig())

    assert jobs == []


@pytest.mark.asyncio
async def test_search_uses_cache_without_fetch(monkeypatch):
    cached_jobs = [
        linkedin_page.RawJob(
            job_url="https://www.linkedin.com/jobs/view/1",
            title="Agentic AI Engineer",
            company="Neurealm",
            description=None,
            location="Pune",
            site="linkedin_page",
            date_posted=None,
        )
    ]
    monkeypatch.setattr(linkedin_page, "load_cached_jobs", AsyncMock(return_value=cached_jobs))
    monkeypatch.setattr(linkedin_page, "store_cached_jobs", AsyncMock())
    monkeypatch.setattr(linkedin_page, "scrape_url", AsyncMock(side_effect=AssertionError("cache miss")))

    results = await linkedin_page.search(
        [SearchQuery(term="agentic ai", location="Pune", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://www.linkedin.com/jobs/view/1"]
