"""Back-office (F6.1 à F6.4) : tableau de bord, statistiques d'usage, suivi des diffusions, paramètres."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import diffusion
from ..db import get_db
from ..models import User, UserStatus, utcnow
from ..models_content import (
    Advisory,
    Alert,
    Broadcast,
    Bulletin,
    ContentStatus,
    Delivery,
    MediaStatus,
    Setting,
    UsageEvent,
)
from ..rbac import require_permission
from ..schemas_content import (
    BroadcastDetail,
    BroadcastList,
    BroadcastOut,
    DashboardOut,
    DeliveryOut,
    SettingsUpdate,
    SmsPilotOut,
    UsageOut,
)
from ..seed import DEFAULT_SETTINGS, all_settings, get_setting
from .common import get_or_404

router = APIRouter(prefix="/backoffice", tags=["Back-office"])

_CHANNELS = {"push", "sms", "email", "whatsapp"}
_CONTENT_TYPES = {"alert", "bulletin", "advisory"}


# ============================================================== tableau de bord
@router.get("/dashboard", response_model=DashboardOut)
def dashboard(_: User = Depends(require_permission("stats:read")), db: Session = Depends(get_db)):
    """Indicateurs du tableau de bord : comptes, contenus diffusés, envois par canal, usage des 7 derniers jours."""
    now = utcnow()

    def count(model, *conds) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*conds)) or 0

    users_by_status = dict(db.execute(select(User.status, func.count()).group_by(User.status)).all())
    users_by_role = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    by_commune = db.execute(select(User.commune, func.count()).where(User.status == UserStatus.active)
                            .group_by(User.commune).order_by(func.count().desc())).all()
    deliveries = {}
    for channel, st, n in db.execute(select(Delivery.channel, Delivery.status, func.count()).group_by(Delivery.channel, Delivery.status)):
        deliveries.setdefault(channel, {})[st] = n
    usage = dict(db.execute(select(UsageEvent.kind, func.count()).where(UsageEvent.created_at > now - timedelta(days=7))
                            .group_by(UsageEvent.kind)).all())
    recent = db.scalars(select(Broadcast).order_by(Broadcast.created_at.desc()).limit(5)).all()
    return {
        "users": {
            "total": sum(users_by_status.values()),
            "by_status": {k.value: v for k, v in users_by_status.items()},
            "by_role": {k.value: v for k, v in users_by_role.items()},
            "active_by_commune": [{"commune": c or "Non renseignée", "users": n} for c, n in by_commune],
        },
        "content": {
            "bulletins_published": count(Bulletin, Bulletin.status == ContentStatus.published),
            "bulletins_draft": count(Bulletin, Bulletin.status == ContentStatus.draft),
            "alerts_published": count(Alert, Alert.status == ContentStatus.published),
            "alerts_active": count(Alert, Alert.status == ContentStatus.published,
                                   (Alert.valid_until.is_(None)) | (Alert.valid_until > now)),
            "alerts_draft": count(Alert, Alert.status == ContentStatus.draft),
            "advisories_published": count(Advisory, Advisory.status == ContentStatus.published),
            "media_failed": count(Bulletin, Bulletin.media_status == MediaStatus.failed)
            + count(Alert, Alert.media_status == MediaStatus.failed),
        },
        "diffusion": {"deliveries_by_channel": deliveries, "recent_broadcasts": [BroadcastOut.model_validate(b).model_dump(mode="json") for b in recent]},
        "usage_last_7_days": usage,
    }


@router.get("/usage", response_model=UsageOut)
def usage_stats(days: int = Query(default=30, ge=1, le=365), _: User = Depends(require_permission("stats:read")),
                db: Session = Depends(get_db)):
    """Statistiques d'usage (consultations, écoutes, lectures vidéo, partages) par jour, par langue, et contenus les plus vus."""
    since = utcnow() - timedelta(days=days)
    day = func.date(UsageEvent.created_at)
    by_day: dict[str, dict[str, int]] = {}
    for d, kind, n in db.execute(select(day, UsageEvent.kind, func.count()).where(UsageEvent.created_at > since)
                                 .group_by(day, UsageEvent.kind).order_by(day)):
        by_day.setdefault(str(d), {})[kind] = n
    by_language = dict(db.execute(select(func.coalesce(UsageEvent.language, "inconnue"), func.count())
                                  .where(UsageEvent.created_at > since).group_by(UsageEvent.language)).all())
    top = db.execute(select(UsageEvent.content_type, UsageEvent.content_id, func.count().label("n"))
                     .where(UsageEvent.created_at > since).group_by(UsageEvent.content_type, UsageEvent.content_id)
                     .order_by(func.count().desc()).limit(10)).all()
    return {"days": days, "by_day": by_day, "by_language": by_language,
            "top_content": [{"content_type": t, "content_id": i, "events": n} for t, i, n in top]}


