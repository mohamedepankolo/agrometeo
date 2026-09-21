"""Construction des réponses API à partir des lignes de base (URLs de médias, zones, prévention)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .models import utcnow
from .models_content import (
    Alert,
    AlertType,
    AlertZone,
    Bulletin,
    ContentStatus,
    PreventionMessage,
    Zone,
)
from .schemas_content import (
    AlertOut,
    AlertTypeOut,
    BulletinOut,
    MediaFiles,
    MediaInfo,
    PreventionOut,
    ZoneOut,
)
from .seed import get_setting


def source_citation(db: Session) -> str:
    return get_setting(db, "platform.source_citation")


def media_info(row) -> MediaInfo:
    files = {}
    for lang, f in (row.media or {}).items():
        files[lang] = MediaFiles(audio=storage.media_url(f.get("audio")), video=storage.media_url(f.get("video")))
    return MediaInfo(status=row.media_status, error=row.media_error, files=files)


def alert_is_active(alert: Alert, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return alert.status == ContentStatus.published and (alert.valid_until is None or alert.valid_until > now)


def alert_zones(db: Session, alert_id: str) -> list[Zone]:
    return list(db.scalars(select(Zone).join(AlertZone, AlertZone.zone_id == Zone.id)
                           .where(AlertZone.alert_id == alert_id).order_by(Zone.name)))


def prevention_for(db: Session, alert_type_id: str) -> list[PreventionMessage]:
    return list(db.scalars(select(PreventionMessage).where(PreventionMessage.alert_type_id == alert_type_id,
                                                           PreventionMessage.active.is_(True))))


def alert_out(db: Session, alert: Alert, staff: bool = False) -> AlertOut:
    return AlertOut(
        id=alert.id,
        type=AlertTypeOut.model_validate(db.get(AlertType, alert.alert_type_id)),
        level=alert.level,
        title=alert.title,
        status=alert.status,
        is_active=alert_is_active(alert),
        zones=[ZoneOut.model_validate(z) for z in alert_zones(db, alert.id)],
        parsed=alert.parsed,
        texts=alert.texts,
        prevention=[PreventionOut.model_validate(p) for p in prevention_for(db, alert.alert_type_id)],
        image_url=storage.media_url(alert.image_path),
        media=media_info(alert),
        valid_until=alert.valid_until,
        created_at=alert.created_at,
        published_at=alert.published_at,
        source=source_citation(db),
        raw_text=alert.raw_text if staff else None,
    )


def bulletin_out(db: Session, b: Bulletin) -> BulletinOut:
    return BulletinOut(
        id=b.id, title=b.title, date_text=b.date_text, issued_at=b.issued_at, status=b.status, parsed=b.parsed,
        texts=b.texts, pdf_url=storage.media_url(b.pdf_path), media=media_info(b), created_at=b.created_at,
        published_at=b.published_at, source=source_citation(db),
    )
