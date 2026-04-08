from api.models import Profile


def deep_merge_dict(base: dict | None, incoming: dict | None) -> dict | None:
    if base is None:
        return incoming
    if incoming is None:
        return base
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged.get(key), value)
        else:
            merged[key] = value
    return merged


def profile_resume_template(profile: Profile | None) -> str | None:
    if not profile or not isinstance(profile.config_overrides, dict):
        return None
    resume_cfg = profile.config_overrides.get("resume")
    if not isinstance(resume_cfg, dict):
        return None
    template = resume_cfg.get("template")
    return template if isinstance(template, str) else None
