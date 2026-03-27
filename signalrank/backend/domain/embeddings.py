# domain/embeddings.py
from __future__ import annotations

import hashlib
import logging
from typing import Dict, Iterable, List

import numpy as np

logger = logging.getLogger(__name__)
_ENGINE = None


def fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingEngine:
    def __init__(self, cfg):
        if hasattr(self, "model"):
            return
        # 🚫 Hard guard: never allow this in Streamlit
        if "streamlit" in __import__("sys").modules:
            raise RuntimeError("EmbeddingEngine must not be used inside Streamlit UI")

        from sentence_transformers import SentenceTransformer

        emb_cfg = cfg["embeddings"]

        self.model_name = emb_cfg["model_name"]
        self.device = emb_cfg.get("device", "cpu")
        self.normalize = emb_cfg["text"].get("normalize_embeddings", True)

        logger.info(
            "[EMBED] Loading model=%s device=%s normalize=%s",
            self.model_name,
            self.device,
            self.normalize,
        )

        self.model = SentenceTransformer(
            self.model_name,
            device=self.device,
        )

        logger.info("[EMBED] Model loaded successfully")

    def __new__(cls, cfg):
        global _ENGINE
        if _ENGINE is not None:
            return _ENGINE
        self = super().__new__(cls)
        _ENGINE = self
        return self

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype="float32")

        logger.info("[EMBED] Encoding %d texts", len(texts))

        batch_size = 64 if self.device == "mps" else 256

        vecs = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
        )

        return np.asarray(vecs, dtype="float32")

    def unload(self):
        global _ENGINE
        del self.model
        _ENGINE = None
        import gc
        gc.collect()
        logger.info("[EMBED] Model unloaded, memory freed")


class EmbeddingCache:
    """
    DuckDB-backed embedding cache (read/write via Store).

    RULES:
    - keyed by (text_fp, cfg_fp, user, use_case)
    - deterministic lookup
    """

    def __init__(self, store, ctx):
        self.store = store
        self.ctx = ctx

    def fetch(self, text_fps: Iterable[str]) -> Dict[str, List[float]]:
        if not text_fps:
            return {}

        rows = self.store.con.execute(
            """
            SELECT text_fp, vector
            FROM embeddings
            WHERE
              text_fp IN ?
              AND cfg_fp = ?
              AND user = ?
              AND use_case = ?
            """,
            [
                list(text_fps),
                self.ctx.config_fp,
                self.ctx.user,
                self.ctx.use_case,
            ],
        ).fetchall()

        return {k: v for k, v in rows}

    def store_vectors(self, rows: List[tuple[str, List[float]]]):
        if not rows:
            return

        import pandas as pd

        df = pd.DataFrame(
            rows,
            columns=["text_fp", "vector"],
        )
        df["cfg_fp"] = self.ctx.config_fp
        df["user"] = self.ctx.user
        df["use_case"] = self.ctx.use_case

        self.store.con.execute("""
            INSERT INTO embeddings
            SELECT
              text_fp,
              cfg_fp,
              vector,
              user,
              use_case
            FROM df
            ON CONFLICT (text_fp, cfg_fp, user, use_case)
            DO NOTHING
            """)


def build_job_embedding_text(
    *,
    title: str,
    description: str,
    canonical_skills: list[str],
    cfg: dict,
) -> str:
    max_chars = cfg["embeddings"]["text"].get("max_chars", 2000)

    title = (title or "").strip()
    desc = " ".join((description or "").split())[:max_chars]
    skills = ", ".join(sorted(canonical_skills)) if canonical_skills else ""

    return f"ROLE: {title}\n" f"RESPONSIBILITIES: {desc}\n" f"REQUIRED_SKILLS: {skills}"


def build_resume_embedding_text(*, resume_text, distilled, cfg, use_case):
    parts = []

    if distilled:
        parts.append(distilled)
    else:
        parts.append(resume_text)

    prefix = cfg.get("resume", {}).get("embedding_prefix")
    if prefix:
        parts.insert(0, prefix)

    return "\n\n".join(parts)
