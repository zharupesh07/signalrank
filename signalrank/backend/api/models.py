import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from api.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(50), default="credentials")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False)
    runs: Mapped[list["Run"]] = relationship(back_populates="user")
    applications: Mapped[list["Application"]] = relationship(back_populates="user")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    resume_text: Mapped[str | None] = mapped_column(Text)
    resume_embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    distilled_text: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[dict | None] = mapped_column(JSONB)
    target_roles: Mapped[dict | None] = mapped_column(JSONB)
    target_companies: Mapped[dict | None] = mapped_column(JSONB)
    preferred_locations: Mapped[dict | None] = mapped_column(JSONB)
    min_salary: Mapped[int | None] = mapped_column(Integer)
    min_yoe: Mapped[int | None] = mapped_column(Integer)
    max_yoe: Mapped[int | None] = mapped_column(Integer)
    role_intent: Mapped[str | None] = mapped_column(String(100))
    config_overrides: Mapped[dict | None] = mapped_column(JSONB)
    target_lpa: Mapped[float | None] = mapped_column(Float)
    custom_search_queries: Mapped[list | None] = mapped_column(JSONB)
    scraper_hours_old: Mapped[int | None] = mapped_column(Integer)
    scraper_max_terms: Mapped[int | None] = mapped_column(Integer)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="profile")


class JobRaw(Base):
    __tablename__ = "jobs_raw"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    job_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    company: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    site: Mapped[str | None] = mapped_column(String(100))
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    results: Mapped[list["JobResult"]] = relationship(back_populates="job")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_count: Mapped[int | None] = mapped_column(Integer)
    scrape_count: Mapped[int | None] = mapped_column(Integer)
    progress: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped["User"] = relationship(back_populates="runs")
    results: Mapped[list["JobResult"]] = relationship(back_populates="run")


class JobResult(Base):
    __tablename__ = "job_results"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs_raw.id"), nullable=False)
    semantic_score: Mapped[float | None] = mapped_column(Float)
    skills_score: Mapped[float | None] = mapped_column(Float)
    company_score: Mapped[float | None] = mapped_column(Float)
    seniority_score: Mapped[float | None] = mapped_column(Float)
    location_score: Mapped[float | None] = mapped_column(Float)
    recency_score: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float | None] = mapped_column(Float)
    company_tier: Mapped[str | None] = mapped_column(String(50))
    is_contract: Mapped[bool | None] = mapped_column(Boolean)
    archived_by_llm: Mapped[bool | None] = mapped_column(Boolean)
    archival_reason: Mapped[str | None] = mapped_column(String(500))

    run: Mapped["Run"] = relationship(back_populates="results")
    job: Mapped["JobRaw"] = relationship(back_populates="results")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs_raw.id"))
    company: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(100), default="interested")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(10))
    location_group: Mapped[str | None] = mapped_column(String(100))
    interview_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer_lpa: Mapped[float | None] = mapped_column(Float)
    system_score: Mapped[float | None] = mapped_column(Float)
    resume_match_pct: Mapped[float | None] = mapped_column(Float)
    recruiter_id: Mapped[str | None] = mapped_column(ForeignKey("recruiters.id"))

    user: Mapped["User"] = relationship(back_populates="applications")
    job: Mapped["JobRaw | None"] = relationship()
    recruiter: Mapped["Recruiter | None"] = relationship()

    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),)


class Recruiter(Base):
    __tablename__ = "recruiters"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    company: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[str | None] = mapped_column(String(20))
    email_source: Mapped[str | None] = mapped_column(String(50))
    email_verified: Mapped[bool | None] = mapped_column(Boolean)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("company", "linkedin_url", name="uq_recruiter_company_linkedin"),)


class RecruiterSearch(Base):
    __tablename__ = "recruiter_searches"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    company: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_candidates: Mapped[dict | None] = mapped_column(JSONB)


class RecruiterRefreshTask(Base):
    __tablename__ = "recruiter_refresh_tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    progress_json: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TailoredResume(Base):
    __tablename__ = "tailored_resumes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs_raw.id"))
    content_json: Mapped[dict | None] = mapped_column(JSONB)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    template: Mapped[str] = mapped_column(String(50), default="classic")
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_tailored_resume_user_job"),)


class GenerationQueue(Base):
    __tablename__ = "generation_queue"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs_raw.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_generation_queue_user_job"),
    )


class ArchivalQueue(Base):
    __tablename__ = "archival_queue"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_result_id: Mapped[str] = mapped_column(ForeignKey("job_results.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("user_id", "job_result_id", name="uq_archival_queue_user_job_result"),
    )


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    text_fp: Mapped[str] = mapped_column(String(64), nullable=False)
    cfg_fp: Mapped[str] = mapped_column(String(32), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("text_fp", "cfg_fp", name="uq_embedding_text_cfg"),
    )


class LLMCache(Base):
    __tablename__ = "llm_cache"

    prompt_hash: Mapped[str] = mapped_column(String(32), primary_key=True)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
