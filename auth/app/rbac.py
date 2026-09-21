"""Contrôle d'accès par rôle (RBAC).

Les autres modules protègent leurs routes avec `Depends(require_permission("..."))`
au lieu de tester les rôles à la main : si la matrice change, seul ce fichier bouge.

MATRICE À VALIDER AVEC L'ANAM : le cahier des charges liste les 5 rôles mais pas
leurs droits exacts ; ce qui suit est une proposition raisonnable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, User, UserStatus
from .security import TokenError, decode_jwt

log = logging.getLogger("auth.audit")

ALL_PERMISSIONS = {
    "content:read",  # consulter bulletins, alertes, cartes
    "content:manage",  # créer / modifier bulletins, alertes, avis
    "observations:write",  # saisir des observations terrain
    "stats:read",  # tableau de bord, statistiques
    "users:read",  # consulter les comptes
    "users:manage",  # créer, activer, désactiver des comptes
    "roles:assign",  # attribuer des rôles
    "config:manage",  # paramètres et canaux de diffusion
}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.grand_public: {"content:read"},
    Role.observateur: {"content:read", "observations:write"},
    Role.responsable_communal: {"content:read", "stats:read"},
    Role.agent_anam: {"content:read", "content:manage", "observations:write", "stats:read", "users:read"},
    Role.administrateur: set(ALL_PERMISSIONS),
}

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Authentification requise.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def _load_user(db: Session, token: str, typ: str) -> User:
    try:
        user_id = decode_jwt(token, typ)
    except TokenError:
        raise _unauthorized("Token invalide ou expiré.") from None
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or user.status != UserStatus.active:
        raise _unauthorized("Compte inexistant ou inactif.")
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise _unauthorized()
    return _load_user(db, creds.credentials, "access")


def get_user_for_2fa_setup(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    """Accepte un token d'accès normal OU le token restreint remis à la connexion d'un compte
    dont le rôle impose la 2FA mais qui ne l'a pas encore configurée."""
    if creds is None:
        raise _unauthorized()
    try:
        return _load_user(db, creds.credentials, "access")
    except HTTPException:
        return _load_user(db, creds.credentials, "2fa_setup")


def require_permission(permission: str) -> Callable[..., User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if permission not in ROLE_PERMISSIONS[user.role]:
            log.warning("accès refusé user=%s role=%s permission=%s", user.id, user.role.value, permission)
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Droits insuffisants.")
        return user

    return dependency
