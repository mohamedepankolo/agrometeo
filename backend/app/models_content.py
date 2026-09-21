"""Modèles des contenus (bulletins, alertes, avis), des zones et de la diffusion."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import _enum, new_id, utcnow


class AlertLevel(str, enum.Enum):
    """Niveaux de la cartographie. « vert » = aucune alerte active : jamais stocké, calculé pour la carte."""

    jaune = "jaune"
    orange = "orange"
    rouge = "rouge"


LEVEL_ORDER = {"vert": 0, "jaune": 1, "orange": 2, "rouge": 3}


class ContentStatus(str, enum.Enum):
    draft = "draft"  # brouillon, visible seulement du personnel
    published = "published"
    cancelled = "cancelled"  # alerte annulée / avis retiré
    archived = "archived"  # bulletin dépublié


class MediaStatus(str, enum.Enum):
    none = "none"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class AdvisoryKind(str, enum.Enum):
    conseil = "conseil"  # avis et conseils (F6.2)
    planification = "planification"  # avis de planification anticipée (F8.2)


class ZoneKind(str, enum.Enum):
    commune = "commune"
    region = "region"


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[ZoneKind] = mapped_column(_enum(ZoneKind), default=ZoneKind.commune)
    is_pilot: Mapped[bool] = mapped_column(Boolean, default=False)
    # communes des utilisateurs concernées par une alerte sur cette zone (ciblage de la diffusion)
    commune_names: Mapped[list] = mapped_column(JSON, default=list)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[dict | None] = mapped_column(JSON)  # GeoJSON (Polygon/MultiPolygon), fourni par l'ANAM


class AlertType(Base):
    __tablename__ = "alert_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    label_fr: Mapped[str] = mapped_column(String(80))
    label_en: Mapped[str | None] = mapped_column(String(80))
    label_mos: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PreventionMessage(Base):
    __tablename__ = "prevention_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    alert_type_id: Mapped[str] = mapped_column(ForeignKey("alert_types.id", ondelete="CASCADE"), index=True)
    text_fr: Mapped[str] = mapped_column(Text)
    text_en: Mapped[str | None] = mapped_column(Text)
    text_mos: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    alert_type_id: Mapped[str] = mapped_column(ForeignKey("alert_types.id"), index=True)
    level: Mapped[AlertLevel] = mapped_column(_enum(AlertLevel))
    title: Mapped[str] = mapped_column(String(200))
    raw_text: Mapped[str] = mapped_column(Text)  # texte de l'alerte tel que rédigé (format WhatsApp)
    parsed: Mapped[dict | None] = mapped_column(JSON)  # sections reconnues (situation, évolution, risques, conseils)
    texts: Mapped[dict | None] = mapped_column(JSON)  # texte lu par langue : {fr, en, mos}
    status: Mapped[ContentStatus] = mapped_column(_enum(ContentStatus), default=ContentStatus.draft, index=True)
    image_path: Mapped[str | None] = mapped_column(String(255))
    media: Mapped[dict | None] = mapped_column(JSON)  # {fr: {audio, video}, en: {...}, mos: {...}} (chemins relatifs)
    media_status: Mapped[MediaStatus] = mapped_column(_enum(MediaStatus), default=MediaStatus.none)
    media_error: Mapped[str | None] = mapped_column(String(500))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlertZone(Base):
    __tablename__ = "alert_zones"
    __table_args__ = (UniqueConstraint("alert_id", "zone_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)


class Bulletin(Base):
    __tablename__ = "bulletins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    date_text: Mapped[str | None] = mapped_column(String(80))  # date telle qu'écrite dans le PDF
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[ContentStatus] = mapped_column(_enum(ContentStatus), default=ContentStatus.draft, index=True)
    pdf_path: Mapped[str | None] = mapped_column(String(255))
    parsed: Mapped[dict | None] = mapped_column(JSON)  # {observed, forecast, advice_intro, advice[]}
    texts: Mapped[dict | None] = mapped_column(JSON)  # {fr, en, mos}
    media: Mapped[dict | None] = mapped_column(JSON)
    media_status: Mapped[MediaStatus] = mapped_column(_enum(MediaStatus), default=MediaStatus.none)
    media_error: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class Advisory(Base):
    """Avis et conseils (F6.2) et avis de planification anticipée (F8.2)."""

    __tablename__ = "advisories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[AdvisoryKind] = mapped_column(_enum(AdvisoryKind), index=True)
    title_fr: Mapped[str] = mapped_column(String(200))
    title_en: Mapped[str | None] = mapped_column(String(200))
    title_mos: Mapped[str | None] = mapped_column(String(200))
    body_fr: Mapped[str] = mapped_column(Text)
    body_en: Mapped[str | None] = mapped_column(Text)
    body_mos: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(_enum(ContentStatus), default=ContentStatus.draft, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


# ------------------------------------------------------------------ appareils et diffusion
class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(512), unique=True)  # jeton FCM
    platform: Mapped[str] = mapped_column(String(10), default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_type: Mapped[str] = mapped_column(String(20), index=True)  # alert | bulletin | advisory
    content_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    trigger: Mapped[str] = mapped_column(String(10), default="manual")  # auto | manual
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String(500))


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broadcast_id: Mapped[str] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(10), index=True)  # sms | push | email | whatsapp
    recipient: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | simulated | failed
    error: Mapped[str | None] = mapped_column(String(300))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    content_type: Mapped[str] = mapped_column(String(20), index=True)
    content_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # view | play_audio | play_video | share
    language: Mapped[str | None] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
