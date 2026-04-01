"""Post-LLM verification: cross-check parsed resume against PyMuPDF reference text.

The LLM provides *structure* (field classification).  The reference text provides
*content* (exact spelling, dates, names).  This module reconciles the two.
"""

import logging
import re

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(\(?\+?\d[\d\s().-]{7,}\d)")
_MONTH_YEAR_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})\b",
    re.I,
)
_MMYYYY_RE = re.compile(r"\b(\d{1,2})/(\d{4})\b")
_URLISH_RE = re.compile(r"\b(?:https?://)?(?:www\.)?[A-Z0-9.-]+\.[A-Z]{2,}(?:/[^\s|]+)?\b", re.I)
_SUMMARY_POSITION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z/&,\- ]{2,80}?)\s+with\b")


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "")).strip()


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", (text or "").lower()))


def _word_overlap(needle: str, haystack_words: set[str]) -> float:
    words = _word_set(needle)
    if not words:
        return 1.0
    return len(words & haystack_words) / len(words)


def _normalize_linkedin(value: str) -> str:
    cleaned = _clean_line(value).removeprefix("https://").removeprefix("http://").strip("/")
    lower = cleaned.lower()
    for prefix in ("www.linkedin.com/", "linkedin.com/"):
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            lower = cleaned.lower()
    if lower.startswith("in/"):
        cleaned = cleaned[3:]
    return cleaned.strip("/")


def _normalize_github(value: str) -> str:
    cleaned = _clean_line(value).removeprefix("https://").removeprefix("http://").strip("/")
    lower = cleaned.lower()
    for prefix in ("www.github.com/", "github.com/"):
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    return cleaned.strip("/")


def _normalize_website(value: str) -> str:
    cleaned = _clean_line(value).removeprefix("https://").removeprefix("http://").strip("/")
    return cleaned.removeprefix("www.")


def _extract_reference_profiles(ref: str) -> dict[str, str]:
    lines = [_clean_line(line) for line in (ref or "").splitlines()[:20] if _clean_line(line)]
    linkedin = ""
    github = ""
    website = ""
    for line in lines:
        lower = line.lower()
        if not linkedin:
            if "linkedin.com/" in lower:
                linkedin = _normalize_linkedin(line)
            else:
                match = re.search(r"linkedin\s*:\s*([A-Za-z0-9][A-Za-z0-9-]*)", line, re.I)
                if match:
                    linkedin = _normalize_linkedin(match.group(1))
        if not github:
            if "github.com/" in lower:
                github = _normalize_github(line)
            else:
                match = re.search(r"github\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]*)", line, re.I)
                if match:
                    github = _normalize_github(match.group(1))
        if not website:
            for match in _URLISH_RE.finditer(line):
                candidate = match.group(0)
                lower_candidate = candidate.lower()
                if "linkedin.com" in lower_candidate or "github.com" in lower_candidate or "@" in candidate:
                    continue
                website = _normalize_website(candidate)
                break
    return {
        "linkedin": linkedin,
        "github": github,
        "website": website,
    }


def _extract_reference_location(ref: str) -> str:
    lines = [_clean_line(line) for line in (ref or "").splitlines()[:15] if _clean_line(line)]
    for line in lines:
        lower = line.lower()
        if any(token in lower for token in ("summary", "work experience", "experience", "education", "skills", "certif")):
            break
        if "@" in line or _PHONE_RE.search(line):
            continue
        if "linkedin" in lower or "github" in lower or ".io" in lower or lower.startswith("www."):
            continue
        if line == "|" or line.startswith("Last Updated"):
            continue
        if "," in line or "·" in line:
            return line
    return ""


def _extract_summary_position(ref: str) -> str:
    lines = [_clean_line(line) for line in (ref or "").splitlines() if _clean_line(line)]
    for idx, line in enumerate(lines):
        if line.lower() == "summary" and idx + 1 < len(lines):
            summary_line = lines[idx + 1]
            match = _SUMMARY_POSITION_RE.match(summary_line)
            if match:
                return _clean_line(match.group(1))
            break
    return ""


