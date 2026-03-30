"""Development-only endpoints for local debugging.

All routes here return 403 unless settings.environment == "development".
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.config import settings
from api.database import get_db_info, switch_database

router = APIRouter(prefix="/api/dev", tags=["dev"])


def _require_dev() -> None:
    if settings.environment != "development":
        raise HTTPException(status_code=403, detail="Only available in development environment")


@router.get("/db")
async def get_db():
    _require_dev()
    return get_db_info()


class SwitchDbRequest(BaseModel):
    target: str  # "local" | "railway"


@router.post("/db/switch")
async def switch_db(body: SwitchDbRequest):
    _require_dev()
    if body.target not in {"local", "railway"}:
        raise HTTPException(status_code=422, detail="target must be 'local' or 'railway'")
    try:
        await switch_database(body.target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not connect to {body.target} DB: {e}")
    return get_db_info()
