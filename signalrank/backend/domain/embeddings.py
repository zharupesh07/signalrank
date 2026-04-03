# domain/embeddings.py
from __future__ import annotations

import hashlib
import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)
_ENGINE = None
_MAX_SEQ_LEN = 256
_EMBED_BATCH_SIZE = 4


def fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingEngine:
    """ONNX-based embedding engine — no torch dependency."""

    def __init__(self, cfg):
        if hasattr(self, "_session"):
            return
        if "streamlit" in __import__("sys").modules:
            raise RuntimeError("EmbeddingEngine must not be used inside Streamlit UI")

        from huggingface_hub import hf_hub_download
        import onnxruntime as ort
        from tokenizers import Tokenizer

        emb_cfg = cfg["embeddings"]
        self.normalize = emb_cfg["text"].get("normalize_embeddings", True)
        model_repo = emb_cfg.get("model_name", "BAAI/bge-small-en-v1.5")
        self._model_repo = model_repo

        model_path = hf_hub_download(repo_id=model_repo, filename="onnx/model.onnx")
        tokenizer_path = hf_hub_download(repo_id=model_repo, filename="tokenizer.json")

        sess_opts = ort.SessionOptions()
        sess_opts.inter_op_num_threads = 1
        sess_opts.intra_op_num_threads = 1
        sess_opts.enable_mem_pattern = False       # reduces peak RSS
        sess_opts.enable_cpu_mem_arena = False     # don't pre-allocate arena
        self._session = ort.InferenceSession(
            model_path, sess_opts, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=_MAX_SEQ_LEN)
        self._tokenizer.enable_padding(length=_MAX_SEQ_LEN)

        self._batch_size = cfg.get("batch", {}).get("embed_batch_size", _EMBED_BATCH_SIZE)
        logger.info("[EMBED] ONNX model loaded from %s", model_repo)

    def __new__(cls, cfg):
        global _ENGINE
        emb_cfg = cfg.get("embeddings", {})
        model_repo = emb_cfg.get("model_name", "BAAI/bge-small-en-v1.5")
        if _ENGINE is not None and getattr(_ENGINE, "_model_repo", None) == model_repo:
            return _ENGINE
        self = super().__new__(cls)
        _ENGINE = self
        return self

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        token_embs = outputs[0]

        mask_exp = attention_mask[:, :, np.newaxis].astype(np.float32)
        sum_embs = np.sum(token_embs * mask_exp, axis=1)
        sum_mask = np.sum(mask_exp, axis=1).clip(min=1e-9)
        mean_pooled = sum_embs / sum_mask

        if self.normalize:
            norms = np.linalg.norm(mean_pooled, axis=1, keepdims=True).clip(min=1e-9)
            mean_pooled = mean_pooled / norms

        return mean_pooled

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype="float32")

        logger.info("[EMBED] Encoding %d texts via ONNX (%s)", len(texts), self._model_repo)
        first_end = min(self._batch_size, len(texts))
        first_batch = self._embed_batch(texts[:first_end]).astype("float32", copy=False)
        out = np.empty((len(texts), first_batch.shape[1]), dtype="float32")
        out[:first_end] = first_batch
        del first_batch

        for i in range(first_end, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_vecs = self._embed_batch(batch).astype("float32", copy=False)
            out[i : i + len(batch)] = batch_vecs
            del batch_vecs

        return out

    def embed_chunked(self, texts: List[str], on_progress=None) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype="float32")

        logger.info("[EMBED] Encoding %d texts via ONNX (%s)", len(texts), self._model_repo)
        total = len(texts)
        first_end = min(self._batch_size, total)
        first_batch = self._embed_batch(texts[:first_end]).astype("float32", copy=False)
        out = np.empty((total, first_batch.shape[1]), dtype="float32")
        out[:first_end] = first_batch
        del first_batch
        if on_progress:
            on_progress(first_end, total)

        for i in range(first_end, total, self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_vecs = self._embed_batch(batch).astype("float32", copy=False)
            out[i : i + len(batch)] = batch_vecs
            del batch_vecs
            done = min(i + len(batch), total)
            if on_progress:
                on_progress(done, total)

        return out

    def unload(self):
        global _ENGINE
        del self._session
        del self._tokenizer
        _ENGINE = None
        import gc
        gc.collect()
        logger.info("[EMBED] ONNX model unloaded, memory freed")


def unload_embedding_engine() -> None:
    global _ENGINE
    if _ENGINE is None:
        return
    try:
        _ENGINE.unload()
    except Exception:
        logger.warning("[EMBED] Failed to unload ONNX model cleanly", exc_info=True)
        _ENGINE = None



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

    return f"ROLE: {title}\nREQUIRED_SKILLS: {skills}\nRESPONSIBILITIES: {desc}"


def build_resume_embedding_text(*, resume_text, distilled, cfg, use_case):
    parts = []

    if distilled:
        parts.append(distilled)
    elif resume_text:
        parts.append(resume_text)
    else:
        parts.append("")

    prefix = cfg.get("resume", {}).get("embedding_prefix")
    if prefix:
        parts.insert(0, prefix)

    return "\n\n".join(parts)
