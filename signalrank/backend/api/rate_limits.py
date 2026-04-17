import time
from collections import defaultdict, deque

from fastapi import HTTPException

_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)


async def enforce_user_rate_limit(
    user_id: str,
    action: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    now = time.monotonic()
    key = (str(user_id), action)
    events = _events[key]
    cutoff = now - window_seconds
    while events and events[0] <= cutoff:
        events.popleft()
    if len(events) >= limit:
        retry_after = max(1, int(events[0] + window_seconds - now))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {action}; retry later",
            headers={"Retry-After": str(retry_after)},
        )
    events.append(now)