def _extract_header_position(ref: str) -> str:
    """Extract the professional headline from the resume header (lines 2-6 after the name)."""
    lines = [_clean_line(line) for line in (ref or "").splitlines() if _clean_line(line)]
    _TITLE_KEYWORDS_RE = re.compile(
        r"\b(engineer|analyst|developer|manager|consultant|specialist|associate|"
        r"architect|lead|head|director|officer|scientist|researcher|designer|"
        r"certified|platform|cloud|senior|junior|principal|staff)\b",
        re.I,
    )
    for line in lines[1:6]:
        lower = line.lower()
        # Skip contact info and noise
        if "@" in line or _PHONE_RE.search(line):
            continue
        if any(x in lower for x in ("linkedin", "github", ".io", "www.", "summary", "experience")):
            continue
        if line in ("|", "·") or len(line) < 8:
            continue
        # Accept if it looks like a professional title
        if _TITLE_KEYWORDS_RE.search(line) or line.isupper() or "|" in line:
            return line
    return ""


# ---------------------------------------------------------------------------
# Contact verification
# ---------------------------------------------------------------------------

def _verify_contact(editor: dict, ref: str) -> dict:
    ref_emails = _EMAIL_RE.findall(ref)
    if ref_emails:
        llm_email = (editor.get("email") or "").strip().lower()
        ref_email_lower = [e.lower() for e in ref_emails]
        if llm_email and llm_email not in ref_email_lower:
            logger.warning("Verifier: overriding email %r -> %r", llm_email, ref_emails[0])
            editor["email"] = ref_emails[0]
        elif not llm_email:
            editor["email"] = ref_emails[0]

    ref_phones = _PHONE_RE.findall(ref)
    if ref_phones:
        llm_digits = _digits_only(editor.get("phone", ""))
        ref_digits = [_digits_only(p) for p in ref_phones]
        if llm_digits and llm_digits not in ref_digits:
            logger.warning("Verifier: overriding phone %r -> %r", editor.get("phone"), ref_phones[0])
            editor["phone"] = ref_phones[0].strip()
        elif not llm_digits:
            editor["phone"] = ref_phones[0].strip()

    llm_name = (editor.get("name") or "").strip()
    if llm_name:
        header = ref[:500]
        header_lower = header.lower()
        # Fix mashed names: "ExampleCandidate" -> "Example Candidate"
        if " " not in llm_name and llm_name.lower() in header_lower.replace(" ", ""):
            for line in header.splitlines()[:5]:
                line = line.strip()
                if line and line.lower().replace(" ", "") == llm_name.lower().replace(" ", ""):
                    logger.info("Verifier: fixing mashed name %r -> %r", llm_name, line)
                    editor["name"] = line
                    break
        elif llm_name.lower() not in header_lower:
            name_words = llm_name.lower().split()
            if not all(w in header_lower for w in name_words):
                logger.warning("Verifier: name %r not found in reference header", llm_name)

    ref_profiles = _extract_reference_profiles(ref)
    if ref_profiles["linkedin"] and not _normalize_linkedin(editor.get("linkedin", "")):
        editor["linkedin"] = ref_profiles["linkedin"]
    if ref_profiles["github"] and not _normalize_github(editor.get("github", "")):
        editor["github"] = ref_profiles["github"]
    if ref_profiles["website"] and not _normalize_website(editor.get("website", "")):
        editor["website"] = ref_profiles["website"]

    ref_location = _extract_reference_location(ref)
    current_location = _clean_line(editor.get("location", ""))
    if ref_location and (
        not current_location
        or current_location == "|"
        or current_location.startswith("Last Updated")
        or current_location.startswith("SAP Cert")
    ):
        editor["location"] = ref_location

    ref_position = _extract_summary_position(ref)
    header_position = _extract_header_position(ref)
    llm_position = _clean_line(editor.get("position", ""))

    if not llm_position:
        editor["position"] = header_position or ref_position
    elif header_position and header_position.lower() not in (ref or "").lower()[:200].lower():
        # ref header has a headline the LLM missed — prefer it if LLM position isn't in the header
        pass  # keep LLM position; it may have read it from the image
    elif header_position and llm_position.lower() not in (ref or "")[:500].lower():
        # LLM position doesn't appear in reference header — override with reference headline
        logger.info("Verifier: overriding position %r -> %r", llm_position, header_position)
        editor["position"] = header_position

    return editor


# ---------------------------------------------------------------------------
# Certification verification
# ---------------------------------------------------------------------------

