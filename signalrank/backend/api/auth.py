import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from api.config import settings

logger = logging.getLogger(__name__)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 4  # 4 hours


def _normalize_password(password: str) -> str:
    return password[:72]


def hash_password(password: str) -> str:
    normalized = _normalize_password(password).encode("utf-8")
    return bcrypt.hashpw(normalized, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        normalized = _normalize_password(plain).encode("utf-8")
        return bcrypt.checkpw(normalized, hashed.encode("utf-8"))
    except ValueError:
        logger.warning("Password hash verification failed due to invalid hash format")
        return False


def create_access_token(user_id: str, email: str, *, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "email": email, "is_admin": is_admin, "exp": expire},
        settings.nextauth_secret,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.nextauth_secret, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.debug("Token decode failed: %s", e)
        return {}
