import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    yield
