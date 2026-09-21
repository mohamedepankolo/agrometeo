from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .identifiers import classify_identifier
from .models import RefreshSession, User, VerificationCode, utcnow
from .notifications import send_verification_code
from .schemas import TokenPair
from .security import (
    create_access_token,
    hash_code,
    hash_token,
    new_refresh_token,
    new_verification_code,
)

audit = logging.getLogger("auth.audit")


def find_user(db: Session, raw_identifier: str) -> User | None:
    ident = classify_identifier(raw_identifier)
    if ident is None:
        return None
    kind, value = ident
    return db.scalar(select(User).where(getattr(User, kind) == value))


def find_conflicts(db: Session, phone: str | None, email: str | None, username: str | None) -> bool:
    conds = [c for c in (User.phone == phone if phone else None,
                         User.email == email if email else None,
                         User.username == username if username else None) if c is not None]
    return bool(conds) and db.scalar(select(User.id).where(or_(*conds)).limit(1)) is not None


# ------------------------------------------------------------------ codes de vérification
def issue_verification_code(db: Session, user: User, channel: str, respect_cooldown: bool = True) -> bool:
    """Crée et envoie un code. Renvoie False si un code récent existe déjà (anti-spam SMS)."""
    s = get_settings()
    now = utcnow()
    if respect_cooldown:
        last = db.scalar(
            select(VerificationCode).where(VerificationCode.user_id == user.id, VerificationCode.channel == channel)
            .order_by(VerificationCode.created_at.desc()).limit(1)
        )
        if last and (now - last.created_at) < timedelta(seconds=s.verification_resend_seconds):
            return False

    db.execute(update(VerificationCode).where(VerificationCode.user_id == user.id, VerificationCode.consumed.is_(False))
               .values(consumed=True))
    code = new_verification_code()
    db.add(VerificationCode(user_id=user.id, channel=channel, code_hash=hash_code(code),
                            expires_at=now + timedelta(minutes=s.verification_code_minutes)))
    db.commit()

    to = user.phone if channel == "sms" else user.email
    try:
        send_verification_code(channel, to, code, s.verification_code_minutes)
    except Exception:
        audit.exception("échec d'envoi du code (%s) user=%s", channel, user.id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Envoi du code impossible, réessayez dans un instant.") from None
    return True


# ------------------------------------------------------------------ verrouillage anti force brute
def ensure_not_locked(user: User) -> None:
    if user.locked_until and user.locked_until > utcnow():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives : compte temporairement verrouillé.")


def register_failure(db: Session, user: User) -> None:
    s = get_settings()
    user.failed_logins += 1
    if user.failed_logins >= s.login_max_failures:
        user.locked_until = utcnow() + timedelta(minutes=s.login_lockout_minutes)
        user.failed_logins = 0
        audit.warning("compte verrouillé user=%s", user.id)
    db.commit()


def clear_failures(user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None


# ------------------------------------------------------------------ sessions
def issue_tokens(db: Session, user: User, request: Request | None = None) -> TokenPair:
    s = get_settings()
    refresh = new_refresh_token()
    ua = request.headers.get("user-agent", "")[:255] if request else None
    db.add(RefreshSession(user_id=user.id, token_hash=hash_token(refresh), user_agent=ua,
                          expires_at=utcnow() + timedelta(days=s.refresh_token_days)))
    user.last_login_at = utcnow()
    db.commit()
    return TokenPair(access_token=create_access_token(user.id), refresh_token=refresh,
                     expires_in=s.access_token_minutes * 60, must_change_password=user.must_change_password)


def revoke_all_sessions(db: Session, user_id: str) -> None:
    db.execute(update(RefreshSession).where(RefreshSession.user_id == user_id).values(revoked=True))


def default_channels(phone: str | None, email: str | None) -> list[str]:
    channels = ["push"]
    if phone:
        channels.append("sms")
    if email:
        channels.append("email")
    return channels
