import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SaaSContext:
    user_id: str
    config: dict
    config_fp: str
    resume_text: str


def _fingerprint(cfg: dict) -> str:
    raw = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_BASE_CONFIG: dict | None = None


def load_base_config() -> dict:
    global _BASE_CONFIG
    if _BASE_CONFIG is None:
        base_path = Path(__file__).parent.parent / "config" / "base.yaml"
        with open(base_path) as f:
            _BASE_CONFIG = yaml.safe_load(f)
        skills_path = Path(__file__).parent.parent / "config" / "skills.yaml"
        if skills_path.exists():
            with open(skills_path) as f:
                skills = yaml.safe_load(f) or {}
            _BASE_CONFIG = deep_merge(_BASE_CONFIG, skills)
    return _BASE_CONFIG


def reset_base_config() -> None:
    global _BASE_CONFIG
    _BASE_CONFIG = None


def get_timeout(cfg: dict, key: str, default: int = 60) -> int:
    return int(cfg.get("timeouts", {}).get(key, default))


def get_retry(cfg: dict, key: str, default: int = 3) -> int:
    return int(cfg.get("retry", {}).get(key, default))


def get_batch(cfg: dict, key: str, default: int = 4) -> int:
    return int(cfg.get("batch", {}).get(key, default))


def build_context(
    user_id: str, resume_text: str, config_overrides: dict | None = None
) -> SaaSContext:
    base = load_base_config()
    merged = deep_merge(base, config_overrides or {})
    return SaaSContext(
        user_id=user_id,
        config=merged,
        config_fp=_fingerprint(merged),
        resume_text=resume_text or "",
    )
