from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import services
from ..config import get_settings
from ..db import get_db
from ..identifiers import classify_identifier
from ..models import RefreshSession, Role, User, UserStatus, VerificationCode, utcnow
from ..rbac import get_current_user, get_user_for_2fa_setup
from ..schemas import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResendRequest,
    TokenPair,
    TwoFactorEnableRequest,
    TwoFactorLoginRequest,
    TwoFactorSetupResponse,
    VerifyRequest,
)
from ..security import (
    TokenError,
    check_totp,
    codes_match,
    create_jwt,
    decode_jwt,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    new_totp_secret,
    totp_uri,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentification"])
audit = logging.getLogger("auth.audit")

INVALID_CREDENTIALS = HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiant ou mot de passe incorrect.")
INVALID_CODE = HTTPException(status.HTTP_400_BAD_REQUEST, "Code invalide ou expiré.")


class RegisterResponse(BaseModel):
    user_id: str
    status: UserStatus
    verification_required: bool
    verification_channel: str | None
    message: str


# ============================================================== inscription
@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Inscription grand public : par téléphone (code SMS), e-mail (code par e-mail) ou compte local.

    Le rôle attribué est toujours `grand_public` ; les rôles internes sont créés par un administrateur.
    """
    s = get_settings()
    if services.find_conflicts(db, body.phone, body.email, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cet identifiant.")

    channel = {"phone": "sms", "email": "email", "local": None}[body.method]
    if body.method == "local":
        account_status = UserStatus.active if s.local_account_auto_activate else UserStatus.pending
    else:
        account_status = UserStatus.pending  # activé après vérification du code

    user = User(
        phone=body.phone if body.method == "phone" else None,
        email=body.email if body.method == "email" else None,
        username=body.username if body.method == "local" else None,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=Role.grand_public,
        status=account_status,
        commune=body.commune,
        language=body.language,
    )
    user.notification_channels = services.default_channels(user.phone, user.email)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cet identifiant.") from None

    if channel:
        services.issue_verification_code(db, user, channel, respect_cooldown=False)
        message = "Compte créé. Saisissez le code reçu pour l'activer."
    elif account_status == UserStatus.pending:
        message = "Compte créé. Il sera utilisable après validation par un administrateur."
    else:
        message = "Compte créé et activé."
    return RegisterResponse(user_id=user.id, status=user.status, verification_required=channel is not None,
                            verification_channel=channel, message=message)


@router.post("/verify", response_model=MessageResponse)
def verify(body: VerifyRequest, db: Session = Depends(get_db)):
    """Valide le code reçu par SMS / e-mail et active le compte."""
    s = get_settings()
    ident = classify_identifier(body.identifier)
    user = services.find_user(db, body.identifier) if ident and ident[0] != "username" else None
    row = None
    if user:
        row = db.scalar(select(VerificationCode).where(VerificationCode.user_id == user.id, VerificationCode.consumed.is_(False))
                        .order_by(VerificationCode.created_at.desc()).limit(1))
    if not user or not row or row.expires_at < utcnow():
        raise INVALID_CODE

    row.attempts += 1
    if row.attempts > s.verification_max_attempts:
        row.consumed = True
        db.commit()
        raise INVALID_CODE
    if not codes_match(body.code, row.code_hash):
        db.commit()
        raise INVALID_CODE

    row.consumed = True
    if row.channel == "sms":
        user.phone_verified = True
    else:
        user.email_verified = True
    if user.status == UserStatus.pending:
        user.status = UserStatus.active
    db.commit()
    audit.info("compte activé user=%s", user.id)
    return MessageResponse(message="Compte activé. Vous pouvez vous connecter.")


@router.post("/resend-code", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def resend_code(body: ResendRequest, db: Session = Depends(get_db)):
    """Renvoie un code. Réponse identique que le compte existe ou non (pas d'énumération de comptes)."""
    ident = classify_identifier(body.identifier)
    user = services.find_user(db, body.identifier) if ident and ident[0] != "username" else None
    if user and user.status == UserStatus.pending:
        services.issue_verification_code(db, user, "sms" if ident[0] == "phone" else "email")
    return MessageResponse(message="Si un compte en attente correspond, un nouveau code vient d'être envoyé.")


# ============================================================== connexion
@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Connexion par téléphone, e-mail ou identifiant local + mot de passe.

    Selon le compte, la réponse contient soit les jetons (`tokens`), soit un `challenge_token` à
    échanger avec le code 2FA (`/auth/2fa/verify`), soit un `setup_token` pour configurer la 2FA
    (rôles qui l'exigent : administrateur, agent ANAM).
    """
    s = get_settings()
    user = services.find_user(db, body.identifier)
    if user:
        services.ensure_not_locked(user)
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not password_ok:
        if user:
            services.register_failure(db, user)
        audit.warning("échec de connexion identifiant=%s", body.identifier[:40])
        raise INVALID_CREDENTIALS

    if user.status == UserStatus.pending:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Compte non activé.")
    if user.status == UserStatus.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Compte désactivé.")

    services.clear_failures(user)
    if user.totp_enabled:
        db.commit()
        return LoginResponse(requires_2fa=True,
                             challenge_token=create_jwt(user.id, "2fa", s.challenge_token_minutes))
    if user.role.value in s.roles_requiring_2fa:
        db.commit()
        return LoginResponse(requires_2fa_setup=True,
                             setup_token=create_jwt(user.id, "2fa_setup", s.challenge_token_minutes))

    audit.info("connexion user=%s", user.id)
    return LoginResponse(tokens=services.issue_tokens(db, user, request))


# ============================================================== 2FA
@router.post("/2fa/verify", response_model=TokenPair)
def two_factor_verify(body: TwoFactorLoginRequest, request: Request, db: Session = Depends(get_db)):
    """2e étape de connexion : échange le `challenge_token` + code TOTP contre les jetons."""
    try:
        user_id = decode_jwt(body.challenge_token, "2fa")
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Challenge invalide ou expiré.") from None
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or user.status != UserStatus.active or not user.totp_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Challenge invalide ou expiré.")
    services.ensure_not_locked(user)

    step = check_totp(decrypt_secret(user.totp_secret_enc), body.code, user.totp_last_step)
    if step is None:
        services.register_failure(db, user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code 2FA incorrect.")
    user.totp_last_step = step
    services.clear_failures(user)
    audit.info("connexion 2FA user=%s", user.id)
    return services.issue_tokens(db, user, request)


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
def two_factor_setup(user: User = Depends(get_user_for_2fa_setup), db: Session = Depends(get_db)):
    """Génère un secret TOTP (à scanner en QR code dans une application d'authentification).
    Appelable avec un token d'accès, ou avec le `setup_token` reçu à la connexion."""
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "La 2FA est déjà activée.")
    secret = new_totp_secret()
    user.totp_secret_enc = encrypt_secret(secret)
    db.commit()
    account = user.email or user.username or user.phone
    return TwoFactorSetupResponse(secret=secret, otpauth_uri=totp_uri(secret, account))


@router.post("/2fa/enable", response_model=TokenPair)
def two_factor_enable(body: TwoFactorEnableRequest, request: Request,
                      user: User = Depends(get_user_for_2fa_setup), db: Session = Depends(get_db)):
    """Confirme la configuration avec un premier code, active la 2FA et ouvre la session."""
    if user.totp_enabled or not user.totp_secret_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Appelez d'abord /auth/2fa/setup (ou la 2FA est déjà active).")
    services.ensure_not_locked(user)
    step = check_totp(decrypt_secret(user.totp_secret_enc), body.code, user.totp_last_step)
    if step is None:
        services.register_failure(db, user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code 2FA incorrect.")
    user.totp_enabled = True
    user.totp_last_step = step
    services.clear_failures(user)
    audit.info("2FA activée user=%s", user.id)
    return services.issue_tokens(db, user, request)


# ============================================================== sessions
@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Renouvelle la session. Le refresh token est à usage unique (rotation) : le réutiliser
    après échange est traité comme un vol et ferme toutes les sessions du compte."""
    row = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_token(body.refresh_token)))
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou expirée.")
    if row is None:
        raise invalid
    if row.revoked:
        services.revoke_all_sessions(db, row.user_id)
        db.commit()
        audit.warning("réutilisation d'un refresh token user=%s : sessions révoquées", row.user_id)
        raise invalid
    user = db.scalar(select(User).where(User.id == row.user_id))
    if row.expires_at < utcnow() or user is None or user.status != UserStatus.active:
        raise invalid
    row.revoked = True
    return services.issue_tokens(db, user, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    """Termine la session correspondant à ce refresh token (idempotent)."""
    row = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_token(body.refresh_token)))
    if row:
        row.revoked = True
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Termine toutes les sessions du compte, sur tous les appareils."""
    services.revoke_all_sessions(db, user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
