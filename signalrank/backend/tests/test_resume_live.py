"""Live OpenRouter smoke tests for the resume vision pipeline.

Opt in with:
    OPENROUTER_API_KEY=... uv run pytest -m live tests/test_resume_live.py -s
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from api.routes.onboarding import _extract_text_from_pdf, _render_pdf_pages_as_images
from domain.resume_editor import editor_to_tailored_content, merge_resume_editor, parse_resume_editor
from llm.openrouter import OpenRouterClient
from llm.resume_parser import parse_resume_from_images
from llm.resume_tailor import check_page_count, render_and_compile_content, validate_resume_artifacts


RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"
SAMPLE_PDFS = sorted(RESUMES_DIR.glob("*.pdf"))
LIVE_VISION_MODELS = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-3-4b-it:free",
    "google/gemma-3-12b-it:free",
]


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _selected_sample_pdfs() -> list[Path]:
    if not SAMPLE_PDFS:
        pytest.skip("No sample PDFs found")
    raw_idx = os.getenv("LIVE_RESUME_SAMPLE_INDEX", "").strip()
    if not raw_idx:
        return SAMPLE_PDFS
    try:
        idx = int(raw_idx)
    except ValueError:
        return SAMPLE_PDFS
    idx = max(0, min(idx, len(SAMPLE_PDFS) - 1))
    return [SAMPLE_PDFS[idx]]


def _load_sample_spec(pdf_path: Path) -> dict:
    return json.loads(pdf_path.with_suffix(".json").read_text())


def _experience_matches(candidate: dict, marker: dict) -> bool:
    title = (candidate.get("title") or "").lower()
    company = (candidate.get("company") or "").lower()
    return marker["title"].lower() in title and marker["company"].lower() in company


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sample_idx", "pdf_path"),
    list(enumerate(_selected_sample_pdfs())),
    ids=[f"sample_{idx + 1}" for idx, _ in enumerate(_selected_sample_pdfs())],
)
async def test_live_resume_image_parse_roundtrip_smoke(sample_idx: int, pdf_path: Path):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")

    pdf_bytes = pdf_path.read_bytes()
    extracted_text = _extract_text_from_pdf(pdf_bytes)
    spec = _load_sample_spec(pdf_path)
    assert spec["email"], "Sample fixture is missing expected email"

    page_images = _render_pdf_pages_as_images(pdf_bytes, dpi=60)
    assert page_images, "PDF did not render to images"

    client = OpenRouterClient(api_key=api_key)
    try:
        live_editor = await asyncio.wait_for(
            parse_resume_from_images(
                page_images,
                client,
                reference_text=extracted_text,
                vision_models=LIVE_VISION_MODELS,
                max_tokens=1800,
                request_timeout=45.0,
                max_retries=1,
            ),
            timeout=240,
        )
    finally:
        await client.close()

    assert live_editor, "Live vision parser returned empty payload"

    merged = merge_resume_editor(live_editor, parse_resume_editor(extracted_text))
    assert merged["name"] == spec["name"]
    assert merged["email"] == spec["email"]
    if spec["phone"]:
        assert _digits_only(merged["phone"]) == _digits_only(spec["phone"])
    assert len(merged["experiences"]) >= spec["minimums"]["experiences"]
    assert len(merged["skills"]) >= spec["minimums"]["skill_groups"]
    for marker in spec["experience_markers"]:
        assert any(_experience_matches(exp, marker) for exp in merged["experiences"]), marker
    content = editor_to_tailored_content(merged)
    typst_src, rendered_pdf = render_and_compile_content(content)
    validation = validate_resume_artifacts(content, typst_src, rendered_pdf)

    assert check_page_count(rendered_pdf) == 1
    assert validation.page_count == 1
    assert validation.missing_links == []
