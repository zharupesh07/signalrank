from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

from tools import rank_resume_existing_corpus as ranker

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 20
DEFAULT_CANDIDATE_POOL = 150
DEFAULT_LOOKBACK_HOURS = 24 * 60
DEFAULT_BATCH_SIZE = 16
DEFAULT_MAX_DESCRIPTION_CHARS = 2400
DEFAULT_PREFILTER_MAX_JOBS = 600
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / "tmp" / "resume_existing_corpus_rank" / "_scrape_cache"
DEFAULT_INDEX_DIR = Path(__file__).resolve().parents[1] / "tmp" / "semantic_job_search" / "_embedding_cache"
DEFAULT_CORPUS_DB = Path(__file__).resolve().parents[1] / "tmp" / "unified_job_corpus" / "unified_job_corpus.sqlite"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    query_prefix: str = ""
    document_prefix: str = ""
    max_length: int = 512
    normalize: bool = True
    truncate_dim: int | None = None
    default_enabled: bool = True


@dataclass(frozen=True)
class JobDoc:
    job_url: str
    title: str
    company: str
    location: str
    description: str
    date_posted: str | None
    source_terms: tuple[str, ...]


@dataclass(frozen=True)
class QueryProbe:
    name: str
    text: str


MODEL_CATALOG: dict[str, ModelSpec] = {
    "minilm": ModelSpec(
        name="minilm",
        repo_id="sentence-transformers/all-MiniLM-L6-v2",
        max_length=256,
    ),
    "bge-small": ModelSpec(
        name="bge-small",
        repo_id="BAAI/bge-small-en-v1.5",
        query_prefix="Represent this sentence for searching relevant passages: ",
        max_length=512,
    ),
    "embeddinggemma": ModelSpec(
        name="embeddinggemma",
        repo_id="onnx-community/embeddinggemma-300m-ONNX",
        query_prefix="task: search result | query: ",
        document_prefix="title: none | text: ",
        max_length=2048,
        truncate_dim=256,
        default_enabled=False,
    ),
}


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-") or "search"


def _dedupe_strs(values: list[str] | tuple[str, ...] | None, *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if limit is not None and len(result) >= limit:
            break
    return result


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_resume_text(path: Path) -> str:
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ranker._load_resume_text(path)
        parts: list[str] = [
            str(payload.get("name") or payload.get("label") or ""),
            str(payload.get("position") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("location") or ""),
        ]
        for experience in payload.get("experiences") or []:
            if not isinstance(experience, dict):
                continue
            parts.append(str(experience.get("title") or ""))
            parts.append(str(experience.get("company") or ""))
            parts.append(str(experience.get("tech") or ""))
            for bullet in experience.get("bullets") or []:
                parts.append(str(bullet))
        for group in payload.get("skills") or []:
            if not isinstance(group, dict):
                continue
            parts.append(str(group.get("category") or ""))
            parts.extend(str(item) for item in (group.get("items") or []))
        return "\n".join(_normalize_text(part) for part in parts if _normalize_text(part))
    return ranker._load_resume_text(path)


def _parse_date(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if iso_match:
        try:
            return datetime.fromisoformat(iso_match.group(0)).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _build_job_text(job: JobDoc, *, max_description_chars: int) -> str:
    sections = [
        f"TITLE: {job.title}",
        f"COMPANY: {job.company}",
        f"LOCATION: {job.location}",
        f"DESCRIPTION: {_normalize_text(job.description)[:max_description_chars]}",
    ]
    return "\n".join(section for section in sections if _normalize_text(section))


def _collect_jobs_from_scrape_cache(cache_dir: Path, *, lookback_hours: int | None = None) -> tuple[list[JobDoc], dict[str, Any]]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))
        if lookback_hours
        else None
    )
    jobs_by_url: dict[str, JobDoc] = {}
    files_scanned = 0
    skipped_old = 0
    for path in sorted(cache_dir.glob("*.json")):
        files_scanned += 1
        try:
            payload = json.loads(path.read_text())
        except Exception:
            logger.warning("Skipping unreadable cache file: %s", path)
            continue
        query = payload.get("query") or {}
        source_term = str(query.get("term") or "").strip()
        for item in payload.get("jobs") or []:
            if not isinstance(item, dict):
                continue
            job_url = str(item.get("job_url") or "").strip()
            if not job_url:
                continue
            parsed_date = _parse_date(str(item.get("date_posted") or ""))
            if cutoff and parsed_date and parsed_date < cutoff:
                skipped_old += 1
                continue
            previous = jobs_by_url.get(job_url)
            source_terms = _dedupe_strs(
                ([*previous.source_terms] if previous else []) + ([source_term] if source_term else []),
                limit=8,
            )
            jobs_by_url[job_url] = JobDoc(
                job_url=job_url,
                title=str(item.get("title") or (previous.title if previous else "") or ""),
                company=str(item.get("company") or (previous.company if previous else "") or ""),
                location=str(item.get("location") or (previous.location if previous else "") or ""),
                description=str(item.get("description") or (previous.description if previous else "") or ""),
                date_posted=str(item.get("date_posted") or (previous.date_posted if previous else "") or "") or None,
                source_terms=tuple(source_terms),
            )
    jobs = sorted(jobs_by_url.values(), key=lambda job: (job.date_posted or "", job.title.lower(), job.job_url), reverse=True)
    return jobs, {
        "cache_dir": str(cache_dir),
        "files_scanned": files_scanned,
        "jobs_loaded": len(jobs),
        "jobs_skipped_old": skipped_old,
        "lookback_hours": lookback_hours,
    }


