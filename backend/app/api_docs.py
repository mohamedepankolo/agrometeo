"""Ajoute à la description de chaque route qui peut l'appeler (« Accès : ... »), lu dans ses dépendances.
La documentation interactive et le fichier OpenAPI remis aux développeurs front-end sont ainsi toujours
alignés avec le contrôle d'accès réel du code."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.routing import APIRoute

from .rbac import ROLE_LABELS, ROLE_PERMISSIONS, get_current_user, get_optional_user, get_user_for_2fa_setup


def _collect(dependant, found: list) -> None:
    for dep in dependant.dependencies:
        found.append(dep.call)
        _collect(dep, found)


def access_of(route: APIRoute) -> str:
    calls: list = []
    _collect(route.dependant, calls)
    for call in calls:
        perm = getattr(call, "_permission", None)
        if perm:
            roles = [ROLE_LABELS[r] for r, perms in ROLE_PERMISSIONS.items() if perm in perms]
            return f"Connexion requise, permission `{perm}` (rôles : {', '.join(roles)})."
    if get_user_for_2fa_setup in calls:
        return "Jeton d'accès, ou jeton de configuration 2FA reçu à la connexion."
    if get_current_user in calls:
        return "Connexion requise (tout utilisateur connecté)."
    if get_optional_user in calls:
        return "Public. Une connexion avec droits de gestion donne accès aux contenus non publiés."
    return "Public."


def annotate_access(router: APIRouter) -> None:
    """À appeler sur chaque routeur AVANT `app.include_router` (les routes sont copiées à l'inclusion)."""
    for route in router.routes:
        if isinstance(route, APIRoute) and "Accès :" not in (route.description or ""):
            route.description = f"{(route.description or '').rstrip()}\n\n**Accès :** {access_of(route)}".strip()
