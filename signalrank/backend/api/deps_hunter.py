from api.config import settings
from batch.hunter import HunterClient

_client: HunterClient | None = None


def get_hunter_client() -> HunterClient | None:
    global _client
    if not settings.hunter_api_key:
        return None
    if _client is None:
        _client = HunterClient(api_key=settings.hunter_api_key)
    return _client
