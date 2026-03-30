"""Development-only endpoints for local debugging (admin only)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.config import settings
from api.database import get_db_info, switch_database
from api.deps import get_current_user
from api.models import User

router = APIRouter(prefix="/api/dev", tags=["dev"])


def _require_dev(current_user: User = Depends(get_current_user)) -> User:
    if settings.environment != "development":
        raise HTTPException(status_code=403, detail="Only available in development environment")
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


@router.get("/db")
async def get_db_status(_: User = Depends(_require_dev)):
    return get_db_info()


class SwitchDbRequest(BaseModel):
    target: str  # "local" | "railway"


@router.post("/db/switch")
async def switch_db(body: SwitchDbRequest, _: User = Depends(_require_dev)):
    if body.target not in {"local", "railway"}:
        raise HTTPException(status_code=422, detail="target must be 'local' or 'railway'")
    try:
        await switch_database(body.target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to {body.target} DB: {e}")
    return get_db_info()
