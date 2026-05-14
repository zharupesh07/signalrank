import re


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(\(?\+?\d[\d\s().-]{7,}\d)")
_DATE_LINE_RE = re.compile(
    r"(?i)\b(?:\d{1,2}/\d{4}|[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}[’']?\d{2}|\d{4})\b.*(?:present|\d{4}|\d{2})"
)
_SECTION_HEADINGS = {
    "summary": {"summary", "professional summary", "profile"},
    "experience": {"work experience", "professional experience", "experience"},
    "projects": {"projects", "open source & projects", "open source projects"},
    "skills": {"skills", "technical skills", "skills and abilities"},
    "certifications": {"certifications", "certification", "certification and innovation"},
    "education": {"education", "academic background"},
    "awards": {"awards and achievements", "awards", "achievements", "honors and awards"},
}
_ROLE_TITLE_RE = re.compile(
    r"\b(engineer|developer|analyst|manager|consultant|scientist|architect|"
    r"specialist|sdet|qa|automation|platform|cloud|mlops|lead|intern)\b",
    re.I,
)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "")).strip()


def _clean_lines(text: str) -> list[str]:
    return [_clean_line(line) for line in (text or "").splitlines() if _clean_line(line)]


def _normalize_heading(line: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", (line or "").lower()).strip()
    tokens = normalized.split()
    if len(tokens) >= 3 and all(len(token) == 1 for token in tokens):
        return "".join(tokens)
    return normalized


def _looks_like_name(line: str) -> bool:
    if not line or "@" in line or any(ch.isdigit() for ch in line):
        return False
    if _ROLE_TITLE_RE.search(line):
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 5:
        return False
    return all(re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", word) for word in words)


def _looks_like_contact_line(line: str) -> bool:
    lower = (line or "").lower()
    return bool(
        _EMAIL_RE.search(line or "")
        or _PHONE_RE.search(line or "")
        or "linkedin.com/" in lower
        or "github.com/" in lower
        or lower.startswith(("www.", "http://", "https://"))
    )


def _looks_like_handle_token(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned or " " in cleaned or any(ch in cleaned for ch in "@:/|"):
        return False
    if len(cleaned) < 3 or len(cleaned) > 40:
        return False
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cleaned) is not None


def _looks_like_position_line(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned or _looks_like_contact_line(cleaned) or _looks_like_certification_line(cleaned):
        return False
    if cleaned.endswith("."):
        return False
    if re.fullmatch(r"[|·\-–—,/\s]+", cleaned):
        return False
    if _looks_like_location(cleaned):
        return False
    words = cleaned.split()
    letters = [ch for ch in cleaned if ch.isalpha()]
    uppercase_ratio = (
        sum(1 for ch in letters if ch.isupper()) / len(letters) if letters else 0
    )
    if len(words) >= 8 and uppercase_ratio < 0.5 and not any(token in cleaned for token in ("|", "·", "/", "&")):
        return False
    return len(cleaned) <= 140 and 2 <= len(words) <= 16


def _normalize_position_text(value: str) -> str:
    cleaned = _clean_line(value).strip(" |·-/")
    if not cleaned:
        return ""
    letters = [ch for ch in cleaned if ch.isalpha()]
    if letters and sum(1 for ch in letters if ch.isupper()) / len(letters) >= 0.75:
        cleaned = cleaned.upper()
    cleaned = re.sub(r"\bi([A-Z])", r"I\1", cleaned)
    cleaned = re.sub(r"([A-Z])i\b", r"\1I", cleaned)
    if cleaned.upper() == cleaned:
        return (
            cleaned.title()
            .replace("Ai ", "AI ")
            .replace("Mlops", "MLOps")
            .replace("R&D", "R&D")
            .replace("Poc", "POC")
            .replace("Pot", "POT")
            .replace("Mvp", "MVP")
            .replace("Qa ", "QA ")
            .replace("Sdet", "SDET")
        )
    return cleaned


def _looks_like_location(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned:
        return False
    lower = cleaned.lower()
    if cleaned in {"|", "·", "-", "–", "—", "/", ","}:
        return False
    location_indicators = ("india", "usa", "uk", "remote", "hybrid", "bengaluru", "bangalore",
                           "mumbai", "pune", "delhi", "hyderabad", "chennai", "kolkata", "noida",
                           "gurugram", "gurgaon", "new york", "san francisco", "london")
    if any(loc in lower for loc in location_indicators):
        if len(cleaned.split()) <= 5:
            return True
    if "·" in cleaned and len(cleaned.split()) <= 5:
        return True
    return False


def _looks_like_certification_line(line: str) -> bool:
    lower = (line or "").lower()
    return "certif" in lower or "credly" in lower or "badge" in lower


def _looks_like_bullet_fragment(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned or len(cleaned) > 120:
        return False
    if cleaned.startswith(("•", "-", "*")):
        return True
    if cleaned[:1].islower():
        return True
    if cleaned.endswith((".", ",", ";")) and len(cleaned.split()) <= 10:
        return True
    lowered = cleaned.lower()
    return bool(re.search(r"\b(?:built|led|implemented|developed|designed|created|improved|reduced|engineered|configured|delivered|managed|owned|collaborated|architected|productionized|refactored|supported|maintained|deployed)\b", lowered))


def _looks_like_role_header(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned or _looks_like_contact_line(cleaned) or _looks_like_date_line(cleaned):
        return False
    if len(cleaned) > 120:
        return False
    lowered = cleaned.lower()
    return bool(re.search(r"\b(engineer|developer|analyst|manager|consultant|scientist|intern|lead|architect|specialist|designer|administrator|founder|researcher|technician|associate)\b", lowered))


def _split_role_company(line: str) -> tuple[str, str]:
    cleaned = _clean_line(line)
    if not cleaned:
        return "", ""
    for delimiter in (" – ", " — ", " - ", " at "):
        if delimiter in cleaned:
            left, right = cleaned.rsplit(delimiter, 1)
            left = _clean_line(left)
            right = _clean_line(right)
            if left and right:
                return left, right
    return cleaned, ""


def _match_heading(line: str) -> tuple[str | None, str]:
    normalized = _normalize_heading(line)
    compact = normalized.replace(" ", "")
    for name, aliases in _SECTION_HEADINGS.items():
        for alias in aliases:
            alias_normalized = _normalize_heading(alias)
            if normalized == alias_normalized or compact == alias_normalized.replace(" ", ""):
                return name, ""
            pattern = rf"(?i)^\s*{re.escape(alias)}\s*[:\-]\s*(.*)$"
            match = re.match(pattern, line or "")
            if match:
                return name, _clean_line(match.group(1))
    return None, ""


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        matched, remainder = _match_heading(line)
        if matched:
            current = matched
            sections.setdefault(current, [])
            if remainder:
                sections[current].append(remainder)
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _parse_contact(lines: list[str]) -> dict:
    top_lines = lines[:12]
    joined = "\n".join(top_lines)
    name = next((line for line in top_lines if _looks_like_name(line)), "")
    position = ""
    if name:
        try:
            name_index = top_lines.index(name)
        except ValueError:
            name_index = -1
        for line in top_lines[name_index + 1:]:
            if _looks_like_position_line(line) and not _looks_like_name(line):
                position = _normalize_position_text(line)
                break
    if not position:
        for line in top_lines:
            if line == name or len(line) <= 2:
                continue
            if _looks_like_position_line(line):
                position = _normalize_position_text(line)
                break

    email_match = _EMAIL_RE.search(joined)
    phone_match = _PHONE_RE.search(joined)

    linkedin = ""
    github = ""
    website = ""
    location = ""
    handle_candidates: list[str] = []
    for line in top_lines:
        lower = line.lower()
        skip_parts = line == name or _normalize_position_text(line) == position or _looks_like_location(line)
        if "linkedin.com/" in lower and not linkedin:
            linkedin = line
        elif "github.com/" in lower and not github:
            github = line
        elif (
            not website
            and line not in {name, position}
            and "@" not in line
            and not _PHONE_RE.search(line)
            and "." in line
            and " " not in line
        ):
            website = line
        elif _looks_like_handle_token(line):
            handle_candidates.append(line)
        elif not location and line not in {name, position}:
            cleaned_location = _clean_line(line)
            if _looks_like_location(cleaned_location):
                location = cleaned_location
        if skip_parts:
            continue
        for part in re.split(r"\s*[|•]\s*", line):
            part = _clean_line(part)
            part_lower = part.lower()
            if not part or part in {name, position, website}:
                continue
            if not linkedin and "linkedin.com/" in part_lower:
                linkedin = part
            elif not github and "github.com/" in part_lower:
                github = part
            elif (
                not website
                and "@" not in part
                and not _PHONE_RE.search(part)
                and "." in part
                and " " not in part
                and not part_lower.startswith("linkedin.com/")
                and not part_lower.startswith("github.com/")
            ):
                website = part
            elif not location and _looks_like_location(part):
                location = part
            elif _looks_like_handle_token(part):
                handle_candidates.append(part)

    unique_handles = _dedupe_preserve(handle_candidates)
    if unique_handles and (len(unique_handles) >= 2 or any("-" in candidate for candidate in unique_handles)):
        if not linkedin:
            linked_candidate = next((candidate for candidate in unique_handles if "-" in candidate), "")
            if linked_candidate:
                linkedin = linked_candidate
        if not github:
            github_candidate = next((candidate for candidate in unique_handles if "." not in candidate and "-" not in candidate), "")
            if github_candidate:
                github = github_candidate

    return {
        "name": name,
        "position": position,
        "email": email_match.group(0) if email_match else "",
        "phone": _clean_line(phone_match.group(1)) if phone_match else "",
        "location": location,
        "linkedin": linkedin,
        "github": github,
        "website": website,
    }


def _parse_summary(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def _infer_summary_from_header(lines: list[str], contact: dict) -> str:
    exclusions = {
        contact.get("name", ""),
        contact.get("position", ""),
        contact.get("email", ""),
        contact.get("phone", ""),
        contact.get("location", ""),
        contact.get("linkedin", ""),
        contact.get("github", ""),
        contact.get("website", ""),
    }
    summary_lines: list[str] = []
    for line in lines:
        cleaned = _clean_line(line)
        if not cleaned or cleaned in exclusions:
            continue
        if cleaned.lower().startswith("last updated"):
            continue
        if _looks_like_contact_line(cleaned) or _looks_like_name(cleaned) or _looks_like_certification_line(cleaned):
            continue
        if len(cleaned) < 30:
            continue
        summary_lines.append(cleaned)
    return "\n".join(summary_lines).strip()


def _looks_like_date_line(line: str) -> bool:
    return bool(_DATE_LINE_RE.search(line or ""))


def _strip_bullet_marker(line: str) -> str:
    stripped = re.sub(r"^\s*[•\-*]\s*", "", line or "")
    return _clean_line(stripped)


def _has_bullet_marker(line: str) -> bool:
    return bool(re.match(r"^\s*[•]\s*\S", line or "") or re.match(r"^\s*[-*]\s+", line or ""))


def _ends_bullet_sentence(text: str) -> bool:
    cleaned = _clean_line(text)
    return cleaned.endswith((".", "!", "?"))


def _coalesce_experience_bullets(lines: list[str]) -> list[str]:
    bullets: list[str] = []
    current_parts: list[str] = []

    for raw_line in lines:
        cleaned = _strip_bullet_marker(raw_line)
        if (
            not cleaned
            or re.fullmatch(r"[,/–—\- ]+", cleaned)
            or cleaned.lower().startswith("tech:")
            or _looks_like_location_line(cleaned)
        ):
            continue

        starts_new = _has_bullet_marker(raw_line) or not current_parts
        if starts_new and current_parts:
            bullets.append(_clean_line(" ".join(current_parts)))
            current_parts = []

        current_parts.append(cleaned)
        if _ends_bullet_sentence(cleaned):
            bullets.append(_clean_line(" ".join(current_parts)))
            current_parts = []

    if current_parts:
        bullets.append(_clean_line(" ".join(current_parts)))

    return [bullet for bullet in bullets if bullet]


def _looks_like_location_line(line: str) -> bool:
    cleaned = _clean_line(line)
    if not cleaned or _looks_like_date_line(cleaned) or _looks_like_contact_line(cleaned):
        return False
    if re.fullmatch(r"[,/–—\- ]+", cleaned):
        return False
    if cleaned.lower().startswith("tech:"):
        return False
    return _looks_like_location(cleaned)


def _split_title_company(header: str) -> tuple[str, str]:
    cleaned = _clean_line(header)
    for delimiter in (" – ", " — ", " - ", " at "):
        if delimiter in cleaned:
            left, right = cleaned.rsplit(delimiter, 1)
            return left.strip(), right.strip()
    return cleaned, ""


def _split_company_tech(line: str) -> tuple[str, str]:
    cleaned = _clean_line(line)
    if " · " in cleaned:
        company, tech = cleaned.split(" · ", 1)
        return _clean_line(company), _clean_line(tech)
    return cleaned, ""


def _extract_date_location(line: str) -> tuple[str, str]:
    cleaned = _clean_line(line)
    match = re.search(
        r"(?i)\b(?:\d{1,2}/\d{4}|[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}'?\d{2}|\d{4})\b",
        cleaned,
    )
    if not match:
        return cleaned, ""
    prefix = _clean_line(cleaned[:match.start()].rstrip(",-–— "))
    dates = _clean_line(cleaned[match.start():].strip(" ,"))
    if prefix and _looks_like_location(prefix):
        return dates, prefix
    return cleaned, ""


def _extract_inline_dates(header: str) -> tuple[str, str, str] | None:
    match = _DATE_LINE_RE.search(header or "")
    if not match:
        return None
    prefix = _clean_line((header or "")[:match.start()].rstrip(",-–— "))
    dates = _clean_line((header or "")[match.start():])
    if not prefix or not dates:
        return None
    title, company = _split_title_company(prefix)
    if not title:
        return None
    return title, company, dates


def _extract_colon_experience(header: str) -> tuple[str, str, str, str] | None:
    cleaned = _clean_line(header)
    if ":" not in cleaned:
        return None
    date_part, rest = cleaned.split(":", 1)
    date_part = _clean_line(date_part)
    rest = _clean_line(rest)
    if not date_part or not rest or not _looks_like_date_line(date_part):
        return None
    title = ""
    company = rest
    location = ""
    match = re.search(r"(?i)\s+as\s+(.+)$", rest)
    if match:
        title = _clean_line(match.group(1))
        company = _clean_line(rest[: match.start()])
    if "," in company:
        left, right = company.rsplit(",", 1)
        if _looks_like_location(right):
            company = _clean_line(left)
            location = _clean_line(right)
    return title, company, date_part, location


def _starts_new_experience(lines: list[str], index: int) -> bool:
    if index >= len(lines):
        return False
    line = _clean_line(lines[index])
    if not line:
        return False
    normalized = _normalize_heading(line)
    if any(normalized in aliases for aliases in _SECTION_HEADINGS.values()):
        return True
    if _extract_inline_dates(line):
        return True
    if index + 2 < len(lines) and _looks_like_date_line(lines[index + 2]):
        return True
    if index + 1 < len(lines) and _looks_like_date_line(lines[index + 1]):
        return True
    return False


def _parse_experiences(lines: list[str]) -> list[dict]:
    experiences: list[dict] = []
    i = 0
    while i < len(lines):
        line = _clean_line(lines[i])
        if not line:
            i += 1
            continue

        title = company = dates = location = ""
        j = i

        colon_exp = _extract_colon_experience(line)
        inline = _extract_inline_dates(line)
        if colon_exp:
            title, company, dates, location = colon_exp
            j = i + 1
        elif inline:
            title, company, dates = inline
            j = i + 1
        elif i + 2 < len(lines) and _looks_like_date_line(lines[i + 2]):
            title = line
            company = _clean_line(lines[i + 1])
            dates = _clean_line(lines[i + 2])
            j = i + 3
        elif i + 1 < len(lines) and _looks_like_date_line(lines[i + 1]):
            title, company = _split_title_company(line)
            dates = _clean_line(lines[i + 1])
            j = i + 2

        if not dates:
            i += 1
            continue
        dates, inline_location = _extract_date_location(dates)
        if inline_location:
            location = inline_location

        # Repair common OCR/extraction failure where a bullet fragment is followed
        # by the real role header and the date line. In that shape, the fragment
        # belongs to the previous role, not the current title.
        if title and _looks_like_bullet_fragment(title) and experiences:
            prev = experiences[-1]
            prev.setdefault("bullets", [])
            prev["bullets"] = [*prev.get("bullets", []), _clean_line(title)]
            if _looks_like_role_header(company):
                title, company = _split_role_company(company)
            else:
                title = ""

        if not title and _looks_like_role_header(company):
            split_title, split_company = _split_role_company(company)
            if split_company or split_title != company:
                title = split_title
                company = split_company

        while j < len(lines) and re.fullmatch(r"[,/–—\- ]+", _clean_line(lines[j] or "")):
            j += 1
        tech = ""
        if j < len(lines) and _clean_line(lines[j]).lower().startswith("tech") and ":" in _clean_line(lines[j]):
            tech = _clean_line(lines[j]).split(":", 1)[1].strip()
            j += 1
        if not location and j < len(lines) and _looks_like_location_line(lines[j]):
            location = _clean_line(lines[j])
            j += 1
        if not company and j < len(lines):
            candidate_company, candidate_tech = _split_company_tech(lines[j])
            if (
                candidate_company
                and not _has_bullet_marker(lines[j])
                and not _looks_like_date_line(candidate_company)
                and ":" not in candidate_company
            ):
                company = candidate_company
                tech = tech or candidate_tech
                j += 1
        if not location and j < len(lines) and _looks_like_location_line(lines[j]):
            location = _clean_line(lines[j])
            j += 1

        bullet_lines: list[str] = []
        while j < len(lines) and not _starts_new_experience(lines, j):
            bullet_lines.append(lines[j])
            j += 1

        bullets = _coalesce_experience_bullets(bullet_lines)

        experiences.append({
            "title": title.strip(),
            "company": company.strip(),
            "dates": dates.strip(),
            "location": location.strip(),
            "tech": tech.strip(),
            "bullets": bullets,
        })
        i = j

    return [exp for exp in experiences if any(exp.get(key) for key in ("title", "company", "dates", "location", "bullets"))]


def _parse_projects(lines: list[str]) -> list[dict]:
    projects: list[dict] = []
    current: dict | None = None
    for line in lines:
        if line.lower().startswith("tech:"):
            continue
        if line.lstrip().startswith(("-", "*", "•")):
            if current:
                description = line.lstrip("-*• ").strip()
                current["description"] = "\n".join(filter(None, [current.get("description", ""), description])).strip()
            continue
        if line.startswith(("http://", "https://", "www.")) or (
            "." in line and " " not in line and "/" in line
        ):
            if current and not current.get("url"):
                current["url"] = line
            continue
        if "|" in line and "http" not in line.lower():
            parts = [part.strip() for part in line.split("|") if part.strip()]
            if len(parts) > 1:
                for part in parts:
                    if part.lower() in {"idea generation", "others", "other"}:
                        continue
                    projects.append({"name": part, "url": "", "description": ""})
                current = None
                continue
        current = {"name": line, "url": "", "description": ""}
        projects.append(current)
    return [project for project in projects if project.get("name")]


def _dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = _clean_line(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _merge_skill_items(existing: list[dict], category: str, items: list[str]) -> None:
    for group in existing:
        if group["category"].lower() == category.lower():
            group["items"] = _dedupe_preserve([*group["items"], *items])
            return
    existing.append({"category": category, "items": _dedupe_preserve(items)})


def _parse_skills(lines: list[str]) -> list[dict]:
    groups: list[dict] = []
    general_items: list[str] = []
    for line in lines:
        raw = line.lstrip("-*• ").strip()
        if not raw:
            continue
        if ":" in raw:
            category, items = raw.split(":", 1)
            _merge_skill_items(groups, category.strip(), [item.strip() for item in items.split(",") if item.strip()])
            continue
        general_items.extend(item.strip() for item in raw.split(",") if item.strip())
    if general_items:
        _merge_skill_items(groups, "General", general_items)
    return groups


def _parse_certifications(lines: list[str]) -> list[str]:
    certifications: list[str] = []
    pending_parts: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_parts
        if pending_parts:
            certifications.append(_clean_line(" ".join(pending_parts)))
            pending_parts = []

    def is_boundary(raw: str) -> bool:
        matched, _ = _match_heading(raw)
        return matched in {"education", "awards", "experience", "projects", "skills", "summary"}

    def looks_like_description(raw: str) -> bool:
        if "." in raw:
            return True
        if raw.endswith("."):
            return True
        words = raw.split()
        if len(words) >= 8 and sum(1 for word in words if word[:1].islower()) >= 3:
            return True
        return False

    def looks_like_title(raw: str) -> bool:
        if not raw or re.fullmatch(r"[,/–—\- ]+", raw):
            return False
        if _looks_like_date_line(raw):
            return False
        if re.fullmatch(r"\d+(\.\d+)?%", raw):
            return False
        if raw.lower().startswith(("this ", "designed ", "for ", "rated ", "key ")):
            return False
        if looks_like_description(raw):
            return False
        return len(raw) <= 120

    def should_extend_pending(raw: str) -> bool:
        if not pending_parts:
            return False
        prev = pending_parts[-1]
        if prev.endswith("-"):
            return True
        if re.search(r"\bS/\d", raw):
            return True
        if len(prev) <= 45 and len(raw.split()) <= 4:
            return True
        return False

    for line in lines:
        raw = _strip_bullet_marker(line)
        if not raw or re.fullmatch(r"[,/–—\- ]+", raw):
            continue
        if is_boundary(raw):
            flush_pending()
            break
        if looks_like_title(raw):
            if pending_parts and not should_extend_pending(raw):
                flush_pending()
            pending_parts.append(raw)
            continue
        flush_pending()

    flush_pending()
    return _dedupe_preserve(certifications)


def _parse_education(lines: list[str]) -> list[dict]:
    """Extract education entries from section lines."""
    entries: list[dict] = []
    i = 0
    while i < len(lines):
        raw = _strip_bullet_marker(lines[i]).strip()
        if not raw or _looks_like_date_line(raw):
            i += 1
            continue
        # Skip pure date lines and short noise
        if len(raw) < 4:
            i += 1
            continue
        degree = raw
        institution = ""
        year = ""
        # Peek at next lines for institution / year
        if i + 1 < len(lines):
            next_raw = _strip_bullet_marker(lines[i + 1]).strip()
            if next_raw and not _looks_like_date_line(next_raw):
                # Could be institution
                institution = next_raw
                i += 1
        if i + 1 < len(lines):
            next_raw = _strip_bullet_marker(lines[i + 1]).strip()
            if next_raw and (_looks_like_date_line(next_raw) or re.fullmatch(r"\d{4}", next_raw.strip())):
                year = next_raw
                i += 1
        # Also handle "Degree — Institution" on one line
        if " – " in degree or " — " in degree or " - " in degree:
            for sep in (" – ", " — ", " - "):
                if sep in degree:
                    parts = degree.split(sep, 1)
                    degree = parts[0].strip()
                    if not institution:
                        institution = parts[1].strip()
                    break
        entries.append({"degree": degree, "institution": institution, "year": year})
        i += 1
    return entries


def _empty_resume_editor() -> dict:
    return {
        "name": "",
        "position": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "website": "",
        "summary": "",
        "experiences": [],
        "projects": [],
        "skills": [],
        "certifications": [],
        "education": [],
    }


def _merge_experience_rows(preferred_rows: list[dict], fallback_rows: list[dict]) -> list[dict]:
    merged: list[dict] = []
    index_by_key: dict[tuple[str, str, str], int] = {}

    def exp_key(exp: dict) -> tuple[str, str, str]:
        return (
            _clean_line(str(exp.get("title", "") or "")).lower(),
            _clean_line(str(exp.get("company", "") or "")).lower(),
            _clean_line(str(exp.get("dates", "") or "")).lower(),
        )

    for row in preferred_rows + fallback_rows:
        if not isinstance(row, dict):
            continue
        cleaned = {
            "title": _clean_line(str(row.get("title", "") or "")),
            "company": _clean_line(str(row.get("company", "") or "")),
            "dates": _clean_line(str(row.get("dates", "") or "")),
            "location": _clean_line(str(row.get("location", "") or "")),
            "tech": _clean_line(str(row.get("tech", "") or "")),
            "bullets": _dedupe_preserve([str(bullet or "") for bullet in (row.get("bullets", []) or [])]),
        }
        if not any(cleaned.get(field) for field in ("title", "company", "dates", "location", "bullets")):
            continue
        key = exp_key(cleaned)
        if key in index_by_key and any(key):
            target = merged[index_by_key[key]]
            for field in ("title", "company", "dates", "location", "tech"):
                if not target[field] and cleaned[field]:
                    target[field] = cleaned[field]
            target["bullets"] = _dedupe_preserve([*target.get("bullets", []), *cleaned.get("bullets", [])])
            continue
        index_by_key[key] = len(merged)
        merged.append(cleaned)

    return merged


def _merge_project_rows(preferred_rows: list[dict], fallback_rows: list[dict]) -> list[dict]:
    merged: list[dict] = []
    index_by_key: dict[tuple[str, str], int] = {}

    def project_key(project: dict) -> tuple[str, str]:
        name = _clean_line(str(project.get("name", "") or "")).lower()
        url = _clean_line(str(project.get("url", "") or "")).lower()
        if name:
            return ("name", name)
        return ("url", url)

    for row in preferred_rows + fallback_rows:
        if not isinstance(row, dict):
            continue
        cleaned = {
            "name": _clean_line(str(row.get("name", "") or "")),
            "url": _clean_line(str(row.get("url", "") or "")),
            "description": str(row.get("description", "") or "").strip(),
        }
        if not any(cleaned.get(field) for field in ("name", "url", "description")):
            continue
        key = project_key(cleaned)
        if key in index_by_key and any(key):
            target = merged[index_by_key[key]]
            if not target["url"] and cleaned["url"]:
                target["url"] = cleaned["url"]
            if not target["description"] and cleaned["description"]:
                target["description"] = cleaned["description"]
            continue
        index_by_key[key] = len(merged)
        merged.append(cleaned)

    return merged


def _merge_skill_rows(preferred_rows: list[dict], fallback_rows: list[dict]) -> list[dict]:
    merged: list[dict] = []
    category_index: dict[str, int] = {}

    for row in preferred_rows + fallback_rows:
        if not isinstance(row, dict):
            continue
        category = _clean_line(str(row.get("category", "") or ""))
        items = _dedupe_preserve([str(item or "") for item in (row.get("items", []) or [])])
        if not category and not items:
            continue
        key = category.lower() or "general"
        normalized = {"category": category or "General", "items": items}
        if key in category_index:
            target = merged[category_index[key]]
            target["items"] = _dedupe_preserve([*target.get("items", []), *normalized["items"]])
            continue
        category_index[key] = len(merged)
        merged.append(normalized)

    return merged


def merge_resume_editor(preferred: dict | None, fallback: dict | None = None) -> dict:
    merged = _empty_resume_editor()
    for source in (fallback or {}, preferred or {}):
        for field in ("name", "position", "email", "phone", "location", "linkedin", "github", "website", "summary"):
            value = _clean_line(str(source.get(field, "") or "")) if field != "summary" else str(source.get(field, "") or "").strip()
            if value:
                merged[field] = value

    pref_experiences = list((preferred or {}).get("experiences") or [])
    fall_experiences = list((fallback or {}).get("experiences") or []) if not pref_experiences else []
    merged["experiences"] = _merge_experience_rows(pref_experiences, fall_experiences)

    pref_projects = list((preferred or {}).get("projects") or [])
    fall_projects = list((fallback or {}).get("projects") or [])
    merged["projects"] = _merge_project_rows(pref_projects, fall_projects)

    merged["skills"] = _merge_skill_rows(
        list((preferred or {}).get("skills") or []),
        list((fallback or {}).get("skills") or []),
    )

    pref_certs = [str(item or "") for item in ((preferred or {}).get("certifications") or [])]
    fall_certs = [str(item or "") for item in ((fallback or {}).get("certifications") or [])] if not pref_certs else []
    merged["certifications"] = _dedupe_preserve([*pref_certs, *fall_certs])

    pref_edu = list((preferred or {}).get("education") or [])
    fall_edu = list((fallback or {}).get("education") or []) if not pref_edu else []
    merged["education"] = pref_edu or fall_edu
    return merged


def has_resume_editor_content(editor: dict | None) -> bool:
    if not isinstance(editor, dict):
        return False
    return any(editor.get(field) for field in ("name", "position", "email", "phone", "summary", "experiences", "projects", "skills", "certifications"))


def parse_resume_editor(resume_text: str | None) -> dict:
    lines = _clean_lines(resume_text or "")
    if not lines:
        return _empty_resume_editor()

    sections = _split_sections(lines)
    header_lines = sections.get("header", lines[:12])
    contact = _parse_contact(header_lines)
    summary = _parse_summary(sections.get("summary", [])) or _infer_summary_from_header(header_lines, contact)
    certifications = _parse_certifications(sections.get("certifications", []))
    if not certifications:
        certifications = _dedupe_preserve([line for line in header_lines if _looks_like_certification_line(line)])

    experiences = _parse_experiences(sections.get("experience", []))
    if not contact.get("location") and experiences:
        contact["location"] = str(experiences[0].get("location") or "").strip()

    return {
        **contact,
        "summary": summary,
        "experiences": experiences,
        "projects": _parse_projects(sections.get("projects", [])),
        "skills": _parse_skills(sections.get("skills", [])),
        "certifications": certifications,
        "education": _parse_education(sections.get("education", [])),
    }


def editor_to_tailored_content(editor: dict):
    from llm.resume_tailor import TailoredContent, _normalize_tailored_content

    content = TailoredContent(
        name=_clean_line(str(editor.get("name", "") or "")),
        position=_clean_line(str(editor.get("position", "") or "")),
        email=_clean_line(str(editor.get("email", "") or "")),
        phone=_clean_line(str(editor.get("phone", "") or "")),
        location=_clean_line(str(editor.get("location", "") or "")),
        linkedin=_clean_line(str(editor.get("linkedin", "") or "")),
        github=_clean_line(str(editor.get("github", "") or "")),
        homepage=_clean_line(str(editor.get("website", "") or "")),
        summary=str(editor.get("summary", "") or "").strip(),
        skills=[
            {
                "category": _clean_line(str(group.get("category", "") or "")),
                "items": _dedupe_preserve([str(item or "") for item in (group.get("items", []) or [])]),
            }
            for group in (editor.get("skills", []) or [])
            if _clean_line(str(group.get("category", "") or "")) or any(_clean_line(str(item or "")) for item in (group.get("items", []) or []))
        ],
        experiences=[
            {
                "title": _clean_line(str(exp.get("title", "") or "")),
                "company": _clean_line(str(exp.get("company", "") or "")),
                "location": _clean_line(str(exp.get("location", "") or "")),
                "dates": _clean_line(str(exp.get("dates", "") or "")),
                "tech": _clean_line(str(exp.get("tech", "") or "")),
                "bullets": _dedupe_preserve([str(bullet or "") for bullet in (exp.get("bullets", []) or [])]),
            }
            for exp in (editor.get("experiences", []) or [])
            if any(_clean_line(str(exp.get(key, "") or "")) for key in ("title", "company", "location", "dates")) or any(_clean_line(str(bullet or "")) for bullet in (exp.get("bullets", []) or []))
        ],
        projects=[
            {
                "name": _clean_line(str(project.get("name", "") or "")),
                "url": _clean_line(str(project.get("url", "") or "")),
                "description": str(project.get("description", "") or "").strip(),
            }
            for project in (editor.get("projects", []) or [])
            if any(_clean_line(str(project.get(key, "") or "")) for key in ("name", "url", "description"))
        ],
        certifications=_dedupe_preserve([str(item or "") for item in (editor.get("certifications", []) or [])]),
        education=[
            {
                "degree": _clean_line(str(edu.get("degree", "") or "")),
                "institution": _clean_line(str(edu.get("institution", "") or "")),
                "year": _clean_line(str(edu.get("year", "") or "")),
            }
            for edu in (editor.get("education", []) or [])
            if _clean_line(str(edu.get("degree", "") or "")) or _clean_line(str(edu.get("institution", "") or ""))
        ],
    )
    return _normalize_tailored_content(content)


def serialize_resume_editor(editor: dict) -> str:
    lines: list[str] = []
    for value in (
        editor.get("name", ""),
        editor.get("position", ""),
        editor.get("email", ""),
        editor.get("phone", ""),
        editor.get("location", ""),
        editor.get("linkedin", ""),
        editor.get("github", ""),
        editor.get("website", ""),
    ):
        cleaned = _clean_line(str(value or ""))
        if cleaned:
            lines.append(cleaned)

    summary = str(editor.get("summary", "") or "").strip()
    if summary:
        lines.extend(["", "Summary", summary])

    experiences = editor.get("experiences", []) or []
    if experiences:
        lines.extend(["", "Work Experience"])
        for exp in experiences:
            title = _clean_line(str(exp.get("title", "") or ""))
            company = _clean_line(str(exp.get("company", "") or ""))
            dates = _clean_line(str(exp.get("dates", "") or ""))
            location = _clean_line(str(exp.get("location", "") or ""))
            header = " - ".join(part for part in (title, company) if part)
            if header:
                lines.append(header)
            if dates:
                lines.append(dates)
            if location:
                lines.append(location)
            for bullet in exp.get("bullets", []) or []:
                cleaned = _clean_line(str(bullet or ""))
                if cleaned:
                    lines.append(f"- {cleaned}")

    projects = editor.get("projects", []) or []
    if projects:
        lines.extend(["", "Projects"])
        for project in projects:
            name = _clean_line(str(project.get("name", "") or ""))
            url = _clean_line(str(project.get("url", "") or ""))
            description = str(project.get("description", "") or "").strip()
            if name:
                lines.append(name)
            if url:
                lines.append(url)
            if description:
                for raw_line in description.splitlines():
                    cleaned = _clean_line(raw_line)
                    if cleaned:
                        lines.append(f"- {cleaned}")

    skills = editor.get("skills", []) or []
    if skills:
        lines.extend(["", "Technical Skills"])
        for group in skills:
            category = _clean_line(str(group.get("category", "") or ""))
            items = [_clean_line(str(item or "")) for item in (group.get("items", []) or [])]
            items = [item for item in items if item]
            if category and items:
                lines.append(f"{category}: {', '.join(items)}")
            elif items:
                lines.append(", ".join(items))

    certifications = editor.get("certifications", []) or []
    if certifications:
        lines.extend(["", "Certifications"])
        for certification in certifications:
            cleaned = _clean_line(str(certification or ""))
            if cleaned:
                lines.append(cleaned)

    return "\n".join(lines).strip()