def _verify_certifications(certs: list[str], ref: str) -> list[str]:
    if not certs:
        return certs
    ref_lower = ref.lower()
    ref_words = _word_set(ref)
    verified = []
    for cert in certs:
        cert_clean = cert.strip()
        if not cert_clean:
            continue
        if cert_clean.lower() in ref_lower:
            verified.append(cert_clean)
            continue
        if _word_overlap(cert_clean, ref_words) >= 0.6:
            verified.append(cert_clean)
            continue
        logger.warning("Verifier: removing hallucinated certification %r", cert_clean)
    return verified


# ---------------------------------------------------------------------------
# Date correction
# ---------------------------------------------------------------------------

def _extract_ref_dates(ref: str) -> set[str]:
    """Extract all (Month Year) and (MM/YYYY) pairs from reference text, normalized."""
    dates: set[str] = set()
    for m in _MONTH_YEAR_RE.finditer(ref):
        month = m.group(1)[:3].capitalize()
        year = m.group(2)
        dates.add(f"{month} {year}")
    for m in _MMYYYY_RE.finditer(ref):
        mm, yyyy = m.group(1), m.group(2)
        dates.add(f"{int(mm):02d}/{yyyy}")
    years = set(re.findall(r"\b((?:19|20)\d{2})\b", ref))
    return dates | years


def _correct_date_string(date_str: str, ref_dates: set[str], ref_text: str) -> str:
    if not date_str or not ref_dates:
        return date_str
    month_years = _MONTH_YEAR_RE.findall(date_str)
    result = date_str
    for month_str, year_str in month_years:
        month_abbr = month_str[:3].capitalize()
        token = f"{month_abbr} {year_str}"
        if token in ref_dates:
            continue
        if f"{month_str} {year_str}" in ref_text or f"{month_str[:3]} {year_str}" in ref_text:
            continue
        for ref_date in ref_dates:
            parts = ref_date.split()
            if len(parts) == 2 and parts[0] == month_abbr and parts[1] != year_str:
                old_fragment = f"{month_str} {year_str}"
                new_fragment = f"{month_str} {parts[1]}"
                if old_fragment in result:
                    logger.warning("Verifier: correcting date %r -> %r", old_fragment, new_fragment)
                    result = result.replace(old_fragment, new_fragment, 1)
                break
    return result


# ---------------------------------------------------------------------------
# Mashed-word repair
# ---------------------------------------------------------------------------

# Common resume/tech words that may not appear individually in sparse reference texts.
# Used as a base layer so the mashed-word splitter can always decompose standard phrases.
_BASE_VOCAB: frozenset[str] = frozenset("""
led and contributed to the development of iot based sensor home automation projects
driving innovation integration emerging technologies robotics conversational blockchain
designed implemented developed built architected engineered created managed led directed
scaled delivered maintained enhanced improved streamlined established spearheaded
systems platform service services solution solutions team project product process
senior junior principal staff engineer manager analyst consultant lead head director
software hardware cloud data digital technology technologies network infrastructure
enterprise corporate global international strategic operational technical functional
experience research skills communication leadership collaboration problem solving
client customer stakeholder vendor partner academy university institute college school
bachelor master diploma degree certificate program course training certification
""".lower().split())


def _build_vocab(ref: str) -> set[str]:
    ref_words = set(re.findall(r"[a-zA-Z]{2,}", ref.lower()))
    # Also break any long mashed tokens from the ref itself using short words
    short_ref = {w for w in ref_words if len(w) <= 15}
    return ref_words | short_ref | _BASE_VOCAB


def _fix_mashed_token(token: str, vocab: set[str]) -> str | None:
    """Greedy left-to-right word-break using reference vocabulary + base vocab.

    Window is 40 chars to handle long mashed vocab items.
    Allows skipping up to 5 unmatched characters total to handle OCR misreads.
    """
    lower = token.lower()
    words: list[str] = []
    pos = 0
    skipped = 0
    max_skip = 5
    while pos < len(lower):
        best_len = 0
        for end in range(min(pos + 40, len(lower)), pos, -1):
            candidate = lower[pos:end]
            if candidate in vocab and len(candidate) >= 2:
                best_len = end - pos
                break
        if best_len == 0:
            if skipped < max_skip:
                pos += 1
                skipped += 1
                continue
            return None
        words.append(lower[pos : pos + best_len])
        pos += best_len
    if len(words) < 2:
        return None
    return " ".join(words)


