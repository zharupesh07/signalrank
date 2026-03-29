from domain.role_taxonomy import CANONICAL_ROLE_OPTIONS, LOCATION_OPTIONS, TIER_OPTIONS
from llm.resume_parser import ResumeParseResult


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
        "options": CANONICAL_ROLE_OPTIONS,
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
