"""Avis et conseils agrométéorologiques (F6.2) et avis de planification anticipée (F8.2)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import diffusion, messages
from .. import module1_bridge as bridge
from ..db import get_db
from ..models import User, utcnow
from ..models_content import Advisory, AdvisoryKind, ContentStatus
from ..rbac import get_optional_user, require_permission
from ..schemas_content import (
    AdvisoryList,
    AdvisoryOut,
    AdvisoryUpdate,
    AdvisoryWrite,
    BroadcastOut,
    ShareKit,
    TranslateRequest,
)
from ..seed import get_setting
from .common import get_or_404, require_visible, status_filter

router = APIRouter(prefix="/advisories", tags=["Avis et conseils"])


@router.get("", response_model=AdvisoryList)
def list_advisories(
    kind: AdvisoryKind | None = Query(default=None, description="conseil = avis et conseils ; planification = avis de planification anticipée"),
    status_: Literal["published", "draft", "cancelled", "all"] = Query(default="published", alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Avis, du plus récent au plus ancien. Sans droits de gestion : uniquement les avis publiés."""
    wanted = status_filter(user, status_)
    stmt = select(Advisory)
    if wanted:
        stmt = stmt.where(Advisory.status == wanted)
    if kind:
        stmt = stmt.where(Advisory.kind == kind)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(func.coalesce(Advisory.published_at, Advisory.created_at).desc()).limit(limit).offset(offset)).all()
    return AdvisoryList(total=total, items=rows)


@router.get("/{advisory_id}", response_model=AdvisoryOut)
def get_advisory(advisory_id: str, user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    require_visible(user, a.status)
    return a


@router.post("", response_model=AdvisoryOut, status_code=status.HTTP_201_CREATED)
def create_advisory(body: AdvisoryWrite, user: User = Depends(require_permission("content:manage")),
                    db: Session = Depends(get_db)):
    """Crée un avis en brouillon (texte français obligatoire ; anglais et mooré facultatifs, ou
    proposés par `POST /advisories/{id}/translate`)."""
    a = Advisory(**body.model_dump(), created_by=user.id)
    db.add(a)
    db.commit()
    return a


@router.patch("/{advisory_id}", response_model=AdvisoryOut)
def update_advisory(advisory_id: str, body: AdvisoryUpdate, _: User = Depends(require_permission("content:manage")),
                    db: Session = Depends(get_db)):
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    if a.status == ContentStatus.cancelled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Un avis retiré n'est plus modifiable.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(a, field, value)
    db.commit()
    return a


@router.post("/{advisory_id}/translate", response_model=AdvisoryOut)
def translate_advisory(advisory_id: str, body: TranslateRequest, _: User = Depends(require_permission("content:manage")),
                       db: Session = Depends(get_db)):
    """Propose une traduction automatique du titre et du texte (anglais : MyMemory, mooré : CITADEL/NLLB).
    À relire avant publication. N'écrase pas l'existant sauf `overwrite=true`."""
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    try:
        for lang in body.langs:
            for part in ("title", "body"):
                field = f"{part}_{lang}"
                if body.overwrite or not getattr(a, field):
                    setattr(a, field, bridge.translate(getattr(a, f"{part}_fr"), lang))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Service de traduction indisponible : {exc}") from None
    db.commit()
    return a


@router.post("/{advisory_id}/publish", response_model=AdvisoryOut)
def publish_advisory(
    advisory_id: str,
    background: BackgroundTasks,
    broadcast: bool | None = Query(default=None, description="Diffuser tout de suite ; par défaut : paramètre `diffusion.auto_broadcast`"),
    user: User = Depends(require_permission("content:publish")),
    db: Session = Depends(get_db),
):
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    if a.status != ContentStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Seul un brouillon peut être publié.")
    a.status, a.published_at = ContentStatus.published, utcnow()
    db.commit()
    if broadcast is None:
        broadcast = bool((get_setting(db, "diffusion.auto_broadcast") or {}).get("advisory"))
    if broadcast:
        row = diffusion.create_broadcast(db, "advisory", a.id, user.id, "auto")
        background.add_task(diffusion.run_broadcast, row.id)
    return a


@router.post("/{advisory_id}/withdraw", response_model=AdvisoryOut)
def withdraw_advisory(advisory_id: str, _: User = Depends(require_permission("content:publish")), db: Session = Depends(get_db)):
    """Retire un avis publié."""
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    if a.status != ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cet avis n'est pas publié.")
    a.status = ContentStatus.cancelled
    db.commit()
    return a


@router.post("/{advisory_id}/broadcast", response_model=BroadcastOut, status_code=status.HTTP_202_ACCEPTED)
def broadcast_advisory(advisory_id: str, background: BackgroundTasks, user: User = Depends(require_permission("content:publish")),
                       db: Session = Depends(get_db)):
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    if a.status != ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Seul un avis publié peut être diffusé.")
    row = diffusion.create_broadcast(db, "advisory", a.id, user.id, "manual")
    background.add_task(diffusion.run_broadcast, row.id)
    return row


@router.get("/{advisory_id}/share-kit", response_model=ShareKit)
def share_kit(advisory_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    return messages.share_kit(db, "advisory", get_or_404(db, Advisory, advisory_id, "Avis"))


@router.delete("/{advisory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_advisory(advisory_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    a = get_or_404(db, Advisory, advisory_id, "Avis")
    if a.status == ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Retirez d'abord l'avis publié.")
    db.delete(a)
    db.commit()
