"""Tests for batch/local_worker.py orchestration."""
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.models import User, Profile, Run
from batch.local_worker import mirror_user_and_profile, create_run_in_railway


async def _make_railway_user_profile(db: AsyncSession) -> tuple[str, str]:
    """Creates User + Profile in DB, returns (user_id, profile_id)."""
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, email=f"{user_id}@rw.com", password_hash="x"))
    await db.flush()
    p = Profile(
        id=str(uuid.uuid4()),
        user_id=user_id,
        resume_text="Senior ML engineer with Python experience.",
        onboarding_complete=True,
        config_overrides={"current_focus": "mlops"},
    )
    db.add(p)
    await db.commit()
    return user_id, p.id


@pytest.mark.asyncio
async def test_mirror_user_and_profile_seeds_local_db(db: AsyncSession):
    """mirror_user_and_profile copies User + Profile to local DB."""
    user_id, _ = await _make_railway_user_profile(db)
    await mirror_user_and_profile(railway_db=db, local_db=db, user_id=user_id)
    profile = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()
    assert profile.resume_text == "Senior ML engineer with Python experience."
    assert profile.config_overrides == {"current_focus": "mlops"}


@pytest.mark.asyncio
async def test_mirror_user_and_profile_raises_if_user_not_found(db: AsyncSession):
    """mirror_user_and_profile raises RuntimeError if user not in railway_db."""
    with pytest.raises(RuntimeError, match="not found in Railway"):
        await mirror_user_and_profile(railway_db=db, local_db=db, user_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_create_run_in_railway(db: AsyncSession):
    """create_run_in_railway inserts a pending local run and returns its ID."""
    user_id, _ = await _make_railway_user_profile(db)
    run_id = await create_run_in_railway(railway_db=db, user_id=user_id, mode="quick")
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.executor_type == "local"
    assert run.status == "pending"
