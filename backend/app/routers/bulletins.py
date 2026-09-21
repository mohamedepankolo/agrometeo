"""Bulletins agrométéorologiques (Module IA, F1.1 à F1.4) : import du PDF, audios et vidéos, publication."""

from __future__ import annotations

import shutil
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import diffusion, media_jobs, messages, storage
from .. import module1_bridge as bridge
from ..content_views import bulletin_out
from ..db import get_db
from ..models import User, utcnow
from ..models_content import Bulletin, ContentStatus, MediaStatus
from ..rbac import get_optional_user, require_permission
from ..schemas_content import BroadcastOut, BulletinList, BulletinOut, BulletinUpdate, ShareKit
from ..seed import get_setting
from .common import get_or_404, parse_fr_date, require_visible, status_filter

router = APIRouter(prefix="/bulletins", tags=["Bulletins"])


@router.get("", response_model=BulletinList)
def list_bulletins(
    status_: Literal["published", "draft", "archived", "all"] = Query(default="published", alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Bulletins, du plus récent au plus ancien. Sans droits de gestion : uniquement les bulletins publiés."""
    wanted = status_filter(user, status_)
    stmt = select(Bulletin)
    if wanted:
        stmt = stmt.where(Bulletin.status == wanted)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(func.coalesce(Bulletin.issued_at, Bulletin.created_at).desc()).limit(limit).offset(offset)).all()
    return BulletinList(total=total, items=[bulletin_out(db, b) for b in rows])


@router.get("/latest", response_model=BulletinOut)
def latest_bulletin(db: Session = Depends(get_db)):
    """Dernier bulletin publié (écran d'accueil de l'application)."""
    b = db.scalar(select(Bulletin).where(Bulletin.status == ContentStatus.published)
                  .order_by(func.coalesce(Bulletin.issued_at, Bulletin.created_at).desc()).limit(1))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun bulletin publié.")
    return bulletin_out(db, b)


@router.get("/{bulletin_id}", response_model=BulletinOut)
def get_bulletin(bulletin_id: str, user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Détail d'un bulletin : sections du texte, texte lu par langue, PDF, liens des audios et vidéos."""
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    require_visible(user, b.status)
    return bulletin_out(db, b)


@router.post("", response_model=BulletinOut, status_code=status.HTTP_201_CREATED)
def import_bulletin(background: BackgroundTasks, file: UploadFile = File(description="Bulletin PDF de l'ANAM"),
                    user: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Importe un bulletin PDF : extraction immédiate du texte, puis génération en arrière-plan des 3 audios
    et 3 vidéos (1 à 3 minutes : relire le bulletin jusqu'à `media.status` = `ready`). Le bulletin reste en
    brouillon jusqu'à `POST /bulletins/{id}/publish`."""
    bulletin = Bulletin(title="Bulletin agrométéorologique", created_by=user.id)
    db.add(bulletin)
    db.flush()
    try:
        pdf = storage.save_upload(file, storage.content_dir("bulletins", bulletin.id), "bulletin", "pdf")
        parsed = bridge.parse_bulletin_pdf(pdf)
    except HTTPException:
        db.rollback()
        shutil.rmtree(storage.content_dir("bulletins", bulletin.id), ignore_errors=True)
        raise
    except Exception:  # noqa: BLE001
        db.rollback()
        shutil.rmtree(storage.content_dir("bulletins", bulletin.id), ignore_errors=True)
        raise HTTPException(422,
                            "Ce PDF n'a pas pu être lu comme un bulletin de l'ANAM.") from None
    if not parsed["observed"] and not parsed["forecast"]:
        db.rollback()
        shutil.rmtree(storage.content_dir("bulletins", bulletin.id), ignore_errors=True)
        raise HTTPException(422, "Aucune section « temps observé » ni « prévisions » reconnue dans ce PDF.")

    bulletin.pdf_path = storage.rel(pdf)
    bulletin.parsed = parsed
    bulletin.date_text = parsed["date_text"]
    bulletin.issued_at = parse_fr_date(parsed["date_text"])
    bulletin.title = f"Bulletin agrométéorologique - {parsed['date_text']}" if parsed["date_text"] else bulletin.title
    bulletin.media_status = MediaStatus.processing
    db.commit()
    background.add_task(media_jobs.run_bulletin_media, bulletin.id)
    return bulletin_out(db, bulletin)


@router.patch("/{bulletin_id}", response_model=BulletinOut)
def update_bulletin(bulletin_id: str, body: BulletinUpdate, _: User = Depends(require_permission("content:manage")),
                    db: Session = Depends(get_db)):
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(b, field, value)
    db.commit()
    return bulletin_out(db, b)


@router.post("/{bulletin_id}/media", response_model=BulletinOut, status_code=status.HTTP_202_ACCEPTED)
def regenerate_media(bulletin_id: str, background: BackgroundTasks, _: User = Depends(require_permission("content:manage")),
                     db: Session = Depends(get_db)):
    """Relance la génération des audios et vidéos (après un échec, ou si les services de traduction ont évolué)."""
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    if b.media_status == MediaStatus.processing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Une génération est déjà en cours.")
    b.media_status, b.media_error = MediaStatus.processing, None
    db.commit()
    background.add_task(media_jobs.run_bulletin_media, b.id)
    return bulletin_out(db, b)


@router.post("/{bulletin_id}/publish", response_model=BulletinOut)
def publish_bulletin(
    bulletin_id: str,
    background: BackgroundTasks,
    broadcast: bool | None = Query(default=None, description="Diffuser tout de suite ; par défaut : paramètre `diffusion.auto_broadcast`"),
    user: User = Depends(require_permission("content:publish")),
    db: Session = Depends(get_db),
):
    """Publie le bulletin (visible dans l'application) et, selon le paramètre, le diffuse."""
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    if b.status == ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bulletin déjà publié.")
    if b.media_status == MediaStatus.processing:
        raise HTTPException(status.HTTP_409_CONFLICT, "La génération des audios/vidéos est en cours : attendez qu'elle se termine.")
    b.status, b.published_at = ContentStatus.published, utcnow()
    db.commit()
    if broadcast is None:
        broadcast = bool((get_setting(db, "diffusion.auto_broadcast") or {}).get("bulletin"))
    if broadcast:
        row = diffusion.create_broadcast(db, "bulletin", b.id, user.id, "auto")
        background.add_task(diffusion.run_broadcast, row.id)
    return bulletin_out(db, b)


@router.post("/{bulletin_id}/unpublish", response_model=BulletinOut)
def unpublish_bulletin(bulletin_id: str, _: User = Depends(require_permission("content:publish")), db: Session = Depends(get_db)):
    """Retire le bulletin de l'application (archivé)."""
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    if b.status != ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce bulletin n'est pas publié.")
    b.status = ContentStatus.archived
    db.commit()
    return bulletin_out(db, b)


@router.post("/{bulletin_id}/broadcast", response_model=BroadcastOut, status_code=status.HTTP_202_ACCEPTED)
def broadcast_bulletin(bulletin_id: str, background: BackgroundTasks, user: User = Depends(require_permission("content:publish")),
                       db: Session = Depends(get_db)):
    """(Re)diffuse manuellement un bulletin publié. Suivi : `GET /backoffice/broadcasts/{id}`."""
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    if b.status != ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Seul un bulletin publié peut être diffusé.")
    row = diffusion.create_broadcast(db, "bulletin", b.id, user.id, "manual")
    background.add_task(diffusion.run_broadcast, row.id)
    return row


@router.get("/{bulletin_id}/share-kit", response_model=ShareKit)
def share_kit(bulletin_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Texte formaté pour WhatsApp et liens des médias : bouton de diffusion manuelle du back-office."""
    return messages.share_kit(db, "bulletin", get_or_404(db, Bulletin, bulletin_id, "Bulletin"))


@router.delete("/{bulletin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bulletin(bulletin_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Supprime un bulletin non publié (et ses fichiers)."""
    b = get_or_404(db, Bulletin, bulletin_id, "Bulletin")
    if b.status == ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dépubliez d'abord le bulletin.")
    shutil.rmtree(storage.content_dir("bulletins", b.id), ignore_errors=True)
    db.delete(b)
    db.commit()
