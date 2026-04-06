from __future__ import annotations

from pathlib import Path


def repo_resumes_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "resumes"
        if candidate.is_dir():
            return candidate
        if parent.name == ".worktrees":
            root_candidate = parent.parent / "resumes"
            if root_candidate.is_dir():
                return root_candidate
    raise FileNotFoundError("Could not locate resumes directory from test workspace")
