from llm.resume_parser import ResumeParseResult

ROLE_OPTIONS = [
    "AI/ML Engineer",
    "Data Scientist",
    "MLOps/Platform Engineer",
    "Backend Engineer",
    "Full-Stack Engineer",
    "DevOps/SRE",
    "Security Engineer",
]

TIER_OPTIONS = [
    {"label": "S-tier (FAANG, top startups)", "value": "tier_s"},
    {"label": "A-tier (strong tech companies)", "value": "tier_a"},
    {"label": "B-tier (good companies)", "value": "tier_b"},
    {"label": "Any company", "value": "any"},
]

LOCATION_OPTIONS = [
    "Remote only",
    "Bangalore",
    "Hyderabad",
    "Mumbai",
    "Delhi/NCR",
    "Pune",
    "Any India",
    "Open to relocation",
]


def generate_onboarding_questions(profile: ResumeParseResult) -> list[dict]:
    questions = []

    yoe_str = f"{profile.years_of_experience} years" if profile.years_of_experience else "your"
    titles_str = ", ".join(profile.recent_titles[:3]) if profile.recent_titles else "your recent roles"
    skills_str = ", ".join(profile.skills[:5]) if profile.skills else "your skills"

    questions.append({
        "id": "target_roles",
        "text": f"I see {yoe_str} of experience with {skills_str} "
                f"(recent: {titles_str}). What roles are you targeting?",
        "type": "multi_select",
        "options": ROLE_OPTIONS,
    })

    questions.append({
        "id": "preferred_locations",
        "text": "Preferred locations? Open to remote?",
        "type": "multi_select",
        "options": LOCATION_OPTIONS,
    })

    questions.append({
        "id": "company_tiers",
        "text": "What tier of companies are you targeting?",
        "type": "multi_select",
        "options": [t["label"] for t in TIER_OPTIONS],
        "option_values": [t["value"] for t in TIER_OPTIONS],
    })

    questions.append({
        "id": "salary_expectations",
        "text": "What are your salary expectations? (annual, in LPA or USD)",
        "type": "text",
    })

    questions.append({
        "id": "exclusions",
        "text": "Any companies or roles to exclude? (e.g., consulting firms, QA roles)",
        "type": "text",
    })

    return questions
