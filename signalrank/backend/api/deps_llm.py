from api.config import settings
from llm.providers import build_llm_client

_client = None


def get_llm_client():
    global _client
    if _client is None:
        _client = build_llm_client(provider=settings.llm_provider)
    return _client
