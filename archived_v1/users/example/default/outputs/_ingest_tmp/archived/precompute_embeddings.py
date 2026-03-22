# precompute_embeddings.py

import hashlib
import os
from pathlib import Path

import pandas as pd
from embeddings.embedding_cache import EmbeddingCache
from logger import setup_logger
from match_engine import EMBED_DIM, MODEL_NAME
from sentence_transformers import SentenceTransformer

BATCH_SIZE = 128  # safe and efficient on macOS


def text_hash(t: str) -> str:
    return hashlib.md5(t.encode("utf-8")).hexdigest()


def main():
    logger = setup_logger()

    # ---- Load FAISS cache ----
    cache = EmbeddingCache(dim=EMBED_DIM, logger=logger)

    # ---- Load model (CPU ONLY) ----
    logger.info("Loading embedding model (CPU, synchronous)")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    # ---- Load cached job CSVs ----
    cache_dir = Path("cache")
    csvs = list(cache_dir.glob("query_*.csv"))

    if not csvs:
        logger.warning("No cached job CSVs found")
        return

    # ---- Collect and deduplicate texts ----
    text_map = {}
    for csv in csvs:
        df = pd.read_csv(csv)
        for t in df["description"].fillna("").str.slice(0, 2000).tolist():
            h = text_hash(t)
            if h not in text_map:
                text_map[h] = t

    unique_texts = list(text_map.values())
    logger.info(f"Unique job texts: {len(unique_texts)}")

    # ---- Lookup once ----
    found, missing = cache.lookup(unique_texts)

    if not missing:
        logger.info("All embeddings already cached")
        return

    logger.info(f"Embedding {len(missing)} new texts")

    # ---- Batch embed + add ----
    for i in range(0, len(missing), BATCH_SIZE):
        idx = missing[i : i + BATCH_SIZE]
        batch_texts = [unique_texts[j] for j in idx]

        vecs = model.encode(
            batch_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype("float32")

        cache.add(batch_texts, vecs)

        logger.info(f"Embedded {min(i + BATCH_SIZE, len(missing))} / {len(missing)}")

    logger.info("Precompute complete")


if __name__ == "__main__":
    main()
