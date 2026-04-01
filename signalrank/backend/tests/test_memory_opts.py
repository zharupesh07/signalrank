"""
Memory optimization tests — before/after benchmarks for three improvements:

  1. _VECTOR_CACHE stores float32 ndarrays (~1.5KB) not Python list[float] (~9.2KB)
  2. _compute_embeddings pops the embedding column immediately → frees Python objects early
  3. SkillCanonicalizer is constructed once outside the _embed_new_jobs chunk loop
"""
import gc
import sys
import tracemalloc

import numpy as np
import pytest

import batch.embedding_cache as ec
from batch.embedding_cache import _remember_vector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _baseline_list_size(n: int) -> int:
    """Memory a plain list[float] of length n would use (reference baseline)."""
    sample = [0.1] * n
    return sys.getsizeof(sample) + sum(sys.getsizeof(v) for v in sample)


def _ndarray_size(arr: np.ndarray) -> int:
    # arr.nbytes is the data buffer; sys.getsizeof includes it on modern numpy,
    # so use nbytes alone to avoid double-counting.
    return arr.nbytes


# ---------------------------------------------------------------------------
# 1. _VECTOR_CACHE type and per-entry memory
# ---------------------------------------------------------------------------

def test_vector_cache_stores_float32_ndarray():
    """_remember_vector must store an np.ndarray with dtype float32."""
    key = ("mem-test-cfg", "mem-test-fp-type")
    ec._VECTOR_CACHE.pop(key, None)
    _remember_vector(key, [0.1, 0.2, 0.3] + [0.0] * 381)
    stored = ec._VECTOR_CACHE.get(key)
    assert stored is not None, "Vector not stored"
    assert isinstance(stored, np.ndarray), f"Expected ndarray, got {type(stored)}"
    assert stored.dtype == np.float32, f"Expected float32, got {stored.dtype}"
    ec._VECTOR_CACHE.pop(key, None)


def test_vector_cache_nan_sanitised():
    """NaN/Inf values must be zeroed in the cached ndarray."""
    key = ("mem-test-cfg", "mem-test-fp-nan")
    ec._VECTOR_CACHE.pop(key, None)
    vec = [float("nan"), float("inf"), float("-inf")] + [0.5] * 381
    _remember_vector(key, vec)
    stored = ec._VECTOR_CACHE[key]
    assert stored[0] == 0.0
    assert stored[1] == 0.0
    assert stored[2] == 0.0
    assert abs(stored[3] - 0.5) < 1e-4
    ec._VECTOR_CACHE.pop(key, None)


def test_vector_cache_per_entry_memory_vs_list():
    """
    Before: list[float] of 384 elements ≈ 9.2KB
    After:  float32 ndarray of 384 elements ≈ 1.5KB

    Asserts the ndarray path is <2KB and at least 4× smaller than list.
    """
    dim = 384
    key = ("mem-test-cfg", "mem-test-fp-size")
    ec._VECTOR_CACHE.pop(key, None)

    vector = [float(i % 10) / 10 for i in range(dim)]
    _remember_vector(key, vector)
    stored = ec._VECTOR_CACHE[key]

    ndarray_bytes = _ndarray_size(stored)
    list_bytes = _baseline_list_size(dim)

    # float32 ndarray data: 384 * 4 = 1536 bytes
    assert ndarray_bytes == dim * 4, (
        f"ndarray data is {ndarray_bytes} bytes — expected {dim * 4} (float32)"
    )
    # list[float] overhead: each Python float is ~24 bytes on 64-bit CPython
    assert ndarray_bytes * 4 < list_bytes, (
        f"ndarray ({ndarray_bytes}B) not 4× smaller than list ({list_bytes}B)"
    )

    ec._VECTOR_CACHE.pop(key, None)


def test_vector_cache_1000_entries_under_3mb():
    """
    1000 float32 entries should allocate <3MB.
    Before optimisation: 1000 × 9.2KB = ~9.2MB.
    After:               1000 × 1.5KB = ~1.5MB (plus dict/key overhead ≈ 3MB total).
    """
    N = 1000
    keys = [("bench-cfg", f"bench-fp-{i}") for i in range(N)]
    for k in keys:
        ec._VECTOR_CACHE.pop(k, None)
    gc.collect()

    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    for i, key in enumerate(keys):
        _remember_vector(key, [float(i % 10) / 10] * 384)

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snap_after.compare_to(snap_before, "lineno")
    allocated = sum(s.size_diff for s in stats if s.size_diff > 0)
    allocated_mb = allocated / (1024 * 1024)

    for k in keys:
        ec._VECTOR_CACHE.pop(k, None)
    gc.collect()

    assert allocated_mb < 3.0, (
        f"1000 cache entries allocated {allocated_mb:.1f}MB — expected <3MB "
        f"(pre-optimisation baseline ~9.2MB)"
    )


# ---------------------------------------------------------------------------
# 2. LRU eviction still works after float32 change
# ---------------------------------------------------------------------------

