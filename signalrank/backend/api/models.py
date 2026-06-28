from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from api.database import Base
from api.db_types import GUID, JSONField, VectorField, gen_uuid


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
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

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    resume_text: Mapped[str | None] = mapped_column(Text)
    resume_embedding: Mapped[list[float] | None] = mapped_column(VectorField(384))
    distilled_text: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[dict | None] = mapped_column(JSONField())
    target_roles: Mapped[dict | None] = mapped_column(JSONField())
    target_companies: Mapped[dict | None] = mapped_column(JSONField())
    preferred_locations: Mapped[dict | None] = mapped_column(JSONField())
    min_salary: Mapped[int | None] = mapped_column(Integer)
    min_yoe: Mapped[int | None] = mapped_column(Integer)
    max_yoe: Mapped[int | None] = mapped_column(Integer)
    role_intent: Mapped[str | None] = mapped_column(String(100))
    config_overrides: Mapped[dict | None] = mapped_column(JSONField())
    candidate_profile: Mapped[dict | None] = mapped_column(JSONField())
    target_lpa: Mapped[float | None] = mapped_column(Float)
    custom_search_queries: Mapped[list | None] = mapped_column(JSONField())
    scraper_hours_old: Mapped[int | None] = mapped_column(Integer)
    scraper_max_terms: Mapped[int | None] = mapped_column(Integer)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="profile")


class JobRaw(Base):
    __tablename__ = "jobs_raw"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    job_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    company: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    site: Mapped[str | None] = mapped_column(String(100))
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_urls: Mapped[list | None] = mapped_column(
        JSONField(), default=list
    )
    embedding: Mapped[list[float] | None] = mapped_column(VectorField(384))
    job_profile: Mapped[dict | None] = mapped_column(JSONField())
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    role_clusters: Mapped[list | None] = mapped_column(JSONField(), default=list)

    results: Mapped[list["JobResult"]] = relationship(back_populates="job")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_user_started", "user_id", "started_at"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_status_mode_started", "status", "mode", "started_at"),
        Index("ix_runs_claim", "status", "mode", "lease_expires_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    mode: Mapped[str] = mapped_column(String(20), default="quick", server_default="quick", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_count: Mapped[int | None] = mapped_column(Integer)
    scrape_count: Mapped[int | None] = mapped_column(Integer)
    progress: Mapped[dict | None] = mapped_column(JSONField())
    error: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[str | None] = mapped_column(String(255))
    claim_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    trigger_source: Mapped[str | None] = mapped_column(String(50))
    executor_type: Mapped[str | None] = mapped_column(String(50))

    user: Mapped["User"] = relationship(back_populates="runs")
    results: Mapped[list["JobResult"]] = relationship(back_populates="run")


class JobResult(Base):
    __tablename__ = "job_results"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs_raw.id"), nullable=False)
    semantic_score: Mapped[float | None] = mapped_column(Float)
    skills_score: Mapped[float | None] = mapped_column(Float)
    company_score: Mapped[float | None] = mapped_column(Float)
    seniority_score: Mapped[float | None] = mapped_column(Float)
    location_score: Mapped[float | None] = mapped_column(Float)
    recency_score: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float | None] = mapped_column(Float)
    title_relevance_score: Mapped[float | None] = mapped_column(Float)
    fit_band: Mapped[str | None] = mapped_column(String(50))
    confidence_band: Mapped[str | None] = mapped_column(String(50))
    explanation_summary: Mapped[str | None] = mapped_column(Text)
    match_report: Mapped[dict | None] = mapped_column(JSONField())
    verification_report: Mapped[dict | None] = mapped_column(JSONField())
    company_tier: Mapped[str | None] = mapped_column(String(50))
    is_contract: Mapped[bool | None] = mapped_column(Boolean)
    archived_by_llm: Mapped[bool | None] = mapped_column(Boolean)
    archival_reason: Mapped[str | None] = mapped_column(String(500))
    # --- JobDigest additions ---
    work_auth_verdict: Mapped[str | None] = mapped_column(String(50))
    work_auth_evidence: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(100))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_job_results_user_job"),
        Index("ix_job_results_user_score", "user_id", "final_score"),
        Index("ix_jr_user_archived", "user_id", "archived_by_llm"),
        Index("ix_jr_user_tier", "user_id", "company_tier"),
    )

    run: Mapped["Run"] = relationship(back_populates="results")
    job: Mapped["JobRaw"] = relationship(back_populates="results")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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


