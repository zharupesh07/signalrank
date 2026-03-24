import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.main import app
from api.models import User


FAKE_USER_ID = uuid.uuid4()
FAKE_JOB_ID = str(uuid.uuid4())

FAKE_CONTENT_JSON = {
    "name": "Test User",
    "email": "test@example.com",
    "phone": "+1 555 0000",
    "location": "Remote",
    "homepage": "",
    "linkedin": "linkedin.com/in/testuser",
    "github": "github.com/testuser",
    "position": "ML Engineer",
    "summary": "ML engineer.",
    "skills": [],
    "experiences": [],
    "projects": [],
    "education": [],
    "certifications": [],
}


def _fake_user():
    u = MagicMock(spec=User)
    u.id = FAKE_USER_ID
    return u


def _make_client(db_session):
    app.dependency_overrides[get_current_user] = lambda: _fake_user()
    app.dependency_overrides[get_llm_client] = lambda: MagicMock()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_download_returns_202_when_no_tailored_resume():
    db = AsyncMock(spec=AsyncSession)
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=not_found)

    async with _make_client(db) as client:
        r = await client.get(f"/api/resume/tailor/{FAKE_JOB_ID}")

    app.dependency_overrides.clear()

    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "pending"
    assert data["job_id"] == FAKE_JOB_ID


@pytest.mark.asyncio
async def test_download_rerenders_from_cache_no_llm():
    fake_tailored = MagicMock()
    fake_tailored.content_json = FAKE_CONTENT_JSON
    fake_tailored.template = "classic"

    found = MagicMock()
    found.scalar_one_or_none.return_value = fake_tailored

    no_job = MagicMock()
    no_job.scalar_one_or_none.return_value = None

    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=[found, no_job])

    pdf_bytes = b"%PDF-fake"

    with patch("api.routes.resume.tailor_resume") as mock_llm, \
         patch("api.routes.resume.render_typst", return_value="#typst") as mock_render, \
         patch("api.routes.resume.compile_pdf", return_value=pdf_bytes):

        async with _make_client(db) as client:
            r = await client.get(f"/api/resume/tailor/{FAKE_JOB_ID}?template=modern")

        app.dependency_overrides.clear()

        mock_llm.assert_not_called()
        mock_render.assert_called_once()
        assert mock_render.call_args.args[1] == "modern"
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
