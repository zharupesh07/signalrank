"""Post-LLM verification: cross-check parsed resume against PyMuPDF reference text.

The LLM provides *structure* (field classification).  The reference text provides
*content* (exact spelling, dates, names).  This module reconciles the two.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unicode normalisation (ligatures + inverted-caps)
# ---------------------------------------------------------------------------

# PDF ligature glyphs that PyMuPDF sometimes preserves verbatim
_LIGATURE_MAP: dict[str, str] = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# Proper casing for tech terms that title-case would mangle (e.g. MLOPS → Mlops)
_TECH_ACRONYMS: dict[str, str] = {
    "mlops": "MLOps",
    "llmops": "LLMOps",
    "devops": "DevOps",
    "devsecops": "DevSecOps",
    "genai": "GenAI",
    "cicd": "CI/CD",
    "iot": "IoT",
    "nosql": "NoSQL",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "github": "GitHub",
    "gitlab": "GitLab",
    "linkedin": "LinkedIn",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "openai": "OpenAI",
    "langchain": "LangChain",
}


def _normalize_ligatures(text: str) -> str:
    for lig, rep in _LIGATURE_MAP.items():
        text = text.replace(lig, rep)
    return text


def _is_inverted_caps_word(word: str) -> bool:
    """Return True if this word uses PDF small-caps encoding (e.g. SENiOR, ENGiNEER).

    Signature: mostly uppercase letters with lowercase 'i', 'j', 'l', 'f', 'k'
    scattered in — these are glyphs whose small-cap form is indistinguishable from
    the regular lowercase glyph in some PDF fonts.
    """
    alpha = [c for c in word if c.isalpha()]
    if len(alpha) < 4:
        return False
    upper_count = sum(1 for c in alpha if c.isupper())
    lower_chars = [c for c in alpha if c.islower()]
    if not lower_chars or upper_count < 2:
        return False
    # All lowercase chars must be in the "invisible small-cap" set
    _INVERTED_LOWER = frozenset("ijlftk")
    return upper_count / len(alpha) > 0.6 and all(c in _INVERTED_LOWER for c in lower_chars)


def _normalize_caps_token(token: str) -> str:
    """Normalize one whitespace-free token from an inverted-caps string."""
    alpha_only = re.sub(r"[^A-Za-z]", "", token)
    lower_key = alpha_only.lower()
    # Known tech acronyms
    if lower_key in _TECH_ACRONYMS:
        return _TECH_ACRONYMS[lower_key]
    # Short (≤3 alpha chars) → likely acronym, preserve
    if len(alpha_only) <= 3:
        return token
    # Apply title-case (handles SENiOR → Senior, PLATFORM → Platform)
    return token.title()


def _normalize_inverted_caps(text: str) -> str:
    """If *text* exhibits the inverted-caps PDF pattern, normalize each word.

    Only activates when at least one inverted-caps word is detected so normal
    mixed-case strings are left untouched.
    """
    tokens = text.split()
    if not any(_is_inverted_caps_word(t) for t in tokens):
        return text
    return " ".join(_normalize_caps_token(t) for t in tokens)


def _normalize_str(value: Any) -> Any:
    """Apply ligature + inverted-caps normalisation to a single string value."""
    if not isinstance(value, str):
        return value
    value = _normalize_ligatures(value)
    value = _normalize_inverted_caps(value)
    return value


def _normalize_editor_strings(editor: dict) -> dict:
    """Walk all string fields in the editor dict and apply text normalization."""
    scalar_fields = (
        "name", "position", "email", "phone", "location",
        "linkedin", "github", "website", "summary",
    )
    result = dict(editor)
    for field in scalar_fields:
        if isinstance(result.get(field), str):
            result[field] = _normalize_str(result[field])

    # Certifications: list of strings
    result["certifications"] = [
        _normalize_str(c) for c in result.get("certifications", []) if isinstance(c, str)
    ]

    # Experiences
    normalized_exps = []
    for exp in result.get("experiences", []):
        if not isinstance(exp, dict):
            normalized_exps.append(exp)
            continue
        exp = dict(exp)
        for f in ("title", "company", "dates", "location"):
            if isinstance(exp.get(f), str):
                exp[f] = _normalize_str(exp[f])
        exp["bullets"] = [
            _normalize_str(b) for b in exp.get("bullets", []) if isinstance(b, str)
        ]
        normalized_exps.append(exp)
    result["experiences"] = normalized_exps

    # Skills
    normalized_skills = []
    for group in result.get("skills", []):
        if not isinstance(group, dict):
            normalized_skills.append(group)
            continue
        group = dict(group)
        if isinstance(group.get("category"), str):
            group["category"] = _normalize_str(group["category"])
        group["items"] = [
            _normalize_str(i) for i in group.get("items", []) if isinstance(i, str)
        ]
        normalized_skills.append(group)
    result["skills"] = normalized_skills

    return result

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


def _looks_like_handle_token(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned or " " in cleaned or any(ch in cleaned for ch in "@:/|"):
        return False
    if len(cleaned) < 3 or len(cleaned) > 40:
        return False
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cleaned) is not None


def _extract_reference_profiles(ref: str) -> dict[str, str]:
    lines = [_clean_line(line) for line in (ref or "").splitlines()[:20] if _clean_line(line)]
    linkedin = ""
    github = ""
    website = ""
    handle_candidates: list[str] = []
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
        if _looks_like_handle_token(line):
            handle_candidates.append(line)
        if not website:
            for match in _URLISH_RE.finditer(line):
                candidate = match.group(0)
                lower_candidate = candidate.lower()
                if "linkedin.com" in lower_candidate or "github.com" in lower_candidate or "@" in candidate:
                    continue
                website = _normalize_website(candidate)
                break
    unique_handles = []
    seen_handles: set[str] = set()
    for candidate in handle_candidates:
        key = candidate.lower()
        if key not in seen_handles:
            seen_handles.add(key)
            unique_handles.append(candidate)
    if unique_handles and (len(unique_handles) >= 2 or any("-" in candidate or "." in candidate for candidate in unique_handles)):
        if not linkedin:
            linked_candidate = next((candidate for candidate in unique_handles if "-" in candidate or "." in candidate), "")
            if linked_candidate:
                linkedin = _normalize_linkedin(linked_candidate)
        if not github:
            github_candidate = next((candidate for candidate in unique_handles if "." not in candidate and "-" not in candidate), "")
            if github_candidate:
                github = _normalize_github(github_candidate)
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

    ref_position = _normalize_str(_extract_summary_position(ref))
    header_position = _normalize_str(_extract_header_position(ref))
    llm_position = _clean_line(editor.get("position", ""))

    if not llm_position:
        # Prefer: header headline → summary inference → first experience title
        best = header_position or ref_position
        if not best:
            exps = editor.get("experiences", [])
            if exps and isinstance(exps[0], dict):
                best = exps[0].get("title", "")
        editor["position"] = best or ""
    elif (
        header_position
        and not header_position.lower().startswith(("and ", "or ", "with ", "to ", "the ", "of "))
        and llm_position.lower() not in _normalize_ligatures(ref or "").lower()
    ):
        # LLM position doesn't appear anywhere in the reference — override with header headline
        logger.info("Verifier: overriding position %r -> %r", llm_position, header_position)
        editor["position"] = header_position

    return editor


# ---------------------------------------------------------------------------
# Certification verification
# ---------------------------------------------------------------------------

_CERT_SECTION_HEADER_WORDS = frozenset(
    "open source work experience skills education project projects certifications "
    "certification awards award summary technical key achievements achievement "
    "responsibilities responsibility tasks training knowledge proficiency".split()
)
_CERT_SECTION_CONNECTORS = frozenset("in for by at from through via with of".split())


def _is_cert_section_header(cert: str) -> bool:
    """Return True if cert looks like a section header rather than a real cert.

    Handles: "Open Source & Projects", "Technical Skills", "Projects / Tasks",
    "Key Achievements", "Work Experience", etc.
    """
    words = cert.lower().split()
    if not words or len(words) > 5:
        return False
    if words[0] not in _CERT_SECTION_HEADER_WORDS:
        return False
    # Connectors like "in", "for", "by" indicate a real cert phrase, not a header
    if any(w in _CERT_SECTION_CONNECTORS for w in words[1:]):
        return False
    return True


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
        # Drop obvious non-cert patterns before word-overlap check
        if re.match(r"^TECH\s*:", cert_clean, re.I):
            logger.warning("Verifier: dropping tech-stack cert %r", cert_clean[:60])
            continue
        # Drop pipe-separated project/skill lists (2+ pipes with or without spaces)
        if cert_clean.count("|") >= 2:
            logger.warning("Verifier: dropping project-list cert %r", cert_clean[:60])
            continue
        if len(cert_clean) > 120:
            logger.warning("Verifier: dropping oversized cert (%d chars)", len(cert_clean))
            continue
        if _is_cert_section_header(cert_clean):
            logger.warning("Verifier: dropping section-header cert %r", cert_clean)
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

_DASH_SEP_RE = re.compile(r"\s*[–—]\s*")  # em dash / en dash separators in job lines


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

        # Fix "Senior ML Engineer – HCL" in company or title fields
        company = exp.get("company", "")
        title = exp.get("title", "")

        if company and _DASH_SEP_RE.search(company):
            parts = _DASH_SEP_RE.split(company, maxsplit=1)
            if len(parts) == 2:
                inferred_title, actual_company = parts[0].strip(), parts[1].strip()
                if actual_company:
                    logger.info("Verifier: splitting company %r -> title=%r company=%r",
                                company, inferred_title, actual_company)
                    exp["company"] = actual_company
                    if not title:
                        exp["title"] = inferred_title
                    company = actual_company

        if title and _DASH_SEP_RE.search(title):
            parts = _DASH_SEP_RE.split(title, maxsplit=1)
            if len(parts) == 2:
                actual_title, appended_company = parts[0].strip(), parts[1].strip()
                if actual_title:
                    logger.info("Verifier: stripping company from title %r -> %r",
                                title, actual_title)
                    exp["title"] = actual_title

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
        # Drop cert-like category names (e.g. "Microsoft Certified", "AWS Certified")
        category = (group.get("category") or "").strip()
        _CERT_CATEGORY_RE = re.compile(
            r"\b(certified|certification|certificate|specialization|credential)\b",
            re.I,
        )
        if _CERT_CATEGORY_RE.search(category):
            logger.warning("Verifier: dropping cert-like skill category %r", category)
            continue

        # Drop items that look like sentences, dates, company names, or job titles
        _COMPANY_SUFFIX_RE = re.compile(
            r"\b(limited|ltd\.?|inc\.?|corp\.?|llc|private|pvt\.?|solutions|"
            r"services|systems|technologies|consulting|group)\s*$",
            re.I,
        )
        _JOB_TITLE_START_RE = re.compile(
            r"^(senior|junior|lead|principal|staff|associate|assistant|chief|"
            r"vp|director|manager|head of)\b",
            re.I,
        )
        _DATE_ITEM_RE = re.compile(
            r"\b\d{1,2}/\d{4}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
            r"[\s.]\d{4}\b|\b(19|20)\d{2}\s*[-–]\s*(present|\d{4})\b",
            re.I,
        )

        def _is_skill_name(item: str) -> bool:
            s = str(item).strip()
            if len(s) > 60:
                return False
            if ". " in s or s.endswith("."):
                return False
            words = s.split()
            if len(words) > 6:
                return False
            # Date ranges e.g. "09/2022 - Present"
            if _DATE_ITEM_RE.search(s):
                return False
            # Bullet-separator lists e.g. "Python • SQL • PyTorch"
            if "•" in s or " | " in s:
                return False
            # All-caps section header artifacts e.g. "FAMILIAR WITH", "PERSONAL PROJECTS"
            if s == s.upper() and len(s) > 3 and s.replace(" ", "").isalpha():
                return False
            # Company names e.g. "Dow Chemical International Private Limited"
            if _COMPANY_SUFFIX_RE.search(s):
                return False
            # Job title lines e.g. "Senior Information Technology Analyst"
            if _JOB_TITLE_START_RE.match(s) and len(words) >= 3:
                return False
            # Section header artifacts e.g. "Achievements/Tasks and Responsibilities"
            if "/" in s and len(words) >= 3:
                return False
            # Gerund/past-tense openers: "Working as ...", "Configured ..."
            if words and re.match(r"[A-Z]\w+(?:ing|ed)$", words[0]):
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
    result = _normalize_editor_strings(result)
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
