from api.models import GenerationQueue


def test_generation_queue_model_exists():
    assert GenerationQueue.__tablename__ == "generation_queue"
    assert hasattr(GenerationQueue, "user_id")
    assert hasattr(GenerationQueue, "job_id")
    assert hasattr(GenerationQueue, "status")
    assert hasattr(GenerationQueue, "error")


import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_process_generation_task_creates_tailored_resume():
    """Worker processes a pending task and saves TailoredResume."""
    from batch.resume_worker import process_generation_task
    task = MagicMock()
    task.user_id = "user-1"
    task.job_id = "job-1"
    task.id = "task-1"

    mock_content = MagicMock()
    mock_content.name = "Test User"
    mock_content.position = "Engineer"
    mock_content.email = ""
    mock_content.phone = ""
    mock_content.homepage = ""
    mock_content.linkedin = ""
    mock_content.github = ""
    mock_content.location = ""
    mock_content.summary = "Summary."
    mock_content.skills = []
    mock_content.experiences = []
    mock_content.education = []
    mock_content.projects = []
    mock_content.certifications = []

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock(return_value={
        "name": "Test", "email": "", "phone": "", "location": "",
        "homepage": "", "linkedin": "", "github": "",
        "position": "Engineer", "summary": "Summary.",
        "skills": [], "experiences": [], "projects": [],
        "education": [], "certifications": [],
    })

    mock_profile = MagicMock()
    mock_profile.resume_text = "resume text"

    mock_job = MagicMock()
    mock_job.title = "ML Engineer"
    mock_job.description = "Job desc"

    db = AsyncMock(spec=AsyncSession)
    execute_results = [
        MagicMock(**{"scalar_one_or_none.return_value": None}),
        MagicMock(**{"scalar_one_or_none.return_value": mock_profile}),
        MagicMock(**{"scalar_one_or_none.return_value": mock_job}),
        MagicMock(),
    ]
    db.execute = AsyncMock(side_effect=execute_results)
    db.commit = AsyncMock()
    db.add = MagicMock()

    with patch("batch.resume_worker.tailor_resume", AsyncMock(return_value=mock_content)):
        await process_generation_task(task, db, mock_llm)

    db.add.assert_called_once()
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_process_generation_task_skips_if_resume_exists():
    """Worker skips task if TailoredResume already exists."""
    from batch.resume_worker import process_generation_task

    task = MagicMock()
    task.user_id = "user-1"
    task.job_id = "job-1"
    task.id = "task-1"

    mock_existing = MagicMock()
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=[
        MagicMock(**{"scalar_one_or_none.return_value": mock_existing}),
        MagicMock(),
    ])
    db.commit = AsyncMock()
    db.add = MagicMock()

    mock_llm = MagicMock()
    mock_llm.llm_json = AsyncMock()

    with patch("batch.resume_worker.tailor_resume") as mock_tailor:
        await process_generation_task(task, db, mock_llm)

    mock_tailor.assert_not_called()
    db.add.assert_not_called()
