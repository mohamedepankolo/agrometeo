from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import User
from ..models_content import ContentStatus
from ..rbac import has_permission

T = TypeVar("T")

_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
           "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}


def get_or_404(db: Session, model: type[T], obj_id: str, label: str = "Ressource") -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} introuvable.")
    return obj


def status_filter(user: User | None, wanted: str) -> ContentStatus | None:
    """Statut à filtrer pour une liste. Le public ne voit que le publié ; le personnel peut demander
    les brouillons, annulés ou archivés, ou `all` (None = pas de filtre)."""
    if wanted == "published":
        return ContentStatus.published
    if not has_permission(user, "content:manage"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seuls les contenus publiés sont accessibles sans droits de gestion.")
    return None if wanted == "all" else ContentStatus(wanted)


def require_visible(user: User | None, content_status: ContentStatus) -> None:
    """Un contenu non publié est invisible (404, pas 403) pour qui n'a pas les droits de gestion."""
    if content_status != ContentStatus.published and not has_permission(user, "content:manage"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ressource introuvable.")


def parse_fr_date(text: str | None) -> datetime | None:
    """'17 Septembre 2026 à 12 h' -> datetime (UTC naïf), ou None si le format n'est pas reconnu."""
    import re

    if not text:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-zéûôàè]+)\s+(\d{4})(?:\s*[àa]\s*(\d{1,2}))?", text)
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    try:
        return datetime(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)), int(m.group(4) or 0))
    except ValueError:
        return None
