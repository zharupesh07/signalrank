from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select

from api.models import (
    ArchivalQueue,
    Application,
    GenerationQueue,
    JobResult,
    Profile,
    RecruiterRefreshTask,
    Run,
    TailoredResume,
    User,
)


async def delete_user_ids(session_factory, user_ids: Sequence[str]) -> int:
    ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not ids:
        return 0

    deleted = 0
    async with session_factory() as db:
        for user_id in sorted(set(ids)):
            await db.execute(delete(ArchivalQueue).where(ArchivalQueue.user_id == user_id))
            await db.execute(delete(GenerationQueue).where(GenerationQueue.user_id == user_id))
            await db.execute(delete(TailoredResume).where(TailoredResume.user_id == user_id))
            await db.execute(delete(RecruiterRefreshTask).where(RecruiterRefreshTask.user_id == user_id))
            await db.execute(delete(JobResult).where(JobResult.user_id == user_id))
            await db.execute(delete(Run).where(Run.user_id == user_id))
            await db.execute(delete(Application).where(Application.user_id == user_id))
            await db.execute(delete(Profile).where(Profile.user_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))
            deleted += 1
        await db.commit()
    return deleted


async def delete_users_by_email_prefixes(session_factory, prefixes: Sequence[str]) -> int:
    normalized_prefixes = [str(prefix).strip().lower() for prefix in prefixes if str(prefix).strip()]
    if not normalized_prefixes:
        return 0

    async with session_factory() as db:
        result = await db.execute(select(User.id, User.email))
        rows = result.all()

    matching_ids = [
        str(user_id)
        for user_id, email in rows
        if any(str(email).lower().startswith(prefix) for prefix in normalized_prefixes)
    ]
    return await delete_user_ids(session_factory, matching_ids)
