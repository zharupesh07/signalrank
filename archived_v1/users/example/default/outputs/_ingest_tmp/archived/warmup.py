# embeddings/warmup.py
import threading
from typing import List

import numpy as np
from embeddings.async_embedder import AsyncEmbedder
from embeddings.embedding_cache import EmbeddingCache


def warmup_job_embeddings(
    job_texts: List[str],
    model_name: str,
    embed_dim: int,
    logger=None,
):
    """
    Fire-and-forget embedding warmup.
    Safe to call multiple times.
    """

    def _run():
        try:
            embedder = AsyncEmbedder(
                model_name,
                device="mps",
                logger=logger,
            )

            cache = EmbeddingCache(
                dim=embed_dim,
                logger=logger,
            )

            found, missing = cache.lookup(job_texts)
            if not missing:
                if logger:
                    logger.info("Embedding warmup: all vectors already cached")
                return

            texts = [job_texts[i] for i in missing]
            vecs = embedder.embed(texts)
            cache.add(texts, vecs)

            if logger:
                logger.info(f"Embedding warmup: cached {len(texts)} vectors")

        except Exception as e:
            if logger:
                logger.warning(f"Embedding warmup failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
