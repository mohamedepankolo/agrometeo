"""Alertes météo (F1.6) : saisie, génération audio/vidéo, publication, diffusion."""

from __future__ import annotations

import shutil
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import diffusion, media_jobs, messages, storage
from .. import module1_bridge as bridge
from ..content_views import alert_out
from ..db import get_db
from ..models import User, utcnow
from ..models_content import Alert, AlertType, AlertZone, ContentStatus, MediaStatus, Zone
from ..rbac import get_optional_user, has_permission, require_permission
from ..schemas_content import (
    AlertCreate,
    AlertList,
    AlertOut,
    AlertPreview,
    AlertPreviewRequest,
    AlertUpdate,
    BroadcastOut,
    ShareKit,
)
from ..seed import get_setting
from .common import get_or_404, require_visible, status_filter

router = APIRouter(prefix="/alerts", tags=["Alertes"])


def _check_type_and_zones(db: Session, type_id: str | None, zone_ids: list[str] | None) -> None:
    if type_id:
        t = get_or_404(db, AlertType, type_id, "Type d'alerte")
        if not t.active:
            raise HTTPException(422, "Ce type d'alerte est désactivé.")
    if zone_ids:
        found = db.scalar(select(func.count()).select_from(Zone).where(Zone.id.in_(zone_ids)))
        if found != len(set(zone_ids)):
            raise HTTPException(422, "Une ou plusieurs zones sont inconnues.")


def _set_zones(db: Session, alert_id: str, zone_ids: list[str]) -> None:
    for link in db.scalars(select(AlertZone).where(AlertZone.alert_id == alert_id)):
        db.delete(link)
    db.flush()
    for zid in dict.fromkeys(zone_ids):
        db.add(AlertZone(alert_id=alert_id, zone_id=zid))


def _parse(raw_text: str) -> dict | None:
    try:
        return bridge.parse_alert(raw_text)
    except Exception:  # noqa: BLE001 — l'analyse est indicative, jamais bloquante
        return None


def _title(db: Session, type_id: str, level: str) -> str:
    return f"Alerte {level} - {db.get(AlertType, type_id).label_fr}"


@router.post("/preview", response_model=AlertPreview)
def preview_text(body: AlertPreviewRequest, _: User = Depends(require_permission("content:manage"))):
    """Montre comment le texte saisi est découpé (date, situation, évolution, risques, conseils),
    sans rien enregistrer. Sert au formulaire de validation du back-office."""
    return _parse(body.raw_text) or {}


