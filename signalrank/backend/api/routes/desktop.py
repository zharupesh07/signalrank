import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import create_access_token, hash_password
from api.config import desktop_data_dir, is_desktop_mode, settings
from api.database import get_db
from api.models import Profile, User
from llm.providers import build_llm_client, normalize_provider, provider_display_name

router = APIRouter(prefix="/api/desktop", tags=["desktop"])
logger = logging.getLogger(__name__)

DESKTOP_USER_EMAIL = "local@signalrank.desktop"
KEYRING_SERVICE = "SignalRank Desktop"
PROVIDERS = ("openrouter", "openai", "anthropic")
PROVIDER_KEY_ATTRS = {
    "openrouter": "openrouter_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}


class ProviderKeyRequest(BaseModel):
    provider: str = "openrouter"
    api_key: str | None = None
    openrouter_api_key: str | None = None


class ProviderPreferenceRequest(BaseModel):
    active_provider: str


def _require_desktop_mode() -> None:
    if not is_desktop_mode():
        raise HTTPException(status_code=404, detail="Desktop endpoints are disabled")


def _provider_path() -> Path:
    return desktop_data_dir() / "provider.json"


def _provider_keychain_user(provider: str) -> str:
    return f"{provider}_api_key"


def _settings_key(provider: str) -> str:
    return str(getattr(settings, PROVIDER_KEY_ATTRS[provider], "") or "").strip()


def _set_settings_key(provider: str, key: str) -> None:
    setattr(settings, PROVIDER_KEY_ATTRS[provider], key)


def _load_provider_config() -> dict:
    path = _provider_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save_provider_config(payload: dict) -> None:
    path = _provider_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.debug("Could not restrict desktop provider file permissions", exc_info=True)


def _load_keychain_key(provider: str) -> str:
    try:
        import keyring

        return (
            keyring.get_password(KEYRING_SERVICE, _provider_keychain_user(provider)) or ""
        ).strip()
    except Exception as exc:
        logger.debug("Desktop keychain read failed: %s", exc)
        return ""


def _save_keychain_key(provider: str, key: str) -> bool:
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, _provider_keychain_user(provider), key)
        return True
    except Exception as exc:
        logger.debug("Desktop keychain write failed: %s", exc)
        return False


def _save_provider_key(provider: str, key: str, *, keychain_saved: bool) -> None:
    payload = _load_provider_config()
    payload["active_provider"] = provider
    payload.setdefault("providers", {})
    providers = payload["providers"]
    providers[provider] = {"configured": True, "keychain": keychain_saved}
    if not keychain_saved:
        providers[provider]["api_key"] = key
    _save_provider_config(payload)


def _load_provider_key(provider: str) -> str:
    existing = _settings_key(provider)
    if existing:
        return existing
    keychain_key = _load_keychain_key(provider)
    if keychain_key:
        _set_settings_key(provider, keychain_key)
        return keychain_key
    payload = _load_provider_config()
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    provider_payload = providers.get(provider) if isinstance(providers, dict) else {}
    key = str((provider_payload or {}).get("api_key") or "").strip()
    if not key and provider == "openrouter":
        key = str(payload.get("openrouter_api_key") or "").strip()
    if key:
        _set_settings_key(provider, key)
    return key


def _active_provider() -> str:
    payload = _load_provider_config()
    configured = [provider for provider in PROVIDERS if _load_provider_key(provider)]
    saved = normalize_provider(str(payload.get("active_provider") or settings.llm_provider))
    if saved in configured:
        return saved
    return configured[0] if configured else saved


def _provider_statuses() -> list[dict]:
    active = _active_provider()
    return [
        {
            "id": provider,
            "name": provider_display_name(provider),
            "configured": bool(_load_provider_key(provider)),
            "active": provider == active,
        }
        for provider in PROVIDERS
    ]


async def ensure_desktop_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == DESKTOP_USER_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=DESKTOP_USER_EMAIL,
            password_hash=hash_password("desktop-local-user"),
            is_admin=True,
        )
        db.add(user)
        try:
            await db.flush()
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            await db.rollback()
            user = (
                await db.execute(select(User).where(User.email == DESKTOP_USER_EMAIL))
            ).scalar_one()

    profile = (
        await db.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None:
        db.add(Profile(user_id=user.id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
    user = (
        await db.execute(select(User).where(User.email == DESKTOP_USER_EMAIL))
    ).scalar_one()
    return user


@router.get("/status")
async def desktop_status(db: AsyncSession = Depends(get_db)):
    _require_desktop_mode()
    user = await ensure_desktop_user(db)
    profile = (
        await db.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one_or_none()
    active = _active_provider()
    key = _load_provider_key(active)
    settings.llm_provider = active
    return {
        "mode": "desktop",
        "provider_configured": bool(key),
        "provider": active if key else None,
        "active_provider": active,
        "providers": _provider_statuses(),
        "user_id": user.id,
        "resume_uploaded": bool(profile and profile.resume_text),
        "onboarding_complete": bool(profile and profile.onboarding_complete),
    }


@router.post("/session")
async def desktop_session(db: AsyncSession = Depends(get_db)):
    _require_desktop_mode()
    user = await ensure_desktop_user(db)
    return {
        "access_token": create_access_token(user.id, user.email, is_admin=True),
        "token_type": "bearer",
    }


@router.post("/provider-key")
async def save_provider_key(body: ProviderKeyRequest):
    _require_desktop_mode()
    provider = normalize_provider(body.provider)
    key = (body.api_key or body.openrouter_api_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail=f"{provider_display_name(provider)} API key is required",
        )

    client = build_llm_client(provider=provider, api_key=key, timeout=10.0)
    healthy = await client.probe_models(limit=1)
    if not healthy:
        raise HTTPException(
            status_code=400,
            detail=f"{provider_display_name(provider)} key could not be validated",
        )

    keychain_saved = _save_keychain_key(provider, key)
    _save_provider_key(provider, key, keychain_saved=keychain_saved)
    _set_settings_key(provider, key)
    settings.llm_provider = provider
    import api.deps_llm as deps_llm

    deps_llm._client = None
    return {"status": "ok", "provider": provider, "healthy_models": healthy}


@router.get("/providers")
async def desktop_providers():
    _require_desktop_mode()
    return {"active_provider": _active_provider(), "providers": _provider_statuses()}


@router.patch("/provider-preferences")
async def update_provider_preferences(body: ProviderPreferenceRequest):
    _require_desktop_mode()
    provider = normalize_provider(body.active_provider)
    if not _load_provider_key(provider):
        raise HTTPException(
            status_code=400,
            detail=f"{provider_display_name(provider)} key is not configured",
        )
    payload = _load_provider_config()
    payload["active_provider"] = provider
    _save_provider_config(payload)
    settings.llm_provider = provider
    import api.deps_llm as deps_llm

    deps_llm._client = None
    return {"status": "ok", "active_provider": provider}