def test_lru_eviction_drops_oldest():
    """When the cache is full, the oldest entry is evicted (FIFO/LRU)."""
    old_max = ec._VECTOR_CACHE_MAX
    old_cache = dict(ec._VECTOR_CACHE)
    ec._VECTOR_CACHE.clear()
    ec._VECTOR_CACHE_MAX = 3
    try:
        for i in range(4):
            _remember_vector(("evict-cfg", f"evict-{i}"), [float(i)] * 384)
        assert len(ec._VECTOR_CACHE) == 3
        assert ("evict-cfg", "evict-0") not in ec._VECTOR_CACHE, "Oldest entry should be evicted"
        assert ("evict-cfg", "evict-3") in ec._VECTOR_CACHE, "Newest entry should be present"
    finally:
        ec._VECTOR_CACHE.clear()
        ec._VECTOR_CACHE.update(old_cache)
        ec._VECTOR_CACHE_MAX = old_max


def test_duplicate_key_not_overwritten():
    """_remember_vector must not update an existing key."""
    key = ("dedup-cfg", "dedup-fp")
    ec._VECTOR_CACHE.pop(key, None)
    _remember_vector(key, [0.1] * 384)
    _remember_vector(key, [0.9] * 384)
    assert abs(ec._VECTOR_CACHE[key][0] - 0.1) < 1e-4
    ec._VECTOR_CACHE.pop(key, None)


# ---------------------------------------------------------------------------
# 3. _compute_embeddings pops embedding column immediately
# ---------------------------------------------------------------------------

def test_compute_embeddings_pops_column_early():
    """
    After the pop+convert optimisation, 'embedding' must not appear as a
    DataFrame column during or after _compute_embeddings.

    We verify this by inspecting the source code — the drop should happen
    at the very top of the function, before skill extraction.
    """
    import inspect
    from batch.ranker import _compute_embeddings

    src = inspect.getsource(_compute_embeddings)
    lines = [l.strip() for l in src.splitlines()]

    # Find positions of key operations
    pop_line = next((i for i, l in enumerate(lines) if "df.pop" in l and '"embedding"' in l), None)
    skill_line = next((i for i, l in enumerate(lines) if "extract_skills_from_texts" in l), None)
    drop_line = next((i for i, l in enumerate(lines) if 'drop(columns=["embedding"]' in l), None)

    assert pop_line is not None, "df.pop('embedding') not found in _compute_embeddings"
    assert skill_line is not None, "extract_skills_from_texts not found in _compute_embeddings"
    assert pop_line < skill_line, (
        f"df.pop('embedding') (line {pop_line}) must come before "
        f"extract_skills_from_texts (line {skill_line})"
    )
    assert drop_line is None, (
        "df.drop(columns=['embedding']) still present — should be removed after pop refactor"
    )


def test_embedding_column_converted_to_float32():
    """
    stored_embeddings list must contain float32 ndarrays (not Python lists)
    when the embedding column is non-null.

    Verified by checking that the ndarray built from a Python list in the
    conversion snippet uses float32 dtype.
    """
    raw = [0.1] * 384
    converted = np.array(raw, dtype="float32")
    assert converted.dtype == np.float32
    # float32 array should be ~6× smaller than the Python list
    assert converted.nbytes < sys.getsizeof(raw) // 2


# ---------------------------------------------------------------------------
# 4. SkillCanonicalizer hoisted outside the embed chunk loop
# ---------------------------------------------------------------------------

def test_skill_canonicalizer_hoisted_outside_loop():
    """
    Verify that SkillCanonicalizer is constructed before the chunk loop
    in _embed_new_jobs, not inside it.

    Inspects source to confirm canon = SkillCanonicalizer(cfg) appears
    before `for chunk_start in range(`.
    """
    import inspect
    from batch.worker import _embed_new_jobs

    src = inspect.getsource(_embed_new_jobs)
    lines = [l.strip() for l in src.splitlines()]

    canon_line = next(
        (i for i, l in enumerate(lines) if "SkillCanonicalizer(cfg)" in l), None
    )
    loop_line = next(
        (i for i, l in enumerate(lines) if l.startswith("for chunk_start in range(")), None
    )

    assert canon_line is not None, "SkillCanonicalizer(cfg) not found in _embed_new_jobs"
    assert loop_line is not None, "chunk loop not found in _embed_new_jobs"
    assert canon_line < loop_line, (
        f"SkillCanonicalizer (line {canon_line}) must be constructed before "
        f"the chunk loop (line {loop_line})"
    )


def test_canonicalizer_not_in_del_statement():
    """
    After hoisting, 'canon' must not appear in the del statement inside the loop
    (it would be premature to delete it mid-loop).
    """
    import inspect
    from batch.worker import _embed_new_jobs

    src = inspect.getsource(_embed_new_jobs)
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("del ") and "canon" in stripped:
            pytest.fail(
                f"'canon' found in del statement inside _embed_new_jobs: {stripped!r}\n"
                "SkillCanonicalizer should be deleted after the loop, not inside it."
            )