@router.get("", response_model=AlertList)
def list_alerts(
    status_: Literal["published", "draft", "cancelled", "all"] = Query(default="published", alias="status"),
    active_only: bool = Query(default=False, description="Seulement les alertes non expirées"),
    type_code: str | None = None,
    zone_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Liste des alertes, les plus récentes d'abord. Sans droits de gestion : uniquement les alertes publiées."""
    wanted = status_filter(user, status_)
    stmt = select(Alert)
    if wanted:
        stmt = stmt.where(Alert.status == wanted)
    if active_only:
        stmt = stmt.where(Alert.status == ContentStatus.published,
                          or_(Alert.valid_until.is_(None), Alert.valid_until > utcnow()))
    if type_code:
        stmt = stmt.join(AlertType, AlertType.id == Alert.alert_type_id).where(AlertType.code == type_code)
    if zone_id:
        stmt = stmt.where(Alert.id.in_(select(AlertZone.alert_id).where(AlertZone.zone_id == zone_id)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(func.coalesce(Alert.published_at, Alert.created_at).desc()).limit(limit).offset(offset)).all()
    staff = has_permission(user, "content:manage")
    return AlertList(total=total, items=[alert_out(db, a, staff) for a in rows])


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: str, user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    """Détail d'une alerte : texte par langue, message de prévention, zones, liens des audios et vidéos."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    require_visible(user, alert.status)
    return alert_out(db, alert, has_permission(user, "content:manage"))


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(body: AlertCreate, user: User = Depends(require_permission("content:manage")),
                 db: Session = Depends(get_db)):
    """Crée une alerte en brouillon. Étapes suivantes : `PUT /alerts/{id}/image`, `POST /alerts/{id}/media`
    (génération des audios et vidéos), puis `POST /alerts/{id}/publish`."""
    _check_type_and_zones(db, body.alert_type_id, body.zone_ids)
    alert = Alert(alert_type_id=body.alert_type_id, level=body.level, raw_text=body.raw_text.strip(),
                  title=body.title or _title(db, body.alert_type_id, body.level.value), parsed=_parse(body.raw_text),
                  valid_until=body.valid_until, created_by=user.id)
    db.add(alert)
    db.flush()
    _set_zones(db, alert.id, body.zone_ids)
    db.commit()
    return alert_out(db, alert, staff=True)


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: str, body: AlertUpdate, _: User = Depends(require_permission("content:manage")),
                 db: Session = Depends(get_db)):
    """Brouillon : tous les champs modifiables. Alerte publiée : seuls `level`, `title` et `valid_until`."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    data = body.model_dump(exclude_unset=True)
    if alert.status == ContentStatus.cancelled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Une alerte annulée n'est plus modifiable.")
    if alert.status == ContentStatus.published and set(data) - {"level", "title", "valid_until"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Une alerte publiée n'accepte que level, title et valid_until.")
    _check_type_and_zones(db, data.get("alert_type_id"), data.get("zone_ids"))

    zone_ids = data.pop("zone_ids", None)
    for field, value in data.items():
        setattr(alert, field, value)
    if "raw_text" in data:
        alert.raw_text = data["raw_text"].strip()
        alert.parsed = _parse(alert.raw_text)
        alert.texts, alert.media, alert.media_status = None, None, MediaStatus.none  # médias devenus périmés
    if zone_ids is not None:
        _set_zones(db, alert.id, zone_ids)
    db.commit()
    return alert_out(db, alert, staff=True)


@router.put("/{alert_id}/image", response_model=AlertOut)
def upload_image(alert_id: str, file: UploadFile = File(description="Image de l'alerte (JPEG ou PNG)"),
                 _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Envoie (ou remplace) l'image de l'alerte : radar, satellite… C'est elle qui illustre les vidéos."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    if alert.status != ContentStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "L'image ne peut être changée que sur un brouillon.")
    dest = storage.save_upload(file, storage.content_dir("alerts", alert.id), "image", "image")
    alert.image_path = storage.rel(dest)
    alert.texts, alert.media, alert.media_status = None, None, MediaStatus.none
    db.commit()
    return alert_out(db, alert, staff=True)


@router.post("/{alert_id}/media", response_model=AlertOut, status_code=status.HTTP_202_ACCEPTED)
def generate_media(alert_id: str, background: BackgroundTasks, _: User = Depends(require_permission("content:manage")),
                   db: Session = Depends(get_db)):
    """Lance la génération des 3 audios et 3 vidéos (français, anglais, mooré). Dure 1 à 3 minutes :
    relire l'alerte (`GET /alerts/{id}`) jusqu'à `media.status` = `ready` (ou `failed`, avec `media.error`)."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    if not alert.image_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ajoutez d'abord l'image de l'alerte.")
    if alert.media_status == MediaStatus.processing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Une génération est déjà en cours.")
    alert.media_status, alert.media_error = MediaStatus.processing, None
    db.commit()
    background.add_task(media_jobs.run_alert_media, alert.id)
    return alert_out(db, alert, staff=True)


@router.post("/{alert_id}/publish", response_model=AlertOut)
def publish_alert(
    alert_id: str,
    background: BackgroundTasks,
    broadcast: bool | None = Query(default=None, description="Diffuser tout de suite ; par défaut : paramètre `diffusion.auto_broadcast`"),
    user: User = Depends(require_permission("content:publish")),
    db: Session = Depends(get_db),
):
    """Publie l'alerte (visible de tous, affichée sur la carte) et, selon le paramètre, la diffuse aux
    utilisateurs concernés par SMS, notification push, e-mail et WhatsApp."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    if alert.status != ContentStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Seul un brouillon peut être publié.")
    if alert.media_status == MediaStatus.processing:
        raise HTTPException(status.HTTP_409_CONFLICT, "La génération des audios/vidéos est en cours : attendez qu'elle se termine.")
    now = utcnow()
    alert.status, alert.published_at = ContentStatus.published, now
    if alert.valid_until is None:
        alert.valid_until = now + timedelta(hours=int(get_setting(db, "alert.default_validity_hours") or 24))
    db.commit()

    if broadcast is None:
        broadcast = bool((get_setting(db, "diffusion.auto_broadcast") or {}).get("alert"))
    if broadcast:
        b = diffusion.create_broadcast(db, "alert", alert.id, user.id, "auto")
        background.add_task(diffusion.run_broadcast, b.id)
    return alert_out(db, alert, staff=True)


@router.post("/{alert_id}/cancel", response_model=AlertOut)
def cancel_alert(alert_id: str, _: User = Depends(require_permission("content:publish")), db: Session = Depends(get_db)):
    """Annule une alerte (elle disparaît de la carte et des listes publiques)."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    if alert.status == ContentStatus.cancelled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alerte déjà annulée.")
    alert.status = ContentStatus.cancelled
    db.commit()
    return alert_out(db, alert, staff=True)


@router.post("/{alert_id}/broadcast", response_model=BroadcastOut, status_code=status.HTTP_202_ACCEPTED)
def broadcast_alert(alert_id: str, background: BackgroundTasks, user: User = Depends(require_permission("content:publish")),
                    db: Session = Depends(get_db)):
    """Rediffuse manuellement une alerte publiée (relance, canal de secours). Suivi : `GET /backoffice/broadcasts/{id}`."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    if alert.status != ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Seule une alerte publiée peut être diffusée.")
    b = diffusion.create_broadcast(db, "alert", alert.id, user.id, "manual")
    background.add_task(diffusion.run_broadcast, b.id)
    return b


@router.get("/{alert_id}/share-kit", response_model=ShareKit)
def share_kit(alert_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Texte formaté pour WhatsApp (français, anglais, mooré) et liens des médias : bouton de diffusion manuelle."""
    return messages.share_kit(db, "alert", get_or_404(db, Alert, alert_id, "Alerte"))


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: str, _: User = Depends(require_permission("content:manage")), db: Session = Depends(get_db)):
    """Supprime un brouillon ou une alerte annulée (et ses fichiers). Une alerte publiée doit d'abord être annulée."""
    alert = get_or_404(db, Alert, alert_id, "Alerte")
    if alert.status == ContentStatus.published:
        raise HTTPException(status.HTTP_409_CONFLICT, "Annulez d'abord l'alerte publiée.")
    shutil.rmtree(storage.content_dir("alerts", alert.id), ignore_errors=True)
    db.delete(alert)
    db.commit()