# ============================================================== suivi des diffusions
@router.get("/broadcasts", response_model=BroadcastList)
def list_broadcasts(content_type: str | None = None, content_id: str | None = None,
                    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                    _: User = Depends(require_permission("stats:read")), db: Session = Depends(get_db)):
    """Historique des diffusions (automatiques et manuelles), les plus récentes d'abord."""
    stmt = select(Broadcast)
    if content_type:
        stmt = stmt.where(Broadcast.content_type == content_type)
    if content_id:
        stmt = stmt.where(Broadcast.content_id == content_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Broadcast.created_at.desc()).limit(limit).offset(offset)).all()
    return BroadcastList(total=total, items=rows)


@router.get("/broadcasts/{broadcast_id}", response_model=BroadcastDetail)
def get_broadcast(broadcast_id: str, channel: str | None = None, status_: str | None = Query(default=None, alias="status"),
                  limit: int = Query(default=200, ge=1, le=1000), _: User = Depends(require_permission("stats:read")),
                  db: Session = Depends(get_db)):
    """Suivi d'une diffusion : décompte par canal et statut, et détail des envois (filtrables). Statut `simulated`
    = envoi simulé (mode développement, rien n'est parti)."""
    b = get_or_404(db, Broadcast, broadcast_id, "Diffusion")
    stmt = select(Delivery).where(Delivery.broadcast_id == b.id)
    if channel:
        stmt = stmt.where(Delivery.channel == channel)
    if status_:
        stmt = stmt.where(Delivery.status == status_)
    deliveries = db.scalars(stmt.order_by(Delivery.id).limit(limit)).all()
    return BroadcastDetail(**BroadcastOut.model_validate(b).model_dump(), by_channel=diffusion.summarize(db, b.id),
                           deliveries=[DeliveryOut.model_validate(d) for d in deliveries])


@router.get("/sms-pilot", response_model=SmsPilotOut)
def sms_pilot(_: User = Depends(require_permission("stats:read")), db: Session = Depends(get_db)):
    """Suivi du pilote SMS (objectif : 500 utilisateurs) : envois par statut, destinataires distincts, avancement."""
    by_status = dict(db.execute(select(Delivery.status, func.count()).where(Delivery.channel == "sms")
                                .group_by(Delivery.status)).all())
    recipients = db.scalar(select(func.count(func.distinct(Delivery.recipient))).where(Delivery.channel == "sms")) or 0
    users_with_sms = sum(1 for (chs,) in db.execute(select(User.notification_channels).where(User.status == UserStatus.active))
                         if "sms" in (chs or []))
    target = int(get_setting(db, "sms.pilot_target") or 500)
    return {"target_users": target, "users_opted_in_sms": users_with_sms, "distinct_recipients_reached": recipients,
            "deliveries_by_status": by_status, "progress": round(min(users_with_sms / target, 1.0), 3) if target else None}


# ============================================================== paramètres (F6.4)
def _validate_setting(key: str, value) -> None:
    def bad(msg: str):
        raise HTTPException(422, f"{key} : {msg}")

    if key == "diffusion.channels":
        if not isinstance(value, dict) or set(value) != _CONTENT_TYPES:
            bad("attendu un objet avec les clés alert, bulletin, advisory")
        for ctype, chans in value.items():
            if not isinstance(chans, list) or not set(chans) <= _CHANNELS:
                bad(f"{ctype} : canaux autorisés {sorted(_CHANNELS)}")
    elif key == "diffusion.auto_broadcast":
        if not isinstance(value, dict) or set(value) != _CONTENT_TYPES or not all(isinstance(v, bool) for v in value.values()):
            bad("attendu {alert, bulletin, advisory} avec des booléens")
    elif key == "diffusion.whatsapp_recipients":
        if not isinstance(value, list) or not all(isinstance(n, str) and re.fullmatch(r"\+\d{8,15}", n) for n in value):
            bad("liste de numéros au format international (+226...)")
    elif key == "platform.default_language":
        if value not in {"fr", "en", "mos"}:
            bad("valeurs possibles : fr, en, mos")
    elif key in {"alert.default_validity_hours", "sms.max_length", "sms.pilot_target"}:
        limits = {"alert.default_validity_hours": (1, 720), "sms.max_length": (70, 1000), "sms.pilot_target": (1, 1_000_000)}[key]
        if not isinstance(value, int) or isinstance(value, bool) or not limits[0] <= value <= limits[1]:
            bad(f"entier entre {limits[0]} et {limits[1]}")
    elif not isinstance(value, str) or not value.strip():
        bad("texte non vide attendu")


@router.get("/settings", response_model=dict)
def get_settings_(_: User = Depends(require_permission("config:manage")), db: Session = Depends(get_db)):
    """Paramètres généraux de la plateforme et de la diffusion (valeurs actuelles, défauts inclus)."""
    return all_settings(db)


@router.put("/settings", response_model=dict)
def update_settings(body: SettingsUpdate, _: User = Depends(require_permission("config:manage")), db: Session = Depends(get_db)):
    """Modifie un ou plusieurs paramètres : `{"values": {"diffusion.channels": {...}}}`. Clés inconnues refusées."""
    unknown = set(body.values) - set(DEFAULT_SETTINGS)
    if unknown:
        raise HTTPException(422, f"Paramètres inconnus : {sorted(unknown)}")
    for key, value in body.values.items():
        _validate_setting(key, value)
    for key, value in body.values.items():
        row = db.get(Setting, key)
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return all_settings(db)
