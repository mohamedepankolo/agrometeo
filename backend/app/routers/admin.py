from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..models import Role, User, UserStatus
from ..rbac import require_permission
from ..schemas import CommuneStat, InternalAccountCreate, MessageResponse, RoleChange, UserList, UserOut
from ..security import hash_password

router = APIRouter(prefix="/admin", tags=["Administration"])
audit = logging.getLogger("auth.audit")


def _get_user(db: Session, user_id: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable.")
    return user


@router.get("/users", response_model=UserList)
def list_users(
    status_: UserStatus | None = Query(default=None, alias="status", description="ex. pending = comptes à valider"),
    role: Role | None = None,
    commune: str | None = None,
    q: str | None = Query(default=None, description="recherche dans nom, e-mail, téléphone, identifiant"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_permission("users:read")),
    db: Session = Depends(get_db),
):
    stmt = select(User)
    if status_:
        stmt = stmt.where(User.status == status_)
    if role:
        stmt = stmt.where(User.role == role)
    if commune:
        stmt = stmt.where(User.commune == commune)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.phone.ilike(like), User.username.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)).all()
    return UserList(total=total, items=items)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: str, _: User = Depends(require_permission("users:read")), db: Session = Depends(get_db)):
    return _get_user(db, user_id)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_internal_account(body: InternalAccountCreate, admin: User = Depends(require_permission("users:manage")),
                            db: Session = Depends(get_db)):
    """Crée un compte (agent ANAM, administrateur, responsable communal…), actif immédiatement.
    L'utilisateur devra changer son mot de passe initial à sa première connexion."""
    if services.find_conflicts(db, body.phone, body.email, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cet identifiant.")
    user = User(phone=body.phone, email=body.email, username=body.username, password_hash=hash_password(body.password),
                full_name=body.full_name, role=body.role, status=UserStatus.active, commune=body.commune,
                must_change_password=True)
    user.notification_channels = services.default_channels(user.phone, user.email)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cet identifiant.") from None
    audit.info("compte interne créé user=%s role=%s par admin=%s", user.id, user.role.value, admin.id)
    return user


@router.patch("/users/{user_id}/role", response_model=UserOut)
def change_role(user_id: str, body: RoleChange, admin: User = Depends(require_permission("roles:assign")),
                db: Session = Depends(get_db)):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vous ne pouvez pas modifier votre propre rôle.")
    user = _get_user(db, user_id)
    audit.info("rôle modifié user=%s %s -> %s par admin=%s", user.id, user.role.value, body.role.value, admin.id)
    user.role = body.role
    db.commit()
    return user


@router.post("/users/{user_id}/activate", response_model=UserOut)
def activate_user(user_id: str, admin: User = Depends(require_permission("users:manage")), db: Session = Depends(get_db)):
    """Valide un compte en attente (ex. compte local) ou réactive un compte désactivé."""
    user = _get_user(db, user_id)
    user.status = UserStatus.active
    db.commit()
    audit.info("compte activé user=%s par admin=%s", user.id, admin.id)
    return user


@router.post("/users/{user_id}/disable", response_model=UserOut)
def disable_user(user_id: str, admin: User = Depends(require_permission("users:manage")), db: Session = Depends(get_db)):
    """Désactive un compte et ferme toutes ses sessions."""
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vous ne pouvez pas désactiver votre propre compte.")
    user = _get_user(db, user_id)
    user.status = UserStatus.disabled
    services.revoke_all_sessions(db, user.id)
    db.commit()
    audit.info("compte désactivé user=%s par admin=%s", user.id, admin.id)
    return user


@router.post("/users/{user_id}/reset-2fa", response_model=MessageResponse)
def reset_two_factor(user_id: str, admin: User = Depends(require_permission("users:manage")), db: Session = Depends(get_db)):
    """Réinitialise la 2FA (téléphone perdu) : l'utilisateur devra la reconfigurer à sa prochaine connexion."""
    user = _get_user(db, user_id)
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = 0
    services.revoke_all_sessions(db, user.id)
    db.commit()
    audit.info("2FA réinitialisée user=%s par admin=%s", user.id, admin.id)
    return MessageResponse(message="2FA réinitialisée.")


@router.get("/stats/communes", response_model=list[CommuneStat])
def users_by_commune(_: User = Depends(require_permission("stats:read")), db: Session = Depends(get_db)):
    """Répartition des comptes actifs par commune."""
    rows = db.execute(select(User.commune, func.count()).where(User.status == UserStatus.active)
                      .group_by(User.commune).order_by(func.count().desc())).all()
    return [CommuneStat(commune=c or "Non renseignée", users=n) for c, n in rows]
