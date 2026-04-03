#!/usr/bin/env python3
"""PDF text find & replace CLI with interactive confirmation and font preservation."""

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import fitz  # pymupdf
except ImportError:
    print("pymupdf not installed. Run: pip install pymupdf")
    sys.exit(1)


class FontInfo(NamedTuple):
    name: str
    size: float
    color: int  # packed RGB int


class Match(NamedTuple):
    page_num: int
    rect: fitz.Rect
    font: FontInfo


def get_font_at_rect(page: fitz.Page, rect: fitz.Rect) -> FontInfo:
    blocks = page.get_text("dict", clip=rect.inflate(2))["blocks"]
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if fitz.Rect(span["bbox"]).intersects(rect):
                    return FontInfo(
                        name=span.get("font", "helv"),
                        size=round(span.get("size", 11), 1),
                        color=span.get("color", 0),
                    )
    return FontInfo(name="helv", size=11, color=0)


def color_to_rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16) & 0xFF) / 255, ((color >> 8) & 0xFF) / 255, (color & 0xFF) / 255


def collect_matches(doc: fitz.Document, search_text: str) -> list[Match]:
    matches = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        for rect in page.search_for(search_text):
            font = get_font_at_rect(page, rect)
            matches.append(Match(page_num, rect, font))
    return matches


def apply_replacements(doc: fitz.Document, confirmed: list[Match], new_text: str) -> None:
    # Group by page to apply redactions + inserts together per page
    by_page: dict[int, list[Match]] = {}
    for m in confirmed:
        by_page.setdefault(m.page_num, []).append(m)

    for page_num, page_matches in by_page.items():
        page = doc[page_num]
        # Add all redact annotations first
        for m in page_matches:
            page.add_redact_annot(m.rect, fill=(1, 1, 1))
        page.apply_redactions()
        # Insert replacement text for each
        for m in page_matches:
            point = fitz.Point(m.rect.x0, m.rect.y1 - 1)
            rgb = color_to_rgb(m.font.color)
            try:
                page.insert_text(point, new_text, fontname=m.font.name, fontsize=m.font.size, color=rgb)
            except Exception:
                page.insert_text(point, new_text, fontname="helv", fontsize=m.font.size, color=rgb)


def get_context(page: fitz.Page, rect: fitz.Rect, padding: float = 120) -> str:
    clip = fitz.Rect(rect.x0 - padding, rect.y0 - 4, rect.x1 + padding, rect.y1 + 4)
    return page.get_text(clip=clip).strip().replace("\n", " ")


def run_interactive(doc: fitz.Document, search_text: str, replace_text: str) -> list[Match]:
    matches = collect_matches(doc, search_text)
    if not matches:
        print(f'No matches found for "{search_text}"')
        return []

    total = len(matches)
    print(f'Found {total} match(es) for "{search_text}"\n')

    confirmed: list[Match] = []
    i = 0
    while i < len(matches):
        m = matches[i]
        page = doc[m.page_num]
        context = get_context(page, m.rect)

        print(f"[{i+1}/{total}] Page {m.page_num + 1}")
        print(f"  Context : ...{context}...")
        print(f"  Font    : {m.font.name}, {m.font.size}pt")
        print(f'  Replace "{search_text}" → "{replace_text}"?')
        print("  [y]es / [n]o / [a]ll remaining / [q]uit : ", end="", flush=True)

        choice = input().strip().lower()
        print()

        if choice == "q":
            print("Aborted — no changes saved.")
            return []
        elif choice == "a":
            confirmed.extend(matches[i:])
            print(f"  Marked {len(matches) - i} remaining match(es) for replacement.")
            break
        elif choice == "y":
            confirmed.append(m)
            print(f"  Marked for replacement.")
        else:
            print(f"  Skipped.")

        i += 1

    return confirmed


def main():
    parser = argparse.ArgumentParser(
        description="Find and replace text in a PDF, preserving original font and size.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  pdf_replace.py resume.pdf "John Doe" "Jane Smith"
  pdf_replace.py doc.pdf "ACME Corp" "Globex Corp" -o updated.pdf
  pdf_replace.py doc.pdf "draft" "final" --all
        """,
    )
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("search", help="Exact text to search for")
    parser.add_argument("replace", help="Replacement text")
    parser.add_argument("-o", "--output", help="Output PDF path (default: <input>_edited.pdf)")
    parser.add_argument("--all", action="store_true", help="Replace all matches without confirmation")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_path.with_stem(input_path.stem + "_edited")

    doc = fitz.open(str(input_path))

    if args.all:
        matches = collect_matches(doc, args.search)
        if not matches:
            print(f'No matches found for "{args.search}"')
            doc.close()
            return
        confirmed = matches
        print(f"Found {len(confirmed)} match(es) — replacing all.")
    else:
        confirmed = run_interactive(doc, args.search, args.replace)

    if confirmed:
        apply_replacements(doc, confirmed, args.replace)
        doc.save(str(output_path))
        print(f"Replaced {len(confirmed)} match(es). Saved to: {output_path}")
    else:
        print("No changes saved.")

    doc.close()


if __name__ == "__main__":
    main()
