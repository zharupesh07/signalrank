# domain/embeddings_math.py
import numpy as np


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    Deterministic cosine similarity.
    UI-safe. No ML frameworks.
    """
    q = query / np.linalg.norm(query)
    m = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.dot(m, q)