def _collect_jobs_from_corpus_db(corpus_db: Path, *, lookback_hours: int | None = None) -> tuple[list[JobDoc], dict[str, Any]]:
    if not corpus_db.exists():
        raise FileNotFoundError(corpus_db)
    cutoff_iso = None
    if lookback_hours:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))).date().isoformat()
    conn = sqlite3.connect(corpus_db)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT
            job_url,
            title,
            company,
            location,
            description,
            date_posted,
            source_terms_json
        FROM jobs
    """
    params: list[Any] = []
    if cutoff_iso:
        query += " WHERE date_posted IS NULL OR date_posted >= ?"
        params.append(cutoff_iso)
    query += " ORDER BY COALESCE(date_posted, '') DESC, LOWER(title), job_url"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    jobs = [
        JobDoc(
            job_url=str(row["job_url"] or ""),
            title=str(row["title"] or ""),
            company=str(row["company"] or ""),
            location=str(row["location"] or ""),
            description=str(row["description"] or ""),
            date_posted=str(row["date_posted"] or "") or None,
            source_terms=tuple(json.loads(row["source_terms_json"] or "[]")),
        )
        for row in rows
        if str(row["job_url"] or "").strip()
    ]
    return jobs, {
        "corpus_db": str(corpus_db),
        "jobs_loaded": len(jobs),
        "lookback_hours": lookback_hours,
        "source": "sqlite",
    }


def _build_query_probes(resume_text: str, resume_path: Path, extra_probes: list[str]) -> tuple[list[QueryProbe], dict[str, Any]]:
    profile = ranker._extract_generic_profile(resume_text, resume_path.stem)
    signals = ranker._build_matching_signals(profile)
    keyword_queries = ranker._build_keyword_retrieval_queries(signals, profile.get("query_plan") or {})

    roles = _dedupe_strs(list(profile.get("suggested_roles") or []), limit=4)
    skills = _dedupe_strs(list(signals.get("must_have_skills") or []), limit=4)

    probes: list[QueryProbe] = [
        QueryProbe("resume_full", resume_text[:6000]),
        QueryProbe("candidate_summary", str(profile.get("candidate_summary") or "")),
    ]
    probes.extend(QueryProbe(f"role_{idx+1}", role) for idx, role in enumerate(roles[:3]))
    for idx, role in enumerate(roles[:2]):
        for skill in skills[:2]:
            probes.append(QueryProbe(f"role_skill_{idx+1}", f"{role} {skill}"))
    probes.extend(QueryProbe(f"keyword_{idx+1}", query) for idx, query in enumerate(keyword_queries[:4]))
    probes.extend(QueryProbe(f"manual_{idx+1}", probe) for idx, probe in enumerate(extra_probes))

    deduped: list[QueryProbe] = []
    seen: set[str] = set()
    for probe in probes:
        text = _normalize_text(probe.text)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        deduped.append(QueryProbe(probe.name, text))

    enriched_profile = dict(profile)
    enriched_profile["matching_signals"] = signals
    return deduped, enriched_profile


def _normalized_tokens(value: str) -> set[str]:
    return {token for token in ranker._extract_terms(value) if token not in ranker.STOPWORDS}


def _specific_role_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalized_tokens(value)
        if token not in ranker.GENERIC_ROLE_TOKENS
    }


def _build_profile_filter_terms(profile: dict[str, Any]) -> dict[str, list[str]]:
    signals = dict(profile.get("matching_signals") or {})
    primary_roles = _dedupe_strs(list(signals.get("primary_roles") or []), limit=4)
    adjacent_roles = _dedupe_strs(list(signals.get("adjacent_roles") or []), limit=6)
    broadened_roles = _dedupe_strs(list(signals.get("broadened_roles") or []), limit=8)
    must_skills = _dedupe_strs(list(signals.get("must_have_skills") or []), limit=6)
    support_skills = _dedupe_strs(list(signals.get("supporting_skills") or []), limit=6)
    role_terms = _dedupe_strs(primary_roles + adjacent_roles + broadened_roles, limit=12)
    return {
        "primary_roles": primary_roles,
        "adjacent_roles": adjacent_roles,
        "broadened_roles": broadened_roles,
        "must_skills": must_skills,
        "support_skills": support_skills,
        "all_roles": role_terms,
    }


def _job_prefilter_score(job: JobDoc, filter_terms: dict[str, list[str]]) -> float:
    title = _normalize_text(job.title).lower()
    description = _normalize_text(job.description).lower()
    combined = f"{title} {description}"
    source_terms = " ".join(job.source_terms).lower()

    primary_hits = sum(1 for role in filter_terms["primary_roles"] if role.lower() in combined or role.lower() in source_terms)
    adjacent_hits = sum(1 for role in filter_terms["adjacent_roles"] if role.lower() in combined or role.lower() in source_terms)
    broadened_hits = sum(1 for role in filter_terms["broadened_roles"] if role.lower() in combined or role.lower() in source_terms)
    must_skill_hits = sum(1 for skill in filter_terms["must_skills"] if skill.lower() in combined)
    support_skill_hits = sum(1 for skill in filter_terms["support_skills"] if skill.lower() in combined)

    title_tokens = _specific_role_tokens(job.title)
    role_token_overlap = 0
    for role in filter_terms["all_roles"]:
        role_token_overlap = max(role_token_overlap, len(_specific_role_tokens(role) & title_tokens))

    return (
        6.0 * primary_hits
        + 3.0 * adjacent_hits
        + 1.5 * broadened_hits
        + 2.25 * must_skill_hits
        + 0.8 * support_skill_hits
        + 1.2 * role_token_overlap
    )


def _prefilter_jobs_for_profile(
    jobs: list[JobDoc],
    profile: dict[str, Any],
    *,
    max_jobs: int,
) -> tuple[list[JobDoc], dict[str, Any]]:
    filter_terms = _build_profile_filter_terms(profile)
    scored: list[tuple[float, JobDoc]] = []
    for job in jobs:
        score = _job_prefilter_score(job, filter_terms)
        if score > 0:
            scored.append((score, job))
    scored.sort(key=lambda item: (-item[0], item[1].date_posted or "", item[1].title.lower(), item[1].job_url))
    filtered = [job for _, job in scored[:max_jobs]]
    if not filtered:
        filtered = jobs[:max_jobs]
    meta = {
        "input_jobs": len(jobs),
        "matched_jobs": len(scored),
        "selected_jobs": len(filtered),
        "max_jobs": max_jobs,
        "role_filters": filter_terms["all_roles"],
        "skill_filters": filter_terms["must_skills"],
    }
    return filtered, meta


class OnnxEmbedder:
    def __init__(self, spec: ModelSpec, *, allow_remote_download: bool, cpu_threads: int, batch_size: int):
        self.spec = spec
        self.batch_size = max(1, int(batch_size))
        model_path = hf_hub_download(repo_id=spec.repo_id, filename="onnx/model.onnx", local_files_only=not allow_remote_download)
        tokenizer_path = hf_hub_download(repo_id=spec.repo_id, filename="tokenizer.json", local_files_only=not allow_remote_download)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=spec.max_length)
        self.tokenizer.enable_padding(length=spec.max_length)
        sess_opts = ort.SessionOptions()
        sess_opts.inter_op_num_threads = 1
        sess_opts.intra_op_num_threads = max(1, min(cpu_threads, os.cpu_count() or 1))
        self.session = ort.InferenceSession(model_path, sess_opts, providers=["CPUExecutionProvider"])
        self.input_names = [item.name for item in self.session.get_inputs()]

    def _prepare_inputs(self, texts: list[str]) -> dict[str, np.ndarray]:
        encoded = self.tokenizer.encode_batch(texts)
        input_ids = np.array([item.ids for item in encoded], dtype=np.int64)
        attention_mask = np.array([item.attention_mask for item in encoded], dtype=np.int64)
        feeds: dict[str, np.ndarray] = {}
        if "input_ids" in self.input_names:
            feeds["input_ids"] = input_ids
        if "attention_mask" in self.input_names:
            feeds["attention_mask"] = attention_mask
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids, dtype=np.int64)
        return feeds

    def encode(self, texts: list[str], *, is_query: bool) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        prefix = self.spec.query_prefix if is_query else self.spec.document_prefix
        prepared = [f"{prefix}{text}" if prefix else text for text in texts]
        batches: list[np.ndarray] = []
        for start in range(0, len(prepared), self.batch_size):
            feeds = self._prepare_inputs(prepared[start : start + self.batch_size])
            outputs = self.session.run(None, feeds)
            values = outputs[0]
            if values.ndim == 3:
                attention_mask = feeds.get("attention_mask")
                if attention_mask is None:
                    vectors = values.mean(axis=1)
                else:
                    mask = attention_mask[:, :, None].astype(np.float32)
                    vectors = (values * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
            elif values.ndim == 2:
                vectors = values
            else:
                raise RuntimeError(f"Unexpected embedding output rank {values.ndim} for {self.spec.repo_id}")
            vectors = vectors.astype(np.float32, copy=False)
            if self.spec.truncate_dim:
                vectors = vectors[:, : self.spec.truncate_dim]
            if self.spec.normalize:
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                vectors = vectors / np.clip(norms, 1e-9, None)
            batches.append(vectors)
        return np.vstack(batches)


def _corpus_fingerprint(jobs: list[JobDoc]) -> str:
    raw = "\n".join(f"{job.job_url}|{job.date_posted or ''}" for job in sorted(jobs, key=lambda item: item.job_url))
    return sha256(raw.encode("utf-8")).hexdigest()


def _index_paths(index_dir: Path, spec: ModelSpec, corpus_fp: str) -> tuple[Path, Path]:
    index_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_slugify(spec.name)}-{corpus_fp[:16]}"
    return index_dir / f"{stem}.npz", index_dir / f"{stem}.json"


def _load_or_build_job_embeddings(
    jobs: list[JobDoc],
    spec: ModelSpec,
    *,
    index_dir: Path,
    refresh: bool,
    allow_remote_download: bool,
    cpu_threads: int,
    batch_size: int,
    max_description_chars: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    corpus_fp = _corpus_fingerprint(jobs)
    npz_path, meta_path = _index_paths(index_dir, spec, corpus_fp)
    urls = [job.job_url for job in jobs]
    if not refresh and npz_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        archive = np.load(npz_path, allow_pickle=False)
        if list(archive["urls"]) == urls:
            return archive["vectors"].astype(np.float32), {**meta, "cache_hit": True}

    embedder = OnnxEmbedder(
        spec,
        allow_remote_download=allow_remote_download,
        cpu_threads=cpu_threads,
        batch_size=batch_size,
    )
    job_texts = [_build_job_text(job, max_description_chars=max_description_chars) for job in jobs]
    vectors = embedder.encode(job_texts, is_query=False)
    np.savez_compressed(npz_path, vectors=vectors, urls=np.array(urls))
    meta = {
        "model": spec.name,
        "repo_id": spec.repo_id,
        "jobs": len(jobs),
        "embedding_dim": int(vectors.shape[1]) if vectors.size else 0,
        "cache_hit": False,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return vectors, meta


def _semantic_rank(
    jobs: list[JobDoc],
    doc_vectors: np.ndarray,
    query_vectors: np.ndarray,
    probes: list[QueryProbe],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    if not len(jobs) or not query_vectors.size or not doc_vectors.size:
        return []
    similarity = query_vectors @ doc_vectors.T
    best_idx = np.argmax(similarity, axis=0)
    best_score = np.max(similarity, axis=0)
    mean_score = np.mean(similarity, axis=0)
    aggregate = best_score + 0.1 * mean_score
    ranked = np.argsort(-aggregate)[:top_k]
    results: list[dict[str, Any]] = []
    for rank, doc_idx in enumerate(ranked, start=1):
        job = jobs[int(doc_idx)]
        probe = probes[int(best_idx[int(doc_idx)])]
        results.append({
            "rank": rank,
            "job_url": job.job_url,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "date_posted": job.date_posted,
            "semantic_score": float(aggregate[int(doc_idx)]),
            "best_probe": probe.name,
            "best_probe_text": probe.text,
            "source_terms": list(job.source_terms),
        })
    return results


def _deterministic_retrieve(
    jobs: list[JobDoc],
    profile: dict[str, Any],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    if not jobs:
        return []
    records = [
        ranker.JobRecord(
            job_url=job.job_url,
            title=job.title,
            company=job.company,
            location=job.location,
            site="unified_corpus",
            description=job.description,
            date_posted=job.date_posted,
        )
        for job in jobs
    ]
    scored = ranker._score_jobs(profile, records, agentic=False)
    top = scored[:top_k]
    return [
        {
            "rank": idx + 1,
            "job_url": item["job_url"],
            "title": item["title"],
            "company": item["company"],
            "location": item["location"],
            "date_posted": item.get("date_posted"),
            "description": item.get("description") or next((job.description for job in jobs if job.job_url == item["job_url"]), ""),
            "deterministic_score": float(item["final_score"]),
            "fit_band": item.get("fit_band") or "weak_fit",
        }
        for idx, item in enumerate(top)
    ]


def _hybrid_rerank(
    hits: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    candidate_pool: int,
    top_k: int,
) -> list[dict[str, Any]]:
    if not hits:
        return []
    deduped_hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        url = str(hit.get("job_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped_hits.append(hit)
    by_url = {hit["job_url"]: hit for hit in deduped_hits}
    shortlist = deduped_hits[:candidate_pool]
    jobs = [
        ranker.JobRecord(
            job_url=hit["job_url"],
            title=hit["title"],
            company=hit["company"],
            location=hit["location"],
            site="semantic_index",
            description="",
            date_posted=hit.get("date_posted"),
        )
        for hit in shortlist
    ]
    # Restore descriptions for deterministic scoring.
    job_lookup = {job.job_url: job for job in jobs}
    for hit in shortlist:
        job = job_lookup[hit["job_url"]]
        job_lookup[hit["job_url"]] = ranker.JobRecord(
            job_url=job.job_url,
            title=job.title,
            company=job.company,
            location=job.location,
            site=job.site,
            description=_normalize_text(by_url[job.job_url].get("description") or ""),
            date_posted=job.date_posted,
        )
    scored = ranker._score_jobs(profile, list(job_lookup.values()), agentic=False)
    det_by_url = {item["job_url"]: item for item in scored}
    reranked: list[dict[str, Any]] = []
    for hit in shortlist:
        det = det_by_url.get(hit["job_url"])
        det_score = float(det.get("final_score") if det else 0.0)
        semantic_score = ((float(hit["semantic_score"]) + 1.0) / 2.0) * 100.0
        hybrid_score = 0.55 * semantic_score + 0.45 * det_score
        reranked.append({
            **hit,
            "deterministic_score": det_score,
            "hybrid_score": hybrid_score,
            "fit_band": det.get("fit_band") if det else "weak_fit",
        })
    reranked.sort(
        key=lambda item: (
            -item["hybrid_score"],
            -item["deterministic_score"],
            -item["semantic_score"],
            item["title"].lower(),
        )
    )
    for idx, item in enumerate(reranked[:top_k], start=1):
        item["rank"] = idx
    return reranked[:top_k]


def _resolve_model_specs(values: list[str] | None) -> list[ModelSpec]:
    if not values:
        return [spec for spec in MODEL_CATALOG.values() if spec.default_enabled]
    specs: list[ModelSpec] = []
    for value in values:
        key = str(value or "").strip().lower()
        if key in MODEL_CATALOG:
            specs.append(MODEL_CATALOG[key])
            continue
        raise KeyError(f"Unknown model '{value}'. Available: {', '.join(sorted(MODEL_CATALOG))}")
    return specs


def _render_summary(
    *,
    resume_path: Path,
    corpus_meta: dict[str, Any],
    prefilter_meta: dict[str, Any] | None,
    probes: list[QueryProbe],
    results: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Semantic Resume Search: {resume_path.stem}",
        "",
        f"- corpus_jobs: `{corpus_meta['jobs_loaded']}`",
        f"- corpus_source: `{corpus_meta.get('source', 'cache')}`",
        f"- cache_files_scanned: `{corpus_meta.get('files_scanned', 0)}`",
        f"- lookback_hours: `{corpus_meta['lookback_hours']}`",
        f"- probes: `{len(probes)}`",
        "",
        "## Corpus Filter",
    ]
    if prefilter_meta:
        lines.extend([
            f"- input_jobs: `{prefilter_meta['input_jobs']}`",
            f"- matched_jobs: `{prefilter_meta['matched_jobs']}`",
            f"- selected_jobs: `{prefilter_meta['selected_jobs']}`",
            f"- role_filters: `{prefilter_meta['role_filters']}`",
            f"- skill_filters: `{prefilter_meta['skill_filters']}`",
            "",
        "## Query Probes",
        ])
    else:
        lines.append("## Query Probes")
    if corpus_meta.get("corpus_db"):
        lines.insert(4, f"- corpus_db: `{corpus_meta['corpus_db']}`")
    if corpus_meta.get("cache_dir"):
        lines.insert(4, f"- cache_dir: `{corpus_meta['cache_dir']}`")
    for probe in probes:
        lines.append(f"- `{probe.name}`: {probe.text}")
    lines.append("")
    for item in results:
        lines.append(f"## {item['model']}")
        lines.append(f"- repo_id: `{item['repo_id']}`")
        lines.append(f"- embedding_dim: `{item['embedding_dim']}`")
        lines.append(f"- index_cache_hit: `{item['index_cache_hit']}`")
        lines.append("- semantic_top:")
        for hit in item["semantic_top"]:
            lines.append(
                f"  - {hit['rank']}. {hit['title']} | {hit['company']} | sim={hit['semantic_score']:.4f} | probe={hit['best_probe']}"
            )
        lines.append("- hybrid_top:")
        for hit in item["hybrid_top"]:
            lines.append(
                f"  - {hit['rank']}. {hit['title']} | {hit['company']} | hybrid={hit['hybrid_score']:.2f} | det={hit['deterministic_score']:.2f} | {hit['fit_band']}"
            )
        lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone semantic search over cached scraped jobs")
    parser.add_argument("--resume", required=True)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--corpus-db", default=str(DEFAULT_CORPUS_DB))
    parser.add_argument("--use-corpus-db", action="store_true")
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--candidate-pool", type=int, default=DEFAULT_CANDIDATE_POOL)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument("--max-description-chars", type=int, default=DEFAULT_MAX_DESCRIPTION_CHARS)
    parser.add_argument("--prefilter-max-jobs", type=int, default=DEFAULT_PREFILTER_MAX_JOBS)
    parser.add_argument("--probe", action="append", default=[])
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--refresh-index", action="store_true")
    parser.add_argument("--allow-remote-model-download", action="store_true")
    parser.add_argument("--label")
    parser.add_argument("--output-dir")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    resume_path = Path(args.resume).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    corpus_db = Path(args.corpus_db).expanduser().resolve()
    index_dir = Path(args.index_dir).expanduser().resolve()
    if not resume_path.exists():
        raise FileNotFoundError(resume_path)
    if not args.use_corpus_db and not cache_dir.exists():
        raise FileNotFoundError(cache_dir)

    resume_text = _load_resume_text(resume_path)
    probes, profile = _build_query_probes(resume_text, resume_path, list(args.probe or []))
    if args.use_corpus_db:
        jobs, corpus_meta = _collect_jobs_from_corpus_db(corpus_db, lookback_hours=args.lookback_hours)
    else:
        jobs, corpus_meta = _collect_jobs_from_scrape_cache(cache_dir, lookback_hours=args.lookback_hours)
    if not jobs:
        raise RuntimeError("No cached jobs found for semantic search")
    filtered_jobs, prefilter_meta = _prefilter_jobs_for_profile(
        jobs,
        profile,
        max_jobs=int(args.prefilter_max_jobs),
    )

    results: list[dict[str, Any]] = []
    for spec in _resolve_model_specs(args.models):
        vectors, index_meta = _load_or_build_job_embeddings(
            filtered_jobs,
            spec,
            index_dir=index_dir,
            refresh=bool(args.refresh_index),
            allow_remote_download=bool(args.allow_remote_model_download),
            cpu_threads=int(args.cpu_threads),
            batch_size=int(args.batch_size),
            max_description_chars=int(args.max_description_chars),
        )
        embedder = OnnxEmbedder(
            spec,
            allow_remote_download=bool(args.allow_remote_model_download),
            cpu_threads=int(args.cpu_threads),
            batch_size=int(args.batch_size),
        )
        query_vectors = embedder.encode([probe.text for probe in probes], is_query=True)
        semantic_top = _semantic_rank(filtered_jobs, vectors, query_vectors, probes, top_k=max(args.top_k, args.candidate_pool))
        job_map = {job.job_url: job for job in filtered_jobs}
        semantic_for_rerank: list[dict[str, Any]] = []
        for hit in semantic_top:
            job = job_map[hit["job_url"]]
            semantic_for_rerank.append({**hit, "description": job.description})
        deterministic_hits = _deterministic_retrieve(filtered_jobs, profile, top_k=max(args.top_k, args.candidate_pool))
        union_hits = semantic_for_rerank + [
            {
                **hit,
                "semantic_score": float((hit["deterministic_score"] / 100.0) * 2.0 - 1.0),
                "best_probe": "deterministic_filter",
                "best_probe_text": "deterministic candidate retrieval",
                "source_terms": [],
            }
            for hit in deterministic_hits
        ]
        hybrid_top = _hybrid_rerank(
            union_hits,
            profile,
            candidate_pool=args.candidate_pool,
            top_k=args.top_k,
        )
        results.append({
            "model": spec.name,
            "repo_id": spec.repo_id,
            "embedding_dim": int(vectors.shape[1]) if vectors.size else 0,
            "index_cache_hit": bool(index_meta.get("cache_hit")),
            "prefiltered_jobs": len(filtered_jobs),
            "deterministic_top": deterministic_hits[: args.top_k],
            "semantic_top": semantic_for_rerank[: args.top_k],
            "hybrid_top": hybrid_top,
        })

    out_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path(__file__).resolve().parents[1]
        / "tmp"
        / "semantic_job_search"
        / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_slugify(args.label or resume_path.stem)}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "resume": str(resume_path),
        "corpus": corpus_meta,
        "prefilter": prefilter_meta,
        "probes": [asdict(probe) for probe in probes],
        "results": results,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "summary.md").write_text(_render_summary(resume_path=resume_path, corpus_meta=corpus_meta, prefilter_meta=prefilter_meta, probes=probes, results=results))
    print(json.dumps({"output_dir": str(out_dir), "jobs": corpus_meta["jobs_loaded"], "models": [item["model"] for item in results]}, indent=2))


if __name__ == "__main__":
    main()
