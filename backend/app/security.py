from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash("dummy-password-for-timing")


# ------------------------------------------------------------------ mots de passe
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Toujours un calcul argon2, même sans compte, pour ne pas révéler l'existence d'un identifiant par le temps de réponse."""
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


# ------------------------------------------------------------------ JWT
class TokenError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_jwt(subject: str, typ: str, minutes: int) -> str:
    s = get_settings()
    now = _now()
    payload = {"sub": subject, "typ": typ, "iat": now, "exp": now + timedelta(minutes=minutes), "jti": secrets.token_hex(8)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_jwt(token: str, expected_typ: str) -> str:
    """Renvoie le `sub` du token ; lève TokenError s'il est invalide, expiré ou d'un autre type."""
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload["typ"] != expected_typ:
        raise TokenError("type de token inattendu")
    return payload["sub"]


def create_access_token(user_id: str) -> str:
    return create_jwt(user_id, "access", get_settings().access_token_minutes)


# ------------------------------------------------------------------ jetons opaques / codes
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), code.encode(), hashlib.sha256).hexdigest()


def codes_match(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), code_hash)


# ------------------------------------------------------------------ 2FA (TOTP)
def _fernet() -> Fernet:
    s = get_settings()
    key_material = s.data_encryption_key or f"totp:{s.jwt_secret}"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest()))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise TokenError("secret 2FA illisible (clé de chiffrement modifiée ?)") from exc


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account_name: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=get_settings().totp_issuer)


def check_totp(secret: str, code: str, last_step: int) -> int | None:
    """Renvoie le pas de temps validé (à mémoriser pour interdire le rejeu) ou None si le code est faux."""
    totp = pyotp.TOTP(secret)
    current = int(time.time()) // 30
    for step in (current, current - 1, current + 1):
        if step > last_step and hmac.compare_digest(totp.at(step * 30), code):
            return step
    return None