def _fix_mashed_words(text: str, vocab: set[str]) -> str:
    tokens = text.split()
    fixed_tokens = []
    changed = False
    for token in tokens:
        clean = re.sub(r"[^a-zA-Z]", "", token)
        if len(clean) > 25 and clean.lower() not in vocab:
            result = _fix_mashed_token(clean, vocab)
            if result:
                punctuation_prefix = token[: len(token) - len(token.lstrip("•·-–— "))]
                fixed_tokens.append(punctuation_prefix + result)
                changed = True
                continue
        fixed_tokens.append(token)
    if changed:
        logger.info("Verifier: repaired mashed words in text")
    return " ".join(fixed_tokens)


# ---------------------------------------------------------------------------
# Experience verification
# ---------------------------------------------------------------------------

def _verify_experiences(experiences: list[dict], ref: str) -> list[dict]:
    if not experiences:
        return experiences
    ref_dates = _extract_ref_dates(ref)
    ref_words = _word_set(ref)
    vocab = _build_vocab(ref)
    verified = []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        exp = dict(exp)
        dates = exp.get("dates", "")
        if dates:
            exp["dates"] = _correct_date_string(dates, ref_dates, ref)

        company = exp.get("company", "")
        if company and _word_overlap(company, ref_words) < 0.8:
            logger.warning("Verifier: company %r has low overlap with reference text", company)

        bullets = exp.get("bullets", [])
        if bullets and vocab:
            fixed_bullets = []
            for bullet in bullets:
                if not isinstance(bullet, str):
                    fixed_bullets.append(bullet)
                    continue
                fixed = _fix_mashed_words(bullet, vocab)
                if _word_overlap(fixed, ref_words) < 0.4 and len(fixed) > 20:
                    logger.warning("Verifier: low-overlap bullet (%.0f%%): %.60s...",
                                   _word_overlap(fixed, ref_words) * 100, fixed)
                fixed_bullets.append(fixed)
            exp["bullets"] = fixed_bullets

        verified.append(exp)
    return verified


# ---------------------------------------------------------------------------
# Skills verification
# ---------------------------------------------------------------------------

def _verify_skills(skills: list[dict], ref: str) -> list[dict]:
    """Remove garbled skill groups; strip sentence-like items from any group."""
    if not skills:
        return skills
    verified = []
    for group in skills:
        if not isinstance(group, dict):
            continue
        items = group.get("items", [])
        if not items:
            continue
        single_char_count = sum(1 for i in items if len(str(i).strip()) <= 1)
        if single_char_count > len(items) * 0.5:
            logger.warning("Verifier: dropping garbled skill group %r (%d/%d single-char items)",
                           group.get("category"), single_char_count, len(items))
            continue
        # Drop items that look like sentences rather than skill names
        def _is_skill_name(item: str) -> bool:
            s = str(item).strip()
            if len(s) > 60:
                return False
            if ". " in s or s.endswith("."):
                return False
            words = s.split()
            if len(words) > 6:
                return False
            # Gerund openers: "Working as ...", "Managing ...", "Configured ..."
            if words and re.match(r"[A-Z][a-z]+ing$|[A-Z][a-z]+ed$", words[0]):
                return False
            return True

        clean_items = [i for i in items if _is_skill_name(i)]
        if not clean_items:
            logger.warning("Verifier: dropping skill group %r — all items are sentences",
                           group.get("category"))
            continue
        if len(clean_items) < len(items):
            logger.info("Verifier: removed %d sentence-like items from skill group %r",
                        len(items) - len(clean_items), group.get("category"))
        verified.append({**group, "items": clean_items})
    return verified


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_against_reference(editor: dict, reference_text: str) -> dict:
    """Cross-check LLM-parsed editor dict against PyMuPDF reference text.

    Returns a corrected copy.  Pure Python, no LLM calls.
    """
    if not editor or not (reference_text or "").strip():
        return editor or {}
    result = dict(editor)
    result = _verify_contact(result, reference_text)
    result["certifications"] = _verify_certifications(
        result.get("certifications", []), reference_text
    )
    result["experiences"] = _verify_experiences(
        result.get("experiences", []), reference_text
    )
    result["skills"] = _verify_skills(
        result.get("skills", []), reference_text
    )
    return result