class JobPreferenceMemory(Base):
    __tablename__ = "job_preference_memory"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    state_json: Mapped[dict | None] = mapped_column(JSONField(), default=dict)
    summary_json: Mapped[dict | None] = mapped_column(JSONField(), default=dict)
    last_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobFeedbackEvent(Base):
    __tablename__ = "job_feedback_events"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(GUID(), index=True)
    feedback_text: Mapped[str | None] = mapped_column(Text)
    quick_actions: Mapped[list | None] = mapped_column(JSONField(), default=list)
    job_ids: Mapped[list | None] = mapped_column(JSONField(), default=list)
    job_snapshots: Mapped[list | None] = mapped_column(JSONField(), default=list)
    extracted_delta: Mapped[dict | None] = mapped_column(JSONField(), default=dict)
    session_context: Mapped[dict | None] = mapped_column(JSONField(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_job_feedback_events_user_created", "user_id", "created_at"),
    )


class Recruiter(Base):
    __tablename__ = "recruiters"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
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

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    company: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_candidates: Mapped[dict | None] = mapped_column(JSONField())


class QueryPlanCache(Base):
    __tablename__ = "query_plan_cache"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    cache_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    profile_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    search_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filter: Mapped[str] = mapped_column(Text, nullable=False)
    query_version: Mapped[str] = mapped_column(String(100), nullable=False)
    max_terms: Mapped[int] = mapped_column(Integer, nullable=False)
    query_payload: Mapped[dict | None] = mapped_column(JSONField(), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_query_plan_cache_profile_window", "profile_fingerprint", "search_window_days"),
        Index("ix_query_plan_cache_source_filter", "source_filter"),
    )


class ScrapeQueryCache(Base):
    __tablename__ = "scrape_query_cache"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    site: Mapped[str] = mapped_column(String(50), nullable=False)
    term_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    location_normalized: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    country_normalized: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    hours_old: Mapped[int] = mapped_column(Integer, nullable=False)
    result_job_urls: Mapped[list | None] = mapped_column(JSONField(), default=list)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fresh_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "site",
            "term_normalized",
            "location_normalized",
            "country_normalized",
            "hours_old",
            name="uq_scrape_query_cache_key",
        ),
        Index("ix_scrape_query_cache_fresh_until", "provider", "site", "fresh_until"),
    )


class RecruiterRefreshTask(Base):
    __tablename__ = "recruiter_refresh_tasks"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    progress_json: Mapped[dict | None] = mapped_column(JSONField())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TailoredResume(Base):
    __tablename__ = "tailored_resumes"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs_raw.id"))
    content_json: Mapped[dict | None] = mapped_column(JSONField())
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    template: Mapped[str] = mapped_column(String(50), default="classic")
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_tailored_resume_user_job"),)


class GenerationQueue(Base):
    __tablename__ = "generation_queue"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
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

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
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

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)
    text_fp: Mapped[str] = mapped_column(String(64), nullable=False)
    cfg_fp: Mapped[str] = mapped_column(String(32), nullable=False)
    vector: Mapped[list[float]] = mapped_column(VectorField(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("text_fp", "cfg_fp", name="uq_embedding_text_cfg"),
    )


class LLMCache(Base):
    __tablename__ = "llm_cache"

    prompt_hash: Mapped[str] = mapped_column(String(32), primary_key=True)
    response_json: Mapped[dict] = mapped_column(JSONField(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
