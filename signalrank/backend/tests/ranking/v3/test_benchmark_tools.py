from __future__ import annotations

import json
from pathlib import Path

from tools.benchmark_ranking.diff import diff_snapshots
from tools.benchmark_ranking.score_labeled import ndcg_at_k, precision_at_k


def test_diff_snapshots_marks_new_and_dropped_jobs():
    baseline = [
        {"id": "job_a", "title": "Backend Engineer", "score": 0.8},
        {"id": "job_b", "title": "QA Engineer", "score": 0.4},
    ]
    candidate = [
        {"id": "job_c", "title": "Platform Engineer", "score": 0.9},
        {"id": "job_a", "title": "Backend Engineer", "score": 0.85},
    ]

    report = diff_snapshots(baseline, candidate, "example")

    assert "## example" in report
    assert "| 1 | Platform Engineer | 0.900 | - | NEW |" in report
    assert "Dropped from baseline top-30" in report
    assert "QA Engineer" in report


def test_precision_and_ndcg_ignore_unlabeled_jobs():
    ranked = [
        {"id": "job_1", "title": "A"},
        {"id": "job_2", "title": "B"},
        {"id": "job_3", "title": "C"},
    ]
    labels = {"job_1": "good", "job_2": "adjacent"}

    assert precision_at_k(ranked, labels, 3) == 0.75
    assert 0.0 <= ndcg_at_k(ranked, labels, 3) <= 1.0


def test_precision_at_k_zero_when_no_labeled_jobs():
    ranked = [{"id": "job_1", "title": "A"}]

    assert precision_at_k(ranked, {}, 10) == 0.0
